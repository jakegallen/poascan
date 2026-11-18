"""Agent totals (POASCAN data ask 3a): agents = chain account count (status agents_joined), archive_agents = distinct
addresses in POAScan's archive; both exposed on /api/v1/agents/health and a dedicated /api/v1/agents/totals. Counts only.
Usage: python3 tools/agent_totals_test.py (temp database, no network)."""
import os, sys, tempfile
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, agents as G

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

db.init()
db.put_blob("status", {"agents_joined": 5})
db.write("INSERT INTO accounts(addr,balance,first_seen) VALUES(?,?,0)",
         [("poa1" + c * 40, 0) for c in "ABCDEFG"], many=True)   # 7 archive addresses
A._cache.clear()
t = G.agent_totals()
check("agents is the chain account count (status agents_joined)", t["agents"] == 5)
check("archive_agents is every address in the archive", t["archive_agents"] == 7)
check("dropped_at_cut is archive minus chain", t["dropped_at_cut"] == 2)
check("both labelled with a basis", t["agents_basis"] and t["archive_basis"])

h = G.network_health()
check("network_health carries agents + archive_agents", h.get("agents") == 5 and h.get("archive_agents") == 7)

src = open(os.path.join(ROOT, "poascan", "server.py")).read()
check("server routes /api/agents/totals to agent_totals (additive, new route)", '"/api/agents/totals"' in src and "G.agent_totals()" in src)
check("agent_totals reads local data only (no upstream fetch)",
      "fetch(" not in open(os.path.join(ROOT, "poascan", "agents.py")).read().split("def agent_totals(")[1].split("\ndef ")[0])

# 3c: hourly joins (join-memo txs) and established adds (established_after per close, at the close hour)
import time as _t
H = (int(_t.time()) // 3600) * 3600
db.write("INSERT INTO labels(addr,source,ts) VALUES(?,?,?)",
         [("x1", "join memo", H + 10), ("x2", "join memo", H + 20), ("x3", "join memo", H - 3600 + 10)], many=True)
A.epoch_rows = lambda: [dict(close_ts=H + 10, established=3), dict(close_ts=H - 3600 + 10, established=1)]
A._cache.clear()
hr = A.agents_hourly(168)
jh = {h: n for h, n in hr["joins"]}; eh = {h: n for h, n in hr["established"]}
check("3c joins bucketed per UTC hour", jh.get(H) == 2 and jh.get(H - 3600) == 1)
check("3c established bucketed at the close hour", eh.get(H) == 3 and eh.get(H - 3600) == 1)
check("server routes /api/agents/hourly to agents_hourly", '"/api/agents/hourly"' in src and "A.agents_hourly(" in src)

# 3b: per-close rank snapshot with a prior-close rank. Drive it off a controllable close epoch + metric values.
_CE = [100]
G._latest_close_epoch = lambda: _CE[0]
vals = {"earnings": {"poaAAA": 50.0, "poaBBB": 30.0, "poaCCC": 10.0}}
G._rank_values = lambda metric: dict(vals.get(metric, {}))
G._names = lambda: {"poaBBB": "bravo"}

r1 = G.agent_rank("earnings", 20)   # first read at close 100 -> snapshot taken
check("3b ranks high value first", [x["address"] for x in r1["rows"]] == ["poaAAA", "poaBBB", "poaCCC"])
check("3b rank is 1-based", r1["rows"][0]["rank"] == 1 and r1["rows"][2]["rank"] == 3)
check("3b no prior rank on the first close", all(x["prev_rank"] is None for x in r1["rows"]))
check("3b resolves a name when known", r1["rows"][1]["name"] == "bravo" and r1["rows"][0]["name"] is None)
check("3b reports close + metric list", r1["close_epoch"] == 100 and "earnings" in r1["metrics"])

_CE[0] = 101   # new close, order shuffled: CCC jumps above BBB
vals["earnings"] = {"poaAAA": 50.0, "poaCCC": 40.0, "poaBBB": 30.0}
r2 = G.agent_rank("earnings", 20)
pr = {x["address"]: x["prev_rank"] for x in r2["rows"]}
check("3b prev_rank comes from the prior close", pr["poaCCC"] == 3 and pr["poaBBB"] == 2 and pr["poaAAA"] == 1)
check("3b current order reflects the new close", [x["address"] for x in r2["rows"]] == ["poaAAA", "poaCCC", "poaBBB"])

check("3b zero-value addresses are left off the board",
      not any(x["address"] == "poaZZZ" for x in G.agent_rank("earnings", 20)["rows"]))  # poaZZZ never added

for e in range(102, 115):   # advance 13 more closes -> prune keeps only the last 8
    _CE[0] = e; G.agent_rank("earnings", 5)
closes = sorted({row["close_epoch"] for row in db.q("SELECT DISTINCT close_epoch FROM agent_rank_snap WHERE metric='earnings'")})
check("3b prunes to the last 8 closes", len(closes) == 8 and min(closes) == 107 and max(closes) == 114)

check("3b unknown metric falls back to earnings", G.agent_rank("bogus", 5)["metric"] == "earnings")
check("3b limit is clamped to >=1", len(G.agent_rank("earnings", 0)["rows"]) >= 1)
check("server routes /api/agents/rank to agent_rank", '"/api/agents/rank"' in src and "G.agent_rank(" in src)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
