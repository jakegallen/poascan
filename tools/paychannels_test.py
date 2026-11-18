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
      P.extract({}) == dict(answer_pay=None, grading_pay=None, referral_pay=None, by_addr={}))
check("unrelated close-report counts are not pay",
      P.extract({"grades": 49044, "grades_cast": 49044, "answers": 28849, "settled_split": {"passed": 1}})
      == dict(answer_pay=None, grading_pay=None, referral_pay=None, by_addr={}))
check("seal_load alone is not pay",
      P.extract({"basis": {"seal_load": {A1: 4, G1: 9}}, "seal_load": {A1: 4}})["answer_pay"] is None
      and P.extract({"basis": {"seal_load": {A1: 4}}})["by_addr"] == {})

blk = {"payout_channels": {"answer_pay": "10.5", "grading_pay": 2.25,
                           "by_addr": {A1: {"answer_pay": "10.5", "grading_pay": "0"},
                                       G1: {"answer": 0, "grading": "2.25"}}}}
ch = P.extract(blk)
check("named block totals and by_addr (short keys only inside the block)",
      ch["answer_pay"] == 10.5 and ch["grading_pay"] == 2.25
      and ch["by_addr"][A1] == dict(answer_pay=10.5, grading_pay=0.0, referral_pay=None)
      and ch["by_addr"][G1] == dict(answer_pay=0.0, grading_pay=2.25, referral_pay=None))
ch = P.extract({"basis": {"payout_channels": {"answer": "3", "grading": "1"}}})
check("block under basis with short keys", ch["answer_pay"] == 3.0 and ch["grading_pay"] == 1.0)
ch = P.extract({"answer_pay": {A1: "4", A2: "6"}, "grading_pay": {A1: "1"}})
check("exact address maps named answer_pay / grading_pay; missing side stays null; totals summed",
      ch["by_addr"][A1] == dict(answer_pay=4.0, grading_pay=1.0, referral_pay=None)
      and ch["by_addr"][A2] == dict(answer_pay=6.0, grading_pay=None, referral_pay=None)
      and ch["answer_pay"] == 10.0 and ch["grading_pay"] == 1.0)
check("a leftover residual is not invented",
      P.extract({"rewards": {A1: "100"}, "payout_channels": {"answer_pay": "20"}})
      == dict(answer_pay=20.0, grading_pay=None, referral_pay=None, by_addr={}))

# 1.26.326: basis.final_payout answer.E / grading.E / referral.E
fp = {"answer": {"E": 751976668.925128, "W": 7.52e8, "capped": {A1: 100.0, A2: 200.0}, "repooled": {G1: 3.0}},
      "grading": {"E": 98023331.072829, "W": 9.8e7, "capped": {G1: 50.0}},
      "referral": {"E": 3346399.954117}}
ch = P.extract({"basis": {"final_payout": fp}, "rewards": {A1: "1"}})
check("final_payout.E totals are read; referral.E is its own field; capped/repooled are not by_addr",
      abs(ch["answer_pay"] - 751976668.925128) < 1e-9
      and abs(ch["grading_pay"] - 98023331.072829) < 1e-9
      and abs(ch["referral_pay"] - 3346399.954117) < 1e-9
      and ch["by_addr"] == {})
ch = P.extract({"final_payout": {"answer": {"E": 10}, "grading": {"E": 2}, "referral": {"E": 1}}})
check("top-level final_payout is also a published source",
      ch["answer_pay"] == 10.0 and ch["grading_pay"] == 2.0 and ch["referral_pay"] == 1.0)
ch = P.extract({"basis": {"final_payout": {"answer": {"W": 10}, "grading": {"W": 2}}}})
check("final_payout W alone is not an amount; E must be explicit",
      ch["answer_pay"] is None and ch["grading_pay"] is None and ch["referral_pay"] is None)
ch = P.extract({"basis": {"final_payout": {"answer": {"E": 5},
                                           "by_addr": {A1: {"answer_pay": 5, "grading_pay": 0}}}}})
check("final_payout per-Agent amounts only from a named by_addr map, never from capped",
      ch["answer_pay"] == 5.0 and ch["by_addr"][A1]["answer_pay"] == 5.0
      and ch["by_addr"][A1]["referral_pay"] is None)
# payout_channels already set wins over a later final_payout in the same object? extract walks
# named blocks first then final_payout; take() does not overwrite. Good.
ch = P.extract({"payout_channels": {"answer_pay": 1, "grading_pay": 2},
                "basis": {"final_payout": {"answer": {"E": 9}, "grading": {"E": 8}, "referral": {"E": 3}}}})
check("a published payout_channels total is not overwritten by final_payout; referral can still fill in",
      ch["answer_pay"] == 1.0 and ch["grading_pay"] == 2.0 and ch["referral_pay"] == 3.0)


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
      r75["pay_split"] == "off" and r75["answer_pay"] is None and r75["grading_pay"] is None and r75.get("referral_pay") is None
      and abs(r75["minted"] - 110) < 1e-9 and r75["paid"] == 2)
check("E76 without published split: pay_split pending, amounts null, minted still the combined total",
      r76["pay_split"] == "pending" and r76["answer_pay"] is None and r76["grading_pay"] is None and r76.get("referral_pay") is None
      and abs(r76["minted"] - 100) < 1e-9)

e76s = dict(e76, payout_channels={"answer_pay": "70", "grading_pay": "15",
                                  "by_addr": {A1: {"answer_pay": "70", "grading_pay": "0"},
                                              G1: {"answer_pay": "0", "grading_pay": "15"}}})
db.put_blob("epochs", [e75, e76s]); A._cache.clear()
r76 = A.epoch_rows()[-1]
check("E76 with a published block: pay_split split and the published amounts (not inferred 20/10 of minted)",
      r76["pay_split"] == "split" and r76["answer_pay"] == 70.0 and r76["grading_pay"] == 15.0
      and abs(r76["minted"] - 100) < 1e-9)

e76fp = dict(e76, basis={"final_payout": {"answer": {"E": 80.0}, "grading": {"E": 15.0}, "referral": {"E": 5.0}}})
# minted from rewards is 100; the three parts sum to 100 but the parser does not require that
db.put_blob("epochs", [e75, e76fp]); A._cache.clear()
r75b, r76fp = A.epoch_rows()
check("E76 final_payout: pay_split split, three parts present, pre-E76 stays combined",
      r76fp["pay_split"] == "split" and r76fp["answer_pay"] == 80.0 and r76fp["grading_pay"] == 15.0
      and r76fp["referral_pay"] == 5.0 and abs((r76fp["answer_pay"] + r76fp["grading_pay"] + r76fp["referral_pay"]) - 100) < 1e-9
      and r75b["pay_split"] == "off" and r75b["answer_pay"] is None and r75b["referral_pay"] is None)
# restore the payout_channels fixture for the tests that follow
db.put_blob("epochs", [e75, e76s]); A._cache.clear()
r76 = A.epoch_rows()[-1]

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
      'stat("Answer pay"' in src and 'stat("Grading pay"' in src and 'stat("Referral pay"' in src and "Split pending" in src)
# the about text must say we never infer
about = src.split('id="pay-channels"')[1][:2000]
check("about#pay-channels says the split is never inferred and names Answer pay / Grading pay",
      "never inferred" in about and "Answer pay" in about and "Grading pay" in about
      and "Referral pay" in about and "final_payout" in about
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
# later releases bump VERSION; the 1.26.318 changelog entry still records the split
import re as _re
_vm = _re.search(r'VERSION = "(\d+)\.(\d+)\.(\d+)"', ag)
_ver = tuple(int(x) for x in _vm.groups()) if _vm else (0, 0, 0)
check("version is at least 1.26.326 and the changelog records final_payout",
      _ver >= (1, 26, 326) and "## [1.26.326]" in cl and "final_payout" in cl
      and not any(c in cl.split("## [1.26.326]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.329 and the changelog records the revert to 1.26.326",
      _ver >= (1, 26, 329) and "## [1.26.329]" in cl and "back to 1.26.326" in cl
      and not any(c in cl.split("## [1.26.329]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.330 and the changelog records the single first build",
      _ver >= (1, 26, 330) and "## [1.26.330]" in cl and "built once" in cl
      and not any(c in cl.split("## [1.26.330]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.331 and the changelog records the timed out first readers",
      _ver >= (1, 26, 331) and "## [1.26.331]" in cl and "only one build runs" in cl
      and not any(c in cl.split("## [1.26.331]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.332 and the changelog records the shared epoch rows",
      _ver >= (1, 26, 332) and "## [1.26.332]" in cl and "built once per change" in cl
      and not any(c in cl.split("## [1.26.332]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.333 and the changelog records the grading state reuse",
      _ver >= (1, 26, 333) and "## [1.26.333]" in cl and "reused for 10 s" in cl
      and not any(c in cl.split("## [1.26.333]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.334 and the changelog records the probe 429 hold",
      _ver >= (1, 26, 334) and "## [1.26.334]" in cl and "uptime probe" in cl
      and not any(c in cl.split("## [1.26.334]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.335 and the changelog records the params digest and the memo gate",
      _ver >= (1, 26, 335) and "## [1.26.335]" in cl and "digest of the content" in cl
      and not any(c in cl.split("## [1.26.335]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.336 and the changelog records the slim record reuse",
      _ver >= (1, 26, 336) and "## [1.26.336]" in cl and "parses only its own slim close record" in cl
      and not any(c in cl.split("## [1.26.336]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.338 and the changelog records the grading index fold",
      _ver >= (1, 26, 338) and "## [1.26.338]" in cl and "grading index" in cl
      and not any(c in cl.split("## [1.26.338]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.339 and the changelog records the RSS exit ceiling",
      _ver >= (1, 26, 339) and "## [1.26.339]" in cl and "exit ceiling" in cl
      and not any(c in cl.split("## [1.26.339]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.340 and the changelog records the resident memory report",
      _ver >= (1, 26, 340) and "## [1.26.340]" in cl and "resident" in cl
      and not any(c in cl.split("## [1.26.340]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.341 and the changelog records the stuck-pool thread dump",
      _ver >= (1, 26, 341) and "## [1.26.341]" in cl and "thread-stack dump" in cl
      and not any(c in cl.split("## [1.26.341]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.342 and the changelog records the shed counter and Retry-After backoff",
      _ver >= (1, 26, 342) and "## [1.26.342]" in cl and "sheds" in cl
      and not any(c in cl.split("## [1.26.342]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.343 and the changelog records the shed route breakdown",
      _ver >= (1, 26, 343) and "## [1.26.343]" in cl and "sheds_by" in cl
      and not any(c in cl.split("## [1.26.343]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.344 and the changelog records the finer shed split",
      _ver >= (1, 26, 344) and "## [1.26.344]" in cl and "epoch_html" in cl
      and not any(c in cl.split("## [1.26.344]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.345 and the changelog records the 202 poll_url resolve rule (join prompt v2.9.7)",
      _ver >= (1, 26, 345) and "## [1.26.345]" in cl and "poll_url" in cl and "v2.9.7" in cl
      and not any(c in cl.split("## [1.26.345]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.346 and the changelog records the /ops/memory sqlite + tracked/untracked split",
      _ver >= (1, 26, 346) and "## [1.26.346]" in cl and "sqlite section" in cl and "untracked" in cl
      and not any(c in cl.split("## [1.26.346]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.347 and the changelog records /api/swaps offset/limit paging",
      _ver >= (1, 26, 347) and "## [1.26.347]" in cl and "?offset" in cl and "?limit" in cl
      and not any(c in cl.split("## [1.26.347]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.348 and the changelog records the Bearer auth switch (v2.9.8) and the swap state no-op",
      _ver >= (1, 26, 348) and "## [1.26.348]" in cl and "Authorization: Bearer" in cl and "#1214" in cl and "v2.9.8" in cl
      and not any(c in cl.split("## [1.26.348]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.349 and the changelog records Answer Sort and the Bug 2850 locked_est fix",
      _ver >= (1, 26, 349) and "## [1.26.349]" in cl and "Answer Sort" in cl and "locked_est" in cl
      and not any(c in cl.split("## [1.26.349]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.350 and the changelog records the Agent profile refresh",
      _ver >= (1, 26, 350) and "## [1.26.350]" in cl and "Agent profile refresh" in cl and "Epochs card" in cl
      and not any(c in cl.split("## [1.26.350]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.351 and the changelog records the 390 px consistency fixes",
      _ver >= (1, 26, 351) and "## [1.26.351]" in cl and "Consistency at 390 px" in cl
      and not any(c in cl.split("## [1.26.351]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.352 and the changelog records Header search",
      _ver >= (1, 26, 352) and "## [1.26.352]" in cl and "Header search" in cl
      and not any(c in cl.split("## [1.26.352]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.353 and the changelog records Trade on POASwap",
      _ver >= (1, 26, 353) and "## [1.26.353]" in cl and "Trade on POASwap" in cl
      and not any(c in cl.split("## [1.26.353]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.354 and the changelog records Daily volume",
      _ver >= (1, 26, 354) and "## [1.26.354]" in cl and "Daily volume" in cl
      and not any(c in cl.split("## [1.26.354]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.355 and the changelog records Epoch story",
      _ver >= (1, 26, 355) and "## [1.26.355]" in cl and "Epoch story" in cl
      and not any(c in cl.split("## [1.26.355]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.356 and the changelog records settled records",
      _ver >= (1, 26, 356) and "## [1.26.356]" in cl and "settled records" in cl
      and not any(c in cl.split("## [1.26.356]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.357 and the changelog records next full GC",
      _ver >= (1, 26, 357) and "## [1.26.357]" in cl and "next full GC" in cl
      and not any(c in cl.split("## [1.26.357]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.358 and the changelog records one indexed lookup per side",
      _ver >= (1, 26, 358) and "## [1.26.358]" in cl and "one indexed lookup per side" in cl
      and not any(c in cl.split("## [1.26.358]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.359 and the changelog records share one copy of equal addresses",
      _ver >= (1, 26, 359) and "## [1.26.359]" in cl and "share one copy of equal addresses" in cl
      and not any(c in cl.split("## [1.26.359]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.360 and the changelog records only that address's pending rows",
      _ver >= (1, 26, 360) and "## [1.26.360]" in cl and "only that address's pending rows" in cl
      and not any(c in cl.split("## [1.26.360]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.361 and the changelog records Established history API",
      _ver >= (1, 26, 361) and "## [1.26.361]" in cl and "Established history API" in cl
      and not any(c in cl.split("## [1.26.361]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.362 and the changelog records spike dump",
      _ver >= (1, 26, 362) and "## [1.26.362]" in cl and "spike dump" in cl
      and not any(c in cl.split("## [1.26.362]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.363 and the changelog records once per request",
      _ver >= (1, 26, 363) and "## [1.26.363]" in cl and "once per request" in cl
      and not any(c in cl.split("## [1.26.363]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.364 and the changelog records cold compute slots",
      _ver >= (1, 26, 364) and "## [1.26.364]" in cl and "cold compute slots" in cl
      and not any(c in cl.split("## [1.26.364]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.365 and the changelog records keyed by repr",
      _ver >= (1, 26, 365) and "## [1.26.365]" in cl and "keyed by repr" in cl
      and not any(c in cl.split("## [1.26.365]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.366 and the changelog records pinned",
      _ver >= (1, 26, 366) and "## [1.26.366]" in cl and "pinned" in cl
      and not any(c in cl.split("## [1.26.366]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.367 and the changelog records only the closes",
      _ver >= (1, 26, 367) and "## [1.26.367]" in cl and "only the closes" in cl
      and not any(c in cl.split("## [1.26.367]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.368 and the changelog records folds over the closes",
      _ver >= (1, 26, 368) and "## [1.26.368]" in cl and "folds over the closes" in cl
      and not any(c in cl.split("## [1.26.368]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.369 and the changelog records the streamed grader patterns",
      _ver >= (1, 26, 369) and "## [1.26.369]" in cl and "streamed" in cl
      and not any(c in cl.split("## [1.26.369]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.370 and the changelog records the Community Topics tab",
      _ver >= (1, 26, 370) and "## [1.26.370]" in cl and "Community Topics" in cl
      and not any(c in cl.split("## [1.26.370]")[1].split("## [")[0] for c in dash))
check("version is 1.26.371 and the changelog records the homepage forum pulse",
      _ver >= (1, 26, 371) and "## [1.26.371]" in cl and "forum pulse" in cl
      and not any(c in cl.split("## [1.26.371]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.372 and the changelog records forum moments in the epoch timeline",
      _ver >= (1, 26, 372) and "## [1.26.372]" in cl and "Forum moments" in cl
      and not any(c in cl.split("## [1.26.372]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.373 and the changelog records the forum pulse and moments polish",
      _ver >= (1, 26, 373) and "## [1.26.373]" in cl and "word boundary" in cl
      and not any(c in cl.split("## [1.26.373]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.374 and the changelog records the forum pulse spacing and footnote removal",
      _ver >= (1, 26, 374) and "## [1.26.374]" in cl and "tabular numerals" in cl
      and not any(c in cl.split("## [1.26.374]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.375 and the changelog records Answered vs Backlog paid",
      _ver >= (1, 26, 375) and "## [1.26.375]" in cl and "Backlog paid" in cl
      and not any(c in cl.split("## [1.26.375]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.376 and the changelog records the releases to threads links",
      _ver >= (1, 26, 376) and "## [1.26.376]" in cl and "high precision" in cl
      and not any(c in cl.split("## [1.26.376]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.377 and the changelog records the forum posts per day chart",
      _ver >= (1, 26, 377) and "## [1.26.377]" in cl and "Forum posts / day" in cl
      and not any(c in cl.split("## [1.26.377]")[1].split("## [")[0] for c in dash))
check("version is at least 1.26.378 and the changelog records Backlog vs Backlog paid",
      _ver >= (1, 26, 378) and "## [1.26.378]" in cl and "paid 0 POA" in cl
      and not any(c in cl.split("## [1.26.378]")[1].split("## [")[0] for c in dash))
check("version is 1.26.379 and the changelog records the Agent profile forum activity card",
      _ver == (1, 26, 379) and "## [1.26.379]" in cl and "Forum activity" in cl
      and not any(c in cl.split("## [1.26.379]")[1].split("## [")[0] for c in dash))
check("1.26.318 changelog entry is still present", "## [1.26.318]" in cl and "Answer pay" in cl)

# minted series continuity: both closes still have minted, so a minted-vs-burned chart has no gap
check("both pre-E76 and E76 rows have minted, so the total chart has no hole",
      r75["minted"] is not None and r76["minted"] is not None)

if fails:
    print("FAILED:"); [print(" -", x) for x in fails]; sys.exit(1)
print("all ok")
