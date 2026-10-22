"""The module's HTTP surface. The host server calls api() for JSON and page() for HTML; both take paths without the
/v1 prefix (the host maps /api/v1/... onto /api/...). The explorer side reads swaps only through these same routes
(poascan/swapclient.py): /api/v1/price, /api/v1/swaps, /api/v1/swaps/status, /api/v1/swaps/price-history, /api/v1/swaps/<offer_id>."""
import os, re, mimetypes
from . import config as C, market as M, store as S, pages as P

OFFER = re.compile(r"^/api/swaps/([A-Za-z0-9_-]{1,128})$")   # after /status and /price-history

EVENT = {"swap-offer": "offered", "swap-fill": "filled", "swap-cancel": "cancelled"}

def _verified(chains, addr):
    """{chain: address} for a poa1 address's verified external-chain links, as minepoa.com /api/chains publishes them."""
    c = chains.get(addr) if addr else None
    out = {k: v["addr"] for k, v in (c or {}).items() if isinstance(v, dict) and v.get("verified") and v.get("addr")}
    return out or None

def enrich(rows):
    """Additive fields on offer rows, each only where POAScan already holds the data (no extra upstream reads):
    timeline (ledger swap txs, then expiry), maker_chains and taker_chains (verified links), and on fills
    fee_poa, fill_atts and fill_final. A field with no data is left out, never sent as null."""
    rows = [dict(r) for r in rows]
    if not rows: return rows
    ch = S.chains(); ev = S.events_all(); marks = H.tx_marks([r.get("fill_txid") for r in rows])
    for r in rows:
        tl = [dict(event=EVENT.get(e["kind"], e["kind"]), ts=e["ts"], txid=e["txid"]) for e in ev.get(r["offer_id"], [])]
        if r.get("status") == "expired" and r.get("expires_ts"): tl.append(dict(event="expired", ts=r["expires_ts"]))
        if tl: r["timeline"] = tl
        m = _verified(ch, r.get("maker"))
        if m: r["maker_chains"] = m
        t = _verified(ch, r.get("taker"))
        if t: r["taker_chains"] = t
        if r.get("status") == "filled":
            if r.get("fee_bp") is not None and r.get("poa"): r["fee_poa"] = round(r["poa"] * r["fee_bp"] / 10000, 6)
            mk = marks.get(r.get("fill_txid"))
            if mk:
                if mk[0] is not None: r["fill_atts"] = int(mk[0])
                if mk[1] is not None: r["fill_final"] = bool(mk[1])
    return rows

def offer_json(oid):
    """One offer with its fill and cancel events, or None."""
    r = S.offer(oid)
    if not r: return None
    ev = [{k: e[k] for k in ("txid", "kind", "addr", "ts")} for e in S.events(oid)]
    return dict(offer=enrich([r])[0], events=ev)

def api(path, qs):
    """(rows_or_obj, is_list) for a swap API path, or raises KeyError."""
    if path == "/api/swaps": return enrich(S.swaps_all()), True
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
