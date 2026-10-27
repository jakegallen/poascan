"""Grader patterns (1.26.183, LabLeak post 1595 comments 6021 and 6028) and settled only Calibration scores.
Agreement, Peers, Spread, Top score, Distance and Mix from grade_history (settled seats, every seat); system graders tagged and
out of percentiles, medians and bands; n 20 minimum with the All chip; Segment 1 (no scores) shows Agreement and Peers only;
answer to seal timing network wide only; ranges; API, CSV, MCP get_grader_patterns, OpenAPI, llms.txt, /about; pending scores
never read (Calibration included). Usage: python3 tools/graderpat_test.py (temp database, no network)."""
import os, sys, tempfile, time, json, statistics
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, segments as SG, gradehist as GH, graderpat as GP, governance as GV, agentapi as AG, server as SV, calibration as CA, grading as GR, views as V

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NOW = int(time.time()); CUR = SG.CURRENT
G = ["poa1" + c * 40 for c in "ABCDEFGH"]; SYSG = G[7]
PEND_MARK = 3   # every pending grade in the close record carries score 3; none may reach a score anywhere

def seed():
    db.init(); GH._ensure(); GR._ensure()
    db.put_blob("params", {"auto_epoch_seconds": 21600, "trusted_graders": [SYSG], "pending_merge_from_epoch": 0})
    # closes 1 (40 days ago) and 2 (2 hours ago); close 2 carries pending grades with a score (never read as a score)
    pend = {f"p{i}": {"grades": [{"grader": G[0], "score": PEND_MARK, "ts": NOW - 7300 - i}]} for i in range(30)}
    db.put_blob("epochs", [{"epoch": 1, "ts": NOW - 40 * 86400, "basis": {"settled": [], "pending": {}}},
                           {"epoch": 2, "ts": NOW - 7200, "basis": {"settled": [], "pending": pend}}])
    db.put_blob("epochs:s1", [{"epoch": 9, "ts": NOW - 90 * 86400, "basis": {"settled": [], "pending": {}}}])
    rows = []
    # 30 answers, juries G0, G1, G2, SYSG; G0 always aligned, score 2 always; G1 aligned on even answers, scores 0..3 cycling;
    # G2 aligned except every 3rd; SYSG aligned always, score 1. G3 has 5 seats (below n 20).
    for i in range(30):
        c = 1 if i < 10 else 2
        rows += [(CUR, f"a{i}", G[0], c, 1, 1, 2), (CUR, f"a{i}", G[1], c, 1 if i % 2 == 0 else 0, 1, i % 4),
                 (CUR, f"a{i}", G[2], c, 0 if i % 3 == 0 else 1, 1, 2 if i % 2 else 3), (CUR, f"a{i}", SYSG, c, 1, 1, 1)]
    rows += [(CUR, f"a{i}", G[3], 2, 1, 1, 2) for i in range(5)]
    rows += [(1, f"s{i}", G[k], 9, 1 if (i + k) % 2 else 0, 1, None) for i in range(25) for k in (0, 1)]   # Segment 1: no scores
    db.write("INSERT INTO grade_history(seg, answer, grader, close, aligned, passed, score) VALUES(?,?,?,?,?,?,?)", rows, many=True)
    # timing: 60 answer txs and seals (answer at t, seal 2h later), all on settled seats of G0
    db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)",
             [(f"a{i}", "challenge", G[5], 1, NOW - 50000, 5, 5, 1) for i in range(30)], many=True)
    db.write("INSERT INTO grading_seals(answer, grader, ts, t, q, first_seen) VALUES(?,?,?,?,?,?)",
             [(f"a{i}", g, NOW - 50000 + 7200 + j, 0, 1, NOW) for i in range(30) for j, g in enumerate((G[0], G[1]))], many=True)
    A._cache.clear()

seed()
p = GP.patterns("all", 20); by = {r["address"]: r for r in p["rows"]}
g0, g1, g2, sy, g3 = by[G[0]], by[G[1]], by[G[2]], by[SYSG], by[G[3]]
check("agreement per grader from settled seats", g0["agreement"] == 1.0 and g1["agreement"] == 0.5 and g2["agreement"] == round(20 / 30, 4) and g0["seats"] == 30)
# peers of G0 on answer i: mean aligned of G1, G2, SYSG (and G3 on a0..a4)
exp = []
for i in range(30):
    o = [1 if i % 2 == 0 else 0, 0 if i % 3 == 0 else 1, 1] + ([1] if i < 5 else [])
    exp.append(sum(o) / len(o))
check("peers: other jurors' agreement on the same answers", abs(g0["peers"] - statistics.fmean(exp)) < 1e-3 and g0["peer_seats"] == 30)
s1 = [i % 4 for i in range(30)]
check("spread is the stdev of settled scores; flat scorer has 0", g1["spread"] == round(statistics.stdev(s1), 3) and g0["spread"] == 0.0)
check("top score share and mix", g0["top_share"] == 1.0 and g0["top_score"] == 2 and g1["mix"] == {"0": 8, "1": 8, "2": 7, "3": 7} and g1["top_share"] == round(8 / 30, 4))
d0 = []
for i in range(30):
    o = [i % 4, 2 if i % 2 else 3, 1] + ([2] if i < 5 else []); d0.append(abs(2 - statistics.fmean(o)))
check("distance: gap to the other jurors' mean score", abs(g0["distance"] - statistics.fmean(d0)) < 1e-3)
check("system grader tagged, no percentiles; below n 20 flagged, no percentiles", sy["system"] and sy["percentiles"] is None and g3["below_min"] and g3["percentiles"] is None and not g0["below_min"])
check("pool, medians and bands leave out system and low n", p["pool"] == 3 and sum(b["graders"] for b in p["bands"]["agreement"]) == 3 and p["median"]["agreement"] == g2["agreement"])
check("percentiles among the pool", g0["percentiles"]["agreement"] == 100 and g1["percentiles"]["agreement"] == 33)
check("score mix from the pool only (system scores of 1 left out)", p["score_mix"] == [8, 8, 30 + 7 + 15, 7 + 15])
check("timing: network wide bands and median, never a per grader field", p["timing"]["seals"] == 60 and p["timing"]["median_hours"] == 2.0
      and sum(b["seals"] for b in p["timing"]["bands"]) == 60 and not any(k for r in p["rows"] for k in r if "tim" in k or "latency" in k or "hours" in k))
db.write("DELETE FROM grading_seals WHERE grader=?", (G[1],)); A._cache.clear()
check("timing: fewer than 50 matched seals draws nothing", GP.timing("all")["bands"] == [] and GP.timing("all")["seals"] == 30)
db.write("INSERT INTO grading_seals(answer, grader, ts, t, q, first_seen) VALUES(?,?,?,?,?,?)", [(f"a{i}", G[1], NOW - 50000 + 7201, 0, 1, NOW) for i in range(30)], many=True); A._cache.clear()
p7 = GP.patterns("7d", 20); b7 = {r["address"]: r for r in p7["rows"]}
check("range 7d keeps close 2 only", b7[G[0]]["seats"] == 20 and b7[G[0]]["closes"] == 1 and p7["range"] == "7d")
p0 = GP.patterns("all", 0)
check("min_n 0: every grader has percentiles except system", {r["address"] for r in p0["rows"] if r["percentiles"]} == {G[0], G[1], G[2], G[3]})
with SG.use(1):
    A._cache.clear(); q = GP.patterns("all", 20); rr = q["rows"]
    check("Segment 1: no scores, Agreement and Peers only", q["scores"] is False and rr and all("spread" not in r and "mix" not in r for r in rr) and set(q["median"]) == {"agreement", "peers"})
    h = GV.page({"tab": ["graders"], "segment": ["1"]}) if False else GP.section({}, lambda **kw: "/governance?tab=graders&amp;segment=1")
    check("Segment 1 table: no Spread, Distance or Mix column", ">Spread<" not in h and "Distance" not in h and ">Mix<" not in h and "Agreement" in h and "Peers" in h and "only Agreement and Peers" in h)
A._cache.clear()

# HTML
h = GV.page({"tab": ["graders"]})
sec = h[h.index('id="patterns"'):]
card = sec[sec.index('id="patterns"'):]; card = card[:card.index("</section>")]
check("Graders tab: Grader patterns card after Calibration", h.index('id="calibration"') < h.index('id="patterns"') and "Grader patterns · 4" in card)
check("A to Z by default: active Agent header, names before addresses", 'aria-sort="ascending"' in card.split("<tbody>")[0] and card.index(G[0]) < card.index(G[1]) < card.index(G[2]))
check("system tag, low n hidden by default with the count", '<span class="tag">system</span>' in card and G[3] not in card and "1 under n 20 hidden" in card)
check("Advisory tag and note, method link, percentile on hover", "Advisory" in card and 'href="/about#grader-patterns"' in card and 'title="Percentile 100 of 3 graders"' in card)
check("header tips on Agreement, Peers, Spread, Top score, Distance, Mix", card.count('class="qtip hv"') == 6)
check("sortable headers keep the tab (psort, pdir)", "psort=agreement" in card and "tab=graders" in card and "#patterns" in card)
check("range chips 24h 7d 30d All and n 20+ / All chips", all(f">{t}</a>" in card for t in ("24h", "7d", "30d", "All", "n 20+")) and "prange=7d" in card and "pn=all" in card)
check("charts: Agreement, Spread, Score mix, Answer to seal, watermarked chart boxes with ? tips", all(t in sec for t in ("Agreement · graders", "Spread · graders", "Score mix", "Answer to seal · seals")) and sec.count('class="chartbox') >= 4)
st_ = sec[sec.index('gpst'):sec.index('<div class="tw">')]
check("stat cards in the card: Graders, Agreement, Spread, Distance (no sub-lines)", all(f">{t}<" in st_ for t in ("Graders", "Agreement", "Spread", "Distance")) and st_.count('class="stat"') == 4 and 'class="ss"' not in st_)
words = card.lower()
check("neutral wording: no rubber stamp, worst, best, rank, flagged", not any(w in words for w in ("rubber", "worst", "best", "rank", "flagged", "suspicious", "preview data")))
check("no em or en dash", "\u2014" not in h and "\u2013" not in h)
check("names link to LabLeak profiles (Agent cell)", "minepoa.com/lableak/#/u/" in card or "agn" in card)
ha = GP.section({"pn": ["all"]}, lambda **kw: "/governance?tab=graders")
check("All chip shows the low n row, greyed", G[3] in ha and '<tr class="low">' in ha)
hs = GP.section({"psort": ["spread"], "pdir": ["asc"]}, lambda **kw: "/governance?tab=graders")
check("sort by spread ascending puts the flat scorer first", hs.index(G[0]) < hs.index(G[2]) < hs.index(G[1]))
check("timing never per grader in the table", "Answer to seal" not in card)

# API, CSV, MCP, OpenAPI, llms, about
d = SV.governance_api("/api/governance/grader-patterns", {})
check("API: rows (n 20+), medians, bands, timing, method, note", d["total"] == 4 and d["pool"] == 3 and d["timing"]["seals"] == 60 and d["method"].endswith("/about#grader-patterns") and "Advisory" in d["note"])
check("API: profile link only for named Agents, rows A to Z", all(r["profile"] is None for r in d["rows"]) and [r["address"] for r in d["rows"]] == sorted(r["address"] for r in d["rows"]))
d0 = SV.governance_api("/api/governance/grader-patterns", {"min_n": ["0"], "sort": ["agreement"], "range": ["7d"]})
check("API: min_n 0, sort, range", d0["total"] == 5 and d0["rows"][0]["agreement"] == 1.0 and d0["range"] == "7d")
for bad in ({"sort": ["worst"]}, {"range": ["1y"]}, {"x": ["1"]}):
    try: SV.governance_api("/api/governance/grader-patterns", bad); ok = False
    except SV.BadRequest: ok = True
    check(f"API 400 on {bad}", ok)
cs = SV.to_csv(GP.csv_rows(d["rows"]))
check("CSV: flat columns, mix_0..mix_3, no nested JSON", cs.splitlines()[0].startswith("address,name,system,seats") and "mix_3" in cs.splitlines()[0] and "{" not in cs and cs.count("\n") == 5)
src = open(os.path.join(ROOT, "poascan", "server.py")).read()
check("CSV route flattens grader patterns rows", "_GP.csv_rows(rows)" in src and '"/api/governance/grader-patterns", "/api/governance/settlement"' in src)
r = AG.TOOL_FN["get_grader_patterns"]({"range": "all", "min_n": 0})
tl = {t["name"]: t for t in AG.tools_list()}
check("MCP get_grader_patterns answers like the API; 39 tools", r["total"] == 5 and "get_grader_patterns" in tl and len(tl) == 39)
check("OpenAPI and llms.txt", "/api/v1/governance/grader-patterns" in json.dumps(AG.openapi()) and "get_grader_patterns" in AG.llms_txt())
ab = V.about()
check("/about#grader-patterns explains every column, system graders and timing", 'id="grader-patterns"' in ab and all(w in ab for w in ("<b>Peers</b>", "<b>Distance</b>", "<b>Answer to seal</b>", "system_grader_accounts")))

# Calibration: settled only scores (1.26.183)
A._cache.clear()
c = CA.calibration(); cb = {r["grader"]: r for r in c["graders"]}
check("Calibration scores come from settled seats only (grade_history)", cb[G[0]]["scored"] == 30 and cb[G[0]]["score_mean"] == 2.0 and cb[G[1]]["score_hist"] == {"0": 8, "1": 8, "2": 7, "3": 7})
check("Calibration never reads pending grade scores (G0's 30 pending 3s are not counted)", cb[G[0]]["score_hist"].get("3", 0) == 0)
check("Calibration still counts seals from pending grade times", cb[G[0]]["seals"] >= 30)
csrc = open(os.path.join(ROOT, "poascan", "calibration.py")).read()
check("calibration.py reads no pending score", 'gr.get("score")' not in csrc and "gr[\"score\"]" not in csrc)
with SG.use(1):
    A._cache.clear(); c1 = CA.calibration()
    check("Segment 1 Calibration: no scores", all(r["scored"] == 0 and r["score_mean"] is None for r in c1["graders"]))
A._cache.clear()
gsrc = open(os.path.join(ROOT, "poascan", "graderpat.py")).read()
check("graderpat.py: no em or en dash, says Agents not Accounts, reads no pending table", "\u2014" not in gsrc and "\u2013" not in gsrc and "Accounts" not in gsrc and "basis" not in gsrc)
print("all passed" if not fails else f"{len(fails)} failed"); sys.exit(1 if fails else 0)
