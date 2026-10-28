"""Grading queue board (1.26.206, Governance, Queue): birth panel coverage by closes waited, at 3 of 4, expiring within 1 to 3
closes, neutral_answer and neutral_grading per close (POAScan's replay, or the close record's own fields when present), the
API, MCP get_grading_board and the card; counts only, never a pending score. Temp database, no network.
Usage: python3 tools/board_test.py"""
import json, os, sys, tempfile, time
os.environ["POASCAN_SEGMENTS"] = "1"
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "b.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, board as BD, agentapi as AG, governance as GV, segments as SG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
SCORE = 2.718281828; T0 = int(time.time()) - 10 * 21600; W = 21600
g = lambda *xs: [{"grader": x, "score": SCORE} for x in xs]
pend = {"a" * 64: {"since": 9, "panel": ["x"], "grades": g("p", "q", "r")}, "b" * 64: {"since": 8, "panel": [], "grades": []},
        "c" * 64: {"since": 2, "panel": [], "grades": g("p")}, "d" * 64: {"since": 0, "panel": ["y"], "grades": []}}
eps = [{"epoch": n, "ts": T0 + n * W, "rewards": {}, "challenges": {}, "basis": {"pending": pend if n == 9 else {}, "settled": []}} for n in range(10)]
eps[8]["basis"]["neutral_grading"] = False   # a close record that carries the field itself
db.init(); db.put_blob("epochs", eps); db.put_blob("params", {"pending_ttl_epochs": 16, "estab_ttl": 6})
db.put_blob("status", {"epochs_closed": 10, "checkpoint_height": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
seg = SG.CURRENT; rows = []; k = 0
def tx(typ, ts):
    global k; k += 1; rows.append((f"{typ[:2]}{k:062d}", typ, "poa1x", None, ts, 1, seg))
for n in range(1, 10):
    lo = T0 + (n - 1) * W
    if n == 4: [tx("challenge", lo + 60 + i) for i in range(30)]             # all answers in the first minutes: gap about 6 h
    elif n == 5: [tx("challenge", lo + i * 3000) for i in range(7)]          # 7 answers: under 20
    else: [tx("challenge", lo + 300 + i * 700) for i in range(30)]
    for i in range(10 if n == 7 else 100): tx("grade-sealed", lo + 400 + i * 200)  # E7: 10 seals against a baseline of 100
db.write("INSERT INTO txs(id, type, from_addr, epoch, ts, final, segment) VALUES(?,?,?,?,?,?,?)", rows, many=True)
A._cache.clear()
d = BD.data()
b = {x["band"]: x for x in d["bands"]}
check("bands: waited 0 (since 9) has 1 with birth panel, 1 (since 8) none, 7 (since 2) one, 9 (since 0) one",
      b["0 to 2"]["pending"] == 2 and b["0 to 2"]["birth_panel"] == 1 and b["6 to 9"]["pending"] == 2 and b["6 to 9"]["birth_panel"] == 1 and b["0 to 2"]["coverage"] == 0.5)
check("any seal counts lists with grades", b["0 to 2"]["any_seal"] == 1 and b["6 to 9"]["any_seal"] == 1)
check("at 3 of 4 from the close record (3 graders)", d["at_three_record"] == 1)
check("expiring: since 0 + 16 = 16 is 7 closes away, so none within 3", d["expiring"] == {"next_close": 0, "within_2": 0, "within_3": 0})
c = {x["close"]: x for x in d["closes"]}
check("E4: longest gap over 3 h: neutral_answer", c[4]["neutral_answer"] and c[4]["longest_gap_s"] > 3 * 3600)
check("E5: under 20 answers: neutral_answer", c[5]["neutral_answer"] and c[5]["answers"] < 20)
check("E2, E3: normal closes", not c[2]["neutral_answer"] and not c[3]["neutral_answer"])
check("E7: 10 seals under 25% of the 100 baseline: neutral_grading", c[7]["neutral_grading"] and c[7]["baseline"] == 100)
check("E8: the record's own neutral_grading is used, source close record", c[8]["neutral_grading"] is False and c[8]["source"] == "close record")
check("E1 to E3: no baseline yet, grading unknown", not c[2]["grading_known"])
api = json.dumps(BD.api())
check("API counts only: no pending score", str(SCORE) not in api and '"score"' not in api)
tools = {t[0] for t in AG.TOOLS}
check("MCP get_grading_board listed", "get_grading_board" in tools)
h = GV.page({"tab": ["queue"]}); h = h if isinstance(h, str) else h[1]
check("Queue tab shows the board", 'id="board"' in h and "Birth panel by closes waited" in h and "neutral_grading" in h and str(SCORE) not in h)
print("FAILS:", fails) if fails else print("ALL OK")
sys.exit(1 if fails else 0)
