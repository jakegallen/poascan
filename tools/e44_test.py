"""Ballot 2464 at the E44 close (1.26.261): the correction reads from the record in any shape it may take (a total, an
address map, rows), boundary and hash keys are not amounts, the record landing with /api/params carry_correction naming E44
and the pinned table marks it Applied (kept if params later drop it), applied amounts come off locked and out of the
balance check, reconcile explains the supply step, and no em or en dash in the copy. Usage: python3 tools/e44_test.py
(temp database, no network)."""
import json, os, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "e.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from decimal import Decimal as D
from poascan import db, analytics as A, correction as CC, governance as GV, timeline as TL, reconcile as RC

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
DASH = ("\u2014", "\u2013")
db.init()
T = CC.table(); ADDRS = sorted(T); A1, A2 = ADDRS[0], ADDRS[1]
PARAMS = {"auto_epoch_seconds": 21600, "carry_correction": {"from_epoch": 44, "table_sha256": CC.SHA256, "source_sha256": "fa" * 32, "entries": {a: f"{v:.6f}" for a, v in T.items()}}}
NOW = int(time.time())
rec = lambda n, basis=None, **top: dict({"epoch": n, "ts": NOW - (44 - n) * 21600, "pool": "1000", "rewards": {A1: "10"}, "basis": basis or {}}, **top)
closes = {2: [rec(42), rec(43)]}
A.segment_closes = lambda n: closes.get(n, [])
params = [PARAMS]
A.params = lambda: params[0]
def reset(): A._cache.clear(); db.put_blob(CC.MEMO, None)
reset()

# record shapes
cf = A.correction_of
check("number and dict totals", cf({"basis": {"carry_correction": "940522943.638388"}}) == 940522943.638388 and cf({"basis": {"carry_correction": {"total_applied": "5", "applied": {A1: "2", A2: "3"}}}}) == 5)
check("address map and rows sum", cf({"basis": {"carry_correction": {A1: "2", A2: "3.5"}}}) == 5.5 and cf({"carry_correction": [{"addr": A1, "applied": "1"}, {"address": A2, "amount": "2"}]}) == 3)
check("nested applied map without a total", cf({"basis": {"carry_correction": {"from_epoch": 44, "table_sha256": "ab", "applied": {A1: {"applied": "4", "locked_at_close": "9"}}}}}) == 4)
check("boundary, hash and count keys are not amounts", cf({"basis": {"carry_correction_from_epoch": 44, "carry_correction_agents": 92, "correction_sha256": "12"}}) == 0)
check("rows read from the record", A.correction_rows({"basis": {"carry_correction": {"applied": {A1: "2", A2: "3"}, "total": "5"}}}) == {A1: 2.0, A2: 3.0})
check("no correction field: 0", cf(rec(43)) == 0 and A.correction_rows(rec(43)) == {})

# before the close
st = CC.status()
check("before E44: Scheduled, nothing applied", st["state"] == "scheduled" and not CC.done() and CC.applied(A1) == 0 and CC.locked_after(A1, 5e7) == 5e7)
txt, word = CC.effect_text()
check("scheduled copy", txt == "Burns 940.52M POA from 92 Agents' locked at the E44 close" and word == "Scheduled")
check("for_address scheduled", CC.for_address(A1)["state"] == "scheduled" and CC.for_address(A1)["amount"] == T[A1] and CC.for_address(A1)["applied"] is None)
check("params match the pin", CC.api()["params_match"] is True and CC.api()["applied"] is False)

# E44 lands with no correction field, params name E44 and the pinned table: Applied from the table
closes[2].append(rec(44)); reset()
st = CC.status()
check("E44 record in, params match: Applied (via params and close record)", st["state"] == "applied" and st["via"] == "params and close record" and CC.done())
check("rows are the pinned table, total 940,522,943.638388", CC.rows() == T and abs(CC.applied_total() - 940522943.638388) < 1e-4)
txt, word = CC.effect_text()
check("applied copy", txt == "Burned 940.52M POA from 92 Agents' locked at the E44 close" and word == "Applied")
check("locked drops by the Agent's amount, never below 0", abs(CC.locked_after(A1, 5e7) - (5e7 - T[A1])) < 1e-6 and CC.locked_after(A1, 1.0) == 0.0)
check("other Agents unchanged", CC.locked_after("poa1" + "Z" * 40, 7.0) == 7.0)
check("implied: E44 of segment 2 only", abs(CC.implied(rec(44), 2) - CC.total()) < 1e-6 and CC.implied(rec(43), 2) == 0 and CC.implied(rec(44), 1) == 0)
ap = CC.api()
check("api: applied, 92 Agents, matches the table", ap["applied"] and ap["applied_agents"] == 92 and ap["matches_table"] and ap["status"]["state"] == "applied")
params[0] = {"auto_epoch_seconds": 21600}; A._cache.clear()
check("params drop carry_correction later: still Applied (memo)", CC.status()["state"] == "applied")
params[0] = PARAMS

# the record carries its own rows: those amounts win
closes[2][-1] = rec(44, {"carry_correction": {"total_applied": "5", "applied": {A1: "2", A2: "3"}}}); reset()
st = CC.status()
check("record field: Executed state, word Applied, recorded 5", st["state"] == "executed" and st["recorded"] == 5 and CC.effect_text()[1] == "Applied")
check("record rows win over the table", CC.applied(A1) == 2 and CC.applied(ADDRS[5]) == 0 and abs(CC.locked_after(A1, 10) - 8) < 1e-9)
check("implied is 0 when the record carries it", CC.implied(closes[2][-1], 2) == 0)
check("for_address applied amount", CC.for_address(A1)["applied"] == 2 and CC.for_address(A1)["scheduled"] == T[A1])

# no field and no params match: closed, not in the record
closes[2][-1] = rec(44); params[0] = {"auto_epoch_seconds": 21600}; reset()
check("no field, no params: E44 closed, not in the record", CC.status()["state"] == "closed_no_record" and not CC.done() and CC.applied(A1) == 0)
check("reconcile: Mined gap of exactly the table is explained", "ballot 2464" in RC._mined_why(D("100") + D(str(round(CC.total(), 6))), D("100"), D(0), None, D(str(round(CC.total(), 6))), "x"))
check("reconcile: another gap keeps its reason", RC._mined_why(D("105"), D("100"), D(0), None, D(0), "x") == "x")
params[0] = PARAMS; reset()

# ballot card and timeline
h = GV._effect(dict(effect="carry_correction"))
check("ballot card: E44 burn 940.52M, Applied tag ok", "E44 burn 940.52M" in h and 'tag ok">Applied<' in h)
t = TL._cc(dict(state="applied", value=T[A1], post=2464))
check("timeline row: Applied", "Applied" in t and "ballot 2464" in t)
t2 = TL._cc(dict(state="scheduled", value=T[A1], post=2464))
check("timeline row: Scheduled before", "Scheduled" in t2)
allcopy = h + t + t2 + json.dumps(CC.api()) + CC.effect_text()[0]
check("no em or en dash", not any(d in allcopy for d in DASH))
print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
