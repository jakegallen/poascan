"""1.26.338: the grading index (gx_rec, gx_by) is not rebuilt from every close on a boot or a new close. gx_meta records
the close rows (position, sig) the stored rows came from: a boot with the same rows reuses them, a new close folds in
only that close, and anything else (an older row changed) rebuilds. Folded rows must equal a full build. Temp database.
Usage: python3 tools/gxappend_test.py"""
import os, sys, tempfile, time
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "g.db"); os.environ.setdefault("POASCAN_INDEXER", "0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, closestore as CS, segments as S, history as HI
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
A.params = lambda: {}
T0 = int(time.time()) - 21600 * 8
def close(n):
    # answers a{k} stay pending across closes (newest row must win), b{n} are new each close, settled from close 1 on
    p = {f"a{k:063x}": {"kind": "short", "panel": [f"poa1p{n % 3}"], "since": 0, **({"grades": [{"grader": f"poa1g{n}", "ts": T0 + n}]} if n % 2 else {})} for k in range(4)}
    p.update({f"b{n:063x}": {"kind": "long", "panel": ["poa1q"], "since": n}})
    st = [{"answer": f"b{n - 1:063x}", "passed": n % 2 == 0, "jury": [{"grader": "poa1j"}, {"grader": f"poa1j{n}"}]}] if n else []
    return {"epoch": n, "ts": T0 + 21600 * n, "pool": "10", "basis": {"pending": p, "settled": st}, "rewards": {"poa1a": str(n + 1)}}
kind = S.blob_kind(); seg = str(S.CURRENT)
def rows():
    return (sorted(tuple(r.values()) for r in db.q("SELECT answer, p, s FROM gx_rec WHERE seg=?", (seg,))),
            sorted(tuple(r.values()) for r in db.q("SELECT grader, answer FROM gx_by WHERE seg=?", (seg,))))
def full_rows():
    """What a full build stores for the current closes (gx_meta dropped, so nothing is reused)."""
    keep = rows(); raw = A.epochs_raw()
    HI._build(raw, S.CURRENT, "x", HI._fp(raw, S.CURRENT)); out = rows()
    return out, keep
def reset_mem():
    HI._gx["keys"].clear(); HI._gx.update(key=None, v=None)

CS.append_records(kind, [close(n) for n in range(3)])
HI.STATS.update(reuse=0, append=0, full=0)
v1 = HI.grading_index()
check("first call with no gx_meta builds from every close", HI.STATS == {"reuse": 0, "append": 0, "full": 1})
check("gx_meta lists the close rows", db.q1("SELECT fp FROM gx_meta WHERE seg=?", (seg,)) is not None)
reset_mem()   # a restart: the in-memory key is gone, the stored rows are not
v2 = HI.grading_index()
check("a restart with the same close rows reuses the stored rows", HI.STATS == {"reuse": 1, "append": 0, "full": 1} and v2["last"] == 2)
CS.append_records(kind, [close(3)]); A._cache.clear()   # epochs_raw is memoized 15 s
v3 = HI.grading_index()
check("a new close folds in only that close", HI.STATS == {"reuse": 1, "append": 1, "full": 1} and v3["last"] == 3)
folded = rows(); want, _ = full_rows()
check("folded rows equal a full build", folded == want)
CS.append_records(kind, [close(4), close(5)]); A._cache.clear()
reset_mem(); HI.STATS.update(reuse=0, append=0, full=0)
HI.grading_index()
check("two new closes after a restart fold in as one append", HI.STATS == {"reuse": 0, "append": 1, "full": 0})
folded = rows(); want, _ = full_rows()
check("folded rows equal a full build after two closes", folded == want)
rc = HI.gx_recs(HI.grading_index(), [f"a{0:063x}", f"b{4:063x}"])
check("newest pending row wins for an answer pending in many closes", rc[f"a{0:063x}"]["p"][0] == 5)
check("settled row of the newest close is stored", rc[f"b{4:063x}"]["s"][0] == 5 and rc[f"b{4:063x}"]["s"][1] is False)
# an older row changes (same position, new sig): never folded, always a full build
db.write("UPDATE close_rows SET sig='changed' WHERE kind=? AND pos=1", (kind,)); CS._ver[kind] += 1; CS._lru.clear()
reset_mem(); HI.STATS.update(reuse=0, append=0, full=0); A._epochs.clear(); A._cache.clear()
HI.grading_index()
check("a changed older close row forces a full build", HI.STATS == {"reuse": 0, "append": 0, "full": 1})
# records with no stored row (no loc) never trust gx_meta
reset_mem(); HI.STATS.update(reuse=0, append=0, full=0)
real = A.epochs_raw; A.epochs_raw = lambda: [dict(e) for e in real()]
HI.grading_index()
check("records without a stored row take a full build and clear gx_meta", HI.STATS["full"] == 1 and db.q1("SELECT fp FROM gx_meta WHERE seg=?", (seg,)) is None)
A.epochs_raw = real
print("FAILED: " + "; ".join(fails) if fails else "all ok"); sys.exit(1 if fails else 0)
