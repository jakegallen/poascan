"""Settle age (1.26.251): the network-wide spread of answer age at settlement (settle close minus origin epoch), juried
answers by age band with expired-with-no-jury and unknown-origin reported apart; the Governance tab, API, CSV, MCP
get_settle_age, OpenAPI, llms.txt and /about#settle-age; never a pending score. Usage: python3 tools/settleage_test.py
(temp database, no network)."""
import json, os, sys, tempfile, time
os.environ["POASCAN_SEGMENTS"] = "1"
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "sa.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, settleage as SA, governance as GV, agentapi as AG, server as SV, views as V

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NOW = int(time.time()); SCORE_MARK = 2.718281828
# one settled row and one pending row. origin comes from the previous close's pending `since` (govv2.settlement), so the
# age of each settled answer is the settle close minus that since.
SET = lambda aid, passed=True, jury=True, expired=False: {"answer": aid, "passed": passed, "jury": (["g"] if jury else []), "expired": expired, "from": aid}
P = lambda since, sc=None: {"since": since, "panel": [], "grades": ([{"grader": "g", "score": sc, "ts": NOW}] if sc is not None else [])}
rec = lambda n, settled, pending: {"epoch": n, "ts": NOW - (5 - n) * 21600, "rewards": {}, "challenges": {},
    "basis": {"settled": settled, "pending": pending, "established_after": [], "established_removed": [], "challenge_eligible": []}}
# E0 origins (since 0); PX carries a pending score sentinel that must never surface. E1 settles A, B (juried) and C (expired,
# no jury), all age 1; E2 settles D (age 2), E (age 1) and U (not in the prior pending: unknown origin).
eps = [rec(0, [], {"A": P(0), "B": P(0), "C": P(0), "PX": P(0, SCORE_MARK)}),
       rec(1, [SET("A", True, True), SET("B", False, True), SET("C", False, False, expired=True)], {"D": P(0), "E": P(1)}),
       rec(2, [SET("D", True, True), SET("E", True, True), SET("U", True, True)], {})]
db.init(); db.put_blob("epochs", eps)
db.put_blob("params", {"auto_epoch_seconds": 21600, "estab_ttl": 6, "pending_ttl_epochs": 16})
db.put_blob("status", {"epochs_closed": 3, "checkpoint_height": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW))})
A._cache.clear()

d = SA.distribution()
check(f"spread: 6 settled, 4 juried, 1 expired, 1 unknown, median age 1 ({ {k: d[k] for k in ('settled', 'juried', 'expired', 'unknown', 'median', 'closes')} })",
      d["settled"] == 6 and d["juried"] == 4 and d["expired"] == 1 and d["unknown"] == 1 and d["median"] == 1.0 and d["closes"] == 3)
bands = {b["band"]: b["answers"] for b in d["bands"]}
check(f"age bands: three juried at age 1, one at age 2-3, none elsewhere ({bands})",
      bands["1"] == 3 and bands["2-3"] == 1 and bands["0"] == 0 and bands["4-7"] == 0 and bands["8-15"] == 0 and bands["16+"] == 0)
check("first close recorded, no genesis import in this fixture", d["first_close"] == 0 and d["genesis_import"] is False and d["pending_ttl"] == 16)

# the tab
h = GV.page({"tab": ["settleage"]})
check("Governance has a Settle age tab", ">Settle age</a>" in h and 'id="settleage"' in h)
check("stat cards: Settled, Median age, Expired no jury, Unknown origin", all(f">{w}<" in h for w in ("Settled", "Median age", "Expired, no jury", "Unknown origin")))
check("chart and sortable table: Age band labels, Share column, sort link", all(w in h for w in ("Answers by age", ">Age<", ">Answers<", ">Share<", ">2-3<")) and "sort=answers" in h)
hs = GV.page({"tab": ["settleage"], "sort": ["answers"], "dir": ["asc"]})
check("table sorts by answers, reversed with dir=asc (the 2-3 band, one answer, before the 1 band, three)",
      hs.split('id="settleage"')[1].index(">2-3<") < hs.split('id="settleage"')[1].index(">1<"))
check("no em or en dash, no Accounts, no pending score", "\u2014" not in h and "\u2013" not in h and "Accounts" not in h and str(SCORE_MARK) not in h)

# API, CSV, MCP
r = SV.governance_api("/api/governance/settle-age", {})
check("API: segment, bands as rows, totals apart, method and url",
      r["total"] == 6 and len(r["rows"]) == 6 and r["expired_no_jury"] == 1 and r["unknown"] == 1 and r["juried"] == 4 and r["settled"] == 6
      and r["median_age_epochs"] == 1.0 and r["method"].endswith("/about#settle-age") and r["url"].endswith("tab=settleage"))
rb = {b["band"]: b["answers"] for b in r["rows"]}
check("API rows carry band, answers and share", rb["1"] == 3 and rb["2-3"] == 1 and all(set(x) >= {"band", "lo", "hi", "answers", "share"} for x in r["rows"]))
for bad in ({"sort": ["bogus"]}, {"dir": ["x"]}, {"close": ["1"]}, {"x": ["1"]}):
    try: SV.governance_api("/api/governance/settle-age", bad); ok = False
    except SV.BadRequest: ok = True
    check(f"API 400 on {bad}", ok)
check("API text: no pending score", str(SCORE_MARK) not in json.dumps(r))
cs = SV.to_csv(r["rows"])
check("CSV: flat band rows", cs.splitlines()[0].startswith("band,lo,hi,answers,share") and len([l for l in cs.splitlines() if l]) == 7)
src = open(os.path.join(ROOT, "poascan", "server.py")).read()
check("CSV route takes the settle-age rows", '"/api/governance/settle-age", "/api/governance/intake"' in src)
rt = AG.TOOL_FN["get_settle_age"]({})
tl = {t["name"]: t for t in AG.tools_list()}
check("MCP get_settle_age answers like the API", rt["total"] == 6 and rt["juried"] == 4 and "get_settle_age" in tl and "Use it" in tl["get_settle_age"]["description"])
check("OpenAPI and llms.txt", "/api/governance/settle-age" in json.dumps(AG.openapi()) and "get_settle_age" in AG.llms_txt())
ab = V.about()
check("/about#settle-age explains the view", 'id="settle-age"' in ab and all(w in ab for w in ("Settle age", "origin epoch", "expired", "unknown")))
s = open(os.path.join(ROOT, "poascan", "settleage.py")).read()
check("settleage.py: no em or en dash, no Accounts, never reads pending or a score literal", "\u2014" not in s and "\u2013" not in s and "Accounts" not in s and '"pending"' not in s and '"score"' not in s)
print("all passed" if not fails else f"{len(fails)} failed"); sys.exit(1 if fails else 0)
