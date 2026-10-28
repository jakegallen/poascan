"""Establishment door tracker (1.26.205, Governance, Intake): per close Rate (admitted over eligible), TTL out (removed with no
slash or ejection), Other out and Net; the Proposal L params flag (Not set until /api/params carries estab_intake_floor,
estab_intake_rate or estab_intake_from_epoch, then Set with the time POAScan's hourly read first saw it) and estab_ttl changes;
the same fields in /api/v1/governance/intake. Temp database, no network. Usage: python3 tools/door_test.py"""
import json, os, sys, tempfile, time
os.environ["POASCAN_SEGMENTS"] = "1"
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "d.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, intake as IK, governance as GV

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
NOW = int(time.time()); ad = lambda i: "poa1" + format(i, "040d").replace("0", "Q")
EST0 = [ad(i) for i in range(1, 21)]; C = [ad(i) for i in range(100, 110)]
rec = lambda n, ce, ea, er=(), sl=(), ej=(): {"epoch": n, "ts": NOW - (5 - n) * 21600, "rewards": {}, "challenges": {},
    "basis": {"challenge_eligible": list(ce), "established_after": list(ea), "established_removed": list(er), "slashed": list(sl), "ejected": list(ej), "pending": {}, "settled": []}}
eps = [rec(0, [], EST0), rec(1, C, C[:5]), rec(2, C[5:], [], er=EST0[:3] + [EST0[3]], sl=[EST0[3]]), rec(3, [], [], er=[EST0[4]], ej=[EST0[4]])]
db.init(); db.put_blob("epochs", eps); db.put_blob("params", {"estab_ttl": 6, "pending_ttl_epochs": 16})
db.put_blob("status", {"epochs_closed": 4, "checkpoint_height": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW))})
A._cache.clear()
c = {r["close"]: r for r in IK.closes()}
check("E1: Rate 5 of 10 = 0.5, nobody out, Net +5", c[1]["admit_rate"] == 0.5 and c[1]["removed"] == 0 and c[1]["net"] == 5)
check("E2: 4 removed, 3 by TTL, 1 slashed (Other), Net -4, Rate 0", c[2]["removed_ttl"] == 3 and c[2]["removed_other"] == 1 and c[2]["net"] == -4 and c[2]["admit_rate"] == 0)
check("E3: nobody eligible: Rate None; an ejection is Other out", c[3]["admit_rate"] is None and c[3]["removed_other"] == 1 and c[3]["removed_ttl"] == 0)
st = IK.propl_state()
check("flag: Not set without the params", st["present"] is False and st["first_seen"] is None)
h = GV.page({"tab": ["intake"]})
h = h if isinstance(h, str) else h[1]
check("Intake tab: Rate, TTL out, Other out, Net headers and the Proposal L stat Not set", all(x in h for x in (">Rate<", ">TTL out<", ">Other out<", ">Net<", "Proposal L params", "Not set")))
IK.note_params({"estab_ttl": 6}, now=NOW - 100)
IK.note_params({"estab_ttl": 8, "estab_intake_floor": 20, "estab_intake_rate": 0.1}, now=NOW)
db.put_blob("params", {"estab_ttl": 8, "estab_intake_floor": 20, "estab_intake_rate": 0.1, "pending_ttl_epochs": 16}); A._cache.clear()
IK.note_params({"estab_ttl": 8, "estab_intake_floor": 20, "estab_intake_rate": 0.1}, now=NOW + 3600)
st = IK.propl_state()
check("flag: Set with keys, first seen at the first read that carried them", st["present"] and st["keys"] == {"estab_intake_floor": 20, "estab_intake_rate": 0.1} and st["first_seen"] == NOW)
check("estab_ttl change noted once (6 to 8)", [x["value"] for x in st["estab_ttl_changes"]] == [8])
a = IK.api()
check("API: proposal_l and the new per close fields", a["proposal_l"]["present"] and all(k in a["rows"][0] for k in ("admit_rate", "removed_ttl", "removed_other", "net")))
h = GV.page({"tab": ["intake"]}); h = h if isinstance(h, str) else h[1]
check("Intake tab: flag reads Set", "Proposal L params" in h and ">Set<" in h)
print("FAILS:", fails) if fails else print("ALL OK")
sys.exit(1 if fails else 0)
