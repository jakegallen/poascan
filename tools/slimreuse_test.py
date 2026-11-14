"""1.26.336: closestore.slim keeps the records it already parsed for unchanged rows, so a new close parses one slim
record, not every close (a full re-parse held two copies, about 400 MB each at 80 closes). Temp database.
Usage: python3 tools/slimreuse_test.py"""
import os, sys, tempfile, json, time
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "s.db"); os.environ.setdefault("POASCAN_INDEXER", "0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, closestore as CS, segments as S
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
T0 = int(time.time()) - 21600 * 6
def close(n):
    p = {f"{n:02d}{i:062x}": {"kind": "short", "panel": ["poa1p"], "since": n} for i in range(50)}
    return {"epoch": n, "ts": T0 + 21600 * n, "pool": "10", "basis": {"pending": p, "settled": []}, "rewards": {"poa1a": str(n + 1)}}
kind = S.blob_kind()
CS.store_epochs(kind, [close(n) for n in range(3)]) if hasattr(CS, "store_epochs") else CS.append_records(kind, [close(n) for n in range(3)])
a = CS.slim(kind)
check("three slim records", len(a) == 3 and all(isinstance(e, CS.Close) for e in a))
parsed = []; real = json.loads
CS.json.loads = lambda t, *x, **k: (parsed.append(1), real(t, *x, **k))[1]
b = CS.slim(kind)
check(f"an unchanged read parses nothing ({len(parsed)})", len(parsed) == 0 and all(x is y for x, y in zip(a, b)))
CS.json.loads = real
CS.append_records(kind, [close(3)])
CS.json.loads = lambda t, *x, **k: (parsed.append(1), real(t, *x, **k))[1]
c = CS.slim(kind)
CS.json.loads = real
check(f"a new close parses one slim record ({len(parsed)})", len(parsed) == 1 and len(c) == 4)
check("the earlier records are the same objects", all(x is y for x, y in zip(a, c[:3])))
check("every record reads like a fresh parse", json.dumps(c) == json.dumps([json.loads(r["slim"]) for r in db.q("SELECT slim FROM close_rows WHERE kind=? ORDER BY pos", (kind,))]))
check("loc points at each row", [e.loc[1] for e in c] == [r["pos"] for r in db.q("SELECT pos FROM close_rows WHERE kind=? ORDER BY pos", (kind,))])
check("pending of a reused record still reads its own row", len(A.pending_of(c[1]) or {}) == 50 and next(iter(A.pending_of(c[1]))).startswith("01"))
# a changed row (same position) is parsed again
db.write("UPDATE close_rows SET sig='x' WHERE kind=? AND pos=?", (kind, c[0].loc[1]))
d = CS.slim(kind)
check("a row whose sig changed is parsed again", d[0] is not c[0] and d[0] == c[0] and all(x is y for x, y in zip(c[1:], d[1:])))
print("FAILED: " + "; ".join(fails) if fails else "all ok"); sys.exit(1 if fails else 0)
