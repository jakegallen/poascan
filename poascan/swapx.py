"""/swaps as a swap panel: pair, Buy/Sell, amount in, estimate out from the live open offers.
POAScan never signs or holds anything: Connect and Swap hand a prefilled prompt to the visitor's agent."""
import json, time, statistics
from html import escape as E
from . import views2 as V2, db, analytics as A
from .ui import card, table, poa, utc, rel, addr_link, line, plain

CHAIN_NAME = {"solana": "Solana", "base": "Base", "ethereum": "Ethereum"}
def net_logo(chain):
    """Small round network mark (static/net-*.svg); the only network indicator next to a pair."""
    c = (chain or "").lower(); n = CHAIN_NAME.get(c, c.capitalize() or "Network")
    if c not in CHAIN_NAME: return f'<span class="netl" role="img" aria-label="{E(n)}" title="{E(n)}"></span>'
    return f'<img class="netl" src="/static/net-{c}.svg?v=1" width="16" height="16" alt="{E(n)}" aria-label="{E(n)}" title="{E(n)}">'
ICON_INFO = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.3" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8 7.2v3.6M8 5.1v.1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'
ICON_DOWN = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M4 9l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
ICON_WALLET = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="4" width="12" height="9" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M10.5 8.5h1.5M4 4l6-2" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>'
SAFE = "Never send payment outside the network."

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
    c = V2._check()
    return {"buy": c + BUY + V2._TAIL, "buy_token": c + BUY_TOKEN + V2._TAIL, "sell": c + SELL + V2._TAIL, "connect": V2.WALLET_PROMPT}

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

def _n(v, d=6): return plain(v, d)

def book_html():
    asks, last = book(); nm = V2.names()
    data = json.dumps({"asks": [{k: o[k] for k in ("id", "poa", "want", "asset", "chain", "px")} for o in asks], "last": last}, separators=(",", ":"))
    by = {}
    for o in asks: by.setdefault((o["asset"], (o["chain"] or "").lower()), []).append(o)
    out = []
    for a, ch in sorted(set(SUPPORTED) | set(by)):
        rs = sorted(by.get((a, ch), []), key=lambda o: -o["px"])[-12:]
        tr = "".join(f'<tr class="ask" data-offer="{E(o["id"])}" tabindex="0"><td class="num">{_n(o["px"], 5)}</td><td class="num">{poa(o["poa"])}</td>'
                     f'<td class="num">{plain(o["want"], 8)}</td><td class="dim">{f"<span class=xcd data-close={int(o["exp"])}></span>" if o["exp"] else "···"}</td></tr>' for o in rs)
        tr = tr or '<tr><td colspan="4" class="na">···</td></tr>'
        lk = f"{a}|{ch}"
        mid = f'<tr class="mid"><td colspan="4"><span class="num">{_n(last[lk], 5)}</span> <span class="dim small">last fill</span></td></tr>' if lk in last else ""
        out.append(f'<div class="xbk" data-asset="{E(a)}" data-pair="{E(a)}|{E(ch)}"><table class="xbt"><thead><tr><th>{net_logo(ch)}Price · {E(a)} / 1M POA</th><th>Size · POA</th><th>Total · {E(a)}</th><th>Expires</th></tr></thead>'
                   f'<tbody>{tr}{mid}<tr><td colspan="4" class="na">No bids</td></tr></tbody></table></div>')
    return f'<div id="xbook" data-book="{E(data)}">{"".join(out)}</div>'

def fills_html():
    _, fl = _rows(); nm = V2.names()
    rows = [[f'<span class="dim">{utc(r["fill_ts"], "%m-%d %H:%M")}</span>', net_logo(r["chain"]) + f'<span class="num">{_n(r["want"] / r["poa"] * 1e6, 5)}</span> <span class="unit">{E(r["asset"] or "")}</span>',
             poa(r["poa"]), addr_link(r["taker"], nm) if r["taker"] else "···",
             V2._ext(r["chain"], r.get("ext_ref"), tx=True)] for r in fl[:10] if r["poa"] and r["want"]]
    if not rows: return '<div class="xempty na" aria-label="none">-</div>'
    return table(["Time (UTC)", "Price · 1M POA", "Size", "Taker", "Payment"], rows, cls="xft")

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
    btn = ('<button class="xbtn soon" type="button" id="xgo" data-up="0" aria-disabled="true">Coming soon</button>' if not V2.SWAPS_LIVE else
           '<button class="xbtn" type="button" id="xgo" data-up="1">Connect</button>' if up else
           '<button class="xbtn up" type="button" id="xgo" data-up="0" disabled><i></i>Being upgraded</button>')
    apps, apps2 = V2._apps(cls="oc"), V2._apps(cls="oc")
    emb_box = V2._J.pbox('<pre class="pc-text" tabindex="0">' + E(tpl["connect"]) + '</pre>')
    swap_box = V2._J.pbox('<pre class="pc-text" tabindex="0"></pre>')
    lg = f' <span class="dim">· last good read {rel(h["last_good_read"])}</span>' if h["last_good_read"] else ""
    note = "" if up or not V2.SWAPS_LIVE else f'<p class="xnote" role="status">{V2.UPGRADE_MSG}{lg}</p>'
    return f'''<section class="card xp" id="xp" data-fee="{fee}" data-sellmax="{int(A.supply_split().get("spendable") or 0)}" data-tpl="{E(json.dumps(tpl))}">
<div class="xhd"><div class="xtabs" role="tablist"><button type="button" role="tab" class="on" aria-selected="true" data-side="buy">Buy</button><button type="button" role="tab" aria-selected="false" data-side="sell">Sell</button></div>
<div class="xpair"><button type="button" class="xselb" id="xselb" aria-haspopup="listbox" aria-expanded="false" aria-label="Pair"><span id="xsell">{net_logo(c0)}</span><b id="xselt">POA / {E(a0)}</b></button>
<ul class="xopts" id="xopts" role="listbox" aria-label="Pair" hidden>{lis}</ul><select id="xpair" class="sr-only" tabindex="-1" aria-hidden="true">{opts}</select></div></div>
<div class="xf"><span class="lbl" id="xl-in">You pay</span><div class="xin"><input id="xamt" inputmode="decimal" autocomplete="off" placeholder="0.0" aria-labelledby="xl-in"><span class="xu" id="xu-in">{E(a0)}</span></div></div>
<div class="xarr">{ICON_DOWN}</div>
<div class="xf"><span class="lbl" id="xl-out">You get</span><div class="xin"><output id="xout" aria-labelledby="xl-out">0</output><span class="xu" id="xu-out">POA</span></div></div>
<p class="xhint" id="xhint" hidden></p><dl class="xd"><div><dt>Rate</dt><dd id="xpx">···</dd></div><div><dt>Fee</dt><dd>{fee / 100:g}%</dd></div><div><dt>Route</dt><dd><span id="xroute">···</span> <span class="xvia">{ICON_WALLET}via Emblem</span></dd></div></dl>
{note}{btn}
<div class="xembr"><p class="xsafe">{ICON_INFO}<span>{SAFE}</span></p><details class="xemb" id="xemb"><summary aria-label="Add Emblem Wallet"><picture><source type="image/webp" srcset="/static/emblem-32@2x.webp 2x"><img class="netl embl" src="/static/emblem-32.png" srcset="/static/emblem-32.png 1x, /static/emblem-64.png 2x" width="16" height="16" alt="" aria-hidden="true"></picture><span>Add Wallet</span></summary><div class="xembb" data-pcard>{emb_box}
<span class="lbl jm-l">One click</span>{apps}</div></details></div>
<details class="xho" id="xh" hidden><summary>Swap prompt</summary><div class="xhob" data-pcard>{swap_box}<span class="lbl jm-l">One click</span>{apps2}</div></details>
</section>'''

# ---------------- price: the one POA/USD reference. The swap module owns it; the explorer only reads it. ----------------
PRICE_WINDOW_S = 7 * 86400          # no fill in this window: no USD anywhere
THIN_FILLS, THIN_USD = 5, 100.0     # fewer fills, or less volume, in the window: thin (2 significant figures)
MEDIAN_N = 5                        # with this many fills in the window, the median of the last 5 replaces the last fill

def _ref(r):
    """USD per unit of the asset a fill paid in: USDC at 1, else the reference recorded at fill time, else the current one."""
    a = (r.get("asset") or "").upper()
    if a == "USDC": return 1.0
    return r.get("fill_usd") or V2.fx().get(a) or None

def sig(v, n):
    return float(f"{v:.{n}g}") if v else v

@A.cached("swap_price", 30)
def price():
    """POA in USD from filled swaps only; open offers (asks) are never used. See /about#market."""
    now = time.time(); fx = V2.fx()
    fl = sorted((r for r in V2.swaps_all() if r["status"] == "filled" and r["fill_ts"] and r["poa"] and r["want"]), key=lambda r: -r["fill_ts"])
    pts = [(r, r["want"] / r["poa"] * u, r["want"] * u) for r in fl for u in [_ref(r)] if u]
    win = [p for p in pts if p[0]["fill_ts"] >= now - PRICE_WINDOW_S]
    vol = sum(p[2] for p in win); last = int(fl[0]["fill_ts"]) if fl else None
    out = dict(usd_per_poa=None, usd_per_1m_poa=None, shown=False, thin=None, basis=None, sig_figs=None,
               fills_7d=len(win), volume_7d_usd=round(vol, 2), last_fill_ts=last, last_fill_age_s=int(now - last) if last else None,
               window_s=PRICE_WINDOW_S, thin_below=dict(fills=THIN_FILLS, volume_usd=THIN_USD), median_of=MEDIAN_N,
               asks_used=False, usd_ref=fx.get("src") or "CoinGecko", method="https://poascan.io/about#market")
    if not win: return out
    thin = len(win) < THIN_FILLS or vol < THIN_USD
    if len(win) >= MEDIAN_N: px, basis = statistics.median(p[1] for p in win[:MEDIAN_N]), "median_last_5_fills"
    else: px, basis = win[0][1], "last_fill"
    n = 2 if thin else 3
    return dict(out, usd_per_poa=sig(px, n), usd_per_1m_poa=sig(px * 1e6, n), shown=True, thin=thin, basis=basis, sig_figs=n)

def money(v, n=3):
    """$ with n significant figures: $13K, $710, $0.11."""
    if v is None: return None
    v = sig(v, n)
    for d, u in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= d: return f"${plain(v / d, n)}{u}"
    return f"${plain(v, n)}"

def usd_of(amount):
    """Muted ≈$ beside a POA amount, or "" when no price is shown. Same figure rounding as the price itself."""
    p = price()
    if not p["shown"] or amount is None: return ""
    try: v = float(amount) * p["usd_per_poa"]
    except (TypeError, ValueError): return ""
    return f'<span class="usd">≈{money(v, p["sig_figs"])}</span>'

def usd_src():
    """One label per page that shows ≈$: links to the method on /about. "" when no price is shown."""
    p = price()
    if not p["shown"]: return ""
    t = "thin" if p["thin"] else "ref"
    return f'<a class="usdsrc{" thin" if p["thin"] else ""}" href="/about#market">USD · {t}</a>'

NA = '<span class="na">-</span>'   # plain hyphen: no price yet
def _usd(v):
    if v is None: return NA
    if v == 0: return "$0"
    for d, u in ((1e9, "B"), (1e6, "M")):
        if v >= d: return f"${plain(v / d, 3)}{u}"
    return f"${v:,.0f}" if v >= 1000 else f"${v:,.2f}" if v >= 0.01 else f"${plain(v, 2)}"

def stats_html():
    m = V2.swap_market()
    tr, vo = (("Trades", m["trades_all_time"]), ("Volume", m["volume_all_time_usd"])) if V2.STATS_WINDOW == "all" else \
             (("24h Trades", m["trades_24h"]), ("24h Volume", m["volume_24h_usd"]))
    p = price(); fmt = lambda v: NA if v is None else (money(v, p["sig_figs"]) if p["shown"] else _usd(v))
    items = [("Market Cap", fmt(m["market_cap_usd"])), ("FDV", fmt(m["fdv_usd"])), (tr[0], f'{tr[1]:,}'), (vo[0], _usd(vo[1]))]
    return ('<div class="xstats" role="group" aria-label="Market">' + "".join(f'<div class="xst"><span class="lbl">{l}</span><b class="num">{v}</b></div>' for l, v in items)
            + "</div>")

def page():
    op, fl = _rows()
    side = (stats_html() + card(V2.ICON_SWAP + 'Order book', f'<div id="swapsopen">{book_html()}</div>', f'<span class="dim small">{len(op)} open</span>', cls="xcard")
            + card(V2.ICON_SWAP + "Price", chart_html(), usd_src(), cls="xcard")
            + card("Recent fills", fills_html(), f'<span class="dim small">{len(fl)}</span>', cls="xcard"))
    body = ('<h1 class="sr-only">Swap POA</h1>'
            f'<div class="xgrid"><div class="xl">{panel()}</div><div class="xr">{side}</div></div>'
            + card("Activity", V2.history_html(), '<a class="more" href="/api/swaps.csv">CSV →</a>')
            + '<script src="/static/swap.js?v=6" defer></script>')
    return V2.page("Swaps", body, "/swaps")
