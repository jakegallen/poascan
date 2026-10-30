"""Large writes leave nothing behind (1.26.237). SQLite keeps a statement's bound values until the statement runs again,
and the sqlite3 module caches statements per connection, so storing the close record list once used to keep a copy of
it in that connection for good. db.write and db.write_tx now send a value over 1 MB through a connection closed right
after. Run: python3 tools/bigwrite_test.py"""
import os, sys, gc, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from poascan import db
fails = []
def ok(c, m): print(("ok   " if c else "FAIL ") + m); c or fails.append(m)
def rss():
    for l in open("/proc/self/status"):
        if l.startswith("VmRSS"): return int(l.split()[1]) // 1024
db.init(); db.q1("SELECT 1 AS x")
base = rss()
v = "[" + ",".join(['{"a": "%s"}' % ("x" * 1000)] * 60000) + "]"; n = len(v)
db.write("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?, ?, ?)", ("big", 1, v)); v = None; gc.collect()
a = rss()
ok(a - base < 20, f"one 60 MB write leaves {a - base} MB behind (it left about 60 before)")
r = db.q1("SELECT length(json) AS n FROM blobs WHERE kind='big'")
ok(r and r["n"] == n, "the value is stored whole")
rows = [("k%d" % i, 2, "y" * (2 << 20)) for i in range(10)]
db.write("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?, ?, ?)", rows, many=True); rows = None
db.write_tx([("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?, ?, ?)", ("tx", 3, "z" * (30 << 20)), False),
             ("UPDATE blobs SET ts=4 WHERE kind=?", ("tx",), False)]); gc.collect()
b = rss()
ok(b - base < 25, f"many-row and transaction writes of 50 MB leave {b - base} MB behind")
ok(db.q1("SELECT ts FROM blobs WHERE kind='tx'")["ts"] == 4 and db.q1("SELECT COUNT(*) AS n FROM blobs WHERE kind LIKE 'k%'")["n"] == 10, "both statements and every row are stored")
try:
    db.write_tx([("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?, ?, ?)", ("rb", 5, "w" * (2 << 20)), False), ("INSERT INTO nope VALUES(1)", (), False)])
except Exception: pass
ok(db.q1("SELECT 1 AS x FROM blobs WHERE kind='rb'") is None, "a failed transaction with a large value is rolled back")
db.write("UPDATE blobs SET ts=9 WHERE kind='big'")
ok(db.q1("SELECT ts FROM blobs WHERE kind='big'")["ts"] == 9, "small writes still use the thread's connection")
ok(not any("\u2013" in l or "\u2014" in l for l in open(__file__, encoding="utf-8")), "no em or en dash")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED"); sys.exit(1 if fails else 0)
