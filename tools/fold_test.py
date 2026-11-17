"""Per-close folds (1.26.368): one walk reads each close's pending list once for every fold, a new close is folded in on
top of the kept state, and the result always equals a walk over every close.

Root cause covered: jury_series, calibration, settlement and the epoch rows each walked every close on each new close
and after a restart (four full pending reads, plus since_fill), about a minute and 200 MB on the one core.

Run: python3 tools/fold_test.py (temp db, in-process, no network).
"""
import json, os, sys, tempfile

os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "fold.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from poascan import analytics as A, db

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

class R(dict):
    __slots__ = ("loc",)

closes, pend, sigs, blobs, parses, tx_epoch = [], {}, {}, {}, [], {}
psig = ["p1"]
def add_close(pos, epoch, rows):
    e = R(epoch=epoch, ts=1000 + epoch); e.loc = ("epochs", pos, pos, 0); closes.append(e); pend[pos] = rows; sigs[pos] = f"s{pos}"

def fake_q(sql, args=()):
    if "FROM close_rows" in sql: return [{"pos": p, "sig": s} for p, s in sigs.items()]
    if "FROM txs" in sql: return [{"id": t, "epoch": tx_epoch[t]} for t in args if t in tx_epoch]
    raise AssertionError(sql)
db.q = fake_q
db.put_blob = lambda k, o: blobs.__setitem__(k, json.loads(json.dumps(o)))
db.get_blob = lambda k: (blobs[k], 1) if k in blobs else (None, None)
A.epochs_raw = lambda: list(closes)
A.epochs_ts = lambda: len(closes) * 10 + len(tx_epoch)
A.pending_of = lambda e: (parses.append(e.loc[1]), pend[e.loc[1]])[1]
A.params_sig = lambda: psig[0]
A._folds.clear()

def step_n(out, e, p, pe, pp):   # plain fold: queue size and how many rows the previous close had
    return out + [(e["epoch"], len(p), None if pe is None else len(pp))]
def step_o(out, e, p, pe, pp):   # reads origins
    return out + [sorted(A.since_of(t, v) for t, v in p.items())]
def step_c(st, e, p, pe, pp):    # mutates its state (copy given)
    st["n"] += len(p); return st
A.close_fold("n", list, step_n)
A.close_fold("o", list, step_o, since=True)
A.close_fold("c", lambda: {"n": 0}, step_c, copy=dict)

def walk():
    o = {"n": [], "o": [], "c": {"n": 0}}; pe = pp = None
    for e in closes:
        p = pend[e.loc[1]]; o["n"] = step_n(o["n"], e, p, pe, pp); o["o"] = step_o(o["o"], e, p, pe, pp); o["c"] = {"n": o["c"]["n"] + len(p)}; pe, pp = e, p
    return o

def run():
    parses.clear(); r = {k: A.fold(k) for k in ("n", "o", "c")}; return r, list(parses)

add_close(0, 1, {"a": {}, "b": {"since": 0}})
add_close(1, 2, {"a": {}, "c": {}})
r, p = run()
ok(r == walk() and sorted(p) == [0, 0, 1, 1], f"first fold equals a full walk; each close read once for all folds and once for since_fill ({p})")
kept_c = r["c"]; kept_v = dict(kept_c)
add_close(2, 3, {"d": {}, "c": {}})
r, p = run()
ok(r == walk(), "after a new close the folds equal a full walk")
ok(sorted(p) == [1, 2, 2], f"only the new close is read, once for the folds and once for since_fill, plus its predecessor once ({p})")
ok(kept_c == kept_v == {"n": 4}, "a state already returned does not change when a close is folded on")
tx_epoch["a"] = 0
add_close(3, 4, {"e": {}})
r, p = run()
ok(r == walk() and 0 in p, "an origin read by a covered close changed: the origin fold refolds from the first close")
pend[1] = {"a": {}}; sigs[1] = "s1b"
r, p = run(); ok(r == walk(), "a covered close that changed: refold, equal to a full walk")
psig[0] = "p2"; r, p = run(); ok(r == walk() and 0 in p, "a params change: refold")
closes.reverse(); ok(A.fold("n") is None, "closes out of epoch order: no fold, the caller walks as before")
print("FAIL:" if fails else "all ok", fails if fails else "")
sys.exit(1 if fails else 0)
