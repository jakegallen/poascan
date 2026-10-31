"""The swap API build-lock dict (swap/api.py _rc_build) must not grow on unknown offer ids (1.26.249).
Before the fix, _cached did setdefault(path, Lock()) before the build; an unknown id made _build raise, so no _rc
entry was stored and the lock stayed behind forever, one per distinct bogus /api/swaps/<id>. Usage: python3 tools/swapmem_test.py (temp db, no network)."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
tmp = tempfile.mkdtemp()
os.environ["POASCAN_DB"] = os.path.join(tmp, "m.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"; os.environ["POASCAN_SWAP_EVIDENCE"] = ""
import fixture; fixture.seed()
import importlib; SW = importlib.import_module("poascan.swap.api")   # the package re-exports api() as a function; import the submodule

fails = []
def check(name, ok): print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

start = len(SW._rc_build)
for i in range(1000):
    try: SW._cached("/api/swaps/nosuchoffer%d" % i)   # unknown id: _build raises, the fix must pop the lock
    except Exception: pass
check("1000 unknown swap ids leave _rc_build flat (%d -> %d)" % (start, len(SW._rc_build)), len(SW._rc_build) == start)

for _ in range(100):
    try: SW._cached("/api/swaps/doesnotexist")   # the same unknown id repeated must not accumulate either
    except Exception: pass
check("a repeated unknown swap id does not accumulate", len(SW._rc_build) == start)

print(("\n%d failed" % len(fails)) if fails else "\nall passed")
sys.exit(1 if fails else 0)
