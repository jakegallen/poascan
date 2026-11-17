"""since_fill reads only closes it has not covered and keeps its map in a blob (1.26.367); the map always equals a full
rebuild over every close.

Root cause covered: every boot and every close rebuilt the map by parsing every close's pending list (about 9 s on the
one core, 44 s seen in a receipt request under load).

Run: python3 tools/sincefill_test.py (temp db, in-process, no network).
"""
import json, os, sys, tempfile

os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "sincefill.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from poascan import analytics as A, db

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

class R(dict):
    __slots__ = ("loc",)

closes, pend, sigs, tx_epoch, blobs, parses = [], {}, {}, {"t1": 7}, {}, []
def add_close(pos, epoch, rows):
    e = R(epoch=epoch); e.loc = ("epochs", pos, pos, 0); closes.append(e); pend[pos] = rows; sigs[pos] = f"s{pos}"

def fake_q(sql, args=()):
    if "FROM close_rows" in sql: return [{"pos": p, "sig": s} for p, s in sigs.items()]
    if "FROM txs" in sql: return [{"id": t, "epoch": tx_epoch[t]} for t in args if t in tx_epoch]
    raise AssertionError(sql)
db.q = fake_q
db.put_blob = lambda k, o: blobs.__setitem__(k, json.loads(json.dumps(o)))
db.get_blob = lambda k: (blobs[k], 1) if k in blobs else (None, None)
A.epochs_raw = lambda: list(closes)
A.pending_of = lambda e: (parses.append(e.loc[1]), pend[e.loc[1]])[1]

def full():
    first = {}
    for e in closes:
        for t, v in pend[e.loc[1]].items():
            if isinstance(v, dict) and v.get("since") is None and (t not in first or e["epoch"] < first[t]): first[t] = e["epoch"]
    return {t: tx_epoch.get(t, n) for t, n in first.items()}

def build(ts):
    parses.clear(); return A._since_fill_build((2, ts))

add_close(0, 1, {"t1": {}, "t2": {"since": None}, "t3": {"since": 0}})
add_close(1, 2, {"t2": {}, "t4": {}})
ok(build(1) == full() and parses == [0, 1], "first build reads every close and equals a full rebuild")
A._sf_state.clear()
ok(build(1) == full() and parses == [], "after a restart the map comes from the blob, no close read")
add_close(2, 3, {"t5": {}, "t4": {}})
ok(build(2) == full() and parses == [2], "a new close: only that close is read")
tx_epoch["t5"] = 2
add_close(3, 4, {"t6": {"since": 1}})
ok(build(3) == full() and parses == [3] and full()["t5"] == 2, "a fallback id is checked again once its tx epoch is known")
pend[1] = {"t2": {}}; sigs[1] = "s1b"
ok(build(4) == full() and sorted(parses) == [0, 1, 2, 3], "a covered close that changed rebuilds from every close")
del closes[0]; del sigs[0]
ok(build(5) == full() and sorted(parses) == [1, 2, 3], "a covered close that went away rebuilds from every close")
print("FAIL:" if fails else "all ok", fails if fails else "")
sys.exit(1 if fails else 0)
