"""Derived statistics. Every number comes from stored public snapshots; nothing is estimated silently."""
import json, time, threading, statistics, collections, csv, os, re, datetime as dt
from . import db

_cache = collections.OrderedDict()   # (key, *args) -> (computed_at, value); LRU, bounded by CACHE_MAX
_inflight = {}                        # key -> Event while one thread recomputes it
_lock = threading.Lock()
CACHE_MAX = 256
_heavy = threading.BoundedSemaphore(int(os.environ.get("POASCAN_HEAVY_MAX", "2")))   # cold computes running at once
_depth = threading.local()

def cached(key, ttl=30):
    """TTL cache with single-flight: one thread recomputes an expired entry while the others get the stale
    value (or wait for the first compute). Concurrent requests never run the same heavy function at once."""
    def deco(fn):
        def wrap(*a):
            k = (key,) + a; own = True
            while True:
                with _lock:
                    hit = _cache.get(k)
                    if hit and time.time() - hit[0] < ttl:
                        _cache.move_to_end(k); return hit[1]
                    ev = _inflight.get(k)
                    if ev is None:
                        ev = _inflight[k] = threading.Event(); break
                if hit: return hit[1]          # someone is already refreshing it: serve the previous value
                if getattr(_depth, "n", 0):    # nested inside our own compute: never wait on another thread (no lock cycle)
                    own = False; ev = threading.Event(); break
                ev.wait(60)                    # first compute in progress: wait for it, then re-check
                with _lock:
                    hit = _cache.get(k)
                if hit: return hit[1]
            outer = not getattr(_depth, "n", 0)
            if outer: _heavy.acquire()        # nested cached calls run inside the outer slot (no self-deadlock)
            _depth.n = getattr(_depth, "n", 0) + 1
            try:
                v = fn(*a)
                with _lock:
                    _cache[k] = (time.time(), v); _cache.move_to_end(k)
                    while len(_cache) > CACHE_MAX: _cache.popitem(last=False)
                return v
            finally:
                _depth.n -= 1
                if outer: _heavy.release()
                if own:
                    with _lock: _inflight.pop(k, None)
                    ev.set()
        wrap.__wrapped__ = fn
        return wrap
    return deco

def gini(x):
    x = sorted(v for v in x if v is not None); n = len(x); s = sum(x)
    if not n or not s: return None
    return sum((2 * i - n - 1) * v for i, v in enumerate(x, 1)) / (n * s)

def status(): return db.get_blob("status")[0] or {}
def params(): return db.get_blob("params")[0] or {}
def networks():
    nw = db.get_blob("networks")[0] or {}
    for c in nw.get("chains", []):
        if c.get("chain_id") == "poa-mainnet-1": return c
    return {}

_epochs = {"ts": None, "v": []}
@cached("epochs_raw", 15)
def epochs_raw():
    """The epochs blob is ~11 MB of JSON (~40 MB parsed). Parse it only when the indexer stores a new copy."""
    r = db.q1("SELECT ts FROM blobs WHERE kind='epochs'")
    ts = r["ts"] if r else None
    if ts != _epochs["ts"]:
        _epochs["v"] = []; _epochs["ts"] = None          # drop the old copy before parsing the new one
        _epochs["v"] = db.get_blob("epochs")[0] or []; _epochs["ts"] = ts
    return _epochs["v"]

def epochs_count():
    return len(epochs_raw())

@cached("epoch_rows", 60)
def epoch_rows():
    out = []; prev = None; cum = 0.0
    for e in epochs_raw():
        b = e.get("basis", {}); r = [float(v) for v in e.get("rewards", {}).values()]
        pool = float(e.get("pool") or 0); m = sum(r); cum += m; t = int(e["ts"])
        pend = b.get("pending", {}) or {}
        kinds = collections.Counter(v.get("kind") for v in pend.values())
        by_origin = collections.Counter(int(v.get("since", 0)) for v in pend.values())
        st = b.get("settled", []) or []
        rs = sorted(r, reverse=True)
        out.append(dict(
            epoch=int(e["epoch"]), close_ts=t, gap_s=(t - prev) if prev else None, pool=pool, minted=m, burned=pool - m,
            burn_pct=(100 * (1 - m / pool)) if pool else None, cum_supply=cum, paid=len(r),
            challengers=len(e.get("challenges", {})), challenge_eligible=len(b.get("challenge_eligible", [])),
            attesters=len(b.get("attestations", {})), attestations=sum(b.get("attestations", {}).values()),
            median=statistics.median(r) if r else None, max=rs[0] if rs else None,
            top10_share=(sum(rs[:10]) / m) if m else None, gini=gini(r), distinct_amounts=len(set(r)),
            pending=len(pend), pending_short=kinds.get("short", 0), pending_appeal=kinds.get("appeal", 0),
            pending_empty_panel=sum(1 for v in pend.values() if not v.get("panel")),
            pending_by_origin=dict(sorted(by_origin.items())),
            settled=len(st), settled_passed=sum(1 for s in st if s.get("passed")),
            graders=len(b.get("graders_served", {})), grades=sum(b.get("graders_served", {}).values()),
            slashed=len(b.get("slashed", [])), established=len(b.get("established_after", [])),
            established_removed=len(b.get("established_removed", [])),
            audit_sampled=(b.get("audit") or {}).get("sampled"), audit_slashed=len((b.get("audit") or {}).get("slashed", [])),
            ceiling_capped=len((b.get("final_payout") or {}).get("capped", {})),
            referral_paid=len((b.get("referral2") or {}).get("paid", {})), propagation=len(e.get("propagation", {}))))
        prev = t
    return out

def epoch_detail(n):
    for e in epochs_raw():
        if int(e["epoch"]) == n: return e
    return None

AHEAD_MIN = 3   # distinct Agents whose answers carry the next epoch before that tag counts as the open epoch

def open_epoch():
    """The open epoch. Answers are tagged with the epoch they land in, so when the newest answers already carry the next
    number (a close our /api/status or /api/epochs read hasn't caught up with yet), that number is the open epoch.
    Its start is the previous close when we have that record, else the first answer tagged with it (start_estimated)."""
    rows = epoch_rows(); p = params(); st = status()
    closed = max(int(st.get("epochs_closed") or 0), (rows[-1]["epoch"] + 1) if rows else 0)
    period = int(p.get("auto_epoch_seconds") or 21600)
    nxt = db.q1("SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE type='challenge' AND epoch=? AND ts > ?", (closed + 1, int(time.time()) - period))
    ep = closed + 1 if nxt and nxt["n"] >= AHEAD_MIN else closed
    last_close, est = (rows[-1]["close_ts"] if rows else None), False
    if rows and rows[-1]["epoch"] != ep - 1:
        t0 = db.q1("SELECT MIN(ts) AS t FROM txs WHERE type='challenge' AND epoch=? AND ts > ?", (ep, int(time.time()) - 2 * period))["t"]
        if t0: last_close, est = t0, True
    closed = ep
    e0 = float(p.get("E0") or 1e9); halv = int(p.get("halving_epochs") or 720)
    pool = e0 / (2 ** (closed // halv))
    answers = db.q1("SELECT COUNT(*) AS n FROM txs WHERE type='challenge' AND ts > ?", (last_close or 0,))["n"] if last_close else None
    # graders: distinct senders of grade-sealed txs archived since the last close. Not the official count: that is
    # basis.graders_served, published per close (graders_served_last). Seals still land while grading is halted.
    graders = db.q1("SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE type='grade-sealed' AND ts > ?", (last_close or 0,))["n"] if last_close else None
    from . import maint as M
    gs = M.grading_state(); halt = gs["halt_notice"]
    return dict(epoch=closed, last_close=last_close, est_close=(last_close + period) if last_close else None,
                period=period, pool=pool, answers=answers, graders=graders, graders_basis="grade-sealed senders since the last close",
                graders_served_last=rows[-1].get("graders") if rows else None, grading_halted=gs["state"] == "halted" and gs["basis"] != "none", grading_halt_notice=halt,
                grading_state=gs["state"], grading_basis=gs["basis"], last_seal_at=gs.get("last_seal_at"),
                start_estimated=est)

HALT_ID_RX = re.compile(r"grading[-_ ]halt", re.I)
HALT_MSG_RX = re.compile(r"\bgrading\b[^.]{0,40}?\bhalted\b", re.I)
UNHALT_RX = re.compile(r"\b(?:no longer|unhalt\w*|resumed|lifted|reopened)\b", re.I)

def grading_halt(now=None):
    """Id of the active, unexpired notice in our /api/notices mirror that says challenge grading is halted, else None.
    A notice the official completion notice superseded (maint.superseded) no longer counts."""
    from . import maint as M
    d = db.get_blob("notices")[0]
    if not isinstance(d, dict): return None
    now = time.time() if now is None else now
    for x in d.get("active") or []:
        if not isinstance(x, dict) or M.superseded(x): continue
        exp = x.get("expires_ts")
        if isinstance(exp, (int, float)) and exp < now: continue
        nid, msg = str(x.get("id") or ""), str(x.get("msg") or "")
        if UNHALT_RX.search(msg): continue
        if HALT_ID_RX.search(nid) or HALT_MSG_RX.search(msg): return nid or "notice"
    return None

@cached("rewards_by_addr", 60)
def rewards_by_addr():
    out = collections.defaultdict(dict)
    for e in epochs_raw():
        for a, v in e.get("rewards", {}).items(): out[a][int(e["epoch"])] = float(v)
    return out

def vesting_split(rewards, open_ep, vest=100):
    """Each epoch k's reward unlocks 1/vest per epoch starting the next epoch (verified against /api/hosted/me)."""
    sp = sum(v * min(1.0, max(0, open_ep - k) / vest) for k, v in rewards.items())
    return sp, sum(rewards.values()) - sp

@cached("supply", 60)
def supply_split():
    vest = int(params().get("vesting_epochs") or 100); n = status().get("epochs_closed") or len(epoch_rows())
    sp = lk = 0.0
    for a, r in rewards_by_addr().items():
        s, l = vesting_split(r, n, vest); sp += s; lk += l
    return dict(spendable=sp, locked=lk, vesting_epochs=vest, open_epoch=n)

@cached("holders", 60)
def holders():
    acc = {r["addr"]: r for r in db.q("SELECT addr, balance, balance_s, invited_by FROM accounts")}
    rb = rewards_by_addr(); rows = []
    for a, r in acc.items():
        if r["balance"] and r["balance"] > 0:
            rows.append(dict(addr=a, balance=r["balance"], balance_s=r["balance_s"], src="/api/agents"))
    seen = {x["addr"] for x in rows}
    for a, r in rb.items():
        if a not in seen and sum(r.values()) > 0:
            rows.append(dict(addr=a, balance=sum(r.values()), balance_s=f"{sum(r.values()):.6f}", src="reward sum (not in /api/agents)"))
    rows.sort(key=lambda x: -x["balance"])
    tot = sum(x["balance"] for x in rows)
    for i, x in enumerate(rows, 1): x["rank"] = i; x["share"] = x["balance"] / tot if tot else 0
    bal = [x["balance"] for x in rows]
    cl = collections.Counter(round(b, 6) for b in bal).most_common(1)
    return dict(rows=rows, total=tot, count=len(rows), in_agents=len(seen), missing=len(rows) - len(seen),
                top10_share=sum(bal[:10]) / tot if tot else None, top1_share=bal[0] / tot if tot else None,
                gini=gini(bal), median=statistics.median(bal) if bal else None,
                cluster_balance=cl[0][0] if cl else None, cluster_count=cl[0][1] if cl else 0,
                cluster_share=(cl[0][1] / len(bal)) if bal else None)

@cached("established_set", 60)
def established_set():
    """Best public estimate of who is ESTABLISHED now (what hosted /me reports as established).

    Close records only publish changes: basis.established_after lists identities that became
    established at that close and basis.established_removed those that lost it. Standing carried
    in from testnet, and standing restored off-record, is never listed. So we fold the changes
    over every close and add identities that held a grading seat (graders_served or a settled
    jury) after their last removal and within estab_ttl closes, plus trusted/system graders.
    Seats go only to established identities (go.md), so a seat is evidence of standing."""
    ep = epochs_raw()
    if not ep: return set()
    pp = params(); ttl = int(pp.get("estab_ttl") or 6); last = int(ep[-1].get("epoch", len(ep) - 1))
    est, seat, removed = set(), {}, {}
    for e in sorted(ep, key=lambda r: int(r.get("epoch", 0))):
        n = int(e.get("epoch", 0)); b = e.get("basis", {}) or {}
        seated = set(b.get("graders_served", {}) or {})
        seated |= {j.get("grader") for s in (b.get("settled") or []) for j in (s.get("jury") or []) if j.get("grader")}
        for a in seated: seat[a] = n
        gone = set(b.get("established_removed", []) or [])
        for a in gone: removed[a] = n
        est = (est - gone) | set(b.get("established_after", []) or [])
    est |= {a for a, n in seat.items() if n > removed.get(a, -1) and n > last - ttl}
    est |= set(pp.get("trusted_graders") or []) | set(pp.get("system_grader_accounts") or [])
    return est

STANDING_NOTE = ("Estimate from observed behavior, not an official rule: established standing has dropped at close L + estab_ttl + 1 "
                 "(L + 7 with estab_ttl 6), where L is the Agent's last challenge_eligible epoch. It fits all 57 removals at the E8 to E10 closes. "
                 "Grading seats don't refresh standing. Hosted /me is the authority.")

@cached("last_eligible", 300)
def last_eligible():
    """addr -> the latest epoch whose close record lists it in basis.challenge_eligible."""
    out = {}
    for e in epochs_raw():
        n = int(e.get("epoch", -1))
        for a in (e.get("basis") or {}).get("challenge_eligible") or []:
            if n > out.get(a, -1): out[a] = n
    return out

def established_expiry_est(a):
    """When an established Agent's standing is expected to drop, under the observed rule in STANDING_NOTE (an estimate).
    established_expires_epoch_est is the close (epoch number) and established_expires_basis says how; both are None when
    unknown: not established, a trusted or system grader, no challenge_eligible epoch on record (standing from a seat,
    testnet or off record), or the estimated close already passed while the Agent still reads established."""
    L = last_eligible().get(a)
    out = dict(established_expires_epoch_est=None, established_expires_basis=None, last_challenge_eligible_epoch=L)
    pp = params()
    if L is None or a not in established_set() or a in set(pp.get("trusted_graders") or []) | set(pp.get("system_grader_accounts") or []): return out
    ttl = int(pp.get("estab_ttl") or 6); n = L + ttl + 1; cur = open_epoch().get("epoch")
    if cur is None or n < cur: return out
    out.update(established_expires_epoch_est=n,
               established_expires_basis=f"observed estimate, not an official rule: last challenge_eligible epoch {L} + estab_ttl {ttl} + 1")
    return out

def established_expiry_counts():
    """How many Agents show an estimated expiry now, and the soonest close (for the release check and tests)."""
    xs = [established_expiry_est(a)["established_expires_epoch_est"] for a in established_set()]
    xs = [x for x in xs if x is not None]
    return dict(with_estimate=len(xs), soonest=min(xs) if xs else None)

@cached("forum_names", 300)
def forum_names():
    m = {}
    for r in db.q("SELECT author, author_public_id FROM forum_posts UNION ALL SELECT author, author_public_id FROM forum_comments"):
        if r["author_public_id"]: m[r["author_public_id"]] = r["author"]
    return m

def utc_to_ts(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp())

@cached("forum", 120)
def forum():
    comms = db.get_blob("communities")[0] or []
    posts = db.q("SELECT * FROM forum_posts"); cmts = db.q("SELECT c.*, p.community FROM forum_comments c JOIN forum_posts p ON p.id=c.post_id")
    live = [p for p in posts if p["community"] != "poa-archive"]; lc = [c for c in cmts if c["community"] != "poa-archive"]
    pa = {p["author_public_id"] for p in live}; ca = {c["author_public_id"] for c in lc}
    day = collections.defaultdict(lambda: [0, 0])
    for p in live: day[dt.datetime.fromtimestamp(utc_to_ts(p["created_at"]), dt.timezone.utc).date().isoformat()][0] += 1
    for c in lc: day[dt.datetime.fromtimestamp(utc_to_ts(c["created_at"]), dt.timezone.utc).date().isoformat()][1] += 1
    per = []
    for c in comms:
        per.append(dict(slug=c["slug"], name=c.get("name"), archived=int(c.get("archived") or 0), created_at=c.get("created_at"),
                        posts=sum(1 for p in posts if p["community"] == c["slug"]), comments=sum(1 for x in cmts if x["community"] == c["slug"])))
    au = collections.Counter(p["author"] for p in live) + collections.Counter(c["author"] for c in lc)
    tot_items = sum(au.values())
    now = time.time()
    last24 = sum(1 for p in live if now - utc_to_ts(p["created_at"]) < 86400) + sum(1 for c in lc if now - utc_to_ts(c["created_at"]) < 86400)
    return dict(communities=len(comms), active_communities=sum(1 for c in comms if not int(c.get("archived") or 0)),
                posts=len(live), comments=len(lc), replies=sum(1 for c in lc if c["parent_id"]), deleted=sum(1 for p in posts if p["deleted"]),
                archive_posts=len(posts) - len(live), archive_comments=len(cmts) - len(lc),
                posters=len(pa), commenters=len(ca), participants=len(pa | ca),
                post_score=sum(p["score"] for p in live), comment_score=sum(c["score"] for c in lc),
                per_community=per, by_day=sorted((k, v[0], v[1]) for k, v in day.items()),
                top_threads=sorted(live, key=lambda p: -(p["comment_count"] or 0))[:10],
                top_authors=au.most_common(10), top10_share=(sum(v for _, v in au.most_common(10)) / tot_items) if tot_items else None,
                last24=last24)

@cached("census", 3600)
def census():
    p = os.path.join(os.path.dirname(__file__), "..", "data", "census.csv")
    if not os.path.exists(p): return None
    rows = list(csv.DictReader(open(p)))
    return dict(n=len(rows), ecosystem=collections.Counter(r["ecosystem"] for r in rows).most_common(),
                harness=collections.Counter(r["harness"] for r in rows).most_common(),
                web=sum(1 for r in rows if r["label"] == "web"))

@cached("sybil", 120)
def sybil():
    a = db.q("SELECT * FROM answers")
    n = len(a)
    fam = collections.Counter(x["prefix4"] for x in a if x["prefix4"])
    in_fam = sum(v for v in fam.values() if v >= 2)
    inv = db.q("SELECT invited_by, COUNT(*) AS n FROM accounts WHERE invited_by IS NOT NULL GROUP BY invited_by ORDER BY n DESC LIMIT 5")
    inv_total = db.q1("SELECT COUNT(*) AS n, COUNT(DISTINCT invited_by) AS k FROM accounts WHERE invited_by IS NOT NULL")
    chains = db.get_blob("chains")[0] or {}
    ext = collections.defaultdict(list)
    for poa, links in chains.items():
        for ch, v in (links or {}).items():
            if v.get("addr"): ext[(ch, v["addr"])].append(poa)
    shared = [(k[0], k[1], v) for k, v in ext.items() if len(v) > 1]
    anchors = db.q("SELECT DISTINCT chain, anchored_by FROM anchors")
    anchor_wallets = {r["anchored_by"] for r in anchors}
    anchor_linked = sorted({p for (ch, addr), v in ext.items() if addr in anchor_wallets for p in v})
    rb = rewards_by_addr()
    ep = epoch_rows(); last = ep[-1] if ep else None
    return dict(sampled=n, slot=sum(x["slot_template"] for x in a), echo=sum(x["prompt_echo"] for x in a),
                families_members=in_fam, families=sum(1 for v in fam.values() if v >= 2),
                first=min((x["sampled_at"] for x in a), default=None), last=max((x["sampled_at"] for x in a), default=None),
                inviters=inv, invited=inv_total["n"], inviter_count=inv_total["k"], shared_ext=shared,
                anchor_linked=[(p, sum(rb.get(p, {}).values())) for p in anchor_linked],
                last_epoch_capped=(last["ceiling_capped"], last["paid"]) if last else None,
                web_labels=(census() or {}).get("web"))

def tx_counts():
    r = db.q1("SELECT COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last, MIN(first_seen) AS since FROM txs")
    r["by_type"] = db.q("SELECT type, COUNT(*) AS n FROM txs GROUP BY type ORDER BY n DESC")
    r["invalid"] = db.q1("SELECT COUNT(*) AS n FROM invalid_txs")["n"]
    return r

def accounts_series():
    pts = []
    for s in db.q("SELECT ts, json FROM snaps WHERE kind='status' ORDER BY ts"):
        d = json.loads(s["json"]); pts.append((s["ts"], d.get("agents_joined"), d.get("holders"), float(d.get("supply") or 0), d.get("txs")))
    # downsample to one point per 15 minutes
    out = {}; 
    for p in pts: out[p[0] // 900] = p
    return list(out.values())

def health():
    fl = db.q("SELECT * FROM fetch_log ORDER BY endpoint")
    jobs = {r["kind"][4:]: json.loads(r["json"]).get("ran") for r in db.q("SELECT kind, json FROM blobs WHERE kind LIKE 'job:%'")}
    live = db.q1("SELECT last_ok FROM fetch_log WHERE endpoint='/api/explorer/txs'")
    return dict(endpoints=fl, jobs=jobs, live_last_ok=live["last_ok"] if live else None)

# ---- freshness: one state for the header pill, /api/live and /status
LIVE_S = 300            # our own last good read of the live feed
LAG_NODE_S = 600        # minepoa's node snapshot flagged stale and at least this old
LAG_CP_S = 6 * 3600     # checkpoint height unchanged this long

def _ts(iso):
    try: return int(dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp())
    except Exception: return None

@cached("cp_moved", 60)
def cp_moved():
    """When the checkpoint height last changed, from our own status snapshots (3-day window)."""
    cur = status().get("checkpoint_height")
    if not cur: return None
    since = int(time.time()) - 3 * 86400; ex = "CAST(json_extract(json, '$.checkpoint_height') AS INTEGER)"
    r = db.q1(f"SELECT MAX(ts) AS t FROM snaps WHERE kind='status' AND ts > ? AND {ex} IS NOT NULL AND {ex} != ?", (since, int(cur)))
    r = db.q1(f"SELECT MIN(ts) AS t FROM snaps WHERE kind='status' AND ts > ? AND {ex} = ?", (r["t"] or since, int(cur)))
    return r["t"]

@cached("freshness", 15)
def freshness():
    """live: our live fetch is current. lag: it is, but minepoa's node is stale or its checkpoint stalled. stale: our fetch failed."""
    now = time.time(); st = status(); live = health().get("live_last_ok")
    node_t = _ts(st.get("as_of")); node_age = int(now - node_t) if node_t else None
    node_lag = bool(st.get("stale")) and (node_age or 0) >= LAG_NODE_S
    moved = cp_moved(); cp_age = int(now - moved) if moved else None
    cp_lag = cp_age is not None and cp_age >= LAG_CP_S
    from . import maint as M
    up = M.state()["active"]
    if not live or now - live > LIVE_S: state, why = "stale", "No fresh read from minepoa.com"
    elif node_lag: state, why = "lag", f"minepoa node data {node_age // 60}m old"
    elif up: state, why = "up", ("Network upgrade: " + M.state()["headline"]) if M.recovery()["moved"] else "Network upgrade: hosted mining paused, finalized height parked on purpose"
    elif cp_lag: state, why = "lag", f"Finalized height unchanged {cp_age // 3600}h"
    else: state, why = "live", "Live"
    return dict(state=state, label={"live": "Live", "lag": "Lagging", "stale": "Stale", "up": "Upgrading"}[state], why=why,
                href="/upgrade" if state == "up" else "/network?tab=health", maintenance=up,
                fetched_at=live, node_age_s=node_age, node_stale=node_lag, checkpoint_moved=moved, checkpoint_age_s=cp_age, checkpoint_stalled=cp_lag and not up)

def anchors_latest(n=20):
    return db.q("SELECT * FROM anchors ORDER BY height DESC, chain LIMIT ?", (n,))

def anchor_summary():
    r = db.q1("SELECT COUNT(DISTINCT height) AS heights, COUNT(*) AS n, MAX(height) AS top, MAX(anchored_at) AS last, MIN(anchored_at) AS first FROM anchors")
    r["signers"] = db.q("SELECT DISTINCT chain, anchored_by FROM anchors")
    r["sigs"] = db.q("SELECT substr(memo, instr(memo,':sigs')+1) AS s, COUNT(*) AS n FROM anchors GROUP BY s")
    return r

MIN_ACTIVITY_EPOCHS = 1  # an Agent paid in at most this many epochs counts as min-activity

@cached("concentration", 60)
def concentration():
    """Share of supply held by the top 1/5/10/20 holders, Gini, and min-activity Agents (paid in <= 1 epoch)."""
    h = holders(); rows = h["rows"]; tot = h["total"] or 0; bal = [r["balance"] for r in rows]
    rb = rewards_by_addr()
    low = [r for r in rows if len([v for v in rb.get(r["addr"], {}).values() if v > 0]) <= MIN_ACTIVITY_EPOCHS]
    top = {f"top{n}_share": (sum(bal[:n]) / tot if tot else None) for n in (1, 5, 10, 20)}
    return dict(holders=len(rows), total_balance=tot, **top, gini=h["gini"], median_balance=h["median"],
                min_activity=dict(agents=len(low), share_of_holders=(len(low) / len(rows)) if rows else None,
                                  share_of_supply=(sum(r["balance"] for r in low) / tot) if tot else None,
                                  definition=f"holders paid in at most {MIN_ACTIVITY_EPOCHS} epoch"))

@cached("pending_by_epoch", 60)
def pending_by_epoch():
    """Pending answers grouped by the epoch they were submitted in, oldest first.
    Carried-forward: basis.pending of the latest close record (ungraded or unresolved answers, keyed by answer txid, with `since` = origin epoch).
    Current: answers (challenge txs) archived since the last close; none is graded until the next close."""
    raw = epochs_raw(); o = open_epoch(); cur = o["epoch"]; now = time.time()
    last = raw[-1] if raw else {}; pend = (last.get("basis") or {}).get("pending", {}) or {}
    starts = {}
    for i, e in enumerate(raw): starts[int(e["epoch"]) + 1] = int(e["ts"])      # epoch k opens when k-1 closes
    groups = collections.defaultdict(lambda: dict(n=0, short=0, appeal=0, ids=[]))
    for tid, v in pend.items():
        g = groups[int(v.get("since", 0))]; g["n"] += 1; g["ids"].append(tid)
        if v.get("kind") in ("short", "appeal"): g[v["kind"]] += 1
    rows = []
    if raw and 0 not in starts:
        g0 = db.q1("SELECT MIN(ts) AS t FROM txs WHERE type='genesis-identity'"); starts[0] = g0["t"] if g0 and g0["t"] else None
    def ts_of(ids):  # exact only when every pending answer of the group is in the archive
        best = None; seen = 0
        for i in range(0, len(ids), 500):
            ch = ids[i:i + 500]
            r = db.q1(f"SELECT MIN(ts) AS t, COUNT(*) AS n FROM txs WHERE id IN ({','.join('?' * len(ch))})", tuple(ch))
            seen += r["n"] or 0
            if r["t"] and (best is None or r["t"] < best): best = r["t"]
        return best if seen == len(ids) else None
    for ep in sorted(groups):
        g = groups[ep]; t = ts_of(g["ids"]); approx = t is None
        if approx: t = starts.get(ep)
        rows.append(dict(epoch=ep, pending=g["n"], short_panel=g["short"], appeal=g["appeal"], oldest_ts=t, oldest_age_s=int(now - t) if t else None,
                         oldest_approx=approx, stale=ep < cur, source="close"))
    if o["last_close"]:
        r = db.q1("SELECT COUNT(*) AS n, MIN(ts) AS t FROM txs WHERE type='challenge' AND ts > ?", (o["last_close"],))
        if r["n"]:
            rows = [x for x in rows if x["epoch"] != cur]
            rows.append(dict(epoch=cur, pending=r["n"], short_panel=None, appeal=None, oldest_ts=r["t"], oldest_age_s=int(now - r["t"]),
                             oldest_approx=False, stale=False, source="open"))
    pr = params(); ttl = pr.get("pending_ttl_epochs"); period = int(pr.get("auto_epoch_seconds") or 21600)
    bl = backlog(); lc = bl["closes"][-1] if bl["closes"] else None
    for x in rows:
        ep = x["epoch"]; h = bl["hist"].get(ep) if x["source"] == "close" else None
        x["seals"] = h; x["seals_exact"] = bl["exact"] if h else None
        x["grew"] = lc["grew_by_epoch"].get(ep, 0) if lc and x["source"] == "close" else None
        x["dropped"] = lc["dropped_by_epoch"].get(ep, 0) if lc and x["source"] == "close" else None
        x["expires_close"] = ep + int(ttl) if ttl is not None else None
        x["expires_est_ts"] = int(last["ts"]) + (x["expires_close"] - int(last["epoch"])) * period if last and x["expires_close"] is not None else None
    tot = collections.Counter()
    for h in bl["hist"].values(): tot.update(h)
    return dict(current_epoch=cur, as_of_close=int(last["epoch"]) if last else None, total=sum(x["pending"] for x in rows),
                stale_total=sum(x["pending"] for x in rows if x["stale"]), ttl_epochs=ttl, merge_from_epoch=bl["merge_from"],
                quorum=pr.get("grade_quorum"), epoch_seconds=period, seals_basis=bl["basis"], seals_exact=bl["exact"],
                seals_total={k: tot.get(k, 0) for k in SEAL_KEYS} if bl["hist"] else None,
                last_close=lc, closes=bl["closes"], rows=rows)

SEAL_KEYS = ("0", "1", "2", "3", "4+", "unknown")

def _seals(v, close, merge):
    """Distinct graders on a pending row at a close, and whether that count is exact.
    From pending_merge_from_epoch on, rows carry grades (the live seal list): exact.
    Before it, a short row's panel listed the seals the close counted, which missed some accepted seals: lower bound.
    Appeal panels before the merge are drawn seats, not seals: unknown."""
    if "grades" in v: return len({g.get("grader") for g in v.get("grades") or []}), True
    if merge is not None and close < merge and v.get("kind") == "short": return len(v.get("panel") or []), False
    return None, False

@cached("backlog", 60)
def backlog():
    """Per close: settlement origin, rows that grew without settling, silent drops; plus the seal histogram of the latest close."""
    raw = epochs_raw(); mf = params().get("pending_merge_from_epoch"); mf = int(mf) if mf is not None else None
    closes = []; prev = None
    for e in raw:
        n = int(e["epoch"]); b = e.get("basis") or {}; pend = b.get("pending") or {}
        st = [x.get("answer") for x in b.get("settled") or [] if x.get("answer")]
        if prev is not None:
            pn, pp = prev; sset = set(st); org = collections.Counter(); grew = collections.Counter(); drop = collections.Counter(); unk = 0
            miss = [t for t in st if t not in pp]
            tep = {}
            for i in range(0, len(miss), 500):
                ch = miss[i:i + 500]
                for r in db.q(f"SELECT id, epoch FROM txs WHERE id IN ({','.join('?' * len(ch))})", tuple(ch)): tep[r["id"]] = r["epoch"]
            for t in st: org[pp[t].get("since") if t in pp else tep.get(t, "unknown")] += 1
            for t, v in pend.items():
                if t not in pp: continue
                a, _ = _seals(pp[t], pn, mf); c, _ = _seals(v, n, mf)
                if a is None or c is None: unk += 1
                elif c > a: grew[int(v.get("since", 0))] += 1
            for t, v in pp.items():
                if t not in pend and t not in sset: drop[int(v.get("since", 0))] += 1
            closes.append(dict(close=n, settled=len(st), settled_by_origin=[dict(epoch=k, count=org[k]) for k in sorted(org, key=lambda k: (isinstance(k, str), k))],
                               carried=sum(1 for t in pend if t in pp), grew=sum(grew.values()), grew_unknown=unk, dropped=sum(drop.values()),
                               grew_by_epoch=dict(grew), dropped_by_epoch=dict(drop)))
        prev = (n, pend)
    hist = {}; exact = None; basis = None
    if raw:
        n = int(raw[-1]["epoch"]); ex = []
        for v in ((raw[-1].get("basis") or {}).get("pending") or {}).values():
            c, x = _seals(v, n, mf); ep = int(v.get("since", 0)); h = hist.setdefault(ep, {k: 0 for k in SEAL_KEYS})
            h["unknown" if c is None else "4+" if c >= 4 else str(c)] += 1
            if c is not None: ex.append(x)
        exact = all(ex) if ex else None; basis = "grades" if mf is not None and n >= mf else "panel"
    return dict(closes=closes, hist=hist, exact=exact, basis=basis, merge_from=mf)

# ---- Agents / hr: joins per hour from our own /api/status snapshots (agents_joined), no upstream call ----
JOIN_RATE_WINDOW_S = 86400     # default window: trailing 24 h
JOIN_PAUSE_S = 2 * 3600        # agents_joined flat this long reads as joining paused, not a slow spell
JOIN_MIN_S = 3600              # never report over less than an hour

def _join_points(since):
    return [(r["ts"], int(r["a"])) for r in db.q(
        "SELECT ts, json_extract(json, '$.agents_joined') AS a FROM snaps WHERE kind='status' AND ts >= ? ORDER BY ts", (since,)) if r["a"]]

def _rate_since(pts, t0):
    """Joins per hour from the last read at or before t0 (else the first read after it) to the newest read."""
    if len(pts) < 2: return None
    base = next((p for p in reversed(pts) if p[0] <= t0), pts[0]); end = pts[-1]
    h = (end[0] - base[0]) / 3600
    return dict(joins=max(0, end[1] - base[1]), hours=round(h, 2), per_hour=round(max(0, end[1] - base[1]) / h, 1) if h > 0 else None)

def joins_rate_calc(pts, now=None):
    """Pure: the homepage Agents / hr from (ts, agents_joined) reads, oldest first.
    Default: joins over the trailing 24 h divided by its hours. If agents_joined stood still for JOIN_PAUSE_S or more inside
    that window (joining paused, e.g. a network upgrade), the window starts where the latest pause ended, so a pause does not
    drag the rate toward zero; it stays at least JOIN_MIN_S long."""
    if len(pts) < 2: return None
    end = pts[-1][0]; t0 = end - JOIN_RATE_WINDOW_S
    win = [p for p in pts if p[0] >= t0]
    start = t0; paused_until = None
    i = 0
    while i < len(win):            # runs of equal counts: first read to the last read before the count moved
        j = i
        while j + 1 < len(win) and win[j + 1][1] == win[i][1]: j += 1
        if j + 1 < len(win) and win[j][0] - win[i][0] >= JOIN_PAUSE_S: paused_until = win[j][0]   # an ended pause (an ongoing one keeps 24 h)
        i = j + 1
    if paused_until is not None: start = min(paused_until, end - JOIN_MIN_S)
    r = _rate_since(pts, start)
    if not r or r["per_hour"] is None: return None
    trailing = {k: _rate_since(pts, end - s) for k, s in (("1h", 3600), ("6h", 6 * 3600), ("24h", 86400))}
    return dict(agent_joins_per_hour=int(round(r["per_hour"])), joins=r["joins"], window_hours=r["hours"],
                window="since_pause" if paused_until is not None else "24h", window_end=end, paused_until=paused_until,
                trailing={k: (v["per_hour"] if v else None) for k, v in trailing.items()})

@cached("joins_rate", 120)
def joins_rate():
    """Cached 2 min: one indexed range read of about a day of status snapshots."""
    now = int(time.time())
    return joins_rate_calc(_join_points(now - JOIN_RATE_WINDOW_S - 3 * 3600), now)
