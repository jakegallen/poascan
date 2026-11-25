"""1.26.428: the slow indexer loop survives anything a job or its bookkeeping raises. A loop that died silently froze epochs,
release and params for hours while /healthz stayed green (Nov 25). Checks: a job that raises, a job that raises SystemExit,
a db.put_blob that raises, and a can_fetch that raises each leave the loop running the other jobs; supervised() restarts a
loop that run_forever lets escape; /api/health lists the loops with their last pass age. Temp database, no network.
Usage: python3 tools/indexer_loop_test.py"""
import os, sys, tempfile, threading, time, types
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "l.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from poascan import db, indexer as I

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
real_time = I.time
I.time = types.SimpleNamespace(time=real_time.time, sleep=lambda s: real_time.sleep(0.001))   # no 2 s and 5 s spacing in the test

def run(jobs, secs=0.6, target=None, name="loop-t"):
    stop = threading.Event()
    th = threading.Thread(target=target or I.run_forever, kwargs=dict(stop=stop, jobs=jobs), daemon=True, name=name); th.start()
    real_time.sleep(secs); alive = th.is_alive(); stop.set(); th.join(5)
    return alive

ran = {"good": 0, "raise": 0, "exit": 0}
def good(): ran["good"] += 1
def bad(): ran["raise"] += 1; raise RuntimeError("boom")
def bye(): ran["exit"] += 1; raise SystemExit(1)
# every=0 so each pass runs every job again
alive = run([("bad", bad, 0, None), ("bye", bye, 0, None), ("good", good, 0, None)])
check("a raising job and a SystemExit job do not stop the loop", alive and ran["good"] > 3 and ran["raise"] > 3 and ran["exit"] > 3)

ran["good"] = 0
orig_put = db.put_blob
def flaky_put(k, v, *a, **kw):
    if k == "job:good": raise sqlite_err()
    return orig_put(k, v, *a, **kw)
def sqlite_err():
    import sqlite3; return sqlite3.OperationalError("database is locked")
db.put_blob = flaky_put
alive = run([("good", good, 0, None), ("other", good, 0, None)], name="loop-put")
db.put_blob = orig_put
check("db.put_blob raising does not stop the loop", alive and ran["good"] > 6)
check("the loop counts that error", [x for x in I.loop_state() if x["name"] == "loop-put"][0]["errors"] > 0)

ran["good"] = 0
orig_cf = I.can_fetch
def bad_cf(ep): raise RuntimeError("backoff table")
I.can_fetch = bad_cf
alive = run([("fetchy", good, 0, "/api/x"), ("good", good, 0, None)], name="loop-cf")
I.can_fetch = orig_cf
check("can_fetch raising does not stop the loop, other jobs still run", alive and ran["good"] > 3)

# supervised: restart a loop that run_forever lets escape
calls = []
orig_rf = I.run_forever
def dying(**kw):
    calls.append(1)
    if len(calls) < 3: raise SystemExit(2)
    return orig_rf(**kw)
I.run_forever = dying
ran["good"] = 0
alive = run([("good", good, 0, None)], secs=0.5, target=I.supervised, name="loop-sup")
I.run_forever = orig_rf
check("supervised restarts run_forever after it ends with SystemExit", len(calls) >= 3 and ran["good"] > 0)
check("restarts are counted", [x for x in I.loop_state() if x["name"] == "loop-sup"][0]["restarts"] == 2)
check("last pass age is reported", all(x["last_pass_s"] is not None for x in I.loop_state() if x["name"] in ("loop-t", "loop-put", "loop-cf")))

I.time = real_time
from poascan import server as S
import inspect
src = inspect.getsource(S)
check("/api/health carries loops", 'loops=_IX.loop_state()' in src)
check("no em or en dash in the new text", not any(d in open(os.path.join(HERE, "..", "poascan", "indexer.py")).read().split("LOOPS = {}")[1].split("def _purge_keys")[0] for d in ("\u2014", "\u2013")))
print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
