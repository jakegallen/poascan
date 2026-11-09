"""Health check never starves under load (1.26.254): /healthz and /api/health are served WITHOUT taking a
heavy-work slot (GD.slots, MAX_WORKERS), so Fly's health check and the loopback watchdog answer immediately even
when every worker slot is held by slow page renders under a crawler flood. A gated (non-health) request that cannot
get a slot within HEAVY_WAIT is shed with a 503 + Retry-After instead of queueing. Total threads are bounded by a
separate, larger cap (GD.conns, MAX_CONNS) so a health request always gets a thread.
Run: python3 tools/healthslot_test.py (in-process, no network; a temp db for the module import)."""
import os, tempfile, time, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

# env must be set before guard/server import: guard reads MAX_WORKERS / HEAVY_WAIT at import time
tmp = tempfile.mkdtemp()
os.environ["POASCAN_DB"] = os.path.join(tmp, "hs.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_MAX_WORKERS"] = "1"     # one heavy slot: easy to exhaust
os.environ["POASCAN_HEAVY_WAIT"] = "0.3"    # a gated request waits this long for a slot, then 503s
os.environ["POA_BASE"] = "http://127.0.0.1:9"

from poascan import guard as GD
import poascan.server as S

fails = []
def ok(c, m): print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

# ---- a stub handler: exercise _gated / _is_health without a socket (skip BaseHTTPRequestHandler.__init__) ----
class Stub(S.H):
    def __init__(self, path): self.path = path; self.sent = []; self.command = "GET"; self.headers = {}   # 1.26.280: _gated now runs the per-IP page limiter before the slot; no Fly-Client-IP header means it never limits (fail-open)
    def send(self, code, *a, **k): self.sent.append(code); return code

# ---------------------------------------------------------------- 1. configuration
ok(GD.MAX_WORKERS == 1, f"MAX_WORKERS honoured from env ({GD.MAX_WORKERS})")
ok(GD.MAX_CONNS >= GD.MAX_WORKERS and GD.MAX_CONNS >= 50, f"MAX_CONNS is well above the heavy cap ({GD.MAX_CONNS})")
ok(hasattr(GD, "conns"), "a separate total-thread semaphore (GD.conns) exists")

# ---------------------------------------------------------------- 2. path classification
for p in ("/healthz", "/healthz/", "/api/health", "/api/health/", "/api/v1/health", "/api/v1/health/"):
    ok(Stub(p)._is_health() is True, f"{p} is a health path (slot-exempt)")
ok(Stub("/api/v1/health")._is_health() == Stub("/api/health")._is_health() is True, "/api/v1/health is classified the same as /api/health")
for p in ("/", "/address/poa1" + "A" * 40, "/tx/" + "ab" * 32, "/api/v1/status"):
    ok(Stub(p)._is_health() is False, f"{p} is a gated path (takes a worker slot)")
ok(Stub("/api/summary")._is_health() is False and Stub("/api/summary")._is_snapshot() is True, "/api/summary is the live snapshot, not the health check")

# ---------------------------------------------------------------- 3. with the only heavy slot held, health still passes, heavy sheds
got = GD.slots.acquire(timeout=1); ok(got, "test acquired the single heavy slot (simulating a slow render in flight)")

for p in ("/healthz", "/api/health", "/api/v1/health"):
    called = []
    t0 = time.time()
    r = Stub(p)._gated(lambda: (called.append(1), "SERVED")[1])
    dt = time.time() - t0
    ok(called == [1] and r == "SERVED", f"{p} served while every heavy slot is held (fn ran)")
    ok(dt < 0.2, f"{p} answered immediately, did not wait for a slot ({dt*1000:.0f} ms)")

# a gated path cannot get the held slot -> 503 after ~HEAVY_WAIT, fn never runs
heavy = Stub("/address/poa1" + "B" * 40); ran = []
t0 = time.time()
heavy._gated(lambda: (ran.append(1), "RENDER")[1])
dt = time.time() - t0
ok(heavy.sent == [503] and not ran, f"a gated request sheds with 503 when no slot is free (sent={heavy.sent}, fn ran={bool(ran)})")
ok(0.25 <= dt < 1.5, f"it shed after about HEAVY_WAIT, not instantly and not forever ({dt*1000:.0f} ms)")

GD.slots.release()

# ---------------------------------------------------------------- 4. once a slot frees, a gated path runs again and releases cleanly
ran = []
ok(Stub("/tx/" + "cd" * 32)._gated(lambda: (ran.append(1), "OK")[1]) == "OK" and ran == [1], "a gated request runs once a slot is free")
free = [GD.slots.acquire(blocking=False) for _ in range(GD.MAX_WORKERS)]
ok(all(free), "the heavy slot was released after the gated request (semaphore back to full)")
for _ in free: GD.slots.release()

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall ok")
sys.exit(1 if fails else 0)
