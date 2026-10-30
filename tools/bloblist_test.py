"""Large lists are stored in pieces (1.26.238). db.put_blob writes a list whose text is over 1 MB in 1 MB pieces into a
value of its exact size, so storing the close record list no longer builds its whole text (and two more copies of it)
at once. The stored bytes must be exactly json.dumps of the list after key redaction. Run: python3 tools/bloblist_test.py"""
import os, sys, gc, json, tempfile, tracemalloc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from poascan import db, keysafe as KS, closestore as CS
fails = []
def ok(c, m): print(("ok   " if c else "FAIL ") + m); c or fails.append(m)
def stored(kind):
    r = db.conn().execute("SELECT json FROM blobs WHERE kind=?", (kind,)).fetchone()
    return bytes(r[0]) if isinstance(r[0], bytes) else r[0].encode()
db.init()
guid = "-".join(("0123abcd", "4567", "89ab", "cdef", "0123456789ab"))
key = "psk" + "_" + "A1b2C3d4E5f6G7h8"
rows = [{"epoch": i, "ts": 1793000000 + i, "pending": [{"id": "p%d" % i, "grades": [1.5, None, True], "note": "x" * 900}],
         "f": float(i) / 3, "u": "caf\u00e9 \u2603", "n": None} for i in range(3000)]
rows[7]["memo"] = "key=" + guid; rows[9]["memo"] = "see " + key + " here"; rows[11] = ["a", 1, {"token": guid}]
want = KS.redact(json.dumps(rows)).encode()
ok(len(want) > db.BIG_ARG, f"the test list is over 1 MB ({len(want) >> 10} KB)")
db.put_blob("epochs", rows)
ok(stored("epochs") == want, "the stored bytes are exactly json.dumps of the list, redacted")
ok(key not in stored("epochs").decode() and guid not in stored("epochs").decode(), "no key or GUID key is stored")
ok(db.get_blob("epochs")[0] == json.loads(want), "get_blob reads it back")
ok(list(CS.iter_blob("epochs")) == json.loads(want), "the chunked reader reads it back")
small = [{"a": 1}, {"b": "k"}]
db.put_blob("small", small)
r = db.conn().execute("SELECT typeof(json), json FROM blobs WHERE kind='small'").fetchone()
ok(r[0] == "text" and r[1] == json.dumps(small), "a small list is stored as text, as before")
db.put_blob("one", [1]); db.put_blob("empty", []); db.put_blob("obj", {"a": [1, 2]})
ok(db.get_blob("one")[0] == [1] and db.get_blob("empty")[0] == [] and db.get_blob("obj")[0] == {"a": [1, 2]}, "short lists and objects as before")
g0 = db.blob_gen("epochs"); db.put_blob("epochs", rows[:2000]); ok(db.blob_gen("epochs") == g0 + 1, "a write bumps the blob generation")
ok(db.get_blob("epochs")[0] == json.loads(KS.redact(json.dumps(rows[:2000]))), "a rewrite replaces the stored list")
class Odd:
    pass
try: db.put_blob("epochs", rows + [Odd()]); bad = False
except TypeError: bad = True
ok(bad and db.get_blob("epochs")[0] == json.loads(KS.redact(json.dumps(rows[:2000]))), "a list that cannot be encoded raises and keeps the stored copy")
big = [{"i": i, "s": "y" * 2000} for i in range(20000)]; n = len(json.dumps(big)); gc.collect()
tracemalloc.start(); db.put_blob("big", big); peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
ok(peak < n // 4, f"storing a {n >> 20} MB list peaks at {peak >> 20} MB (the whole text and its copies before)")
ok(not any("\u2013" in l or "\u2014" in l for l in open(__file__, encoding="utf-8")), "no em or en dash")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED"); sys.exit(1 if fails else 0)
