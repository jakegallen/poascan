"""The module's HTTP surface. The host server calls api() for JSON and page() for HTML; both take paths without the
/v1 prefix (the host maps /api/v1/... onto /api/...). The explorer side reads swaps only through these same routes
(poascan/swapclient.py): /api/v1/price, /api/v1/swaps, /api/v1/swaps/status, /api/v1/swaps/price-history, /api/v1/swaps/<offer_id>."""
import hashlib, json, os, re, mimetypes, threading, time
from . import config as C, market as M, store as S, pages as P, host as H

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
    fee_poa, fill_atts and fill_final. A field with no data is left out, never sent as null, except fill_epoch:
    every filled row carries it, null when the host cannot place the fill in an epoch. Unfilled rows leave it out.
    Every row carries settle(): taker_credit, taker_credit_at, taker_credit_txid, refund_txid, refund_at, receipt_state
    (null when not applicable)."""
    rows = [dict(r) for r in rows]
    if not rows: return rows
    ch = S.chains(); ev = S.events_all(); marks = H.tx_marks([r.get("fill_txid") for r in rows]); rs = S.receipt_signed()
    ep = getattr(H, "epoch_of_ts", None)   # optional host hook: network epoch of a ledger timestamp
    for r in rows:
        tl = [dict(event=EVENT.get(e["kind"], e["kind"]), ts=e["ts"], txid=e["txid"]) for e in ev.get(r["offer_id"], [])]
        if r.get("status") == "expired" and r.get("expires_ts"): tl.append(dict(event="expired", ts=r["expires_ts"]))
        if tl: r["timeline"] = tl
        m = _verified(ch, r.get("maker"))
        if m: r["maker_chains"] = m
        t = _verified(ch, r.get("taker"))
        if t: r["taker_chains"] = t
        if r.get("status") == "filled":
            r["fill_epoch"] = ep(r.get("fill_ts")) if ep else None   # always on fills: null when the epoch is not determinable
            if r.get("fee_bp") is not None and r.get("poa"): r["fee_poa"] = round(r["poa"] * r["fee_bp"] / 10000, 6)
            mk = marks.get(r.get("fill_txid"))
            if mk:
                if mk[0] is not None: r["fill_atts"] = int(mk[0])
                if mk[1] is not None: r["fill_final"] = bool(mk[1])
        r.update(settle(r, r["offer_id"] in rs))
    return rows

def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts))) if ts else None

def settle(r, signed):
    """Settlement fields from the archived public txs only (no extra reads). taker_credit: on a filled offer (its
    swap-fill is final), poa minus fee_poa, at the fill tx time. refund_txid: on a cancelled offer, the final swap-cancel
    that returned the escrow. An expired offer keeps refund_txid null until the maker cancels; null is not proof the
    escrow stayed locked. receipt_state: 'signed' once a finalized swap-fill tx carries the seller's receipt signature;
    receipts before a fill are not public, so null is not proof none exists."""
    out = dict(taker_credit=None, taker_credit_at=None, taker_credit_txid=None, refund_txid=None, refund_at=None, receipt_state="signed" if signed else None)
    if r.get("status") == "filled" and r.get("fill_txid"):
        if r.get("poa") and r.get("fee_bp") is not None:
            out["taker_credit"] = round(r["poa"] - round(r["poa"] * r["fee_bp"] / 10000, 6), 6)
        out["taker_credit_at"] = _iso(r.get("fill_ts")); out["taker_credit_txid"] = r["fill_txid"]
    if r.get("status") == "cancelled" and r.get("cancel_txid"):
        out["refund_txid"] = r["cancel_txid"]; out["refund_at"] = _iso(r.get("cancel_ts"))
    return out

def offer_json(oid):
    """One offer with its fill and cancel events, or None."""
    r = S.offer(oid)
    if not r: return None
    ev = [{k: e[k] for k in ("txid", "kind", "addr", "ts", "final")} for e in S.events(oid) if not e["dropped"]]
    return dict(offer=enrich([r])[0], events=ev)

# Response cache (SC-004): each swap route's data is built once per data version and reused for at most CACHE_TTL s.
# The version moves when the swap job writes (every 60 s), a swap tx is stored or finalizes, the USD reference, the
# chains blob or the status and epochs blobs change, or the upstream read health changes. Mirrors polling every 60 s
# (POASwap) get a stored copy instead of paying a cold recompute. One build per route at a time.
CACHE_TTL = 30
_rc, _rc_lock, _rc_build = {}, threading.Lock(), {}

def _version():
    v = H.q1("SELECT (SELECT MAX(updated) FROM swaps) AS u, (SELECT COUNT(*) FROM swaps) AS n, (SELECT COUNT(*) FROM swap_events) AS e, "
             "(SELECT COALESCE(SUM(final), 0) FROM swap_events) AS f, (SELECT COALESCE(SUM(dropped), 0) FROM swap_events) AS d") or {}
    fl = H.fetch_log(C.SWAPS_EP)
    return (v.get("u"), v.get("n"), v.get("e"), v.get("f"), v.get("d"), fl.get("last_ok"), fl.get("last_err"), fl.get("fails"),
            tuple(H.blob_ts(k) for k in ("fx", "chains", "status", "epochs")) if hasattr(H, "blob_ts") else None,
            H.swap_flag_version() if hasattr(H, "swap_flag_version") else None)   # the host's swap flag (POAScan: each POASwap read)

def _build(path):
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

def _cached(path):
    """(data, is_list, etag) from the cache when the version matches and the copy is under CACHE_TTL s old, else rebuilt."""
    now = time.time(); ver = _version()
    with _rc_lock:
        hit = _rc.get(path)
        if hit and hit[1] == ver and now - hit[0] < CACHE_TTL: return hit[2]
        lk = _rc_build.setdefault(path, threading.Lock())
    with lk:
        with _rc_lock:
            hit = _rc.get(path)
            if hit and hit[1] == ver and time.time() - hit[0] < CACHE_TTL: return hit[2]
        data, is_list = _build(path)
        tag = 'W/"' + hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:20] + '"'
        with _rc_lock:
            if len(_rc) > 512: _rc.clear(); _rc_build.clear()
            _rc[path] = (time.time(), ver, (data, is_list, tag))
        return data, is_list, tag

def _fresh_age(d):
    """The status copy may be up to CACHE_TTL s old: its age field is recomputed per request."""
    ok = H.fetch_log(C.SWAPS_EP).get("last_ok")
    if d.get("last_good_read_age_s") is None or not ok: return d
    return dict(d, last_good_read_age_s=int(time.time()) - int(ok))

ETAG_ROUTES = ("/api/swaps", "/api/swaps/price-history")   # list routes: unchanged data answers If-None-Match with 304

def api(path, qs):
    """(rows_or_obj, is_list) for a swap API path, or raises KeyError."""
    data, is_list, _ = _cached(path)
    if path == "/api/swaps/status": data = _fresh_age(data)
    return data, is_list

def etag(path):
    """Weak ETag of a list route's current data (None for other routes)."""
    return _cached(path)[2] if path in ETAG_ROUTES else None

def page(path):
    """HTML for the swap page path, or None."""
    return P.page() if path == C.PAGE_PATH else None

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC = {"/static/" + f: (os.path.join(_DIR, f), mimetypes.guess_type(f)[0]) for f in ("swap.js", "swap.css")}

def live():
    """What the host's live snapshot (WebSocket and /api/summary) carries for the swap page: the order book fragment."""
    return {"swapsopen": P.book_html()}
