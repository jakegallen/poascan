"""Intake per close (1.26.189, LabLeak post 1582 and comment 6193): Set, Eligible, Cap, Admitted, Not admitted, Door and the
draw Check from the close records via the engine fold; the Eligible, not admitted state per Agent with its draw place; Agent
cells link to LabLeak profiles; Proposal L's intake params when /api/params carries them; header sort; API, CSV, MCP
get_intake, OpenAPI, llms.txt, /about#intake; never a pending score. Usage: python3 tools/intake_test.py (temp database, no network)."""
import hashlib, json, math, os, sys, tempfile, time
os.environ["POASCAN_SEGMENTS"] = "1"
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "i.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, intake as IK, governance as GV, agentapi as AG, server as SV, views as V

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NOW = int(time.time()); SCORE_MARK = 2.718281828
ad = lambda i: "poa1" + format(i, "040d").replace("0", "Q")   # distinct valid looking addresses
EST0 = [ad(i) for i in range(1, 61)]                  # 60 established at E0 (cap max(5, ceil(6.0)) = 6 at E1)
CAND = [ad(i) for i in range(100, 130)]               # 30 candidates
draw = lambda xs, n: sorted(xs, key=lambda a: hashlib.sha256(f"intake:{a}:{n}".encode()).hexdigest())
adm1 = draw(CAND, 1)[:6]                              # the engine's pick at E1
adm2 = [ad(200)]                                      # E2: one eligible, door open
bad3 = draw(CAND[10:], 3)[-6:]                        # E3: the last 6 in the order, so Check says Differs
rec = lambda n, ce, ea, er=(), slashed=(): {"epoch": n, "ts": NOW - (5 - n) * 21600, "rewards": {}, "challenges": {},
    "basis": {"challenge_eligible": list(ce), "established_after": list(ea), "established_removed": list(er), "slashed": list(slashed),
              "pending": {"p1": {"since": n, "kind": "short", "panel": [], "grades": [{"grader": EST0[0], "score": SCORE_MARK, "ts": NOW}]}}, "settled": []}}
eps = [rec(0, [], EST0), rec(1, CAND + EST0[:3], adm1), rec(2, [ad(200)], adm2, er=EST0[:2]), rec(3, CAND[10:] + [ad(300)], bad3 + [ad(301)])]
db.init(); db.put_blob("epochs", eps)
db.put_blob("params", {"auto_epoch_seconds": 21600, "estab_ttl": 6, "pending_ttl_epochs": 16})
db.put_blob("status", {"epochs_closed": 4, "checkpoint_height": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW))})
db.write("INSERT INTO forum_posts(id, author, author_public_id, title, body, created_at) VALUES(?,?,?,?,?,?)", (1, "Cinderwren", adm1[0], "t", "b", "2026-10-26 10:00:00"))
A._cache.clear()

c = {r["close"]: r for r in IK.closes()}
check("E0: admissions with nobody eligible read Differs", c[0]["eligible"] == 0 and c[0]["admitted"] == 60 and c[0]["check"] == "differs")
check(f"E1: Set 60, Eligible 30 (already established Agents left out), Cap 6, Admitted 6, Not admitted 24, Binding ({ {k: v for k, v in c[1].items() if k != 'rows'} })",
      c[1]["established_before"] == 60 and c[1]["eligible"] == 30 and c[1]["cap"] == 6 and c[1]["admitted"] == 6 and c[1]["not_admitted"] == 24 and c[1]["door"] == "binding")
check("E1: the first Cap Agents in sha256('intake:' + address + ':' + close) order are the admitted: Match", c[1]["check"] == "match")
rk = {r["address"]: r for r in c[1]["rows"]}
check("E1: every eligible Agent has its draw place; admitted are places 1 to 6", sorted(r["draw"] for r in c[1]["rows"]) == list(range(1, 31)) and all(rk[a]["draw"] <= 6 and rk[a]["state"] == "admitted" for a in adm1))
check("E1: Eligible, not admitted state for the rest", sum(1 for r in c[1]["rows"] if r["state"] == "not_admitted") == 24 and all(r["draw"] > 6 for r in c[1]["rows"] if r["state"] == "not_admitted"))
check("E2: Set 66, Cap 7 (ceil 6.6), one eligible: Open door, Match", c[2]["established_before"] == 66 and c[2]["cap"] == 7 and c[2]["door"] == "open" and c[2]["check"] == "match" and c[2]["not_admitted"] == 0)
check("E3: removals at E2 shrink the Set (67 - 2 = 65), Cap 7", c[3]["established_before"] == 65 and c[3]["cap"] == 7)
check("E3: admitted Agents that are not first in the draw: Check Differs", c[3]["check"] == "differs")
st3 = {r["address"]: r["state"] for r in c[3]["rows"]}
check("E3: an Agent in established_after without challenge_eligible is Admitted, not eligible", st3.get(ad(301)) == "admitted_unlisted" and st3.get(ad(300)) == "not_admitted")
check("cap: max(floor, ceil(rate x set))", IK.cap_of(99) == 10 and IK.cap_of(109) == 11 and IK.cap_of(20) == 5 and IK.cap_of(84) == 9 and IK.cap_of(100, 100, 0.5) == 100)

# Proposal L params: used when they explain the draw, or from estab_intake_from_epoch
db.put_blob("params", {"auto_epoch_seconds": 21600, "estab_intake_floor": 100, "estab_intake_rate": 0.5, "estab_intake_from_epoch": 3})
A._cache.clear(); c2 = {r["close"]: r for r in IK.closes()}
check("params with from_epoch 3: E1 keeps the engine default, E3 reads floor 100", c2[1]["cap"] == 6 and c2[1]["cap_basis"].startswith("engine") and c2[3]["cap"] == 100 and c2[3]["cap_basis"].startswith("params"))
db.put_blob("params", {"auto_epoch_seconds": 21600, "estab_intake_floor": 100, "estab_intake_rate": 0.5})
A._cache.clear(); c3 = {r["close"]: r for r in IK.closes()}
check("params without from_epoch: the rule the draw confirms (E1 engine default, still Match)", c3[1]["cap"] == 6 and c3[1]["check"] == "match")
db.put_blob("params", {"auto_epoch_seconds": 21600, "estab_ttl": 6}); A._cache.clear()

# the tab
h = GV.page({"tab": ["intake"]})
check("Governance has an Intake tab", '>Intake</a>' in h and 'id="intake"' in h and 'id="intake-list"' in h)
check("stat cards: Eligible, Cap, Admitted, Not admitted, latest close with intake (E3), no sub-lines", all(f">{w}<" in h for w in ("Eligible", "Cap", "Admitted", "Not admitted")) and 'class="ss"' not in h)
check("per close table: terse sortable headers, Binding, Match and Differs", all(w in h for w in ("Close", "Set", "Door", "Check", "Binding", ">Match<", ">Differs<")) and "sort=eligible" in h)
h1 = GV.page({"tab": ["intake"], "close": ["1"]})
check("E1 Agents: Admitted and Eligible, not admitted tags, draw places, state chips", "E1 intake · 6 of 30, cap 6" in h1 and h1.count(">Eligible, not admitted<") >= 24 and ">Admitted<" in h1 and "state=not_admitted" in h1)
check("Agent cell links a named Agent to its LabLeak profile", f'href="https://minepoa.com/lableak/#/u/{adm1[0]}"' in h1 and ">Cinderwren<" in h1)
hn = GV.page({"tab": ["intake"], "close": ["1"], "state": ["not_admitted"]})
check("state filter: only Eligible, not admitted", ">Admitted</span>" not in hn.split('id="intake-list"')[1] and hn.split('id="intake-list"')[1].count(">Eligible, not admitted</span>") == 24)
import poascan.intake as _IK
_IK.PAGE = 10
hp = GV.page({"tab": ["intake"], "close": ["1"]}).split('id="intake-list"')[1]
hp2 = GV.page({"tab": ["intake"], "close": ["1"], "apage": ["3"]}).split('id="intake-list"')[1]
check("Agents list pages (10 a page here): page 1 of 3, More keeps close and sort", "Page 1 of 3" in hp and "apage=2" in hp and "Page 3 of 3" in hp2 and draw(CAND, 1)[29] in hp2 and draw(CAND, 1)[29] not in hp)
_IK.PAGE = 100
hs = GV.page({"tab": ["intake"], "close": ["1"], "asort": ["draw"], "adir": ["asc"]})
lst = hs.split('id="intake-list"')[1]
check("Agents sort by draw, reversed with adir=asc (place 30 first)", lst.index(draw(CAND, 1)[29]) < lst.index(draw(CAND, 1)[0]))
hc = GV.page({"tab": ["intake"], "sort": ["not_admitted"]})
tb = hc.split('id="intake"')[1].split("</table>")[0]
check("closes sort by Not admitted (E1 first)", tb.index(">E1<") < tb.index(">E2<"))
check("no em or en dash, no Accounts, no pending score", "\u2014" not in h1 and "\u2013" not in h1 and "Accounts" not in h1 and str(SCORE_MARK) not in h1)

# API, CSV, MCP
d = SV.governance_api("/api/governance/intake", {})
check("API per close rows, newest first, no Agent lists", [r["close"] for r in d["rows"]] == [3, 2, 1, 0] and "rows" not in d["rows"][0] and d["method"].endswith("/about#intake") and d["sources"][1]["comment"] == 6193)
d1 = SV.governance_api("/api/governance/intake", {"close": ["1"], "state": ["not_admitted"]})
check("API close=1&state=not_admitted: 24 Agents with draw and summary", d1["total"] == 24 and d1["summary"]["cap"] == 6 and all(r["state"] == "not_admitted" and r["draw"] > 6 for r in d1["rows"]))
d2 = SV.governance_api("/api/governance/intake", {"close": ["1"], "sort": ["name"]})
check("API close=1: profile for named Agents only", sum(1 for r in d2["rows"] if r["profile"]) == 1)
for bad in ({"state": ["admitted"]}, {"close": ["1"], "state": ["x"]}, {"sort": ["draw"]}, {"close": ["1"], "sort": ["cap"]}, {"x": ["1"]}):
    try: SV.governance_api("/api/governance/intake", bad); ok = False
    except SV.BadRequest: ok = True
    check(f"API 400 on {bad}", ok)
check("API unknown close: found false", SV.governance_api("/api/governance/intake", {"close": ["99"]})["found"] is False)
cs = SV.to_csv(d["rows"]); cs1 = SV.to_csv(d1["rows"])
check("CSV: per close and per Agent rows, flat", cs.splitlines()[0].startswith("close,close_ts,established_before,eligible,cap") and cs.count("\n") == 5 and cs1.splitlines()[0].startswith("address,state,draw") and cs1.count("\n") == 25)
src = open(os.path.join(ROOT, "poascan", "server.py")).read()
check("CSV route takes the intake rows", '"/api/governance/intake", "/api/protocol")' in src)
r = AG.TOOL_FN["get_intake"]({"close": 1, "state": "not_admitted"})
tl = {t["name"]: t for t in AG.tools_list()}
check("MCP get_intake answers like the API", r["total"] == 24 and "get_intake" in tl and "Use it" in tl["get_intake"]["description"] and AG.TOOL_FN["get_intake"]({})["total"] == 4)
check("OpenAPI and llms.txt", "/api/v1/governance/intake" in json.dumps(AG.openapi()) and "get_intake" in AG.llms_txt())
ab = V.about()
check("/about#intake defines every column and the draw", 'id="intake"' in ab and all(w in ab for w in ("<b>Set</b>", "<b>Cap</b>", "<b>Draw</b>", "<b>Check</b>", "Eligible, not admitted", "estab_intake_floor")))
check("API text: no pending score", str(SCORE_MARK) not in json.dumps(d1) and str(SCORE_MARK) not in json.dumps(d))
s = open(os.path.join(ROOT, "poascan", "intake.py")).read()
check("intake.py: no em or en dash, no Accounts, never reads pending or a score", "\u2014" not in s and "\u2013" not in s and "Accounts" not in s and '"pending"' not in s and '"score"' not in s)
print("all passed" if not fails else f"{len(fails)} failed"); sys.exit(1 if fails else 0)
