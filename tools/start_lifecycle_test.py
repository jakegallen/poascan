"""Start section data asks: 7a GET /api/v1/agents/{addr}/lifecycle (stage + joined/first-answer/first-seal/first-payout,
archive only, 404 on unknown/malformed) and 7b GET /api/v1/agents/joiners (joins per hour + median seconds to first pass
and first payout for recent joiners). Counts/medians only, no upstream. Usage: python3 tools/start_lifecycle_test.py."""
import os, sys, tempfile, time
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, agents as G, analytics as A
db.init()

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

now = int(time.time()); day = 86400
AAA = "poa1" + "A" * 40; BBB = "poa1" + "B" * 40; CCC = "poa1" + "C" * 40
db.write("INSERT INTO txs(id,type,from_addr,ts) VALUES(?,?,?,?)", [
    ("j1", "join", AAA, now - 6 * day), ("c1", "challenge", AAA, now - 6 * day + 3600),
    ("s1", "grade-sealed", AAA, now - 6 * day + 7200), ("j2", "join", BBB, now - 5 * day)], many=True)
G.accounts_all = lambda: {AAA: {}, BBB: {}}
G.record_agents = lambda: frozenset()
A.segment_closes = lambda n: [dict(ts=now - 6 * day + 10000, rewards={AAA: 5.0})]

# ---- 7a lifecycle ----
lc = G.agent_lifecycle(AAA)
check("7a stage is paid when a payout exists", lc["stage"] == "paid")
check("7a joined_ts from the first join tx", lc["joined_ts"] == now - 6 * day)
check("7a first_answer_ts from the first challenge tx", lc["first_answer_ts"] == now - 6 * day + 3600)
check("7a first_seal_ts from the first grade-sealed tx", lc["first_seal_ts"] == now - 6 * day + 7200)
check("7a first_payout_ts from the earliest paying close", lc["first_payout_ts"] == now - 6 * day + 10000)
check("7a malformed address returns badaddr sentinel", G.agent_lifecycle("not-an-addr") == "badaddr")
G.accounts_all = lambda: {}
check("7a unknown address with no footprint returns None (route 404s)", G.agent_lifecycle(CCC) is None)
G.accounts_all = lambda: {AAA: {}, BBB: {}}

# ---- 7b joiners ----
A.epoch_rows = lambda: [dict(epoch=5, close_ts=now - 6 * day + 5000)]
G.settled_records = lambda: [(5, "ans", AAA, True, [], "passed")]
G.settled_index = lambda: ({AAA: [0]}, {})
A._cache.clear()
j = G.joiners(7)
check("7b counts the joiners in the window", j["joiners"] == 2)
check("7b median seconds to first pass = pass close ts minus join ts", j["median_s_to_first_pass"] == 5000)
check("7b median seconds to first pay = payout ts minus join ts", j["median_s_to_first_pay"] == 10000)
check("7b reached_first_pass counts only joiners who passed", j["reached_first_pass"] == 1)
check("7b joins_per_hour buckets sum to the joiner count", sum(n for _h, n in j["joins_per_hour"]) == 2)

srv = open(os.path.join(ROOT, "poascan", "server.py")).read()
check("server routes /api/agents/joiners to G.joiners", '"/api/agents/joiners"' in srv and "G.joiners(" in srv)
check("server routes agents/{addr}/lifecycle to G.agent_lifecycle", "/lifecycle$" in srv and "G.agent_lifecycle(" in srv)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
