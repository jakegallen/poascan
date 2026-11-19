"""Stored API samples (POASCAN data ask 6b): one example response per endpoint for the API page's Run pane,
so the page can show a real shape without the reader's browser ever hitting the live API. Built in-process
by self-calling a CURATED allowlist of cheap, cache-backed GET endpoints (the same cached copies POASCAN
already polls, no synchronous upstream fetch), refreshed at most hourly and bounded in size. Served at
/api/v1/reference/samples. On a build error for one endpoint its sample is an {error} note, never a raise."""
import json, threading, time

TTL = 3600                 # rebuild at most once an hour (lazy, on access)
MAX_JSON = 4000            # cap each stored sample's serialized size
LIST_KEEP = 3              # keep at most this many items from any list in a sample

# Cheap, parameterless, cache-backed endpoints (read copies POASCAN already holds; no heavy upstream call).
# display is the public /api/v1 path; call is what the in-process dispatcher (server.api) expects.
SAMPLES = [
    ("/api/v1/health", "/api/health", {}),
    ("/api/v1/status", "/api/status", {}),
    ("/api/v1/summary?lite=1", "/api/summary", {"lite": ["1"]}),
    ("/api/v1/params", "/api/params", {}),
    ("/api/v1/swaps/status", "/api/swaps/status", {}),
    ("/api/v1/telemetry", "/api/telemetry", {}),
]

_lock = threading.Lock()
_cache = {"ts": 0, "data": None}

def _shrink(v, depth=0):
    """Bound a sample: trim long lists and stop recursing deep, so the stored copy stays small and real JSON."""
    if isinstance(v, list):
        out = [_shrink(x, depth + 1) for x in v[:LIST_KEEP]]
        if len(v) > LIST_KEEP: out.append(f"...{len(v) - LIST_KEEP} more")
        return out
    if isinstance(v, dict):
        if depth >= 4: return {"...": "truncated"}
        return {k: _shrink(x, depth + 1) for k, x in v.items()}
    return v

def _one(display, call, qs):
    try:
        from . import server as _SV
        body, is_list = _SV.api(call, qs)
        sample = _shrink(body)
        s = json.dumps(sample)
        if len(s) > MAX_JSON:
            top = list(body.keys())[:20] if isinstance(body, dict) else None
            return dict(endpoint=display, status=200,
                        note="sample too large to store; call the endpoint for the full body",
                        top_level_keys=top, is_list=is_list)
        return dict(endpoint=display, status=200, is_list=is_list, sample=sample)
    except Exception as e:
        return dict(endpoint=display, status="error", error=type(e).__name__)

def _build():
    rows = [_one(d, c, q) for d, c, q in SAMPLES]
    return dict(generated_ts=int(time.time()), ttl=TTL, count=len(rows), samples=rows,
                note="Example responses from POAScan's own cheap cached endpoints, refreshed hourly in-process. "
                     "For the live value, call the endpoint. Large bodies are trimmed; lists are shortened.")

def samples():
    now = time.time()
    with _lock:
        if _cache["data"] is None or now - _cache["ts"] >= TTL:
            _cache["data"] = _build(); _cache["ts"] = now
        return _cache["data"]
