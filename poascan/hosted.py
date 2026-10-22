"""Hosted route check during the network upgrade: is each hosted surface paused or open again?
One keyless GET per route (no query string, no key, no redirects, first 2 KB only) every 15 minutes, spaced a second
apart, only while the maintenance switch is on. A halted route answers 503 at once with a short body, so this adds
almost no load to minepoa.com. Paused: 503 with the halt text. Open: the route answers as a live route does without
a key (2xx, 400, 401, 403, 405, 422). Anything else (404, 429, other 5xx, timeouts) is unknown and keeps the last
state; a 429 or a 5xx without the halt text also ends the round and skips the next one."""
import os, time, logging, urllib.request, urllib.error
from . import db

log = logging.getLogger("poascan.hosted")
BASE = os.environ.get("POA_BASE", "https://minepoa.com").rstrip("/")
UA = "POAScan-indexer/1.0 (+https://poascan.io; read-only)"
ON = os.environ.get("POASCAN_ROUTE_CHECK", "1") != "0"
EVERY, TIMEOUT, GAP, STALE_S, SKIP_S = 900, 10, 1.0, 3600, 1800   # round interval, fetch timeout, spacing, state trusted for, skip after trouble
FLOOR_S = 600   # hard floor between rounds, kept in the database so restarts and deploys never add a round
BLOB = "hosted_routes"
# id, public label, path. Fixed list: these are the only paths this module can call.
ROUTES = [("mining", "Mining", "/api/hosted/mine"), ("grading", "Grading", "/api/hosted/grade"), ("send", "Send", "/api/hosted/send"),
          ("swap_offer", "Swap offers", "/api/hosted/swap-offer"), ("vote", "Voting", "/api/hosted/vote"), ("export", "Export", "/api/hosted/export")]
LABEL = {i: l for i, l, _ in ROUTES}
OPEN_CODES = (200, 201, 202, 204, 400, 401, 403, 405, 422)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
_OPENER = urllib.request.build_opener(_NoRedirect)

def classify(code, body=b""):
    """paused, open, or None (unknown: keep the last state)."""
    b = (body or b"")[:2048].decode("utf-8", "replace").lower()
    if code == 503 and "halted" in b: return "paused"
    if code in OPEN_CODES: return "open"
    return None

def _get(path):
    """(code, first 2 KB). Raises on network errors."""
    if path not in {p for _, _, p in ROUTES}: raise ValueError("path not in the route list")
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r: return r.status, r.read(2048)
    except urllib.error.HTTPError as e:
        try: body = e.read(2048)
        except Exception: body = b""
        return e.code, body

def job(now=None, get=None):
    """Indexer job. Only while maintenance is switched on; a round after trouble is skipped."""
    from . import maint as M
    if not ON or not M.MAINTENANCE: return
    get = get or _get; now = int(now or time.time())
    prev = db.get_blob(BLOB)[0] or {}
    if (prev.get("skip_until") or 0) > now or now - (prev.get("ts") or 0) < FLOOR_S: return
    routes = dict(prev.get("routes") or {}); skip = None
    for i, (rid, _, path) in enumerate(ROUTES):
        if i and get is _get: time.sleep(GAP)
        try: code, body = get(path)
        except Exception as e:
            log.warning("hosted: %s unknown (%s)", rid, type(e).__name__); continue
        st = classify(code, body)
        if st is None:
            log.warning("hosted: %s unknown (HTTP %s)", rid, code)
            if code == 429 or code >= 500: skip = now + SKIP_S; break
            continue
        old = routes.get(rid) or {}
        routes[rid] = dict(state=st, since=old.get("since") if old.get("state") == st else now, checked=now)
    db.put_blob(BLOB, dict(routes=routes, ts=now, skip_until=skip))

def current(now=None):
    """{id: {label, state, since, checked}} for every route; state is paused, open or unknown (no fresh read)."""
    now = now or time.time(); d = (db.get_blob(BLOB)[0] or {}).get("routes") or {}
    out = {}
    for rid, lab, _ in ROUTES:
        r = d.get(rid) or {}
        fresh = r.get("checked") and now - r["checked"] <= STALE_S
        out[rid] = dict(label=lab, state=r.get("state") if fresh else "unknown", since=r.get("since") if fresh else None, checked=r.get("checked"))
    return out

def state(rid): return current()[rid]["state"]
def any_known(): return any(r["state"] != "unknown" for r in current().values())
def checked_at():
    t = [r["checked"] for r in current().values() if r.get("checked")]
    return max(t) if t else None
