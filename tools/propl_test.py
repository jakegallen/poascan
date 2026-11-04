"""Proposal L and ballot 2464 (1.26.257): the rule each close ran under (econ_rules.json, segment aware, the newest range
overlaid with /api/params), the intake cap per close, estab_ttl copy, no settle cap once params drop it, the carry aware
burn, the bundled correction table, the waitlist, the /api/established and close-report parsers, the operator notices card
and no em or en dash in any new copy. Usage: python3 tools/propl_test.py (temp database, no network)."""
import json, os, sys, tempfile, time
os.environ["POASCAN_SEGMENTS"] = "1"
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "p.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, econ as X, grading as GR, correction as CC, netfacts as NF, governance as GV, earn as EA, intake as IK, views as V

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)
DASH = ("\u2014", "\u2013")
NOW = int(time.time())
db.init()

# econ: segment 2 history keeps the old rules, E36 on is Proposal L
s2 = lambda n: X.at(n, 2, live=False)
check("seg2 E35: estab_ttl 6, max(5, 10%), no waitlist", (s2(35)["estab_ttl"], s2(35)["intake_floor"], s2(35)["intake_rate"], s2(35)["waitlist_epochs"]) == (6, 5, 0.10, 0))
check("seg2 E36: estab_ttl 26, max(25, 25%), waitlist 3, carry on", (s2(36)["estab_ttl"], s2(36)["intake_floor"], s2(36)["intake_rate"], s2(36)["waitlist_epochs"], s2(36)["carry_cap_pools"]) == (26, 25, 0.25, 3, 1))
check("seg2 E39: carry off", s2(39)["carry_cap_pools"] == 0)
check("seg2 settle cap 2000 to E32, none from E33", s2(32)["settle_cap"] == 2000 and not s2(33)["settle_cap"])
check("segment 1 stays on the old rules", X.at(5, 1, live=False)["estab_ttl"] == 6 and X.at(5, 1, live=False)["intake_floor"] == 5)
check("cap: E42 set 223 reads 56, E39 set 113 reads 29, E36 set 38 reads 25", (X.cap_of(223, 25, 0.25), X.cap_of(113, 25, 0.25), X.cap_of(38, 25, 0.25)) == (56, 29, 25))
check("ttl phrase: 26 epochs, about 6.5 days; 6 epochs, about 36 hours", X.ttl_phrase(26) == "26 epochs, about 6.5 days" and X.ttl_phrase(6) == "6 epochs, about 36 hours")

# live params overlay the newest range of the current segment; a dropped settle_cap_per_close means no cap
db.put_blob("params", {"auto_epoch_seconds": 21600, "estab_ttl": 26, "estab_intake_floor": 25, "estab_intake_rate": 0.25, "estab_waitlist_epochs": 3})
A._cache.clear()
check("params overlay: estab_ttl 26 and waitlist 3 now", X.estab_ttl() == 26 and X.waitlist() == 3)
check("segment 2 newest range: no settle cap (params dropped settle_cap_per_close)", X.settle_cap(None, 2) is None and X.settle_cap(32, 2) == 2000)
db.put_blob("params", {"auto_epoch_seconds": 21600, "settle_cap_per_close": 2000}); A._cache.clear()
check("settle_cap_per_close in params still reads", GR.settle_cap() == 2000)
db.put_blob("params", {"auto_epoch_seconds": 21600, "estab_ttl": 26, "estab_intake_floor": 25, "estab_intake_rate": 0.25, "estab_waitlist_epochs": 3}); A._cache.clear()

# copy: no fixed 6 epochs or max(5, 10%) once params say otherwise
rules = " ".join(t for _, t, _ in EA.grading_rules()) + " ".join(w["qualifies"] for w in EA.ways())
check("earn copy reads 26 epochs and max(25, ceil(25%", "26 epochs" in rules and "max(25, ceil(25%" in rules and "last 6 epochs" not in rules and "plus 27" in rules)
check("governance rules copy reads the live TTL", "26 epochs, about 6.5 days" in GV.rules() and "E26 close (estab_ttl 26)" in GV.rules())
check("rules: one line per change", "From E36: estab_ttl 6 to 26" in " ".join(GV._rule_line(c) for c in X.changes(2)))
check("/about#econ table", 'id="econ"' in X.about_html())
check("no em or en dash in the new copy", not any(d in rules + GV.rules() + X.about_html() + json.dumps(X.api_block()) for d in DASH))

# carry aware burn: pool includes carry_in; carried out pay rolls, it is not burned
ad = lambda i: "poa1" + format(i, "040d").replace("0", "Q")
rec = lambda n, pool, paid, b: {"epoch": n, "ts": NOW - (6 - n) * 21600, "pool": str(pool), "rewards": {ad(1): str(paid)}, "challenges": {}, "basis": b}
eps = [rec(0, 1000, 200, {"carry_in": "0", "carry_out": "800"}), rec(1, 1800, 1500, {"carry_in": "800", "carry_out": "300"}),
       rec(2, 1000, 900, {"carry_in": "0", "carry_out": "100", "carry_burned": "300"}), rec(3, 1000, 950, {"carry_in": "0", "carry_out": "50", "carry_burned": "100", "carry_correction": {"total": "40"}})]
db.put_blob("epochs", eps); A._cache.clear()
r = {x["epoch"]: x for x in A.epoch_rows()}
check(f"a carried close burns 0 ({r[0]['burned']})", r[0]["burned"] == 0 and r[0]["carry_rolled"] == 800)
check(f"a carry_out the next close does not take in burns (E38 pattern: {r[1]['burned']})", r[1]["burned"] == 300 and r[1]["carry_rolled"] == 0)
check(f"carry off: unpaid burns ({r[1]['burned']}, {r[2]['burned']}, {r[3]['burned']})", r[2]["burned"] == 100 and r[3]["burned"] == 50 and abs(r[3]["burn_pct"] - 5.0) < 1e-9)
check("correction field read from the record and taken off cum_supply", r[3]["correction"] == 40 and abs(r[3]["cum_supply"] - (200 + 1500 + 900 + 950 - 40)) < 1e-6)

# ballot 2464 table: pinned, 92 Agents, 940,522,943.64 POA
check("correction table: sha pinned, 92 rows, 940.52M", len(CC.table()) == 92 and abs(CC.total() - 940522943.64) < 0.01)
check("correction effect text, no dash", CC.effect_text()[0] == "Burns 940.52M POA from 92 Agents' locked at the E44 close" and not any(d in CC.effect_text()[0] for d in DASH))

# /api/established and close-report live shapes
db.put_blob(NF.EST_BLOB, {"computed_at_close": 42, "current": {"members": [{"addr": ad(1), "since_epoch": 3, "expires_after_epoch": 40}, {"addr": ad(2), "since_epoch": 4}]}})
aset, det = NF.authoritative_established()
check("/api/established current.members reads (was 0)", aset == {ad(1), ad(2)} and det[ad(1)]["since"] == 3 and det[ad(1)]["expires"] == 40)
check("established check reads /api/established, not the grading list", GR.established_check(ad(1))[0] == "api_established" and GR.established_check(ad(3))[0] == "conflict")
db.put_blob(NF.CLOSE_BLOB, {"close_epoch": 42, "settled_split": {"passed": 189, "failed": 14, "expired_empty_jury": 2842, "expired_with_seals": 0},
                            "panels": {"grades_cast": 8621, "rows_reaching_quorum": 203}, "concentration": {"distinct_graders": 17, "n_eff_inverse_herfindahl": 5.8, "top_grader_share": 0.3621},
                            "establishment": {"established_before": 223, "eligible": 183, "admitted": 56, "waitlisted": 113}})
c = NF.authoritative_close()
check("close-report live shape", (c["epoch"], c["passed"], c["failed"], c["expired"], c["grades"], c["graders"], c["quorum_rows"], c["n_eff"]) == (42, 189, 14, 2842, 8621, 17, 203, 5.8) and c["establishment"]["waitlisted"] == 113)
cc = NF.close_crosscheck()
check("grades and graders not compared (different definitions)", all(x["state"] == "not_compared" for x in cc["rows"] if x["name"] in ("grades", "graders")))
check("system_addresses rows read", NF.system_accounts({"system_addresses": [{"label": "v1", "addr": ad(9), "role": "liveness"}]})[0]["address"] == ad(9))
check("ECON lists the waitlist", any(k == "estab_waitlist_epochs" for k, _, _ in NF.ECON))

# operator notices
db.put_blob("notices", {"active": [{"id": "2026-11-04-carry-correction-E44", "severity": "info", "msg": "2464=A: carry correction at E44 close \u2014 test", "issued_ts": NOW - 60, "txid": "ab" * 32}]})
nr = V.notices_rows()
check("notices card: active G0 notice row, dashes removed", nr and nr[0]["active"] and not any(d in nr[0]["msg"] for d in DASH) and "Operator notices" in V._notices_card())

print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
