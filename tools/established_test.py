"""Unit test for analytics.established_set() under minepoa's engine rule (1.26.140, estfold.py): the segment's genesis
import seeds the set, established_after adds, established_removed drops (unless slash_pardons voids a slash removal),
and trusted graders, grading seats and jury seats neither grant nor keep standing.
Usage: python3 tools/established_test.py (uses a temp database, no network)."""
import os, sys, tempfile
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, estfold as EF, segments as S

def addr(c): return "poa1" + c * 40
CARRIED, NEW, DROPPED, RESTORED, NEVER, TRUSTED, STALE, PARDONED, SLASHED = (addr(c) for c in "CNDRVTSPQ")

def close(n, after=(), removed=(), served=(), jury=(), slashed=()):
    return {"epoch": n, "ts": 1792000000 + n * 21600, "pool": 1e9, "rewards": {}, "challenges": {}, "propagation": {},
            "basis": {"established_after": list(after), "established_removed": list(removed), "slashed": list(slashed),
                      "graders_served": {a: 1 for a in served},
                      "settled": [{"from": NEVER, "passed": True, "jury": [{"grader": g, "aligned": True} for g in jury]}]}}

def main():
    db.init()
    db.put_blob("params", {"estab_ttl": 6, "trusted_graders": [TRUSTED], "slash_pardons": {"2": [PARDONED]}})
    seg = S.selected()
    EF.CFG["imports"] = {str(seg): {"established": [CARRIED, DROPPED, STALE, PARDONED, SLASHED, RESTORED], "established_count": 6,
                                    "url": "x", "sha256": "x", "final_checkpoint_height": 1, "agents": 6}}
    db.put_blob(S.blob_kind(), [
        close(0),
        close(1, after=[NEW], served=[CARRIED, DROPPED, RESTORED, STALE, TRUSTED]),
        close(2, removed=[DROPPED, RESTORED, PARDONED, SLASHED], slashed=[PARDONED, SLASHED]),
        close(3, jury=[RESTORED], served=[RESTORED]),            # seated again after its drop: seats don't restore it
        close(8, after=["poa1" + "X" * 40], served=[CARRIED], jury=[CARRIED]),
    ])
    A._cache.clear(); s = A.established_set()
    want = {CARRIED: True, NEW: True, DROPPED: False, RESTORED: False, NEVER: False, TRUSTED: False, STALE: True, PARDONED: True, SLASHED: False}
    fails = [a for a, w in want.items() if (a in s) != w]
    for a, w in want.items(): print(("ok   " if (a in s) == w else "FAIL ") + f"{a[:6]}{a[4]} expect {w}")
    est, le, why = A.established_fold()
    ok = why[CARRIED] == ("import", None) and why[NEW] == ("added", 1) and why[DROPPED] == ("removed", 2)
    print(("ok   " if ok else "FAIL ") + "basis per Agent: import, added, removed"); fails += [] if ok else ["why"]
    ok = EF.drop_close(None, 6) == 6 and EF.drop_close(1, 6) == 8
    print(("ok   " if ok else "FAIL ") + "drop close: L + ttl + 1, L = -1 when none (E6 for the genesis import)"); fails += [] if ok else ["drop"]
    ok = len(EF.load_cfg()["imports"]["2"]["established"]) == 81
    print(("ok   " if ok else "FAIL ") + "established.json: segment 2 genesis import flags 81 Agents"); fails += [] if ok else ["cfg"]
    sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
