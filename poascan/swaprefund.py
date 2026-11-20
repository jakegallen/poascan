"""Read-only auto-refund view (1.26.409). Rows come from a named field on close records once that field exists.
CLOSE_FIELD stays unset until the field is named on a public close; this module does not guess it. Cap 20."""
from . import analytics as A
from .ui import E, addr_link, intc, poa, table, utc, na, card, flag

# Set to the close-record field name when a public close names refunds. None: show the empty state, never invent rows.
CLOSE_FIELD = None
PAGE = 20

def swap_v2_state(p=None, now=None):
    """'Shipped, not active' until /api/params carries swap_v2_from_ts. Never reports the feature as on before that key exists.
    After the key appears, 'Active from <time>' once the timestamp has passed, else still 'Shipped, not active'."""
    import time
    if p is None: p = A.params()
    ts = (p or {}).get("swap_v2_from_ts") if isinstance(p, dict) else None
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return dict(state="shipped", label="Shipped, not active", from_ts=None)
    now = now if now is not None else time.time()
    if now < ts:
        return dict(state="shipped", label="Shipped, not active", from_ts=int(ts))
    return dict(state="active", label="Active from " + utc(ts, "%b %d %H:%M"), from_ts=int(ts))

def _rows_from_close(rec, field):
    """Offer rows under one close's named field. Accepts a list of dicts; unknown shapes are skipped, not guessed."""
    blob = rec.get(field) if isinstance(rec, dict) else None
    if blob is None and isinstance(rec.get("basis"), dict):
        blob = rec["basis"].get(field)
    if not isinstance(blob, list):
        return []
    epoch = rec.get("epoch")
    height = rec.get("height") or rec.get("close_height") or rec.get("checkpoint_height")
    out = []
    for r in blob:
        if not isinstance(r, dict):
            continue
        offer = r.get("offer_id") or r.get("offer") or r.get("id")
        maker = r.get("maker") or r.get("addr") or r.get("address")
        amount = r.get("amount") or r.get("poa") or r.get("qty")
        txid = r.get("refund_txid") or r.get("txid")
        h = r.get("close_height") or r.get("height") or height
        if not offer and not maker:
            continue
        out.append(dict(offer=offer, maker=maker, amount=amount, close_height=h, refund_txid=txid, epoch=epoch,
                        close_ts=rec.get("close_ts") or rec.get("ts")))
    return out

def refunds(limit=PAGE):
    """Up to `limit` auto-refund rows, newest close first. Empty while CLOSE_FIELD is unset or no close carries it."""
    if not CLOSE_FIELD:
        return []
    out = []
    for rec in reversed(list(A.epoch_rows() or [])):
        out.extend(_rows_from_close(rec, CLOSE_FIELD))
        if len(out) >= limit:
            break
    return out[:limit]

def fee_text(p=None):
    """The swap fee, once, from swap_fee_bp (100 is 1%)."""
    if p is None: p = A.params()
    bp = (p or {}).get("swap_fee_bp") if isinstance(p, dict) else None
    try: bp = int(bp)
    except (TypeError, ValueError): return None
    if bp % 100 == 0: return f"{bp // 100}%"
    return f"{bp / 100:g}%"

def page_html():
    """/swaps explorer body: fee, swap v2 state, auto-refund rows or the empty state. Trading stays on POASwap."""
    p = A.params()
    v2 = swap_v2_state(p)
    fee = fee_text(p)
    ev = p.get("escrow_autorefund_from_epoch") if isinstance(p, dict) else None
    per = p.get("escrow_autorefund_per_close") if isinstance(p, dict) else None
    figs = []
    if fee: figs.append(("Fee", fee))
    figs.append(("v2", v2["label"]))
    if isinstance(ev, int): figs.append(("From", f"E{ev}"))
    if isinstance(per, int): figs.append(("Per close", f"{per:,}"))
    from . import kit as KIT
    head = KIT.figs(figs) if figs else ""
    rows = refunds()
    names = A.forum_names()
    if not rows:
        body = na("No close has named refunds yet.")
    else:
        def maker(r):
            a = r.get("maker")
            return addr_link(a, names, (8, 6)) if a else "···"
        def offer(r):
            o = r.get("offer")
            return f'<span class="mono">{E(str(o)[:16])}</span>' if o else "···"
        def tx(r):
            t = r.get("refund_txid")
            return f'<a class="mono" href="/tx/{E(t)}">{E(str(t)[:10])}...</a>' if t else "···"
        body = table(["Offer", "Maker", "Amount", "Close height", "Refund tx"],
                     [[offer(r), maker(r), poa(r["amount"]) if r.get("amount") is not None else "···",
                       intc(r["close_height"]) if r.get("close_height") is not None else "···", tx(r)]
                      for r in rows], cls="wrapt")
    return head + card("Refunds", body)

def page():
    from . import views as V
    return V.page("Swaps", '<div class="sechead"><h1>Swaps</h1></div>' + page_html(), "/network")
