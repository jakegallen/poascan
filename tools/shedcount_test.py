"""1.26.342 (plan v2, A): a shed (a 503 returned because no heavy slot or capacity was free within the bounded wait) is
counted and shown as telemetry `sheds` on /api/status and /ops, and the shed 503 advises Retry-After 15 so a client
backs off instead of hammer-retrying into the jam. Usage: python3 tools/shedcount_test.py"""
import os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import guard as GD

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

before = GD.telemetry().get("sheds")
check("telemetry exposes an integer sheds counter", isinstance(before, int))
GD.note_shed(); GD.note_shed()
check("note_shed increments the telemetry sheds count", GD.telemetry()["sheds"] == before + 2)

src = open(os.path.join(ROOT, "poascan", "server.py"), encoding="utf-8").read()
check("the busy and API shed 503 advise Retry-After 15", '"Retry-After": "15"' in src and "server busy, retry shortly" in src)
check("a search crawler shed keeps Retry-After 60", '"60" if self._is_search_crawler()' in src)
check("each shed 503 is counted (note_shed before the shed returns)", src.count("GD.note_shed()") >= 2)

print("FAILED: " + "; ".join(fails) if fails else "all ok"); sys.exit(1 if fails else 0)
