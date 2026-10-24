"""POAScan's own totals beside the node's reported numbers, from reads POAScan already makes. No extra upstream calls."""
import time, json, collections
from decimal import Decimal as D
from . import db, analytics as A
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
    parts = ([f"{n} rewarded address{'es' if n != 1 else ''} missing from /api/agents ({unl:,.6f} POA)"] if n else []) + ([f"{esc:,.6f} POA escrowed in open swap offers"] if esc else [])
    if parts and abs(gap - esc - unl) <= D("0.01"): return " plus ".join(parts)
    return "beyond " + " and ".join(parts) + ", /api/agents and close records are read at different times" if parts else "/api/agents and close records are read at different times"

@cached("reconcile", 60)
def reconcile():
    st, st_t = db.get_blob("status"); st = st or {}; nw = A.networks(); _, nw_t = db.get_blob("networks")
    E = A.epochs_raw(); ep_t = (db.q1("SELECT ts FROM blobs WHERE kind='epochs'") or {"ts": None})["ts"]; node_at = _iso_ts(st.get("as_of")) or st_t
    acc_t = (db.q1("SELECT MAX(last_seen) AS t FROM accounts") or {}).get("t")
    tx_t = (db.q1("SELECT MAX(last_seen) AS t FROM txs") or {}).get("t")
    mint = sum((_d(v) or D(0)) for e in E for v in (e.get("rewards") or {}).values())
    pool = sum((_d(e.get("pool")) or D(0)) for e in E)
    sup = _d(st.get("supply"))
    lagging = (st.get("epochs_closed") or 0) > len(E); behind = bool(E and node_at and node_at < int(E[-1]["ts"]))
    why_mint = ("the node has closed an epoch whose record POAScan has not read yet" if lagging else
                "the node's status read predates the latest close" if behind else "not explained by the public reads")
    held = sum((_d(r["balance_s"]) or D(0)) for r in db.q("SELECT balance_s FROM accounts WHERE balance_s IS NOT NULL"))
    esc = sum((_d(v) or D(0)) for v in __import__("poascan.market", fromlist=["x"]).open_escrow())   # open offers, via /api/v1/swaps
    listed = {r["addr"] for r in db.q("SELECT addr FROM accounts")}
    unl = collections.defaultdict(D)
    for e in E:
        for a, v in (e.get("rewards") or {}).items():
            if a not in listed: unl[a] += _d(v) or D(0)
    unl_sum = sum(unl.values(), D(0))
    hold = len(A.holders()["rows"])
    acc = (db.q1("SELECT COUNT(*) AS n FROM accounts") or {}).get("n")
    tx = db.q1("SELECT COUNT(*) AS n, SUM(final) AS f FROM txs") or {}
    inv = (db.q1("SELECT COUNT(*) AS n FROM invalid_txs") or {}).get("n")
    # The node's txs and final counters restarted at a recovery checkpoint (observed: its txs equal the archive's txs since
    # NODE_RESET_TS to 0.1% on Oct 23 and 24, 2026; its final stays at the checkpoint). Both rows read explained, with the
    # time, while the archive since then matches the node's txs within 2% and its final within 10%.
    nt, nf, reset = st.get("txs"), st.get("final"), None
    if nt and NODE_RESET_TS and (tx.get("n") or 0) > nt:
        r = db.q1("SELECT COUNT(*) AS n, SUM(final) AS f FROM txs WHERE ts >= ?", (NODE_RESET_TS,)) or {}
        if abs((r.get("n") or 0) - nt) <= max(10, nt * 0.02) and (not nf or abs((r.get("f") or 0) - nf) <= max(10, nf * 0.1)): reset = NODE_RESET_TS
    rs_txt = (f"the node's counters restart at a recovery checkpoint: it counts the archive's txs since "
              f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(reset))}, and its final count stays at the checkpoint") if reset else None
    anc = db.q1("SELECT MAX(height) AS h FROM anchors") or {}
    pend_rec = len(((E[-1].get("basis") or {}).get("pending") or {})) if E else None
    pend_ours = A.pending_by_epoch().get("stale_total") if E else None
    rows = [
        _row("mined", "Mined", mint, sup, "sum of rewards in close records", ep_t, "/api/status supply", node_at, "poa", why_mint, tol=EPS * 10),
        _row("burned", "Burned", pool - mint, (pool - sup) if sup is not None else None, "pool minus rewards, close records", ep_t, "pool minus /api/status supply", node_at, "poa",
             "burn is pool minus mined, so it moves with Mined", tol=EPS * 10),
        _row("held", "Held", mint, held, "sum of rewards in close records", ep_t, "sum of /api/agents balances", acc_t, "poa",
             _held_why(mint - held, esc, unl_sum, len(unl)), explained=esc + unl_sum, tol=D("0.01")),
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
    ]
    pc = per_close()
    return dict(generated_at=int(time.time()), node_as_of=node_at, node_stale=bool(st.get("stale")), node_stale_age_s=st.get("stale_age_s"),
                matched=sum(r["state"] == "match" for r in rows), explained=sum(r["state"] == "explained" for r in rows),
                differs=sum(r["state"] == "differs" for r in rows), rows=rows, per_close=pc)
