"""Governance standing summary (POASCAN data ask 5a): /api/v1/governance/standing returns safe/watch/at_risk counts plus
closing_next (established Agents dropping at the open epoch's close). Counts only, from the close records. Usage:
python3 tools/gov_standing_test.py (temp database, no network)."""
import os, sys, tempfile
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, governance as GV
db.init()

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

GV.standing_rows = lambda: dict(
    rows=[dict(level="risk", left=1), dict(level="risk", left=0), dict(level="watch", left=3), dict(level="safe", left=40)],
    open_epoch=100, ttl=26, last_close=99,
    counts=dict(risk=2, watch=1, safe=1, norecord=0, system=0))
o = GV.api_standing_summary()
check("5a at_risk maps from the risk bucket", o["at_risk"] == 2)
check("5a watch + safe pass through", o["watch"] == 1 and o["safe"] == 1)
check("5a closing_next counts only closes-left == 1 (drop at the open close)", o["closing_next"] == 1)
check("5a established is safe + watch + at_risk", o["established"] == 4)
check("5a carries open_epoch, last_close, ttl", o["open_epoch"] == 100 and o["last_close"] == 99 and o["ttl"] == 26)

srv = open(os.path.join(ROOT, "poascan", "server.py")).read()
check("server routes /api/governance/standing to api_standing_summary", '"/api/governance/standing": GV.api_standing_summary()'.split(":")[0] in srv and "api_standing_summary()" in srv)
check("/api/governance/standing is in the GOV_API allow-list", '"/api/governance/standing": set()' in srv)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
