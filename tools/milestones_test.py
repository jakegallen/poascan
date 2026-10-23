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
want = {"begins": ("2026-10-21T19:00:51Z", "Upgrade begins"), "paused": ("2026-10-21T19:00:51Z", "Mining, grading paused"),
        "notice": ("2026-10-21T20:24:21Z", "Hardening notice"), "checkpoint": ("2026-10-22T21:34:03Z", "Checkpoint 33,463"),
        "route:mining": ("2026-10-22T22:35:21Z", "Mining responding"), "route:send": ("2026-10-22T23:16:36Z", "Send responding"),
        "route:swap_offer": ("2026-10-22T23:16:36Z", "Swap offers responding"), "route:vote": ("2026-10-22T23:16:36Z", "Voting responding"),
        "route:export": ("2026-10-22T23:16:36Z", "Export responding"), "allclear": ("2026-10-22T23:16:55Z", "All-clear"),
        "grading_halted": ("2026-10-22T23:22:29Z", "Grading still halted"), "mining_reopened": ("2026-10-22T23:45:49Z", "Mining reopened"),
        "grading_reopened": ("2026-10-23T16:57:36Z", "Grading reopened"), "ended": ("2026-10-23T16:57:36Z", "Upgrade complete")}
for k, (t, lab) in want.items():
    check(f"{lab} at {t}", k in ev and iso(ev[k]["ts"]) == t and ev[k]["label"] == lab)
check("upgrade begins at the post 1357 time (maint.STARTED)", ev["begins"]["ts"] == M.STARTED)
check("events are oldest first", [e["ts"] for e in MS.events()] == sorted(e["ts"] for e in MS.events()))
check("labels are terse (at most 24 characters) with no em dash", all(len(e["label"]) <= 24 and "\u2014" not in e["label"] + (e["source"] or "") for e in MS.events()))
pub = re.compile(r"^(https://minepoa\.com/lableak/#/post/1357|/tx/[0-9a-f]{64})$")
check("links only to public anchors (post 1357 or an on-ledger notice tx)", all(e["url"] is None or pub.match(e["url"]) for e in MS.events()))
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

# ---------------- grouping ----------------
e7 = [e for e in MS.events() if e["key"] in want and e["ts"] < 1792774656]
t1 = 1792712749 + 3600; g = MS.group(e7, t1 - 7 * 86400, t1)
check(f"7 days: two groups before completion ({[x[1] for x in g]})", [x[1] for x in g] == ["Upgrade begins", "Mining reopened"])
g2 = MS.group([e for e in MS.events() if e["key"] in want], 1792774656 + 3600 - 7 * 86400, 1792774656 + 3600)
check(f"7 days with completion: both completion markers labelled ({[x[1] for x in g2]})", [x[1] for x in g2][-2:] == ["Upgrade complete", "Grading reopened"] and not any(re.search(r"\+\d", x[1]) for x in g2))
check("group labels carry no +N count suffix", not any(re.search(r"\+\d", x[1]) for x in g))
check("a group's tip lists every member", all(e["label"] in g[1][3] for e in e7 if e["ts"] >= 1792704843) and g[1][3].endswith("(UTC)"))
check("a group links its lead event's source", g[1][2] == MS.POST)
g1 = MS.group(e7, 1792704843 - 600, 1792712749 + 600)
check(f"zoomed in, close events still group, far ones split ({[x[1] for x in g1]})", len(g1) >= 3 and sum(len(x[3].split("; ")) for x in g1) == 9 and not any("+" in x[1] for x in g1))
check("events outside the range are left out", MS.group(e7, 0, 1000) == [])

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
check("the marked chart opens at its newest end at 390px", 'class="chartbox end"' in sup)
mls = h[h.find(">Milestones<"):]
check("Milestones table lists every upgrade event", all(lab in mls for _, lab in want.values()))
check("table links the all-clear to its post", re.search(r'href="https://minepoa\.com/lableak/#/post/1357"[^>]*>All-clear<', mls) is not None)
check("hardening notice links its on-ledger tx", 'href="/tx/23bc1a34c81f4591046a62c29ae8f20a3f64b834df89ff8cf83861eef9c5eddb">Hardening notice<' in mls)
check("no em dash, no share button in the charts section", "\u2014" not in h and "share" not in h.lower())
from poascan import indexer as I
check("the milestones job runs every 5 min", {j[0]: j[2] for j in I.JOBS}.get("milestones") == 300)
I.flush_counts(force=True); before = db.q1("SELECT COALESCE(SUM(n),0) AS n FROM upstream_counts")["n"]
dict((j[0], j[1]) for j in I.JOBS)["milestones"](); I.flush_counts(force=True)
check("the milestones job makes no upstream request", db.q1("SELECT COALESCE(SUM(n),0) AS n FROM upstream_counts")["n"] == before)

if fails: print(f"\nFAIL: {len(fails)}: {fails}"); sys.exit(1)
print("\nPASS")
