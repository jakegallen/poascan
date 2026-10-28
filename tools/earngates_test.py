"""Preview (preview/earn-gates-1028): the three earning gates in earn.check. Every value names a source and a read time;
'No panel seated yet' and the two close read are marked Inferred; the birth panel (close record) and seated graders
(receipts) are separate fields; disagreeing Established reads are shown side by side. No network. Usage: python3 tools/earngates_test.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import earn as EA

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
A = "poa1" + "x" * 40; T1, T2 = "a" * 64, "b" * 64
st = dict(segment=2, established=True, minepoa_established=False, last_challenge_eligible_epoch=11, established_expires_closes_left=3, open_epoch=16, last_close=15,
          pending=dict(as_of_close=15, count=2, with_panel=0))
rc = [dict(tx=T1, epoch=13, segment=2, accepted=True, status="pending", seals=0), dict(tx=T2, epoch=14, segment=2, accepted=True, status="pending", seals=0),
      dict(tx="c" * 64, epoch=9, segment=2, accepted=True, status="passed", settled_close=11)]
inp = dict(standing=st, receipts=rc, governance=dict(facts=dict(jury_seats=5)), history=[dict(close=14, ts=1000), dict(close=15, ts=2000), dict(close=11, ts=500)],
           pend_grades={14: {T1: dict(grades=0, panel=0), T2: dict(grades=0, panel=0)}, 15: {T1: dict(grades=0, panel=0), T2: dict(grades=0, panel=0)}})
cnt = dict(passed=1, failed=0, pending=2, awaiting_close=0, vanished=0)
g = EA.gates(A, inp, [9, 13, 14], cnt, 16, now=3000)
check("three gates: Answers, Grading, Established", [x["key"] for x in g] == ["answers", "grading", "established"])
vals = [v for x in g for v in x["values"]]
check("every value has a source and a read time", all(v["source"] and v["at"] for v in vals))
gv = {v["label"]: v for v in g[1]["values"]}
check("birth panel from the close record, seated graders from receipts", gv["Birth panel"]["source"] == "Close record" and "fixed at birth" in gv["Birth panel"]["field"] and gv["Seated graders"]["source"] == "POAScan receipts")
check("close record value is timed at its close", gv["Birth panel"]["at"] == 2000)
check("no panel seated yet is Inferred", gv.get("Panel", {}).get("value") == "No panel seated yet" and gv["Panel"]["inferred"])
check("grade count across two closes, not moving, stalled read Inferred", "not moving" in gv["Grades, last two closes"]["value"] and gv["Read"]["inferred"] and "stalled" in gv["Read"]["value"])
ev = {v["label"]: v for v in g[2]["values"]}
check("Established reads disagree: both shown and the disagreement is Inferred", ev["Established"]["value"] == "Yes" and ev["Network read"]["value"] == "No" and ev["Agreement"]["inferred"])
check("closes left is an Inferred estimate", ev["Closes left"]["inferred"])
inp["pend_grades"][15][T1]["grades"] = 2
g = EA.gates(A, inp, [9, 13, 14], cnt, 16, now=3000); gv = {v["label"]: v for v in g[1]["values"]}
check("grades rising across two closes reads as landing", "moving" in gv["Grades, last two closes"]["value"] and "not" not in gv["Grades, last two closes"]["value"] and gv["Read"]["value"] == "Grades are landing")
check("FAQ explains the two panels and the rule of thumb", any("two closes" in a and "birth panel" in a for q, a in __import__("poascan.earnview", fromlist=["FAQ"]).FAQ))
print("FAILS:", fails) if fails else print("ALL OK")
sys.exit(1 if fails else 0)
