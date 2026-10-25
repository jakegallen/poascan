"""Settle queue and exact grading counts from minepoa's grading list (1.26.137): the Queue tab (header sorting, phone
sort menu, need chips, 4 step quorum progress, trusted and untrusted seals, expiry, countdown to the next close),
the Overview stats, exact Graders counts, per Agent pending answers, seals and jury reasons, /api/governance/queue
(JSON and CSV) with upstream_as_of and fetched_at, receipts and standing with exact seals, and copy rules.
Usage: python3 tools/grading_queue_test.py (temp database, no network)."""
import os, sys, tempfile, time, json, re
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
from poascan import db, grading as GR, analytics as A, governance as GV, gradingview as GVW, receipts as RC, standing as SD, server as SV, agentapi as AA
import fixture

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

NOW = int(time.time())
T1, G1, G2 = "poa1" + "T" * 40, "poa1" + "G" * 40, "poa1" + "H" * 40

def seal(g, t, q, dt): return dict(g=g, ts=NOW - dt, t=t, q=q)

def doc():
    A1 = fixture.A1
    rows = [dict(id="d" * 64, author=A1, born=2, since=2, expires=18, kind="short", raw=5, qual=4, need=0, snippet="s",
                 grades=[seal(T1, True, True, 50), seal(G1, False, True, 60), seal(G2, False, True, 70), seal(A1 + "x", False, True, 80), seal(fixture.A2, False, False, 90)]),
            dict(id="e" * 64, author=G1, born=3, since=3, expires=17, kind="short", raw=2, qual=1, need=3, snippet="s",
                 grades=[seal(T1, True, True, 30), seal(A1, False, False, 40)]),
            dict(id="f" * 64, author=G2, born=1, since=1, expires=19, kind="long", raw=0, qual=0, need=4, snippet="s", grades=[])]
    op = [dict(id="9" * 64, author=G2, born=4, since=4, expires=20, kind="short", raw=0, qual=0, need=4, snippet="s", grades=[])]
    ro = [dict(epoch=i, ts=NOW - 3600 - (3 - i) * 21600) for i in range(4)]
    return dict(as_of=NOW - 40, epoch=4, chain="poa-mainnet-1", quorum=4, ttl_epochs=16, trusted=[T1], established=[],
                stats=dict(pending=3, at_quorum=1, by_need={"0": 1, "3": 1, "4": 1}, trusted_share=0.29, graders_distinct=5), rollups=ro, rows=rows, open=op,
                leaderboard=[dict(addr=G1, seals=1, qual=1, avg=2.5, trusted=False, established=False), dict(addr=T1, seals=2, qual=2, avg=None, trusted=True, established=False)],
                settled=[dict(id="c" * 64, author=A1, close=2, passed=True, expired=False, jury=[dict(g=G1, aligned=True, t=False, s=2, r="Concrete and correct."),
                                                                                                dict(g=T1, aligned=False, t=True, s=1, r="Thin on numbers.")])], gen_ms=1)

def txt(h): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
def nodash(name, s): check(name + ": no em or en dash", "\u2014" not in s and "\u2013" not in s)

def main():
    fixture.seed()
    # before any read: honest empty states, no crash
    h = GV.page({"tab": ["queue"]})
    check("queue before a read says it has not been read", "has not been read yet" in h)
    check("API before a read: available false, no rows", GV.api_queue()["available"] is False and GV.api_queue()["rows"] == [])
    check("graders fall back to archived txs", GV.api_graders().get("seals_source") == "archived_txs")

    GR.job(now=NOW, get=lambda: doc(), force=True); A._cache.clear()
    s = GR.summary()
    check("summary: pending and at quorum from the list", s["pending"] == 3 and s["at_quorum"] == 1)
    # queue rows
    rs = GVW.queue_select()
    check("queue: pending rows only by default (open epoch apart)", len(rs) == 3 and all(not r["open"] for r in rs))
    check("queue: ready first by default", rs[0]["need"] == 0)
    check("queue: open filter", [r["id"] for r in GVW.queue_select("open")] == ["9" * 64])
    check("queue: need filter", [r["id"] for r in GVW.queue_select("3")] == ["e" * 64])
    r0 = GR.row_of("d" * 64)
    check("row: trusted and untrusted seals", r0["trusted_seals"] == 1 and r0["untrusted_seals"] == 4)
    check("row: counting split by trust", r0["counting_trusted"] == 1 and r0["counting_untrusted"] == 3)
    check("row: expires_in from the open epoch", r0["expires_in"] == 14)
    check("sort by expires: first click soonest first (low kind)", [r["expires"] for r in GVW.queue_select("", "expires", "desc")] == [17, 18, 19] and [r["expires"] for r in GVW.queue_select("", "expires", "asc")] == [19, 18, 17])
    check("sort by untrusted desc", GVW.queue_select("", "untrusted", "desc")[0]["id"] == "d" * 64)

    h = GV.page({"tab": ["queue"]}); t = txt(h); nodash("queue page", h)
    check("queue page: four stats, no sub-lines", all(w in t for w in ("At quorum", "Pending", "Trusted share", "E4 close")) and 'class="sub"' not in h.split('id="queue"')[0])
    check("queue page: watermark-bearing stat cards", h.count('class="stat') >= 4)
    check("queue page: countdown in the visitor's time", 'class="cd num"' in h and "data-close=" in h and "<time" in h)
    check("queue page: header sorting and phone sort menu", 'class="sorth' in h or "sort=" in h)
    check("queue page: shared sort select", "<select" in h)
    check("queue page: 4 step progress with trusted and untrusted pips", 'class="qp"' in h and '<i class="t"' in h and '<i class="u"' in h and "4/4" in t)
    check("queue page: trusted and untrusted are wide-screen columns, Need and Expires stay at 390 (1.26.138)", '<td class="r dk">1</td><td class="r dk">4</td>' in h)
    check("queue page: ready row marked", "class=rdy" in h and "Ready" in t)
    check("queue page: need chips with counts", "Need 3" in t and "Open epoch" in t)
    check("queue page: CSV and API links", "/api/v1/governance/queue.csv" in h and "/api/v1/governance/queue" in h)
    check("queue page: Agent names link to LabLeak or address", "/address/" in h)
    check("queue tab in nav and sitemap", 'tab=queue' in GV.page({"tab": ["overview"]}) and "/governance?tab=queue" in open(SV.__file__).read())
    # overview
    h = GV.page({"tab": ["overview"]}); nodash("overview", h)
    check("overview: grading stats row", "At quorum" in txt(h) and "Trusted share" in txt(h))
    # graders exact
    g = GV.api_graders()
    check("graders API: exact source with as of", g["seals_source"] == "minepoa_grading" and g["upstream_as_of"] and g["fetched_at"])
    row = {x["address"]: x for x in g["seals_since_close"]}
    check("graders API: qual, rate, pending, avg, trusted", G1 in row and row[G1]["qual"] == 1 and row[G1]["qual_rate"] == 1.0 and "minepoa_avg" in row[G1] and "trusted_listed" in row[G1])
    h = GV.page({"tab": ["graders"]}); nodash("graders", h)
    check("graders page: exact columns, no lower bound mark", "Jury avg" in h and "On queue" in h and "\u2265" not in txt(h).split("Seals since close")[-1][:2000])
    # agent
    ag = GV.api_agent(fixture.A1)["grading"]
    check("agent API: pending answers", [x["id"] for x in ag["pending_answers"]] == ["d" * 64])
    check("agent API: seals on pending with counts flag", len(ag["seals_on_pending"]) == 1 and ag["seals_on_pending"][0]["counts"] is False)
    check("agent API: jury reasons on own settled answers", ag["settled_answers"] and ag["settled_answers"][0]["jury"][0]["reason"] == "Concrete and correct.")
    gj = GV.api_agent(G1)["grading"]
    check("agent API: jury seats with reason", gj["jury_seats"] and gj["jury_seats"][0]["reason"] == "Concrete and correct." and gj["jury_seats"][0]["aligned"] is True)
    h = GVW.agent_cards(G1); nodash("agent cards", h)
    check("agent page: jury reasons card", "Jury reasons" in h and "Concrete and correct." in h)
    check("agent page: phones get the reason under its row (1.26.138)", 'class="whym"' in h and '<td class="why dk">' in h)
    h = GVW.agent_cards(fixture.A1)
    check("agent page: pending answers and seals with tx column", "Pending answers" in h and "Seals on pending answers" in h and ">Tx<" in h)
    # API, CSV, server routes
    q = GV.api_queue(need="ready")
    check("queue API: fields and as of", q["available"] and q["total"] == 1 and q["upstream_as_of"] == NOW - 40 and q["fetched_at"] and q["quorum"] == 4 and q["next_close_ts_est"])
    check("queue API: row fields", set(GV.QUEUE_FIELDS) <= set(q["rows"][0]))
    check("queue API: pagination", GV.api_queue(limit=1, offset=1)["rows"][0]["id"] != GV.api_queue(limit=1)["rows"][0]["id"])
    check("server: queue in GOV_API", "/api/governance/queue" in SV.GOV_API)
    check("OpenAPI: queue op with CSV", "/api/governance/queue" in json.dumps(AA.openapi() if hasattr(AA, "openapi") else open(AA.__file__).read()))
    ov = GV.api_overview()["grading"]
    check("overview API: grading summary", ov and ov["pending"] == 3 and ov["at_quorum"] == 1 and ov["upstream_as_of"])
    # receipts and standing exact
    cur = GR.current(); cur["rows"][1]["id"] = fixture.RN; GR._cur.update(queue=None, qix=None, idx=None)
    r = RC.receipt(fixture.RN)
    check("receipt: exact seals from the list", r["seals_source"] == "minepoa_grading" and r["seals"] == 2 and r["seals_counting"] == 1 and r["seals_need"] == 3 and r["quorum"] == 4)
    check("receipt: no lower bound mark", "\u2265" not in RC.seals_txt(r))
    # archived segment hides the live list
    from poascan import segments as SG
    with SG.use(1):
        check("archived segment: queue not shown", "current segment only" in GV.page({"tab": ["queue"]}))
    # stale
    cur["fetched_at"] = NOW - 7200
    db.put_blob(GR.BLOB, cur); GR._cur.clear(); A._cache.clear()
    check("stale copy is flagged", GR.stale() and "Stale" in GV.page({"tab": ["queue"]}))
    print(f"\n{len(fails)} failed" if fails else "\nall passed")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
