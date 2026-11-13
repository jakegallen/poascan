"""1.26.323: fill_epoch is the first archived close after fill_ts, from every segment's close archive.
A fill at a close's exact second belongs to the next epoch. Never 0 (a genesis or cut close is not a fill epoch);
null when unknown. The seven live fills are checked against POAScan's own published close times (not a third-party list).

Usage: python3 tools/fill_epoch_test.py
"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

# Segment 1 (poa-mainnet-1) and the start of segment 2, from GET https://poascan.io/api/v1/epochs
# on 13 Nov 2026. close_ts values were checked against that archive, not taken on trust from elsewhere.
# Segment 2 continues past E0; only the first close is needed to show the current-segment-only bug (all
# pre-cut fills would hash to epoch 0). A frozen last close stands in for the open-epoch case.
SEG1 = [
    (0, 1792429396),  # 19 Oct 2026 9:03:16 AM PT, genesis close
    (1, 1792451026),
    (2, 1792472676),
    (3, 1792494347),
    (4, 1792516022),
    (5, 1792537717),
    (6, 1792559408),  # 20 Oct 2026 9:10:08 PM PT
    (7, 1792581132),
    (8, 1792602878),
    (9, 1792624586),
    (10, 1792768855),
    (11, 1792790634),  # 23 Oct 2026 1:23:54 PM PT
    (12, 1792812426),  # 23 Oct 2026 7:27:06 PM PT
    (13, 1792834256),
    (14, 1792856416),
]
SEG2_FIRST = (0, 1792878384)  # 24 Oct 2026 1:46:24 PM PT, genesis cut close, lifetime 15
# Frozen current-segment tail: epochs 0..2 of segment 2 (enough for open-epoch arithmetic).
SEG2 = [SEG2_FIRST, (1, 1792900005), (2, 1792921663)]

def rows_of(pairs, segment):
    return [dict(epoch=e, close_ts=t, segment=segment) for e, t in pairs]

ALL = rows_of(SEG1, 1) + rows_of(SEG2, 2)
CUR = rows_of(SEG2, 2)

# The seven filled offers, fill_ts from POAScan's own /api/v1/swaps rows, expected epoch from the archive above.
FILLS = [
    ("9d095580", 1792551896, 6),    # 20 Oct 2026 7:04:56 PM PT, before E6 close
    ("3122d34a", 1792774185, 11),   # 23 Oct 2026 8:49:45 AM PT
    ("39705dd2", 1792787496, 11),
    ("24403dc0", 1792788023, 11),
    ("3e0613bf", 1792789265, 11),
    ("de1ddefb", 1792789857, 11),
    ("cb83e695", 1792791356, 12),   # 23 Oct 2026 1:35:56 PM PT, after E11 close 1:23:54 PM PT
]

os.environ.setdefault("POASCAN_DB", os.path.join(tempfile.mkdtemp(), "t.db"))
from poascan.swap import host_poascan as HP

class FakeA:
    @staticmethod
    def epoch_rows_all():
        return list(ALL)
    @staticmethod
    def epoch_rows():
        return list(CUR)

HP._A = FakeA

# Current-segment-only (the 1.26.322 hook) would return segment 2's epoch 0 for every pre-cut fill.
import bisect
def old_hook(ts):
    rows = CUR
    k = bisect.bisect_right([r["close_ts"] for r in rows], int(ts))
    if k < len(rows): return int(rows[k]["epoch"])
    return None

for oid, ts, expect in FILLS:
    got = HP.epoch_of_ts(ts)
    check(f"{oid} fill_ts={ts} -> {expect} (got {got})", got == expect)
    check(f"{oid} current-segment-only would have been 0 (got {old_hook(ts)})", old_hook(ts) == 0)

# Exact close second belongs to the next epoch.
check("fill at E11 close second 1792790634 -> 12", HP.epoch_of_ts(1792790634) == 12)
check("one second before E11 close -> 11", HP.epoch_of_ts(1792790633) == 11)

# Never 0: a ts before the first close (segment 1 genesis) is null, not epoch 0.
check("before first close is null, not 0", HP.epoch_of_ts(SEG1[0][1] - 1) is None)
check("at segment 2 cut close second is not 0 (next is E1 of segment 2)", HP.epoch_of_ts(SEG2_FIRST[1]) == 1)
check("in the cut gap (after last s1 close, before s2 E0 close) is null, not 0",
      HP.epoch_of_ts(SEG1[-1][1] + 1) is None)
check("epoch_of_ts(None) is None", HP.epoch_of_ts(None) is None)
check("epoch_of_ts(0) is None", HP.epoch_of_ts(0) is None)

# Open epoch of the current segment, only when status confirms no later close.
LAST = SEG2[-1][1]
class FakeDb:
    blob = ({"as_of": "2026-10-25T12:00:00Z", "epochs_closed": len(CUR)}, LAST + 100)
    @staticmethod
    def get_blob(kind):
        return FakeDb.blob

HP._db = FakeDb
check("after newest close, status confirms, open epoch is 3", HP.epoch_of_ts(LAST + 10) == 3)
FakeDb.blob = ({"as_of": "2026-10-25T09:00:00Z", "epochs_closed": len(CUR) - 1}, LAST + 100)
check("after newest close, epochs_closed does not match current rows: null", HP.epoch_of_ts(LAST + 10) is None)
FakeDb.blob = ({"as_of": "2026-10-25T09:00:00Z", "epochs_closed": len(CUR)}, LAST + 5)
check("status read taken before the fill: null", HP.epoch_of_ts(LAST + 10) is None)

# Local ext_ref backfill reads only stored bodies, never invents fill_usd.
from poascan.swap import indexer as IX
PROOF = "2CmCr8HQBncY4K5kiRbScFKiwrFwUJ6sfcMoKAhMFQfWsdU1TqKngnBbdgfSGaKfp7XEcJe8ddKYdEm85uX9YZQz"
check("event body with proof.ref yields ext_ref",
      IX._ref_from_stored("b"*64, json.dumps({"type": "swap-fill", "proof": {"ref": PROOF}})) == PROOF)
check("empty event body and no tx_detail: no ext_ref invented",
      IX._ref_from_stored("c"*64, "{}") is None)

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
