"""Network upgrade milestones on Network > Charts (poascan/milestones.py, 1.26.18).
* the verified past events, exact times and terse labels; links only to public anchors (post 1357, on-ledger notice txs)
* live events from POAScan's own state, stored with their first-seen time and kept across restarts; state flags need a
  second look CONFIRM_S later, so one odd read never adds a marker; a route's first open read never moves later
* grouping keeps close markers readable at 390px; the Supply chart and the Milestones table carry them; no upstream call
Usage: python3 tools/milestones_test.py"""
import os, re, subprocess, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "m.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"   # nothing listens: any upstream call would fail
import fixture; fixture.seed()
from poascan import db, milestones as MS, maint as M
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))

# ---------------- verified past events ----------------
ev = {e["key"]: e for e in MS.events()}
want = {"begins": ("2026-10-21T19:00:51Z", "Upgrade begins"), "paused": ("2026-10-21T19:00:51Z", "Mining paused"),
        "notice": ("2026-10-21T20:24:21Z", "Hardening notice"), "checkpoint": ("2026-10-22T21:34:03Z", "Checkpoint 33,463"),
        "route:mining": ("2026-10-22T22:35:21Z", "Mining responding"), "route:send": ("2026-10-22T23:16:36Z", "Send responding"),
        "route:swap_offer": ("2026-10-22T23:16:36Z", "Swap offers responding"), "route:vote": ("2026-10-22T23:16:36Z", "Voting responding"),
        "route:export": ("2026-10-22T23:16:36Z", "Export responding"), "allclear": ("2026-10-22T23:16:55Z", "Mining reopened"),
        "grading_halted": ("2026-10-22T23:22:29Z", "Grading still halted"), "mining_reopened": ("2026-10-22T23:45:49Z", "Mining back seen"),
        "grading_reopened": ("2026-10-23T16:57:36Z", "Grading reopened"), "ended": ("2026-10-23T16:57:36Z", "Upgrade complete"),
        "s2_mining_reopened": ("2026-10-24T21:11:34Z", "Mining reopened"), "s2_first_join": ("2026-10-24T22:59:00Z", "First join"),
        "s2_signup_surge": ("2026-10-26T02:17:28Z", "Signup surge"),
        "genesis_cut": ("2026-10-24T21:01:00Z", "Genesis cut")}
for k, (t, lab) in want.items():
    check(f"{lab} at {t}", k in ev and iso(ev[k]["ts"]) == t and ev[k]["label"] == lab)
check("upgrade begins at the post 1357 time (maint.STARTED)", ev["begins"]["ts"] == M.STARTED)
check("events are oldest first", [e["ts"] for e in MS.events()] == sorted(e["ts"] for e in MS.events()))
check("labels are terse (at most 24 characters) with no em dash", all(len(e["label"]) <= 24 and "\u2014" not in e["label"] + (e["source"] or "") for e in MS.events()))
pub = re.compile(r"^(https://minepoa\.com/lableak/#/post/\d+|/tx/[0-9a-f]{64})$")
check("links only to public anchors (a LabLeak post or an on-ledger tx)", all(e["url"] is None or pub.match(e["url"]) for e in MS.events()))
src = open(os.path.join(ROOT, "poascan", "milestones.py"), encoding="utf-8").read().lower()
check("no private sources and no key wording in the module", not any(w in src for w in ("halt_src", "pulse_src", "halts.", "pulse.", "vulnerab", "api key", "?key=")))

# ---------------- live events ----------------
now = int(time.time())
def routes(**st): db.put_blob("hosted_routes", dict(routes={k: dict(state=s, since=t, checked=now) for k, (s, t) in st.items()}, ts=now))
def notices(*ids): db.put_blob("notices", {"active": [{"id": i, "issued_ts": now - 100, "expires_ts": now + 86400} for i in ids]})
routes(mining=("open", 1792708521), grading=("paused", now - 5000)); notices("2026-10-21-hardening", "2026-10-22-grading-halted")
MS.observe(now)
check("nothing new while grading is still paused and the notice holds", not (db.get_blob(MS.BLOB)[0] or {}).get("events"))
routes(mining=("open", 1792708521), grading=("open", now - 300))
MS.observe(now)
st = db.get_blob(MS.BLOB)[0]
check("grading answering: 'Grading responding' at its first open read", st["events"]["route:grading"]["ts"] == now - 300 and st["events"]["route:grading"]["label"] == "Grading responding")
check("grading open but its halt notice is still active: not reopened", "grading_reopened" not in st["events"] and "grading_reopened" not in (st.get("pending") or {}))
routes(mining=("open", 1792708521), grading=("open", now + 900))   # a later flip back to open must not move the first sighting
notices("2026-10-21-hardening")   # the grading halt notice is gone
MS.observe(now + 60)
st = db.get_blob(MS.BLOB)[0]
check("a later open read never moves 'Grading responding'", st["events"]["route:grading"]["ts"] == now - 300)
check("grading reopened is seeded at the official notice time, never re-added live", "grading_reopened" not in st["events"] and "grading_reopened" not in (st.get("pending") or {}))
MS.observe(now + 60 + MS.CONFIRM_S)
st = db.get_blob(MS.BLOB)[0]
check("live reads leave the seeded grading reopened alone", "grading_reopened" not in st["events"] and {e["key"]: e for e in MS.events()}["grading_reopened"]["ts"] == 1792774656)
check("both completion markers link the on-ledger notice tx", all(ev[k]["url"] == "/tx/" + MS.DONE_TX for k in ("grading_reopened", "ended")))
db.put_blob("notices", {"active": []})   # the hardening notice disappears for one read only
MS.observe(now + 2000); db.put_blob("notices", {"active": [{"id": "2026-10-21-hardening", "expires_ts": now + 86400}]})
MS.observe(now + 2000 + MS.CONFIRM_S)
st = db.get_blob(MS.BLOB)[0]
check("a notice missing from one read only adds no marker", "notice_cleared" not in st["events"] and "notice_cleared" not in st.get("pending", {}))
db.put_blob("notices", {"active": [{"id": "2026-10-22-restored", "expires_ts": now + 86400}]})
MS.observe(now + 5000); MS.observe(now + 5000 + MS.CONFIRM_S)
st = db.get_blob(MS.BLOB)[0]
check("hardening notice gone on two looks: 'Notice cleared' at the first", st["events"]["notice_cleared"]["ts"] == now + 5000)
out = subprocess.run([sys.executable, "-c", "from poascan import milestones as MS; print(sorted(e['key'] for e in MS.events() if e['key'] not in MS.SEEDED))"],
                     cwd=ROOT, env=dict(os.environ), capture_output=True, text=True).stdout.strip()
check(f"live events survive a restart ({out})", "route:grading" in out and "notice_cleared" in out)
# upgrade complete: a notice saying grading is back and the hardening is over supersedes the older ones; no 'Notice cleared' from that
db.put_blob(MS.BLOB, {}); db.put_blob("notices", {"active": [{"id": "2026-10-21-hardening", "issued_ts": 1792614261, "expires_ts": now + 86400},
    {"id": "2026-10-22-grading-halted", "issued_ts": 1792711337, "expires_ts": now + 86400, "msg": "Challenge GRADING is HALTED, grading + challenge-pool payouts paused until further notice."},
    {"id": "2026-10-23-grading-resumed", "issued_ts": 1792774656, "expires_ts": now + 86400, "txid": MS.DONE_TX,
     "msg": "GRADING IS BACK, all paths OPEN (answers, assignments, grades, swaps). Hardening pause over, resume normal cadence."}]})
MS.observe(now + 9000); MS.observe(now + 9000 + MS.CONFIRM_S)
st = db.get_blob(MS.BLOB)[0] or {}
check("completion: no live 'Notice cleared' or 'ended' marker (seeded instead)", not any(k in (st.get("events") or {}) for k in ("notice_cleared", "ended", "grading_reopened")))
check("completion: the events list has no 'Notice cleared'", "notice_cleared" not in {e["key"] for e in MS.events()})
check("a stale live 'Upgrade ends' never shows (the seed replaces it)", [e["label"] for e in MS.events() if e["key"] == "ended"] == ["Upgrade complete"])
check("seeded keys are never replaced by live reads", ev["mining_reopened"]["ts"] == {e["key"]: e for e in MS.events()}["mining_reopened"]["ts"])

# ---------------- per-chart relevance (milestones.json) ----------------
import json
cfg = json.load(open(os.path.join(ROOT, "poascan", "milestones.json"), encoding="utf-8"))
from poascan import chartpop as CP
check("every pop-out time chart with markers is a known chart id", all(k in MS.CHART_IDS for k, c in CP.CHARTS.items() if c["marks"]))
check("every config event names its charts ([] = Milestones table only), with known ids or groups", all("charts" in e and MS.expand(e["charts"]) is not None for e in cfg["events"]))
rel = {k: [e["key"] for e in MS.events(k)] for k in MS.CHART_IDS}
check(f"Genesis cut on every chart (chain-wide) {[k for k in rel if 'genesis_cut' not in rel[k]]}", all("genesis_cut" in v for v in rel.values()))
check("hardening start on mining, grading and joining charts", all("begins" in rel[k] for k in ("mined", "supply", "circ", "txs", "gov-paid", "gov-queue", "gov-cover", "joins", "agents")) and "begins" not in rel["holders"])
check("mining reopened (Oct 22 and segment 2) on mining charts; Oct 22 also on joining charts, as Joining reopened",
      all({"allclear", "s2_mining_reopened"} <= set(rel[k]) for k in ("mined", "supply", "circ", "txs")) and "s2_mining_reopened" not in rel["joins"]
      and [e["label"] for e in MS.events("joins") if e["key"] == "allclear"] == ["Joining reopened"] and [e["label"] for e in MS.events("mined") if e["key"] == "allclear"] == ["Mining reopened"])
check("First join only on Agents and Agents / hr", [k for k, v in rel.items() if "s2_first_join" in v] == ["agents", "joins"])
check("Signup surge only on Agents and Agents / hr (no Holders, mined, circulating, Active Agents or txs)",
      [k for k, v in rel.items() if "s2_signup_surge" in v] == ["agents", "joins"])
check("Signup surge is the first join of the Oct 25 burst (tx 0628afd6, 7:17:28 PM PT)",
      {e["key"]: e for e in MS.events()}["s2_signup_surge"]["url"] == "/tx/0628afd6289cc8b8f2fdbca3355e144306d784f68898f7f405ea5ca588ec7e74")
check("Home Total Agents sparkline (spark id home-agents) carries only Signup surge", MS.SPARK_IDS == ("home-agents",) and [e["key"] for e in MS.events("home-agents")] == ["s2_signup_surge"])
check("spark ids are not in any chart group (no group event lands on a sparkline)", not any(x in v for v in MS.GROUPS.values() for x in MS.SPARK_IDS))
from poascan import ui as UI
_sp = [(1792981048 - 7200 + i * 900, 5000 + i) for i in range(16)]
_sv = UI.spark(_sp, marks=MS.events("home-agents"))
check("sparkline draws the Signup surge tick and label inside its span", _sv.count('class="spkt"') == 1 and ">Signup surge</span>" in _sv and 'class="spkw"' in _sv)
check("sparkline without marks in its span is unchanged (plain svg)", UI.spark(_sp[:4], marks=MS.events("home-agents")) == UI.spark(_sp[:4]) and UI.spark(_sp[:4]).startswith('<svg class="spk"'))
check("Signup surge is not a Mining or Active marker", "s2_signup_surge" not in rel["active"] and "s2_signup_surge" not in rel["mined"] and "s2_signup_surge" not in rel["circ"] and "s2_signup_surge" not in rel["holders"])
check("Grading reopened only on grading charts; Upgrade complete never on them (no two labels at one time)",
      [k for k, v in rel.items() if "grading_reopened" in v] == ["gov-est", "gov-paid", "gov-queue", "gov-cover"] and not any("ended" in rel[k] for k in ("gov-est", "gov-paid", "gov-queue", "gov-cover")))
check("Holders carries only chain-wide events", rel["holders"] == ["genesis_cut"])
check("route reads, checkpoint, notices and the back signal are table only", not any(k in v for v in rel.values() for k in ("checkpoint", "notice", "paused", "grading_halted", "mining_reopened", "route:mining", "route:send")))
check("labels are plain: no +N, no em or en dash, at most 24 characters, per chart too",
      all(len(e["label"]) <= 24 and not re.search(r"\+\d|[\u2013\u2014]", e["label"]) for k in MS.CHART_IDS for e in MS.events(k)))
check("no em or en dash anywhere in the config", not re.search(r"[\u2013\u2014]", open(os.path.join(ROOT, "poascan", "milestones.json"), encoding="utf-8").read()))
check("no milestone cites or links Plus1 content (operator notices and chain data only)",
      "plus1" not in open(os.path.join(ROOT, "poascan", "milestones.json"), encoding="utf-8").read().lower()
      and all(e["url"] is None or e["url"] == MS.POST or e["url"].startswith("/tx/") for e in MS.events())   # operator post 1357 or chain txs only
      and all("plus1" not in (e["source"] or "").lower() for e in MS.events()))
check("segment 2 Mining reopened is the first segment 2 answer tx (chain data)", {e["key"]: e for e in MS.events()}["s2_mining_reopened"]["url"] == "/tx/190951ee90e8ab3d1ec4b6808f79f8b02245bed3348f4788c41c88dfa05d6daa")
check("a live event of an unknown kind is table only", MS.charts_of("route:grading") == () and MS.charts_of("something_new") == ())

# ---------------- grouping ----------------
e7 = [e for e in MS.events("mined") if e["ts"] < 1792774656]
t1 = 1792712749 + 3600; g = MS.group(e7, t1 - 7 * 86400, t1)
check(f"7 days, Total mined, before completion: two markers ({[x[1] for x in g]})", [x[1] for x in g] == ["Upgrade begins", "Mining reopened"])
g2 = MS.group(MS.events("mined"), 1792876294 + 3600 - 7 * 86400, 1792876294 + 3600)
check(f"7 days, Total mined, with segment 2: every event labelled ({[x[1] for x in g2]})", [x[1] for x in g2] == ["Upgrade begins", "Mining reopened", "Upgrade complete", "Genesis cut", "Mining reopened"])
g3 = MS.group(MS.events("gov-queue"), 1792876294 + 3600 - 7 * 86400, 1792876294 + 3600)
check(f"7 days, Grading queue ({[x[1] for x in g3]})", [x[1] for x in g3] == ["Upgrade begins", "Grading reopened", "Genesis cut"])
check("group labels carry no +N count suffix", not any(re.search(r"\+\d", x[1]) for gg in (g, g2, g3) for x in gg))
gz = MS.group([e for e in MS.events() if e["key"] in want and e["ts"] < 1792774656], 1792609251 - 3600, 1792712749 + 3600)
check("a group's tip lists every member with its dated UTC time (app.js shows it local, 1.26.122)", all(all(re.match(r"[A-Z][a-z]{2} \d{1,2}, (\d{4}, )?\d\d:\d\d UTC ", m) for m in x[3].split("; ")) for x in gz) and sum(len(x[3].split("; ")) for x in gz) == len([k for k in want if 1792609251 <= {e["key"]: e for e in MS.events()}[k]["ts"] < 1792774656]))
check("a group links its lead event's source", g[1][2] == MS.POST)
check("events outside the range are left out", MS.group(e7, 0, 1000) == [])
for r_, sp_ in (("24h", 86400), ("7d", 7 * 86400), ("30d", 30 * 86400), ("all", 60 * 86400)):
    x1 = 1792876294 + 7200; gg = MS.group(MS.events("joins"), x1 - sp_, x1, width=326)
    check(f"{r_} at 390px (Agents / hr): markers present, plain labels {[x[1] for x in gg]}", gg and all(not re.search(r"\+\d", x[1]) for x in gg) and "Genesis cut" in [x[1] for x in gg])

# ---------------- Supply chart and Milestones table ----------------
s = 1.0e9
for t in range(now - 8 * 86400, now, 900):
    s += 0 if 1792609251 <= t < 1792708521 else 9000
    db.add_snap("status", {"agents_joined": 3000, "holders": 900, "supply": s, "txs": 5}, t)
db.write("DELETE FROM snaps WHERE kind='status' AND (json_extract(json,'$.supply') IS NULL OR json_extract(json,'$.supply') < 1e8)")
from poascan import views3 as V3
h = V3.charts_body("7d")
sup = h[h.find(">Supply<"):h.find(">Txs")]
check("Supply chart carries the grouped markers as links", 'href="https://minepoa.com/lableak/#/post/1357"' in sup and ">Mining reopened<" in sup and not re.search(r"Mining reopened \+\d", sup) and "<title>" in sup)
check("Supply has no table-only markers (route reads, checkpoint)", ">Checkpoint 33,463<" not in sup and "responding<" not in sup)
hol = h[h.find(">Holders"):h.find(">Supply<")]
check("Holders has no epoch close or swap markers", not re.search(r">(S\d+ )?E\d+<", hol) and "1st swap" not in hol)
agt = h[h.find(">Agents<"):h.find(">Holders")]
check("Agents has no swap marker", "1st swap" not in agt)
check("the marked chart opens at its newest end at 390px", 'class="chartbox end"' in sup)
mls = h[h.find(">Milestones<"):]
check("Milestones table lists every upgrade event in range", all(lab in mls for k, (t, lab) in want.items() if {e["key"]: e for e in MS.events()}[k]["ts"] >= now - 7 * 86400))
check("table links the Oct 22 reopening to its post", re.search(r'href="https://minepoa\.com/lableak/#/post/1357"[^>]*>Mining reopened<', mls) is not None)
check("hardening notice links its on-ledger tx", 'href="/tx/23bc1a34c81f4591046a62c29ae8f20a3f64b834df89ff8cf83861eef9c5eddb">Hardening notice<' in mls)
check("no em dash, no share button in the charts section", "\u2014" not in h and "share" not in h.lower())
from poascan import governance as GV
gh_ = GV.charts({})
# the fixture's closes span the last 72 h, so from Oct 26 16:57 UTC on Grading reopened (Oct 23) sits before the first close and
# is rightly not drawn; the relevance rule is checked on the event list and the drawn label only while it is in the plotted span
from poascan import analytics as _A
gk = {e["key"] for e in MS.events("gov-queue")}; _gr = ev["grading_reopened"]["ts"]; _ep = _A.epoch_rows()
in_span = bool(_ep) and _ep[0]["close_ts"] <= _gr
check("Governance charts carry their own milestones (Grading reopened, not Upgrade complete or route reads)",
      "grading_reopened" in gk and "ended" not in gk and not any(k.startswith("route:") or k == "checkpoint" for k in gk)
      and (">Grading reopened<" in gh_ or not in_span) and ">Upgrade complete<" not in gh_ and "responding<" not in gh_ and ">Checkpoint" not in gh_)
from poascan import indexer as I
check("the milestones job runs every 5 min", {j[0]: j[2] for j in I.JOBS}.get("milestones") == 300)
I.flush_counts(force=True); before = db.q1("SELECT COALESCE(SUM(n),0) AS n FROM upstream_counts")["n"]
dict((j[0], j[1]) for j in I.JOBS)["milestones"](); I.flush_counts(force=True)
check("the milestones job makes no upstream request", db.q1("SELECT COALESCE(SUM(n),0) AS n FROM upstream_counts")["n"] == before)

if fails: print(f"\nFAIL: {len(fails)}: {fails}"); sys.exit(1)
print("\nPASS")
