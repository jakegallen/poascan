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
    (re.compile(r"^/network$"), None, 60),   # 1.26.x: all Network tabs (overview + health/charts/…) cache 60s, not just health
    (re.compile(r"^/governance$"), None, 60),
    (re.compile(r"^/(about|api|privacy|agents/census|agents/operators)$"), None, 300),
    (re.compile(r"^/(address|tx)/"), None, 30),
]
WARM = ["/", "/start", "/help", "/about", "/network", "/network?tab=health", "/governance", "/governance?tab=established", "/governance?tab=at-risk", "/chain", "/agents", "/agents/top"]
WARM_EVERY = 20
WARM_GRACE = 75   # 1.26.203: a warmed page's copy is served up to this long past its TTL while the warmer renders the next one
# 1.26.272: query keys that change the rendered page. Anything else (nocache, a tracker) is not a different page.
# / ignores the query entirely (home() does not read it). Dropping those keys is what lets ?nocache= reuse the canonical copy.
# 1.26.280: extended to every cached page route. Each tuple is the exact set of parameters that page varies on; any other
# key (?x=random, a utm_ tag) is dropped so the request reuses the canonical copy instead of forcing a fresh heavy render
# that holds a slot. The sets are the real reads: /network -> views.network(tab, range); /governance -> the union over all
# its tabs (sort/dir/filter/level/page/range plus the intake sub-table's close/state/asort/adir/apage); /agents/top ->
# views4.leaderboard_page(tab) with sort/dir. A page that reads no query is (): the whole query is dropped.
CANON_QS = {"/": (), "/start": (), "/about": (), "/privacy": (), "/agents": (), "/agents/operators": (),
            "/help": ("address", "sort", "dir"),
            "/chain": ("tab", "state", "sort", "dir"), "/chain/txs": ("page", "type", "sort", "dir"),
            "/network": ("tab", "range", "esort", "edir", "isort", "idir"),
            "/agents/top": ("tab", "sort", "dir"), "/agents/census": ("tab",), "/agents/community": ("tab",),
            "/governance": ("tab", "sort", "dir", "filter", "level", "page", "range", "close", "state", "kind", "need",
                            "carry", "csort", "cdir", "asort", "adir", "apage")}
# 1.26.280: valid tab values per path, registered from the owning modules (server.py) so there is no import cycle and no
# drift. An unknown tab renders the default page (the views coerce it), so it is dropped from the key too: ?tab=random1,
# ?tab=random2 ... all collapse onto the default copy instead of each forcing its own render.
_TAB_OK = {}
def register_tabs(path, values):
    _TAB_OK[path] = frozenset(v for v in values if isinstance(v, str))
_warm_set = set()

_c, _bytes, _inflight, _lock = {}, [0], {}, threading.Lock()
_pin = {}   # 1.26.275: warmed visitor pages, outside the 24 MB FIFO, replaced only by a finished render
_close_due = [False]
_wake = threading.Event()
stats = dict(hit=0, miss=0, wait=0, warm=0, evict=0)
# 1.26.x: per-warm-path reliability (poascan's OWN render, not an upstream probe). ok/fail counts, the last successful
# render time (for last_warm_age_s) and its duration in ms. _warm_ms is a bounded recent sample for self-render p50/p95.
warm_paths = {}
_warm_ms = []
_WARM_MS_MAX = 60

def _warm_ok(u, secs):
    ms = round(secs * 1000)
    with _lock:
        wp = warm_paths.setdefault(u, dict(ok=0, fail=0, last_ok=None, last_ms=None))
        wp["ok"] += 1; wp["last_ok"] = time.time(); wp["last_ms"] = ms
        _warm_ms.append(ms)
        if len(_warm_ms) > _WARM_MS_MAX: del _warm_ms[0]

def _warm_fail(u):
    with _lock:
        wp = warm_paths.setdefault(u, dict(ok=0, fail=0, last_ok=None, last_ms=None))
        wp["fail"] += 1

def _pctl(vals, q):
    if not vals: return None
    s = sorted(vals); return s[min(len(s) - 1, int(q * len(s)))]

def _warm_pairs():
    if not _warm_set:
        import urllib.parse
        for u in WARM:
            p, _, q = u.partition("?"); _warm_set.add((p, tuple(sorted((k, tuple(v)) for k, v in urllib.parse.parse_qs(q).items()))))
    return _warm_set

def _qs_tuple(qs):
    return tuple(sorted((k, tuple(v)) for k, v in (qs or {}).items()))

def grace(path, qs):
    """Seconds a warmed page may be served past its TTL (0 for any other page)."""
    return WARM_GRACE if (path, _qs_tuple(qs)) in _warm_pairs() else 0

def canon_qs(path, qs):
    """The query this page actually varies on. A path not in CANON_QS keeps its query unchanged (an API route, a dynamic
    page). For a listed page, only the whitelisted keys survive and an unknown tab value is dropped (it renders the
    default page), so a cache buster reuses the canonical copy."""
    keep = CANON_QS.get(path)
    if keep is None: return qs or {}
    out = {k: qs[k] for k in qs if k in keep} if qs else {}
    ok = _TAB_OK.get(path)
    if ok is not None and "tab" in out and (out["tab"] or [""])[0] not in ok:
        out = {k: v for k, v in out.items() if k != "tab"}
    return out

def is_warm(path, qs):
    """True for a warmed visitor URL (the canonical query only)."""
    return (path, _qs_tuple(qs)) in _warm_pairs()

def _pinned_key(k):
    """Warmed pages live outside the FIFO (any segment, visitor or crawler)."""
    return (k[0], k[1]) in _warm_pairs()

def note_close():
    """A new close landed. The warm loop rebuilds visitor pages and publishes each one when it is finished.
    The copy visitors are reading stays until that publish. Nothing is cleared first."""
    _close_due[0] = True
    _wake.set()

def ttl(path, qs):
    for rx, test, t in TTLS:
        if rx.match(path) and (test is None or test(qs)): return t
    return DEFAULT_TTL

def key(path, qs, segment, crawler):
    return (path, tuple(sorted((k, tuple(v)) for k, v in (qs or {}).items())), segment, bool(crawler))

def _entry(k):
    """Pinned copy first, else the FIFO. Caller holds _lock."""
    return _pin.get(k) or _c.get(k)

def get(k, t, now=None):
    now = now or time.time()
    with _lock:
        e = _entry(k)
        if e and now - e[0] < t: stats["hit"] += 1; return e[1]
    return None

def fresh(k, t, now=None):
    """True when a copy is inside its TTL. Does not count a hit (the serve path counts it)."""
    now = now or time.time()
    with _lock:
        e = _entry(k)
        return bool(e and now - e[0] < t)

def age(k):
    """Seconds since this key was stored, or None when there is no copy. Does not count a hit."""
    with _lock:
        e = _entry(k)
        return None if not e else time.time() - e[0]

def within(k, max_age, now=None):
    """The stored page if it is younger than max_age seconds, else None. Does not count a hit."""
    now = now or time.time()
    with _lock:
        e = _entry(k)
        if not e or now - e[0] >= max_age: return None
        return e[1]

def last(k):
    """The stored page at any age, or None. A warmed page is served from this when its TTL has passed."""
    with _lock:
        e = _entry(k)
        return None if not e else e[1]

def waiting(k):
    """The event a render of k is in flight on, or None. Callers wait without taking a serving slot."""
    with _lock: return _inflight.get(k)

def size(html):
    """Memory a page holds (1.26.234): sys.getsizeof, not len. A page with one character past U+00FF (an arrow, a
    middle dot past Latin-1, an emoji) stores every character in 2 or 4 bytes, so len() counted half or a quarter of
    it and the 24 MB cap held about 48 MB (pages here run 2 bytes a character)."""
    return sys.getsizeof(html)

def put(k, html, now=None):
    """Store a finished render. A warmed page replaces its pin in one assignment, so readers keep the previous copy
    until this one is complete. The pin is not part of the 24 MB FIFO and is never evicted to make room."""
    if not isinstance(html, str): return
    n = size(html)
    if n > MAX_BYTES // 8: return
    ts = now or time.time()
    with _lock:
        old = _c.pop(k, None)
        if old: _bytes[0] -= old[2]
        if _pinned_key(k):
            _pin[k] = (ts, html, n)   # atomic publish: the old pin is dropped only as this tuple is stored
            return
        _pin.pop(k, None)
        _c[k] = (ts, html, n); _bytes[0] += n   # insertion order is age order: a put moves its key to the end
        while _bytes[0] > MAX_BYTES and _c:
            k0 = next(iter(_c)); _bytes[0] -= _c.pop(k0)[2]; stats["evict"] += 1

def _reserve():
    """The cheap-slot semaphore, or None when this process has no reserve (a one-slot test)."""
    try:
        from . import guard as GD
        return GD.cheap
    except Exception:
        return None

def _refresh(k, fn):
    """Render k once in the background. No-op when a render is already in flight or the cheap reserve is full,
    so a visitor is never blocked and a flood of stale reads does not start a thread each."""
    with _lock:
        if k in _inflight: return
        ev = _inflight[k] = threading.Event()
    sem = _reserve(); got = sem is None
    if sem is not None:
        got = sem.acquire(blocking=False)
        if not got:
            with _lock: _inflight.pop(k, None)
            ev.set(); return
    def run():
        try:
            h = fn()
            if isinstance(h, str): put(k, h)
        except Exception as ex:
            log.warning("htmlcache: refresh failed (%s)", type(ex).__name__)
        finally:
            if sem is not None and got:
                try: sem.release()
                except ValueError: pass
            with _lock: _inflight.pop(k, None)
            ev.set()
    threading.Thread(target=run, daemon=True, name="htmlrefresh").start()

def render(k, t, fn, stale=0):
    """The cached page for k, or fn() rendered once (concurrent callers for the same key wait for that render).
    stale: when the fresh copy has expired but a page younger than this many seconds is stored, return it now and
    refresh in the background. The caller does not wait on that render and does not hold a serving slot for it."""
    if not ENABLED: return fn()
    h = get(k, t)
    if h is not None: return h
    if stale or _pinned_key(k):
        old = last(k) if _pinned_key(k) else within(k, stale)   # a pin is served at any age
        if old is not None:
            with _lock: stats["hit"] += 1
            _refresh(k, fn); return old
    with _lock:
        ev = _inflight.get(k); mine = ev is None
        if mine: ev = _inflight[k] = threading.Event()
    if not mine:
        stats["wait"] += 1; ev.wait(10)
        h = get(k, t)
        if h is not None: return h
        old = last(k) if _pinned_key(k) else (within(k, stale) if stale else None)
        if old is not None: return old
        return fn()
    try:
        stats["miss"] += 1; h = fn()
        if isinstance(h, str): put(k, h)
        return h
    finally:
        with _lock: _inflight.pop(k, None)
        ev.set()

def state():
    now = time.time()
    with _lock:
        wp = {u: dict(d, last_warm_age_s=(int(now - d["last_ok"]) if d["last_ok"] else None)) for u, d in warm_paths.items()}
        ms = list(_warm_ms)
        base = dict(stats, entries=len(_c), bytes=_bytes[0], pinned=len(_pin), enabled=ENABLED)
    base["warm_total_paths"] = len(WARM)
    base["warm_paths"] = wp
    # poascan's OWN warm-render latency (distinct from the upstream minepoa probe p50/p95 on /api/status.endpoints)
    base["self_render_ms"] = dict(p50=_pctl(ms, 0.5), p95=_pctl(ms, 0.95), n=len(ms))
    return base

def warm_once(render_path, seg=lambda: None, force=False):
    """One pass over WARM. force (after a close): rebuild every page and publish it when finished. The previous pin
    stays readable for the whole rebuild."""
    import urllib.parse
    n = 0
    for u in WARM:
        p, _, q = u.partition("?"); qs = urllib.parse.parse_qs(q)
        k = key(p, qs, seg(), False); t = ttl(p, qs)
        with _lock: e = _entry(k)
        if not force and e and time.time() - e[0] < t - 5: continue
        try:
            t0 = time.time()
            if force:
                h = render_path(p, qs)   # do not return the old copy and call it done
                if isinstance(h, str): put(k, h)
            else:
                h = render(k, max(1, t - 5), lambda p=p, qs=qs: render_path(p, qs))
            if isinstance(h, str): stats["warm"] += 1; n += 1; _warm_ok(u, time.time() - t0)
            else: _warm_fail(u)
            log.debug("warm %s %.2fs", u, time.time() - t0)
        except Exception as ex: _warm_fail(u); log.warning("htmlcache: warm %s failed (%s)", u, type(ex).__name__)
    return n

def warm_loop(render_path, seg=lambda: None, stop=None):
    """Background: re-render each WARM page when its copy is within WARM_EVERY s of its TTL. render_path(path, qs) -> html
    (it sets up the request context: current segment, not a crawler); seg() is the segment part of the key.
    A close (note_close) wakes this loop and forces one pass that publishes each new render without clearing the pin first."""
    while not (stop and stop.is_set()):
        with _lock:
            force = _close_due[0]
            if force: _close_due[0] = False
        warm_once(render_path, seg, force)
        _wake.wait(WARM_EVERY)
        _wake.clear()
