"""1.26.82 accuracy and resilience fixes. Temp database, no network. Usage: python3 tools/accuracy_test.py
* Grader counts come from each close's grade rows (settled jury seats plus pending grades sealed in that epoch), not
  basis.graders_served, which undercounts (E12: 16 named, 63 graders and 1,570 grades in the rows). The record's own
  figure stays as graders_official and grades_official.
* Max reward counts Agents paid the close's top reward from its rewards row, not final_payout.capped (E12: 152 vs 210).
* A failed indexer job is not recorded as ran and retries after JOB_RETRY_S, not a full interval.
* The node's txs and final counters restarting at a checkpoint read explained, with the time, when they match the archive.
* The guard treats 30% steal as throttled."""
import json, os, sys, tempfile, threading, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "a.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
from poascan import db, analytics as A, indexer as I, guard as GD
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
ad = lambda c: "poa1" + c * 40
t0 = 1_000_000; t1 = t0 + 21600
e11 = {"epoch": 0, "ts": t0, "pool": 1e9, "rewards": {}, "basis": {}}
e12 = {"epoch": 1, "ts": t1, "pool": 1e9,
       "rewards": {ad("A"): "709920.144234", ad("B"): "709920.144234", ad("C"): "354960.072117", ad("D"): "0"},
       "basis": {"graders_served": {ad("G"): 2},
                 "settled": [{"answer": "a1", "from": ad("A"), "passed": True, "jury": [{"grader": ad("G"), "aligned": True}, {"grader": ad("H"), "aligned": True}]}],
                 "pending": {"p1": {"grades": [{"grader": ad("J"), "ts": t0 + 10}, {"grader": ad("K"), "ts": t0 - 10}], "since": 1, "panel": [ad("J")]},
                             "p2": {"grades": [], "since": 0}, "p3": {"grades": [{"grader": ad("H"), "ts": t1}, {"grader": ad("L"), "ts": t1 + 5}], "since": 1}},
                 "final_payout": {"capped": {ad("A"): "1", ad("B"): "1", ad("C"): "1"}}}}
c = A.grade_counts(e12, t0)
check("grade_counts: settled jury seats plus pending grades inside the epoch only", dict(c) == {ad("G"): 1, ad("H"): 2, ad("J"): 1})
db.put_blob("epochs", [e11, e12]); A._cache.clear()
r = A.epoch_rows()[-1]
check("epoch row: graders and grades from the rows, the record's figure kept as *_official", r["graders"] == 3 and r["grades"] == 4 and r["graders_official"] == 1 and r["grades_official"] == 2)
check("epoch row: paid_at_max from the rewards row (2), not final_payout.capped (3)", r["paid_at_max"] == 2 and r["ceiling_capped"] == 3)
src = open(os.path.join(ROOT, "poascan", "views.py"), encoding="utf-8").read()
check("Max reward stat reads paid_at_max", 'stat("Max reward", intc(r.get("paid_at_max", 0))' in src and 'intc(r["ceiling_capped"]), tip="Agents paid the per-epoch maximum"' not in src)

# ---- failed jobs retry soon
I.JOB_RETRY_S = 30
runs = []
def bad(): runs.append(time.time()); raise I.Busy("timed out")
stop = threading.Event()
real_sleep = I.time.sleep
db.put_blob("job:bad", {"ran": 123})
th = threading.Thread(target=I.run_forever, kwargs=dict(stop=stop, jobs=[("bad", bad, 3600, None)]), daemon=True); th.start()
real_sleep(2.5); stop.set(); th.join(15)
check("failed job: not recorded as ran", (db.get_blob("job:bad")[0] or {}).get("ran") == 123)
src = open(os.path.join(ROOT, "poascan", "indexer.py"), encoding="utf-8").read()
check("failed job: next try after JOB_RETRY_S, not the full interval", "last[name] = now - every + JOB_RETRY_S" in src and "if ok: db.put_blob(\"job:\" + name" in src)

# ---- reconcile: node counters restart at a checkpoint
from poascan import reconcile as RC
now = int(time.time())
db.write_tx([("INSERT INTO txs(id, type, ts, final) VALUES(?, 'challenge', ?, ?)", ("t%d" % i, now - 100000 + i * 10, 1 if i % 2 else 0), False) for i in range(100)])
RC.NODE_RESET_TS = now - 100000 + 80 * 10   # the newest 20 synthetic txs
db.put_blob("status", {"txs": 20, "final": 10, "as_of": "2026-10-24T05:00:00Z", "epochs_closed": 2, "supply": "0"})
A._cache.clear()
try:
    rows = {x["key"]: x for x in RC.reconcile()["rows"]} if hasattr(RC, "reconcile") else None
except Exception as e:
    rows = None; print("reconcile:", type(e).__name__, e)
if rows is None:
    fn = [getattr(RC, n) for n in dir(RC) if callable(getattr(RC, n)) and n in ("report", "data", "build", "rows")]
    rows = {x["key"]: x for x in fn[0]()["rows"]} if fn else {}
check("reconcile: txs reads explained with the restart time", rows.get("txs", {}).get("state") == "explained" and "restart at a recovery checkpoint" in (rows["txs"].get("reason") or ""))
check("reconcile: final reads explained too", rows.get("final", {}).get("state") == "explained")
db.put_blob("status", {"txs": 40, "final": 10, "as_of": "2026-10-24T05:00:00Z", "epochs_closed": 2, "supply": "0"}); A._cache.clear()
rows = {x["key"]: x for x in (RC.reconcile() if hasattr(RC, "reconcile") else fn[0]())["rows"]}
check("reconcile: a txs count that does not match the archive since the reset stays differs", rows["txs"]["state"] == "differs")

import poascan.server as SV
try: SV.api("/api/epoch/999999", {}); check("api: an epoch past the last close is 404 epoch not closed yet", False)
except SV.NotFound as e: check("api: an epoch past the last close is 404 epoch not closed yet", str(e) == "epoch not closed yet")

check("guard: 30% steal is throttled, 10% is a hang", GD.STEAL_THROTTLED == 0.3)
print("ALL OK" if not fails else f"{len(fails)} FAILED"); sys.exit(1 if fails else 0)
