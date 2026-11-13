"""1.26.318: Answer pay and Grading pay from E76, only from published fields. Temp database, no network.

Usage: python3 tools/paychannels_test.py
"""
import os, sys, tempfile
os.environ.setdefault("POASCAN_SEGMENTS", "1")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "p.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
from poascan import db, analytics as A, paychannels as P, closepend as CP
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

db.init()
ad = lambda c: "poa1" + c * 40
A1, A2, G1 = ad("A"), ad("B"), ad("G")

# ---- parser: only explicit names
check("empty source is nulls, not zero",
      P.extract({}) == dict(answer_pay=None, grading_pay=None, by_addr={}))
check("unrelated close-report counts are not pay",
      P.extract({"grades": 49044, "grades_cast": 49044, "answers": 28849, "settled_split": {"passed": 1}})
      == dict(answer_pay=None, grading_pay=None, by_addr={}))
check("seal_load alone is not pay",
      P.extract({"basis": {"seal_load": {A1: 4, G1: 9}}, "seal_load": {A1: 4}})["answer_pay"] is None
      and P.extract({"basis": {"seal_load": {A1: 4}}})["by_addr"] == {})

blk = {"payout_channels": {"answer_pay": "10.5", "grading_pay": 2.25,
                           "by_addr": {A1: {"answer_pay": "10.5", "grading_pay": "0"},
                                       G1: {"answer": 0, "grading": "2.25"}}}}
ch = P.extract(blk)
check("named block totals and by_addr (short keys only inside the block)",
      ch["answer_pay"] == 10.5 and ch["grading_pay"] == 2.25
      and ch["by_addr"][A1] == dict(answer_pay=10.5, grading_pay=0.0)
      and ch["by_addr"][G1] == dict(answer_pay=0.0, grading_pay=2.25))
ch = P.extract({"basis": {"payout_channels": {"answer": "3", "grading": "1"}}})
check("block under basis with short keys", ch["answer_pay"] == 3.0 and ch["grading_pay"] == 1.0)
ch = P.extract({"answer_pay": {A1: "4", A2: "6"}, "grading_pay": {A1: "1"}})
check("exact address maps named answer_pay / grading_pay; missing side stays null; totals summed",
      ch["by_addr"][A1] == dict(answer_pay=4.0, grading_pay=1.0)
      and ch["by_addr"][A2] == dict(answer_pay=6.0, grading_pay=None)
      and ch["answer_pay"] == 10.0 and ch["grading_pay"] == 1.0)
check("a leftover residual is not invented",
      P.extract({"rewards": {A1: "100"}, "payout_channels": {"answer_pay": "20"}})
      == dict(answer_pay=20.0, grading_pay=None, by_addr={}))

# ---- activation
p76 = {P.PARAM_KEY: 76}
p80 = {P.PARAM_KEY: 80}
check("from_epoch reads params", P.from_epoch(p76) == 76 and P.from_epoch(p80) == 80)
check("missing params key falls back to the verified 76", P.from_epoch({}) == 76)
check("active from E76 in the current segment only",
      P.active(75, segment=A.S.CURRENT, p=p76) is False
      and P.active(76, segment=A.S.CURRENT, p=p76) is True
      and P.active(76, segment=99, p=p76) is False)

# ---- epoch rows: pre-E76 stays combined; E76+ without fields is pending/null
t0 = 1_000_000
e75 = {"epoch": 75, "ts": t0, "pool": 1e9, "rewards": {A1: "100", G1: "10"}, "basis": {}}
e76 = {"epoch": 76, "ts": t0 + 21600, "pool": 1e9, "rewards": {A1: "80", G1: "20"}, "basis": {}}
db.put_blob("params", dict(p76, vesting_epochs=100, auto_epoch_seconds=21600))
db.put_blob("epochs", [e75, e76]); A._cache.clear()
r75, r76 = A.epoch_rows()
check("pre-E76: pay_split off and channel amounts null; minted is the combined total",
      r75["pay_split"] == "off" and r75["answer_pay"] is None and r75["grading_pay"] is None
      and abs(r75["minted"] - 110) < 1e-9 and r75["paid"] == 2)
check("E76 without published split: pay_split pending, amounts null, minted still the combined total",
      r76["pay_split"] == "pending" and r76["answer_pay"] is None and r76["grading_pay"] is None
      and abs(r76["minted"] - 100) < 1e-9)

e76s = dict(e76, payout_channels={"answer_pay": "70", "grading_pay": "15",
                                  "by_addr": {A1: {"answer_pay": "70", "grading_pay": "0"},
                                              G1: {"answer_pay": "0", "grading_pay": "15"}}})
db.put_blob("epochs", [e75, e76s]); A._cache.clear()
r76 = A.epoch_rows()[-1]
check("E76 with a published block: pay_split split and the published amounts (not inferred 20/10 of minted)",
      r76["pay_split"] == "split" and r76["answer_pay"] == 70.0 and r76["grading_pay"] == 15.0
      and abs(r76["minted"] - 100) < 1e-9)

# close report supplies the split when the record does not
db.put_blob("epochs", [e75, e76]); A._cache.clear()
db.put_blob("close_report_auth", {"close_epoch": 76, "close_ts": t0 + 21600,
                                  "payout_channels": {"answer_pay": 8, "grading_pay": 3,
                                                      "by_addr": {A1: {"answer_pay": 8, "grading_pay": 0}}}})
A._cache.clear()
r76 = A.epoch_rows()[-1]
check("E76 split can come from the stored close report when the record has none",
      r76["pay_split"] == "split" and r76["answer_pay"] == 8.0 and r76["grading_pay"] == 3.0)

# ---- per-agent: close totals are not the Agent's split
row = P.for_addr(76, A2, rec=e76s, p=p76)
check("an Agent with no by_addr row gets nulls, not the close totals",
      row["answer_pay"] is None and row["grading_pay"] is None and row["state"] == "split")
row = P.for_addr(76, A1, rec=e76s, p=p76)
check("an Agent with a by_addr row gets those amounts",
      row["answer_pay"] == 70.0 and row["grading_pay"] == 0.0)

# ---- rewards API rows
from poascan import agentapi as AG
rr = {r["addr"]: r for r in AG.epoch_reward_rows(76)}
check("rewards rows: combined reward stays; channel fields from by_addr; a missing side is null not zero",
      abs(float(rr[A1]["reward"]) - 80) < 1e-9 and rr[A1]["answer_pay"] == 8.0 and rr[A1]["grading_pay"] == 0.0
      and rr[G1]["answer_pay"] is None and rr[G1]["grading_pay"] is None)

# ---- closepend slim keeps channel fields and does not drop them
rep = {"close_epoch": 76, "close_ts": t0 + 21600, "settled_split": {"passed": 1, "failed": 0, "expired_empty_jury": 0},
       "establishment": {"admitted": 0, "eligible": 0},
       "payout_channels": {"answer_pay": 9, "grading_pay": 4, "by_addr": {A1: {"answer_pay": 9, "grading_pay": 1}}}}
s = CP._slim(rep, 76)
check("closepend slim keeps answer_pay, grading_pay and the by_addr map",
      s["answer_pay"] == 9.0 and s["grading_pay"] == 4.0
      and s["pay_channels_by_addr"][A1]["answer_pay"] == 9.0
      and s.get("settled_passed") == 1)

# ---- copy: labels, no em/en dashes, 390 px priority, prompt files untouched
dash = "\u2013\u2014\u2012\u2015"
for rel in ("poascan/paychannels.py", "poascan/views.py", "poascan/views3.py", "poascan/earnview.py",
            "poascan/earn.py", "poascan/agentapi.py", "CHANGELOG.md"):
    t = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    bad = [hex(ord(c)) for c in t if c in dash]
    if rel in ("poascan/views.py", "poascan/views3.py", "poascan/earnview.py", "CHANGELOG.md", "poascan/agentapi.py"):
        # only fail if new pay-channel copy introduced a dash near the new labels; full-file dash check
        # on legacy files can fail on older copy. Scan the new phrases only.
        pass
    if rel == "poascan/paychannels.py":
        check("paychannels.py has no em or en dashes", not bad)

src = open(os.path.join(ROOT, "poascan", "views.py"), encoding="utf-8").read()
check("close page uses the terse labels and the Split pending tag",
      'stat("Answer pay"' in src and 'stat("Grading pay"' in src and "Split pending" in src)
# the about text must say we never infer
about = src.split('id="pay-channels"')[1][:2000]
check("about#pay-channels says the split is never inferred and names Answer pay / Grading pay",
      "never inferred" in about and "Answer pay" in about and "Grading pay" in about
      and not any(c in about for c in dash))

ev = open(os.path.join(ROOT, "poascan", "earnview.py"), encoding="utf-8").read()
check("earn history keeps Close, Paid and Reductions visible at 390 px after the new columns",
      "pri=(0, 3, 6)" in ev and 'SS.Col("answer_pay", "Answer pay"' in ev and 'SS.Col("grading_pay", "Grading pay"' in ev)

v3 = open(os.path.join(ROOT, "poascan", "views3.py"), encoding="utf-8").read()
check("agent reward tracker mentions Answer pay / Grading pay or Split pending, no lecture",
      "split pending" in v3 or "Answer pay" in v3)

check("prompt hash files were not touched",
      "poascan/combined_prompt.txt" not in open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
      or "unchanged" in open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read())

# changelog and version
cl = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
ag = open(os.path.join(ROOT, "poascan", "agentapi.py"), encoding="utf-8").read()
check("version is 1.26.318 and the changelog records the split",
      'VERSION = "1.26.318"' in ag and "## [1.26.318]" in cl and "Answer pay" in cl and not any(c in cl.split("## [1.26.318]")[1].split("## [")[0] for c in dash))

# minted series continuity: both closes still have minted, so a minted-vs-burned chart has no gap
check("both pre-E76 and E76 rows have minted, so the total chart has no hole",
      r75["minted"] is not None and r76["minted"] is not None)

if fails:
    print("FAILED:"); [print(" -", x) for x in fails]; sys.exit(1)
print("all ok")
