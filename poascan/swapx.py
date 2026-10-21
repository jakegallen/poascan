"""/swaps as a swap panel: pair, Buy/Sell, amount in, estimate out from the live open offers.
POAScan never signs or holds anything: Connect and Swap hand a prefilled prompt to the visitor's agent."""
import json, time
from html import escape as E
from . import views2 as V2, db, analytics as A
from .ui import card, table, poa, utc, rel, addr_link, line

CHAIN_NAME = {"solana": "Solana", "base": "Base", "ethereum": "Ethereum"}
def net_logo(chain):
    """Small round network mark (static/net-*.svg); the only network indicator next to a pair."""
    c = (chain or "").lower(); n = CHAIN_NAME.get(c, c.capitalize() or "Network")
    if c not in CHAIN_NAME: return f'<span class="netl" role="img" aria-label="{E(n)}" title="{E(n)}"></span>'
    return f'<img class="netl" src="/static/net-{c}.svg?v=1" width="16" height="16" alt="{E(n)}" aria-label="{E(n)}" title="{E(n)}">'
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

BUY_TOKEN = ("Buy POA (Proof of Agent, minepoa.com) with up to {IN} {ASSET} on {CHAINNAME}. Check offer {OFFERS} in https://minepoa.com/api/swaps (amount, what it wants, "
             "expiry) and confirm with me. One-call swap-take pays native legs only, so use the coordinated flow in go.md: build and sign the {ASSET} payment to the offer's want.to "
             "from my linked Emblem vault without broadcasting, register it with /api/hosted/swap-intent, poll /api/hosted/swap-receipt until receipt_ready, then "
             "/api/hosted/swap-broadcast and /api/hosted/swap-fill with that ref. I expect about {OUT} POA after the network fee.")

def templates():
    return {"buy": V2._CHECK + BUY + V2._TAIL, "buy_token": V2._CHECK + BUY_TOKEN + V2._TAIL, "sell": V2._CHECK + SELL + V2._TAIL, "connect": V2.WALLET_PROMPT}

def _rows():
    rows = V2.swaps_all()
    return [r for r in rows if r["status"] == "open"], sorted([r for r in rows if r["status"] == "filled" and r["fill_ts"]], key=lambda r: -r["fill_ts"])

# go.md SWAPS: open chains solana, ethereum, base; one-call take pays native SOL/ETH; token legs (USDC on Solana) use the coordinated flow
SUPPORTED = [("SOL", "solana"), ("ETH", "base"), ("ETH", "ethereum"), ("USDC", "solana")]
NATIVE = {"SOL", "ETH"}

def pairs():
    """Every pair the network supports, plus any other pair seen in the book; pairs with live offers first."""
    asks, _ = book(); n = {}
    for o in asks: n[(o["asset"], (o["chain"] or "").lower())] = n.get((o["asset"], (o["chain"] or "").lower()), 0) + 1
    ps = list(SUPPORTED) + [k for k in n if k not in SUPPORTED]
    return sorted(ps, key=lambda k: -n.get(k, 0)), n

def book(asset=None):
    op, fl = _rows(); now = time.time()
    asks = [dict(id=r["offer_id"], poa=r["poa"], want=r["want"], asset=(r["asset"] or "").upper(), chain=r["chain"], exp=r["expires_ts"],
                 px=r["want"] / r["poa"] * 1e6, maker=r["maker"]) for r in op if r["poa"] and r["want"] and (not r["expires_ts"] or r["expires_ts"] > now)]
    last = {}
    for r in fl:
        a = (r["asset"] or "").upper()
        k = a + "|" + (r["chain"] or "").lower()
        if k not in last and r["poa"] and r["want"]: last[k] = r["want"] / r["poa"] * 1e6
    asks.sort(key=lambda o: o["px"])
    return asks, last

def _n(v, d=6): return f"{v:.{d}g}"

def book_html():
    asks, last = book(); nm = V2.names()
    data = json.dumps({"asks": [{k: o[k] for k in ("id", "poa", "want", "asset", "chain", "px")} for o in asks], "last": last}, separators=(",", ":"))
    by = {}
    for o in asks: by.setdefault((o["asset"], (o["chain"] or "").lower()), []).append(o)
    out = []
    for a, ch in sorted(set(SUPPORTED) | set(by)):
        rs = sorted(by.get((a, ch), []), key=lambda o: -o["px"])[-12:]
        tr = "".join(f'<tr class="ask" data-offer="{E(o["id"])}" tabindex="0"><td class="num">{_n(o["px"], 5)}</td><td class="num">{poa(o["poa"])}</td>'
                     f'<td class="num">{o["want"]:g}</td><td class="dim">{f"<span class=xcd data-close={int(o["exp"])}></span>" if o["exp"] else "···"}</td></tr>' for o in rs)
        tr = tr or '<tr><td colspan="4" class="na">···</td></tr>'
        lk = f"{a}|{ch}"
        mid = f'<tr class="mid"><td colspan="4"><span class="num">{_n(last[lk], 5)}</span> <span class="dim small">last fill</span></td></tr>' if lk in last else ""
        out.append(f'<div class="xbk" data-asset="{E(a)}" data-pair="{E(a)}|{E(ch)}"><table class="xbt"><thead><tr><th>{net_logo(ch)}Price · {E(a)} / 1M POA</th><th>Size · POA</th><th>Total · {E(a)}</th><th>Expires</th></tr></thead>'
                   f'<tbody>{tr}{mid}<tr><td colspan="4" class="na">No bids</td></tr></tbody></table></div>')
    return f'<div id="xbook" data-book="{E(data)}">{"".join(out)}</div>'

def fills_html():
    _, fl = _rows(); nm = V2.names()
    rows = [[f'<span class="dim">{utc(r["fill_ts"], "%m-%d %H:%M")}</span>', net_logo(r["chain"]) + f'<span class="num">{_n(r["want"] / r["poa"] * 1e6, 5)}</span> <span class="unit">{E(r["asset"] or "")}</span>',
             poa(r["poa"]), addr_link(r["taker"], nm) if r["taker"] else "···"] for r in fl[:10] if r["poa"] and r["want"]]
    if not rows: return '<div class="xempty na" aria-label="none">-</div>'
    return table(["Time (UTC)", "Price · 1M POA", "Size", "Taker"], rows, cls="xft")

def chart_html():
    rows = [r for r in V2.price_history() if r["price_per_1m_poa"] is not None]
    if not rows: return '<div class="chartbox xempty">No fills yet</div>'
    return V2.price_chart_html()

def panel():
    h = V2.swap_health(); up = h["available"]; pr = pairs(); tpl = templates()
    fee = (A.params().get("swap_fee_bp") or 100)
    pr, cnt = pr
    cn = lambda c: CHAIN_NAME.get(c, c.capitalize())
    opts = "".join(f'<option value="{E(a)}|{E(c)}" data-chain="{E(c)}">POA / {E(a)} · {E(cn(c))}</option>' for a, c in pr)
    lis = "".join(f'<li role="option" tabindex="-1" data-v="{E(a)}|{E(c)}"{" aria-selected=\"true\"" if k == 0 else ""}>{net_logo(c)}<b>POA / {E(a)}</b>'
                  f'<span class="xoc">{(str(cnt[(a, c)]) + (" offers" if cnt[(a, c)] > 1 else " offer")) if cnt.get((a, c)) else ""}</span></li>' for k, (a, c) in enumerate(pr))
    a0, c0 = pr[0]
    btn = (f'<button class="xbtn" type="button" id="xgo" data-up="1">Connect</button>' if up else
           f'<button class="xbtn up" type="button" id="xgo" data-up="0" disabled><i></i>Being upgraded</button>')
    apps = V2._apps(auto_first=True)
    lg = f' <span class="dim">· last good read {rel(h["last_good_read"])}</span>' if h["last_good_read"] else ""
    note = "" if up else f'<p class="xnote" role="status">{V2.UPGRADE_MSG}{lg}</p>'
    return f'''<section class="card xp" id="xp" data-fee="{fee}" data-sellmax="{int(A.supply_split().get("spendable") or 0)}" data-tpl="{E(json.dumps(tpl))}">
<div class="xhd"><div class="xtabs" role="tablist"><button type="button" role="tab" class="on" aria-selected="true" data-side="buy">Buy</button><button type="button" role="tab" aria-selected="false" data-side="sell">Sell</button></div>
<div class="xpair"><button type="button" class="xselb" id="xselb" aria-haspopup="listbox" aria-expanded="false" aria-label="Pair"><span id="xsell">{net_logo(c0)}</span><b id="xselt">POA / {E(a0)}</b></button>
<ul class="xopts" id="xopts" role="listbox" aria-label="Pair" hidden>{lis}</ul><select id="xpair" class="sr-only" tabindex="-1" aria-hidden="true">{opts}</select></div></div>
<div class="xf"><span class="lbl" id="xl-in">You pay</span><div class="xin"><input id="xamt" inputmode="decimal" autocomplete="off" placeholder="0.0" aria-labelledby="xl-in"><span class="xu" id="xu-in">{E(a0)}</span></div></div>
<div class="xarr">{ICON_DOWN}</div>
<div class="xf"><span class="lbl" id="xl-out">You get</span><div class="xin"><output id="xout" aria-labelledby="xl-out">0</output><span class="xu" id="xu-out">POA</span></div></div>
<p class="xhint" id="xhint" hidden></p><dl class="xd"><div><dt>Rate</dt><dd id="xpx">···</dd></div><div><dt>Fee</dt><dd>{fee / 100:g}%</dd></div><div><dt>Route</dt><dd><span id="xroute">···</span> <span class="xvia">{ICON_WALLET}via Emblem</span></dd></div></dl>
{note}{btn}
<p class="xsafe">{ICON_INFO}{SAFE}</p>
<details class="xemb" id="xemb"><summary><picture><source type="image/webp" srcset="/static/emblem-32@2x.webp 2x"><img class="netl embl" src="/static/emblem-32.png" srcset="/static/emblem-32.png 1x, /static/emblem-64.png 2x" width="16" height="16" alt="" aria-hidden="true"></picture><span>Add Emblem Wallet</span></summary><div class="xembb" data-pcard><pre class="pc-text" tabindex="0">{E(tpl["connect"])}</pre>
<span class="lbl jm-l">One click</span><div class="apps oc">{apps}</div><button class="jm-copy sec" type="button" data-copy-prompt>Copy prompt</button></div></details>
<details class="xho" id="xh" hidden><summary>Swap prompt</summary><div class="xhob" data-pcard><pre class="pc-text" tabindex="0"></pre><span class="lbl jm-l">One click</span><div class="apps oc">{apps}</div>
<button class="jm-copy sec" type="button" data-copy-prompt>Copy prompt</button></div></details>
<a class="xself" href="/how-to-buy-poa#self-custody">Self-custody</a>
</section>'''

NA = '<span class="na">-</span>'   # plain hyphen: no price yet
def _usd(v):
    if v is None: return NA
    if v == 0: return "$0"
    for d, u in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= d: return f"${v / d:.3g}{u}"
    return f"${v:,.2f}" if v >= 1 else f"${v:.3g}"

def stats_html():
    m = V2.swap_market()
    items = [("Market Cap", _usd(m["market_cap_usd"])), ("FDV", _usd(m["fdv_usd"])), ("24h Trades", f'{m["trades_24h"]:,}'),
             ("24h Volume", _usd(m["volume_24h_usd"]))]
    return '<div class="xstats" role="group" aria-label="Market">' + "".join(f'<div class="xst"><span class="lbl">{l}</span><b class="num">{v}</b></div>' for l, v in items) + "</div>"

def page():
    op, fl = _rows()
    side = (stats_html() + card(V2.ICON_SWAP + 'Order book', f'<div id="swapsopen">{book_html()}</div>', f'<span class="dim small">{len(op)} open</span>', cls="xcard")
            + card(V2.ICON_SWAP + "Price", chart_html(), cls="xcard")
            + card("Recent fills", fills_html(), f'<span class="dim small">{len(fl)}</span>', cls="xcard"))
    body = ('<h1 class="sr-only">Swap POA</h1>'
            f'<div class="xgrid"><div class="xl">{panel()}</div><div class="xr">{side}</div></div>'
            + card("Activity", V2.history_html(), '<a class="more" href="/api/swaps.csv">CSV →</a>')
            + '<script src="/static/swap.js?v=4" defer></script>')
    return V2.page("Swaps", body, "/swaps")
