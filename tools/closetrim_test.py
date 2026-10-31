"""After the epochs job stores a close, it drops the big list and trims the heap at once (1.26.250), so the per-close
allocation is returned to the OS rather than lingering until the guard's periodic trim. Usage: python3 tools/closetrim_test.py (temp db, no network)."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
tmp = tempfile.mkdtemp()
os.environ["POASCAN_DB"] = os.path.join(tmp, "c.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
from poascan import db, indexer as I, guard as G
db.init()

fails = []
def check(name, ok): print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

trims = []
I.fetch = lambda *a, **k: [{"epoch": 1, "close_time": 1}]   # a non-empty list so the store branch runs
I.store_epochs = lambda d: True                              # pretend a close was stored
G.trim = lambda *a, **k: trims.append(1)                      # record the trim

r = I.job_epochs(force=True)
check("job_epochs returns the store result", r is True)
check("job_epochs trims the heap once after a store", len(trims) == 1)

# no fetch result (upstream empty) -> no store, no trim
trims.clear()
I.fetch = lambda *a, **k: None
check("no trim when nothing was fetched", I.job_epochs(force=True) is False and len(trims) == 0)

print(("\n%d failed" % len(fails)) if fails else "\nall passed")
sys.exit(1 if fails else 0)
