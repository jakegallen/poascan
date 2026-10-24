"""The swap page: pair panel (Buy | Sell, estimate from the live book, Coming soon until SWAPS_LIVE), stats row, order book,
price chart, recent fills and activity. Renders through host.page; links come from config, so the same page works at
poascan.io/swaps or at the root of a standalone site."""
import json
from . import host as H, config as C, market as M, store as S, prompts as P
from .host import E, card, table, poa, utc, rel, addr_link, tx_link, line, plain, short, chart_skel, _ic
from .prompts import SAFE

CHAIN_NAME = {"solana": "Solana", "base": "Base", "ethereum": "Ethereum"}
def net_logo(chain):
    """Small round network mark (static/net-*.svg); the only network indicator next to a pair."""
    c = (chain or "").lower(); n = CHAIN_NAME.get(c, c.capitalize() or "Network")
    if c not in CHAIN_NAME: return f'<span class="netl" role="img" aria-label="{E(n)}" title="{E(n)}"></span>'
    return f'<img class="netl" src="/static/net-{c}.svg?v=1" width="16" height="16" alt="{E(n)}" aria-label="{E(n)}" title="{E(n)}">'
ICON_INFO = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.3" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8 7.2v3.6M8 5.1v.1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'
ICON_DOWN = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M4 9l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
ICON_WALLET = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="4" width="12" height="9" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M10.5 8.5h1.5M4 4l6-2" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>'

ICON_SWAP = _ic('<path d="M8 10h7.5l-2-2M16 14H8.5l2 2" stroke-linecap="round" stroke-linejoin="round"/>')

EXPL = {"solana": ("https://solscan.io/account/", "https://solscan.io/tx/"),
        "base": ("https://basescan.org/address/", "https://basescan.org/tx/"),
        "ethereum": ("https://etherscan.io/address/", "https://etherscan.io/tx/")}


def _pfmt(per_m, usd, asset):
    if per_m is None: return '<span class="na">···</span>'
    s = f'<span class="num">{plain(per_m, 6)}</span> <span class="unit">{E(asset or "")}</span>'
    if usd is not None: s += f' <span class="dim">· ${plain(usd, 4)}</span>'
    return s

def _ext(chain, addr, tx=False):
    if not addr: return '<span class="na">···</span>'
    e = EXPL.get((chain or "").lower())
    if not e: return f'<span class="mono">{E(short(addr, 6, 4))}</span>'
    return f'<a class="mono" href="{e[1 if tx else 0]}{E(addr)}" target="_blank" rel="noopener noreferrer">{E(short(addr, 6, 4))} ↗</a>'


def money(v, n=3):
    """$ with n significant figures: $13K, $710, $0.11."""
    if v is None: return None
    v = M.sig(v, n)
    for d, u in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= d: return f"${plain(v / d, n)}{u}"
    return f"${plain(v, n)}"


def usd_src():
    """One label per page that shows ≈$: links to the USD method. "" when no price is shown."""
    p = M.price()
    if not p["shown"]: return ""
    t = "thin" if p["thin"] else "ref"
    return f'<a class="usdsrc{" thin" if p["thin"] else ""}" href="{C.link(C.METHOD_URL)}">USD · {t}</a>'


def _n(v, d=6): return plain(v, d)

def book_html():
    asks, last = M.book()
    data = json.dumps({"asks": [{k: o[k] for k in ("id", "poa", "want", "asset", "chain", "px")} for o in asks], "last": last}, separators=(",", ":"))
    by = {}
    for o in asks: by.setdefault((o["asset"], (o["chain"] or "").lower()), []).append(o)
    out = []
    for a, ch in sorted(set(M.SUPPORTED) | set(by)):
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
    _, fl = M.rows(); nm = H.names()
    rows = [[f'<span class="dim">{utc(r["fill_ts"], "%m-%d %H:%M")}</span>', net_logo(r["chain"]) + f'<span class="num">{_n(r["want"] / r["poa"] * 1e6, 5)}</span> <span class="unit">{E(r["asset"] or "")}</span>',
             poa(r["poa"]), addr_link(r["taker"], nm) if r["taker"] else "···",
             _ext(r["chain"], r.get("ext_ref"), tx=True)] for r in fl[:10] if r["poa"] and r["want"]]
    if not rows: return '<div class="xempty na" aria-label="none">-</div>'
    return table(["Time (UTC)", "Price · 1M POA", "Size", "Taker", "Payment"], rows, cls="xft", pri=(0, 1, 2))

def chart_html():
    rows = [r for r in M.price_history() if r["price_per_1m_poa"] is not None]
    if not rows: return '<div class="chartbox xempty">No fills yet</div>'
    return price_chart_html()


def panel():
    h = M.swap_health(); up = h["available"]; pr = M.pairs(); tpl = P.templates()
    fee = (H.params().get("swap_fee_bp") or 100)
    pr, cnt = pr
    cn = lambda c: CHAIN_NAME.get(c, c.capitalize())
    opts = "".join(f'<option value="{E(a)}|{E(c)}" data-chain="{E(c)}">POA / {E(a)} · {E(cn(c))}</option>' for a, c in pr)
    lis = "".join(f'<li role="option" tabindex="-1" data-v="{E(a)}|{E(c)}"{" aria-selected=\"true\"" if k == 0 else ""}>{net_logo(c)}<b>POA / {E(a)}</b>'
                  f'<span class="xoc">{(str(cnt[(a, c)]) + (" offers" if cnt[(a, c)] > 1 else " offer")) if cnt.get((a, c)) else ""}</span></li>' for k, (a, c) in enumerate(pr))
    a0, c0 = pr[0]
    btn = ('<button class="xbtn soon" type="button" id="xgo" data-up="0" aria-disabled="true">Coming soon</button>' if not C.SWAPS_LIVE else
           '<button class="xbtn" type="button" id="xgo" data-up="1">Connect</button>' if up else
           '<button class="xbtn up" type="button" id="xgo" data-up="0" disabled><i></i>Being upgraded</button>')
    apps, apps2 = H.apps("oc"), H.apps("oc")
    emb_box = H.pbox('<pre class="pc-text" tabindex="0"' + (getattr(H, "reg_attrs", None) or (lambda **k: ""))(**P.WALLET_REG) + '>' + E(tpl["connect"]) + '</pre>')
    swap_box = H.pbox('<pre class="pc-text" tabindex="0"></pre>')
    lg = f' <span class="dim">· last good read {rel(h["last_good_read"])}</span>' if h["last_good_read"] else ""
    note = "" if up or not C.SWAPS_LIVE else f'<p class="xnote" role="status">{M.UPGRADE_MSG}{lg}</p>'
    return f'''<section class="card xp" id="xp" data-fee="{fee}" data-sellmax="{int(H.circulating() or 0)}" data-tpl="{E(json.dumps(tpl))}">
<div class="xhd"><div class="xtabs" role="tablist"><button type="button" role="tab" class="on" aria-selected="true" data-side="buy">Buy</button><button type="button" role="tab" aria-selected="false" data-side="sell">Sell</button></div>
<div class="xpair"><button type="button" class="xselb" id="xselb" aria-haspopup="listbox" aria-expanded="false" aria-label="Pair"><span id="xsell">{net_logo(c0)}</span><b id="xselt">POA / {E(a0)}</b></button>
<ul class="xopts" id="xopts" role="listbox" aria-label="Pair" hidden>{lis}</ul><select id="xpair" class="sr-only" tabindex="-1" aria-hidden="true">{opts}</select></div></div>
<div class="xf"><span class="lbl" id="xl-in">You pay</span><div class="xin"><input id="xamt" inputmode="decimal" autocomplete="off" placeholder="0.0" aria-labelledby="xl-in"><span class="xu" id="xu-in">{E(a0)}</span></div></div>
<div class="xarr">{ICON_DOWN}</div>
<div class="xf"><span class="lbl" id="xl-out">You get</span><div class="xin"><output id="xout" aria-labelledby="xl-out">0</output><span class="xu" id="xu-out">POA</span></div></div>
<p class="xhint" id="xhint" hidden></p><dl class="xd"><div><dt>Rate</dt><dd id="xpx">···</dd></div><div><dt>Fee</dt><dd>{fee / 100:g}%</dd></div><div><dt>Route</dt><dd><span id="xroute">···</span> <span class="xvia">{ICON_WALLET}via Emblem</span></dd></div></dl>
{note}{btn}
<div class="xembr"><p class="xsafe">{ICON_INFO}<span>{SAFE}</span></p><details class="xemb" id="xemb"><summary aria-label="Add Emblem Wallet"><picture><source type="image/webp" srcset="/static/emblem-32@2x.webp 2x"><img class="netl embl" src="/static/emblem-32.png" srcset="/static/emblem-32.png 1x, /static/emblem-64.png 2x" width="16" height="16" alt="" aria-hidden="true"></picture><span>Add Wallet</span></summary><div class="xembb" data-pcard data-pid="wallet">{emb_box}
<span class="lbl jm-l">One click</span>{apps}</div></details></div>
<details class="xho" id="xh" hidden><summary>Swap prompt</summary><div class="xhob" data-pcard data-pid="swap">{swap_box}<span class="lbl jm-l">One click</span>{apps2}</div></details>
</section>'''


NA = '<span class="na">-</span>'   # plain hyphen: no price yet
def _usd(v):
    if v is None: return NA
    if v == 0: return "$0"
    for d, u in ((1e9, "B"), (1e6, "M")):
        if v >= d: return f"${plain(v / d, 3)}{u}"
    return f"${v:,.0f}" if v >= 1000 else f"${v:,.2f}" if v >= 0.01 else f"${plain(v, 2)}"

def stats_html():
    m = M.swap_market()
    tr, vo = (("Trades", m["trades_all_time"]), ("Volume", m["volume_all_time_usd"])) if C.STATS_WINDOW == "all" else \
             (("24h Trades", m["trades_24h"]), ("24h Volume", m["volume_24h_usd"]))
    p = M.price(); fmt = lambda v: NA if v is None else (money(v, p["sig_figs"]) if p["shown"] else _usd(v))
    items = [("Market Cap", fmt(m["market_cap_usd"])), ("FDV", fmt(m["fdv_usd"])), (tr[0], f'{tr[1]:,}'), (vo[0], _usd(vo[1]))]
    return ('<div class="xstats" role="group" aria-label="Market">' + "".join(f'<div class="xst"><span class="lbl">{l}</span><b class="num">{v}</b></div>' for l, v in items)
            + "</div>")


def history_html():
    nm = H.names(); ev = []
    for r in ST.correct([dict(x) for x in S.swaps_all()]):
        pm, usd = M.per_1m(r); pair = net_logo(r["chain"]) + f'POA→{E(r["asset"] or "?")}'
        if r["created_ts"]: ev.append((r["created_ts"], "offer", r, pm, usd, pair))
        if r["fill_ts"]: ev.append((r["fill_ts"], "fill", r, pm, usd, pair))
        if r["cancel_ts"]: ev.append((r["cancel_ts"], "cancel", r, pm, usd, pair))
        if r["status"] == "refunded": ev.append((r["refund_basis"]["ts"], "refunded", r, pm, usd, pair))
        if r["status"] in ("expired", "delisted") and r["expires_ts"]: ev.append((r["expires_ts"] if r["status"] == "expired" else r["updated"], r["status"], r, pm, usd, pair))
    ev.sort(key=lambda x: -x[0])
    cls = {"offer": "b-send", "fill": "b-grade", "cancel": "b-sys", "expired": "b-sys", "delisted": "b-sys", "refunded": "b-sys"}
    rows = [[utc(ts, "%m-%d %H:%M"), f'<span class="badge {cls[k]}">{k.upper()}</span>', pair, poa(r["poa"]), _pfmt(pm, usd, r["asset"]),
             addr_link(r["maker"], nm), addr_link(r["taker"], nm) if r["taker"] else '<span class="na">···</span>',
             _ext(r["chain"], r["ext_ref"], tx=True) if k == "fill" and r["ext_ref"] else (tx_link(r["fill_txid"] if k == "fill" else r["cancel_txid"] if k == "cancel" else r["offer_id"], (6, 4)) if (r["fill_txid"] if k == "fill" else r["cancel_txid"] if k == "cancel" else r["offer_id"]) and k in ("offer", "fill", "cancel") else '<span class="na">···</span>')]
            for ts, k, r, pm, usd, pair in ev]
    return table(["Time (UTC)", "Event", "Pair", "Size", "Price · 1M POA", "Maker", "Taker", "Tx / leg"], rows)


def price_chart_html():
    rows = [r for r in M.price_history() if r["price_per_1m_poa"] is not None]
    if not rows: return chart_skel(640, 170, "No fills yet.")
    out = []
    for a in sorted({r["asset"] for r in rows}):
        pts = [(r["ts"], r["price_per_1m_poa"]) for r in rows if r["asset"] == a]
        if len(pts) == 1: pts = pts + [(pts[0][0] + 1, pts[0][1])]  # one fill: flat at its own time
        out.append(f'<div data-asset="{E(a or "")}"><div class="minihd">{E(a or "?")} · 1M POA</div>' + line(pts, height=170, color="#FFB000" if a == "SOL" else "#8FA3B8", fmt=lambda v: plain(v, 4), y0=0) + "</div>")
    return f'<div class="pgrid">{"".join(out)}</div>'


def page():
    op, fl = M.rows()
    side = (stats_html() + card(ICON_SWAP + 'Order book', f'<div id="swapsopen">{book_html()}</div>', f'<span class="dim small">{len(op)} open</span>', cls="xcard")
            + card(ICON_SWAP + "Price", chart_html(), usd_src(), cls="xcard")
            + card("Recent fills", fills_html(), f'<span class="dim small">{len(fl)}</span>', cls="xcard"))
    body = ('<h1 class="sr-only">Swap POA</h1>'
            f'<div class="xgrid"><div class="xl">{panel()}</div><div class="xr">{side}</div></div>'
            + card("Activity", history_html(), '<a class="more" href="/api/swaps.csv">CSV →</a>')
            + '<script src="/static/swap.js?v=6" defer></script>')
    return H.page("Swaps", body, C.PAGE_PATH, head='<link rel="stylesheet" href="/static/swap.css?v=1">')
