"""Cold compute slots go to visitors first (1.26.364): background renders hold at most one, and a visitor
refreshing a value it already has never waits for one.

Root cause covered: on boot and after a close two warm renders held both cold compute slots, and every visitor
render waited behind them while its request slot stayed taken, so new address and tx pages shed 503.

Run: python3 tools/bgslot_test.py (temp db, in-process, no network).
"""
import os, sys, tempfile, threading, time

os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "bgslot.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_HEAVY_MAX"] = "2"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from poascan import analytics as A

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

gate = threading.Event(); running = []

@A.cached("bgslot_slow", ttl=60)
def slow(i):
    running.append(i); gate.wait(5); return i

@A.cached("bgslot_fast", ttl=60)
def fast(i):
    return i * 2

def bg(i):
    A.background(); slow(i)

ts = [threading.Thread(target=bg, args=(i,), daemon=True) for i in (1, 2)]
for t in ts: t.start()
time.sleep(0.3)
ok(len(running) == 1, f"two background computes: one runs, one waits (running {running})")
t0 = time.time(); v = fast(7); dt = time.time() - t0
ok(v == 14 and dt < 1, f"a visitor compute gets the free slot at once ({dt:.2f} s)")
gate.set()
for t in ts: t.join(5)
ok(sorted(running) == [1, 2], "both background computes finish")
ok(slow(1) == 1 and slow(2) == 2, "their values are cached")
# a visitor refreshing an expired value while both cold slots are held gets the previous value at once
calls = []
@A.cached("bgslot_stale", ttl=1)
def stale():
    calls.append(1); return len(calls)

ok(stale() == 1, "first compute")
time.sleep(1.1)
A._heavy.acquire(); A._heavy.acquire()
t0 = time.time(); v = stale(); dt = time.time() - t0
ok(v == 1 and dt < 0.5, f"expired value with no free slot: previous value served at once ({dt:.2f} s)")
A._heavy.release(); A._heavy.release()
ok(stale() == 2, "with a slot free the next caller refreshes it")
A._cache[("bgslot_stale", A.S.selected())] = (time.time() - 400, 9)
A._heavy.acquire(); A._heavy.acquire()
done = []
th = threading.Thread(target=lambda: done.append(stale()), daemon=True); th.start(); th.join(0.5)
ok(not done, "a value older than STALE_MAX still waits for a slot")
A._heavy.release(); th.join(3)
ok(done == [3], "and is refreshed once a slot frees")
A._heavy.release()

print("FAIL:" if fails else "all ok", fails if fails else "")
sys.exit(1 if fails else 0)
