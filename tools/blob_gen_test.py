"""Parsed blob caches see every write (1.26.180). blobs.ts is whole seconds, so two writes of the close records in the same
second (or a regroup that keeps a segment blob's old ts) used to leave analytics.epochs_raw serving the earlier copy; that is
what made established_engine_test fail now and then in a full run. Readers key on (ts, generation). Temp database, frozen clock.
Usage: python3 tools/blob_gen_test.py"""
import os, sys, tempfile, time
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "g.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, segments as S, grading as GR
if not hasattr(db, "blob_gen"): db.blob_gen = lambda k: 0   # older code: run the checks anyway (they fail there)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
real = time.time; T = int(real()); time.time = lambda: T + 0.25   # every write below lands in the same second
try:
    rec = lambda n: [{"epoch": i, "ts": T - 3600 * (n - i), "pool": 1e9, "rewards": {}, "basis": {}} for i in range(n)]
    db.put_blob(S.blob_kind(), rec(5)); A._cache.clear()
    check("first copy read", [e["epoch"] for e in A.epochs_raw()] == [0, 1, 2, 3, 4])
    g0 = db.blob_gen(S.blob_kind())
    db.put_blob(S.blob_kind(), rec(4)); A._cache.clear()
    check("a second write in the same second is seen (no stale close records)", [e["epoch"] for e in A.epochs_raw()] == [0, 1, 2, 3])
    check("its generation moved", db.blob_gen(S.blob_kind()) == g0 + 1)
    check("same ts on both copies (the case ts alone missed)", db.q1("SELECT ts FROM blobs WHERE kind=?", (S.blob_kind(),))["ts"] == T)
    check("epoch_rows follows", [r["epoch"] for r in A.epoch_rows()] == [0, 1, 2, 3])
    v1 = {"as_of": T, "epoch": 1, "chain": "poa-mainnet-1", "quorum": 4, "ttl_epochs": 16, "trusted": [], "established": [], "rows": [], "stats": {}}
    if GR.valid(v1):
        db.put_blob(GR.BLOB, v1); GR._cur.clear(); a = GR.current()
        db.put_blob(GR.BLOB, dict(v1, epoch=2)); GR._cur["chk"] = 0; b = GR.current()
        check("grading list: a second copy in the same second is seen", a and b and a["epoch"] == 1 and b["epoch"] == 2)
    else:
        print("skip grading copy check (fixture shape)")
finally:
    time.time = real
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
