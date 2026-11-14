"""1.26.330: close_memo, since_fill and the live hub's first snapshot are single-flight. On a cold boot dozens of /ws and
/api/summary readers reached _epoch_pend at once and each parsed every close's pending list (py-spy: 42 threads), which
pushed RSS over the 1500 MB guard. Temp database.
Usage: python3 tools/singleflight_test.py"""
import os, sys, tempfile, threading, time
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "s.db"); os.environ.setdefault("POASCAN_INDEXER", "0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, live as L
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()

calls = []
@A.close_memo("sf_test")
def slow():
    calls.append(threading.get_ident()); time.sleep(0.3); return {"v": len(calls)}
out = []
ts = [threading.Thread(target=lambda: out.append(slow())) for _ in range(20)]
[t.start() for t in ts]; [t.join(30) for t in ts]
check(f"close_memo: 20 concurrent callers run the body once ({len(calls)})", len(calls) == 1)
check("close_memo: every caller gets the same value", len(out) == 20 and all(o is out[0] for o in out))
check("close_memo: a later call is a memo hit", slow() is out[0] and len(calls) == 1)

# nested and re-entrant use on one thread does not deadlock
@A.close_memo("sf_outer")
def outer(): return slow()["v"] + 1
check("close_memo: nested memo on one thread returns", outer() == 2)

# since_fill: concurrent cold callers rebuild once
n = {"b": 0}; orig = A._since_fill_build
def counted(ts):
    n["b"] += 1; time.sleep(0.2); return orig(ts)
A._since_fill_build = counted; A._sf["ts"] = None
A.epochs_ts = lambda: 12345
ts = [threading.Thread(target=A.since_fill) for _ in range(10)]
[t.start() for t in ts]; [t.join(30) for t in ts]
check(f"since_fill: 10 concurrent cold callers rebuild once ({n['b']})", n["b"] == 1)
A._since_fill_build = orig

# live hub: the first snapshot is built once
built = []
def snap():
    built.append(1); time.sleep(0.3); return {"x": 1}
hub = L.Hub(snap) if hasattr(L, "Hub") else None
if hub is None:
    cls = next(v for v in vars(L).values() if isinstance(v, type) and hasattr(v, "snapshot") and hasattr(v, "_refresh"))
    hub = cls.__new__(cls); hub.__init__(snap)
res = []
ts = [threading.Thread(target=lambda: res.append(hub.snapshot())) for _ in range(15)]
[t.start() for t in ts]; [t.join(30) for t in ts]
check(f"live hub: 15 concurrent first readers build one snapshot ({len(built)})", len(built) == 1)
check("live hub: every first reader gets the snapshot", len(res) == 15 and all(r and '"x":1' in r for r in res))

# 1.26.331: a first build slower than the wait must not make each waiter build its own copy
built2 = []
def slow_snap():
    built2.append(1); time.sleep(1.0); return {"y": 2}
hub2 = L.Hub(slow_snap); hub2.FIRST_WAIT = 0.2
res2 = []
ts = [threading.Thread(target=lambda: res2.append(hub2.snapshot())) for _ in range(12)]
[t.start() for t in ts]; [t.join(30) for t in ts]
check(f"live hub: waiters that time out do not build their own first snapshot ({len(built2)})", len(built2) == 1)
check("live hub: a timed out waiter gets None, the builder gets the snapshot",
      sum(1 for r in res2 if r is None) == 11 and sum(1 for r in res2 if r and '"y":2' in r) == 1)

# 1.26.331: epoch_rows reads params once per walk, not once per close row
import inspect
src = inspect.getsource(A._epoch_rows_build)
check("epoch_rows passes one params read to every row", "ppar = params()" in src and "p=ppar" in src)

# 1.26.332: epoch_rows is built once per change, not once per call (close_times / epoch_of_ts called it per row)
from poascan import agents as G
nb = {"b": 0}; orig_b = A._epoch_rows_build
def counted_b(raw, pp):
    nb["b"] += 1; time.sleep(0.2); return [dict(epoch=1, close_ts=100), dict(epoch=2, close_ts=200)]
A._epoch_rows_build = counted_b; A._er.clear()
ts = [threading.Thread(target=A.epoch_rows) for _ in range(10)]
[t.start() for t in ts]; [t.join(30) for t in ts]
check(f"epoch_rows: 10 concurrent cold callers build once ({nb['b']})", nb["b"] == 1)
eps = [G.epoch_of_ts(t) for t in range(0, 300, 1)]
check(f"epoch_rows: 300 epoch_of_ts calls reuse the build ({nb['b']})", nb["b"] == 1 and eps[150] == 1 and eps[250] == 2)
r = A.epoch_rows(); r[0]["close_ts"] = -1; r.append({})
check("epoch_rows: a caller changing its rows does not change the shared build", A.epoch_rows() == [dict(epoch=1, close_ts=100), dict(epoch=2, close_ts=200)])
db.put_blob("params", {"x": 1})
A.epoch_rows()
check(f"epoch_rows: a params change rebuilds ({nb['b']})", nb["b"] == 2)
A._er[next(iter(A._er))] = (A._er[next(iter(A._er))][0], time.time() - A.ER_TTL - 1) + A._er[next(iter(A._er))][2:]
A.epoch_rows()
check(f"epoch_rows: an entry older than ER_TTL rebuilds ({nb['b']})", nb["b"] == 3)
A._epoch_rows_build = orig_b; A._er.clear()

print("FAILED: " + "; ".join(fails) if fails else "all ok"); sys.exit(1 if fails else 0)
