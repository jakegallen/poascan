"""/swaps as a swap panel: pair, Buy/Sell, amount in, estimate out from the live open offers.
POAScan never signs or holds anything: Connect and Swap hand a prefilled prompt to the visitor's agent."""
import json, time
from html import escape as E
from . import views2 as V2, db, analytics as A
from .ui import card, table, poa, utc, rel, addr_link, line

CHAIN_NAME = {"solana": "Solana", "base": "Base", "ethereum": "Ethereum"}
ICON_INFO = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.3" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8 7.2v3.6M8 5.1v.1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'
ICON_DOWN = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M4 9l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
ICON_WALLET = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="4" width="12" height="9" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M10.5 8.5h1.5M4 4l6-2" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>'
SAFE = "Only swap through the network. Never send payment outside it."

BUY = ("Buy POA (Proof of Agent, minepoa.com) with up to {IN} {ASSET}. Take offer {OFFERS} from https://minepoa.com/api/swaps: check its amount, "
       "what it wants and its expiry, and confirm with me. Use my Emblem vault linked to my PoA agent (go.md LINK; link it first if it isn't). "
       "Call /api/hosted/swap-take with that offer id; if it returns pending_receipt, re-call until stage is filled. I expect about {OUT} POA after the network fee.")
SELL = ("Sell {IN} of my spendable POA for {OUT} {ASSET} on {CHAINNAME} (PoA = Proof of Agent, minepoa.com). First make sure my Emblem vault is linked "
        "(go.md LINK) and my {CHAINNAME} address shows verified:true in https://minepoa.com/api/chains. Then post the offer with /api/hosted/swap-offer "
        "(chain={CHAIN}, asset={ASSET}, want_amount={OUT}, to = my verified address, ttl in seconds) and tell me the offer id and expiry.")

def templates():
    return {"buy": V2._CHECK + BUY + V2._TAIL, "sell": V2._CHECK + SELL + V2._TAIL, "connect": V2.WALLET_PROMPT}

def _rows():
    rows = V2.swaps_all()
    return [r for r in rows if r["status"] == "open"], sorted([r for r in rows if r["status"] == "filled" and r["fill_ts"]], key=lambda r: -r["fill_ts"])

def pairs():
    op, fl = _rows(); seen = {}
    for r in op + fl:
        a = (r["asset"] or "").upper()
        if a and a not in seen: seen[a] = r["chain"] or ""
    return seen or {"SOL": "solana"}

def book(asset=None):
    op, fl = _rows(); now = time.time()
    asks = [dict(id=r["offer_id"], poa=r["poa"], want=r["want"], asset=(r["asset"] or "").upper(), chain=r["chain"], exp=r["expires_ts"],
                 px=r["want"] / r["poa"] * 1e6, maker=r["maker"]) for r in op if r["poa"] and r["want"] and (not r["expires_ts"] or r["expires_ts"] > now)]
    last = {}
    for r in fl:
        a = (r["asset"] or "").upper()
        if a not in last and r["poa"] and r["want"]: last[a] = r["want"] / r["poa"] * 1e6
    asks.sort(key=lambda o: o["px"])
    return asks, last

def _n(v, d=6): return f"{v:.{d}g}"

def book_html():
    asks, last = book(); nm = V2.names()
    data = json.dumps({"asks": [{k: o[k] for k in ("id", "poa", "want", "asset", "chain", "px")} for o in asks], "last": last}, separators=(",", ":"))
    by = {}
    for o in asks: by.setdefault(o["asset"], []).append(o)
    out = []
    for a in sorted(set(by) | set(last)) or ["SOL"]:
        rs = sorted(by.get(a, []), key=lambda o: -o["px"])[-12:]
        tr = "".join(f'<tr class="ask" data-offer="{E(o["id"])}" tabindex="0"><td class="num">{_n(o["px"], 5)}</td><td class="num">{poa(o["poa"])}</td>'
                     f'<td class="num">{o["want"]:g}</td><td class="dim">{f"<span class=xcd data-close={int(o["exp"])}></span>" if o["exp"] else "···"}</td></tr>' for o in rs)
        tr = tr or '<tr><td colspan="4" class="na">No asks</td></tr>'
        mid = f'<tr class="mid"><td colspan="4"><span class="num">{_n(last[a], 5)}</span> <span class="dim small">last fill</span></td></tr>' if a in last else '<tr class="mid"><td colspan="4" class="dim small">No fills yet</td></tr>'
        out.append(f'<div class="xbk" data-asset="{E(a)}"><table class="xbt"><thead><tr><th>Price · {E(a)} / 1M POA</th><th>Size · POA</th><th>Total · {E(a)}</th><th>Expires</th></tr></thead>'
                   f'<tbody>{tr}{mid}<tr><td colspan="4" class="na">No bids</td></tr></tbody></table></div>')
    return f'<div id="xbook" data-book="{E(data)}">{"".join(out)}</div>'

def fills_html():
    _, fl = _rows(); nm = V2.names()
    rows = [[f'<span class="dim">{utc(r["fill_ts"], "%m-%d %H:%M")}</span>', f'<span class="num">{_n(r["want"] / r["poa"] * 1e6, 5)}</span> <span class="unit">{E(r["asset"] or "")}</span>',
             poa(r["poa"]), addr_link(r["taker"], nm) if r["taker"] else "···"] for r in fl[:10] if r["poa"] and r["want"]]
    if not rows: return '<div class="xempty">No fills yet</div>'
    return table(["Time (UTC)", "Price · 1M POA", "Size", "Taker"], rows, cls="xft")

def chart_html():
    rows = [r for r in V2.price_history() if r["price_per_1m_poa"] is not None]
    if not rows: return '<div class="chartbox xempty">No fills yet</div>'
    return V2.price_chart_html()

def panel():
    h = V2.swap_health(); up = h["available"]; pr = pairs(); tpl = templates()
    fee = (A.params().get("swap_fee_bp") or 100)
    opts = "".join(f'<option value="{E(a)}" data-chain="{E(c)}">POA / {E(a)}</option>' for a, c in pr.items())
    a0 = next(iter(pr))
    btn = (f'<button class="xbtn" type="button" id="xgo" data-up="1">Connect</button>' if up else
           f'<button class="xbtn up" type="button" id="xgo" data-up="0" disabled><i></i>Being upgraded</button>')
    apps = V2._apps(auto_first=True)
    return f'''<section class="card xp" id="xp" data-fee="{fee}" data-tpl="{E(json.dumps(tpl))}">
<div class="xhd"><div class="xtabs" role="tablist"><button type="button" role="tab" class="on" aria-selected="true" data-side="buy">Buy</button><button type="button" role="tab" aria-selected="false" data-side="sell">Sell</button></div>
<label class="xpair"><span class="sr-only">Pair</span><select id="xpair" aria-label="Pair">{opts}</select></label></div>
<div class="xf"><span class="lbl" id="xl-in">You pay</span><div class="xin"><input id="xamt" inputmode="decimal" autocomplete="off" placeholder="0.0" aria-labelledby="xl-in"><span class="xu" id="xu-in">{E(a0)}</span></div></div>
<div class="xarr">{ICON_DOWN}</div>
<div class="xf"><span class="lbl" id="xl-out">You get</span><div class="xin"><output id="xout" aria-labelledby="xl-out">0</output><span class="xu" id="xu-out">POA</span></div></div>
<dl class="xd"><div><dt>Price · 1M POA</dt><dd id="xpx">···</dd></div><div><dt>Fee</dt><dd>{fee / 100:g}%</dd></div><div><dt>Route</dt><dd><span id="xroute">···</span> <span class="xvia">{ICON_WALLET}via Emblem</span></dd></div></dl>
{btn}
<p class="xsafe">{ICON_INFO}{SAFE}</p>
<div class="xho" id="xh" data-pcard hidden><pre class="pc-text" tabindex="0"></pre><span class="lbl jm-l">One click</span><div class="apps oc">{apps}</div>
<button class="jm-copy sec" type="button" data-copy-prompt>Copy prompt</button></div>
<a class="xself" href="/how-to-buy-poa#self-custody">Self-custody</a>
</section>'''

def status_pill():
    h = V2.swap_health()
    if h["available"]: return '<span class="pill live xpill"><i></i>Live</span>'
    t = f' <span class="dim">· {rel(h["last_good_read"])}</span>' if h["last_good_read"] else ""
    return f'<span class="pill xpill up" role="status"><i></i>{V2.UPGRADE_MSG}{t}</span>'

def page():
    op, fl = _rows()
    side = (card(V2.ICON_SWAP + f'Order book <span class="pulse"></span>', f'<div id="swapsopen">{book_html()}</div>', f'<span class="dim small">{len(op)} open</span>', cls="xcard")
            + card(V2.ICON_SWAP + "Price", chart_html(), '<a class="more" href="/api/v1/swaps/price-history.csv">CSV →</a>', cls="xcard")
            + card("Recent fills", fills_html(), f'<span class="dim small">{len(fl)}</span>', cls="xcard"))
    body = (f'<div class="sechead xsh"><h1>Swap</h1>{status_pill()}</div>'
            f'<div class="xgrid"><div class="xl">{panel()}</div><div class="xr">{side}</div></div>'
            + card("Activity", V2.history_html(), '<a class="more" href="/api/swaps.csv">CSV →</a>')
            + '<script src="/static/swap.js?v=2" defer></script>')
    return V2.page("Swaps", body, "/swaps")
