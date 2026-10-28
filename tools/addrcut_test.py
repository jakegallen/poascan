"""Address reads answered by the agent list (1.26.212): no minepoa.com address read while the stored agent list row is
fresh (20 min) and nothing since could have moved the balance; the balance keeps its own as-of time and source.
Temp database, no network. Usage: python3 tools/addrcut_test.py"""
import json, os, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "a.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, views as V, indexer as I, segments as SG, server as S

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
ad = lambda i: "poa1" + format(i, "040d").replace("0", "Q")
NOW = int(time.time()); seg = SG.CURRENT
db.init()
db.put_blob("epochs", [{"epoch": 0, "ts": NOW - 7200, "rewards": {}, "basis": {}}])
calls = []
def fake(path, ep, a):
    calls.append(a); return {"balance": "7.000000", "txs": [], "balance_as_of": {"checkpoint_height": 5}}
I.fetch_ondemand = fake
def acc(a, bal, seen): db.write("INSERT OR REPLACE INTO accounts(addr, balance, balance_s, last_seen, first_seen) VALUES(?,?,?,?,?)", (a, float(bal), bal, seen, seen))
acc(ad(1), "5.000000", NOW - 300); acc(ad(2), "5.000000", NOW - 3000); acc(ad(3), "5.000000", NOW - 300); acc(ad(4), "5.000000", NOW - 300)
db.write("INSERT INTO txs(id, type, from_addr, to_addr, amount, ts, final, segment) VALUES(?,?,?,?,?,?,?,?)", ("1" * 64, "transfer", ad(9), ad(3), "2", NOW - 100, 1, seg))
db.write("INSERT INTO txs(id, type, from_addr, to_addr, amount, ts, final, segment) VALUES(?,?,?,?,?,?,?,?)", ("2" * 64, "challenge", ad(4), None, None, NOW - 100, 1, seg))
A._cache.clear()
d, err, at = V.address_read(ad(1))
check("fresh agent list row, nothing since: no address read", (d, err, at) == (None, None, None) and ad(1) not in calls)
bb = V.address_balance(ad(1), d, at)
check("balance from the agent list with its own as-of and source", bb["balance"] == "5.000000" and bb["source"] == "agents" and bb["as_of"] == NOW - 300 and not bb["stale"])
V.address_read(ad(2)); check("agent list row older than 20 min: reads", ad(2) in calls)
V.address_read(ad(3)); check("a transfer to the address since the row: reads", ad(3) in calls)
V.address_read(ad(4)); check("an answer tx is not value moving: no read", ad(4) not in calls)
V.address_read(ad(5)); check("no agent list row: reads", ad(5) in calls)
db.put_blob("epochs", [{"epoch": 0, "ts": NOW - 7200, "rewards": {}, "basis": {}}, {"epoch": 1, "ts": NOW - 60, "rewards": {}, "basis": {}}]); A._cache.clear()
n0 = len(calls); V.address_read(ad(1)); check("a close since the row: reads", len(calls) == n0 + 1 and calls[-1] == ad(1))
n1 = len(calls); V.address_read(ad(1)); check("then the cached read answers (no second read)", len(calls) == n1)
r, _ = S.api("/api/address/" + ad(4), {})
check("API: balance, balance_as_of and balance_source kept", r["balance"] == "5.000000" and r["balance_source"] == "agents" and r["balance_as_of"] == NOW - 300)
h, _ = S.api("/api/health", {})
check("health counts address reads answered by the agent list", h["address_reads"]["agent_list"] >= 2 and h["address_reads"]["agent_list_fresh_s"] == 1200)
src = open(V.__file__).read(); i = src.index("ROSTER_FRESH_S = "); seg_src = src[i:src.index("def fetch_address")]
check("no dashes in new copy", "\u2014" not in seg_src and "\u2013" not in seg_src)
print("ALL OK" if not fails else f"{len(fails)} FAILED: {fails}"); sys.exit(1 if fails else 0)
