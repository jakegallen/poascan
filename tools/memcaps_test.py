"""Memory caps (1.26.234): the page cache counts the memory a page holds (sys.getsizeof), not its length; the address
cache drops copies too old to serve; the share card cache is smaller; /ops/memory reports cheap memory stats behind
the ops token. Temp database. Usage: python3 tools/memcaps_test.py"""
import os, sys, tempfile, time, re
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "d.db"); os.environ.setdefault("POASCAN_INDEXER", "0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, htmlcache as HC, views as V, og as OG, memstats as MS
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
HC._c.clear(); HC._bytes[0] = 0; mb = HC.MAX_BYTES; HC.MAX_BYTES = 100_000
page = "x" * 5000 + "\u2192"   # one arrow: Python keeps every character in 2 bytes
HC.put(HC.key("/a", {}, None, False), page)
check("a page counts its memory, not its length", HC.state()["bytes"] == sys.getsizeof(page) and sys.getsizeof(page) > 2 * len(page) - 10)
for i in range(40): HC.put(HC.key(f"/p{i}", {}, None, False), page)
st = HC.state()
check("the cap holds in real bytes", st["bytes"] <= HC.MAX_BYTES and st["bytes"] == sum(e[2] for e in HC._c.values()))
check("the oldest copy goes first", HC.get(HC.key("/p39", {}, None, False), 15) and not HC.get(HC.key("/a", {}, None, False), 15))
HC.put(HC.key("/p39", {}, None, False), page + "y")
check("a replaced copy keeps the tally exact", HC._bytes[0] == sum(e[2] for e in HC._c.values()))
HC.MAX_BYTES = mb
now = time.time()
V._addr_cache.clear(); V._addr_swept[0] = 0
V._addr_cache["old"] = (now - 4000, {"txs": []}, now - V.ADDR_STALE - 5)
V._addr_cache["new"] = (now, {"txs": []}, now - 10)
with V._addr_lock: V._addr_sweep(now)
check("address copies past ADDR_STALE are dropped, fresh ones kept", "old" not in V._addr_cache and "new" in V._addr_cache)
V._addr_cache["old2"] = (now - 4000, {}, now - V.ADDR_STALE - 5)
with V._addr_lock: V._addr_sweep(now + 10)
check("the sweep runs at most once a minute", "old2" in V._addr_cache)
check("address cache max 1000, share cards 120", V.ADDR_MAX == 1000 and OG._MAX == 120)
from poascan import fastindex as FX
FX._addr_cache.clear(); real = (FX.enabled, FX._get, FX._state)
FX.enabled = lambda: True; FX._state = lambda: {}
FX._get = lambda q, kind, visitor=True: {"rows": [{"balance": "1", "tx_count": 1}], "history": []}
addrs = ["poa1" + c * 44 for c in "ABCDEFGHJK"]
for x in addrs[:3]: FX.address(x)
k0 = next(iter(FX._addr_cache)); FX._addr_cache[k0] = (time.time() - FX.ADDR_CACHE_S - 1, FX._addr_cache[k0][1])
FX.address(addrs[3])
check("fast index address copies past 60 s go on the next insert", k0 not in FX._addr_cache and len(FX._addr_cache) == 3 and FX.ADDR_CACHE_MAX == 200)
FX.enabled, FX._get, FX._state = real
r = MS.report()
check("memory report: RSS, glibc heap, Python blocks, gc, caches", r["proc"].get("VmRSS") and r["malloc"] and {"arena", "in_use", "free", "mmap"} <= set(r["malloc"])
      and r["py_blocks"] > 0 and len(r["gc"]) == 3 and {"html", "analytics", "address", "og"} <= set(r["caches"]))
check("html cache stats in the report", r["caches"]["html"]["max_bytes"] == HC.MAX_BYTES)
src = open(os.path.join(ROOT, "poascan", "server.py"), encoding="utf-8").read()
check("/ops/memory sits behind ops_gate", 'if path == "/ops/memory": return self.ops_memory(path, qs)' in src and "def ops_memory" in src
      and "g = self.ops_gate(path, {}, lambda q: (None, None))" in src)
ft = open(os.path.join(ROOT, "fly.toml"), encoding="utf-8").read(); dk = open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8").read()
check("fixed glibc mmap and trim thresholds on Fly and in the image", 'MALLOC_MMAP_THRESHOLD_ = "131072"' in ft and 'MALLOC_TRIM_THRESHOLD_ = "131072"' in ft
      and "MALLOC_MMAP_THRESHOLD_=131072" in dk and "MALLOC_TRIM_THRESHOLD_=131072" in dk and 'MALLOC_ARENA_MAX = "2"' in ft)
# 1.26.235: close records grow every close; what stays in memory must not (closestore.py, history gx tables)
import json, tracemalloc
from poascan import analytics as A, closestore as CS, segments as S, history as HI, receipts as RC, cohorts as CO
def closes(n, k=3000):
    ids = [f"{i:064x}" for i in range(k + 50 * n)]; T = int(time.time()) - 21600 * (n + 1); out = []
    for c in range(n):
        p = {t: {"kind": "short", "panel": ["poa1p" + str(i % 7)], "since": max(0, c - i % 16), "grades": [{"grader": "poa1g" + str(i % 11), "score": 2, "ts": T + i}]}
             for i, t in enumerate(ids[50 * c: 50 * c + k])}
        out.append({"epoch": c, "ts": T + 21600 * c, "basis": {"pending": p, "settled": [{"answer": ids[50 * c - 1] if c else ids[0], "passed": True, "jury": []}]}, "rewards": {"poa1a": "1"}})
    return out
res = {}
for n in (8, 24):
    db.write("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?,?,?)", (S.blob_kind(), int(time.time()) - n, json.dumps(closes(n)))); db._bump(S.blob_kind())
    A._cache.clear(); A._epochs.clear(); A._cm.clear(); CS._lru.clear(); HI._gx["keys"].clear()
    A.epochs_raw()   # rows rebuilt (streamed) before measuring
    tracemalloc.start(); A._cache.clear(); A._epochs.clear(); CS._lru.clear()
    er = A.epochs_raw(); HI.grading_index(); A.epoch_rows(); A.backlog(); CO.cohorts(); RC.index()
    res[n] = tracemalloc.get_traced_memory()[0]; tracemalloc.stop()
    check(f"{n} closes: pending lists in memory at most LRU_MAX ({len(CS._lru)})", len(CS._lru) <= CS.LRU_MAX)
grow = res[24] - res[8]
check(f"3x the closes: resident memory grows {grow // 1024} KB ({res[8] // 1024} KB at 8, {res[24] // 1024} KB at 24), not 3x", res[24] < 2 * res[8])
ms = open(os.path.join(ROOT, "poascan", "memstats.py"), encoding="utf-8").read()
check("no em or en dash", not re.search("[\u2013\u2014]", ms + open(__file__, encoding="utf-8").read()))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
