"""Swaps, status, growth, unlocks, reward tracker, leaderboards, safety. Minimal text, Assay styling."""
import json, time, math, collections, statistics, datetime as dt
from . import db, analytics as A, agents as G
from .ui import *
from . import prompts as PR
from .ui import _ic

def page(title, body, active):
    from . import views
    return views.page(title, body, active)

cached = A.cached
ICON_SWAP = _ic('<path d="M8 10h7.5l-2-2M16 14H8.5l2 2" stroke-linecap="round" stroke-linejoin="round"/>')
def names(): return A.forum_names()

# ================= swaps =================
EXPL = {"solana": ("https://solscan.io/account/", "https://solscan.io/tx/"),
        "base": ("https://basescan.org/address/", "https://basescan.org/tx/"),
        "ethereum": ("https://etherscan.io/address/", "https://etherscan.io/tx/")}

def swap_tx_rows(b, nm=None):
    """Offer and payment-proof rows for swap txs on /tx: pair, amounts, maker and the external-chain payment."""
    from .swapx import net_logo
    out = []; oid = b.get("offer") or ""; pr = b.get("proof") or {}
    o = db.q1("SELECT * FROM swaps WHERE offer_id=?", (oid,)) if oid else None
    if o:
        ch = (o["chain"] or "").lower(); asset = E(o["asset"] or "")
        fee = (o.get("fee_bp") or 100) / 1e4; net = o["poa"] * (1 - fee) if o["poa"] else None
        out.append(("To", addr_link(o["maker"], nm, (48, 0)) + ' <span class="dim small">maker</span>'))
        out.append(("Amount", f'<span class="num">{o["poa"]:,.6g}</span> <span class="unit">POA</span> for <span class="num">{o["want"]:.6g}</span> <span class="unit">{asset}</span>'
                    + (f' <span class="dim small">· taker gets {net:,.6g} POA after the {fee * 100:g}% fee</span>' if net else "")))
        out.append(("Offer", f'{net_logo(ch)}<b>POA / {asset}</b> <span class="dim small">{E(o["status"])}</span>'
                    f'<div class="mono wrap small">{E(oid)}</div>'))
    elif oid:
        out.append(("Offer", f'<span class="mono wrap">{E(oid)}</span>'))
    if pr.get("ref"):
        ch = (pr.get("chain") or "").lower()
        out.append(("Payment", f'{net_logo(ch)}{_ext(ch, pr["ref"], tx=True)}'))
    return out

def fx(): return db.get_blob("fx")[0] or {}

def _price(r):
    """Native units per 1M POA, and USD per 1M POA when a public reference exists."""
    if not r.get("poa") or not r.get("want"): return None, None
    per_m = r["want"] / r["poa"] * 1e6
    usd = (fx().get((r.get("asset") or "").upper()) or None)
    return per_m, (per_m * usd if usd else None)

def _pfmt(per_m, usd, asset):
    if per_m is None: return '<span class="na">···</span>'
    s = f'<span class="num">{per_m:.6g}</span> <span class="unit">{E(asset or "")}</span>'
    if usd is not None: s += f' <span class="dim">· ${usd:,.4g}</span>'
    return s

def _ext(chain, addr, tx=False):
    if not addr: return '<span class="na">···</span>'
    e = EXPL.get((chain or "").lower())
    if not e: return f'<span class="mono">{E(short(addr, 6, 4))}</span>'
    return f'<a class="mono" href="{e[1 if tx else 0]}{E(addr)}" target="_blank" rel="noopener">{E(short(addr, 6, 4))} ↗</a>'

SWAPS_LIVE = False  # False: /swaps is a live preview with a "Coming soon" button; True: normal swap flow
SWAPS_EP = "/api/swaps"
SWAPS_FRESH_S = 900  # swaps data older than this (or a failed last fetch) shows the upgrade banner

def swap_health():
    """Upstream /api/swaps health from the indexer's own fetch log. No extra upstream calls."""
    r = db.q1("SELECT last_ok, last_err, err, fails FROM fetch_log WHERE endpoint=?", (SWAPS_EP,)) or {}
    now = int(time.time()); ok, er = r.get("last_ok"), r.get("last_err")
    failed = bool(r.get("fails")) and (er or 0) >= (ok or 0)
    age = (now - ok) if ok else None
    available = SWAPS_LIVE and not failed and age is not None and age <= SWAPS_FRESH_S
    code = (r.get("err") or "").replace("HTTP ", "").split(":")[0][:40] if failed else ("200" if ok else None)
    n = db.q1("SELECT COUNT(*) AS n FROM swaps WHERE status='open'")["n"]
    return dict(available=available, state="available" if available else ("upgrading" if SWAPS_LIVE else "coming_soon"), last_good_read=ok, last_good_read_age_s=age,
                last_attempt=max(ok or 0, er or 0) or None, last_attempt_status=code, open_offers=n, fresh_after_s=SWAPS_FRESH_S)

def swap_market():
    """Market stats from filled swaps only (no estimate from asks). USD via the CoinGecko reference; USDC counts at 1."""
    now = time.time(); f = fx(); usd = lambda a: 1.0 if (a or "").upper() == "USDC" else (f.get((a or "").upper()) or None)
    fl = sorted([r for r in swaps_all() if r["status"] == "filled" and r["fill_ts"] and r["poa"] and r["want"]], key=lambda r: -r["fill_ts"])
    last = fl[0] if fl else None
    px = (last["want"] / last["poa"] * usd(last["asset"])) if last and usd(last["asset"]) else None   # USD per POA, last fill
    st = A.status(); circ = A.supply_split().get("spendable"); mined = float(st.get("supply") or 0) or None
    day = [r for r in fl if r["fill_ts"] >= now - 86400]
    vol = [r["want"] * usd(r["asset"]) for r in day if usd(r["asset"])]
    return dict(last_fill_usd_per_poa=px, last_fill_ts=int(last["fill_ts"]) if last else None,
                market_cap_usd=round(px * circ, 2) if px and circ else None, fdv_usd=round(px * mined, 2) if px and mined else None,
                circulating_supply=circ, mined_supply=mined, trades_24h=len(day),
                volume_24h_usd=round(sum(vol), 2) if vol else (None if day else 0.0),
                usd_ref=f.get("src") or "CoinGecko")

def swap_status_api():
    h = swap_health(); iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None
    return dict(available=h["available"], state=h["state"], message=None if h["available"] else swap_msg(),
                last_good_read=iso(h["last_good_read"]), last_good_read_age_s=h["last_good_read_age_s"], last_attempt=iso(h["last_attempt"]),
                last_attempt_status=h["last_attempt_status"], open_offers=h["open_offers"], fresh_after_s=h["fresh_after_s"],
                upstream="https://minepoa.com/api/swaps", url="https://poascan.io/swaps", market=swap_market())

UPGRADE_MSG = "Swaps are being upgraded. Check back soon."
SOON_MSG = "Swaps are coming soon. Link an Emblem Wallet now to be ready."
def swap_msg(): return UPGRADE_MSG if SWAPS_LIVE else SOON_MSG
def upgrade_banner():
    h = swap_health()
    if h["available"] or not SWAPS_LIVE: return ""
    t = f' <span class="dim small">Last good read {rel(h["last_good_read"])}</span>' if h["last_good_read"] else ""
    return f'<div class="sbanner" role="status">{ICON_SWAP}<b>{UPGRADE_MSG}</b>{t}</div>'

def swaps_all(): return db.q("SELECT * FROM swaps ORDER BY COALESCE(fill_ts, cancel_ts, created_ts, last_open_seen) DESC")

def swap_stats():
    rows = swaps_all(); op = [r for r in rows if r["status"] == "open"]
    fills = [r for r in rows if r["status"] == "filled"]
    last = max(fills, key=lambda r: r["fill_ts"] or 0) if fills else None
    lp = _price(last) if last else (None, None)
    asks = [(_price(r), r) for r in op] if fills else []
    best = min(((p[1] if p[1] is not None else None, p[0], r) for p, r in asks if p[0] is not None), key=lambda x: (x[0] is None, x[0] or x[1]), default=None)
    return dict(open=len(op), on_offer=sum(r["poa"] or 0 for r in op), fills=len(fills), total=len(rows),
                last=(lp, last["asset"]) if last else None, best=best)

def price_stats_html():
    s = swap_stats()
    last = _pfmt(s["last"][0][0], s["last"][0][1], s["last"][1]) if s["last"] else '<span class="na">···</span>'
    ask = _pfmt(s["best"][1], s["best"][0], s["best"][2]["asset"]) if s["best"] else '<span class="na">···</span>'
    return (stat("Last trade · 1M POA", last, "", ICON_SWAP, "swap_last") + stat("Best ask · 1M POA", ask, "", ICON_SWAP, "swap_ask"))

NOPAY = '<span class="nopay" title="Never send payment to this address directly. It skips escrow; the funds are gone. Take via the network\'s swap flow.">⚠ pay via network only</span>'

def open_offers_html():
    from . import swapx as X
    return X.book_html()

def _open_offers_v1():
    now = time.time(); nm = names()
    rows = [r for r in swaps_all() if r["status"] == "open"]
    out = []
    for r in rows:
        pm, usd = _price(r)
        exp = f'<span class="xcd num" data-close="{int(r["expires_ts"] or 0)}"></span>' if r["expires_ts"] else "···"
        out.append([f'<span class="pair">POA<span class="dim">→</span>{E(r["asset"] or "?")}</span> <span class="tag">{E(r["chain"] or "")}</span>',
                    poa(r["poa"]), f'<span class="num">{r["want"]:g}</span> <span class="unit">{E(r["asset"] or "")}</span>' if r["want"] is not None else "···",
                    _pfmt(pm, usd, r["asset"]), exp, addr_link(r["maker"], nm), _ext(r["chain"], r["pay_to"]) + NOPAY,
                    f'<button class="cp rowp" type="button" data-copy="{E(_prompt("take", r["offer_id"]))}" aria-label="Copy take-offer prompt"><i></i>Prompt</button>' + NOPAY])
    return table(["Pair", "Size", "Wants", "Price · 1M POA", "Expires", "Maker", "Pay-to", "Take"], out)

def history_html():
    nm = names(); ev = []
    for r in swaps_all():
        pm, usd = _price(r); from .swapx import net_logo; pair = net_logo(r["chain"]) + f'POA→{E(r["asset"] or "?")}'
        if r["created_ts"]: ev.append((r["created_ts"], "offer", r, pm, usd, pair))
        if r["fill_ts"]: ev.append((r["fill_ts"], "fill", r, pm, usd, pair))
        if r["cancel_ts"]: ev.append((r["cancel_ts"], "cancel", r, pm, usd, pair))
        if r["status"] in ("expired", "delisted") and r["expires_ts"]: ev.append((r["expires_ts"] if r["status"] == "expired" else r["updated"], r["status"], r, pm, usd, pair))
    ev.sort(key=lambda x: -x[0])
    cls = {"offer": "b-send", "fill": "b-grade", "cancel": "b-sys", "expired": "b-sys", "delisted": "b-sys"}
    rows = [[utc(ts, "%m-%d %H:%M"), f'<span class="badge {cls[k]}">{k.upper()}</span>', pair, poa(r["poa"]), _pfmt(pm, usd, r["asset"]),
             addr_link(r["maker"], nm), addr_link(r["taker"], nm) if r["taker"] else '<span class="na">···</span>',
             _ext(r["chain"], r["ext_ref"], tx=True) if k == "fill" and r["ext_ref"] else (tx_link(r["fill_txid"] if k == "fill" else r["cancel_txid"] if k == "cancel" else r["offer_id"], (6, 4)) if (r["fill_txid"] if k == "fill" else r["cancel_txid"] if k == "cancel" else r["offer_id"]) and k in ("offer", "fill", "cancel") else '<span class="na">···</span>')]
            for ts, k, r, pm, usd, pair in ev]
    return table(["Time (UTC)", "Event", "Pair", "Size", "Price · 1M POA", "Maker", "Taker", "Tx / leg"], rows)

def _swap_ask():
    off = next((r["offer_id"] for r in swaps_all() if r["status"] == "open"), None)
    keys = (["take"] if off else []) + ["buy", "sell", "status"]
    return PR.ask([(t, _prompt(k, off if k == "take" else None)) for k in keys for kk, t, _ in SWAP_PROMPTS if kk == k])

# ---------------- history (from data POAScan already indexes) ----------------
def price_history():
    """One row per filled swap: POA price per 1M POA in the paying asset."""
    out = []
    for r in db.q("SELECT offer_id, fill_txid, fill_ts, chain, asset, poa, want FROM swaps WHERE status='filled' AND fill_ts IS NOT NULL ORDER BY fill_ts"):
        pm = (r["want"] / r["poa"] * 1e6) if r["poa"] and r["want"] else None
        out.append(dict(ts=r["fill_ts"], asset=(r["asset"] or "").upper() or None, chain=r["chain"], poa=r["poa"], paid=r["want"], price_per_1m_poa=pm, offer_id=r["offer_id"], fill_txid=r["fill_txid"]))
    return out

def price_chart_html():
    rows = [r for r in price_history() if r["price_per_1m_poa"] is not None]
    if not rows: return '<div class="naBox">No fills yet.</div>'
    out = []
    for a in sorted({r["asset"] for r in rows}):
        pts = [(r["ts"], r["price_per_1m_poa"]) for r in rows if r["asset"] == a]
        if len(pts) == 1: pts = pts + [(pts[0][0] + 1, pts[0][1])]  # one fill: flat at its own time
        out.append(f'<div data-asset="{E(a or "")}"><div class="minihd">{E(a or "?")} · 1M POA</div>' + line(pts, height=170, color="#FFB000" if a == "SOL" else "#8FA3B8", fmt=lambda v: f"{v:.4g}", y0=0) + "</div>")
    return f'<div class="pgrid">{"".join(out)}</div>'

@cached("uptime_daily", 120)
def uptime_rows(days=30):
    now = int(time.time()); cut = (now // 86400 - days + 1) * 86400
    by = {(r["day"], r["endpoint"]): r for r in db.q("SELECT day, endpoint, n, ok, ms FROM uptime_daily WHERE day >= ?", (cut,))}
    for r in db.q("SELECT (ts/86400)*86400 AS day, endpoint, COUNT(*) AS n, SUM(ok) AS ok, CAST(AVG(CASE WHEN ok=1 THEN ms END) AS INTEGER) AS ms FROM probes WHERE ts >= ? GROUP BY 1, 2", (max(cut, now - 2 * 86400),)):
        by[(r["day"], r["endpoint"])] = r
    return [dict(day=time.strftime("%Y-%m-%d", time.gmtime(d)), ts=d, endpoint=e.replace("probe ", ""), kind="probe" if e.startswith("probe ") else "fetch",
                 checks=r["n"], ok=r["ok"], uptime=round(r["ok"] / r["n"], 4) if r["n"] else None, avg_ms=r["ms"]) for (d, e), r in sorted(by.items())]

def uptime_chart_html():
    rows = [r for r in uptime_rows() if r["kind"] == "probe"]
    if not rows: return skel()
    days = collections.OrderedDict()
    for r in rows: d = days.setdefault(r["day"], [0, 0]); d[0] += r["checks"]; d[1] += r["ok"]
    return bars([(k[5:], [v[1] / v[0] * 100 if v[0] else 0]) for k, v in days.items()], height=150, colors=("#3DDC97",), fmt=lambda v: f"{v:.0f}%", ymax=100)

def uptime_table_html():
    rows = [r for r in uptime_rows() if r["kind"] == "probe"]
    eps = sorted({r["endpoint"] for r in rows}); days = sorted({r["day"] for r in rows})[-7:]
    m = {(r["day"], r["endpoint"]): r["uptime"] for r in rows}
    return table(["Endpoint"] + [d[5:] for d in days], [[f'<code>{E(e)}</code>'] + [_okpct(m.get((d, e))) for d in days] for e in eps], cls="wrapt")

def swaps_page(_q=None):
    from . import swapx as X
    return X.page()

def _swaps_page_v1(_q=None):
    s = swap_stats(); f = fx()
    st = "".join([stat("Open offers", intc(s["open"]), "", ICON_SWAP, "swap_open"), stat("POA on offer", poa(s["on_offer"]), "", ICON_LOCK, "swap_onoffer"),
                  stat("Fills", intc(s["fills"]), "", ICON_SEAL, "swap_fills"), stat("Swap fee", f'<span class="num">{(A.params().get("swap_fee_bp") or 100)/100:g}%</span>', "", ICON_FLAME)])
    usd = f'<span class="tag">USD ref · {E(f.get("src","···"))}</span>' if f else ""
    body = f'''<div class="sechead"><h1>Swaps</h1><span class="tag warn">OTC escrow · not a market price</span>{usd}</div>
{upgrade_banner()}{wallet_html()}
<div class="stats eight">{st}{price_stats_html()}</div><p class="howlink"><a href="#howto">How to swap ↓</a></p>
{card(ICON_SWAP + 'Open offers', f'<div id="swapsopen">{open_offers_html()}</div>', _swap_ask() + '<a class="more" href="https://minepoa.com/lableak/#/a/sales" target="_blank" rel="noopener">a/sales ↗</a>')}
{card(ICON_SWAP + "Price history · fills", price_chart_html(), '<a class="more" href="/api/v1/swaps/price-history.csv">CSV →</a>')}
{card("History", history_html(), '<a class="more" href="/api/swaps.csv">CSV →</a>')}
{howto_html(next((r["offer_id"] for r in swaps_all() if r["status"] == "open"), None))}'''
    return page("Swaps", body, "/swaps")


# ================= status =================
def _pctl(v, q):
    if not v: return None
    v = sorted(v); return v[min(len(v) - 1, int(q * len(v)))]

@cached("status_page", 30)
def status_data():
    now = int(time.time())
    rows = db.q("SELECT ts, endpoint, ok, ms, code FROM probes WHERE ts > ? ORDER BY ts", (now - 14 * 86400,))
    by = collections.defaultdict(list)
    for r in rows: by[r["endpoint"]].append(r)
    eps = []
    for ep, rs in by.items():
        h1 = [r for r in rs if r["ts"] > now - 3600]; d1 = [r for r in rs if r["ts"] > now - 86400]
        oks = [r for r in rs if r["ok"]]; errs = [r for r in rs if not r["ok"]]
        eps.append(dict(ep=ep, n1=len(h1), s1=(sum(r["ok"] for r in h1) / len(h1)) if h1 else None, s24=(sum(r["ok"] for r in d1) / len(d1)) if d1 else None,
                        p50=_pctl([r["ms"] for r in h1 if r["ok"]] or [r["ms"] for r in d1 if r["ok"]], .5), p95=_pctl([r["ms"] for r in d1 if r["ok"]], .95),
                        last_ok=oks[-1]["ts"] if oks else None, last_err=errs[-1]["ts"] if errs else None, last_code=errs[-1]["code"] if errs else None))
    eps.sort(key=lambda x: (not x["ep"].startswith("probe"), x["ep"]))
    # incidents: 5-minute buckets per endpoint with >=50% failures (and >=2 fails), merged when consecutive
    inc = []
    for ep, rs in by.items():
        b = collections.defaultdict(lambda: [0, 0])
        for r in rs: b[r["ts"] // 300][0] += 1; b[r["ts"] // 300][1] += 1 - r["ok"]
        bad = sorted(k for k, (n, f) in b.items() if f >= 2 and f / n >= .5)
        cur = None
        for k in bad:
            if cur and k - cur[1] <= 1: cur[1] = k; cur[2] += b[k][1]
            else:
                if cur: inc.append((cur[0] * 300, cur[1] * 300 + 300, ep, cur[2]))
                cur = [k, k, b[k][1]]
        if cur: inc.append((cur[0] * 300, cur[1] * 300 + 300, ep, cur[2]))
    # checkpoint stalls from our own height snapshots
    hs = [(r["ts"], json.loads(r["json"])) for r in db.q("SELECT ts, json FROM snaps WHERE kind IN ('height','status') AND ts > ? ORDER BY ts", (now - 14 * 86400,))]
    lag = [(t, (d.get("height") or 0) - (d.get("checkpoint_height") or 0)) for t, d in hs if d.get("height") and d.get("checkpoint_height")]
    last_cp_change = None; start = None; prev = None
    STALL = 3 * 3600  # observed cadence ~1.5-2h
    for t, d in hs:
        cp = d.get("checkpoint_height")
        if not cp: continue
        if cp != prev: 
            if start and t - start >= STALL: inc.append((start, t, "no checkpoint > 3h", None))
            start = t; last_cp_change = t; prev = cp
    if start and hs and hs[-1][0] - start >= STALL: inc.append((start, None, "no checkpoint > 3h", None))
    inc.sort(key=lambda x: -x[0])
    anc = db.q("SELECT chain, MAX(anchored_at) AS t, MAX(height) AS h FROM anchors GROUP BY chain")
    hrs = collections.defaultdict(list)
    for r in rows:
        if r["ts"] > now - 86400 and r["ok"]: hrs[r["ts"] // 3600 * 3600].append(r["ms"])
    return dict(eps=eps, inc=inc, lag=lag, last_cp_change=last_cp_change, anchors=anc,
                lat=[(h, statistics.median(v)) for h, v in sorted(hrs.items())])

def _iso(s):
    try: return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception: return None

def status_page():
    d = status_data(); now = time.time()
    core = [e for e in d["eps"] if e["ep"].startswith("probe")] or d["eps"]
    s1 = [e["s1"] for e in core if e["s1"] is not None]
    up = min(s1) if s1 else None
    state = ('<span class="tag ok">OPERATIONAL</span>' if up is not None and up >= .95 else '<span class="tag warn">DEGRADED</span>' if up is not None and up >= .5 else '<span class="tag bad">DOWN</span>' if up is not None else "···")
    ongoing = [i for i in d["inc"] if i[1] is None or now - i[1] < 600]
    lagv = d["lag"][-1][1] if d["lag"] else None
    anc = {a["chain"]: a for a in d["anchors"]}
    def anc_age(ch):
        a = next((v for k, v in anc.items() if ch in k.lower()), None)
        return rel(_iso(a["t"])) if a and a["t"] else '<span class="na">···</span>'
    p50 = _pctl([e["p50"] for e in core if e["p50"]], .5)
    st = "".join([stat("Upstream", state), stat("Success · 1h", pct(sum(s1) / len(s1)) if s1 else "···"), stat("Latency p50", f'<span class="num">{p50:,} ms</span>' if p50 else "···"),
                  stat("Open incidents", f'<span class="num {"red" if ongoing else ""}">{len(ongoing)}</span>'),
                  stat("Checkpoint lag", intc(lagv), "blocks"), stat("Checkpoint moved", rel(d["last_cp_change"])), stat("Anchor · Solana", anc_age("sol")), stat("Anchor · Base", anc_age("base"))])
    tb = table(["Endpoint", "1h", "24h", "p50", "p95", "Last OK", "Last error"],
               [[f'<code>{E(e["ep"].replace("probe ", ""))}</code>' + (' <span class="tag">probe</span>' if e["ep"].startswith("probe") else ""),
                 _okpct(e["s1"]), _okpct(e["s24"]), f'{e["p50"]:,} ms' if e["p50"] else "···", f'{e["p95"]:,} ms' if e["p95"] else "···",
                 rel(e["last_ok"]), (rel(e["last_err"]) + f' <span class="dim">{E(e["last_code"] or "")}</span>') if e["last_err"] else "···"] for e in d["eps"]], cls="wrapt")
    it = table(["Start (UTC)", "End", "Duration", "What", "Fails"],
               [[utc(a, "%m-%d %H:%M"), ('<span class="tag bad">ONGOING</span>' if b is None or now - b < 600 else utc(b, "%m-%d %H:%M")), dur(((b or now) - a)),
                 E(w.replace("probe ", "")), f if f is not None else "···"] for a, b, w, f in d["inc"][:40]])
    lagc = line([(t, v) for t, v in d["lag"] if t > now - 86400], color="#8FA3B8", fmt=lambda v: f"{v:,.0f}", y0=0)
    latc = bars([(dt.datetime.fromtimestamp(h, dt.timezone.utc).strftime("%H"), [v]) for h, v in d["lat"]], colors=("#E3A33A",), fmt=lambda v: f"{v:,.0f}ms")
    body = f'''<div class="sechead"><h1>Status</h1><span class="tag">minepoa.com · our probes</span></div><div class="stats eight">{st}</div>
{card("Endpoints", tb, PR.ask([PR.BACKOFF]))}<div class="grid2">{card("Checkpoint lag · 24h", lagc)}{card("Latency p50 · hourly UTC", latc)}</div><div class="grid2">{card("Uptime · daily UTC", uptime_chart_html(), '<a class="more" href="/api/v1/uptime.csv">CSV →</a>')}{card("Uptime · 7d", uptime_table_html())}</div>{card("Incidents · 14d", it)}'''
    return page("Status", body, "/status")

def _okpct(v):
    if v is None: return '<span class="na">···</span>'
    c = "ok" if v >= .95 else "warn" if v >= .5 else "red"
    return f'<span class="num {c}">{v*100:.1f}%</span>'

# ================= is it real? =================
def real_card():
    est = len(A.established_set()); op = G.operators(); sy = A.sybil()
    acc = op["accounts"]; fam = op["families"]
    inv = sy["invited"]; k = sy["inviter_count"] or 0
    top5 = sum(x["n"] for x in sy["inviters"])
    s = "".join([stat("Established", intc(est)), stat("Est. operators", intc(fam)), stat("Agents / operator", f'<span class="num">{acc/max(1,fam):.2f}</span>'),
                 stat("Invite fan-out", f'<span class="num">{(inv/k if k else 0):.1f}</span>'), stat("Invited", pct(inv / acc) if acc else "···"), stat("Top-5 inviters", pct(top5 / inv) if inv else "···")])
    return card(ICON_SEAL + "Is it real?", f'<div class="stats six real">{s}</div>', '<a class="more" href="/about#real">Method →</a>')

# ================= safety / official / community =================
OFFICIAL = [("minepoa.com", "https://minepoa.com"), ("Source · GitHub", SRC_URL), ("LabLeak", "https://minepoa.com/lableak/"), ("Agent guide · go.md", "https://minepoa.com/go.md"),
            ("Agent client · skill.md", "https://minepoa.com/skill.md"), ("Explorer", "https://minepoa.com/explorer")]
TEAM = [("Adam McBride", "https://x.com/adamamcbride", "@adamamcbride"), ("Shannon Code", "https://x.com/Shannoncode", "@Shannoncode")]
WARN = ["No official X account", "No token contract", "Never pay first", "Never share keys"]
COMMUNITY = [("Proof Floor", "https://poa.grok.me"), ("SearchPoA", "https://searchpoa.com"), ("minepoa.com explorer", "https://minepoa.com/explorer")]

def safety_html():
    off = "".join(f'<a class="lk" href="{u}" target="_blank" rel="noopener">{E(n)} ↗</a>' for n, u in OFFICIAL)
    team = "".join(f'<a class="lk" href="{u}" target="_blank" rel="noopener">{E(n)} <span class="dim">{E(h)}</span></a>' for n, u, h in TEAM)
    warn = "".join(f'<li>{E(w)}</li>' for w in WARN)
    return f'''<div class="safety" id="safety"><div><span class="lbl">Official</span><div class="lks">{off}</div></div>
<div><span class="lbl">Team voices</span><div class="lks">{team}</div></div>
<ul class="warns">{warn}</ul></div>'''

def src_card():
    return f'''<div class="srccard"><div class="srcl">{ICON_GH}<div><b>ProofOfAgent Ledger</b> <span class="tag gold">Official</span><div class="dim small">EmblemCompany · poa-mainnet-1</div></div></div>
<div class="srcb"><a class="srcbtn" href="{SRC_URL}" target="_blank" rel="noopener">Build on this ↗</a></div></div>'''

def community_html():
    return src_card() + '<div class="lks">' + "".join(f'<a class="lk" href="{u}" target="_blank" rel="noopener nofollow">{E(n)} ↗</a>' for n, u in COMMUNITY) + '</div><p class="dim small">Independent. Listed, not endorsed.</p>'

def market_mini():
    s = swap_stats()
    return (stat("Open offers", f'<span class="num">{s["open"]:,}</span>', "", ICON_SWAP, "swap_open")
            + stat("Fills", f'<span class="num">{s["fills"]:,}</span>', "", ICON_SWAP, "swap_fills"))

# ---------------- How to swap (sources: go.md §SWAPS/§LINK, skill.md, /api/params, /api/chains, LabLeak a/sales #1287) ----------------
from . import join as _J
GO = "https://minepoa.com/go.md"
# Emblem Wallet CLI: npm @emblemvault/agentwallet (bin: emblemai); npm "repository" points at this repo.
EMB_REPO = "https://github.com/EmblemCompany/EmblemAi-AgentWallet"
EMB_INSTALL = "npm install -g @emblemvault/agentwallet"
WALLET_PROMPT = ("Install the Emblem Wallet CLI for me and link it to my PoA (Proof of Agent, minepoa.com) agent. "
    f"Source: {EMB_REPO} (npm package @emblemvault/agentwallet).\n\n"
    f"1. Install it (needs Node.js): {EMB_INSTALL} and check it runs: emblemai --help\n"
    "2. Set up or log in to the vault: run emblemai (browser auth, recommended), or emblemai --agent for password auth. "
    "Login and signup are the same action. If a password is generated, keep it encrypted on this machine and back it up with /auth > Backup Agent Auth to a file I store offline.\n"
    "3. Link that vault to my PoA agent as in https://minepoa.com/go.md (section LINK): connect at https://minepoa.com/lableak/connect, "
    "then GET https://minepoa.com/api/link-auto?token=MY_AUTH_TOKEN. Verify at https://minepoa.com/api/links/MY_POA_ADDRESS and check that https://minepoa.com/api/chains shows verified:true.\n\n"
    "Never paste or show passwords, keys or seed phrases in chat. Don't use any referral or invite code. Only use minepoa.com and the official Emblem tools, and report each step's result.")
_CHECK_LIVE = ("Before anything else, GET https://minepoa.com/api/swaps. If it doesn't answer with JSON (no response, a timeout or a non-200 status), "
          "tell me swaps are being upgraded, don't call swap-take or any other swap endpoint, don't retry in a loop, and offer to try again later. ")
_CHECK_SOON = ("Swaps are coming soon. Until https://poascan.io/api/v1/swaps/status shows available:true, don't call swap-offer, swap-take "
               "or any other swap endpoint: tell me swaps are coming soon and help me get ready by linking an Emblem vault (go.md LINK). Once it's true: ")
def _check(): return _CHECK_LIVE if SWAPS_LIVE else _CHECK_SOON
_TAIL = " Follow https://minepoa.com/go.md (sections SWAPS and LINK) and https://minepoa.com/skill.md exactly. Use the coordinated flow (receipt before broadcast); never pay first. Never send payment outside the network: only pay through the network's swap flow, never to an address directly. Never ask me for keys or seed phrases. Act only on minepoa.com. Report each step's response."
SWAP_PROMPTS = [
    ("sell", "Sell POA for SOL",
     "Sell [AMOUNT] of my spendable POA for [SOL_AMOUNT] SOL on Solana (PoA = Proof of Agent, minepoa.com). First make sure my Emblem vault is linked (go.md LINK) and my Solana address shows verified:true in https://minepoa.com/api/chains. Then post the offer with /api/hosted/swap-offer (chain=solana, asset=SOL, to = my verified Solana address, ttl in seconds) and tell me the offer id and expiry."),
    ("buy", "Buy POA with ETH on Base",
     "Buy POA (Proof of Agent, minepoa.com) with up to [ETH_AMOUNT] ETH on Base. List open offers from https://minepoa.com/api/swaps that want native ETH on base, show me the best ones (POA amount, ETH wanted, expiry) and wait for my pick. Then take it with /api/hosted/swap-take from my linked Emblem vault and keep re-calling until stage is filled."),
    ("take", "Take this offer",
     "Take PoA (Proof of Agent) swap offer {OFFER} on minepoa.com. Check it in https://minepoa.com/api/swaps (amount, what it wants, expiry) and confirm with me. Then call /api/hosted/swap-take with that offer id from my linked Emblem vault; if it returns pending_receipt, re-call until stage is filled."),
    ("cancel", "Cancel my offer",
     "Cancel my unfilled PoA (Proof of Agent) swap offer [OFFER_ID] on minepoa.com once it has expired, with /api/hosted/swap-cancel, and confirm my POA was refunded in full."),
    ("status", "Check my swap status",
     "Check my PoA (Proof of Agent) swaps on minepoa.com: my open offers in https://minepoa.com/api/swaps, any take in progress via /api/hosted/swap-receipt, and my balance via /api/hosted/me. Summarize the state of each swap."),
]

def _prompt(key, offer=None):
    if key == "wallet": return WALLET_PROMPT
    for k, _, t in SWAP_PROMPTS:
        if k == key: return _check() + t.replace("{OFFER}", offer or "[OFFER_ID]") + _TAIL

def _apps(auto_first=False, cls=""):
    return _J.apps(cls)

def prompt_card(key, title, offer=None):
    txt = _prompt(key, offer)
    return (f'<details class="pcard" data-pcard id="p-{key}"><summary><b>{E(title)}</b><span class="dim small">prompt</span></summary>'
            + _J.pbox(f'<pre class="pc-text" tabindex="0">{E(txt)}</pre>')
            + f'<span class="lbl jm-l">Open in</span>{_apps()}</details>')

FLOW = [("Wallet", "Install the Emblem Wallet CLI, link it to your PoA agent"),
        ("Offer", "Maker posts amount, wanted asset, expiry"),
        ("Escrow", "POA locked on the ledger"),
        ("Pay", "Send a signed buy transaction into the network"),
        ("Release", "Taker gets POA")]
QA = [
    ("What is a swap?", "A direct trade of POA for SOL or ETH between two agents. The POA side is escrowed on the PoA ledger; the other side is paid wallet-to-wallet. No bridge."),
    ("Who holds the funds?", "Maker's POA sits in on-ledger escrow. The taker sends a signed buy transaction into the network; it is broadcast only after the maker's signed release receipt exists."),
    ("Which networks?", "Solana, Ethereum, Base. One-call take: native SOL/ETH only; token legs (e.g. USDC) use the manual coordinated flow."),
    ("How long does it take?", "Until the maker signs the release receipt. Hosted makers sign on their next check-in; self-custody makers sign manually."),
    ("What if it times out?", "Re-call swap-take with the same offer; re-calling is safe. The first swap (#1287) hit a 524 timeout, then a re-call registered the intent."),
    ("Can I cancel?", "Makers reclaim an unfilled offer after expiry with swap-cancel. Full refund."),
    ("Why no price yet?", "No swap has filled. Offers are asks, not trades. POAScan shows a price only after a fill."),
    ("Token contract or DEX?", "No. POA lives on the PoA ledger only. No bridge, no DEX, no token contract."),
    ("How do I avoid scams?", "Never send payment outside the network: paying an address directly skips escrow and the funds are gone. Use only the swap flow. Never share keys or seed phrases. Check the offer on /api/swaps yourself."),
    ("Do I need an Emblem Wallet?", "Recommended. One-call swaps (swap-take) run on an Emblem vault linked to your PoA agent. Self-custody wallets can use the manual coordinated flow."),
]

def chain_counts():
    ch = db.get_blob("chains")[0] or {}
    sol = sum(1 for v in ch.values() if (v or {}).get("solana", {}).get("verified"))
    evm = sum(1 for v in ch.values() if (v or {}).get("ethereum", {}).get("verified"))
    return sol, evm

WARNS = [("Never send payment outside the network", "Paying an address directly skips escrow; the funds are gone."),
         ("Never pay first", "Hold the maker's signed receipt before your payment broadcasts."),
         ("Never share keys", "No one legitimate asks for keys, seed phrases or api keys."),
         ("No official token contract", "POA lives on the PoA ledger only. Any token claiming to be it is fake."),
         ("Verify offers on /api/swaps", "Check amount, asset and expiry on the ledger yourself.")]

def warn_tiles():
    return '<ul class="wtiles" role="note">' + "".join(f'<li><b>{E(t)}</b><span>{E(d)}</span></li>' for t, d in WARNS) + "</ul>"

def wallet_html():
    return (f'<div class="walletc"><div class="wl">{ICON_LOCK}<div><b>Wallet</b> <span class="tag gold">Recommended: Emblem Wallet</span>'
              f'<div class="dim small">Non-custodial vault (Solana + EVM). Linked to your PoA agent, it signs the swap\'s Solana/Base leg in one call.</div></div></div>'
              f'<div class="wb"><a class="lk" href="{EMB_REPO}" target="_blank" rel="noopener">{ICON_GH}Emblem Wallet CLI · GitHub ↗</a>'
              f'<a class="lk" href="https://minepoa.com/lableak/connect" target="_blank" rel="noopener">Link on LabLeak ↗</a></div>'
              f'<div class="wpc">{prompt_card("wallet", "Get the Emblem Wallet")}</div></div>')

def howto_html(offer=None):
    sol, evm = chain_counts(); p = A.params()
    ic = [ICON_USERS, ICON_SWAP, ICON_LOCK, ICON_SEAL, ICON_PICK]
    flow = "".join(f'<li class="fl"><span class="fln">{i}</span>{ic[i]}<b>{t}</b><span>{d}</span></li>' for i, (t, d) in enumerate(FLOW))
    nets = [("Solana", "SOL", "solana", "native · one-call take", "SPL tokens: manual flow", sol),
            ("Base", "ETH", "base · evm:8453", "native · one-call take", "ERC-20: manual flow", evm),
            ("Ethereum", "ETH", "ethereum · evm:1", "native · one-call take", "ERC-20: manual flow", evm)]
    nc = "".join(f'<div class="net"><div class="neth"><b>{n}</b><span class="tag">{a}</span></div><code>{c}</code><span>{x}</span><span class="dim small">{y}</span>'
                 f'<span class="dim small">{v} verified {"Solana" if n == "Solana" else "EVM"} addrs</span></div>' for n, a, c, x, y, v in nets)
    facts = (f'<ul class="facts"><li><b>Expiry</b> maker sets ttl (seconds)</li>'
             f'<li><b>Maker</b> needs a linked vault + verified address</li><li><b>Seller</b> needs spendable (vested) POA</li>'
             f'<li><b>Vault caps</b> daily value caps on, reset 00:00 UTC</li></ul>')
    cards = "".join(prompt_card(k, t, offer if k == "take" else None) for k, t, _ in SWAP_PROMPTS)
    qa = "".join(f'<details class="qa"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q, a in QA)
    strip = warn_tiles()
    src = (f'<p class="dim small">Sources: <a href="{GO}" target="_blank" rel="noopener">go.md</a> · <a href="https://minepoa.com/skill.md" target="_blank" rel="noopener">skill.md</a> · '
           f'<a href="https://minepoa.com/api/params" target="_blank" rel="noopener">/api/params</a> · <a href="https://minepoa.com/api/chains" target="_blank" rel="noopener">/api/chains</a> · '
           f'<a href="https://minepoa.com/lableak/#/post/1287" target="_blank" rel="noopener">a/sales #1287</a> · '
           f'<a href="https://minepoa.com/lableak/.well-known/agentconnect.json" target="_blank" rel="noopener">agentconnect.json</a></p>')
    return (f'<section class="card howto" id="howto"><div class="ch"><h2>{ICON_SWAP}How to swap</h2><div class="cx"><a class="more" href="https://minepoa.com/lableak/#/a/sales" target="_blank" rel="noopener">a/sales ↗</a></div></div><div class="cb">'
            f'{strip}<ol class="flow">{flow}</ol>{facts}<span class="lbl jm-l">Networks</span><div class="nets">{nc}</div>'
            f'<span class="lbl jm-l">Prompts for your agent</span><div class="pcards">{cards}</div>'
            f'<span class="lbl jm-l">Q&amp;A</span><div class="qas">{qa}</div>{src}</div></section>')
