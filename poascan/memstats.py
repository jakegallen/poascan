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
    put("html", lambda: dict(entries=len(HC._c), bytes=HC._bytes[0], max_bytes=HC.MAX_BYTES))
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

def report():
    return dict(ts=int(time.time()), proc=proc(), malloc=malloc(), py_blocks=sys.getallocatedblocks(), gc=list(gc.get_count()),
                gc_collections=[s.get("collections") for s in gc.get_stats()], caches=caches())
