"""Agent profile v2 timeline (1.26.213): milestones from final txs and close records, the address page Timeline tab,
/api/v1/address/<a>/timeline and MCP get_agent_timeline. Temp database, no network. Usage: python3 tools/timeline_test.py"""
import json, os, re, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, timeline as TL, agentapi as AG, views as V, segments as SG, server as S

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
ad = lambda i: "poa1" + format(i, "040d").replace("0", "Q")
NOW = int(time.time()); D = 86400; seg = SG.CURRENT; a = ad(1)
db.init()
db.put_blob("epochs", [{"epoch": 0, "ts": NOW - 5 * D, "rewards": {a: "0"}, "basis": {}},
                       {"epoch": 1, "ts": NOW - 4 * D, "rewards": {a: "10.5"}, "basis": {"established_after": [a]}},
                       {"epoch": 2, "ts": NOW - 3 * D, "rewards": {a: "40"}, "basis": {}},
                       {"epoch": 3, "ts": NOW - 2 * D, "rewards": {a: "5"}, "basis": {"established_removed": [a]}}])
db.put_blob("status", {"epochs_closed": 4, "checkpoint_height": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW))})
rows = [("a" * 64, "join", a, None, None, None, NOW - 6 * D, 1, seg), ("b" * 64, "challenge", a, None, None, 0, NOW - 6 * D + 60, 1, seg),
        ("c" * 64, "challenge", a, None, None, 1, NOW - 5 * D, 1, seg), ("d" * 64, "grade-sealed", a, None, None, None, NOW - 5 * D + 9, 1, seg),
        ("e" * 64, "transfer", ad(2), a, "3", None, NOW - 4 * D + 5, 1, seg), ("f" * 64, "challenge", a, None, None, 3, NOW - 3600, 1, seg)]
db.write("INSERT INTO txs(id, type, from_addr, to_addr, amount, epoch, ts, final, segment) VALUES(?,?,?,?,?,?,?,?,?)", rows, many=True)
db.write("INSERT INTO txs(id, type, from_addr, to_addr, amount, epoch, ts, final, segment, invited_by) VALUES(?,?,?,?,?,?,?,?,?,?)", ("9" * 64, "join", ad(3), None, None, None, NOW - 4 * D + 50, 1, seg, a))
A._cache.clear()
ev = TL.events(a); k = [x["kind"] for x in ev]
check("milestones oldest first", [x["ts"] for x in ev] == sorted(x["ts"] for x in ev))
check("join, first answer, first seal, est add and paid (same close), transfer, invite, best, est removed, latest", k == ["join", "answer", "seal", "paid", "est_add", "transfer", "invite", "best", "est_rm", "latest"])
P = {x["kind"]: x for x in ev}
check("first paid close is E1 (10.5), best is E2 (40)", P["paid"]["close"] == 1 and P["paid"]["value"] == 10.5 and P["best"]["close"] == 2 and P["best"]["value"] == 40)
check("latest tx is the newest answer", P["latest"]["tx"] == "f" * 64)
check("an Agent with nothing has no events", TL.events(ad(77)) == [])
h = TL.tab_html(a)
check("tab card: id, count, tx links, close links, method", 'id="timeline"' in h and "Timeline · 10" in h and '/tx/' + "a" * 64 in h and 'href="/epoch/2"' in h and "/about#timeline" in h)
r, _ = S.api("/api/address/" + a + "/timeline", {})
check("API: events and kinds", len(r["events"]) == 10 and r["kinds"]["best"] == "Best close reward" and r["segment"] == SG.CURRENT)
try: S.api("/api/address/" + a + "/timeline", {"x": ["1"]}); check("API: unknown parameter is a 400", False)
except S.BadRequest: check("API: unknown parameter is a 400", True)
check("MCP get_agent_timeline", "get_agent_timeline" in [t[0] for t in AG.TOOLS] and len(AG.t_agent_timeline({"address": a})["events"]) == 10)
check("OpenAPI lists the timeline path", "/api/v1/address/{address}/timeline" in json.dumps(AG.openapi()))
V.REQ.qs = {"tab": ["timeline"]}
pg = V.address(a); pg = pg[1] if isinstance(pg, tuple) else pg
check("address page: Timeline tab chip and card", "?tab=timeline" in pg and 'id="timeline"' in pg)
ab = V.about(); sec = ab[ab.find('id="timeline"'):ab.find('id="board"')]
check("about: #timeline", 'id="timeline"' in ab and "established_after" in sec)
src = open(TL.__file__).read() + sec + h
check("no dashes, no prohibited names", "\u2014" not in src and "\u2013" not in src and not re.search(r"plus\s?1", src, re.I))
R = TL.records(a)
check("records: 3 of 4 closes paid, run 3, best E2 40, total 55.5, rank 1", R["paid_closes"] == 3 and R["closes"] == 4 and R["longest_paid_run"] == 3 and R["best_close"]["close"] == 2
      and R["total_rewards"] == 55.5 and R["rewards_rank"] == 1)
check("records: most answers in a day 1, most seals in a day 1", R["most_answers_day"]["value"] == 1 and R["most_seals_day"]["value"] == 1)
h2 = TL.tab_html(a)
check("records card above the timeline, UTC day labelled", h2.index('id="agent-records"') < h2.index('id="timeline"') and "(UTC day)" in h2 and "Longest paid run" in h2)
check("API carries records", S.api("/api/address/" + a + "/timeline", {})[0]["records"]["paid_closes"] == 3)
print("ALL OK" if not fails else f"{len(fails)} FAILED: {fails}"); sys.exit(1 if fails else 0)
