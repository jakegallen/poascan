"""Token tab price and volume charts (1.26.354), from the fills POAScan already reads (swapclient price-history).
Chart only: no trade links, no offer book. Both charts share UTC days from the first fill day to the last, so the range
that exists draws with no gap and nothing is projected past the last fill. Price is each day's last fill (a day with no
fill keeps the day before), in the asset most fills used, or USD at fill time only while the guarded reference is shown.
Volume is POA filled that day."""
import time, threading
from . import swapclient as SC

TTL = 300
_c, _lock = {}, threading.Lock()

def _rows():
    out = []
    for r in SC.price_history() or []:
        try: t, px, q = int(r["ts"]), float(r["price_per_1m_poa"]), float(r["poa"])
        except (KeyError, TypeError, ValueError): continue
        if t > 0 and px > 0 and q > 0: out.append(dict(ts=t, px=px, poa=q, asset=(r.get("asset") or "").upper(), oid=r.get("offer_id")))
    return sorted(out, key=lambda x: x["ts"])

def _usd(rows):
    """USD per 1M POA at each fill, only while the reference price is shown and every fill carries its fill_usd."""
    try:
        if not (SC.price() or {}).get("shown"): return None
        fx = {o.get("offer_id"): o.get("fill_usd") for o in SC.offers("filled") or []}
        if not rows or not all(fx.get(r["oid"]) for r in rows): return None
        return [(r["ts"], r["px"] * float(fx[r["oid"]])) for r in rows]
    except Exception:
        return None

def data():
    """{asset, unit, price: [(label, per_1m, day_ts)], volume: [(label, poa, day_ts)], fills, first, last} or None with no fills."""
    now = time.time()
    with _lock:
        hit = _c.get("d")
        if hit and now - hit[0] < TTL: return hit[1]
    rows = _rows(); d = None
    if rows:
        cnt = {}
        for r in rows: cnt[r["asset"]] = cnt.get(r["asset"], 0) + 1
        asset = max(cnt, key=lambda a: (cnt[a], a)); pr = [r for r in rows if r["asset"] == asset]
        usd = _usd(pr)
        fills = usd if usd else [(r["ts"], r["px"]) for r in pr]
        day = lambda t: t - t % 86400
        vol, close = {}, {}
        for r in rows: vol[day(r["ts"])] = vol.get(day(r["ts"]), 0.0) + r["poa"]
        for t, v in fills: close[day(t)] = v   # sorted by ts, so the last fill of the day wins
        d0, d1 = day(rows[0]["ts"]), day(rows[-1]["ts"])
        days = [d0 + 86400 * i for i in range((d1 - d0) // 86400 + 1)]
        lab = lambda t: time.strftime("%b %-d", time.gmtime(t))
        price, last = [], None
        for t in days:
            last = close.get(t, last)
            if last is not None: price.append((lab(t), last, t))
        price, volume = price[-90:], [(lab(t), vol.get(t, 0.0), t) for t in days][-90:]
        d = dict(asset=asset, unit="USD" if usd else asset, price=price, volume=volume, fills=len(rows), first=rows[0]["ts"], last=rows[-1]["ts"])
    with _lock: _c["d"] = (now, d)
    return d

def _pfmt(v): return f"{v:.3g}"

def cards_html():
    """Two chart cards in a grid2, or '' when there are no fills yet."""
    from .ui import card, bars, compact, E
    d = data()
    if not d: return ""
    unit = "$" if d["unit"] == "USD" else d["unit"]
    pc = card(f"Price · {E(unit)} per 1M POA", bars([(l, [v]) for l, v, _ in d["price"]], fmt=_pfmt), id="price")
    vc = card("Daily volume · POA", bars([(l, [v]) for l, v, _ in d["volume"]], fmt=compact), id="volume")
    return f'<div class="grid2 tokcharts">{pc}{vc}</div>'
