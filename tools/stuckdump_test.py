"""1.26.341 (plan v2, B): when the heavy pool stays full for JAM_CHECKS checks in a row the guard writes a thread-stack
dump to the volume so the jam's slot holders are visible. Rate-limited to one per DUMP_EVERY, capped at DUMP_KEEP, and
code stacks only (no request data, headers, IPs or tokens). Usage: python3 tools/stuckdump_test.py"""
import os, sys, tempfile

D = tempfile.mkdtemp()
os.environ["POASCAN_DUMP_DIR"] = D
os.environ["POASCAN_DUMP_EVERY"] = "600"
os.environ["POASCAN_DUMP_KEEP"] = "3"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import guard as GD

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

def dumps():
    return [x for x in os.listdir(D) if x.startswith("stuck-")]

# a dump writes one file with the header and every thread's stack
GD._last_dump[0] = 0.0
GD._stuck_dump(GD.HEAVY_CAP, 3, 42)
check("a dump file is written", len(dumps()) == 1)
body = open(os.path.join(D, dumps()[0]), encoding="utf-8").read()
check("header records heavy_busy and the hold", "heavy_busy" in body and "held 3 checks" in body)
check("the dump has thread stacks", "all thread stacks" in body and ("Thread" in body or 'File "' in body))
check("no header or token leak", "Authorization" not in body and "x-api-key" not in body and "Bearer" not in body)

# rate-limited: a second call within DUMP_EVERY writes nothing new
GD._stuck_dump(GD.HEAVY_CAP, 4, 60)
check("a second dump within DUMP_EVERY is suppressed", len(dumps()) == 1)

# keep at most DUMP_KEEP
for i in range(5):
    open(os.path.join(D, "stuck-2020010100000%dZ.txt" % i), "w").write("x")
GD._prune_dumps()
check("prune keeps at most DUMP_KEEP", len(dumps()) == 3)

print("FAILED: " + "; ".join(fails) if fails else "all ok"); sys.exit(1 if fails else 0)
