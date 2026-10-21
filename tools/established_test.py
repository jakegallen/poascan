"""Unit test for analytics.established_set(): close records publish established changes, not the full set.
Usage: python3 tools/established_test.py (uses a temp database, no network)."""
import os, sys, tempfile
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A

def addr(c): return "poa1" + c * 40
CARRIED, NEW, DROPPED, RESTORED, NEVER, TRUSTED, STALE = (addr(c) for c in "CNDRVTS")

def close(n, after=(), removed=(), served=(), jury=()):
    return {"epoch": n, "ts": 1792000000 + n * 21600, "pool": 1e9, "rewards": {}, "challenges": {}, "propagation": {},
            "basis": {"established_after": list(after), "established_removed": list(removed),
                      "graders_served": {a: 1 for a in served},
                      "settled": [{"from": NEVER, "passed": True, "jury": [{"grader": g, "aligned": True} for g in jury]}]}}

def main():
    db.init()
    db.put_blob("params", {"estab_ttl": 6, "trusted_graders": [TRUSTED]})
    db.put_blob("epochs", [
        close(0),
        close(1, after=[NEW], served=[CARRIED, DROPPED, RESTORED, STALE]),  # carried standing: seated, never in established_after
        close(2, removed=[DROPPED, RESTORED]),
        close(3, jury=[RESTORED]),            # restored off-record; seated again after its drop
        close(8, after=["poa1" + "X" * 40], served=[CARRIED], jury=[CARRIED]),  # latest close lists only one newcomer
    ])
    A._cache.clear(); s = A.established_set()
    want = {CARRIED: True, NEW: True, DROPPED: False, RESTORED: True, NEVER: False, TRUSTED: True, STALE: False}
    # RESTORED's last seat is epoch 3, inside ttl 6 of epoch 8 (3 > 2). STALE's last seat is epoch 1, outside it.
    fails = [a for a, w in want.items() if (a in s) != w]
    old = set(A.epochs_raw()[-1]["basis"]["established_after"])
    assert CARRIED not in old and NEW not in old, "regression guard: latest established_after alone misses standing agents"
    for a, w in want.items(): print(("ok   " if (a in s) == w else "FAIL ") + f"{a[:6]}{a[4]} expect {w}")
    sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
