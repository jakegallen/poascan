"""Derived statistics. Every number comes from stored public snapshots; nothing is estimated silently."""
import json, time, threading, statistics, collections, csv, os, re, datetime as dt
from . import db, segments as S

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
            k = (key, S.selected()) + a; own = True   # every cached value is per segment (segments.py)
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

_epochs = {}   # segment -> {"ts", "v"}
@cached("epochs_raw", 15)
def epochs_raw():
    """The selected segment's close records (segments.py: one blob per segment; segment 1's is ~21 MB of JSON).
    Each is parsed only when the indexer stores a new copy."""
    kind = S.blob_kind(); c = _epochs.setdefault(kind, {"ts": None, "v": []})
    r = db.q1("SELECT ts FROM blobs WHERE kind=?", (kind,))
    ts = r["ts"] if r else None
    if ts != c["ts"]:
        c["v"] = []; c["ts"] = None          # drop the old copy before parsing the new one
        c["v"] = db.get_blob(kind)[0] or []; c["ts"] = ts
    return c["v"]

def epochs_ts():
    """When the selected segment's close records were stored (blobs.ts), or None."""
    try: r = db.q1("SELECT ts FROM blobs WHERE kind=?", (S.blob_kind(),))
    except Exception: return None   # a database not yet initialised (tools that read before db.init)
    return r["ts"] if r else None

def segment_closes(n):
    """Close records of segment n, whatever segment this thread reads."""
    with S.use(n): return epochs_raw()

@cached("segment_minted", 300)
def segment_minted():
    """Sum of every reward in the selected segment's close records."""
    return sum(float(v) for e in epochs_raw() for v in (e.get("rewards") or {}).values())

@cached("segment_carried", 300)
def segment_carried():
    """1.26.122: rewards of the selected segment's closes that later balances carry: segment_minted() minus closes in
    segments config unconfirmed_closes or a cut's excluded_closes (segments.unconfirmed)."""
    seg = S.selected()
    return sum(float(v) for e in epochs_raw() if not S.unconfirmed(int(e.get("epoch", 0)), seg) for v in (e.get("rewards") or {}).values())

def minted_before():
    """Rewards carried from every segment before the selected one (cum_supply starts there). 1.26.122: closes excluded at a
    cut are not carried, so segment 2's E0 starts at the carried supply, not at every reward segment 1 recorded."""
    out = 0.0
    for n in S.NUMBERS:
        if n >= S.selected(): break
        with S.use(n): out += segment_carried()
    return out

# 1.26.89: from the E14 close minepoa's pending rows carry no "since" (origin epoch); before, every row had it. Reading a
# missing since as 0 put E14's 1,252 new answers under E0 (stale, expiring at close 16). since_of() fills it from POAScan's
# archived challenge tx epoch, else the first close the answer sat in. The raw blob is never changed (close records hash it).
_sf = {"ts": None, "v": {}}
def since_fill():
    """{answer id: origin epoch} for pending rows without since, rebuilt only when a new epochs blob lands."""
    ts = (S.selected(), epochs_ts())
    if ts[1] is not None and ts == _sf["ts"]: return _sf["v"]
    first = {}
    for e in epochs_raw():
        n = int(e.get("epoch", 0))
        for t, v in ((e.get("basis") or {}).get("pending") or {}).items():
            if isinstance(v, dict) and v.get("since") is None and (t not in first or n < first[t]): first[t] = n
    out, ids = {}, list(first)
    for i in range(0, len(ids), 500):
        ch = ids[i:i + 500]
        for row in db.q(f"SELECT id, epoch FROM txs WHERE id IN ({','.join('?' * len(ch))})", tuple(ch)):
            if row["epoch"] is not None: out[row["id"]] = int(row["epoch"])
    for t, n in first.items(): out.setdefault(t, n)
    _sf["v"] = out; _sf["ts"] = ts
    return out

def since_of(tid, v):
    """A pending row's origin epoch: its own since, else since_fill()."""
    s = v.get("since") if isinstance(v, dict) else None
    if s is not None: return int(s)
    return since_fill().get(tid, 0)

def epochs_count():
    return len(epochs_raw())

def grade_counts(e, prev_ts=None):
    """grader -> grades at one close, counted from its grade rows: every settled jury seat plus every pending grade
    sealed inside this epoch (prev close < ts <= this close). basis.graders_served undercounts (E12: it names 16
    graders and 79 grades; the rows hold 63 graders and 1,570 grades), so it is kept only as the *_official fields."""
    b = e.get("basis", {}) or {}; t1 = int(e.get("ts") or 0); c = collections.Counter()
    for s in b.get("settled") or []:
        for j in s.get("jury") or []:
            if j.get("grader"): c[j["grader"]] += 1
    for v in (b.get("pending") or {}).values():
        for g in (v.get("grades") or []) if isinstance(v, dict) else []:
            ts = g.get("ts") if isinstance(g, dict) else None
            if isinstance(g, dict) and g.get("grader") and isinstance(ts, (int, float)) and (prev_ts is None or ts > prev_ts) and (not t1 or ts <= t1): c[g["grader"]] += 1
    return c

@cached("epoch_rows", 60)
def epoch_rows():
    """One row per close of the selected segment. cum_supply continues from earlier segments (balances carried over)."""
    out = []; prev = None; cum = cumc = minted_before(); pprev = None; seg = S.selected()
    for e in epochs_raw():
        b = e.get("basis", {}); r = [float(v) for v in e.get("rewards", {}).values()]
        unc = S.unconfirmed(int(e["epoch"]), seg)
        pool = float(e.get("pool") or 0); m = sum(r); cum += m; cumc += 0.0 if unc else m; t = int(e["ts"])
        pend = b.get("pending", {}) or {}
        kinds = collections.Counter(v.get("kind") for v in pend.values())
        by_origin = collections.Counter(since_of(t, v) for t, v in pend.items())
        st = b.get("settled", []) or []
        # Dropped at close: in the previous close's pending, in neither this close's pending nor its settled list. Not
        # settled, graded or rejected; null for the first close (nothing to compare).
        sids = {s.get("answer") for s in st if s.get("answer")}
        dropped = None if pprev is None else sum(1 for t in pprev if t not in pend and t not in sids)
        pprev = pend
        rs = sorted(r, reverse=True)
        out.append(dict(
            epoch=int(e["epoch"]), close_ts=t, gap_s=(t - prev) if prev else None, pool=pool, minted=m, burned=pool - m,
            rewards_state="unconfirmed" if unc else "recorded",
            burn_pct=(100 * (1 - m / pool)) if pool else None, cum_supply=cum, cum_supply_confirmed=cumc, paid=len(r),
            challengers=len(e.get("challenges", {})), challenge_eligible=len(b.get("challenge_eligible", [])),
            attesters=len(b.get("attestations", {})), attestations=sum(b.get("attestations", {}).values()),
            median=statistics.median(r) if r else None, max=rs[0] if rs else None,
            top10_share=(sum(rs[:10]) / m) if m else None, gini=gini(r), distinct_amounts=len(set(r)),
            pending=len(pend), pending_short=kinds.get("short", 0), pending_appeal=kinds.get("appeal", 0),
            pending_empty_panel=sum(1 for v in pend.values() if not v.get("panel")),
            pending_by_origin=dict(sorted(by_origin.items())),
            settled=len(st), settled_passed=sum(1 for s in st if s.get("passed")), dropped=dropped,
            graders=len(gc := grade_counts(e, prev)), grades=sum(gc.values()),
            graders_official=len(b.get("graders_served", {}) or {}), grades_official=sum((b.get("graders_served", {}) or {}).values()),
            slashed=len(b.get("slashed", [])), established=len(b.get("established_after", [])),
            established_removed=len(b.get("established_removed", [])),
            audit_sampled=(b.get("audit") or {}).get("sampled"), audit_slashed=len((b.get("audit") or {}).get("slashed", [])),
            ceiling_capped=len((b.get("final_payout") or {}).get("capped", {})),
            paid_at_max=sum(1 for v in r if rs and round(v, 6) == round(rs[0], 6)) if r else 0,   # from the rewards row, not final_payout (E12: 152 at the top tier, 210 capped)
            referral_paid=len((b.get("referral2") or {}).get("paid", {})), propagation=len(e.get("propagation", {})), segment=seg))
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
    with S.use(S.CURRENT): return _open_epoch()

def _open_epoch():
    rows = epoch_rows(); p = params(); st = status()
    closed = max(int(st.get("epochs_closed") or 0), (rows[-1]["epoch"] + 1) if rows else 0)
    period = int(p.get("auto_epoch_seconds") or 21600)
    nxt = db.q1("SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE type='challenge' AND epoch=? AND ts > ?", (closed + 1, int(time.time()) - period))
    ep = closed + 1 if nxt and nxt["n"] >= AHEAD_MIN else closed
    last_close, est = (rows[-1]["close_ts"] if rows else None), False
    seg0 = S.BY_N[S.CURRENT].get("start_ts")
    if not rows and seg0 and S.has_cut(): last_close, est = seg0, True   # a new segment's first epoch opens at the cut
    if rows and rows[-1]["epoch"] != ep - 1:
        t0 = db.q1("SELECT MIN(ts) AS t FROM txs WHERE type='challenge' AND epoch=? AND ts > ?", (ep, int(time.time()) - 2 * period))["t"]
        if t0: last_close, est = t0, True
    closed = ep
    e0 = float(p.get("E0") or 1e9); halv = int(p.get("halving_epochs") or 720)
    pool = e0 / (2 ** (closed // halv))
    answers = db.q1("SELECT COUNT(*) AS n FROM txs WHERE type='challenge' AND ts > ?", (last_close or 0,))["n"] if last_close else None
    # graders: distinct senders of grade-sealed txs archived since the last close. graders_served_last is the last
    # close's count from its grade rows (settled juries plus pending grades in that epoch); basis.graders_served,
    # which undercounts, is graders_served_last_official. Seals still land while grading is halted, so when
    # the completion notice reopened grading inside this epoch only seals since the notice count (graders_reopened_at);
    # graders_epoch keeps every sealer since the close.
    from . import maint as M
    gs = M.grading_state(); halt = gs["halt_notice"]
    nq = lambda t: db.q1("SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE type='grade-sealed' AND ts > ?", (t,))["n"]
    graders_epoch = nq(last_close) if last_close else None
    na = gs.get("notice_at"); reopened = na if (last_close and na and na > last_close and gs["state"] != "halted") else None
    graders = nq(reopened - 1) if reopened else graders_epoch
    return dict(epoch=closed, last_close=last_close, est_close=(last_close + period) if last_close else None,
                period=period, pool=pool, answers=answers, graders=graders,
                graders_basis="grade-sealed senders since grading reopened" if reopened else "grade-sealed senders since the last close",
                graders_epoch=graders_epoch, graders_reopened_at=reopened,
                graders_served_last=rows[-1].get("graders") if rows else None, graders_served_last_official=rows[-1].get("graders_official") if rows else None, graders_served_last_epoch=rows[-1]["epoch"] if rows else None, grading_halted=gs["state"] == "halted" and gs["basis"] != "none", grading_halt_notice=halt,
                grading_state=gs["state"], grading_basis=gs["basis"], last_seal_at=gs.get("last_seal_at"),
                start_estimated=est, segment=S.CURRENT)

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
    """addr -> {lifetime close number: reward} over every segment (segments.gkey: segment 1's E0 to E14 are 0 to 14,
    segment 2's E0 is 15). Lifetime totals, vesting and streaks span the cut; segments.split_gkey gives (segment, epoch)."""
    out = collections.defaultdict(dict)
    for n in S.NUMBERS:
        for e in segment_closes(n):
            for a, v in e.get("rewards", {}).items(): out[a][S.gkey(e["epoch"], n)] = float(v)
    return out

def rewards_in_segment(rb, n=None):
    """{epoch: reward} of one segment from a rewards_by_addr() entry."""
    n = n or S.selected(); out = {}
    for g, v in rb.items():
        sg, k = S.split_gkey(g)
        if sg == n: out[k] = v
    return out

def open_gkey():
    """The open epoch as a lifetime close number (vesting counts closes across segments)."""
    with S.use(S.CURRENT): k = status().get("epochs_closed") or len(epoch_rows())
    return S.gkey(int(k), S.CURRENT)

def last_close_gkey():
    """The newest close in any segment as a lifetime close number (None with no close at all)."""
    for n in reversed(S.NUMBERS):
        ep = segment_closes(n)
        if ep: return S.gkey(max(int(e.get("epoch", 0)) for e in ep), n)
    return None

def vesting_split(rewards, open_ep, vest=100):
    """Each epoch k's reward unlocks 1/vest per epoch starting the next epoch (verified against /api/hosted/me)."""
    sp = sum(v * min(1.0, max(0, open_ep - k) / vest) for k, v in rewards.items())
    return sp, sum(rewards.values()) - sp

def confirmed(rb):
    """{lifetime close: reward} without closes whose rewards later balances do not carry (segments.unconfirmed_g)."""
    return {k: v for k, v in rb.items() if not S.unconfirmed_g(k)}

def vest_split(rb, n=None, vest=None):
    """(spendable, locked) of one address's rewards_by_addr() entry: the vesting basis is its confirmed rewards (1.26.122).
    With segments cut.carry_unlocked true (1.26.123), rewards from earlier segments are fully spendable since the cut."""
    vest = vest or int(params().get("vesting_epochs") or 100); n = open_gkey() if n is None else n
    c = confirmed(rb)
    if S.carry_unlocked() is True:
        off = S.offset(S.CURRENT); early = sum(v for k, v in c.items() if k < off)
        sp, lk = vesting_split({k: v for k, v in c.items() if k >= off}, n, vest)
        return early + sp, lk
    return vesting_split(c, n, vest)

@cached("supply", 60)
def supply_split():
    """Network spendable and locked over confirmed rewards, so spendable + locked is the carried supply (1.26.122)."""
    vest = int(params().get("vesting_epochs") or 100); n = open_gkey()
    sp = lk = 0.0
    for a, r in rewards_by_addr().items():
        s, l = vest_split(r, n, vest); sp += s; lk += l
    with S.use(S.CURRENT): carried = minted_before()
    return dict(spendable=sp, locked=lk, vesting_epochs=vest, open_epoch=n, circulating_basis=S.carry_basis(),
                locked_confirmed=S.carry_unlocked() is not None or not S.has_cut(), carried_supply=carried if S.has_cut() else None,
                excluded_rewards=excluded_rewards())

def segment_transfers():
    """{addr: net POA} from the current segment's archived transfer txs (received minus sent). Used only for addresses not
    in /api/agents, whose balance POAScan otherwise rebuilds from rewards."""
    out = collections.defaultdict(float)
    for r in db.q("SELECT from_addr, to_addr, amount FROM txs WHERE type='transfer' AND segment=?", (S.CURRENT,)):
        try: v = float(r["amount"] or 0)
        except (TypeError, ValueError): continue
        if r["to_addr"]: out[r["to_addr"]] += v
        if r["from_addr"]: out[r["from_addr"]] -= v
    return dict(out)

def excluded_rewards():
    """Rewards of closes later balances do not carry (segments config), summed over every segment."""
    out = 0.0
    for n in S.NUMBERS:
        for e in segment_closes(n):
            if S.unconfirmed(int(e.get("epoch", 0)), n): out += sum(float(v) for v in (e.get("rewards") or {}).values())
    return out

def carry_flag(kind):
    """Interim tag (ui.flag) on Circulating and Locked while segments cut.carry_unlocked is unset; "" otherwise."""
    if not S.has_cut() or S.carry_unlocked() is not None: return ""
    from .ui import flag
    return flag("Lower bound" if kind == "circ" else "Upper bound",
                "Carried balances may have unlocked at the genesis cut. Not yet confirmed network-wide, so this counts them as still vesting.", tone="est")

@cached("holders", 60)
def holders():
    # 1.26.122: every address in the current segment's /api/agents counts as listed whatever its balance (a 0 balance no
    # longer falls back to its reward sum), and the fallback for addresses not listed sums confirmed rewards only.
    st0 = int(S.BY_N[S.CURRENT].get("start_ts") or 0)
    acc = {r["addr"]: r for r in db.q("SELECT addr, balance, balance_s, invited_by FROM accounts WHERE COALESCE(last_seen, 0) >= ?", (st0,))}
    rb = rewards_by_addr(); rows = []
    for a, r in acc.items():
        if r["balance"] and r["balance"] > 0:
            rows.append(dict(addr=a, balance=r["balance"], balance_s=r["balance_s"], src="/api/agents"))
    seen = set(acc); net = segment_transfers()
    for a in set(rb) | set(net):   # 1.26.124: an unlisted address also nets the current segment's archived transfers
        if a in seen: continue
        v = sum(confirmed(rb.get(a, {})).values()) + net.get(a, 0.0)
        if v > 1e-9:
            rows.append(dict(addr=a, balance=v, balance_s=f"{v:.6f}", src="reward sum and transfers (not in /api/agents)" if net.get(a) else "reward sum (not in /api/agents)"))
    rows.sort(key=lambda x: -x["balance"])
    tot = sum(x["balance"] for x in rows)
    for i, x in enumerate(rows, 1): x["rank"] = i; x["share"] = x["balance"] / tot if tot else 0
    bal = [x["balance"] for x in rows]
    cl = collections.Counter(round(b, 6) for b in bal).most_common(1)
    listed = sum(1 for x in rows if x["src"] == "/api/agents")
    return dict(rows=rows, total=tot, count=len(rows), in_agents=listed, missing=len(rows) - listed,
                top10_share=sum(bal[:10]) / tot if tot else None, top1_share=bal[0] / tot if tot else None,
                gini=gini(bal), median=statistics.median(bal) if bal else None,
                cluster_balance=cl[0][0] if cl else None, cluster_count=cl[0][1] if cl else 0,
                cluster_share=(cl[0][1] / len(bal)) if bal else None)

@cached("established_set", 60)
def established_set():
    """Who is ESTABLISHED now, per minepoa's engine (estfold.py, 1.26.140): the selected segment's genesis import flags,
    plus established_after, minus established_removed, over that segment's closes. No trusted or system graders, no
    seats. Hosted /me is the authority."""
    from . import estfold as F
    return established_fold()[0]

@cached("established_fold", 60)
def established_fold():
    """(set, {address: last challenge_eligible close}, {address: (how, close)}) for the selected segment (estfold.fold)."""
    from . import estfold as F
    seg = S.selected()
    return F.fold(segment_closes(seg), F.imported(seg), params().get("slash_pardons"))

STANDING_NOTE = ("minepoa's engine removes an established Agent at close L + estab_ttl + 1 (L + 7 with estab_ttl 6), where L is its last "
                 "challenge_eligible close in this segment, -1 when none (genesis import Agents start at -1). Grading seats and jury seats don't "
                 "keep standing. A slash or ejection can remove it sooner. Hosted /me is the authority.")

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
    """When an established Agent is removed under minepoa's engine (estfold.py): close L + estab_ttl + 1, where L is its last
    challenge_eligible close in this segment (-1 when none). established_expires_basis says how. All None when not
    established or when that close already passed while the Agent still reads established.
    established_expires_closes_left counts closes from now (the open epoch's own close is 1); established_expires_ts_est is the
    open epoch's estimated close plus auto_epoch_seconds per later close (None without a close time on record)."""
    from . import estfold as F
    est, le, _ = established_fold(); L = le.get(a)
    out = dict(established_expires_epoch_est=None, established_expires_basis=None, last_challenge_eligible_epoch=L,
               established_expires_closes_left=None, established_expires_ts_est=None)
    if a not in est: return out
    pp = params(); ttl = F.ttl_of(pp); Lr = -1 if L is None else L; n = F.drop_close(Lr, ttl); o = open_epoch(); cur = o.get("epoch")
    if cur is None or n < cur: return out
    out.update(established_expires_epoch_est=n, established_expires_closes_left=n - cur + 1,
               established_expires_ts_est=int(o["est_close"] + (n - cur) * (o.get("period") or 21600)) if o.get("est_close") else None,
               established_expires_basis=(f"minepoa's engine rule, time an estimate: last challenge_eligible close {L} + estab_ttl {ttl} + 1" if L is not None else
                                          f"minepoa's engine rule, time an estimate: no challenge_eligible close in this segment (L = -1) + estab_ttl {ttl} + 1"))
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
    # the tx list: /api/txs since 1.26.98, /api/explorer/txs as its fallback; whichever read last
    live = db.q1("SELECT MAX(last_ok) AS last_ok FROM fetch_log WHERE endpoint IN ('/api/txs', '/api/explorer/txs')")
    return dict(endpoints=fl, jobs=jobs, live_last_ok=live["last_ok"] if live else None)

# ---- freshness: one state for the header pill, /api/live and /status
LIVE_S = 300            # our own last good read of the live feed
LAG_NODE_S = 600        # minepoa's node snapshot flagged stale and at least this old
LAG_CP_S = 6 * 3600     # checkpoint height unchanged this long
LAG_BLOCKS = 2000       # finality lag (blocks) flagged on Network > Overview; segment 2 anchors every 400 to 700 blocks
FEED_LIVE = ("/api/txs", "/api/explorer/txs", "/api/status", "/api/networks")   # any fresh read of the live network counts as live

def _ts(iso):
    try: return int(dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp())
    except Exception: return None

@cached("cp_moved", 60)
def cp_moved():
    """When the checkpoint height last changed, from our own status snapshots (3-day window)."""
    cur = status().get("checkpoint_height")
    if not cur: return None
    since = int(time.time()) - 3 * 86400; ex = "CAST(json_extract(json, '$.checkpoint_height') AS INTEGER)"
    sg = f"COALESCE(CAST(json_extract(json, '$.segment') AS INTEGER), 1) = {int(S.CURRENT)}"   # current segment only (heights restart at a cut)
    r = db.q1(f"SELECT MAX(ts) AS t FROM snaps WHERE kind='status' AND ts > ? AND {sg} AND {ex} IS NOT NULL AND {ex} != ?", (since, int(cur)))
    r = db.q1(f"SELECT MIN(ts) AS t FROM snaps WHERE kind='status' AND ts > ? AND {sg} AND {ex} = ?", (r["t"] or since, int(cur)))
    return r["t"]

@cached("freshness", 15)
def freshness():
    """live: our live fetch is current. lag: it is, but minepoa's node is stale or its checkpoint stalled. stale: our fetch failed."""
    now = time.time(); st = status(); h = health(); tx_live = h.get("live_last_ok")
    # 1.26.94: live when any read of the live network (tx feed, status, networks) is fresh, not the tx feed alone
    live = max([r["last_ok"] for r in h.get("endpoints") or [] if r.get("endpoint") in FEED_LIVE and r.get("last_ok")] + [tx_live or 0]) or None
    tx_down = bool(live and now - live <= LIVE_S and (not tx_live or now - tx_live > LIVE_S))
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
    elif (fd := feeds())["state"] != "OK": state, why = "partial", "Chain live. Not OK: " + ", ".join(fd["not_ok"])
    else: state, why = "live", "Live"
    return dict(state=state, label={"live": "Live", "partial": "Partial", "lag": "Lagging", "stale": "Stale", "up": "Upgrading"}[state], why=why,
                href="/upgrade" if state == "up" else "/network?tab=health", maintenance=up,
                fetched_at=live, node_age_s=node_age, node_stale=node_lag, checkpoint_moved=moved, checkpoint_age_s=cp_age, checkpoint_stalled=cp_lag and not up, tx_feed_down=tx_down)

# ---- per-feed state: one source for Network > Health, /api/health and the header pill (1.26.94)
# 1.26.98: a row with "best" is one feed with alternative paths (OK when either path serves it); the others take the
# worst of their callers. Tx lookup and swap tx reads try /chain/<id>/api/tx/<txid> first, so their keys cover both paths.
FEEDS = [("Status", ("/api/status",)), ("Networks", ("/api/networks",)), ("Tx list", ("/api/txs", "/api/explorer/txs"), "best"), ("Epochs", ("/api/epochs",)),
         ("Close records", ()), ("Tx lookup", ("/api/explorer/tx/:id (on demand)", "/api/explorer/tx/:id")), ("Address lookup", ("/api/explorer/address/:addr",)),
         ("Swaps", ("/api/swaps", "/api/explorer/tx/:id (swaps)")), ("Anchors", ("/api/anchors",)), ("Agents", ("/api/agents",)),
         ("Notices", ("/api/notices",)), ("Ballots", ("/api/ballots",)), ("Release", ("/api/release",)), ("Params", ("/api/params",)),
         ("Forum", ("/lableak/api/communities", "/lableak/api/posts")), ("Grading list", ("/api/explorer/grading",))]
FEED_ON_NEED = ("/api/epochs",)   # read only when a close record is missing: judged by its failures, like an on-view read
FEED_IDLE_S = 3600                # an on-view read not tried for this long is idle: old failures no longer count
FEED_RANK = {"OK": 0, "Degraded": 1, "Down": 2}
FEED_VIEW_DOWN = 5          # an on-view read (no schedule) with this many failures in a row is Down

def _feed_state(r, every, now):
    """OK, Degraded or Down for one fetch_log row. Scheduled: fresh when the last good read is within 3 cadences (5 min
    at least); a fresh read with failures since is Degraded; no fresh read is Down. On view: failures in a row decide."""
    lo, fails = r.get("last_ok"), r.get("fails") or 0
    if every:
        if not lo or now - lo > max(3 * every, 300): return "Down"
        return "Degraded" if fails else "OK"
    if not fails: return "OK"
    if fails >= FEED_VIEW_DOWN or not lo or now - lo > 3600: return "Down"
    return "Degraded"

def _iso_s(v):
    try: return int(dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()) if v else None
    except ValueError: return None

@cached("feeds", 15)
def feeds():
    """Chain state, one row per upstream feed (label, state, last_ok) and the headline: OK only when every feed is OK,
    Partial when the chain is live and any feed is not, Degraded when the chain is not live."""
    from . import indexer as I
    now = time.time(); rows = {r["endpoint"]: r for r in db.q("SELECT endpoint, last_ok, last_err, fails FROM fetch_log")}
    out = []
    for label, eps, *mode in FEEDS:
        if not eps:   # Close records: this segment's records cover every close the live network counts
            closed = status().get("epochs_closed")
            with S.use(S.CURRENT): have = len(epochs_raw()); ts = epochs_ts()
            if not isinstance(closed, (int, float)): continue
            st = "OK" if have >= closed else "Degraded"   # the count still shows (from /api/status); the record is missing
            out.append(dict(label=label, state=st, last_ok=ts if have else None, served=have, closed=int(closed))); continue
        every = lambda e: None if e in FEED_ON_NEED else I.EVERY.get(e)
        seen = [(rows[e], every(e)) for e in eps if e in rows]
        if not seen:
            if any(every(e) for e in eps): out.append(dict(label=label, state="Down", last_ok=None))
            continue
        tried = lambda r: max(r.get("last_ok") or 0, r.get("last_err") or 0)
        got = [(r, ev) for r, ev in seen if ev or now - tried(r) < FEED_IDLE_S]   # idle on-view reads drop out
        states = [_feed_state(r, ev, now) for r, ev in got] or ["OK"]
        st = (min if mode == ["best"] else max)(states, key=FEED_RANK.get)
        got = got or seen
        out.append(dict(label=label, state=st, last_ok=max((r["last_ok"] or 0) for r, _ in got) or None))
    from . import hosted as HO   # 1.26.127: swap order placement (the write check), Down when failing, Degraded when paused
    w, _ok = HO.writes(now); ws = w["swap_offer"]
    if ws["state"] != "unknown":
        out.append(dict(label="Swap writes", state={"open": "OK", "paused": "Degraded", "down": "Down"}[ws["state"]],
                        last_ok=_iso_s(ws["since"]) if ws["state"] == "open" else None, http=ws["http"], checked_at=ws["checked_at"]))
    live = [r.get("last_ok") for e, r in rows.items() if e in ("/api/status", "/api/networks") and r.get("last_ok")]
    fresh = bool(live) and now - max(live) <= LIVE_S
    moved = cp_moved(); stalled = bool(moved) and now - moved >= LAG_CP_S
    chain = "Live" if fresh and not stalled else "Stalled" if fresh else "Stale"
    bad = [f["label"] for f in out if f["state"] != "OK"]
    head = "Degraded" if chain != "Live" else "Partial" if bad else "OK"
    return dict(state=head, chain=chain, feeds=out, not_ok=bad, ok=head == "OK")

def anchors_latest(n=20, segment=None):
    """Newest anchors first, current segment first (heights restart at a genesis cut); segment= keeps one segment."""
    if segment: return db.q("SELECT * FROM anchors WHERE segment=? ORDER BY height DESC, chain LIMIT ?", (segment, n))
    return db.q("SELECT * FROM anchors ORDER BY segment DESC, height DESC, chain LIMIT ?", (n,))

def anchor_summary():
    """The selected segment's anchors (a new segment's top height is its own, not segment 1's h44003)."""
    sg = S.selected()
    r = db.q1("SELECT COUNT(DISTINCT height) AS heights, COUNT(*) AS n, MAX(height) AS top, MAX(anchored_at) AS last, MIN(anchored_at) AS first FROM anchors WHERE segment=?", (sg,))
    r["signers"] = db.q("SELECT DISTINCT chain, anchored_by FROM anchors WHERE segment=?", (sg,))
    # only checkpoint anchors carry ":sigsN"; the genesis import anchor's memo has none (it showed the whole memo)
    r["sigs"] = db.q("SELECT substr(memo, instr(memo,':sigs')+1) AS s, COUNT(*) AS n FROM anchors WHERE segment=? AND instr(memo,':sigs')>0 GROUP BY s", (sg,))
    r["segment"] = sg
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
        g = groups[since_of(tid, v)]; g["n"] += 1; g["ids"].append(tid)
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
            for t in st: org[since_of(t, pp[t]) if t in pp else tep.get(t, "unknown")] += 1
            for t, v in pend.items():
                if t not in pp: continue
                a, _ = _seals(pp[t], pn, mf); c, _ = _seals(v, n, mf)
                if a is None or c is None: unk += 1
                elif c > a: grew[since_of(t, v)] += 1
            for t, v in pp.items():
                if t not in pend and t not in sset: drop[since_of(t, v)] += 1
            closes.append(dict(close=n, settled=len(st), settled_by_origin=[dict(epoch=k, count=org[k]) for k in sorted(org, key=lambda k: (isinstance(k, str), k))],
                               carried=sum(1 for t in pend if t in pp), grew=sum(grew.values()), grew_unknown=unk, dropped=sum(drop.values()),
                               grew_by_epoch=dict(grew), dropped_by_epoch=dict(drop)))
        prev = (n, pend)
    hist = {}; exact = None; basis = None
    if raw:
        n = int(raw[-1]["epoch"]); ex = []
        for t, v in ((raw[-1].get("basis") or {}).get("pending") or {}).items():
            c, x = _seals(v, n, mf); ep = since_of(t, v); h = hist.setdefault(ep, {k: 0 for k in SEAL_KEYS})
            h["unknown" if c is None else "4+" if c >= 4 else str(c)] += 1
            if c is not None: ex.append(x)
        exact = all(ex) if ex else None; basis = "grades" if mf is not None and n >= mf else "panel"
    return dict(closes=closes, hist=hist, exact=exact, basis=basis, merge_from=mf)

# ---- Agents / hr: joins per hour from our own /api/status snapshots (agents_joined), no upstream call ----
JOIN_RATE_WINDOW_S = 86400     # default window: trailing 24 h
JOIN_PAUSE_S = 2 * 3600        # agents_joined flat this long reads as joining paused, not a slow spell
JOIN_MIN_S = 3600              # never report over less than an hour

def cut_list():
    """Segment boundaries (UTC ts, oldest first) from segments.json: agents_joined restarts at each, so no join delta crosses one."""
    return sorted(c["ts"] for c in S.cuts())

def seg_idx(t, cuts):
    """Which segment run a read at t falls in: the number of cuts at or before it (pure)."""
    return sum(1 for c in cuts if c <= t)

def join_steps(pts, cuts=()):
    """Pure: (ts, joins) between consecutive (ts, agents_joined) reads in the same segment, oldest first.
    A pair that straddles a cut is skipped: the count restarted there (carried Agents), so its difference is not joins."""
    return [(b[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]) if seg_idx(a[0], cuts) == seg_idx(b[0], cuts)]

def hourly_joins(pts, cuts=(), now=None):
    """Pure: Agents / hr points [(hour start, joins)] from (ts, agents_joined) reads. Joins in hour k are the last read of hour k
    minus the last read of hour k-1, only when both exist and are in the same segment (no bucket across a cut: no fake zero or
    spike). The current hour is still filling and is left out."""
    hr = {}
    for t, a in pts: hr[int(t) // 3600] = (int(t), a)
    cur = int(now if now is not None else time.time()) // 3600
    ks = sorted(k for k in hr if k < cur)
    return [(k * 3600, max(0, hr[k][1] - hr[j][1])) for j, k in zip(ks, ks[1:])
            if k - j == 1 and seg_idx(hr[j][0], cuts) == seg_idx(hr[k][0], cuts)]

def seg_join_times():
    """UTC times of the current segment's join txs (real join times), oldest first. One indexed read (txs_seg_type)."""
    return [r["ts"] for r in db.q("SELECT ts FROM txs WHERE segment = ? AND type = 'join' AND ts IS NOT NULL ORDER BY ts", (S.CURRENT,))]

def joins_series(pts, now=None, floor=None, join_ts=None):
    """Pure: the Agents / hr chart [(hour start, joins)]. Before the current segment: hourly_joins over the status reads.
    From the first whole hour of the current segment (floor, its start): join txs counted per hour (real join times), unless
    the tx list holds fewer joins than agents_joined rose (a gap in the feed), then the status reads there too. The hour
    holding the cut has no point, so the line breaks at the cut."""
    now = int(now if now is not None else time.time()); cuts = sorted({c for c in cut_list()} | ({floor} if floor else set()))
    snap = hourly_joins(pts, cuts, now)
    if not floor or join_ts is None: return snap
    seg = [p for p in pts if p[0] >= floor]
    rise = seg[-1][1] - seg[0][1] if len(seg) > 1 else 0
    if len([t for t in join_ts if t >= floor]) < rise: return snap
    first, cur = -(-int(floor) // 3600) * 3600, now // 3600 * 3600
    n = collections.Counter(int(t) // 3600 * 3600 for t in join_ts if t >= floor)
    return [p for p in snap if p[0] + 3600 <= floor] + [(h, n.get(h, 0)) for h in range(first, cur, 3600)]

def joins_between(lo, hi):
    """Agents joined in (lo, hi] from POAScan's own status snapshots, summed within each segment (never across a cut).
    Base: the last read at or before lo. Two indexed reads, no upstream call."""
    b = db.q1("SELECT ts, json_extract(json, '$.agents_joined') AS a FROM snaps WHERE kind='status' AND ts <= ? AND json_extract(json, '$.agents_joined') IS NOT NULL ORDER BY ts DESC LIMIT 1", (lo,))
    rows = db.q("SELECT ts, json_extract(json, '$.agents_joined') AS a FROM snaps WHERE kind='status' AND ts > ? AND ts <= ? ORDER BY ts", (lo, hi))
    pts = ([(b["ts"], int(b["a"]))] if b and b["a"] else []) + [(r["ts"], int(r["a"])) for r in rows if r["a"]]
    if len(pts) < 2: return None
    return sum(max(0, d) for _, d in join_steps(pts, cut_list()))

def _join_points(since):
    if S.has_cut() and time.time() >= S.CUT_TS: since = max(since, S.CUT_TS)   # agents_joined restarted at the genesis cut: never a delta across it
    return [(r["ts"], int(r["a"])) for r in db.q(
        "SELECT ts, json_extract(json, '$.agents_joined') AS a FROM snaps WHERE kind='status' AND ts >= ? ORDER BY ts", (since,)) if r["a"]]

def _rate_since(pts, t0):
    """Joins per hour from the last read at or before t0 (else the first read after it) to the newest read."""
    if len(pts) < 2: return None
    base = next((p for p in reversed(pts) if p[0] <= t0), pts[0]); end = pts[-1]
    h = (end[0] - base[0]) / 3600
    return dict(joins=max(0, end[1] - base[1]), hours=round(h, 2), per_hour=round(max(0, end[1] - base[1]) / h, 1) if h > 0 else None)

def joins_rate_calc(pts, now=None, floor=None, join_ts=None):
    """Pure: the homepage Agents / hr from (ts, agents_joined) reads, oldest first.
    Default: joins over the trailing 24 h divided by its hours. If agents_joined stood still for JOIN_PAUSE_S or more inside
    that window (joining paused, e.g. a network upgrade), the window starts where the latest pause ended, so a pause does not
    drag the rate toward zero; it stays at least JOIN_MIN_S long.
    floor: the current segment's start (a genesis cut) when it is inside the 24 h. The window then starts at the first read of the
    segment (kind since_cut); with less than JOIN_MIN_S of the segment read it is None, and a trailing rate longer than the
    segment is None, never a figure over a shorter span.
    join_ts: the current segment's join tx times. Since a cut they are the source (real join times): joins from the segment's
    first join (joining reopened; joining_from) to now, over at least JOIN_MIN_S; 0 while none has joined in a segment over
    an hour old. If the tx list holds fewer joins than agents_joined rose, the status reads are used instead."""
    if join_ts is not None and floor is not None and now is not None and floor > now - JOIN_RATE_WINDOW_S and now - floor >= JOIN_MIN_S:
        seg = [p for p in pts if p[0] >= floor]; jt = sorted(t for t in join_ts if floor <= t <= now)
        rise = seg[-1][1] - seg[0][1] if len(seg) > 1 else 0
        if len(jt) >= rise:
            start = jt[0] if jt else floor; h = max(JOIN_MIN_S, now - start) / 3600
            tr = {k: (round(sum(1 for t in jt if t > now - s) / (s / 3600), 1) if now - s >= floor else None) for k, s in (("1h", 3600), ("6h", 6 * 3600), ("24h", 86400))}
            return dict(agent_joins_per_hour=int(round(len(jt) / h)), joins=len(jt), window_hours=round(h, 2), window="since_cut", window_end=now,
                        paused_until=None, joining_from=jt[0] if jt else None, source="join_txs", trailing=tr)
    if len(pts) < 2: return None
    end = pts[-1][0]; t0 = end - JOIN_RATE_WINDOW_S
    since_cut = floor is not None and floor > t0
    if since_cut:
        pts = [p for p in pts if p[0] >= floor]
        if len(pts) < 2 or end - pts[0][0] < JOIN_MIN_S: return None
        t0 = pts[0][0]
    win = [p for p in pts if p[0] >= t0]
    start = t0; paused_until = None
    i = 0
    while i < len(win):            # runs of equal counts: first read to the last read before the count moved
        j = i
        while j + 1 < len(win) and win[j + 1][1] == win[i][1]: j += 1
        if j + 1 < len(win) and win[j][0] - win[i][0] >= JOIN_PAUSE_S: paused_until = win[j][0]   # an ended pause (an ongoing one keeps 24 h)
        i = j + 1
    if paused_until is not None: start = max(t0, min(paused_until, end - JOIN_MIN_S))
    r = _rate_since(pts, start)
    if not r or r["per_hour"] is None: return None
    trailing = {k: (_rate_since(pts, end - s) if not since_cut or end - s >= t0 else None) for k, s in (("1h", 3600), ("6h", 6 * 3600), ("24h", 86400))}
    return dict(agent_joins_per_hour=int(round(r["per_hour"])), joins=r["joins"], window_hours=r["hours"],
                window="since_pause" if paused_until is not None else "since_cut" if since_cut else "24h", window_end=end, paused_until=paused_until,
                joining_from=None, source="status", trailing={k: (v["per_hour"] if v else None) for k, v in trailing.items()})

# ---- Active Agents (1.26.173): distinct Agents with an answer (challenge tx) in the current segment over the last epoch length ----
# An Agent answers at most once per epoch, so one epoch (params.auto_epoch_seconds, 6 h) is the shortest window in which every
# Agent mining right now shows up, and a rolling one never drops to zero at a close. Was the last 24 h (1.26.116 to 1.26.172).
ACTIVE_WINDOW_S = 21600

def active_window_s(p=None):
    """Window length in whole hours: params.auto_epoch_seconds (the epoch target, already read with /api/params), else 6 h."""
    try: s = int((params() if p is None else p).get("auto_epoch_seconds") or ACTIVE_WINDOW_S)
    except (TypeError, ValueError, AttributeError): s = ACTIVE_WINDOW_S
    return max(3600, min(86400, s // 3600 * 3600))

def active_window(now, seg_start, win=ACTIVE_WINDOW_S):
    """Pure: (start, kind) of the Active Agents window: the last epoch length (kind '6h' for 6 h), cut back to the current
    segment's start (segments.json) when that is newer, so no answer from an earlier segment is counted."""
    t0 = now - win
    return (int(seg_start), "since_segment_start") if seg_start and seg_start > t0 else (int(t0), f"{win // 3600}h")

@cached("active_agents", 120)
def active_agents():
    """Cached 2 min: one indexed read (txs_seg_type) of POAScan's own tx archive, no upstream call. Distinct senders of
    challenge txs (answers) in the current segment since the window start."""
    now = int(time.time()); seg0 = S.CUT_TS if S.has_cut() and now >= S.CUT_TS else None; win = active_window_s()
    t0, kind = active_window(now, seg0, win)
    n = db.q1("SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE segment = ? AND type = 'challenge' AND ts > ? AND ts <= ?", (S.CURRENT, t0, now))["n"]
    return dict(active_agents=int(n or 0), window=kind, start_ts=t0, end_ts=now, hours=round((now - t0) / 3600, 2), segment=S.CURRENT,
                basis="distinct_answerers", source="challenge_txs", window_s=win)

def active_runs(rows, segs, now, live=None, win=ACTIVE_WINDOW_S):
    """Pure: the Active Agents series [(ts, n)] over every segment, oldest first. rows: distinct (segment, hour index, Agent)
    of challenge txs. At each whole hour of a segment, n is the distinct Agents that answered in the `win` seconds (whole
    hours) before it within that segment (the card's own window, so a count never reaches back across a genesis cut). A segment's run starts at
    the first hour after its first answer (real data only, never padded) and ends at its last hour boundary; the current
    segment ends at now with `live` (the card value) when given."""
    from collections import Counter
    by = {}
    for sg, h, a in rows: by.setdefault(int(sg), {}).setdefault(int(h), set()).add(a)
    out = []
    for x in segs:
        hrs = by.get(x["n"])
        if not hrs: continue
        end = x.get("end_ts") or now; first = min(hrs); last = int(end) // 3600
        cnt = Counter(); hw = win // 3600; run = []
        for H in range(first + 1, last + 1):   # boundary H closes the window of hours H-w .. H-1 (w = win in hours)
            for a in hrs.get(H - 1, ()): cnt[a] += 1
            for a in hrs.get(H - 1 - hw, ()):
                cnt[a] -= 1
                if not cnt[a]: del cnt[a]
            run.append((H * 3600, len(cnt)))
        if x.get("end_ts") is None and live is not None and (not run or now > run[-1][0]): run.append((int(now), int(live)))
        out += run
    return out

@cached("active_series", 300)
def active_series():
    """Cached 5 min: the Active Agents chart (Home sparkline and pop-out, chartpop.py) from POAScan's own tx archive, one
    indexed read (txs_seg_type), no upstream call. Every segment, oldest first; the pop-out breaks the line at each cut."""
    now = int(time.time())
    rows = db.q("SELECT segment, ts/3600 AS h, from_addr FROM txs WHERE type = 'challenge' AND ts <= ? GROUP BY segment, h, from_addr", (now,))
    a = active_agents()
    return active_runs([(r["segment"], r["h"], r["from_addr"]) for r in rows], S.SEGMENTS, now, a["active_agents"] if a else None,
                       a["window_s"] if a else active_window_s())

@cached("joins_rate", 120)
def joins_rate():
    """Cached 2 min: one indexed range read of about a day of status snapshots."""
    now = int(time.time()); fl = S.CUT_TS if S.has_cut() and now >= S.CUT_TS else None
    return joins_rate_calc(_join_points(now - JOIN_RATE_WINDOW_S - 3 * 3600), now, floor=fl, join_ts=seg_join_times() if fl else None)
