"""Records and firsts (1.26.207, Network, Records): records for 24 h, 7 days and the segment from final txs and close records,
firsts, the tab, /api/v1/highlights and MCP get_highlights. Temp database, no network. Usage: python3 tools/highlights_test.py"""
import json, os, sys, tempfile, time
os.environ["POASCAN_SEGMENTS"] = "1"
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "h.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, highlights as HL, agentapi as AG, views as V, segments as SG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
NOW = int(time.time()); D = 86400; ad = lambda i: "poa1" + format(i, "040d").replace("0", "Q")
eps = [{"epoch": 0, "ts": NOW - 10 * D, "rewards": {ad(1): "900.0", ad(2): "5.0"}, "basis": {"settled": [{}] * 9, "graders_served": {ad(3): 40}}},
       {"epoch": 1, "ts": NOW - 3 * D, "rewards": {ad(1): "100.0", ad(2): "50.0", ad(4): "1.0"}, "basis": {"settled": [{}] * 2, "graders_served": {ad(5): 7}}},
       {"epoch": 2, "ts": NOW - 3600, "rewards": {ad(6): "20.0"}, "basis": {"settled": [{}], "graders_served": {}}}]
db.init(); db.put_blob("epochs", eps); db.put_blob("params", {"pending_ttl_epochs": 16})
db.put_blob("status", {"epochs_closed": 3, "checkpoint_height": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW))})
seg = SG.CURRENT; rows = []
def tx(i, typ, ts, frm, amount=None, epoch=None, to=None): rows.append((f"{i:064d}", typ, frm, to, amount, epoch, ts, 1, seg))
tx(1, "transfer", NOW - 9 * D, ad(1), "5000", to=ad(2)); tx(2, "transfer", NOW - 2 * D, ad(2), "300", to=ad(3)); tx(3, "transfer", NOW - 600, ad(3), "7", to=ad(1))
tx(4, "join", NOW - 9 * D, ad(1)); tx(5, "join", NOW - 9 * D + 5, ad(2))
for i in range(5): tx(10 + i, "grade-sealed", NOW - 1200 + i, ad(5))
tx(20, "challenge", NOW - 9 * D, ad(1), epoch=0); tx(21, "challenge", NOW - 1000, ad(6), epoch=3)
db.write("INSERT INTO txs(id, type, from_addr, to_addr, amount, epoch, ts, final, segment) VALUES(?,?,?,?,?,?,?,?,?)", rows, many=True)
A._cache.clear()
d = HL.data(); P = d["periods"]
check("largest transfer: 7 in 24 h, 300 in 7 days, 5,000 in the segment", [P[k]["records"]["transfer"]["value"] for k in ("day", "week", "ever")] == [7.0, 300.0, 5000.0])
check("largest reward: 20 in 24 h, 100 in 7 days, 900 ever, with who and close", P["day"]["records"]["reward"]["value"] == 20 and P["week"]["records"]["reward"]["value"] == 100
      and P["ever"]["records"]["reward"]["who"] == ad(1) and P["ever"]["records"]["reward"]["close"] == 0)
check("most paid at a close: 3 (E1) in 7 days", P["week"]["records"]["paid"]["value"] == 3 and P["week"]["records"]["paid"]["close"] == 1)
check("most settled ever 9, seats served ever 40", P["ever"]["records"]["settled"]["value"] == 9 and P["ever"]["records"]["served"]["value"] == 40)
check("most seals by one Agent in 24 h: 5", P["day"]["records"]["seals_by_one"]["value"] == 5 and P["day"]["records"]["seals_by_one"]["who"] == ad(5))
check("most joins in one day: 2", P["ever"]["records"]["join_day"]["value"] == 2)
f = {x["key"]: x for x in d["firsts"]}
check("firsts: first answer, first join, first answer of open epoch E3, first seal after the E2 close",
      f["first_answer"]["who"] == ad(1) and f["first_join"]["who"] == ad(1) and f["open_answer"]["who"] == ad(6) and f["close_seal"]["found"])
h = V.network("records"); h = h if isinstance(h, str) else h[1]
check("Network, Records tab renders both cards and the chip", 'id="records"' in h and 'id="firsts"' in h and "?tab=records" in h)
check("MCP get_highlights listed", "get_highlights" in {t[0] for t in AG.TOOLS})
check("neutral wording: no accusatory words", not any(w in h.lower() for w in ("suspicious", "abuse", "cheat", "farm", "sybil")))
print("FAILS:", fails) if fails else print("ALL OK")
sys.exit(1 if fails else 0)
