"""Keeps the process answering. Three parts:

1. A cap on request threads: the server holds at most MAX_WORKERS requests in flight; extra connections wait in
   the listen backlog instead of each getting a thread (and its share of memory).
2. A watchdog thread that requests /healthz over loopback through the same server. If it fails HANG_FAILS times
   in a row the process exits, so Fly restarts it instead of leaving a running-but-hung machine. A failure while the
   VM is CPU throttled (most of the interval was steal time: a shared vCPU out of burst credit) does not count toward
   that limit, only toward the much larger THROTTLED_FAILS: a restart cannot add CPU, it resets the burst balance to
   a few seconds and reruns startup, which deepened the 2026-10-22 outage into a restart loop.
3. A memory guard: memory freed by Python is handed back to the OS (malloc_trim) at most once a minute, a full
   gc.collect() runs at most every GC_EVERY s (or right before a memory exit is decided), and if the resident size still
   sits above RSS_EXIT_MB the process exits cleanly rather than waiting for the kernel OOM killer.
   2026-10-26: trim() used to run gc.collect() on every 15 s check while RSS sat above RSS_TRIM_MB, which it now always
   does (a ~340 MB working set). A full collection of that heap every 15 s was the largest CPU user in the process and
   ran the shared vCPUs out of burst credit (83% steal, 15 to 40 s responses). due_trim() and due_gc() bound both.
"""
import ctypes, gc, logging, os, threading, time, urllib.request

log = logging.getLogger("guard")
MAX_WORKERS = int(os.environ.get("POASCAN_MAX_WORKERS", "16"))
HANG_FAILS = int(os.environ.get("POASCAN_HANG_FAILS", "4"))
THROTTLED_FAILS = int(os.environ.get("POASCAN_THROTTLED_FAILS", "40"))   # about 10 minutes of throttled failures
STEAL_THROTTLED = float(os.environ.get("POASCAN_STEAL_THROTTLED", "0.3"))   # share of CPU time that was steal over a check interval (1.26.82: 0.5 let 40 to 50% steal intervals count as hangs, so a throttled VM still restarted)
CHECK_EVERY = 15
RSS_TRIM_MB = int(os.environ.get("POASCAN_RSS_TRIM_MB", "600"))
RSS_EXIT_MB = int(os.environ.get("POASCAN_RSS_EXIT_MB", "860"))   # 1 GB VM (1.26.162), ~950 MB usable; was 430 on 512 MB
TRIM_EVERY = int(os.environ.get("POASCAN_TRIM_EVERY", "60"))   # malloc_trim at most this often, over RSS_TRIM_MB or not
GC_EVERY = int(os.environ.get("POASCAN_GC_EVERY", "900"))     # full gc.collect() at most this often (Python's own GC runs anyway)

slots = threading.BoundedSemaphore(MAX_WORKERS)
state = {"last_ok": time.time(), "fails": 0, "throttled_fails": 0, "steal": None, "rss_mb": None, "trims": 0, "gcs": 0}

try:
    _libc = ctypes.CDLL("libc.so.6"); _libc.malloc_trim.argtypes = [ctypes.c_size_t]
except Exception:
    _libc = None

def trim(full=False):
    """Hand freed memory back to the OS; full=True runs a full gc.collect() first (costly on a large heap)."""
    if full: gc.collect(); state["gcs"] += 1
    if _libc:
        try: _libc.malloc_trim(0); state["trims"] += 1
        except Exception: pass

def due_trim(now, last_trim):
    """A trim is due once TRIM_EVERY s have passed, never on every check (RSS over RSS_TRIM_MB no longer forces one)."""
    return now - last_trim >= TRIM_EVERY

def due_gc(now, last_gc, rss):
    """A full collection is due every GC_EVERY s, or at once when RSS is over RSS_EXIT_MB (last try before exiting)."""
    return now - last_gc >= GC_EVERY or bool(rss and rss > RSS_EXIT_MB)

def rss_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"): return int(line.split()[1]) // 1024
    except Exception: return None

def cpu_times(path="/proc/stat"):
    """(steal, total) jiffies from the first line of /proc/stat, or None."""
    try:
        with open(path) as f: v = [int(x) for x in f.readline().split()[1:]]
        return (v[7] if len(v) > 7 else 0), sum(v[:8])
    except Exception: return None

def steal_share(a, b):
    """Share of CPU time that was steal between two cpu_times() samples, or None."""
    if not a or not b or b[1] <= a[1]: return None
    return max(0.0, min(1.0, (b[0] - a[0]) / (b[1] - a[1])))

def on_check(ok, steal):
    """Update the failure counters for one self-check; returns the exit reason, or None to keep running."""
    if ok:
        state["fails"] = 0; state["throttled_fails"] = 0; state["last_ok"] = time.time(); return None
    if steal is not None and steal >= STEAL_THROTTLED:
        state["throttled_fails"] += 1
        log.warning("guard: /healthz self-check failed while CPU throttled (steal %d%%, %d in a row); not restarting", round(steal * 100), state["throttled_fails"])
        if state["throttled_fails"] >= THROTTLED_FAILS: return f"/healthz did not answer {THROTTLED_FAILS} checks in a row while throttled"
        return None
    state["fails"] += 1
    if state["fails"] >= HANG_FAILS: return f"/healthz did not answer {HANG_FAILS} checks in a row"
    return None

def _exit(why):
    log.critical("guard: %s; exiting so the machine restarts", why)
    logging.shutdown(); os._exit(70)

def _watch(port):
    url = f"http://127.0.0.1:{port}/healthz"; over = 0; last_trim = 0; last_gc = time.time()
    time.sleep(30)
    cpu = cpu_times()
    while True:
        t0 = time.time()
        try:
            with urllib.request.urlopen(url, timeout=10) as r: ok = r.status == 200
        except Exception:
            ok = False
        c = cpu_times(); st = steal_share(cpu, c); cpu = c; state["steal"] = st
        if not ok and not (st is not None and st >= STEAL_THROTTLED):
            log.warning("guard: /healthz self-check failed (%d in a row, %.1fs)", state["fails"] + 1, time.time() - t0)
        why = on_check(ok, st)
        if why: _exit(why)
        m = rss_mb(); state["rss_mb"] = m
        now = time.time()
        if due_trim(now, last_trim) or (m and m > RSS_EXIT_MB):
            full = due_gc(now, last_gc, m)
            trim(full); last_trim = now; m = rss_mb(); state["rss_mb"] = m
            if full: last_gc = now
        if m and m > RSS_EXIT_MB:
            over += 1; log.warning("guard: resident memory %d MB over %d MB (%d)", m, RSS_EXIT_MB, over)
            if over >= 2: _exit(f"resident memory {m} MB stayed over {RSS_EXIT_MB} MB")
        else: over = 0
        time.sleep(max(1, CHECK_EVERY - (time.time() - t0)))

def start(port):
    threading.Thread(target=_watch, args=(port,), daemon=True, name="guard").start()
