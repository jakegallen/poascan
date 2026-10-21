"""Derived statistics. Every number comes from stored public snapshots; nothing is estimated silently."""
import json, time, statistics, collections, csv, os, datetime as dt
from . import db

_cache = {}
def cached(key, ttl=30):
    def deco(fn):
        def wrap(*a):
            k = (key,) + a
            hit = _cache.get(k)
            if hit and time.time() - hit[0] < ttl: return hit[1]
            v = fn(*a); _cache[k] = (time.time(), v); return v
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

@cached("epochs_raw", 60)
def epochs_raw():
    return db.get_blob("epochs")[0] or []

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

def open_epoch():
    rows = epoch_rows(); p = params(); st = status()
    closed = st.get("epochs_closed", len(rows))
    period = int(p.get("auto_epoch_seconds") or 21600)
    last_close = rows[-1]["close_ts"] if rows else None
    e0 = float(p.get("E0") or 1e9); halv = int(p.get("halving_epochs") or 720)
    pool = e0 / (2 ** (closed // halv))
    answers = db.q1("SELECT COUNT(*) AS n FROM txs WHERE type='challenge' AND ts > ?", (last_close or 0,))["n"] if last_close else None
    graders = db.q1("SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE type='grade-sealed' AND ts > ?", (last_close or 0,))["n"] if last_close else None
    return dict(epoch=closed, last_close=last_close, est_close=(last_close + period) if last_close else None,
                period=period, pool=pool, answers=answers, graders=graders)

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

def tps(window=3600):
    now = time.time()
    r = db.q1("SELECT COUNT(*) AS n, MIN(ts) AS a, MAX(ts) AS b FROM txs WHERE ts > ?", (now - window,))
    if not r["n"] or not r["a"] or r["b"] == r["a"]: return None
    return dict(n=r["n"], per_hour=r["n"] * 3600 / max(1, (now - max(r["a"], now - window))), tps=r["n"] / window)

def accounts_series():
    pts = []
    for s in db.q("SELECT ts, json FROM snaps WHERE kind='status' ORDER BY ts"):
        d = json.loads(s["json"]); pts.append((s["ts"], d.get("agents_joined"), d.get("holders"), float(d.get("supply") or 0), d.get("txs")))
    # downsample to one point per 15 minutes
    out = {}; 
    for p in pts: out[p[0] // 900] = p
    return list(out.values())

def joins_by_hour():
    return db.q("SELECT (ts/3600)*3600 AS h, COUNT(*) AS n FROM txs WHERE type='join' GROUP BY h ORDER BY h")

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
    if not live or now - live > LIVE_S: state, why = "stale", "No fresh read from minepoa.com"
    elif node_lag: state, why = "lag", f"minepoa node data {node_age // 60}m old"
    elif cp_lag: state, why = "lag", f"Checkpoint unchanged {cp_age // 3600}h"
    else: state, why = "live", "Live"
    return dict(state=state, label={"live": "Live", "lag": "Lagging", "stale": "Stale"}[state], why=why,
                fetched_at=live, node_age_s=node_age, node_stale=node_lag, checkpoint_moved=moved, checkpoint_age_s=cp_age, checkpoint_stalled=cp_lag)

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
