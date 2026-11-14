"""1.26.337: close_sum rows and close_fold states (closesum.py). Every memo that walked each close's pending list gives
the same value from the stored rows, a new close parses only its own and the previous pending list, and a restart
parses none. Temp database, no network. Usage: python3 tools/closesum_test.py"""
import os, sys, tempfile, json, time, random
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "s.db"); os.environ.setdefault("POASCAN_INDEXER", "0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, closestore as CS, segments as S, closesum as SUM, receipts as R, cohorts as C, calibration as CB, governance as G, govv2 as G2
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init(); random.seed(7)
T0 = int(time.time()) - 21600 * 12
db.put_blob("params", {"pending_merge_from_epoch": 2, "K": 4})
ids = [f"{i:064x}" for i in range(400)]
def close(n):
    live = [t for i, t in enumerate(ids) if n * 30 <= i < n * 30 + 90]
    p = {}
    for i, t in enumerate(live):
        row = {"kind": "appeal" if i % 7 == 0 else "short", "panel": ["poa1p"] if i % 3 else []}
        if i % 5: row["since"] = int(ids.index(t) // 30)          # some rows carry no since (E14 style)
        if n >= 2 and i % 2: row["grades"] = [{"grader": f"poa1g{(i + k) % 6}", "ts": T0 + 21600 * n - 100 * k, "score": 2} for k in range(i % 4)]
        p[t] = row
    st = [{"answer": t, "passed": bool(j % 2), "from": f"poa1a{j % 9}", "jury": [{"grader": f"poa1g{j % 6}", "aligned": bool(j % 3)}] if j % 4 else []}
          for j, t in enumerate(ids[max(0, n * 30 - 30): n * 30])]
    return {"epoch": n, "ts": T0 + 21600 * n, "pool": "1000", "basis": {"pending": p, "settled": st, "challenge_eligible": live[:5]},
            "rewards": {f"poa1a{k}": str(n + k) for k in range(5)}, "challenges": {f"poa1a{n % 9}": "1"}}
for t in ids[::3]:   # some answers archived (their tx epoch fills a missing since)
    db.write("INSERT OR REPLACE INTO txs(id, type, epoch, ts, from_addr) VALUES(?,?,?,?,?)", (t, "challenge", int(ids.index(t) // 30), T0, "poa1x"))
kind = S.blob_kind()
CS.append_records(kind, [close(n) for n in range(6)])
def clear():
    A._cm.clear(); SUM._mem.clear(); SUM._live.clear(); A._sf["ts"] = None; A._cache.clear(); CS._lru.clear()
def walk():
    """Every memo the way 1.26.336 computed it (closesum off)."""
    g, f = SUM.get, SUM.fold; SUM.get = lambda *a, **k: None; SUM.fold = lambda *a, **k: None
    try:
        clear(); w = A._since_fill_build
        return vals()
    finally:
        SUM.get, SUM.fold = g, f; clear()
def vals():
    dump = lambda v: json.dumps(v, default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else repr(o))
    return dict(ep=dump(A._epoch_pend()), bl=dump(A.backlog()), js=dump(G.jury_series()), st=dump(G2.settlement()), er=dump(A.epoch_rows()),
                rc=dump(R._close_index()), co=dump(C._cohorts()), cb=dump(CB._close_part()), sf=dump(sorted(A.since_fill().items())))
ref = walk(); clear()
got = vals()
for k in ref: check(f"{k}: stored rows give the walk's value", got[k] == ref[k])
check("rows built for every close", db.q1("SELECT COUNT(*) AS n FROM close_sum WHERE kind=?", (kind,))["n"] == 6)
# a restart: nothing parsed
parsed = []; real = CS.pending
CS.pending = lambda *a, **k: (parsed.append(a[1]), real(*a, **k))[1]
clear(); got2 = vals()
check(f"a restart parses no pending list ({len(parsed)})", parsed == [] and got2 == got)
# a new close: its own list and the one before it
parsed.clear(); CS.append_records(kind, [close(6)]); clear(); got3 = vals()
CS.pending = real
check(f"a new close parses only closes 5 and 6 ({sorted(set(parsed))})", set(parsed) <= {5, 6})
ref3 = walk()
for k in ref3: check(f"{k} after a new close: same as the walk", got3[k] == ref3[k])
# an answer filled from its first close gets archived: the rows that used it are rebuilt
miss = [t for t in ids if t not in ids[::3]]
no_since = None
for pos in range(7):
    p = CS.pending(kind, pos) or {}
    no_since = next((t for t, v in p.items() if v.get("since") is None and t in miss), None)
    if no_since: break
db.write("INSERT OR REPLACE INTO txs(id, type, epoch, ts, from_addr) VALUES(?,?,?,?,?)", (no_since, "challenge", 0, T0, "poa1x"))
clear(); got4 = vals(); ref4 = walk()
for k in ("ep", "bl", "st", "rc", "co", "sf"): check(f"{k} after a late archive of a filled answer: same as the walk", got4[k] == ref4[k])
# params merge change: rows keyed on it
db.put_blob("params", {"pending_merge_from_epoch": 3, "K": 4}); clear(); got5 = vals(); ref5 = walk()
for k in ("bl", "co", "cb"): check(f"{k} after a params merge change: same as the walk", got5[k] == ref5[k])
# ingest warm: a new close is folded by warm(), and a page read after it parses nothing
CS.append_records(kind, [close(7)]); clear()
parsed.clear(); CS.pending = lambda *a, **k: (parsed.append(a[1]), real(*a, **k))[1]
w = SUM.warm(kind); first = sorted(set(parsed)); parsed.clear(); got6 = vals(); CS.pending = real
check(f"warm() runs every memo ({w}) and parses only closes 6 and 7 ({first})", w == 7 and set(first) <= {6, 7})
check(f"a page read after warm parses nothing ({len(parsed)})", parsed == [])
# a warm process (no restart): a new close folds onto a copy of the receipts state it holds, nothing unpickled,
# and the value an earlier reader got is not changed under it
clear(); dump = lambda v: json.dumps(v, default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else repr(o))
old = R._close_index(); before = dump(old); SUM.stats.clear(); loads = []; rl = SUM._load
SUM._load = lambda *a, **k: (loads.append(a[0]), rl(*a, **k))[1]
CS.append_records(kind, [close(8)]); A._cm.clear(); A._cache.clear(); CS._lru.clear(); A._sf["ts"] = None
new = dump(R._close_index()); SUM._load = rl
check(f"a warm new close folds the held receipts state (fold_live {SUM.stats['fold_live']}, loads {loads})", SUM.stats["fold_live"] >= 1 and "receipt_closes" not in loads)
check("the earlier receipts value is unchanged", dump(old) == before and new != before)
check("rc after a warm new close: same as the walk", new == walk()["rc"])
print("FAILED: " + "; ".join(fails) if fails else "all ok"); sys.exit(1 if fails else 0)
