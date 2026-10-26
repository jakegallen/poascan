"""Governance v2 (preview/gov-v2): settlement by origin epoch per close (settled, sealed, paid, open, panel), standing
changes per close (engine fold, relisted not added, pardons honoured), Agents never established, Panel and Age on the
settle queue; header sort, CSV, API, MCP; never a pending score. Temp database, no network. Usage: python3 tools/govv2_test.py"""
import json, os, re, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ["POASCAN_SEGMENTS"] = "1"
os.environ.update(POASCAN_DB=os.path.join(tmp, "g.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import db
db.init()
now = int(time.time()); t0 = now - 4 * 21600
A, B, C, D, X = ("poa1" + c * 40 for c in "ABCDX")
aid = lambda i: f"{i:064x}"
SCORE_MARK = 2.718281828   # a pending grade score: must never appear in any output
eps = [
  {"epoch": 0, "ts": t0 + 21600, "rewards": {A: "5"}, "challenges": {A: "1"},
   "basis": {"pending": {aid(1): {"since": 0, "kind": "short", "panel": [B, C], "grades": [{"grader": B, "score": SCORE_MARK, "ts": t0}]},
                         aid(2): {"since": 0, "kind": "short", "panel": []}},
             "settled": [], "established_after": [A, B], "established_removed": [], "slashed": []}},
  {"epoch": 1, "ts": t0 + 43200, "rewards": {A: "5", B: "3"}, "challenges": {A: "1"},
   "basis": {"pending": {aid(2): {"since": 0, "kind": "short", "panel": [C]}, aid(3): {"since": 1, "kind": "short", "panel": []}},
             "settled": [{"answer": aid(1), "from": A, "passed": True, "jury": [{"grader": B, "aligned": True}]},
                         {"answer": aid(9), "from": B, "passed": True, "jury": []}],
             "established_after": [A, C], "established_removed": [B], "slashed": []}},
  {"epoch": 2, "ts": t0 + 64800, "rewards": {}, "challenges": {},
   "basis": {"pending": {aid(3): {"since": 1, "kind": "short", "panel": [A, B, C, D]}},
             "settled": [{"answer": aid(2), "from": D, "passed": False, "jury": [{"grader": A, "aligned": False}]}],
             "established_after": [], "established_removed": [C], "slashed": [C]}}]
db.put_blob("epochs", eps)
db.put_blob("params", {"K": 5, "grade_quorum": 4, "estab_ttl": 6, "slash_pardons": {"2": [C]}, "auto_epoch_seconds": 21600})
db.put_blob("status", {"epochs_closed": 3, "checkpoint_height": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))})
db.put_blob("networks", {"chains": [{"chain_id": "poa-mainnet-1", "status": "live", "default": True}]})
db.write("INSERT INTO txs(id,type,from_addr,epoch,ts,final,segment) VALUES(?,?,?,?,?,?,?)", (aid(9), "challenge", B, 0, t0 + 100, 1, 1))
db.write("INSERT INTO txs(id,type,from_addr,epoch,ts,final,segment) VALUES(?,?,?,?,?,?,?)", (aid(20), "challenge", X, 2, now - 600, 1, 1))
db.write("INSERT OR REPLACE INTO accounts(addr,balance,balance_s,api_ts,api_joined_epoch,first_seen,last_seen) VALUES(?,?,?,?,?,?,?)",
         [(a, bal, str(bal), t0 + 50, je, t0, now) for a, bal, je in ((A, 10.0, 0), (B, 3.0, 0), (C, 1.0, 1), (D, 0.5, 1), (X, 7.0, 2))], many=True)
db.put_blob("grading", {"epoch": 3, "as_of": now, "fetched_at": now, "stats": {"pending": 1}, "rollups": [{"ts": t0 + 64800}], "established": [],
                        "rows": [{"id": aid(3), "author": D, "born": 1, "since": 1, "expires": 17, "kind": "short", "raw": 2, "qual": 1, "need": 3,
                                  "grades": [{"g": A, "ts": now - 60, "t": 1, "q": 1}, {"g": B, "ts": now - 30, "t": 0, "q": 0}]},
                                 {"id": aid(7), "author": D, "born": 2, "since": 2, "expires": 18, "kind": "short", "raw": 0, "qual": 0, "need": 4, "grades": []}],
                        "open": [{"id": aid(8), "author": X, "born": 3, "since": 3, "expires": 19, "kind": "short", "raw": 0, "qual": 0, "need": 4, "grades": []}]})
from poascan import govv2 as GV2, analytics as A_, server as SV, agentapi as AG, governance as GV

# (e) settlement
S = GV2.settlement()
by = {(r["close"], r["origin"]): r for r in S}
check(f"E1: aid(1) settles under origin 0 (since in the previous close), sealed and paid ({by.get((1, 0))})",
      by[(1, 0)]["settled"] == 2 and by[(1, 0)]["sealed"] == 1 and by[(1, 0)]["passed"] == 2 and by[(1, 0)]["paid"] == 1)
check("E1: aid(9) not pending at E0 takes its archived tx epoch (0); B passed but no challenge payout: not paid", by[(1, 0)]["paid"] == 1)
check(f"E1: open rows by origin with panels ({by.get((1, 1))})", by[(1, 0)]["open"] == 1 and by[(1, 0)]["open_panel"] == 1 and by[(1, 1)]["open"] == 1 and by[(1, 1)]["open_panel"] == 0)
check(f"E2: a failed settle is settled and sealed, not paid ({by.get((2, 0))})", by[(2, 0)]["settled"] == 1 and by[(2, 0)]["sealed"] == 1 and by[(2, 0)]["paid"] == 0)
tot = {c["close"]: c for c in GV2.settlement_closes()}
check("per close totals add up", tot[1]["settled"] == 2 and tot[2]["open"] == 1 and tot[0]["open"] == 2)

# (d) standing changes
ch = {r["close"]: r for r in GV2.standing_changes()}
check(f"E0: two added, nothing removed ({ch[0]['added']}, {ch[0]['removed']}, {ch[0]['after']})", ch[0]["added"] == 2 and ch[0]["removed"] == 0 and ch[0]["after"] == 2)
check(f"E1: A relisted is not added; C added; B removed ({ch[1]})", ch[1]["added"] == 1 and ch[1]["relisted"] == 1 and ch[1]["removed"] == 1 and ch[1]["net"] == 0 and ch[1]["added_list"] == [C] and ch[1]["removed_list"] == [B])
check(f"E2: a pardoned slash removal does not count ({ch[2]['removed']}, {ch[2]['after']})", ch[2]["removed"] == 0 and ch[2]["after"] == 2)
est, _, _ = A_.established_fold()
check("the last row matches the engine fold", ch[2]["after"] == len(est))

# (c) never established
nv = {r["address"]: r for r in GV2.never_established()}
check(f"never established: D and X only (B was, then removed) ({sorted(nv)})", set(nv) == {D, X})
check(f"X: answers, last tx, joined epoch, balance ({nv[X]})", nv[X]["answers"] == 1 and nv[X]["last_ts"] == now - 600 and nv[X]["joined_epoch"] == 2 and nv[X]["balance"] == 7.0)
check("sort by balance, highest first", [r["address"] for r in GV2.never_select("balance", "desc")] == [X, D])

# (a) queue panel and age
from poascan import gradingview as GVW
q = {r["id"]: r for r in GVW.queue_select("", "panel", "desc")}
check(f"queue: panel from the last close record, age in epochs ({q[aid(3)].get('panel')}, {q[aid(3)].get('age')})", q[aid(3)]["panel"] == 4 and q[aid(3)]["age"] == 2)
check("queue: an answer not pending at the last close has no panel", q[aid(7)]["panel"] is None and q[aid(7)]["age"] == 1)
qa = SV.api("/api/governance/queue", {"sort": ["panel"]})[0]
check("queue API rows carry panel and age", all("panel" in r and "age" in r for r in qa["rows"]) and qa["rows"][0]["panel"] == 4)
qh = GV.page({"tab": ["queue"]})
check("queue page: Panel and Age headers sort", 'Panel' in qh and 'sort=panel' in qh and 'sort=age' in qh)

# pages, header sort, CSV, API, MCP
for tab in ("settlement", "changes", "never"):
    h = GV.page({"tab": [tab]})
    check(f"{tab}: renders with header sort links, CSV and API, no em or en dash",
          "sort=" in h and ".csv" in h and "/api/v1/governance/" in h and "\u2014" not in h and "\u2013" not in h)
    check(f"{tab}: never a pending score", str(SCORE_MARK) not in h)
h = GV.page({"tab": ["settlement"], "sort": ["paid"], "dir": ["asc"], "close": ["1"]})
check("settlement: sort and close filter in the URL", "close=1" in h and "E1" in h)
h = GV.page({"tab": ["changes"], "close": ["1"]})
check("changes: close=1 lists added and removed Agents", "E1 changes" in h and "Removed · 1" in h)
check("charts render (watermarked chart boxes)", 'class="chartbox' in GV.page({"tab": ["settlement"]}) and 'class="chartbox' in GV.page({"tab": ["changes"]}))
for p, qs in (("/api/governance/settlement", {"close": ["1"]}), ("/api/governance/standing-changes", {"close": ["1"]}), ("/api/governance/never-established", {})):
    d = SV.api(p, qs)[0]
    check(f"{p}: rows, total, method; never a score", d["rows"] and d["total"] >= 1 and "method" in d and str(SCORE_MARK) not in json.dumps(d, default=str))
try: SV.api("/api/governance/settlement", {"sort": ["score"]}); bad = False
except Exception as e: bad = type(e).__name__ == "BadRequest"
check("bad sort is a 400", bad)
try: SV.api("/api/governance/never-established", {"addr": ["x"]}); bad = False
except Exception as e: bad = type(e).__name__ == "BadRequest"
check("unknown parameter is a 400", bad)
names = [t[0] for t in AG.TOOLS]
check("MCP tools: get_settlement_by_origin, get_standing_changes, list_never_established", all(n in names for n in ("get_settlement_by_origin", "get_standing_changes", "list_never_established")))
fn = {t[0]: t[4] for t in AG.TOOLS}
r1 = fn["get_settlement_by_origin"]({"close": 1}); r2 = fn["get_standing_changes"]({}); r3 = fn["list_never_established"]({"sort": "balance"})
check("MCP calls answer like the API", r1["rows"] and all(r["close"] == 1 for r in r1["rows"]) and len(r2["rows"]) == 3 and r3["rows"][0]["address"] == X)
src = open(os.path.join(ROOT, "poascan", "govv2.py")).read()
check("govv2.py: no em or en dash, never reads a grade score", "\u2014" not in src and "\u2013" not in src and '"score"' not in src and "'score'" not in src)
check("UI copy says Agents, not Accounts", "Accounts" not in src)
print("all passed" if not fails else f"{len(fails)} failed"); sys.exit(1 if fails else 0)
