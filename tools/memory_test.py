"""Memory regressions (1.26.227, the 2026-10-29 OOM). 1) A request thread's SQLite connection is closed when the thread
ends: the server gives each request its own thread, and connections left on finished threads sat in reference cycles
until a full GC, so RSS climbed about 6 MB/s under load to the 1 GB limit. 2) Close records parse to the same values as
json.loads while unchanged pending rows are shared between closes, so the parsed list stays a fraction of its old size.
Temp database. Usage: python3 tools/memory_test.py"""
import os, sys, tempfile, json, threading, gc, sqlite3, tracemalloc, random
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "m.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, segments as S, indexer as I, server as SV
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()

# 1) connections end with their thread
got = []
def work():
    db.q("SELECT 1 AS x"); got.append(db._local.c); db.release()
t = threading.Thread(target=work); t.start(); t.join()
c = got[0]
try: c.execute("SELECT 1"); closed = False
except sqlite3.ProgrammingError: closed = True
check("db.release closes the thread's connection", closed)
check("db.release with no connection is a no-op", db.release() is None)
db.q("SELECT 1 AS x"); db.release(); check("a released thread opens a fresh connection when it reads again", db.q1("SELECT 1 AS x")["x"] == 1)
import inspect
check("request threads release their connection", "db.release()" in inspect.getsource(SV.Server.process_request_thread))
before = sum(1 for o in gc.get_objects() if isinstance(o, sqlite3.Connection))
gc.disable()
try:
    for _ in range(40):
        th = threading.Thread(target=lambda: (db.q("SELECT 1 AS x"), db.release())); th.start(); th.join()
    after = sum(1 for o in gc.get_objects() if isinstance(o, sqlite3.Connection))
finally: gc.enable()
check(f"40 finished request threads leave no open connection behind without a GC ({after - before} left)", after - before <= 1)

# 2) close records: same values, shared pending rows, bounded size
rnd = random.Random(7); ids = [f"{rnd.getrandbits(256):064x}" for _ in range(3000)]
def pend(n): return {t: {"since": i % 5, "author": "poa1" + t[:20], "grades": [{"grader": "poa1g" + str(j), "ts": 1000 + j} for j in range(i % 4)], "panel": ["poa1p" + str(i % 9)]}
                     for i, t in enumerate(ids[: 1000 + 100 * n])}
recs = []
for n in range(12):
    p = pend(n)
    if n: p[ids[n]] = dict(p[ids[n]], grades=[{"grader": "poa1new", "ts": 5000 + n}])   # one row changes each close
    recs.append({"epoch": n, "ts": 1700000000 + 21600 * n, "rewards": {"poa1a": "1.5"}, "basis": {"pending": p, "settled": [{"id": ids[n], "passed": True}]}})
text = json.dumps(recs, indent=None)
ref = json.loads(text)
tracemalloc.start(); got = A.parse_closes(text); size = tracemalloc.get_traced_memory()[0]; tracemalloc.stop()
tracemalloc.start(); plain = json.loads(text); psize = tracemalloc.get_traced_memory()[0]; tracemalloc.stop(); del plain
check("parse_closes equals json.loads", got == ref and json.dumps(got) == text)
check("key order kept", [list(e["basis"]["pending"]) for e in got] == [list(e["basis"]["pending"]) for e in ref])
check("an unchanged pending row is shared with the previous close", got[3]["basis"]["pending"][ids[500]] is got[2]["basis"]["pending"][ids[500]])
check("a changed row is not shared", got[3]["basis"]["pending"][ids[3]] is not got[2]["basis"]["pending"][ids[3]] and got[3]["basis"]["pending"][ids[3]]["grades"][0]["grader"] == "poa1new")
check(f"parsed size is under half of json.loads ({size // 1024} KB vs {psize // 1024} KB)", size < psize / 2)
for s in ("[]", " [ ]\n", "null", "{}", '[1, 2 ,3]', '[{"basis": null}, {"basis": {"pending": null}}]'):
    check(f"edge case {s!r}", A.parse_closes(s) == (json.loads(s) or []))
db.put_blob(S.blob_kind(), recs); A._cache.clear(); A._epochs.clear()
check("epochs_raw reads the stored copy through parse_closes", A.epochs_raw() == ref)
check("indexer parses /api/epochs the same way", I._parse("/api/epochs", text.encode()) == ref and I._parse("/api/status", b'{"a": 1}') == {"a": 1})
# 3) boot regroup (1.26.230): the (epoch, ts) check agrees with the full regroup on whether anything moves
import copy
c = db.conn()
def blobs(): return {k: j for k, j in c.execute("SELECT kind, json FROM blobs WHERE kind='epochs' OR kind LIKE 'epochs:s%'")}
def scenario(name, setup):
    c.execute("DELETE FROM blobs WHERE kind='epochs' OR kind LIKE 'epochs:s%'"); c.commit()
    for k, v in setup.items(): c.execute("INSERT INTO blobs(kind, ts, json) VALUES(?, 1, ?)", (k, v if isinstance(v, str) else json.dumps(v)))
    c.commit(); need = db._closes_need_regroup(c, S); b0 = blobs()
    real = db._closes_need_regroup; db._closes_need_regroup = lambda c, S: True
    try: db._regroup_closes(c, S)
    finally: db._closes_need_regroup = real
    moved = blobs() != b0
    check(f"regroup check: {name} (needs {need}, full regroup wrote {moved})", need == moved)
    check(f"regroup check: {name}, settled after one regroup", db._closes_need_regroup(c, S) is False)
r3 = [{"epoch": i, "ts": 1700000000 + i, "basis": {}} for i in range(3)]
scenario("in place", {S.blob_kind(): r3})
scenario("duplicate record across blobs", {S.blob_kind(): r3, "epochs:s9": r3[:1]})
scenario("no current blob", {"epochs:s9": []})
scenario("not a list", {S.blob_kind(): "{}"})
scenario("unsorted", {S.blob_kind(): r3[::-1]})
scenario("an object, not a list", {S.blob_kind(): r3, "epochs:s9": '{"a": 1}'})
scenario("a list of non-records", {S.blob_kind(): r3, "epochs:s9": "[1, 2]"})
scenario("null", {S.blob_kind(): "null"})
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
