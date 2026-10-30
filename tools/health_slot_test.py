"""/api/health never waits for a heavy compute slot (1.26.228) and the WAL checkpoint truncates the WAL (1.26.231).
On Oct 29 /api/health took 4 to 9 s now and then while /healthz took 0.1 s: every 15 s one request refreshes the cheap
feeds and epochs_raw entries, and that request waited for one of the two _heavy slots held by cold page computes on a
throttled VM. Temp database. Usage: python3 tools/health_slot_test.py"""
import os, sys, tempfile, threading, time
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "h.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, segments as S
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
db.put_blob(S.blob_kind(), [{"epoch": 0, "ts": int(time.time()) - 60, "rewards": {}, "basis": {}}])
A.feeds(); A.epochs_raw()   # warm once
held = 0
while A._heavy.acquire(blocking=False): held += 1   # every heavy slot busy, as when cold page computes hold them
try:
    A._cache.clear()   # expired: the next call recomputes
    done = {}
    def call():
        t = time.time(); A.feeds(); A.epochs_raw(); A.cp_moved(); done["s"] = time.time() - t
    th = threading.Thread(target=call, daemon=True); th.start(); th.join(5)
    check(f"feeds, epochs_raw and cp_moved recompute with every heavy slot held ({held} held, {done.get('s', 'timed out')})", "s" in done and done["s"] < 2)
    hv = {}
    @A.cached("test_heavy", 30)
    def heavy(): return 1
    th = threading.Thread(target=lambda: hv.setdefault("v", heavy()), daemon=True); th.start(); th.join(0.5)
    check("a heavy compute still waits for a slot", "v" not in hv)
finally:
    for _ in range(held): A._heavy.release()
th.join(2); check("and runs once a slot frees", hv.get("v") == 1)
if hasattr(db, "checkpoint"):
    for i in range(200): db.write("INSERT INTO snaps(kind, ts, json) VALUES('t', ?, '{}')", (i,))
    wal = db.DB_PATH + "-wal"; before = os.path.getsize(wal) if os.path.exists(wal) else 0
    r = db.checkpoint()
    check(f"WAL checkpoint completes and truncates the WAL ({before} bytes before, result {r})", r and r[0] == 0 and os.path.getsize(wal) == 0)
    check("reads still work after it", db.q1("SELECT COUNT(*) AS n FROM snaps WHERE kind='t'")["n"] == 200)
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
