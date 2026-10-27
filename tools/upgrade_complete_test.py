"""Upgrade complete (1.26.51): the official notice that grading is back and the hardening is over ends the upgrade by itself.
* complete() reads the /api/notices mirror only, keeps the first sight in the database, and holds after the notice expires
* older notices (hardening, restored, grading-halted) are superseded: no Halted tag, no paused payouts, notice.active false
* a newer halt notice after completion still counts; /upgrade shows the completed note with dates; the route check stops
Usage: python3 tools/upgrade_complete_test.py"""
import os, re, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "u.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import db, maint as M, analytics as A, hosted as R, views as V, views2 as V2, milestones as MS
now = int(time.time())
HARD = {"id": "2026-10-21-hardening", "issued_ts": 1792614261, "expires_ts": now + 86400, "msg": "API hardening: mining & grading paths PAUSED. Check back hourly at a RANDOM minute."}
REST = {"id": "2026-10-22-restored", "issued_ts": 1792710966, "expires_ts": now + 86400, "msg": "Mining & joins OPEN. Attestation earnings live. Challenge grading + pool payouts resume after the panel-stability fix."}
HALT = {"id": "2026-10-22-grading-halted", "issued_ts": 1792711337, "expires_ts": now + 86400, "msg": "Mining, joins, answers & attestation earnings fully LIVE. Challenge GRADING is HALTED, but grading + challenge-pool payouts paused until further notice."}
DONE = {"id": "2026-10-23-grading-resumed", "issued_ts": 1792774656, "expires_ts": now + 3600, "txid": "a241efae5b315b9f4dfdd4030990321d3d794cf800acdb76932029c6be267000",
        "msg": "\u2705 GRADING IS BACK \u2014 all paths OPEN (answers, assignments, grades, swaps). Panels are now deterministic. Hardening pause over \u2014 resume normal cadence."}
def notices(*xs): db.put_blob("notices", {"active": list(xs)})

# ---------------- before: halted, nothing complete ----------------
notices(HARD, REST, HALT)
check("before the notice: not complete", M.complete() is None)
check("before the notice: grading halted from the notice", A.grading_halt() == "2026-10-22-grading-halted")
check("before the notice: pool payouts paused", M.pool_payouts() == "paused")
check("a notice that only says grading resumes after a fix is not completion", not M._says_complete(REST["msg"]))

# ---------------- the completion notice ----------------
notices(HARD, REST, HALT, DONE)
# 1.26.58: the notice alone no longer shows grading open; grade seals landing in the archive confirm it (tools/grading_truth_test.py)
db.write("INSERT OR REPLACE INTO fetch_log(endpoint, last_ok) VALUES('/api/explorer/txs', ?)", (now,))
for i in range(3): db.write("INSERT INTO txs (id, type, from_addr, ts) VALUES (?, 'grade-sealed', ?, ?)", (f"{0xc0de00 + i:064x}", "poa1" + "S" * 40, now - 60 * (i + 1)))
c = M.complete()
check("complete at the notice's issued time, with its id and txid", c and c["at"] == 1792774656 and c["notice_id"] == DONE["id"] and c["txid"] == DONE["txid"])
check("older notices are superseded", all(M.superseded(x) for x in (HARD, REST, HALT)) and not M.superseded(DONE))
check("grading_halted false on the open epoch", A.open_epoch()["grading_halted"] is False and A.grading_halt() is None)
check("pool payouts and attestation earnings live", M.pool_payouts() == "live" and M.attestation_earnings() == "live")
st = M.state()
check("maintenance inactive, cleared by upgrade_complete, phase complete", not st["active"] and st["cleared_by"] == "upgrade_complete" and st["phase"] == "complete")
check("completed_at and completed_by", st["completed_at"] == "2026-10-23T16:57:36Z" and st["completed_by"] == {"notice_id": DONE["id"], "txid": DONE["txid"]})
check(f"paused is empty ({st['paused']})", st["paused"] == [])
check("working lists hosted mining, grading, onboarding and payouts", all(k in st["working"] for k in ("onboarding", "hosted_mining", "grading", "self_custody_mining", "attestation_earnings", "challenge_pool_payouts", "balances", "explorer")))
check("hardening notice reads no longer active, superseded by the completion notice", st["notice"]["active"] is False and st["notice"]["superseded_by"] == DONE["id"])
check("no swap write read yet: swap_offer unknown, never open (1.26.184 swap resolver)", st["hosted_routes_display"]["swap_offer"] == "unknown" and st["swap_route"]["state"] == "unknown")
R.write_job(now=int(time.time()), get=lambda: (401, b'{"error":"missing key"}'), force=True); st = M.state()
check("every hosted route shows open once the write check reads open", set(st["hosted_routes_display"].values()) == {"open"})
check("hosted mining back, joining open", st["hosted_mining"] == "back" and st["join_state"] == "open")
check("headline says complete", st["headline"].startswith("Upgrade complete") and st["headline_short"] == "Upgrade complete.")
check("freshness is not Upgrading", A.freshness()["state"] != "up")
db.put_blob("halts", {"groups": {"Answers": "planned", "Grading": "planned", "Joining": "planned", "MCP mining tools": "paused"}, "ts": now})
check("stale tracker states read back once complete", set((M.state()["surfaces"] or {}).values()) <= {"back"} and M.join_open())

# ---------------- held after expiry; a later halt still counts ----------------
notices(HARD, REST, HALT)   # the completion notice expired and left the list; the old halt notice is still listed
check("completion holds after its notice leaves the list", M.complete() and M.complete()["at"] == 1792774656)
check("the old halt notice stays superseded", A.grading_halt() is None and M.pool_payouts() == "live")
NEW = {"id": "2026-10-30-grading-halted", "issued_ts": 1792774656 + 600000, "expires_ts": now + 86400, "msg": "Challenge GRADING is HALTED, challenge-pool payouts paused until further notice."}
notices(HARD, HALT, NEW)
check("a newer halt notice after completion counts again", A.grading_halt() == NEW["id"] and M.pool_payouts() == "paused")
notices(HARD, REST, HALT, DONE)

# ---------------- pages ----------------
h = V2.upgrade_body()
check("/upgrade shows the completed note", "Upgrade complete" in h and "API hardening is over" in h and "Still paused" not in h and "Endpoints" not in h)
check("/upgrade carries the dates (visitor-local times, UTC fallback)", 'datetime="2026-10-21T19:00:51Z"' in h and 'datetime="2026-10-23T16:57:36Z"' in h and "16:57 UTC" in h)
check("/upgrade links the notice tx and post 1357", "/tx/" + DONE["txid"] in h and M.POST_URL in h)
check("no em or en dash on /upgrade", "\u2014" not in h and "\u2013" not in h)
from poascan import agentapi as AG
check("completed /upgrade shows the Release row with the release line", "<dt>Release</dt>" in h and AG.VERSION in h and AG.RELEASE_LINE in h)
check("og description says complete", M.og_desc().startswith("Network upgrade complete"))
check("no home strip", not hasattr(V, "upgrade_strip") and "upline" not in V.upgrade_live())
check("graders tile has no Halted tag", "Halted" not in V.graders_tile(A.open_epoch()))

# ---------------- route check stops; markers ----------------
calls = []
R.job(now=now + 99999, get=lambda p: calls.append(p) or (503, b'{"halted": true}'))
check("route check makes no request once complete", calls == [])
ev = {e["key"]: e for e in MS.events()}
check("chart milestones: Grading reopened and Upgrade complete at the notice time", ev["grading_reopened"]["ts"] == ev["ended"]["ts"] == 1792774656
      and ev["grading_reopened"]["label"] == "Grading reopened" and ev["ended"]["label"] == "Upgrade complete")
g = MS.group(MS.events(), 1792774656 - 7 * 86400, 1792774656 + 3600)
labs = [x[1] for x in g]
check(f"both are their own labelled markers, no +N ({labs})", "Grading reopened" in labs and "Upgrade complete" in labs and not any(re.search(r"\+\d", l) for l in labs))

if fails: print(f"\nFAIL: {len(fails)}: {fails}"); sys.exit(1)
print("\nPASS")
