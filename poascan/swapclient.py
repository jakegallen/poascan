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
    """/api/v1/swaps/status: availability, open offers and market (market cap, FDV, trades, volume, last trade, best ask)."""
    return _call("/swaps/status") or {}
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
