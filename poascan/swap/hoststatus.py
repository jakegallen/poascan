"""Fast /api/v1/swaps/status (1.26.278).

The request path never reads SQLite and never calls minepoa.com. It returns the pinned
copy, or an UNKNOWN body when none exists yet, and asks one background thread to refresh.
A refresh that hangs does not block the response.

stale_after_s is 2160 seconds (36 minutes). That is the longest gap the swap-offer write
probe allows before a read is too old (hosted.WRITE_STALE_S: 30 min after repeated identical
reads, plus jitter and grace). A probe or a copy older than that is UNKNOWN, not DOWN.
DOWN is only an upstream answer that was a halt or a failure, and only while that answer
is still fresh.

Join clearance (route, notices, maintenance) is a separate block from swap write clearance.
Neither fails open. Mining does not use this endpoint. Swap writes gate on write_ok.
"""
import threading, time

STALE_AFTER_S = 2160
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


def _row(kind, ts, now):
    """One OK / DOWN / UNKNOWN row. Missing or too old is UNKNOWN, never DOWN."""
    age = _age(ts, now)
    if ts is None or age is None or age > STALE_AFTER_S or kind not in ("OK", "DOWN"):
        return dict(state="UNKNOWN", as_of=_iso(ts), age_s=age)
    return dict(state=kind, as_of=_iso(ts), age_s=age)


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
    stale = built_at is None or age is None or age > STALE_AFTER_S
    if not facts:
        join, writes = _blank_join(), _blank_writes()
        write_ok = False
    else:
        jr = _row(facts["join_route"]["kind"], facts["join_route"]["ts"], now)
        jr["name"] = "joining"
        nt = _row(facts["notices"]["kind"], facts["notices"]["ts"], now)
        mt = _row(facts["maintenance"]["kind"], facts["maintenance"]["ts"], now)
        jst, jas, jag = _agg([jr, nt, mt])
        join = dict(state=jst, as_of=jas, age_s=jag, route=jr, notices=nt, maintenance=mt)
        routes = {}
        for name in WRITE_ROUTES:
            src = (facts.get("writes") or {}).get(name) or {"kind": "UNKNOWN", "ts": None}
            routes[name] = _row(src["kind"], src["ts"], now)
            if src.get("probe"): routes[name]["probe"] = src["probe"]
        wst, was, wag = _agg(list(routes.values()))
        writes = dict(state=wst, as_of=was, age_s=wag, routes=routes)
        write_ok = wst == "OK" and not stale
    if stale:
        join, writes = _force_unknown(join), _force_unknown(writes)
        write_ok = False
    flag = (facts or {}).get("flag_status")
    available = bool(write_ok) and flag != "paused"
    if writes["state"] == "DOWN":
        message = "Order placement is failing on the network."
    elif not available:
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
    body["message"] = message if not available else body.get("message")
    body["swaps_writable"] = True if write_ok else (False if writes["state"] == "DOWN" and not stale else None)
    _legacy(body)
    return body


def _legacy(body):
    """Fields POASwap already reads. Same names. A stale or unknown copy is never OK or open.
    active true means stop. join_state open only when join.state is OK and the copy is fresh.
    swap_route.state and writes.swap_offer.state are open only when that write route is OK and fresh."""
    offer = body["swap_writes"]["routes"]["swap_offer"]
    sw = offer["state"]
    if body["stale"] or sw == "UNKNOWN":
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
