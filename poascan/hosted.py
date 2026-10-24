"""Hosted route check during the network upgrade: is each hosted surface paused or open again?
One keyless GET per route (no query string, no key, no redirects, first 2 KB only) every 15 minutes, spaced a second
apart, only while the maintenance switch is on. A halted route answers 503 at once with a short body, so this adds
almost no load to minepoa.com. Paused: 503 with the halt text. Open: the route answers as a live route does without
a key (2xx, 400, 401, 403, 405, 422). Anything else (404, 429, other 5xx, timeouts, network errors) is unknown: it never
changes the shown state, which keeps the last clear read and its time however old it is (only a route never read clearly
shows unknown). A 429 or a 5xx without the halt text also ends the round and skips the next one. Each route also counts
its consecutive clear reads of the same state (streak), so a caller can wait for two halted reads in a row."""
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
    """paused, open, or None (unknown: keep the last state). Open needs a JSON answer from the app itself, so an edge
    block page (HTML 403, challenge) never reads as a reopened route."""
    b = (body or b"")[:2048].decode("utf-8", "replace").strip().lower()
    if code == 503 and "halted" in b: return "paused"
    if code in OPEN_CODES and b[:1] in ("{", "[") and "halted" not in b:
        from . import strain as _ST   # a strain stand-in (notice in place of the route's answer) never reads as reopened
        return None if _ST.text_hit(b) else "open"
    return None

def _get(path):
    """(code, first 2 KB). Raises on network errors."""
    if path not in {p for _, _, p in ROUTES}: raise ValueError("path not in the route list")
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept": "application/json"})
    from . import indexer as _I   # upstream request counter (/ops/visits)
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r: _I.count(path + " (route check)", r.status); return r.status, r.read(2048)
    except urllib.error.HTTPError as e:
        _I.count(path + " (route check)", e.code)
        try: body = e.read(2048)
        except Exception: body = b""
        return e.code, body
    except Exception: _I.count(path + " (route check)", "err"); raise

def job(now=None, get=None):
    """Indexer job. Only while maintenance is switched on; a round after trouble is skipped."""
    from . import maint as M
    if not ON or not M.MAINTENANCE or M.complete(): return   # the upgrade is officially complete: no more route checks
    get = get or _get; now = int(now or time.time())
    prev = db.get_blob(BLOB)[0] or {}
    if (prev.get("skip_until") or 0) > now:
        from . import indexer as _I   # a round skipped after trouble: one backoff denial per route (/ops/internal)
        for _, _, path in ROUTES: _I.deny(path + " (route check)", "backoff")
        return
    if now - (prev.get("ts") or 0) < FLOOR_S: return
    routes = dict(prev.get("routes") or {}); skip = None
    for i, (rid, _, path) in enumerate(ROUTES):
        if i and get is _get: time.sleep(GAP)
        old = routes.get(rid) or {}; t0 = time.monotonic()
        try: code, body = get(path)
        except Exception as e:
            record(now, path, "timeout" if "timeout" in type(e).__name__.lower() or "timed out" in str(e).lower() else "error", t0, False)
            log.warning("hosted: %s no answer (%s)", rid, type(e).__name__); routes[rid] = dict(old, tried=now, slow_since=old.get("slow_since") or now); continue
        st = classify(code, body); record(now, path, str(int(code)), t0, st is not None)
        if st is None:
            log.warning("hosted: %s unknown (HTTP %s)", rid, code); routes[rid] = dict({k: v for k, v in old.items() if k != "slow_since"}, tried=now)   # it answered: not slow
            if code == 429 or code >= 500: skip = now + SKIP_S; break
            continue
        same = old.get("state") == st
        routes[rid] = dict(state=st, since=old.get("since") if same else now, checked=now, code=code, tried=now,
                           streak=(old.get("streak") or 1) + 1 if same else 1)
    db.put_blob(BLOB, dict(routes=routes, ts=now, skip_until=skip))

# Per-read log of the route check (1.26.26, private /ops/internal): time, route path, HTTP code (or timeout / error),
# latency and whether the read was clear (paused or open). No body, key or query string. Kept CHECKS_KEEP_DAYS.
CHECKS_KEEP_DAYS = 400
def _ensure_checks():
    db.write("CREATE TABLE IF NOT EXISTS route_checks(ts INTEGER NOT NULL, route TEXT NOT NULL, code TEXT NOT NULL CHECK (length(code) <= 8), "
             "ms INTEGER, ok INTEGER NOT NULL)")
    db.write("CREATE INDEX IF NOT EXISTS route_checks_ts ON route_checks(ts)")
def record(now, path, code, t0, ok):
    try:
        _ensure_checks()
        db.write("INSERT INTO route_checks VALUES(?,?,?,?,?)", (int(now), path, code[:8], int((time.monotonic() - t0) * 1000), 1 if ok else 0))
        db.write("DELETE FROM route_checks WHERE ts < ?", (int(now) - CHECKS_KEEP_DAYS * 86400,))
    except Exception as e: log.warning("hosted: route check log failed (%s)", type(e).__name__)

def current(now=None):
    """{id: {label, state, since, checked, streak, stale, tried}} for every route. state is the last clear read (paused or open),
    kept however old it is; unknown only when the route was never read clearly. stale says the last clear read is over an hour old."""
    now = now or time.time(); d = (db.get_blob(BLOB)[0] or {}).get("routes") or {}
    out = {}
    for rid, lab, _ in ROUTES:
        r = d.get(rid) or {}; known = r.get("state") in ("open", "paused") and r.get("checked")
        out[rid] = dict(label=lab, state=r["state"] if known else "unknown", since=r.get("since") if known else None, checked=r.get("checked"),
                        streak=int(r.get("streak") or 1) if known else 0, stale=bool(known and now - r["checked"] > STALE_S), tried=r.get("tried"),
                        slow=bool(r.get("slow_since")), slow_since=r.get("slow_since"))   # slow: the newest read timed out or got no answer
    return out

def state(rid): return current()[rid]["state"]
def counts():
    """(open, known) over the route list. open counts only routes answering now: a slow route is not counted as open."""
    c = current(); return sum(1 for v in c.values() if v["state"] == "open" and not v["slow"]), sum(1 for v in c.values() if v["state"] != "unknown" or v["slow"])
def slow(): return [k for k, v in current().items() if v["slow"]]
def any_known(): return any(r["state"] != "unknown" for r in current().values())
def checked_at():
    t = [r["checked"] for r in current().values() if r.get("checked")]
    return max(t) if t else None
