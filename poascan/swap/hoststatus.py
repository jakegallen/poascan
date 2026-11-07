"""Fast /api/v1/swaps/status (1.26.278).

The request path never reads SQLite and never calls minepoa.com. It returns the pinned
copy, or an UNKNOWN body when none exists yet, and asks one background thread to refresh.
A refresh that hangs does not block the response.

Freshness follows the probe that produced each row, not the pin's build time.
The pin is rebuilt every 20s. A pin older than PIN_STALE_S (300s) is a dead refresher:
the whole copy is UNKNOWN, so it cannot keep serving open.
stale_after_s is hosted.WRITE_STALE_S (1920s): the swap-offer probe's steady gap.
That probe runs every 600s, plus or minus 60s, and every 1800s plus or minus 60s after
three identical reads. The indexer notices the stored next_at on its 60s tick.
1800 + 60 + 60 = 1920. The same constant ages swap_route, so a read cannot be Down on
one surface and unknown on another. A 300s cutoff would mark that healthy probe UNKNOWN
for most of each cycle. Join-pow and
notices refresh every 300s, so those rows go UNKNOWN after JOIN_STALE_S (420s).
A row older than its limit is UNKNOWN, not DOWN. DOWN is only a fresh halt or failure.

Join clearance (route, notices, maintenance) is a separate block from swap write clearance.
Neither fails open. Mining does not use this endpoint. Swap writes gate on write_ok.
"""
import threading, time
from ..hosted import WRITE_STALE_S as STALE_AFTER_S
# join-pow and /api/notices are scheduled every 300s. 420s covers one late loop.
JOIN_STALE_S = 420
# The pin thread rebuilds every _REFRESH_S. Past this, the copy is not being refreshed.
PIN_STALE_S = 300
WRITE_ROUTES = ("swap_offer",)
_REFRESH_S = 20

_lock = threading.Lock()
_pin = {"facts": None, "extra": None, "built_at": None}
_building = [False]


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(t))) if t else None


def _age(ts, now):
    if ts is None: return None
    return max(0, int(now - ts))


def _row(kind, ts, now, limit):
    """One OK / DOWN / UNKNOWN row. Missing or older than this probe's limit is UNKNOWN, never DOWN.
    Returns (row, too_old). too_old is not part of the public row."""
    age = _age(ts, now)
    # No timestamp yet is UNKNOWN, not a stale copy of a real read.
    too_old = age is not None and age > limit
    if ts is None or age is None or too_old or kind not in ("OK", "DOWN"):
        return dict(state="UNKNOWN", as_of=_iso(ts), age_s=age), too_old
    return dict(state=kind, as_of=_iso(ts), age_s=age), False


def _agg(rows):
    """Fail closed: DOWN if any part is DOWN, else UNKNOWN if any part is not OK, else OK.
    as_of and age_s follow the oldest part that has a time, so a stale input is visible."""
    states = [r["state"] for r in rows]
    if "DOWN" in states: st = "DOWN"
    elif any(s != "OK" for s in states): st = "UNKNOWN"
    else: st = "OK"
    aged = [r for r in rows if r.get("age_s") is not None]
    if len(aged) != len(rows):
        return st, None, None
    old = max(aged, key=lambda r: r["age_s"])
    return st, old.get("as_of"), old.get("age_s")


def _blank_join():
    u = dict(state="UNKNOWN", as_of=None, age_s=None)
    return dict(state="UNKNOWN", as_of=None, age_s=None, route=dict(u, name="joining"), notices=dict(u), maintenance=dict(u))


def _blank_writes():
    routes = {n: dict(state="UNKNOWN", as_of=None, age_s=None) for n in WRITE_ROUTES}
    return dict(state="UNKNOWN", as_of=None, age_s=None, routes=routes)


def _force_unknown(block):
    """A stale copy must not keep OK or DOWN."""
    out = dict(block, state="UNKNOWN")
    if "route" in block:
        out["route"] = dict(block["route"], state="UNKNOWN")
        out["notices"] = dict(block["notices"], state="UNKNOWN")
        out["maintenance"] = dict(block["maintenance"], state="UNKNOWN")
    if "routes" in block:
        out["routes"] = {k: dict(v, state="UNKNOWN") for k, v in block["routes"].items()}
    return out


def render(facts, extra, built_at, now):
    """Public body from stored facts. Pure: no database and no network."""
    now = now if now is not None else time.time()
    age = _age(built_at, now)
    # A dead pin is stale on its own. Probe rows are judged by their own timestamps.
    pin_stale = built_at is None or age is None or age > PIN_STALE_S
    if not facts:
        join, writes = _blank_join(), _blank_writes()
        write_ok = False
        probe_stale = True
    else:
        jr, jr_old = _row(facts["join_route"]["kind"], facts["join_route"]["ts"], now, JOIN_STALE_S)
        jr["name"] = "joining"
        # Notices are a MANDATORY security signal and stay FAIL-CLOSED: a stale notices fetch goes
        # UNKNOWN (via _agg below), which blocks join clearance. We deliberately do NOT degrade a stale
        # notices fetch to last-known-clear: during a notices-endpoint outage minepoa could publish a
        # NEW critical pause/migration we cannot see, so "last we knew it was clear" is not safe for a
        # security notice (reviewed 2026-11-07). A known-critical row stays DOWN, a never-read row stays
        # UNKNOWN, and a transient false-"unknown" during an outage is the accepted, safe trade.
        nt, nt_old = _row(facts["notices"]["kind"], facts["notices"]["ts"], now, JOIN_STALE_S)
        mt, mt_old = _row(facts["maintenance"]["kind"], facts["maintenance"]["ts"], now, PIN_STALE_S)
        jst, jas, jag = _agg([jr, nt, mt])
        join = dict(state=jst, as_of=jas, age_s=jag, route=jr, notices=nt, maintenance=mt)
        routes = {}
        sw_old = False
        for name in WRITE_ROUTES:
            src = (facts.get("writes") or {}).get(name) or {"kind": "UNKNOWN", "ts": None}
            routes[name], old = _row(src["kind"], src["ts"], now, STALE_AFTER_S)
            sw_old = sw_old or old
            if src.get("probe"): routes[name]["probe"] = src["probe"]
        wst, was, wag = _agg(list(routes.values()))
        writes = dict(state=wst, as_of=was, age_s=wag, routes=routes)
        probe_stale = jr_old or nt_old or mt_old or sw_old
        write_ok = wst == "OK" and not pin_stale and not sw_old
    if pin_stale:
        join, writes = _force_unknown(join), _force_unknown(writes)
        write_ok = False
    stale = pin_stale or probe_stale
    flag = (facts or {}).get("flag_status")
    available = bool(write_ok) and flag != "paused" and not stale
    if writes["state"] == "DOWN":
        message = "Order placement is failing on the network."
    elif not write_ok:
        message = "Swap write status is unknown. No write."
    else:
        message = None
    body = dict(extra or {})
    body.update(as_of=_iso(built_at), age_s=age, stale=bool(stale), stale_after_s=STALE_AFTER_S,
                available=available, write_ok=bool(write_ok), join=join, swap_writes=writes,
                gate={"mining": "do not use this endpoint", "join": "join.state", "swap_write": "write_ok"})
    if available:
        body["state"] = "available"
    elif writes["state"] == "DOWN" and not stale:
        body["state"] = "upgrading"
    else:
        body["state"] = "unknown"
    body["message"] = message if message is not None else body.get("message")
    # Keys the book and the upstream read own. Absent until that build runs, never omitted.
    if "open_offers" not in body: body["open_offers"] = None
    if "last_good_read" not in body: body["last_good_read"] = None
    body["swaps_writable"] = True if write_ok else (False if writes["state"] == "DOWN" and not stale else None)
    _legacy(body)
    return body


def _legacy(body):
    """Fields POASwap already reads. Same names. A stale or unknown copy is never OK or open.
    active true means stop. join_state open only when join.state is OK and the copy is fresh.
    swap_route.state and writes.swap_offer.state are open only when that write route is OK and fresh."""
    offer = body["swap_writes"]["routes"]["swap_offer"]
    sw = offer["state"]
    if sw == "UNKNOWN":
        leg, writable = "unknown", None
    elif sw == "DOWN":
        leg, writable = ("paused" if offer.get("probe") == "paused" else "down"), False
    else:
        leg, writable = "open", True
    checked = offer.get("as_of")
    # stale means the read is too old to trust. A fresh halt or failure stays stale false.
    leg_stale = bool(body["stale"] or sw == "UNKNOWN")
    def honest(obj):
        return isinstance(obj, dict) and obj.get("state") == leg and not (leg == "open" and body["stale"])
    prev_w = body.get("writes") if isinstance(body.get("writes"), dict) else {}
    prev_offer = prev_w.get("swap_offer") if isinstance(prev_w.get("swap_offer"), dict) else None
    if honest(prev_offer):
        body["writes"] = prev_w
    else:
        body["writes"] = {"swap_offer": {"state": leg, "http": None, "checked_at": checked, "since": None, "stale": leg_stale}}
    body["swaps_writable"] = writable
    prev_r = body.get("swap_route") if isinstance(body.get("swap_route"), dict) else None
    if not honest(prev_r):
        body["swap_route"] = dict(state=leg, display=leg, writable=writable, probe_state=leg, http=None,
                                  checked_at=checked, since=None, stale=leg_stale,
                                  feed={"open": "OK", "down": "Down"}.get(leg), label=leg.capitalize() if leg != "unknown" else "Unknown",
                                  basis="write_check")
    js = body["join"]["state"]
    if body["stale"] or js == "UNKNOWN":
        body["join_state"] = "unknown"
    elif body["join"]["route"]["state"] == "DOWN":
        body["join_state"] = "halted"
    elif js == "DOWN":
        body["join_state"] = "paused"
    else:
        body["join_state"] = "open"
    maint_unknown = body["stale"] or body["join"]["maintenance"]["state"] != "OK"
    body["maintenance_active"] = bool(maint_unknown or body["join"]["maintenance"]["state"] == "DOWN")
    if "status" not in body: body["status"] = "unknown"
    return body


def _unknown(now):
    return render(None, {"status": "unknown", "message": "Swap write status is unknown. No write."}, None, now)


def _kind_join(state):
    """Routwatch joining: open is OK, a 503 halt is DOWN, anything else (timeout, unread) is UNKNOWN."""
    if state == "open": return "OK"
    if state == "halted": return "DOWN"
    return "UNKNOWN"


def _kind_write(state):
    """Write probe: open is OK, paused (503 halt) or down (failure answer) is DOWN, else UNKNOWN."""
    if state == "open": return "OK"
    if state in ("paused", "down"): return "DOWN"
    return "UNKNOWN"


def _facts(now):
    """Local blobs only. No minepoa.com call."""
    from .. import db, hosted as HO
    now = int(now)
    rw = (db.get_blob("routewatch")[0] or {}).get("routes") or {}
    j = rw.get("joining") or {}
    join_route = {"kind": _kind_join(j.get("state")), "ts": j.get("as_of")}
    fl = db.q1("SELECT last_ok FROM fetch_log WHERE endpoint=?", ("/api/notices",)) or {}
    nt = fl.get("last_ok")
    notices_kind = "UNKNOWN"
    try:
        blob = db.get_blob("notices")[0]
        if isinstance(blob, dict) and nt:
            active = [x for x in (blob.get("active") or []) if isinstance(x, dict)
                      and not (isinstance(x.get("expires_ts"), (int, float)) and x["expires_ts"] < now)]
            crit = any(str(x.get("severity") or "").lower() == "critical" for x in active)
            notices_kind = "DOWN" if crit else "OK"
    except Exception:
        notices_kind = "UNKNOWN"
    notices = {"kind": notices_kind, "ts": nt}
    try:
        from .. import maint as M
        done = M.complete()
        active = bool(M.MAINTENANCE) and not done
        # The completion record is permanent. as_of is this local read, not the notice time,
        # so a weeks-old completion does not look too old.
        maintenance = {"kind": "DOWN" if active else "OK", "ts": now}
    except Exception:
        maintenance = {"kind": "UNKNOWN", "ts": None}
    w = db.get_blob(HO.WRITE_BLOB)[0] or {}
    wst = w.get("state") if w.get("state") in ("open", "paused", "down", "unknown") else None
    writes = {"swap_offer": {"kind": _kind_write(wst), "ts": w.get("checked_at"), "probe": wst}}
    flag_status, flag_basis = None, None
    try:
        from . import market as MK
        flg = MK._flag()
        if flg:
            flag_status, flag_basis = flg.get("status"), flg.get("basis")
    except Exception:
        pass
    return dict(join_route=join_route, notices=notices, maintenance=maintenance, writes=writes,
                flag_status=flag_status, flag_basis=flag_basis)


def _extra():
    """Existing status fields (market, flag, offers). Local only. Failures leave them out."""
    try:
        from . import market as M
        d = M.swap_status_api()
        if not isinstance(d, dict): return {}
        return d
    except Exception:
        return {}


def build(now=None):
    """Refresh the pin. Called off the request path. Returns the public body."""
    now = time.time() if now is None else now
    facts, extra = _facts(now), _extra()
    body = render(facts, extra, now, now)
    with _lock:
        _pin.update(facts=facts, extra=extra, built_at=now)
    return body


def _refresh():
    try: build()
    except Exception: pass
    finally:
        with _lock: _building[0] = False


def refresh_bg(now=None):
    """One background rebuild when the pin is missing or older than _REFRESH_S."""
    now = time.time() if now is None else now
    with _lock:
        built = _pin["built_at"]
        if _building[0]: return
        if built and now - built < _REFRESH_S: return
        _building[0] = True
    threading.Thread(target=_refresh, daemon=True, name="swapstatus").start()


def serve(now=None):
    """The request body. Does not wait for a rebuild and does not touch the database."""
    now = time.time() if now is None else now
    with _lock:
        facts, extra, built = _pin["facts"], _pin["extra"], _pin["built_at"]
    refresh_bg(now)
    if not facts or built is None: return _unknown(now)
    return render(facts, extra, built, now)


def reset():
    """Tests: drop the pin."""
    with _lock:
        _pin.update(facts=None, extra=None, built_at=None)
        _building[0] = False
