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
# 1.26.359: equal addresses, small flat dicts (jury seats) and empty lists are shared, and the JSON never changes
def jclose(n):
    st = [{"answer": f"{n:02d}{i:062x}", "from": "poa1author" + "x" * 30, "passed": True, "losers": [], "winners": [],
           "jury": [{"grader": "poa1g" + "y" * 30, "aligned": True}, {"grader": "poa1h" + "y" * 30, "aligned": 1}]} for i in range(3)]
    return {"epoch": n, "ts": T0 + 21600 * n, "pool": "10", "basis": {"pending": {}, "settled": st}, "rewards": {}}
CS.append_records(kind, [jclose(4), jclose(5)])
e = CS.slim(kind); s4, s5 = e[4]["basis"]["settled"], e[5]["basis"]["settled"]
check("an address repeated across closes is one string", s4[0]["from"] is s5[2]["from"])
check("equal jury seats are one dict", s4[0]["jury"][0] is s5[1]["jury"][0])
check("aligned True and aligned 1 stay apart", s4[0]["jury"][1]["aligned"] == 1 and type(s4[0]["jury"][1]["aligned"]) is int and s4[0]["jury"][0]["aligned"] is True)
check("empty lists are one list", s4[0]["losers"] is s5[0]["winners"])
check("the shared records still read like a fresh parse", json.dumps(e) == json.dumps([json.loads(r["slim"]) for r in db.q("SELECT slim FROM close_rows WHERE kind=? ORDER BY pos", (kind,))]))
print("FAILED: " + "; ".join(fails) if fails else "all ok"); sys.exit(1 if fails else 0)
