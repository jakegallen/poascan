"""Private daily network aggregates for the operator (GET /ops/network, Bearer POASCAN_STATS_TOKEN, else the normal 404).

Every number comes from data POAScan already archives (txs, snaps, accounts, swaps, the epochs blob, /api/chains,
uptime_daily; swaps through the swap module's API). Nothing here calls minepoa.com or adds a poll. Aggregates only: no address leaves this module.

Per-day tx and snapshot figures live in a small rollup table (network_daily, one row per UTC day) that is updated
incrementally: only days touched by tx or snapshot rows added since the last refresh are recomputed, found by rowid
watermarks. Everything else is read with range-bounded SQL. Responses are cached per (from, to) for CACHE_TTL seconds."""
import bisect, collections, datetime as dt, json, statistics, threading, time
from . import db, analytics as A, swapclient as SC

CACHE_TTL = 180
CACHE_MAX = 8
REFRESH_EVERY = 60
WM_KIND = "rollup:network"
GENESIS_MIN = 1704067200           # 2024-01-01: rows with ts 0 or junk timestamps stay out of the series
BUCKETS = (("0", None), ("lt1", 1), ("lt10", 10), ("lt100", 100), ("lt1k", 1000), ("lt10k", 10000), ("ge10k", None))


METRICS = {
    "agents.new": "new Agents that day: change in minepoa's agents_joined between the last /api/status snapshot of the day and of the day before (first day: within the day)",
    "agents.total": "agents_joined in the last /api/status snapshot of the day (cumulative Agents)",
    "agents.first_seen": "Agents whose first archived tx (any type) falls on that day",
    "agents.join_txs": "archived join txs (registrations) that day",
    "agents.active": "distinct Agents that sent at least one archived tx that day",
    "agents.listed": "Agents in POAScan's last /api/agents read of the day",
    "agents.with_balance": "Agents with a balance above 0 in POAScan's last /api/agents read of the day",
    "agents.holders_reported": "holders in the last /api/status snapshot of the day",
    "supply": "supply in the last /api/status snapshot of the day (POA)",
    "txs.total": "archived txs with a ledger timestamp that day",
    "txs.by_type": "archived txs that day by type: {type: {n, agents}} where agents is distinct senders",
    "transfers.count": "archived transfer txs that day",
    "transfers.poa": "sum of transfer amounts that day (POA)",
    "transfers.senders": "distinct transfer senders that day",
    "transfers.recipients": "distinct transfer recipients that day",
    "epochs.closed": "epochs whose close record timestamp falls on that day",
    "epochs.numbers": "the epoch numbers closed that day",
    "epochs.minted": "rewards paid by those closes (POA)",
    "epochs.pool": "reward pool of those closes (POA)",
    "epochs.burned": "pool minus rewards paid (POA)",
    "epochs.paid_agents": "reward rows in those closes (an Agent paid in two closes counts twice)",
    "epochs.challengers": "challengers listed in those close records",
    "epochs.settled": "answers settled by those closes",
    "epochs.accepted": "settled answers that passed grading",
    "epochs.grades": "grades served in those closes",
    "epochs.slashed": "Agents slashed in those closes",
    "epochs.established": "Agents that became established in those closes",
    "mining.submissions": "archived challenge (answer) txs that day",
    "mining.submitters": "distinct Agents that submitted an answer that day",
    "mining.grade_seals": "archived grade-sealed txs that day",
    "mining.graders": "distinct graders that day",
    "mining.attest_batches": "archived attest-batch txs that day",
    "mining.attesters": "distinct attesters that day",
    "mining.height": "ledger height in POAScan's last /api/networks read of the day",
    "mining.checkpoint_height": "finalized checkpoint height in the last /api/status snapshot of the day",
    "mining.checkpoint_advance": "checkpoint_height change from the day before (null when either day has no snapshot)",
    "swaps.created": "swap offers whose swap-offer tx timestamp falls on that day",
    "swaps.filled": "offers filled that day (swap-fill tx timestamp)",
    "swaps.cancelled": "offers cancelled that day (swap-cancel tx timestamp)",
    "swaps.expired": "offers that expired unfilled that day (expiry time)",
    "swaps.fill_rate": "filled / (filled + cancelled + expired) for offers resolved that day; null when none resolved",
    "swaps.median_fill_s": "median seconds from offer to fill for fills that day (fills with a known offer time)",
    "swaps.volume_poa": "POA locked in offers filled that day",
    "swaps.volume_usd": "USD value of fills that day at the SOL/ETH reference recorded near fill time (USDC at 1); fills without a recorded rate are left out",
    "swaps.makers": "distinct makers of offers created that day",
    "swaps.takers": "distinct takers of fills that day",
    "swaps.by_asset": "per quote asset: {fills, poa, quote, open, high, low, close, vwap}; prices are quote asset per POA from fills in fill order, vwap = quote / poa",
    "wallets.solana_new": "Agents whose currently verified solana address was first registered by an archived finalized chains-update tx that day",
    "wallets.ethereum_new": "same for ethereum",
    "wallets.solana_total": "cumulative Agents with a currently verified solana address dated by the ledger, at the end of the day",
    "wallets.ethereum_total": "same for ethereum",
    "wallets.any_total": "cumulative Agents with either",
    "upstream.total": "POAScan's own requests to minepoa.com that day (all outcomes), from the existing uptime_daily rollup (kept 365 days, starts at snapshot.upstream_from); the current day refreshes every 10 minutes",
    "upstream.by_endpoint": "the same by endpoint or route template; upstream is null for days before snapshot.upstream_from",
    "snapshot.holders": "current only: balance distribution and top-N concentration from POAScan's latest /api/agents read (plus reward sums for Agents missing from it, as on /token); not an end-of-day history",
    "snapshot.wallets": "current only: Agents with a verified address per chain in the latest /api/chains read, and how many of those have a ledger date",
}

SKIPPED = {
    "holders_history": "end-of-day balance distribution and top-N shares are not reconstructible: balances include per-epoch rewards with vesting, swap escrow and fees, and the archive does not hold every tx since genesis; current snapshot only (snapshot.holders). Daily holder counts come from /api/status and /api/agents snapshots instead",
    "wallet_unlinks": "removed or replaced links are not dated; wallet cohorts count Agents whose link is verified now",
}

_lock = threading.Lock()
_cache = collections.OrderedDict()
_last_refresh = [0.0]

def _day(d): return dt.date(1970, 1, 1) + dt.timedelta(days=int(d))
def _dn(s): return (dt.date.fromisoformat(s) - dt.date(1970, 1, 1)).days
def _iso(t): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(t)))
def _r(x, n=6): return round(x, n) if isinstance(x, float) else x

# ---- rollup
def _tx_day(d):
    lo, hi = d * 86400, (d + 1) * 86400
    by = {}
    for r in db.q("SELECT type, COUNT(*) AS n, COUNT(DISTINCT from_addr) AS a FROM txs WHERE ts >= ? AND ts < ? GROUP BY type", (lo, hi)):
        by[r["type"] or "unknown"] = dict(n=r["n"], agents=r["a"])
    act = db.q1("SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE ts >= ? AND ts < ? AND from_addr LIKE 'poa1%'", (lo, hi))["n"]
    tr = db.q1("""SELECT COUNT(*) AS n, SUM(CAST(amount AS REAL)) AS v, COUNT(DISTINCT from_addr) AS s, COUNT(DISTINCT to_addr) AS r
                  FROM txs WHERE type = 'transfer' AND ts >= ? AND ts < ?""", (lo, hi))
    return dict(by_type=by, active=act, transfers=dict(count=tr["n"] or 0, poa=_r(float(tr["v"] or 0)), senders=tr["s"] or 0, recipients=tr["r"] or 0))

def _last_snap(kind, lo, hi, first=False):
    r = db.q1(f"SELECT json FROM snaps WHERE kind = ? AND ts >= ? AND ts < ? ORDER BY ts {'ASC' if first else 'DESC'} LIMIT 1", (kind, lo, hi))
    try: return json.loads(r["json"]) if r else {}
    except Exception: return {}

def _num(x, f=int):
    try: return f(x) if x is not None and x != "" else None
    except Exception: return None

def _snap_day(d):
    lo, hi = d * 86400, (d + 1) * 86400
    st, st0 = _last_snap("status", lo, hi), _last_snap("status", lo, hi, first=True)
    ac, ht = _last_snap("accounts", lo, hi), _last_snap("height", lo, hi)
    return dict(agents_end=_num(st.get("agents_joined")), agents_start=_num(st0.get("agents_joined")), holders=_num(st.get("holders")),
                supply=_r(_num(st.get("supply"), float)), checkpoint=_num(st.get("checkpoint_height")) or _num(ht.get("checkpoint_height")),
                height=_num(ht.get("height")), listed=_num(ac.get("total")), with_balance=_num(ac.get("with_balance")))

def refresh(force=False):
    """Recompute the rollup rows for days touched since the last refresh (and today). Cheap when nothing changed."""
    if not force and time.time() - _last_refresh[0] < REFRESH_EVERY: return
    wm = db.get_blob(WM_KIND)[0] or {}
    tw, sw = int(wm.get("txs") or 0), int(wm.get("snaps") or 0)
    tmax = db.q1("SELECT MAX(rowid) AS m FROM txs")["m"] or 0
    smax = db.q1("SELECT MAX(rowid) AS m FROM snaps")["m"] or 0
    if tmax < tw or smax < sw: tw = sw = 0                # table rebuilt: start over
    today = int(time.time()) // 86400
    tdays = {r["d"] for r in db.q("SELECT DISTINCT ts / 86400 AS d FROM txs WHERE rowid > ? AND rowid <= ? AND ts >= ?", (tw, tmax, GENESIS_MIN))}
    sdays = {r["d"] for r in db.q("SELECT DISTINCT ts / 86400 AS d FROM snaps WHERE rowid > ? AND rowid <= ? AND ts >= ? AND kind IN ('status','accounts','height')",
                                  (sw, smax, GENESIS_MIN))}
    if tw: tdays.add(today)
    if sw: sdays.add(today)
    now = int(time.time()); stmts = []
    for d in sorted(tdays | sdays):
        if d > today: continue
        tx = json.dumps(_tx_day(d), separators=(",", ":")) if d in tdays else None
        sn = json.dumps(_snap_day(d), separators=(",", ":")) if d in sdays else None
        stmts.append(("""INSERT INTO network_daily(day, txs, snaps, updated) VALUES(?,?,?,?) ON CONFLICT(day) DO UPDATE SET
                         txs = COALESCE(excluded.txs, network_daily.txs), snaps = COALESCE(excluded.snaps, network_daily.snaps), updated = excluded.updated""",
                      (d, tx, sn, now), False))
    stmts.append(("""INSERT INTO network_first(addr, ts) SELECT from_addr, MIN(ts) FROM txs WHERE rowid > ? AND rowid <= ? AND ts >= ? AND from_addr LIKE 'poa1%'
                     GROUP BY from_addr ON CONFLICT(addr) DO UPDATE SET ts = MIN(network_first.ts, excluded.ts)""", (tw, tmax, GENESIS_MIN), False))
    stmts.append(("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?,?,?)", (WM_KIND, now, json.dumps({"txs": tmax, "snaps": smax})), False))
    db.write_tx(stmts)
    _last_refresh[0] = time.time()

# ---- live, range-bounded sources
def _epochs(d0, d1):
    out = {}
    for e in A.epoch_rows():
        d = e["close_ts"] // 86400
        if d < d0 or d > d1: continue
        x = out.setdefault(d, dict(closed=0, numbers=[], minted=0.0, pool=0.0, burned=0.0, paid_agents=0, challengers=0, settled=0,
                                   accepted=0, grades=0, slashed=0, established=0))
        x["closed"] += 1; x["numbers"].append(e["epoch"])
        for k, s in (("minted", "minted"), ("pool", "pool"), ("burned", "burned")): x[k] += float(e.get(s) or 0)
        for k, s in (("paid_agents", "paid"), ("challengers", "challengers"), ("settled", "settled"), ("accepted", "settled_passed"),
                     ("grades", "grades"), ("slashed", "slashed"), ("established", "established")): x[k] += int(e.get(s) or 0)
    for x in out.values():
        for k in ("minted", "pool", "burned"): x[k] = _r(x[k])
    return out

def _swaps(d0, d1):
    """Per-day swap aggregates from the swap module's own API (poascan/swapclient.py, the explorer's only door to swap data)."""
    lo, hi = d0 * 86400, (d1 + 1) * 86400; out = {}
    def S(d): return out.setdefault(d, dict(created=0, filled=0, cancelled=0, expired=0, fill_rate=None, median_fill_s=None, volume_poa=0.0,
                                            volume_usd=None, makers=set(), takers=set(), by_asset={}))
    inr = lambda t: isinstance(t, (int, float)) and lo <= t < hi
    fills = collections.defaultdict(list)
    for r in SC.offers() or []:
        st, c = r.get("status"), r.get("created_ts")
        if inr(c): x = S(int(c) // 86400); x["created"] += 1; x["makers"].add(r.get("maker"))
        if st == "cancelled" and inr(r.get("cancel_ts")): S(int(r["cancel_ts"]) // 86400)["cancelled"] += 1
        if st == "expired" and inr(r.get("expires_ts")): S(int(r["expires_ts"]) // 86400)["expired"] += 1
        if st == "filled" and inr(r.get("fill_ts")): fills[int(r["fill_ts"]) // 86400].append(r)
    for d, fs in fills.items():
        fs.sort(key=lambda f: f["fill_ts"]); x = S(d); x["filled"] = len(fs); x["takers"] |= {f.get("taker") for f in fs}
        x["volume_poa"] = _r(sum(float(f.get("poa") or 0) for f in fs))
        usd = [float(f["want"]) * float(f["fill_usd"]) for f in fs if f.get("want") and f.get("fill_usd")]
        x["volume_usd"] = _r(sum(usd), 2) if usd else None
        lag = [f["fill_ts"] - f["created_ts"] for f in fs if f.get("created_ts") and f["fill_ts"] >= f["created_ts"]]
        x["median_fill_s"] = int(statistics.median(lag)) if lag else None
        for f in fs:
            poa, q = float(f.get("poa") or 0), float(f.get("want") or 0)
            a = x["by_asset"].setdefault(str(f.get("asset") or "?").upper(), dict(fills=0, poa=0.0, quote=0.0, open=None, high=None, low=None, close=None, vwap=None))
            a["fills"] += 1; a["poa"] += poa; a["quote"] += q
            if poa > 0 and q > 0:
                p = q / poa
                a["open"] = a["open"] if a["open"] is not None else p; a["close"] = p
                a["high"] = p if a["high"] is None else max(a["high"], p); a["low"] = p if a["low"] is None else min(a["low"], p)
        for a in x["by_asset"].values():
            a["vwap"] = (a["quote"] / a["poa"]) if a["poa"] > 0 and a["quote"] > 0 else None
            for k in ("poa", "quote"): a[k] = _r(a[k])
            for k in ("open", "high", "low", "close", "vwap"): a[k] = float(f"{a[k]:.6g}") if a[k] is not None else None
    for x in out.values():
        res = x["filled"] + x["cancelled"] + x["expired"]
        x["fill_rate"] = round(x["filled"] / res, 4) if res else None
        x["makers"] = len(x["makers"] - {None}); x["takers"] = len(x["takers"] - {None})
    return out

def _wallet_links():
    """[(chain, ts)] for each Agent's currently verified link that an archived finalized chains-update dates (earliest such tx)."""
    try:
        rows = db.q("""SELECT t.from_addr AS a, j.key AS chain, CAST(j.value AS TEXT) AS addr, MIN(t.ts) AS ts
                       FROM txs t JOIN tx_detail d ON d.id = t.id, json_each(d.json, '$.body.chains') j
                       WHERE t.type = 'chains-update' AND (t.final = 1 OR d.final = 1) AND t.from_addr IS NOT NULL GROUP BY 1, 2, 3""")
    except Exception:
        rows = []
    norm = lambda s: str(s or "").lower() if str(s or "")[:2].lower() == "0x" else str(s or "")
    first = {}
    for r in rows: first[(r["a"], r["chain"], norm(r["addr"]))] = r["ts"]
    cur = collections.Counter(); dated = collections.Counter(); links = []
    for agent, ls in (db.get_blob("chains")[0] or {}).items():
        if not str(agent).startswith("poa1") or not isinstance(ls, dict): continue
        chs = set()
        for c, v in ls.items():
            if not (isinstance(v, dict) and v.get("verified") is True and v.get("addr")): continue
            cur[c] += 1; chs.add(c); t = first.get((agent, c, norm(v["addr"])))
            if t: dated[c] += 1; links.append((agent, c, int(t)))
        if chs: cur["any"] += 1
        if {"solana", "ethereum"} <= chs: cur["both"] += 1
    return links, dict(verified=dict(cur), dated=dict(dated))

def _upstream(d0, d1):
    out = {}
    for r in db.q("SELECT day / 86400 AS d, endpoint, n FROM uptime_daily WHERE day >= ? AND day < ?", (d0 * 86400, (d1 + 1) * 86400)):
        ep = r["endpoint"][6:] if r["endpoint"].startswith("probe ") else r["endpoint"]
        x = out.setdefault(r["d"], dict(total=0, by_endpoint={})); x["total"] += r["n"] or 0
        x["by_endpoint"][ep] = x["by_endpoint"].get(ep, 0) + (r["n"] or 0)
    for x in out.values(): x["by_endpoint"] = dict(sorted(x["by_endpoint"].items(), key=lambda kv: (-kv[1], kv[0])))
    return out

def _holders():
    h = A.holders(); rows = h.get("rows") or []; tot = h.get("total") or 0
    bal = [float(r["balance"]) for r in rows]
    agents = db.q1("SELECT COUNT(*) AS n FROM accounts")["n"] or 0
    zero = max(0, agents - (h.get("in_agents") or 0))
    b = {k: 0 for k, _ in BUCKETS}; b["0"] = zero
    for v in bal:
        k = "lt1" if v < 1 else "lt10" if v < 10 else "lt100" if v < 100 else "lt1k" if v < 1000 else "lt10k" if v < 10000 else "ge10k"
        b[k] += 1
    share = lambda n: round(sum(bal[:n]) / tot, 6) if tot else None
    ts = db.q1("SELECT MAX(last_seen) AS t FROM accounts")["t"]
    return dict(current_only=True, read_at=_iso(ts) if ts else None, agents=agents, holders=len(rows), total_poa=_r(float(tot)), buckets=b,
                top1_share=share(1), top10_share=share(10), top100_share=share(100), gini=_r(h.get("gini")), median_poa=_r(h.get("median")),
                from_reward_sums=h.get("missing") or 0)

# ---- report
def _compute(frm, to):
    refresh()
    d0, d1 = _dn(frm), _dn(to); today = int(time.time()) // 86400
    rows = {r["day"]: r for r in db.q("SELECT day, txs, snaps FROM network_daily WHERE day >= ? AND day <= ?", (d0 - 1, d1))}
    first = {r["d"]: r["n"] for r in db.q("SELECT ts / 86400 AS d, COUNT(*) AS n FROM network_first WHERE ts >= ? AND ts < ? GROUP BY d", (d0 * 86400, (d1 + 1) * 86400))}
    hist = db.q1("SELECT MIN(day) AS d FROM network_daily WHERE txs IS NOT NULL")["d"]
    ep, sw, up = _epochs(d0, d1), _swaps(d0, d1), _upstream(d0, d1)
    up_first = db.q1("SELECT MIN(day) AS d FROM uptime_daily")["d"]; up_d = up_first // 86400 if up_first is not None else None
    links, wcur = _wallet_links()
    lday = collections.defaultdict(collections.Counter); lfirst = {}
    for agent, c, t in links:
        lday[t // 86400][c] += 1
        lfirst[agent] = min(lfirst.get(agent, t), t)
    lch = {c: sorted(t // 86400 for _, c2, t in links if c2 == c) for c in ("solana", "ethereum")}
    afirst = sorted(t // 86400 for t in lfirst.values())
    def cum(d, chain): return bisect.bisect_right(lch[chain], d)
    def J(r, k):
        try: return json.loads(r[k]) if r and r[k] else None
        except Exception: return None
    zero_ep = dict(closed=0, numbers=[], minted=0.0, pool=0.0, burned=0.0, paid_agents=0, challengers=0, settled=0, accepted=0, grades=0, slashed=0, established=0)
    zero_sw = dict(created=0, filled=0, cancelled=0, expired=0, fill_rate=None, median_fill_s=None, volume_poa=0.0, volume_usd=None, makers=0, takers=0, by_asset={})
    start = max(d0, hist) if hist is not None else d1 + 1
    days = []
    for d in range(start, min(d1, today) + 1):
        tx, sn = J(rows.get(d), "txs") or {}, J(rows.get(d), "snaps") or {}
        prev = J(rows.get(d - 1), "snaps") or {}
        by = tx.get("by_type") or {}; g = lambda t, k="n": (by.get(t) or {}).get(k, 0)
        ae, pe = sn.get("agents_end"), prev.get("agents_end")
        new = (ae - pe) if ae is not None and pe is not None else (ae - sn["agents_start"]) if ae is not None and sn.get("agents_start") is not None else None
        ck, pk = sn.get("checkpoint"), prev.get("checkpoint")
        days.append(dict(
            day=_day(d).isoformat(),
            agents=dict(new=new, total=ae, first_seen=first.get(d, 0), join_txs=g("join"), active=tx.get("active", 0),
                        listed=sn.get("listed"), with_balance=sn.get("with_balance"), holders_reported=sn.get("holders")),
            supply=sn.get("supply"),
            txs=dict(total=sum(v.get("n", 0) for v in by.values()), by_type=dict(sorted(by.items(), key=lambda kv: (-kv[1].get("n", 0), kv[0])))),
            transfers=tx.get("transfers") or dict(count=0, poa=0.0, senders=0, recipients=0),
            epochs=ep.get(d, dict(zero_ep, numbers=[])),
            mining=dict(submissions=g("challenge"), submitters=g("challenge", "agents"), grade_seals=g("grade-sealed"), graders=g("grade-sealed", "agents"),
                        attest_batches=g("attest-batch"), attesters=g("attest-batch", "agents"), height=sn.get("height"), checkpoint_height=ck,
                        checkpoint_advance=(ck - pk) if ck is not None and pk is not None else None),
            swaps=sw.get(d, dict(zero_sw, by_asset={})),
            wallets=dict(solana_new=lday[d].get("solana", 0), ethereum_new=lday[d].get("ethereum", 0), solana_total=cum(d, "solana"),
                         ethereum_total=cum(d, "ethereum"), any_total=bisect.bisect_right(afirst, d)),
            upstream=up.get(d, dict(total=0, by_endpoint={})) if up_d is not None and d >= up_d else None))
    days.reverse()   # newest first, as /ops/visits
    st = A.status(); o = (SC.status() or {}).get("open_offers")
    snap = dict(history_from=_day(hist).isoformat() if hist is not None else None,
                upstream_from=_day(up_first // 86400).isoformat() if up_first else None,
                agents_total=_num(st.get("agents_joined")), holders_reported=_num(st.get("holders")), supply=_r(_num(st.get("supply"), float)),
                epochs_closed=_num(st.get("epochs_closed")), checkpoint_height=_num(st.get("checkpoint_height")), open_swap_offers=o,
                holders=_holders(), wallets=dict(current_only=True, verified=wcur["verified"], dated=wcur["dated"]),
                skipped=SKIPPED)
    return dict(**{"from": frm, "to": to}, as_of=_iso(time.time()), metrics=METRICS, days=days, snapshot=snap)

def report(frm, to):
    k = (frm, to)
    with _lock:
        hit = _cache.get(k)
        if hit and time.time() - hit[0] < CACHE_TTL: return hit[1]
        v = json.dumps(_compute(frm, to), separators=(",", ":"))
        _cache[k] = (time.time(), v); _cache.move_to_end(k)
        while len(_cache) > CACHE_MAX: _cache.popitem(last=False)
        return v
