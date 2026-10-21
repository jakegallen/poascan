"""The module's HTTP surface. The host server calls api() for JSON and page() for HTML; both take paths without the
/v1 prefix (the host maps /api/v1/... onto /api/...). The explorer side reads swaps only through these same routes
(poascan/swapclient.py): /api/v1/price, /api/v1/swaps, /api/v1/swaps/status, /api/v1/swaps/price-history, /api/v1/swaps/<offer_id>."""
import os, re, mimetypes
from . import config as C, market as M, store as S, pages as P

OFFER = re.compile(r"^/api/swaps/([A-Za-z0-9_-]{1,128})$")   # after /status and /price-history

def offer_json(oid):
    """One offer with its fill and cancel events, or None."""
    r = S.offer(oid)
    if not r: return None
    ev = [{k: e[k] for k in ("txid", "kind", "addr", "ts")} for e in S.events(oid)]
    return dict(offer=dict(r), events=ev)

def api(path, qs):
    """(rows_or_obj, is_list) for a swap API path, or raises KeyError."""
    if path == "/api/swaps": return S.swaps_all(), True
    if path == "/api/swaps/status": return M.swap_status_api(), False
    if path == "/api/swaps/price-history": return M.price_history(), True
    if path == "/api/price": return M.price(), False
    m = OFFER.match(path)
    if m:
        d = offer_json(m.group(1))
        if d is None: raise KeyError(path)
        return d, False
    raise KeyError(path)

def page(path):
    """HTML for the swap page path, or None."""
    return P.page() if path == C.PAGE_PATH else None

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC = {"/static/" + f: (os.path.join(_DIR, f), mimetypes.guess_type(f)[0]) for f in ("swap.js", "swap.css")}

def live():
    """What the host's live snapshot (WebSocket and /api/summary) carries for the swap page: the order book fragment."""
    return {"swapsopen": P.book_html()}
