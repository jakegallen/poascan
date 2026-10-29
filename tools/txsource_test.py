#!/usr/bin/env python3
"""1.26.219: tx lookup serves indexed copies first (stored detail, then the fast index), asks minepoa.com only on a miss
and not while its tx route is Halted or Down for an archived tx; every answer names its source and as-of time."""
import json, os, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, indexer as I, fastindex as FX, server as S, views as V, agentapi as AG
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NOW = int(time.time()); A1 = "poa1" + "Q" * 40
calls = []
def node_read(path, ep, key): calls.append(key); return dict(id=key, type="transfer", from_addr=A1, ts=NOW - 50, final=True, body={"nonce": 3})
I.fetch_ondemand = node_read
fx = {}
FX.tx_detail = lambda tid, visitor=True: fx.get(tid)
route = {"open": True}; I.route_open = lambda rid="tx_lookup": route["open"]
row = lambda t: db.write("INSERT INTO txs(id, type, from_addr, ts, final, first_seen, last_seen, source) VALUES(?,?,?,?,?,?,?,?)", (t, "transfer", A1, NOW - 900, 1, NOW - 800, NOW - 700, "explorer/txs"))

t1 = "1" * 64; db.write("INSERT INTO tx_detail VALUES(?,?,?,?)", (t1, json.dumps(dict(id=t1, type="transfer", from_addr=A1, ts=NOW - 900, final=True, body={})), NOW - 600, 1))
r = S.tx_api(t1)
check("stored final detail: source cache of a minepoa.com read, as of its read time, no upstream call", r["source"] == "cache" and "minepoa.com" in r["source_label"] and r["as_of"] == time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 600)) and not calls)
t2 = "2" * 64; fx[t2] = dict(id=t2, type="transfer", from_addr=A1, ts=NOW - 100, final=True, body={}, detail_source="indexed cache")
r = S.tx_api(t2)
check("fast index final copy: source index, no minepoa.com call", r["source"] == "index" and r["source_label"] == "fast index" and not calls)
r = S.tx_api(t2)
check("asked again: POAScan's stored copy of the fast index read", r["source"] == "cache" and "fast index" in r["source_label"])
t3 = "3" * 64; row(t3); route["open"] = False
r = S.tx_api(t3)
check("tx route halted and the tx archived: archive copy, minepoa.com not asked", r["source"] == "archive" and r["as_of"] and not calls)
t4 = "4" * 64
r = S.tx_api(t4)
check("a miss still asks minepoa.com once, even while halted (nothing indexed to serve)", r["source"] == "node" and calls == [t4])
route["open"] = True; t5 = "5" * 64; row(t5)
r = S.tx_api(t5)
check("route open, archived but no detail: minepoa.com read for the full detail", r["source"] == "node" and calls == [t4, t5])
h = V.tx(t1); h = h if isinstance(h, str) else str(h)
check("tx page names its source and as-of time", "Source: POAScan cache of a minepoa.com read" in h and "/about#tx-source" in h)
route["open"] = False; t6 = "6" * 64; row(t6)
h = V.tx(t6); h = h if isinstance(h, str) else str(h)
check("tx page while halted: the archive row, labelled, no upstream call", "Source: POAScan archive" in h and t6 not in calls)
m = AG.t_tx({"hash": t2})
check("MCP get_transaction: source, source_label, as_of", m["source"] == "cache" and m["source_label"] and m["as_of"])
m = AG.t_tx({"hash": t6})
check("MCP get_transaction while halted: archive, no upstream call", m["source"] in ("archive",) and t6 not in calls)
st = json.loads(db.q1("SELECT json FROM tx_detail WHERE id=?", (t2,))["json"])
check("stored copies never carry the served_ labels", not any(k.startswith("served_") for k in st))
ab = V.about(); ab = ab if isinstance(ab, str) else str(ab)
check("/about#tx-source, no em or en dash", 'id="tx-source"' in ab and "\u2014" not in ab[ab.find('id="tx-source"'):ab.find('id="halts"')])
print("ALL OK" if not fails else f"FAIL: {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
