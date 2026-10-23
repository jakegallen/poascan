"""Grading truth (1.26.58): the completion notice alone never shows grading as open.
* open: the notice plus grade seals in POAScan's archive in the last GRADE_RECENT_S (at least GRADE_MIN_SEALS), feed fresh
* unconfirmed: the notice alone (no recent seals, old seals only, or our feed is not fresh)
* halted: a newer official halt notice, or a live read since the notice (probe Grading group, grading route) saw it halted
Covers meta.maintenance, the home strip (full and 390px lines), /upgrade, the graders tile, og, route display, surfaces,
open_epoch / MCP fields, and today's case (seals 10:00 to 11:07 AM PT, none from 11:36 to 11:56 AM PT).
No network: the route check is never called. Usage: python3 tools/grading_truth_test.py"""
import os, re, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "g.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import db, maint as M, analytics as A, hosted as R, views as V, views2 as V2, og as OG, pulse as P
now = int(time.time())
HALT = {"id": "2026-10-22-grading-halted", "issued_ts": 1792711337, "expires_ts": now + 86400, "msg": "Challenge GRADING is HALTED, grading + challenge-pool payouts paused until further notice."}
DONE = {"id": "2026-10-23-grading-resumed", "issued_ts": 1792774656, "expires_ts": now + 3600, "txid": "a241efae5b315b9f4dfdd4030990321d3d794cf800acdb76932029c6be267000",
        "msg": "GRADING IS BACK, all paths OPEN (answers, assignments, grades, swaps). Hardening pause over, resume normal cadence."}
def notices(*xs): db.put_blob("notices", {"active": list(xs)}); A._cache.clear()
def feed(ok=True): db.write("INSERT OR REPLACE INTO fetch_log(endpoint, last_ok) VALUES('/api/explorer/txs', ?)", (now if ok else now - 7200,))
n_seal = [0]
def seal(ts, who="S"):
    n_seal[0] += 1; db.write("INSERT INTO txs (id, type, from_addr, ts) VALUES (?, 'grade-sealed', ?, ?)", (f"{0xfeed0000 + n_seal[0]:064x}", "poa1" + who * 40, int(ts)))
def clear_seals(): db.write("DELETE FROM txs WHERE type='grade-sealed'"); A._cache.clear()
def nodash(h): return "\u2014" not in h and "\u2013" not in h and "&mdash;" not in h and "&ndash;" not in h

notices(HALT, DONE); feed(); clear_seals()
check("completion notice is seen", bool(M.complete()))

# ---------------- the notice alone: unconfirmed ----------------
g = M.grading_state()
check(f"notice alone reads unconfirmed ({g['state']}, {g['basis']})", g["state"] == "unconfirmed" and g["basis"] == "notice")
st = M.state()
check("meta.maintenance.grading carries state and label", st["grading"]["state"] == "unconfirmed" and st["grading"]["label"] == "Grading: notice says open, not yet confirmed")
check("grading is in unconfirmed, not working, not paused", st["unconfirmed"] == ["grading"] and "grading" not in st["working"] and "grading" not in st["paused"])
check("headline says not yet confirmed", st["headline"] == "Upgrade complete per notice. Grading not yet confirmed: no recent grade seals." and st["headline_short"] == "Grading not yet confirmed.")
check("phase stays complete (the notice is official)", st["phase"] == "complete" and not st["active"])
check("route display: grading unconfirmed, the rest open", st["hosted_routes_display"]["grading"] == "unconfirmed" and st["hosted_routes_display"]["mining"] == "open")
db.put_blob("halts", {"groups": {"Grading": "planned", "Answers": "planned"}, "ts": now})
check("surfaces: Grading unconfirmed, others back", (M.state()["surfaces"] or {}).get("Grading") == "unconfirmed" and M.state()["surfaces"].get("Answers") == "back")
check("pool payouts follow the notice while unconfirmed", M.pool_payouts() == "live")
o = A.open_epoch()
check("open_epoch: grading_state unconfirmed, not halted", o["grading_state"] == "unconfirmed" and o["grading_halted"] is False and o["grading_basis"] == "notice")
t = V.graders_tile(o)
check("graders tile: Unconfirmed tag, no Halted", '<span class="tag warn">Unconfirmed</span>' in t and "Halted" not in t)
check("graders tooltip explains it", "no grade seals have landed in the last 30 minutes" in t)
s = V.upgrade_strip()
check("home strip shows, badge Grading, links /upgrade", s.startswith('<p class="upstrip"') and "<b>Grading</b>" in s and 'href="/upgrade"' in s)
check("strip full line", "<b>Notice says open</b>" in s and "not yet confirmed" in s and "No grade seals in the last 30 min." in s)
check("strip 390px line is short", '<span class="upm"><b>Grading not yet confirmed</b>. No recent seals.</span>' in s)
check("live snapshot carries the strip line", V.upgrade_live()["upline"] == V.upline() and V.upline() != "")
h = V2.upgrade_body()
check("/upgrade: per notice title, Not yet confirmed group", "Upgrade complete per notice" in h and "Not yet confirmed" in h and 'data-grp="grading"' in h)
wk = h.split('data-grp="working"', 1)[1].split("</ul>", 1)[0]
check("/upgrade: Grading not in Working", "<span>Grading</span>" not in wk and "<span>Hosted mining</span>" in wk)
check("/upgrade: Grade seals row and notice row label", "<dt>Grade seals</dt>" in h and "Grading reopened (notice)" in h and "0 since the notice" in h)
gs = re.search(r"<dt>Grade seals</dt><dd>(.*?)</dd>", h, re.S)
check("/upgrade: Grade seals counts Agents, not addresses", gs is not None and "from 0 Agents" in gs.group(1) and "address" not in gs.group(1))
ogt = OG._upgrade()
check("og: Grading Unconfirmed", ("Grading", "Unconfirmed") in ogt[3] and ogt[1] == "Upgrade complete per notice")
check("og description", M.og_desc().startswith("Network upgrade complete per notice") and "grading not yet confirmed" in M.og_desc())
check("no em or en dashes", all(nodash(x) for x in (s, h, t, st["headline"], M.og_desc())))

# ---------------- seals landing: confirmed open ----------------
seal(now - 120, "A"); seal(now - 300, "B")
g = M.grading_state(); st = M.state()
check(f"two recent seals confirm open ({g['state']}, {g['basis']})", g["state"] == "open" and g["basis"] == "notice+seals" and g["seals_recent"] == 2)
check("open: working has grading, unconfirmed empty", "grading" in st["working"] and st["unconfirmed"] == [] and st["headline"] == M.DONE_HEAD)
check("open: no home strip, graders tile untagged", V.upgrade_strip() == "" and V.upgrade_live()["upline"] == "" and "tag warn" not in V.graders_tile(A.open_epoch()))
h = V2.upgrade_body()
check("open: /upgrade says Upgrade complete, Grading in Working", '<h1 class="uph-t" id="uph-t">Upgrade complete</h1>' in h and "<span>Grading</span>" in h and 'data-grp="grading"' not in h)
check("open: evidence counts", st["grading"]["seals_since_notice"] == 2 and st["grading"]["sealers_since_notice"] == 2 and st["grading"]["last_seal_at"])
feed(False)
check("feed not fresh: back to unconfirmed (we can't see seals)", M.grading_state()["state"] == "unconfirmed")
feed()
clear_seals(); seal(now - 60)
check("one recent seal is not enough", M.grading_state()["state"] == "unconfirmed")
clear_seals(); seal(now - 3600, "A"); seal(now - 3500, "B"); seal(now - 3400, "C")
check("seals older than 30 min only: unconfirmed", M.grading_state()["state"] == "unconfirmed" and M.grading_state()["seals_since_notice"] == 3)
clear_seals(); seal(DONE["issued_ts"] - 60, "A"); seal(DONE["issued_ts"] - 30, "B")
check("seals before the notice do not count", M.grading_state(now=DONE["issued_ts"] + 60)["seals_since_notice"] == 0)

# ---------------- halted ----------------
clear_seals(); seal(now - 60, "A"); seal(now - 90, "B")
db.put_blob(P.BLOB, {"groups": {"Grading": "paused"}, "seen": ["Grading"], "ok": True, "ts": now})
g = M.grading_state()
check(f"live probe Grading paused after the notice: halted even with seals ({g['state']}, {g['basis']})", g["state"] == "halted" and g["basis"] == "probe")
st = M.state(); o = A.open_epoch()
check("halted: grading in paused, headline, short", "grading" in st["paused"] and st["headline"] == "Upgrade complete per notice, but grading is halted." and st["headline_short"] == "Grading halted.")
check("halted: route display paused, surfaces paused", st["hosted_routes_display"]["grading"] == "paused" and (st["surfaces"] or {}).get("Grading") == "paused")
check("halted: open_epoch grading_halted true, basis probe, no notice id", o["grading_halted"] is True and o["grading_basis"] == "probe" and o["grading_halt_notice"] is None)
t = V.graders_tile(o)
check("halted: graders tile Halted tag, tooltip names the live read", '<span class="tag warn">Halted</span>' in t and "live read" in t)
s = V.upgrade_strip()
check("halted: strip says Halted", "<b>Halted</b>" in s and "Mining and joining open." in s)
check("halted: pool payouts paused", M.pool_payouts() == "paused")
check("halted: /upgrade Halted group", 'data-grp="grading"><h2><i></i>Halted</h2>' in V2.upgrade_body())
db.put_blob(P.BLOB, {"groups": {"Grading": "paused"}, "seen": ["Grading"], "ok": True, "ts": DONE["issued_ts"] - 600})
check("a probe read from before the notice does not count", M.grading_state()["state"] == "open")
db.put_blob(P.BLOB, {})
db.put_blob(R.BLOB, {"routes": {"grading": {"state": "paused", "since": now - 60, "checked": now - 60, "streak": 1}}, "ts": now - 60})
check("a halted route read after the notice reads halted (basis route)", M.grading_state()["basis"] == "route" and M.grading_state()["state"] == "halted")
db.put_blob(R.BLOB, {})
NEW = {"id": "2026-10-30-grading-halted", "issued_ts": DONE["issued_ts"] + 600000, "expires_ts": now + 86400, "msg": "Challenge GRADING is HALTED until further notice."}
notices(HALT, DONE, NEW)
g = M.grading_state()
check("a newer halt notice reads halted (basis notice)", g["state"] == "halted" and g["basis"] == "notice" and g["halt_notice"] == NEW["id"])
notices(HALT, DONE)

# ---------------- today's case (Oct 23, 2026; PT = UTC minus 7) ----------------
clear_seals()
import calendar
T = lambda hms: calendar.timegm(time.strptime("2026-10-23 " + hms, "%Y-%m-%d %H:%M:%S")) + 7 * 3600   # PT wall time to unix
for i, hms in enumerate(["10:00:52", "10:24:02", "10:35:42", "10:37:08", "11:00:42", "11:07:28"]): seal(T(hms), "ABCDEF"[i])
check("today 11:10 AM PT: seals landing, open", M.grading_state(now=T("11:10:00"))["state"] == "open")
check("today 11:36 to 11:56 AM PT: no seal since 11:07, unconfirmed", all(M.grading_state(now=T(x))["state"] == "unconfirmed" for x in ("11:36:00", "11:46:00", "11:56:00")))
check("today 12:15 PM PT: still unconfirmed", M.grading_state(now=T("12:15:00"))["state"] == "unconfirmed")

# ---------------- no route check request ----------------
calls = []
R.job(now=now + 99999, get=lambda p: calls.append(p) or (503, b'{"halted": true}'))
check("no new request: the route check stays off once complete", calls == [])
check("pulse maps a grade endpoint only if the probe already reports one", P.parse({"age_s": 10, "results": [{"endpoint": "GET /api/hosted/grade (cred)", "code": 503, "body": {"error": "endpoint temporarily halted"}}]})[0] == {"Grading": "paused"})

if fails: print(f"\nFAIL: {len(fails)}: {fails}"); sys.exit(1)
print("\nPASS")
