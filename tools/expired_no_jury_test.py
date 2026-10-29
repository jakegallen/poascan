"""Expired, no jury (1.26.224): a basis.settled row with expired true and an empty jury is its own outcome, never a failure.
Covers the classifier (expired with no jury vs jury fail vs pass), the E19 split (2,000 settled: 1,954 expired, 42 passed,
4 failed), receipts, the earn check (grades, chips, history lines), epoch rows, the epoch page, cohorts, governance facts and
the Score's pass rate over juried answers, and (1.26.225) the settlement Paid per close split. No network. Usage: python3 tools/expired_no_jury_test.py"""
import os, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "x.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
def nodash(h): return "\u2014" not in h and "\u2013" not in h and "&mdash;" not in h and "&ndash;" not in h

import fixture; fixture.seed()
from poascan import db, outcome as O, analytics as A, receipts as RC, earn as EA, earnview as EV, cohorts as CO, govscore as GS, views as V, agents as G

J = lambda *g: [{"grader": x, "aligned": True} for x in g]
PASS = {"answer": "p" * 64, "from": "poa1P", "passed": True, "jury": J("a", "b", "c", "d")}
FAIL = {"answer": "f" * 64, "from": "poa1F", "passed": False, "jury": J("a", "b", "c", "d")}
EXP = {"answer": "e" * 64, "from": "poa1E", "passed": False, "expired": True, "losers": [], "winners": [], "jury": []}

# ---------------- the classifier ----------------
check("pass: passed", O.of(PASS) == "passed")
check("jury fail: failed", O.of(FAIL) == "failed")
check("expired with no jury: expired_no_jury", O.of(EXP) == "expired_no_jury" and O.no_jury(EXP))
check("passed false, no expired flag: a jury outcome (failed), not expired", O.of({"passed": False, "jury": []}) == "failed")
check("expired flag but jurors listed: judged, so failed", O.of(dict(FAIL, expired=True)) == "failed")
check("expired flag on a passed row: passed", O.of(dict(EXP, passed=True)) == "passed")
check("labels: Expired, no jury and the short form", O.LABEL["expired_no_jury"] == "Expired, no jury" and O.SHORT["expired_no_jury"] == "Expired")
t = O.tag("expired_no_jury", "E19", short=True)
check("short tag carries the full label as its tooltip", 'title="Expired, no jury"' in t and ">Expired · E19<" in t and "bad" not in t)
check("pass rate over juried rows", O.rate(42, 46) == 42 / 46 and O.rate(0, 0) is None)

# ---------------- the E19 close: 2,000 settled ----------------
e19 = [dict(EXP, answer=f"{i:064x}") for i in range(1954)] + [dict(PASS, answer=f"p{i:063x}") for i in range(42)] + [dict(FAIL, answer=f"f{i:063x}") for i in range(4)]
c = O.counts(e19)
check(f"E19 split: 1954 expired, 42 passed, 4 failed ({c})", c == {"passed": 42, "failed": 4, "expired_no_jury": 1954} and sum(c.values()) == 2000)

# ---------------- close records: an expired answer by A1 at the latest close ----------------
A1, A2 = fixture.A1, fixture.A2
eps = A.epochs_raw(); n = int(eps[-1]["epoch"]); TXE = "4f6168ad" + "0" * 56
db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)", (TXE, "challenge", A1, 3, int(eps[3]["ts"]) - 600, 5, 5, 1))
eps[3]["basis"]["pending"][TXE] = {"kind": "short", "panel": [], "since": 3}
eps[-1]["basis"]["settled"] += [dict(EXP, answer=TXE, **{"from": A1}), dict(FAIL, answer="fa" * 32, **{"from": A2}), dict(PASS, answer="pa" * 32, **{"from": A2})]
db.put_blob("epochs", eps); A._cache.clear()
r = next(x for x in A.epoch_rows() if x["epoch"] == n)
base = [s for s in eps[-1]["basis"]["settled"]]
check("epoch row: settled, passed, failed and expired split",
      r["settled"] == len(base) and r["settled_expired_no_jury"] == 1 and r["settled_passed"] + r["settled_failed"] + r["settled_expired_no_jury"] == r["settled"])
rc = RC.receipt(TXE)
check(f"receipt: status expired_no_jury, not failed ({rc['status']})", rc["status"] == "expired_no_jury" and rc["expired_no_jury"] is True and rc["passed"] is False and rc["basis_state"] == "settled")
check("receipt tag reads Expired, no jury with its close", f"Expired, no jury · E{n}" in RC.status_tag(rc) and "tag bad" not in RC.status_tag(rc))
check("receipt list: short Expired with the full label on hover", 'title="Expired, no jury"' in RC.list_html([rc]))

# ---------------- the earn check ----------------
mine = [dict(tx=TXE, epoch=3, segment=2, accepted=True, final=True, status="expired_no_jury", seals=0)]
row = EA.close_row(n, eps[-1], A1, mine, False)
ex = [l for l in row["lines"] if l["kind"] == "exp"]
check("history: an exp line, not a failed line", len(ex) == 1 and ex[0]["text"] == "E3 answer expired, no jury" and not any("failed grading" in l["text"] for l in row["lines"] if "E3" in l["text"]))
check("history: an expiry is not a reduction", row["cuts"] == sum(1 for l in row["lines"] if l["kind"] in ("cut", "bad", "miss")))
st2 = dict(segment=2, segments=[dict(segment=1, closes=15), dict(segment=2)])
def rcp(e, status): return dict(tx=f"{e:064x}", epoch=e, segment=2, accepted=True, final=True, status=status, seals=0)
inp = dict(address=dict(balance="0", balance_segment=2, rewards={}, wallet_binding=dict(linked=False), txs=[dict(type="challenge", ts=1, segment=2, epoch=3)]),
           standing=dict(established=False, open_epoch=5, last_close=4), receipts=[rcp(3, "expired_no_jury"), rcp(4, "failed"), rcp(5, "awaiting_close")],
           governance=dict(facts={}), established={}, status=st2)
d = EA.check(A1, inp); it = {i["key"]: i for i in d["items"]}
check(f"grades row: 1 failed, 1 expired, no jury ({it['grades']['value']})", it["grades"]["value"] == "0 passed · 1 pending · 1 failed · 1 expired, no jury")
check("grades field: failed is jury failures only", d["grades"] == dict(passed=0, failed=1, expired_no_jury=1, pending=1, pass_rate=0.0))
ch = {c["epoch"]: c for c in it["answers"]["chips"]}
check("chip: E3 Expired, no jury in its own state", ch[3]["state"] == "exp" and ch[3]["label"] == "Expired, no jury" and ch[4]["state"] == "bad")
h = EV.result(d)
check("chip renders with class exp and the label on hover", '<li class="exp" title="E3: Expired, no jury">' in h)
only = EA.check(A1, dict(inp, receipts=[rcp(3, "expired_no_jury")]))
oi = {i["key"]: i for i in only["items"]}
check("only expiries: never 'failed grading', says no jury", "failed" not in only["verdict"]["reason"] and "no jury" in only["verdict"]["reason"]
      and oi["grades"]["value"] == "0 passed · 0 pending · 0 failed · 1 expired, no jury" and only["grades"]["pass_rate"] is None)
check("its record names the expiry, not counted as failed", any("expired with no jury. Not counted as failed." in x for x in only["specific"]))

# ---------------- cohorts, governance facts, the Score ----------------
cs = CO.cohorts()
check("cohorts: six states always sum (expired_no_jury included)", all(sum(t[k] for k in CO.STATES) == c2["answers"] for c2 in cs["cohorts"] for t in c2["closes"]))
co3 = CO.one(3)
check("cohorts: the expired answer is expired_no_jury, not failed", co3 is not None and co3["closes"][-1]["expired_no_jury"] >= 1)
F, _, _ = GS.close_facts([{"epoch": 1, "basis": {"settled": [dict(EXP, **{"from": "poa1X"}), dict(FAIL, **{"from": "poa1X"}), dict(PASS, **{"from": "poa1X"}), dict(PASS, **{"from": "poa1X"})]}}])
f = F["poa1X"]
check("governance facts: settled 4, passed 2, expired_no_jury 1", f["settled"] == 4 and f["passed"] == 2 and f["expired_no_jury"] == 1)
g = dict(GS._blank(), **GS.EMPTY_TX, **GS.EMPTY_FORUM, first_close=1, closes_established=0)
s1 = GS.score(dict(g, settled=3, passed=2, expired_no_jury=0), "none", 1, 1)["standing"]
s2 = GS.score(dict(g, settled=13, passed=2, expired_no_jury=10), "none", 1, 1)["standing"]
check(f"Score: expiries never lower the pass part ({s1} == {s2})", s1 == s2)
lb = G.leaderboard()
rows = lb["by_family"]
check("leaderboard rows carry failed and expired_no_jury; pass rate over juried",
      all("expired_no_jury" in x and "failed" in x and (x["pass_rate"] is None or abs(x["pass_rate"] - x["passed"] / (x["passed"] + x["failed"])) < 1e-9) for x in rows))

# ---------------- settlement: Paid per close (1.26.225) ----------------
from poascan import govv2 as GV2
sc = next(x for x in GV2.settlement_closes() if x["close"] == n)
check(f"settlement close: paid + not paid + expired = settled, no gap ({sc['paid']}+{sc['not_paid']}+{sc['expired_no_jury']}={sc['settled']})",
      sc["expired_no_jury"] >= 1 and sc["paid"] + sc["not_paid"] + sc["expired_no_jury"] == sc["settled"])
check("settlement close: failed is jury failures only", sc["failed"] == sc["settled"] - sc["passed"] - sc["expired_no_jury"] and sc["failed"] >= 1)
check("settlement rows carry failed and not_paid", all("failed" in x and "not_paid" in x and x["paid"] + x["not_paid"] + x["expired_no_jury"] == x["settled"] for x in GV2.settlement()))
st = GV2.settlement_tab({}, lambda tab, **k: "/governance?tab=" + tab, lambda **k: "")
st = st[1] if isinstance(st, tuple) else st
tipn = f'E{n} · Paid {sc["paid"]:,} · Settled, not paid {sc["not_paid"]:,} · Expired, no jury {sc["expired_no_jury"]:,}'
check("Paid per close: an Expired, no jury segment, neutral, in legend and tooltip", tipn in st and "s-mute" in st and st.count("Expired, no jury") >= 2)
api = GV2.api_settlement()
check("settlement API: closes carry failed and not_paid", all("failed" in x and "not_paid" in x for x in api["closes"]))
check("settlement: no em or en dashes", nodash(st) and nodash(api["definitions"]))

# ---------------- pages ----------------
ep = V.epoch(n); ep = ep[1] if isinstance(ep, tuple) else ep
check("epoch page: Passed / failed / expired row", "Passed / failed / expired" in ep and f'{r["settled_passed"]:,} / {r["settled_failed"]:,} / {r["settled_expired_no_jury"]:,}' in ep)
gp = V.grading()
check("grading tab: Failed and Expired stats, three series", ">Expired<" in gp and "Expired, no jury" in gp and ">Failed<" in gp)
ab = V.about(); ab = ab[1] if isinstance(ab, tuple) else ab
check("about: one Expired, no jury section, pass rate over juried", ab.count('<h3 id="expired">Expired, no jury</h3>') == 1 and "passed over juried answers" in ab)
txt = repr(d) + repr(only) + h + ep + gp + ab + repr(O.LABEL)
check("no em or en dashes", nodash(txt) and nodash(open(os.path.join(ROOT, "poascan", "outcome.py")).read()))
check("says Agents, never Accounts", "Accounts" not in h)

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
