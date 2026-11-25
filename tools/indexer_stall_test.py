"""1.26.429: the slow indexer loop watchdog. stall_reason is None during the startup grace and while the loop is
passing, and names the stall when the loop has not finished a pass for stall_s, or never finished one after grace.
No network. Usage: python3 tools/indexer_stall_test.py"""
import os, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from poascan import indexer as I

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

I.LOOPS.clear()
now = 2_000_000
check("no loops started: no stall", I.stall_reason(now=now, started=now - 10_000, stall_s=3600, grace_s=3600) is None)

I.LOOPS["indexer"] = {}
check("first pass still inside grace: no stall", I.stall_reason(now=now, started=now - 1800, stall_s=3600, grace_s=3600) is None)
check("first pass never finished after grace: stall", "has not finished a pass" in (I.stall_reason(now=now, started=now - 3600, stall_s=3600, grace_s=3600) or ""))

I.LOOPS["indexer"] = {"pass_ts": now - 100}
check("a recent pass is not a stall, even after grace", I.stall_reason(now=now, started=now - 10_000, stall_s=3600, grace_s=3600) is None)

I.LOOPS["indexer"] = {"pass_ts": now - 3600}
check("a pass 3600 s ago trips the watchdog", "last passed 3600 s ago" in (I.stall_reason(now=now, started=now - 10_000, stall_s=3600, grace_s=3600) or ""))

I.LOOPS.clear()
I.LOOPS["indexer-fast"] = {"pass_ts": now - 10_000}
check("a stalled fast loop does not trip the slow-loop watchdog", I.stall_reason(now=now, started=now - 20_000, stall_s=3600, grace_s=3600) is None)

# default constants
check("defaults are 60 minutes", I.STALL_S == 3600 and I.STALL_GRACE_S == 3600 and I.STALL_LOOPS == ("indexer",))
src = open(os.path.join(HERE, "..", "poascan", "indexer.py"), encoding="utf-8").read() + open(__file__, encoding="utf-8").read()
src += open(os.path.join(HERE, "..", "poascan", "guard.py"), encoding="utf-8").read()
check("no em or en dash in stall text", not any(c in src[src.find("STALL_S"):] for c in ("\u2013", "\u2014")) if False else not any(c in open(os.path.join(HERE, "..", "poascan", "indexer.py")).read().split("STALL_S =")[1].split("def run_forever")[0] + open(os.path.join(HERE, "..", "poascan", "guard.py")).read() for c in ("\u2013", "\u2014")))
check("guard calls stall_reason and writes a stall dump", "stall_reason" in open(os.path.join(HERE, "..", "poascan", "guard.py")).read() and "_stall_dump" in open(os.path.join(HERE, "..", "poascan", "guard.py")).read())

I.LOOPS.clear()
print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
