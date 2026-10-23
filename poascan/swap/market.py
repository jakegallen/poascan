"""Swap data: health of the upstream read, the order book, fills, market stats and the one POA/USD reference.
Pure data (dicts and lists); api.py serves it as JSON, pages.py renders it. Fills only: open offers (asks) are never a price."""
import time, statistics
from . import host as H, config as C, store as S

# ---------------- availability ----------------
UPGRADE_MSG = "Swaps are being upgraded. Check back soon."
SOON_MSG = "Swaps are coming soon. Link an Emblem Wallet now to be ready."
def swap_msg(): return UPGRADE_MSG if C.SWAPS_LIVE else SOON_MSG

def _up(name):
    """A mirror host answers from the instance it follows; a host that indexes minepoa.com itself has no hook."""
    f = getattr(H, "upstream_" + name, None)
    return f() if f else None

def _flag():
    """The host's swap flag (POAScan: POASwap's status, read only), or None when the host has none."""
    f = getattr(H, "swap_flag", None)
    return f() if f else None

def _dot(m): return m if m[-1:] in ".!?" else m + "."

def swap_view():
    """What pages show. status: live, paused, coming_soon or unknown (the display keys off it); available: the button only;
    url: where swap links go; message: one terse line. From the host's flag when it has one, else this module's own read."""
    h = swap_health(); fl = _flag()
    if fl is None:
        return dict(status="live" if C.SWAPS_LIVE else "coming_soon", available=h["available"], url=C.LINK_URL,
                    message=None if h["available"] else swap_msg(), open_offers=h["open_offers"], flag=None)
    avail = fl["available"] if fl["available"] is not None else h["available"]   # flag never read since boot: own read
    msg = fl["message"] if fl["basis"] != "fallback" or avail else swap_msg()   # fallback: POAScan's own read decides the line
    return dict(status=fl["status"], available=bool(avail), url=fl["url"], message=_dot(msg), open_offers=h["open_offers"], flag=fl)

def legacy_state(status, available):
    """v1 state from status: available, upgrading (live but not available, or paused), coming_soon, or unknown."""
    return {"live": "available" if available else "upgrading", "paused": "upgrading", "coming_soon": "coming_soon"}.get(status, "unknown")

def swap_health():
    """Upstream /api/swaps health from the indexer's own fetch log. No extra upstream calls."""
    u = _up("health")
    if u is not None: return u
    r = H.fetch_log(C.SWAPS_EP)
    now = int(time.time()); ok, er = r.get("last_ok"), r.get("last_err")
    failed = bool(r.get("fails")) and (er or 0) >= (ok or 0)
    age = (now - ok) if ok else None
    available = C.SWAPS_LIVE and not failed and age is not None and age <= C.FRESH_S
    code = (r.get("err") or "").replace("HTTP ", "").split(":")[0][:40] if failed else ("200" if ok else None)
    n = S.open_count()
    return dict(available=available, state="available" if available else ("upgrading" if C.SWAPS_LIVE else "coming_soon"), last_good_read=ok, last_good_read_age_s=age,
                last_attempt=max(ok or 0, er or 0) or None, last_attempt_status=code, open_offers=n, fresh_after_s=C.FRESH_S)

# ---------------- price: the one POA/USD reference ----------------
PRICE_WINDOW_S = 7 * 86400          # no fill in this window: no USD anywhere
THIN_FILLS, THIN_USD = 5, 100.0     # fewer fills, or less volume, in the window: thin (2 significant figures)
MEDIAN_N = 5                        # with this many fills in the window, the median of the last 5 replaces the last fill

def _ref(r):
    """USD per unit of the asset a fill paid in: USDC at 1, else the reference recorded at fill time, else the current one."""
    a = (r.get("asset") or "").upper()
    if a == "USDC": return 1.0
    return r.get("fill_usd") or S.fx().get(a) or None

def sig(v, n):
    return float(f"{v:.{n}g}") if v else v

@H.cached("swap_price", 30)
def price():
    """POA in USD from filled swaps only; open offers (asks) are never used. Served as /api/v1/price."""
    u = _up("price")
    if u is not None: return u
    now = time.time(); fx = S.fx()
    fl = sorted((r for r in S.swaps_all() if r["status"] == "filled" and r["fill_ts"] and r["poa"] and r["want"]), key=lambda r: -r["fill_ts"])
    pts = [(r, r["want"] / r["poa"] * u, r["want"] * u) for r in fl for u in [_ref(r)] if u]
    win = [p for p in pts if p[0]["fill_ts"] >= now - PRICE_WINDOW_S]
    vol = sum(p[2] for p in win); last = int(fl[0]["fill_ts"]) if fl else None
    out = dict(usd_per_poa=None, usd_per_1m_poa=None, shown=False, thin=None, basis=None, sig_figs=None,
               fills_7d=len(win), volume_7d_usd=round(vol, 2), last_fill_ts=last, last_fill_age_s=int(now - last) if last else None,
               window_s=PRICE_WINDOW_S, thin_below=dict(fills=THIN_FILLS, volume_usd=THIN_USD), median_of=MEDIAN_N,
               asks_used=False, usd_ref=fx.get("src") or "CoinGecko", method=C.METHOD_URL)
    if not win: return out
    thin = len(win) < THIN_FILLS or vol < THIN_USD
    if len(win) >= MEDIAN_N: px, basis = statistics.median(p[1] for p in win[:MEDIAN_N]), "median_last_5_fills"
    else: px, basis = win[0][1], "last_fill"
    n = 2 if thin else 3
    return dict(out, usd_per_poa=sig(px, n), usd_per_1m_poa=sig(px * 1e6, n), shown=True, thin=thin, basis=basis, sig_figs=n)

def per_1m(r):
    """Native units per 1M POA, and USD per 1M POA when a public reference exists."""
    if not r.get("poa") or not r.get("want"): return None, None
    pm = r["want"] / r["poa"] * 1e6
    usd = (S.fx().get((r.get("asset") or "").upper()) or None)
    return pm, (pm * usd if usd else None)

# ---------------- market stats (fills only) ----------------
def swap_stats():
    rows = S.swaps_all(); op = [r for r in rows if r["status"] == "open"]
    fills = [r for r in rows if r["status"] == "filled"]
    last = max(fills, key=lambda r: r["fill_ts"] or 0) if fills else None
    lp = per_1m(last) if last else (None, None)
    asks = [(per_1m(r), r) for r in op] if fills else []
    best = min(((p[1] if p[1] is not None else None, p[0], r) for p, r in asks if p[0] is not None), key=lambda x: (x[0] is None, x[0] or x[1]), default=None)
    return dict(open=len(op), on_offer=sum(r["poa"] or 0 for r in op), fills=len(fills), total=len(rows),
                last=(lp, last["asset"]) if last else None, best=best)

def swap_market():
    """Market stats from filled swaps only (no estimate from asks). USD via the CoinGecko reference; USDC counts at 1."""
    u = _up("market")
    if u is not None: return u
    now = time.time(); f = S.fx(); usd = lambda a: 1.0 if (a or "").upper() == "USDC" else (f.get((a or "").upper()) or None)
    fl = sorted([r for r in S.swaps_all() if r["status"] == "filled" and r["fill_ts"] and r["poa"] and r["want"]], key=lambda r: -r["fill_ts"])
    last = fl[0] if fl else None
    px = (last["want"] / last["poa"] * usd(last["asset"])) if last and usd(last["asset"]) else None   # USD per POA, last fill (raw)
    pr = price(); gp = pr["usd_per_poa"]   # guarded reference for Market Cap and FDV: hidden after 7 days without a fill
    circ = H.circulating(); mined = H.supply()
    day = [r for r in fl if r["fill_ts"] >= now - 86400]
    vol = [r["want"] * usd(r["asset"]) for r in day if usd(r["asset"])]
    fin = H.final_fill_ids()
    done = [r for r in fl if r["fill_txid"] in fin]
    at = lambda r: r.get("fill_usd") or usd(r["asset"])   # USD at fill time when recorded, else the current reference
    vall = [r["want"] * at(r) for r in done if at(r)]
    st = swap_stats()
    r8 = lambda v: float(f"{v:.8g}") if v is not None else None   # the page shows 6 significant figures
    lt = dict(per_1m_poa=r8(st["last"][0][0]), asset=st["last"][1]) if st["last"] else None
    ba = dict(per_1m_poa=r8(st["best"][1]), asset=st["best"][2]["asset"]) if st["best"] else None
    return dict(last_fill_usd_per_poa=float(f"{px:.6g}") if px else px, last_fill_ts=int(last["fill_ts"]) if last else None,
                market_cap_usd=round(gp * circ, 2) if gp and circ else None, fdv_usd=round(gp * mined, 2) if gp and mined else None,
                circulating_supply=circ, mined_supply=mined, trades_24h=len(day),
                volume_24h_usd=round(sum(vol), 2) if vol else (None if day else 0.0),
                trades_all_time=len(done), volume_all_time_usd=round(sum(vall), 2) if vall else (None if done else 0.0),
                usd_ref=f.get("src") or "CoinGecko", price=pr,
                last_trade=lt, best_ask=ba, poa_on_offer=st["on_offer"], fills=st["fills"],
                usd_ref_rates={k: f.get(k) for k in ("SOL", "ETH")}, **_rates_ts())

def _rates_ts():
    """When the USD reference rates were last written (left out when there are none yet)."""
    t = S.fx_ts()
    return dict(usd_ref_rates_updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))) if t else {}

def swap_status_api():
    """/api/v1/swaps/status: availability plus market. The explorer reads swaps only through this, /price and /swaps."""
    h = swap_health(); iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None
    d = dict(available=h["available"], state=h["state"], message=None if h["available"] else swap_msg(),
                last_good_read=iso(h["last_good_read"]), last_good_read_age_s=h["last_good_read_age_s"], last_attempt=iso(h["last_attempt"]),
                last_attempt_status=h["last_attempt_status"], open_offers=h["open_offers"], fresh_after_s=h["fresh_after_s"],
                upstream=C.UPSTREAM + C.SWAPS_EP, url=C.LINK_URL if C.LINK_URL.startswith("https://") else C.PAGE_URL, market=swap_market(), names=swap_names())
    fl = _flag()
    if fl is None: return d
    v = swap_view()   # POASwap's flag decides status, available, message and url; POAScan's own read stays in last_good_read and open_offers
    d.update(status=v["status"], available=v["available"], state=legacy_state(v["status"], v["available"]), message=v["message"], url=v["url"],
             swaps_live=fl["swaps_live"], reason=fl["reason"], open_offer_count=fl["open_offer_count"], updated_at=fl["updated_at"],
             source=fl["source"], fetched_at=fl["fetched_at"], flag_basis=fl["basis"], flag_version=fl["version"])
    return d

def swap_names():
    """Agent names for the makers and takers in the book (so a mirror can link them without a names feed)."""
    nm = H.names(); ads = {a for r in S.swaps_all() for a in (r.get("maker"), r.get("taker")) if a}
    return {a: nm[a] for a in sorted(ads) if nm.get(a)}

# ---------------- book and history ----------------
# go.md SWAPS: open chains solana, ethereum, base; one-call take pays native SOL/ETH; token legs (USDC on Solana) use the coordinated flow
SUPPORTED = [("SOL", "solana"), ("ETH", "base"), ("ETH", "ethereum"), ("USDC", "solana")]

def rows():
    rs = S.swaps_all()
    return [r for r in rs if r["status"] == "open"], sorted([r for r in rs if r["status"] == "filled" and r["fill_ts"]], key=lambda r: -r["fill_ts"])

def book(asset=None):
    op, fl = rows(); now = time.time()
    asks = [dict(id=r["offer_id"], poa=r["poa"], want=r["want"], asset=(r["asset"] or "").upper(), chain=r["chain"], exp=r["expires_ts"],
                 px=r["want"] / r["poa"] * 1e6, maker=r["maker"]) for r in op if r["poa"] and r["want"] and (not r["expires_ts"] or r["expires_ts"] > now)]
    last = {}
    for r in fl:
        a = (r["asset"] or "").upper()
        k = a + "|" + (r["chain"] or "").lower()
        if k not in last and r["poa"] and r["want"]: last[k] = r["want"] / r["poa"] * 1e6
    asks.sort(key=lambda o: o["px"])
    return asks, last

def pairs():
    """Every pair the network supports, plus any other pair seen in the book; pairs with live offers first."""
    asks, _ = book(); n = {}
    for o in asks: n[(o["asset"], (o["chain"] or "").lower())] = n.get((o["asset"], (o["chain"] or "").lower()), 0) + 1
    ps = list(SUPPORTED) + [k for k in n if k not in SUPPORTED]
    return sorted(ps, key=lambda k: -n.get(k, 0)), n

def price_history():
    """One row per filled swap: POA price per 1M POA in the paying asset."""
    out = []
    for r in H.q("SELECT offer_id, fill_txid, fill_ts, chain, asset, poa, want FROM swaps WHERE status='filled' AND fill_ts IS NOT NULL ORDER BY fill_ts"):
        pm = (r["want"] / r["poa"] * 1e6) if r["poa"] and r["want"] else None
        out.append(dict(ts=r["fill_ts"], asset=(r["asset"] or "").upper() or None, chain=r["chain"], poa=r["poa"], paid=r["want"], price_per_1m_poa=pm, offer_id=r["offer_id"], fill_txid=r["fill_txid"]))
    return out
