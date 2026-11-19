"""In-process API telemetry ring (POASCAN data ask 6a): per-UTC-minute request counts by surface (rest, mcp, csv),
success rate, p50 latency and the top endpoints by count. Keyed by route TEMPLATE only (never a raw path with an
address, hash or id) and with no client identifier. Fixed-size and reset on restart: at most KEEP_MIN minute buckets,
MAX_TMPL templates per bucket, and at most LAT_CAP latency samples per bucket. Recording never raises into a response."""
import threading, time, re

KEEP_MIN = 180          # minute buckets kept (3 h); old buckets pruned
MAX_TMPL = 300          # distinct route templates tracked per minute bucket
LAT_CAP = 256           # latency samples kept per minute bucket (bounded, for p50)

_lock = threading.Lock()
_mins = {}              # minute_ts -> dict(n, ok, surf{}, tmpl{}, lat[])

_POA = re.compile(r"/poa1[a-z0-9]{6,}")   # a poa1 bech32 address in a path is collapsed to a template token
_HEX = re.compile(r"/[0-9a-fA-F]{16,}")
_NUM = re.compile(r"/\d+")

def template(path):
    """Collapse a concrete path to its route template so no address, hash or id is ever stored as a key."""
    p = (path or "").split("?", 1)[0].rstrip("/") or "/"
    p = _POA.sub("/{addr}", p)
    p = _HEX.sub("/{hash}", p)
    p = _NUM.sub("/{n}", p)
    return p[:80]

def _surface(path, ctype):
    p = path or ""
    if p.startswith("/mcp"): return "mcp"
    if not (p.startswith("/api/") or p == "/api"): return None   # only API surfaces are counted
    if "format=csv" in p or p.split("?", 1)[0].endswith(".csv") or "text/csv" in (ctype or ""): return "csv"
    return "rest"

def record(path, code, ms, ctype=""):
    try:
        surf = _surface(path, ctype)
        if surf is None: return
        tmpl = template(path)
        m = (int(time.time()) // 60) * 60
        with _lock:
            b = _mins.get(m)
            if b is None:
                if len(_mins) >= KEEP_MIN:
                    for old in sorted(_mins)[:len(_mins) - KEEP_MIN + 1]: _mins.pop(old, None)
                b = _mins[m] = dict(n=0, ok=0, surf={}, tmpl={}, lat=[])
            b["n"] += 1
            try: ic = int(code)
            except (TypeError, ValueError): ic = 0
            if 200 <= ic < 400: b["ok"] += 1
            b["surf"][surf] = b["surf"].get(surf, 0) + 1
            if tmpl in b["tmpl"] or len(b["tmpl"]) < MAX_TMPL:
                b["tmpl"][tmpl] = b["tmpl"].get(tmpl, 0) + 1
            if ms is not None and len(b["lat"]) < LAT_CAP:
                b["lat"].append(float(ms))
    except Exception:
        pass   # telemetry never breaks a response

def _p(sorted_xs, q):
    if not sorted_xs: return None
    i = min(len(sorted_xs) - 1, int(q * len(sorted_xs)))
    return round(sorted_xs[i], 1)

def snapshot(minutes=60):
    try: minutes = max(1, min(KEEP_MIN, int(minutes)))
    except (ValueError, TypeError): minutes = 60
    now_m = (int(time.time()) // 60) * 60
    cut = now_m - (minutes - 1) * 60
    with _lock:
        buckets = [(m, b) for m, b in _mins.items() if m >= cut]
    per_min, surf, tmpl, lat = [], {}, {}, []
    tot = ok = 0
    for m, b in sorted(buckets):
        per_min.append([m, b["n"]])
        tot += b["n"]; ok += b["ok"]
        for k, v in b["surf"].items(): surf[k] = surf.get(k, 0) + v
        for k, v in b["tmpl"].items(): tmpl[k] = tmpl.get(k, 0) + v
        lat.extend(b["lat"])
    lat.sort()
    top = sorted(tmpl.items(), key=lambda kv: -kv[1])[:5]
    return dict(window_minutes=minutes, requests=tot, success_rate=(round(ok / tot, 4) if tot else None),
                by_surface=surf, per_minute=per_min, p50_ms=_p(lat, 0.50), p95_ms=_p(lat, 0.95),
                top_endpoints=[dict(endpoint=k, count=v) for k, v in top], sampled_requests=len(lat),
                note="in-process, route-template keys only, no client identifiers; resets on restart")
