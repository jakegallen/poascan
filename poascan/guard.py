"""Keeps the process answering. Three parts:

1. A cap on request threads: the server holds at most MAX_WORKERS requests in flight; extra connections wait in
   the listen backlog instead of each getting a thread (and its share of memory).
2. A watchdog thread that requests /healthz over loopback through the same server. If it fails HANG_FAILS times
   in a row the process exits, so Fly restarts it instead of leaving a running-but-hung machine.
3. A memory guard: memory freed by Python is handed back to the OS (malloc_trim) every minute, and if the
   resident size still sits above RSS_EXIT_MB the process exits cleanly rather than waiting for the kernel OOM killer.
"""
import ctypes, gc, logging, os, threading, time, urllib.request

log = logging.getLogger("guard")
MAX_WORKERS = int(os.environ.get("POASCAN_MAX_WORKERS", "16"))
HANG_FAILS = int(os.environ.get("POASCAN_HANG_FAILS", "4"))
CHECK_EVERY = 15
RSS_TRIM_MB = int(os.environ.get("POASCAN_RSS_TRIM_MB", "300"))
RSS_EXIT_MB = int(os.environ.get("POASCAN_RSS_EXIT_MB", "430"))   # the VM has ~460 MB usable

slots = threading.BoundedSemaphore(MAX_WORKERS)
state = {"last_ok": time.time(), "fails": 0, "rss_mb": None, "trims": 0}

try:
    _libc = ctypes.CDLL("libc.so.6"); _libc.malloc_trim.argtypes = [ctypes.c_size_t]
except Exception:
    _libc = None

def trim():
    gc.collect()
    if _libc:
        try: _libc.malloc_trim(0); state["trims"] += 1
        except Exception: pass

def rss_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"): return int(line.split()[1]) // 1024
    except Exception: return None

def _exit(why):
    log.critical("guard: %s; exiting so the machine restarts", why)
    logging.shutdown(); os._exit(70)

def _watch(port):
    url = f"http://127.0.0.1:{port}/healthz"; over = 0; last_trim = 0
    time.sleep(30)
    while True:
        t0 = time.time()
        try:
            with urllib.request.urlopen(url, timeout=10) as r: ok = r.status == 200
        except Exception:
            ok = False
        if ok: state["fails"] = 0; state["last_ok"] = time.time()
        else:
            state["fails"] += 1
            log.warning("guard: /healthz self-check failed (%d in a row, %.1fs)", state["fails"], time.time() - t0)
            if state["fails"] >= HANG_FAILS: _exit(f"/healthz did not answer {HANG_FAILS} checks in a row")
        m = rss_mb(); state["rss_mb"] = m
        if m and (m > RSS_TRIM_MB or time.time() - last_trim > 60):
            trim(); last_trim = time.time(); m = rss_mb(); state["rss_mb"] = m
        if m and m > RSS_EXIT_MB:
            over += 1; log.warning("guard: resident memory %d MB over %d MB (%d)", m, RSS_EXIT_MB, over)
            if over >= 2: _exit(f"resident memory {m} MB stayed over {RSS_EXIT_MB} MB")
        else: over = 0
        time.sleep(max(1, CHECK_EVERY - (time.time() - t0)))

def start(port):
    threading.Thread(target=_watch, args=(port,), daemon=True, name="guard").start()
