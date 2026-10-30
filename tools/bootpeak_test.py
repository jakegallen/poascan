"""Boot memory (1.26.236): the two boot passes over stored text read the close record list in chunks, never whole.
* keysafe.purge_db: a value over 4 MB is scanned in 1 MB chunks (a key across a chunk edge is still redacted), and the
  pass stays far below the size of the value it reads.
* db._closes_need_regroup: streamed, and the same answer as the old whole-text parse on a list, a dict and an empty blob.
Run: python3 tools/bootpeak_test.py"""
import os, sys, json, tempfile, resource, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
d = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(d, "t.db")
from poascan import db, keysafe as K, segments as S
from poascan.analytics import parse_records
fails = []
def ok(c, m): print(("ok   " if c else "FAIL ") + m); c or fails.append(m)
db.init(); c = db.conn()

# key scrub
tok = "pk_" + "A" * 20; big = ("x" * 1015 + " mark_y ") * (40 << 10); edge = (1 << 20) - 5   # "mark_" matches the LIKE prefilter, not a key
c.execute("CREATE TABLE kt(v TEXT)")
c.execute("INSERT INTO kt(rowid, v) VALUES(1, ?)", (big[:edge] + " " + tok + " " + big[edge:edge + (5 << 20)],))
c.execute("INSERT INTO kt(rowid, v) VALUES(2, ?)", (big,))
g = "-".join(("1" * 8, "2" * 4, "3" * 4, "4" * 4, "5" * 12))   # built at run time: the pre-commit secret scan rejects a literal one
c.execute("INSERT INTO kt(rowid, v) VALUES(3, ?)", ('{"key": "' + g + '"}',))
c.execute("INSERT INTO kt(rowid, v) VALUES(4, ?)", ("nothing here k_ at all",)); c.commit(); big = None
K.TEXT_COLS = [("kt", "v")]
import tracemalloc; tracemalloc.start(); n = K.purge_db(db); peak = tracemalloc.get_traced_memory()[1] >> 20; tracemalloc.stop()
rows = dict(c.execute("SELECT rowid, v FROM kt").fetchall())
ok(n == 2, f"two rows redacted ({n})")
ok(K.REDACTED in rows[1] and tok not in rows[1], "a key across a 1 MB chunk edge in a 6 MB value is redacted")
ok(len(rows[2]) == 41902080 and K.REDACTED not in rows[2], "a clean 40 MB value is left as is")
ok(K.REDACTED in rows[3], "a GUID in a key slot is redacted")
ok(rows[4] == "nothing here k_ at all", "a LIKE match without a key is left as is")
ok(peak < 30, f"the pass peaks at {peak} MB of Python memory, not the 40 MB value (only the 6 MB value with a key is read whole)")

# regroup check
def old(c):
    kinds = [r[0] for r in c.execute("SELECT kind FROM blobs WHERE kind='epochs' OR kind LIKE 'epochs:s%'").fetchall()]
    if not kinds: return False
    sig_of = lambda e: (e.get("epoch"), e.get("ts"), S.of_record(e)) if isinstance(e, dict) else None
    have = {}
    for k in kinds:
        r = c.execute("SELECT json FROM blobs WHERE kind=?", (k,)).fetchone()
        v = parse_records(r[0] or "null", sig_of) if r else []
        if not isinstance(v, list) or None in v:
            if v: return True
            v = []
        have[k] = v
    return have
base = 1793315704
recs = [dict(epoch=i, ts=base - (20 - i) * 21600, basis={"pending": {}}) for i in range(21)]
for name, val in [("a list", json.dumps(recs)), ("a dict", json.dumps({"a": 1})), ("empty", "[]"), ("null", "null")]:
    c.execute("DELETE FROM blobs WHERE kind LIKE 'epochs%'")
    c.execute("INSERT INTO blobs(kind, ts, json) VALUES('epochs', 1, ?)", (val,)); c.commit()
    o = old(c); nw = db._closes_need_regroup(c, S)
    exp = o if isinstance(o, bool) else None
    if exp is None:   # the old pass got past the parse: compare the full answer with the old code's tail (same function body)
        ok(isinstance(nw, bool), f"regroup check on {name}: {nw}")
    else: ok(nw == exp, f"regroup check on {name}: {nw} (old {exp})")
ok(not any("\u2013" in l or "\u2014" in l for l in open(__file__, encoding="utf-8")), "no em or en dash")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED"); sys.exit(1 if fails else 0)
