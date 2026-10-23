"""POASwap's shared swap flag, read only: GET https://poaswap.io/api/v1/swaps/status, the single source for whether swaps
are live, paused or coming soon. POAScan never writes to POASwap and never feeds its own data into that flag.

One background thread (started with the indexer) reads it at most once every POLL_S, with If-None-Match, and a short
timeout so no page ever waits on it. The last good copy (a 200 or a 304) is kept for KEEP_S; after that the status is
unknown. Until POASwap has answered once since boot, the fallback is swap/config.SWAPS_LIVE (the host passes it in).
Only plain GETs with User-Agent, Accept and If-None-Match: no visitor data, nothing written, no other poaswap.io route."""
import json, os, re, threading, time, urllib.error, urllib.request

URL = os.environ.get("SWAP_FLAG_URL", "https://poaswap.io/api/v1/swaps/status").strip()   # empty: never read (fallback only)
POLL_S, KEEP_S, TIMEOUT = 60, 900, 3
STATUSES = ("live", "paused", "coming_soon")
DEFAULT_URL = "https://poaswap.io/start"
UA = "POAScan/1 (+https://poascan.io/about)"

# POAScan's own terse labels, used when POASwap sends no message or one that isn't clean.
LABEL = {"live": "Swaps are live on minepoa.com.", "paused": "Swaps are paused. Check back soon.",
         "coming_soon": "Swaps are coming soon.", "unknown": "Swap status is unknown right now."}

_lock = threading.Lock()
_state = dict(body=None, etag=None, ok_ts=None, attempt_ts=None, err=None)   # ok_ts: last 200 or 304

def clean(msg):
    """A POASwap message is shown only when it is short, plain text, with no em or en dash."""
    if not isinstance(msg, str): return None
    m = msg.strip()
    if not m or len(m) > 160 or re.search(r"[\u2013\u2014<>\x00-\x1f\x7f]", m): return None
    return m

def _https(u):
    return u if isinstance(u, str) and re.fullmatch(r"https://[A-Za-z0-9.-]+(/[^\s\"'<>]*)?", u) else None

def _valid(d):
    return isinstance(d, dict) and d.get("status") in STATUSES and isinstance(d.get("available"), bool)

def refresh(now=None, opener=None):
    """One read (the poll thread calls this; tests call it directly). Never raises."""
    if not URL: return "off"
    now = time.time() if now is None else now
    with _lock: etag = _state["etag"]; _state["attempt_ts"] = now
    h = {"User-Agent": UA, "Accept": "application/json"}
    if etag: h["If-None-Match"] = etag
    try:
        r = (opener or urllib.request.urlopen)(urllib.request.Request(URL, headers=h), timeout=TIMEOUT)
        with r:
            d = json.loads(r.read(200_000)); tag = r.headers.get("ETag")
        if not _valid(d): raise ValueError("unexpected shape")
        with _lock: _state.update(body=d, etag=tag, ok_ts=now, err=None)
        return "ok"
    except urllib.error.HTTPError as e:
        if e.code == 304 and _state["body"] is not None:
            with _lock: _state.update(ok_ts=now, err=None)
            return "not_modified"
        err = f"HTTP {e.code}"
    except (ValueError, json.JSONDecodeError): err = "bad JSON"
    except Exception as e: err = type(e).__name__   # timeout, DNS, refused
    with _lock: _state["err"] = err
    return err

def _loop():
    while True:
        refresh(); time.sleep(POLL_S)

def start():
    if URL: threading.Thread(target=_loop, daemon=True, name="swapflag").start()

def version():
    """Moves on every read of POASwap's status (a new copy, a 304 or an error), so cached swap responses rebuild."""
    with _lock: return (_state["ok_ts"], _state["err"], id(_state["body"]))

def _iso(t): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None

def current(now=None, live=True):
    """The flag as POAScan shows it. status: live, paused, coming_soon or unknown. basis: poaswap (a copy at most KEEP_S
    old), expired (older: status unknown) or fallback (POASwap not reached since boot: live is swap/config.SWAPS_LIVE)."""
    now = time.time() if now is None else now
    with _lock: s = dict(_state)
    d, ok = s["body"], s["ok_ts"]
    base = dict(source="poaswap", fetched_at=_iso(ok), age_s=int(now - ok) if ok else None, last_error=s["err"])
    if d is None:
        st = "live" if live else "coming_soon"
        return dict(base, status=st, available=None, swaps_live=bool(live), reason="poaswap_not_reached", message=LABEL[st],
                    open_offer_count=None, updated_at=None, url=DEFAULT_URL, version=None, basis="fallback")
    url = _https(d.get("url")) or DEFAULT_URL
    if now - ok > KEEP_S:
        return dict(base, status="unknown", available=False, swaps_live=None, reason="poaswap_stale", message=LABEL["unknown"],
                    open_offer_count=None, updated_at=d.get("updated_at"), url=url, version=d.get("version"), basis="expired")
    st = d["status"]; n = d.get("open_offer_count")
    return dict(base, status=st, available=d["available"], swaps_live=d.get("swaps_live") if isinstance(d.get("swaps_live"), bool) else None,
                reason=d.get("reason") if isinstance(d.get("reason"), str) else None, message=clean(d.get("message")) or LABEL[st],
                open_offer_count=n if isinstance(n, int) and not isinstance(n, bool) else None, updated_at=d.get("updated_at"),
                url=url, version=d.get("version"), basis="poaswap")

def _reset():
    """Tests only: back to never reached."""
    with _lock: _state.update(body=None, etag=None, ok_ts=None, attempt_ts=None, err=None)
