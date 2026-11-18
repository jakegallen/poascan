"""Chain KPI closes series (POASCAN data ask 1a): analytics.chain_closes maps the last N close records to the five KPI
fields (backlog, awaiting_graders, passed, failed, burn_pct) and the server routes /api/chain/closes to it. Archive only,
counts only, additive (no route removed). Usage: python3 tools/chain_closes_test.py (temp database, no network)."""
import os, sys, tempfile
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import analytics as A

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

# Synthetic close records, oldest first, carrying the exact fields epoch_rows() produces.
A.epoch_rows = lambda: [
    dict(epoch=1, close_ts=100, pending=5, pending_empty_panel=2, settled_passed=10, settled_failed=1, burn_pct=12.0),
    dict(epoch=2, close_ts=200, pending=3, pending_empty_panel=0, settled_passed=8, settled_failed=2, burn_pct=14.6),
]
out = A.chain_closes(24)
check("maps each close to the five KPI fields (oldest first)", out == [
    dict(epoch=1, close_ts=100, backlog=5, awaiting_graders=2, passed=10, failed=1, burn_pct=12.0),
    dict(epoch=2, close_ts=200, backlog=3, awaiting_graders=0, passed=8, failed=2, burn_pct=14.6)])
check("limit returns the most recent tail", [r["epoch"] for r in A.chain_closes(1)] == [2])
check("a bad limit falls back to 24 (all available rows)", len(A.chain_closes("x")) == 2)
check("limit clamps into [1, 96]", len(A.chain_closes(0)) == 1 and len(A.chain_closes(999)) == 2)

src = open(os.path.join(ROOT, "poascan", "server.py")).read()
check("server routes /api/chain/closes to chain_closes (additive)", '"/api/chain/closes"' in src and "A.chain_closes(" in src)
check("chain_closes reads the archive only (no upstream fetch)",
      "fetch(" not in open(os.path.join(ROOT, "poascan", "analytics.py")).read().split("def chain_closes(")[1].split("\ndef ")[0])

# 1c: pending answers per origin epoch bucketed by seal count 0..3 (maps pending_by_epoch rows, drops 4+/unknown)
A.pending_by_epoch = lambda: {"rows": [{"epoch": 5, "seals": {"0": 2, "1": 1, "2": 0, "3": 3, "4+": 9, "unknown": 1}},
                                       {"epoch": 6, "seals": {}}]}
check("1c maps rows to origin_epoch + seal_0..3 (4+ and unknown dropped)", A.pending_by_origin_seals() == [
    dict(origin_epoch=5, seal_0=2, seal_1=1, seal_2=0, seal_3=3), dict(origin_epoch=6, seal_0=0, seal_1=0, seal_2=0, seal_3=0)])
check("server routes /api/chain/pending-by-origin to pending_by_origin_seals", '"/api/chain/pending-by-origin"' in src and "A.pending_by_origin_seals()" in src)

# 1b: the open-epoch counts and the close countdown on /api/v1/summary (names agreed with POASCAN)
an = open(os.path.join(ROOT, "poascan", "analytics.py")).read()
check("1b: open_epoch exposes answers_so_far, graders_so_far and closing_in",
      "answers_so_far=answers" in an and "graders_so_far=graders" in an and "closing_in=(last_close + period" in an)
check("1b: /api/v1/summary carries closing_in", 'closing_in=o.get("closing_in")' in open(os.path.join(ROOT, "poascan", "agentapi.py")).read())

# 4a: next anchor ETA + cadence from the anchors table (seed three anchors 100 s apart)
from poascan import db
import datetime as _dt
db.init()
base = _dt.datetime(2026, 11, 18, 0, 0, 0, tzinfo=_dt.timezone.utc)
iso = lambda sec: (base + _dt.timedelta(seconds=sec)).isoformat().replace("+00:00", "Z")
db.write("INSERT INTO anchors(height,chain,tx,state_root,anchored_by,memo,anchored_at,segment) VALUES(?,?,?,?,?,?,?,1)",
         [(1, "base", "t1", "r", "by", "m", iso(0)), (2, "base", "t2", "r", "by", "m", iso(100)), (3, "base", "t3", "r", "by", "m", iso(200))], many=True)
e = A.anchor_eta()
check("4a: cadence is the median anchor gap", e["cadence_s"] == 100)
check("4a: next_anchor_eta is the last anchor plus the cadence", e["next_anchor_eta"] == e["last_anchor_ts"] + 100 and e["last_anchor_ts"] == int(base.timestamp()) + 200)
check("4a: counts the anchors in the window", e["anchors_in_window"] == 3)
check("server routes /api/network/anchors-eta to anchor_eta", '"/api/network/anchors-eta"' in src and "A.anchor_eta()" in src)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
