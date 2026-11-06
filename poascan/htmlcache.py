"""Rendered page cache (1.26.202). Every HTML view used to render from scratch: a cold Network Health took 1.1 to 1.9 s
and bots asked for 70k pages a day. A rendered page is reused for its path's TTL (data on the page moves at most that
late; live parts update over the WebSocket as before), one render per key at a time (others wait for it), and the
heaviest pages are re-rendered in the background before they expire, so no visitor waits on them. Memory only, bounded
by MAX_BYTES. Key: path, query, chain segment and whether the viewer is a crawler (a crawler's render never waits on an
upstream read, so it is kept apart). Off when the indexer is off (tests seed data and read pages in the same second),
unless POASCAN_HTML_CACHE=1."""
import os, re, sys, threading, time, logging

log = logging.getLogger("poascan.htmlcache")
ENABLED = os.environ.get("POASCAN_HTML_CACHE", "0" if os.environ.get("POASCAN_INDEXER") == "0" else "1") == "1"
MAX_BYTES = int(os.environ.get("POASCAN_HTML_CACHE_BYTES", str(24 * 1024 * 1024)))
DEFAULT_TTL = 15
# (path regex, query test or None, ttl s). First match wins.
TTLS = [
    (re.compile(r"^/network$"), lambda qs: (qs.get("tab") or [""])[0] == "health", 60),
    (re.compile(r"^/governance$"), None, 60),
    (re.compile(r"^/(about|api|privacy|agents/census|agents/operators)$"), None, 300),
    (re.compile(r"^/(address|tx)/"), None, 30),
]
WARM = ["/network?tab=health", "/governance", "/governance?tab=established", "/governance?tab=at-risk", "/chain", "/agents", "/agents/top"]
WARM_EVERY = 20
WARM_GRACE = 75   # 1.26.203: a warmed page's copy is served up to this long past its TTL while the warmer renders the next one
_warm_set = set()

_c, _bytes, _inflight, _lock = {}, [0], {}, threading.Lock()
stats = dict(hit=0, miss=0, wait=0, warm=0, evict=0)

def grace(path, qs):
    """Seconds a warmed page may be served past its TTL (0 for any other page)."""
    if not _warm_set:
        import urllib.parse
        for u in WARM:
            p, _, q = u.partition("?"); _warm_set.add((p, tuple(sorted((k, tuple(v)) for k, v in urllib.parse.parse_qs(q).items()))))
    return WARM_GRACE if (path, tuple(sorted((k, tuple(v)) for k, v in (qs or {}).items()))) in _warm_set else 0

def ttl(path, qs):
    for rx, test, t in TTLS:
        if rx.match(path) and (test is None or test(qs)): return t
    return DEFAULT_TTL

def key(path, qs, segment, crawler):
    return (path, tuple(sorted((k, tuple(v)) for k, v in (qs or {}).items())), segment, bool(crawler))

def get(k, t, now=None):
    now = now or time.time()
    with _lock:
        e = _c.get(k)
        if e and now - e[0] < t: stats["hit"] += 1; return e[1]
    return None

def size(html):
    """Memory a page holds (1.26.234): sys.getsizeof, not len. A page with one character past U+00FF (an arrow, a
    middle dot past Latin-1, an emoji) stores every character in 2 or 4 bytes, so len() counted half or a quarter of
    it and the 24 MB cap held about 48 MB (pages here run 2 bytes a character)."""
    return sys.getsizeof(html)

def put(k, html, now=None):
    if not isinstance(html, str): return
    n = size(html)
    if n > MAX_BYTES // 8: return
    with _lock:
        old = _c.pop(k, None)
        if old: _bytes[0] -= old[2]
        _c[k] = (now or time.time(), html, n); _bytes[0] += n   # insertion order is age order: a put moves its key to the end
        while _bytes[0] > MAX_BYTES and _c:
            k0 = next(iter(_c)); _bytes[0] -= _c.pop(k0)[2]; stats["evict"] += 1   # the oldest copy (was an O(n) min scan per eviction)

def render(k, t, fn):
    """The cached page for k, or fn() rendered once (concurrent callers for the same key wait for that render)."""
    if not ENABLED: return fn()
    h = get(k, t)
    if h is not None: return h
    with _lock:
        ev = _inflight.get(k); mine = ev is None
        if mine: ev = _inflight[k] = threading.Event()
    if not mine:
        stats["wait"] += 1; ev.wait(10)
        h = get(k, t)
        if h is not None: return h
        return fn()
    try:
        stats["miss"] += 1; h = fn()
        if isinstance(h, str): put(k, h)
        return h
    finally:
        with _lock: _inflight.pop(k, None)
        ev.set()

def state():
    with _lock: return dict(stats, entries=len(_c), bytes=_bytes[0], enabled=ENABLED)

def warm_loop(render_path, seg=lambda: None, stop=None):
    """Background: re-render each WARM page when its copy is within WARM_EVERY s of its TTL. render_path(path, qs) -> html
    (it sets up the request context: current segment, not a crawler); seg() is the segment part of the key."""
    import urllib.parse
    while not (stop and stop.is_set()):
        for u in WARM:
            p, _, q = u.partition("?"); qs = urllib.parse.parse_qs(q)
            k = key(p, qs, seg(), False); t = ttl(p, qs)
            with _lock: e = _c.get(k)
            if e and time.time() - e[0] < t - 5: continue
            try:
                t0 = time.time(); h = render_path(p, qs)
                if isinstance(h, str): put(k, h); stats["warm"] += 1
                log.debug("warm %s %.2fs", u, time.time() - t0)
            except Exception as ex: log.warning("htmlcache: warm %s failed (%s)", u, type(ex).__name__)
        time.sleep(WARM_EVERY)
