#!/usr/bin/env python3
"""1.26.220: health over six routes with mining and grading as core. A non-core route (tx lookup, swaps, anchors,
assignments) not OK is listed on its own and leaves health OK (200) and the header dot Live; a core route not OK is
Partial (503) and the dot and note say so."""
import json, os, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, routehealth as RH, routewatch as RW, ui as UI, views as V, views2 as V2, server as S
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)
NOW = int(time.time())
def live():
    for ep in ("/api/status", "/api/networks"):
        db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,fails,next_at,err) VALUES(?,?,0,0,NULL)", (ep, NOW))
def feed(ep, ok=True):
    db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,last_err,fails,next_at,err) VALUES(?,?,?,?,0,?)", (ep, NOW if ok else NOW - 7200, None if ok else NOW, 0 if ok else 6, None if ok else "HTTP 503"))
def routes(**st):
    recs = {rid: dict(state=st.get(rid, "open"), as_of=NOW - 30, since=NOW - 3600) for rid in ("hosted_mining", "assignments", "grading", "path_actions", "swap_writes", "tx_lookup", "address_lookup")}
    db.put_blob(RW.BLOB, dict(ts=NOW, routes=recs)); A._cache.clear()
live(); db.put_blob("status", {"epochs_closed": 0, "supply": "1", "txs": 1, "checkpoint_height": 1}); db.put_blob("networks", {"chains": []})
for ep in ("/api/swaps", "/api/anchors", "/api/explorer/txs"): feed(ep)
routes()
fd = A.feeds()
check("all routes open: OK, ok true, six routes, core mining and grading", fd["state"] == "OK" and fd["ok"] and [r["id"] for r in fd["routes"]] == ["mining", "grading", "assignments", "tx_lookup", "swaps", "anchors"] and fd["core"] == ["mining", "grading"])
routes(tx_lookup="halted"); feed("/api/swaps", ok=False)
fd = A.feeds(); h = S.api("/api/health", {})[0]
tl = next(r for r in h["routes"] if r["id"] == "tx_lookup"); sw = next(r for r in h["routes"] if r["id"] == "swaps")
check("tx lookup halted and swaps down: still OK (200), both listed in degraded on their own", h["ok"] and h["state"] == "OK" and "Tx lookup" in h["degraded"] and "Swaps" in h["degraded"] and tl["state"] == "down" and sw["state"] == "down")
p = UI.status_pill(A.freshness())
check("header dot stays Live; the note has one line each for tx lookup and swaps", p["state"] == "live" and any(x.startswith("Tx lookup ") for x in p["reasons"]) and any(x.startswith("Swaps down") for x in p["reasons"]))
routes(grading="halted")
fd = A.feeds(); h = S.api("/api/health", {})[0]; p = UI.status_pill(A.freshness())
check("grading halted (core): Partial, ok false (503), core_not_ok Grading", h["state"] == "Partial" and not h["ok"] and h["core_not_ok"] == ["Grading"])
check("the dot turns Partial and the note names the core route", p["state"] == "partial" and any("Core route not OK: Grading" in x for x in p["reasons"]))
routes(hosted_mining="down")
h = S.api("/api/health", {})[0]
check("mining down (core): Partial", h["state"] == "Partial" and "Mining" in h["core_not_ok"])
routes()
check("back to OK once the core routes are open", S.api("/api/health", {})[0]["ok"])
hh = V2.feeds_html(); hh = str(hh)
check("Network > Health lists the six routes with Core tags", hh.count('data-rh="') == 6 and hh.count(">Core<") == 2)
ab = V.about(); ab = ab if isinstance(ab, str) else str(ab)
check("/about#health-core explains the core set", 'id="health-core"' in ab and "Mining and Grading are core" in ab)
check("no em or en dash in routehealth copy", not any(c in RH.CORE_BASIS + RH.__doc__ for c in "\u2014\u2013"))
feed("/api/explorer/txs", ok=False); db.write("DELETE FROM fetch_log WHERE endpoint='/api/txs'"); A._cache.clear()
h = S.api("/api/health", {})[0]
check("POAScan's own tx list feed down: Partial too (core feed)", h["state"] == "Partial" and "Tx list" in h["core_not_ok"])
print("ALL OK" if not fails else f"FAIL: {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
