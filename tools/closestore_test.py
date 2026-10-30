"""Close records one row per close (1.26.235, poascan/closestore.py). Temp database.
* migration: rows are rebuilt from the blob streamed in small chunks (never the whole text), the same records come back
  (full_close equals json.loads of the blob, byte for byte as JSON), and a second run is a no-op (idempotent);
* backward compatible: the blob is still written with every store, so a build from before 1.26.235 reads the same data;
  a blob an older build wrote later (rollback, then forward again) is picked up and the rows rebuilt;
* epochs_raw keeps slim records only; pending_of reads one close's list from its row; pend_ix answers per answer lookups;
  records.index serves the hash and size stored at ingest; epochs_same compares by stored sha1.
Usage: python3 tools/closestore_test.py"""
import os, sys, tempfile, json, time, tracemalloc
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "c.db"); os.environ.setdefault("POASCAN_INDEXER", "0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, closestore as CS, records as RR, segments as S, indexer as I
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
ids = [f"{i:064x}" for i in range(4000)]
T0 = int(time.time()) - 21600 * 13
def close(n, k):
    p = {t: {"kind": "short" if i % 3 else "appeal", "panel": ["poa1p" + str(i % 7)], "originalPassed": False, "since": i % 5,
             "grades": [{"grader": "poa1g" + str(j), "score": 2, "ts": 1000 + j} for j in range(i % 3 + (1 if i == n else 0))]} for i, t in enumerate(ids[:k])}
    return {"epoch": n, "ts": T0 + 21600 * n, "pool": "10", "note": "\u00e9 \u2192 ok", "basis": {"challenge_eligible": ["poa1a"], "pending": p,
            "settled": [{"answer": ids[n], "passed": True, "jury": [{"grader": "poa1g1", "aligned": True}]}]}, "rewards": {"poa1a": "1.5"}}
recs = [close(n, 500 + 300 * n) for n in range(10)] + [{"epoch": 10, "ts": T0 + 216000, "basis": {"settled": []}, "rewards": {}}]
text = json.dumps(recs)
kind = S.blob_kind()
db.write("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?,?,?)", (kind, T0, text))   # as an older build stores it
CS.CHUNK = 4096   # many chunks per record: the decoder must resume across chunk edges
tracemalloc.start(); done = CS.migrate(); peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
check("migration rebuilt the segment's rows", done == [kind] and CS.meta(kind)["n"] == len(recs))
tracemalloc.start(); json.loads(text); old_peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
check(f"migration peak {peak // 1024} KB, below one json.loads of the blob {old_peak // 1024} KB (streamed, one close at a time)", peak < old_peak)
check("a second migration is a no-op (idempotent)", CS.migrate() == [] and CS.current(kind))
A._cache.clear(); A._epochs.clear()
er = A.epochs_raw()
check("epochs_raw: slim records, no pending list kept", len(er) == len(recs) and all("pending" not in (e.get("basis") or {}) for e in er))
check("full_close gives each record back exactly (keys in order)", json.dumps([A.full_close(e) for e in er]) == text)
check("a record without pending stays as it was", A.full_close(er[-1]) == recs[-1] and A.pending_of(er[-1]) is None)
check("pending_of reads one close's list", A.pending_of(er[4]) == recs[4]["basis"]["pending"])
check("the pending LRU stays at 2 closes", len(CS._lru) <= CS.LRU_MAX == 2)
g = A.pending_get(er[6], [ids[0], ids[2400], "nope"])
check("pend_ix: per answer lookup without a parse", g == {ids[0]: recs[6]["basis"]["pending"][ids[0]]})
check("pend_ix: an answer not in that close is absent", A.pending_get(er[1], [ids[1500]]) == {})
n_ix = db.q1("SELECT COUNT(*) AS n FROM pend_ix WHERE kind=?", (kind,))["n"]; n_pairs = sum(len(r["basis"].get("pending") or {}) for r in recs)
check(f"pend_ix holds runs, not every (close, answer) pair ({n_ix} vs {n_pairs})", n_ix < n_pairs)
ix = RR.index(); b = RR.canonical(recs[3])
check("records.index: stored hash and size equal the canonical bytes", ix[3]["sha256"] == RR.sha256(b) and ix[3]["bytes"] == len(b) and RR.record(3)[0] == b)
check("epochs_same: the same list is unchanged", A.epochs_same(kind, json.loads(text)))
r2 = json.loads(text); r2[2]["basis"]["pending"][ids[1]]["kind"] = "appeal"
check("epochs_same: one changed row is a change", not A.epochs_same(kind, r2))
# indexer store: blob (for older builds) and rows together; only the changed row is rewritten
before = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=?", (kind,))}
time.sleep(1.1); I.store_epochs(r2)
after = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=?", (kind,))}
check("store_epochs: only the changed close's row is rewritten", [p for p in after if after[p] != before.get(p)] == [2])
check("store_epochs: the blob holds the new list (an older build reads it)", db.get_blob(kind)[0] == r2)
A._cache.clear()
check("epochs_raw follows the new copy", A.pending_of(A.epochs_raw()[2])[ids[1]]["kind"] == "appeal")
# rollback then forward: an older build writes only the blob
time.sleep(1.1); r3 = r2 + [close(11, 600)]
db.write("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?,?,?)", (kind, int(time.time()), json.dumps(r3)))
check("a blob an older build wrote is seen as newer than the rows", not CS.current(kind))
A._cache.clear(); er = A.epochs_raw()
check("and the rows are rebuilt from it", len(er) == 12 and json.dumps([A.full_close(e) for e in er]) == json.dumps(r3) and CS.current(kind))
# an old build reading the database: blobs row is the whole list as before
check("old read path: json.loads of the blobs row gives the list", json.loads(db.q1("SELECT json FROM blobs WHERE kind=?", (kind,))["json"]) == r3)
for s in ("[]", " [ ]\n", "null"):
    db.write("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?,?,?)", ("epochs:s9", 1, s)); CS._gen.pop("epochs:s9", None)
    CS.rebuild("epochs:s9")
    check(f"edge blob {s!r}: no rows", CS.meta("epochs:s9")["n"] == 0)
print("\nall ok" if not fails else f"\n{len(fails)} FAILED"); sys.exit(1 if fails else 0)
