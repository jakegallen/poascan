"""Process memory, for the private /ops/memory JSON (1.26.234). Cheap reads only: /proc/self, glibc mallinfo2, Python's
block count and gc counters, and the entry counts and byte tallies the caches already keep. No deep walk of any object,
no upstream call, nothing written."""
import ctypes, gc, sys, time

class _MI2(ctypes.Structure):
    _fields_ = [(n, ctypes.c_size_t) for n in ("arena", "ordblks", "smblks", "hblks", "hblkhd", "usmblks", "fsmblks", "uordblks", "fordblks", "keepcost")]
try:
    _libc = ctypes.CDLL("libc.so.6"); _libc.mallinfo2.restype = _MI2
except Exception:
    _libc = None

MB = 1 << 20
def proc():
    out = {}
    try:
        for l in open("/proc/self/status"):
            k = l.split(":")[0]
            if k in ("VmRSS", "VmHWM", "RssAnon", "VmData"): out[k] = int(l.split()[1]) // 1024
            elif k == "Threads": out[k] = int(l.split()[1])
    except Exception: pass
    return out

def malloc():
    """glibc heap in MB: arena (heap from brk/sbrk and arena maps), in_use, free (held inside the heap, not returned), mmap (large blocks mapped apart)."""
    if not _libc: return None
    try: m = _libc.mallinfo2()
    except Exception: return None
    return dict(arena=m.arena // MB, in_use=m.uordblks // MB, free=m.fordblks // MB, mmap=m.hblkhd // MB, mmap_blocks=m.hblks)

def caches():
    """Entry counts (and bytes where the cache tallies them) of the caches that fill with traffic."""
    out = {}
    def put(name, fn):
        try: out[name] = fn()
        except Exception: out[name] = None
    from . import htmlcache as HC, analytics as A, views as V, og as OG, indexer as I
    put("html", lambda: dict(entries=len(HC._c), bytes=HC._bytes[0], pinned=len(HC._pin), max_bytes=HC.MAX_BYTES))
    put("analytics", lambda: dict(entries=len(A._cache), max=A.CACHE_MAX))
    put("address", lambda: dict(entries=len(V._addr_cache), max=V.ADDR_MAX))
    put("og", lambda: dict(entries=len(OG._CACHE), bytes=sum(len(v[1]) for v in list(OG._CACHE.values())), max=OG._MAX))
    put("ondemand_recent", lambda: len(I._recent))
    put("ondemand_neg", lambda: len(I._neg))
    put("etags", lambda: len(I._etags) + len(I._lastmod))
    try:
        from . import fastindex as FX
        put("fast_addr", lambda: len(FX._addr_cache))
    except Exception: pass
    try:
        from . import timeline as TL
        put("timeline", lambda: len(TL._memo))
    except Exception: pass
    return out

def _approx_bytes(o, cap=6000):
    """Best-effort byte size of one object graph, visiting at most `cap` objects. Bounded and low memory: a stack walk
    with an id set, no recursion, stops at the cap. Undercounts a graph larger than the cap (good enough to rank)."""
    seen = set(); stack = [o]; total = 0; n = 0
    while stack and n < cap:
        x = stack.pop(); i = id(x)
        if i in seen: continue
        seen.add(i); n += 1
        try: total += sys.getsizeof(x)
        except Exception: continue
        if isinstance(x, dict):
            for k, v in x.items(): stack.append(k); stack.append(v)
        elif isinstance(x, (list, tuple, set, frozenset)):
            stack.extend(x)
        else:
            d = getattr(x, "__dict__", None)
            if isinstance(d, dict): stack.append(d)
    return total

def _est(c, sample=12, cap_per=6000):
    """Approximate total bytes of a dict or sequence: deep-size up to `sample` entries and scale by len. Cheap and
    bounded (never a full walk of a 400 MB structure), so it is safe on the live request path of the private endpoint."""
    try: n = len(c)
    except Exception: return None
    if not n: return dict(entries=0, approx_kb=0)
    items = list(c.items()) if isinstance(c, dict) else [(None, v) for v in c]
    k = min(sample, len(items)); per = 0
    for key, val in items[:k]:
        per += _approx_bytes(val, cap_per) + (_approx_bytes(key, 64) if key is not None else 0)
    avg = per / k if k else 0
    return dict(entries=n, approx_kb=int(avg * n) // 1024)

def _sum_kinds(d):
    """For a {kind: sub-container} map, sum the per-kind estimates."""
    te = tk = 0
    for v in (d or {}).values():
        if v is None: continue
        r = _est(v)
        if r: te += r["entries"]; tk += r["approx_kb"]
    return dict(entries=te, approx_kb=tk)

def resident():
    """1.26.340: approximate bytes of the largest resident structures, so /ops/memory shows the real split instead of
    estimates. Sampled and bounded (see _est), each guarded so one failure cannot break the report."""
    out = {}
    def put(name, fn):
        try: out[name] = fn()
        except Exception as e: out[name] = {"err": type(e).__name__}
    from . import closestore as CS, analytics as A, history as HI, chartpop as CP, grading as GR
    put("slim_prev", lambda: _sum_kinds(CS._slim_prev))               # parsed slim close records, all kinds (the big one)
    put("close_lru", lambda: _est(CS._lru))
    put("analytics_epochs", lambda: _sum_kinds({k: v.get("v") for k, v in A._epochs.items()}))
    put("analytics_cache", lambda: _est(A._cache))
    put("analytics_cm", lambda: _est(A._cm))
    put("analytics_er", lambda: _est(A._er))
    put("grading_acache", lambda: _est(HI._acache))
    put("grading_gx_keys", lambda: _est(HI._gx.get("keys", {})))
    put("grading_cur", lambda: _est(GR._cur))
    put("chartpop_last", lambda: _est(CP._last))
    return out

def report():
    return dict(ts=int(time.time()), proc=proc(), malloc=malloc(), py_blocks=sys.getallocatedblocks(), gc=list(gc.get_count()),
                gc_collections=[s.get("collections") for s in gc.get_stats()], caches=caches(), resident=resident())
