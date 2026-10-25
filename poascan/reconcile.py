"""POAScan's own totals beside the node's reported numbers, from reads POAScan already makes. No extra upstream calls."""
import time, json, collections
from decimal import Decimal as D
from . import db, analytics as A
from . import segments as S
from .analytics import cached

EPS = D("0.000001")
NODE_RESET_TS = int(__import__("os").environ.get("POASCAN_NODE_RESET_TS", "1792804079"))   # 2026-10-24 01:07:59 UTC, the first tx the node's counters include

def _d(v):
    try: return D(str(v))
    except Exception: return None

def _row(key, label, ours, node, ours_src, ours_at, node_src, node_at, unit="int", reason=None, explained=None, tol=None):
    diff = (ours - node) if ours is not None and node is not None else None
    if ours is None or node is None: state = "node_only" if ours is None else "poascan_only"
    elif abs(diff) <= (tol if tol is not None else 0): state = "match"
    elif explained is not None and abs(diff - explained) <= (tol or 0): state = "explained"
    else: state = "differs"
    num = (lambda v: None if v is None else (float(v) if unit == "poa" else int(v)))
    return dict(key=key, label=label, poascan=num(ours), node=num(node), diff=num(diff), unit=unit, state=state,
                reason=None if state == "match" else reason, poascan_source=ours_src, poascan_as_of=ours_at, node_source=node_src, node_as_of=node_at)

def _iso_ts(s):
    t = A._ts(s) if s else None
    return int(t) if t else None

@cached("reconcile_close", 300)
def per_close():
    """Mint per close from close records against the node's supply step across that close, from archived /api/status reads (bracketed by the node's as_of)."""
    out = []
    for r in A.epoch_rows():
        t = r["close_ts"]; b = a = None
        for x in db.q("SELECT ts, json FROM snaps WHERE kind='status' AND ts BETWEEN ? AND ? ORDER BY ts", (t - 7200, t + 7200)):
            j = json.loads(x["json"]); at = _iso_ts(j.get("as_of")) or x["ts"]; sp = _d(j.get("supply"))
            if sp is None: continue
            if at <= t: b = (at, sp)
            elif a is None: a = (at, sp)
        step = (a[1] - b[1]) if a and b else None
        m = sum((_d(v) or D(0)) for v in (A.epoch_detail(r["epoch"]) or {}).get("rewards", {}).values())
        d = (m - step) if step is not None else None
        out.append(dict(epoch=r["epoch"], close_ts=t, record_mint=float(m), supply_step=float(step) if step is not None else None,
                        diff=float(d) if d is not None else None, state=("no_reads" if step is None else "match" if abs(d) <= D("0.01") else "differs"),
                        before_as_of=b[0] if b else None, after_as_of=a[0] if a else None))
    return out

def _held_why(gap, esc, unl, n):
    parts = ([f"{n} address{'es' if n != 1 else ''} with rewards or transfers missing from /api/agents ({unl:,.6f} POA)"] if n else []) + ([f"{esc:,.6f} POA escrowed in open swap offers"] if esc else [])
    if parts and abs(gap - esc - unl) <= D("0.01"): return " plus ".join(parts)
    return "beyond " + " and ".join(parts) + ", /api/agents and close records are read at different times" if parts else "/api/agents and close records are read at different times"

GR_SRC = "minepoa /api/explorer/grading"

def grading_rows(E, ep_t, pend_rec):
    """1.26.138: POAScan's own figures beside minepoa's grading list (the copy POAScan already reads; no extra calls).
    Pending: basis.pending in the latest close against the list's stats.pending. Seals since close: archived grade-sealed
    txs after the latest close against the list's seals after it. Established: POAScan's fold against the list's established."""
    from . import grading as GR
    if not GR.usable(): return []
    d = GR.current(); at = GR.upstream_as_of(); st = d.get("stats") or {}
    with S.use(S.CURRENT):
        from . import governance as GV
        t = (A.epoch_rows() or [{}])[-1].get("close_ts") or 0
        w, a = S.sql()
        ours_seals = (db.q1("SELECT COUNT(*) AS n FROM txs WHERE type='grade-sealed' AND ts > ?" + w, (t,) + a) or {}).get("n")
        est = [r["address"] for r in GV.standing_rows()["rows"]]
    list_seals = sum(1 for r in d.get("rows") or [] for g in r.get("grades") or [] if int(g.get("ts") or 0) > t)
    tx_t = (db.q1("SELECT MAX(last_seen) AS t FROM txs") or {}).get("t")
    c = GR.conflict_summary(est) or {}
    behind = bool(E and at and at < int(E[-1]["ts"]))
    return [
        _row("grading_pending", "Queue", pend_rec, st.get("pending"), "basis.pending, latest close", ep_t, GR_SRC + " stats.pending", at,
             reason="the grading list was read before the latest close" if behind else "a close POAScan has not read yet, or answers that settled or expired between reads"),
        _row("grading_seals", "Seals since close", ours_seals, list_seals, "grade-sealed txs archived since the latest close", tx_t, GR_SRC + " seals after the latest close", at,
             reason=("seals cast after the list was read" if (ours_seals or 0) > list_seals else "seal txs the archive missed during an outage or a burst, or not archived yet")),
        _row("grading_established", "Established", len(est), len(d.get("established") or []), "POAScan's fold of the close records", ep_t, GR_SRC + " established", at,
             reason=(f"minepoa's grading list shows none; POAScan counts {c.get('conflict', 0)} Agents from the close records and tags them Unconfirmed. Their seals still count toward quorum."
                     if c.get("list_empty") else f"{c.get('conflict', 0)} Agents POAScan counts are not on minepoa's list (Unconfirmed)")),
    ]

@cached("reconcile", 60)
def reconcile():
    st, st_t = db.get_blob("status"); st = st or {}; nw = A.networks(); _, nw_t = db.get_blob("networks")
    # 1.26.91 genesis cut: the node's epochs_closed, txs, final, invalid and checkpoint restarted with segment 2, so those rows
    # compare the current segment only. Supply carried over, so Mined, Burned and Held sum the close records of every segment.
    with S.use(S.CURRENT): E = A.epochs_raw(); ep_t = A.epochs_ts()
    EA = [e for n in S.NUMBERS for e in A.segment_closes(n)]
    node_at = _iso_ts(st.get("as_of")) or st_t; seg0 = S.BY_N[S.CURRENT].get("start_ts") or 0
    acc_t = (db.q1("SELECT MAX(last_seen) AS t FROM accounts") or {}).get("t")
    tx_t = (db.q1("SELECT MAX(last_seen) AS t FROM txs") or {}).get("t")
    mint = sum((_d(v) or D(0)) for e in EA for v in (e.get("rewards") or {}).values())
    # 1.26.122: closes whose rewards later balances do not carry (segments config: excluded at the genesis cut). The node's
    # supply leaves them out, so Mined and Burned read explained by exactly their sum; Held compares carried rewards.
    xs = [(n, e) for n in S.NUMBERS for e in A.segment_closes(n) if S.unconfirmed(int(e.get("epoch", 0)), n)]
    exc = sum((_d(v) or D(0)) for _, e in xs for v in (e.get("rewards") or {}).values())
    exc_lab = " and ".join(f"S{n} E{int(e.get('epoch', 0))}" for n, e in xs)
    exc_why = f"{exc_lab} rewards excluded at the genesis cut ({exc:,.6f} POA)" if xs else None
    pool = sum((_d(e.get("pool")) or D(0)) for e in EA)
    sup = _d(st.get("supply"))
    lagging = (st.get("epochs_closed") or 0) > len(E); behind = bool(E and node_at and node_at < int(E[-1]["ts"]))
    why_mint = ("the node has closed an epoch whose record POAScan has not read yet" if lagging else
                "the node's status read predates the latest close" if behind else "not explained by the public reads")
    held = sum((_d(r["balance_s"]) or D(0)) for r in db.q("SELECT balance_s FROM accounts WHERE balance_s IS NOT NULL AND COALESCE(last_seen, 0) >= ?", (seg0,)))
    esc = sum((_d(v) or D(0)) for v in __import__("poascan.market", fromlist=["x"]).open_escrow())   # open offers, via /api/v1/swaps
    listed = {r["addr"] for r in db.q("SELECT addr FROM accounts WHERE COALESCE(last_seen, 0) >= ?", (seg0,))}   # in the current /api/agents
    unl = collections.defaultdict(D)
    for n in S.NUMBERS:
        for e in A.segment_closes(n):
            if S.unconfirmed(int(e.get("epoch", 0)), n): continue
            for a, v in (e.get("rewards") or {}).items():
                if a not in listed: unl[a] += _d(v) or D(0)
    for a, v in A.segment_transfers().items():   # 1.26.124: transfers to and from addresses not in /api/agents
        if a not in listed: unl[a] += _d(f"{v:.6f}") or D(0)
    unl = {a: v for a, v in unl.items() if v}
    unl_sum = sum(unl.values(), D(0))
    hold = len(A.holders()["rows"])
    acc = (db.q1("SELECT COUNT(*) AS n FROM accounts") or {}).get("n")
    tx = db.q1("SELECT COUNT(*) AS n, SUM(final) AS f FROM txs WHERE segment = ?", (S.CURRENT,)) or {}
    inv = (db.q1("SELECT COUNT(*) AS n FROM invalid_txs WHERE COALESCE(first_seen, 0) >= ?", (seg0,)) or {}).get("n")
    # The node's txs and final counters restarted at a recovery checkpoint (observed: its txs equal the archive's txs since
    # NODE_RESET_TS to 0.1% on Oct 23 and 24, 2026; its final stays at the checkpoint). Both rows read explained, with the
    # time, while the archive since then matches the node's txs within 2% and its final within 10%.
    nt, nf, reset = st.get("txs"), st.get("final"), None
    if nt and NODE_RESET_TS and (tx.get("n") or 0) > nt:
        r = db.q1("SELECT COUNT(*) AS n, SUM(final) AS f FROM txs WHERE ts >= ? AND segment = ?", (NODE_RESET_TS, S.CURRENT)) or {}
        if abs((r.get("n") or 0) - nt) <= max(10, nt * 0.02) and (not nf or abs((r.get("f") or 0) - nf) <= max(10, nf * 0.1)): reset = NODE_RESET_TS
    rs_txt = (f"the node's counters restart at a recovery checkpoint: it counts the archive's txs since "
              f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(reset))}, and its final count stays at the checkpoint") if reset else None
    anc = db.q1("SELECT MAX(height) AS h FROM anchors WHERE segment = ?", (S.CURRENT,)) or {}
    pend_rec = len(((E[-1].get("basis") or {}).get("pending") or {})) if E else None
    pend_ours = A.pending_by_epoch().get("stale_total") if E else None
    rows = [
        _row("mined", "Mined", mint, sup, "sum of rewards in close records", ep_t, "/api/status supply", node_at, "poa",
             exc_why if exc_why and sup is not None and abs(mint - sup - exc) <= EPS * 10 else why_mint, explained=exc if xs else None, tol=EPS * 10),
        _row("burned", "Burned", pool - mint, (pool - sup) if sup is not None else None, "pool minus rewards, close records", ep_t, "pool minus /api/status supply", node_at, "poa",
             "burn is pool minus mined, so it moves with Mined", explained=-exc if xs else None, tol=EPS * 10),
        _row("held", "Held", mint - exc, held, "sum of carried rewards in close records", ep_t, "sum of /api/agents balances", acc_t, "poa",
             _held_why(mint - exc - held, esc, unl_sum, len(unl)), explained=esc + unl_sum, tol=D("0.01")),
        _row("holders", "Holders", hold, st.get("holders"), "balances above 0, plus reward sums missing from /api/agents", acc_t, "/api/status holders", node_at,
             reason="/api/agents and /api/status are read at different times"),
        _row("agents", "Agents", acc, st.get("agents_joined"), "addresses in /api/agents", acc_t, "/api/status agents_joined", node_at,
             reason="/api/agents is read every 15 min, /api/status every minute"),
        _row("epochs", "Closes", len(E), st.get("epochs_closed"), "close records in /api/epochs", ep_t, "/api/status epochs_closed", node_at,
             reason="a close POAScan has not read yet"),
        _row("height", "Height", None, nw.get("height"), None, None, "/api/networks height", nw_t,
             reason="public reads carry no block height per tx, so POAScan has no count of its own"),
        _row("checkpoint", "Checkpoint", anc.get("h"), st.get("checkpoint_height"), "highest anchored height in /api/anchors", (db.get_blob("anchors")[1]), "/api/status checkpoint_height", node_at,
             reason="the checkpoint is ahead of its anchors" if anc.get("h") is not None and st.get("checkpoint_height") and anc["h"] < st["checkpoint_height"] else "an anchor beyond the node's checkpoint"),
        _row("txs", "Txs", tx.get("n"), st.get("txs"), "txs archived", tx_t, "/api/status txs", node_at,
             reason=rs_txt or ("the node counts fewer txs than the archive holds; which txs it counts is not published" if (tx.get("n") or 0) > (st.get("txs") or 0) else "txs missed during outages or bursts"),
             explained=(tx["n"] - nt) if reset else None),
        _row("final", "Final", tx.get("f"), st.get("final"), "archived txs marked final", tx_t, "/api/status final", node_at,
             reason=rs_txt or "moves with Txs; finality is updated only while a tx is still in a feed POAScan reads",
             explained=((tx.get("f") or 0) - nf) if reset else None),
        _row("invalid", "Invalid", inv, st.get("invalid"), "invalid txs seen in /api/txs", (db.get_blob("job:window")[0] or {}).get("ran"), "/api/status invalid", node_at,
             reason="POAScan keeps every invalid tx it has seen; the node figure looks like a current count"),
        _row("pending", "Pending", pend_ours, pend_rec, "Pending panel, carried forward", ep_t, "basis.pending, latest close", ep_t,
             reason="not explained by the public reads"),
    ] + grading_rows(E, ep_t, pend_rec)
    pc = per_close()
    return dict(generated_at=int(time.time()), node_as_of=node_at, node_stale=bool(st.get("stale")), node_stale_age_s=st.get("stale_age_s"),
                matched=sum(r["state"] == "match" for r in rows), explained=sum(r["state"] == "explained" for r in rows),
                differs=sum(r["state"] == "differs" for r in rows), rows=rows, per_close=pc)
