"""Grade history and open seats (1.26.158): settled seats only, scores only from settled juries, open seats as public
counts read in the background (at most PER_RUN a run, once per epoch per Agent, assignment lists never kept), Governance
and address page cards with header sort, CSV, /api/v1/governance/grade-history, MCP get_grade_history; plus the UPGRADE
prompt wording and join-pow in the halts route list.
Usage: python3 tools/gradehist_test.py (uses a temp database, no network)."""
import os, sys, tempfile, time, json, gzip
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, segments as SG, gradehist as GH, indexer as IX, governance as GV, agentapi as AG, prompts as PR, halts as HL, server as SV

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

G1, G2, G3, AU = "poa1" + "A" * 40, "poa1" + "B" * 40, "poa1" + "C" * 40, "poa1" + "D" * 40
NOW = int(time.time())
def close(n, ts, settled, pending=None):
    return {"epoch": n, "ts": ts, "pool": 1e9, "rewards": {}, "challenges": {}, "propagation": {},
            "basis": {"settled": settled, "pending": pending or {}, "established_after": [G1, G2], "graders_served": {}}}
def st(ans, passed, jury): return {"answer": ans, "from": AU, "passed": passed, "jury": [{"grader": g, "aligned": al} for g, al in jury]}
SECRET = "f" * 64   # an answer id that only appears in an assignments list and a pending row

def main():
    db.init()
    db.put_blob("params", {"auto_epoch_seconds": 21600})
    db.put_blob("epochs", [close(1, NOW - 50000, [st("a1", True, [(G1, True), (G2, True), (G3, False)])]),
                           close(2, NOW - 20000, [st("a2", False, [(G1, True), (G2, False)]), st("a3", True, [(G1, True)])],
                                 pending={SECRET: {"grades": [{"grader": G1, "score": 3, "ts": NOW - 100}]}})])
    db.put_blob("epochs:s1", [close(5, NOW - 900000, [st("old", True, [(G1, False)])])])
    # grading list copy: settled scores count; a pending row's grades never carry into history
    db.put_blob("grading", {"epoch": 3, "fetched_at": NOW, "settled": [{"id": "a1", "jury": [{"g": G1, "s": 3, "aligned": True}, {"g": G2, "s": 2}]},
                                                                      {"id": "a2", "jury": [{"g": G1, "s": True}, {"g": G2, "s": 9}]}],
                            "rows": [{"id": SECRET, "grades": [{"g": G1, "ts": NOW, "t": False, "q": True, "s": 1}]}], "open": [], "leaderboard": [], "stats": {}})
    from poascan import grading as GR; GR._ensure(); GR._cur.clear(); A._cache.clear()
    n = GH.sync()
    check("sync stores every settled jury seat in both segments", n == 7 and db.q1("SELECT COUNT(*) AS c FROM grade_history")["c"] == 7)
    check("sync twice adds nothing (a read close is skipped)", GH.sync() == 0 and db.q1("SELECT COUNT(*) AS c FROM grade_history")["c"] == 7)
    check("sync remembers the last close read per segment", (db.get_blob("gradehist_meta")[0] or {}).get("closes_seen") == {"1": 5, str(SG.CURRENT): 2})
    sc = {(r["answer"], r["grader"]): r["score"] for r in db.q("SELECT answer, grader, score FROM grade_history")}
    check("scores only from settled juries, 0 to 3 integers", sc[("a1", G1)] == 3 and sc[("a1", G2)] == 2 and sc[("a2", G1)] is None and sc[("a2", G2)] is None)
    check("pending answers and pending scores never enter grade_history", db.q1("SELECT COUNT(*) AS c FROM grade_history WHERE answer=?", (SECRET,))["c"] == 0)
    rows = {r["address"]: r for r in GH.per_grader(SG.CURRENT)}
    check("per grader: seats, aligned, closes, last", rows[G1]["seats"] == 3 and rows[G1]["aligned"] == 3 and rows[G1]["closes"] == 2 and rows[G1]["last"] == 2 and rows[G1]["avg"] == 3.0)
    check("segment 1 kept apart", [r["seats"] for r in GH.per_grader(1)] == [1])

    # raw post copies backfill scores once
    db.write("INSERT INTO grading_raw(epoch, kind, ts, as_of, bytes, body) VALUES(?,?,?,?,?,?)",
             (2, "post", NOW, NOW, 1, gzip.compress(json.dumps({"settled": [{"id": "a3", "jury": [{"g": G1, "s": 1}]}]}).encode())))
    GH.sync()
    check("raw copies fill a missing settled score", db.q1("SELECT score FROM grade_history WHERE answer='a3' AND grader=?", (G1,))["score"] == 1)

    # a new close is read on the next pass, alone
    eps = db.get_blob("epochs")[0]; db.put_blob("epochs", eps + [close(3, NOW - 5000, [st("a4", True, [(G2, True)])])]); A._cache.clear(); A._epochs.clear()
    check("a new close is added incrementally", GH.sync() == 1 and db.q1("SELECT COUNT(*) AS c FROM grade_history")["c"] == 8)
    db.put_blob("epochs", eps); db.write("DELETE FROM grade_history WHERE answer='a4'"); A._cache.clear(); A._epochs.clear()

    # flag: POASCAN_GRADEHIST=off stops both jobs
    GH.ENABLED = False
    check("flag off: sync and open seat job do nothing", GH.sync() == 0 and GH.job(NOW, lambda a: 1 / 0) == 0)
    GH.ENABLED = True

    # open seats: background reads, counts only
    check("allowlist: /api/assignments/<addr>?limit=1", bool(IX.ALLOWED.match(f"/api/assignments/{G1}?limit=1")) and not IX.ALLOWED.match("/api/assignments/x/../../hosted/me"))
    A.established_set = lambda *a, **k: {G1, G2}
    check("targets: established Agents plus recent graders", GH.targets() == sorted([G1, G2, G3]))
    folds = []; real = GH.targets; GH.targets = lambda: folds.append(1) or real()
    GH.targets_for(3, NOW); GH.targets_for(3, NOW + 60); GH.targets_for(3, NOW + 120)
    check("targets kept per epoch: one fold for three runs", len(folds) == 1)
    GH.targets_for(4, NOW + 180)
    check("a new epoch rebuilds targets", len(folds) == 2)
    GH.targets = real; GH._targets.update(ep=None, at=0, list=[])
    calls = []
    def get(a):
        calls.append(a)
        return {"addr": a, "epoch": 3, "has_seat": True, "total": {G1: 4, G2: 0, G3: 2}[a], "already_graded": 1,
                "assignments": [{"answer": SECRET, "snippet": "SECRET-SNIPPET"}], "note": "x"}
    IX.degraded = lambda now=None: False
    k = GH.job(NOW, get)
    check("first run reads at most PER_RUN Agents", k == min(GH.PER_RUN, 3) and len(calls) == k)
    GH.job(NOW + 60, get); before = len(calls)
    GH.job(NOW + 120, get)
    check("once per epoch: no re-read in the same epoch", len(calls) == before == 3)
    dump = json.dumps([dict(r) for t in ("open_seats", "grade_history", "blobs") for r in db.q(f"SELECT * FROM {t}")], default=str)
    check("no snippet or assigned answer id in open_seats", "SECRET-SNIPPET" not in dump and SECRET not in json.dumps([dict(r) for r in db.q("SELECT * FROM open_seats")]))
    o = GH.open_seats(G1)
    check("open seats row keeps total, graded, has_seat, epoch, read time", o["total"] == 4 and o["graded"] == 1 and o["has_seat"] == 1 and o["epoch"] == 3 and o["read_at"])
    db.put_blob("grading", {"epoch": 4, "fetched_at": NOW, "settled": [], "rows": [], "open": [], "leaderboard": [], "stats": {}}); GR._cur.clear()
    seen = []
    def bad(a):
        seen.append(a); raise IX.Busy("HTTP 503")
    GH.job(NOW + 200, bad)
    check("a failure stops the run after one read", len(seen) == 1)
    IX.degraded = lambda now=None: True; seen.clear()
    GH.job(NOW + 300, get)
    check("no reads while upstream is degraded", len(calls) == 3)
    IX.degraded = lambda now=None: False

    # pages
    A._cache.clear(); A.forum_names = lambda *a, **k: {G1: "Koda"}
    with SG.use(SG.CURRENT):
        h = GH.graders_card({}, lambda **kw: GV.href("graders", **kw))
        check("Graders card: title, Open seats column and tip, CSV and API links", "Grade history" in h and "Open seats" in h and "grade-history.csv" in h and "/api/v1/governance/grade-history" in h)
        check("Graders card: headers sort with hsort and hdir", "hsort=open" in h and "#history" in h and 'aria-sort="descending"' in h)
        h2 = GH.graders_card({"hsort": ["open"], "hdir": ["asc"]}, lambda **kw: GV.href("graders", **kw))
        check("Graders card: sort by Open seats, low to high", h2.index(G2[:6]) < h2.index(G1[:6]))
        check("Agent names link to LabLeak", "lableak" in h.lower() and ">Koda<" in h)
        ag = GH.agent_section(G1, {})
        check("agent section: stats, watermarked chart box, per close table, CSV", "Jury seats" in ag and "chartbox" in ag and "Per close" in ag and "grade-history.csv?addr=" in ag)
        check("agent section: headers sort with gsort", "gsort=seats" in ag and "tab=governance" in ag)
        check("no sub-lines under stats", 'class="ss"' not in ag and "<small" not in ag.split("Seats per close")[0])
        for x in (h, ag): check("no em or en dashes", "\u2014" not in x and "\u2013" not in x)
        tab = GV.agent_tab(G1, {})
        check("Governance tab carries the section", 'id="gov-history"' in tab)
    # API and MCP
    with SG.use(SG.CURRENT):
        d = SV.governance_api("/api/governance/grade-history", {"sort": ["open"]})
        check("API rows sorted by open seats with counts and read time", d["rows"][0]["address"] == G1 and d["rows"][0]["open_seats"] == 4 and d["rows"][0]["open_seats_read_at"])
        d1 = SV.governance_api("/api/governance/grade-history", {"addr": [G1]})
        check("API addr: per close rows and settled seats", [r["close"] for r in d1["rows"]] == [2, 1] and len(d1["seats_list"]) == 3 and d1["open_seats"] == 4)
        check("API never names assigned answers", SECRET not in json.dumps(d1) and "assignments" not in d1)
        for bad_q in ({"addr": ["nope"]}, {"sort": ["x"]}, {"foo": ["1"]}):
            try: SV.governance_api("/api/governance/grade-history", bad_q); ok = False
            except SV.BadRequest: ok = True
            check(f"API 400 on {list(bad_q)[0]}", ok)
    tl = {t["name"]: t for t in AG.tools_list()}
    check("MCP get_grade_history listed", "get_grade_history" in tl and "Settled only" in tl["get_grade_history"]["description"])
    r = AG.TOOL_FN["get_grade_history"]({"address": G1})
    check("MCP get_grade_history returns one grader", r["address"] == G1 and r["seats"] == 3)
    spec = json.dumps(AG.openapi())
    check("OpenAPI documents /api/governance/grade-history with CSV", "governanceGradeHistory" in spec)
    check("llms.txt names the endpoint and tool", "grade-history" in AG.llms_txt() and "get_grade_history" in AG.llms_txt())

    # small fixes
    up = PR.UPGRADE[1]
    check("UPGRADE prompt no longer says hosted mining and grading are paused", "are paused" not in up and "hardening" not in up and "If one is critical, stop and tell me." in up)
    check("UPGRADE prompt: no em or en dashes", "\u2014" not in up and "\u2013" not in up)
    check("halts: join-pow is in the Joining route list", HL.group_of("/api/join-pow") == "Joining" and "join-pow" in HL.MATCH[0][1])
    print(f"\n{len(fails)} failure(s)"); sys.exit(1 if fails else 0)

main()
