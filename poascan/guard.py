"""Keeps the process answering. Three parts:

1. A cap on request threads. Total threads are MAX_CONNS. Heavy page and API renders share HEAVY_CAP of the
   MAX_WORKERS serving slots. SERVE_RESERVE slots stay for cheap pages (the homepage and /chain), so close ingest
   and a crawl cannot take every slot. Static files and the health checks take none.
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
MAX_WORKERS = int(os.environ.get("POASCAN_MAX_WORKERS", "16"))   # serving slots in all (heavy renders plus the cheap reserve)
SERVE_RESERVE = int(os.environ.get("POASCAN_SERVE_RESERVE", "4"))   # slots heavy renders and close ingest cannot take
MAX_CONNS = int(os.environ.get("POASCAN_MAX_CONNS", "200"))   # total in-flight request threads (far above MAX_WORKERS so /healthz always gets a thread)
CONN_WAIT = float(os.environ.get("POASCAN_CONN_WAIT", "0.5"))   # a new connection waits this long for a thread slot, then is shed (no deep backlog that holds crawler sockets open)
HEAVY_WAIT = float(os.environ.get("POASCAN_HEAVY_WAIT", "2.0"))   # a gated request waits this long for its slot, then 503s with Retry-After
HANG_FAILS = int(os.environ.get("POASCAN_HANG_FAILS", "4"))
THROTTLED_FAILS = int(os.environ.get("POASCAN_THROTTLED_FAILS", "40"))   # about 10 minutes of throttled failures
# 1.26.284 (S1): a legitimately slow render on the one dedicated core must not read as a hang. While heavy serving slots
# are in use the self-check gets a longer timeout, and a miss counts toward a much larger BUSY_FAILS (about 10 minutes,
# like THROTTLED_FAILS) rather than HANG_FAILS. A genuine hang still exits: stuck renders keep the slots busy, so
# BUSY_FAILS is reached and the process restarts, just with more tolerance under heavy-but-live load.
BUSY_FAILS = int(os.environ.get("POASCAN_BUSY_FAILS", "40"))
HANG_SELF_TIMEOUT = float(os.environ.get("POASCAN_HANG_SELF_TIMEOUT", "10"))   # self-check timeout when no heavy render is in flight
BUSY_SELF_TIMEOUT = float(os.environ.get("POASCAN_BUSY_SELF_TIMEOUT", "25"))   # longer timeout while heavy renders hold slots (a slow render must get time to answer)
STEAL_THROTTLED = float(os.environ.get("POASCAN_STEAL_THROTTLED", "0.3"))   # share of CPU time that was steal over a check interval (1.26.82: 0.5 let 40 to 50% steal intervals count as hangs, so a throttled VM still restarted)
CHECK_EVERY = 15
RSS_TRIM_MB = int(os.environ.get("POASCAN_RSS_TRIM_MB", "600"))
RSS_EXIT_MB = int(os.environ.get("POASCAN_RSS_EXIT_MB", "1500"))   # 2048 MB VM (fly.toml memory 2gb). 1.26.162 set 860 for the 1 GB tier (~950 MB usable). On 2026-11-06 the steady set was ~860 MB after gc and malloc_trim, so that cap restarted a healthy process during a close. 1500 still exits well before the kernel OOM.
TRIM_EVERY = int(os.environ.get("POASCAN_TRIM_EVERY", "60"))   # malloc_trim at most this often, over RSS_TRIM_MB or not
GC_EVERY = int(os.environ.get("POASCAN_GC_EVERY", "900"))     # full gc.collect() at most this often (Python's own GC runs anyway)

# 1.26.271: leave at least one heavy slot when MAX_WORKERS is 1 (the slot tests). A full reserve on a one slot
# process would give heavy work nothing to take.
_reserve = min(max(0, SERVE_RESERVE), max(0, MAX_WORKERS - 1))
HEAVY_CAP = MAX_WORKERS - _reserve   # page/API renders and close ingest
RESERVE_CAP = _reserve               # homepage and /chain only
slots = threading.BoundedSemaphore(HEAVY_CAP)   # heavy-work cap; health and static never take it, close ingest takes only this
cheap = threading.BoundedSemaphore(RESERVE_CAP) if RESERVE_CAP else None   # None when the process is too small for a reserve (tests)
# 1.26.275: address, tx and epoch-record/rewards reads still take a heavy slot, but only this many at once.
# A request past the cap sheds at once instead of sitting on a worker through a long minepoa wait.
SCRAPE_MAX = int(os.environ.get("POASCAN_SCRAPE_MAX", "3"))
SCRAPE_WAIT = float(os.environ.get("POASCAN_SCRAPE_WAIT", "0.05"))
scrape = threading.BoundedSemaphore(max(1, SCRAPE_MAX))
conns = threading.BoundedSemaphore(MAX_CONNS)   # 1.26.254: total-thread cap; kept well above MAX_WORKERS so the Fly health check never starves behind a flood of slow renders

# 1.26.287: one shared token bucket per throttled User-Agent, across every client IP. poa-dashboard/1.0 spread about
# 9 requests a second over ~150 IPs (Nov 9), so a per-IP limit never fired and it held the one core. The match is the
# exact User-Agent string (minepoa-dashboard/1.0 and everyone else are untouched). Checked in server._gated before any
# slot, cache or upstream work, so an over-limit request costs a dict read and a small 429. Comma-separated list.
UA_THROTTLE = tuple(x.strip() for x in os.environ.get("POASCAN_UA_THROTTLE", "poa-dashboard/1.0").split(",") if x.strip())
UA_THROTTLE_RATE = float(os.environ.get("POASCAN_UA_THROTTLE_RATE", "1"))    # tokens per second, shared by all of that UA's IPs
UA_THROTTLE_BURST = float(os.environ.get("POASCAN_UA_THROTTLE_BURST", "5"))  # bucket size
_ua_lock = threading.Lock()
_ua_bucket = {}   # ua -> (tokens, monotonic time of last update)
ua_stats = {"throttled": 0, "allowed": 0}

def ua_throttle(ua, now=None):
    """0 when this request may go on, else the Retry-After seconds. Only an exact UA_THROTTLE match spends a token."""
    if not ua or ua not in UA_THROTTLE: return 0
    now = time.monotonic() if now is None else now
    rate = max(UA_THROTTLE_RATE, 0.001); burst = max(UA_THROTTLE_BURST, 1.0)
    with _ua_lock:
        tok, last = _ua_bucket.get(ua, (burst, now))
        tok = min(burst, tok + max(0.0, now - last) * rate)
        if tok >= 1.0:
            _ua_bucket[ua] = (tok - 1.0, now); ua_stats["allowed"] += 1; return 0
        _ua_bucket[ua] = (tok, now); ua_stats["throttled"] += 1
    return max(1, int((1.0 - tok) / rate + 0.999))

def close_acquire():
    """One heavy slot for close ingest. Never a reserved cheap slot: False when every heavy slot is already held,
    and the reserve stays free for the homepage and /chain."""
    return slots.acquire(blocking=False)

def heavy_busy():
    """Heavy serving slots in use right now (0..HEAVY_CAP): the heavy-work semaphore's occupancy, read under its own
    condition lock. On any error (a different threading internal) it returns 0, which is the safe default: no exemption,
    so the watchdog stays strict rather than ever going soft and never restarting."""
    try:
        with slots._cond:
            return max(0, HEAVY_CAP - slots._value)
    except Exception:
        return 0
state = {"last_ok": time.time(), "fails": 0, "throttled_fails": 0, "busy_fails": 0, "steal": None, "rss_mb": None, "trims": 0, "gcs": 0, "rss_over": 0}

def telemetry():
    """Cheap read of the memory guard and self-check counters for diagnostics (poascan's own, not an upstream probe).
    trims/gcs: malloc_trim and full gc.collect() run counts. rss_mb: last resident size. rss_over: times RSS was seen
    above RSS_EXIT_MB (a second in a row triggers a clean exit, which the restart counter then records on the next boot).
    self_check_fails/throttled_fails: consecutive /healthz self-check misses (throttled ones do not force a restart).
    ua_throttle: the shared per-User-Agent API throttle (1.26.287); throttled counts its 429s since boot."""
    s = state
    return dict(trims=s["trims"], gcs=s["gcs"], rss_mb=s["rss_mb"], rss_exit_mb=RSS_EXIT_MB, rss_trim_mb=RSS_TRIM_MB,
                rss_over=s.get("rss_over", 0), self_check_fails=s["fails"], throttled_fails=s["throttled_fails"],
                busy_fails=s.get("busy_fails", 0), heavy_busy=heavy_busy(),
                steal=s["steal"], last_ok=s["last_ok"], heavy_cap=HEAVY_CAP, reserve_cap=RESERVE_CAP,
                ua_throttle=dict(agents=list(UA_THROTTLE), rate=UA_THROTTLE_RATE, burst=UA_THROTTLE_BURST,
                                 throttled=ua_stats["throttled"], allowed=ua_stats["allowed"]))

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

def on_check(ok, steal, busy=0):
    """Update the failure counters for one self-check; returns the exit reason, or None to keep running. busy is the
    heavy-slot occupancy at the check: a miss while heavy renders are in flight counts toward BUSY_FAILS (a busy but
    answering box is not a hang), not the small HANG_FAILS, but a sustained run still exits."""
    if ok:
        state["fails"] = 0; state["throttled_fails"] = 0; state["busy_fails"] = 0; state["last_ok"] = time.time(); return None
    if steal is not None and steal >= STEAL_THROTTLED:
        state["throttled_fails"] += 1
        log.warning("guard: /healthz self-check failed while CPU throttled (steal %d%%, %d in a row); not restarting", round(steal * 100), state["throttled_fails"])
        if state["throttled_fails"] >= THROTTLED_FAILS: return f"/healthz did not answer {THROTTLED_FAILS} checks in a row while throttled"
        return None
    if busy > 0:
        state["busy_fails"] += 1
        log.warning("guard: /healthz self-check failed while %d heavy render(s) in flight (%d in a row); not restarting yet", busy, state["busy_fails"])
        if state["busy_fails"] >= BUSY_FAILS: return f"/healthz did not answer {BUSY_FAILS} checks in a row under heavy load"
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
        busy = heavy_busy()   # S1: heavy renders in flight -> a slow answer is not a hang
        try:
            with urllib.request.urlopen(url, timeout=(BUSY_SELF_TIMEOUT if busy > 0 else HANG_SELF_TIMEOUT)) as r: ok = r.status == 200
        except Exception:
            ok = False
        c = cpu_times(); st = steal_share(cpu, c); cpu = c; state["steal"] = st
        if not ok and not (st is not None and st >= STEAL_THROTTLED):
            log.warning("guard: /healthz self-check failed (%.1fs, heavy_busy %d, fails %d/busy_fails %d)", time.time() - t0, busy, state["fails"], state["busy_fails"])
        why = on_check(ok, st, busy)
        if why: _exit(why)
        m = rss_mb(); state["rss_mb"] = m
        now = time.time()
        if due_trim(now, last_trim) or (m and m > RSS_EXIT_MB):
            full = due_gc(now, last_gc, m)
            trim(full); last_trim = now; m = rss_mb(); state["rss_mb"] = m
            if full: last_gc = now
        if m and m > RSS_EXIT_MB:
            over += 1; state["rss_over"] = state.get("rss_over", 0) + 1; log.warning("guard: resident memory %d MB over %d MB (%d)", m, RSS_EXIT_MB, over)
            if over >= 2: _exit(f"resident memory {m} MB stayed over {RSS_EXIT_MB} MB")
        else: over = 0
        time.sleep(max(1, CHECK_EVERY - (time.time() - t0)))

def start(port):
    threading.Thread(target=_watch, args=(port,), daemon=True, name="guard").start()
