"""The shared epoch-rows build never waits for a cold compute slot while it holds its single-flight lock (1.26.427).

Root cause covered: on 1.26.426 a warm render took the epoch-rows single-flight lock, then a cached read inside the build
(minted_before) blocked on _heavy. Both _heavy holders (funnel and answerers on /agents/top and an address page) were
waiting on that same lock, 30 s per epoch_of_ts call, so every heavy request slot, the slow indexer loop and the live
snapshot stalled for hours and the API answered "server busy".

Run: python3 tools/er_flight_test.py (temp db, in-process, no network).
"""
import os, sys, tempfile, threading, time

os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "erflight.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_HEAVY_MAX"] = "2"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from poascan import analytics as A, db

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

db.init()

@A.cached("erflight_inner", ttl=60)
def inner():
    return 7

raw = [{"epoch": 0}]; pp = [{}]
A.epochs_raw = lambda: raw
A._epoch_pend = lambda: pp
A.params_sig = lambda: "sig"
built = []
def fake_build(r, p):
    built.append(inner()); return [{"epoch": 0, "v": built[-1]}]
A._epoch_rows_build = fake_build

# Every cold compute slot and the background slot are held by other threads, as in the stuck dumps.
A._heavy.acquire(); A._heavy.acquire(); A._bg_heavy.acquire()
res = []
def worker(bgmode):
    if bgmode: A.background()
    res.append(A._epoch_rows_shared())
for bgmode, label in ((False, "visitor"), (True, "background warm render")):
    A._er.clear(); A._cache.clear(); res.clear()
    t = threading.Thread(target=worker, args=(bgmode,), daemon=True); t0 = time.time(); t.start(); t.join(5)
    ok(not t.is_alive(), f"{label}: epoch rows build finishes with every _heavy slot held ({time.time() - t0:.2f}s)")
    ok(res and res[0][0]["v"] == 7, f"{label}: rows built from the nested cached read")
    lk = A._er_flight.get(A.S.selected())
    got = lk.acquire(timeout=1) if lk else True
    ok(got, f"{label}: single-flight lock released after the build")
    if lk and got: lk.release()
ok(getattr(A._depth, "n", 0) == 0, "nesting depth restored on the calling thread")
A._heavy.release(); A._heavy.release(); A._bg_heavy.release()

print("FAILED: %d" % len(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
