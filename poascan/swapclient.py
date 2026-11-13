"""The explorer's only way to swap data: the swap module's public API.

In process today (the module is mounted in this app); set POASCAN_SWAP_API to a remote base such as
https://swap.example.com/api/v1 and the same calls go over HTTP instead (cached 30 s, last good copy kept on failure).
Each function returns exactly what the matching endpoint returns."""
import os, json, time, threading, urllib.request

REMOTE = os.environ.get("POASCAN_SWAP_API", "").rstrip("/")
TTL, TIMEOUT = 30, 6
_cache, _lock = {}, threading.Lock()

def _get(path):
    """GET <REMOTE><path> as JSON, cached TTL seconds; on failure the last good copy (or None)."""
    now = time.time()
    with _lock: hit = _cache.get(path)
    if hit and now - hit[0] < TTL: return hit[1]
    try:
        req = urllib.request.Request(REMOTE + path, headers={"User-Agent": "POAScan/1 (+https://poascan.io/about)", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r: d = json.loads(r.read(5_000_000))
        if isinstance(d, dict): d.pop("meta", None)
        with _lock: _cache[path] = (now, d)
        return d
    except Exception:
        return hit[1] if hit else None

def _local(path):
    from . import swap
    try: return swap.api("/api" + path, {})[0]
    except KeyError: return None

def _call(path): return _get(path) if REMOTE else _local(path)

def price():
    """/api/v1/price: the POA/USD reference from fills only."""
    return _call("/price") or dict(usd_per_poa=None, usd_per_1m_poa=None, shown=False, thin=None, sig_figs=None)
def status():
    """/api/v1/swaps/status: availability, open offers and market (market cap, FDV, trades, volume, last trade, best ask).
    The live local book, so open_offers is the real count. An unread database returns {}."""
    try: return _call("/swaps/status") or {}
    except Exception: return {}
def trading_status():
    """Pinned clearance body used by HTTP /api/v1/swaps/status and /api/v1/trading/status (1.26.320).

    Same fields as the request path: write_ok, swap_writes_up, chain, last_incident, plus the market
    fields when the pin has them. Explorer code must use this instead of importing hoststatus.
    A remote swap API falls back to /swaps/status."""
    if REMOTE:
        try: return _get("/trading/status") or _get("/swaps/status") or {}
        except Exception: return {}
    from .swap import hoststatus as SS
    try: return SS.serve() or {}
    except Exception: return {}
def offers(status=None):
    """/api/v1/swaps: every offer, newest activity first; status filters one state (open, filled, cancelled, expired, delisted)."""
    rows = _call("/swaps") or []
    return rows if not status else [r for r in rows if r.get("status") == status]
def offer(oid):
    """/api/v1/swaps/<offer_id>: {offer, events} or None."""
    return _call("/swaps/" + oid) if oid else None
def price_history():
    """/api/v1/swaps/price-history."""
    return _call("/swaps/price-history") or []

def book():
    """Open unexpired asks and last fill per pair from the ingested book (1.26.322).
    Expired offers are out. Bids are always empty: the book is ask-only and never estimated."""
    if REMOTE:
        rows = offers("open") or []
        hist = price_history() or []
        asks, last = [], {}
        now = time.time()
        for r in rows:
            exp = r.get("expires_ts")
            if exp is not None and float(exp) <= now: continue
            if not r.get("poa") or not r.get("want"): continue
            a = (r.get("asset") or "").upper(); ch = (r.get("chain") or "").lower()
            asks.append(dict(id=r.get("offer_id"), poa=r["poa"], want=r["want"], asset=a, chain=ch, exp=exp,
                             px=r["want"] / r["poa"] * 1e6, maker=r.get("maker")))
        asks.sort(key=lambda o: o["px"])
        for r in sorted([x for x in hist if x.get("price_per_1m_poa") is not None], key=lambda x: -int(x.get("ts") or 0)):
            k = (r.get("asset") or "").upper() + "|" + (r.get("chain") or "").lower()
            if k not in last: last[k] = r["price_per_1m_poa"]
        return dict(asks=asks, last=last, bids=[])
    from .swap import market as M
    try:
        asks, last = M.book()
        return dict(asks=asks, last=last, bids=[])
    except Exception:
        return dict(asks=[], last={}, bids=[])

