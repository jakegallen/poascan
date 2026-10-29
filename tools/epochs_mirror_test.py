#!/usr/bin/env python3
"""1.26.221: /api/v1/epochs is small, paged (latest n, from and limit) and links each close; minepoa.com's full list is
read once per new close and at most once per EPOCHS_GAP_S, never per request."""
import json, os, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, segments as SG, indexer as I, server as S
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)
NOW = int(time.time()); P = 21600
recs = [dict(epoch=k, ts=NOW - (20 - k) * P, pool="1000000000.000000", rewards={"poa1" + "Q" * 40: "5"}, basis={}) for k in range(20)]
db.put_blob(SG.blob_kind(SG.CURRENT), recs); db.put_blob("status", {"epochs_closed": 20, "supply": "1", "txs": 1, "checkpoint_height": 1}); A._cache.clear()
rows = S.api("/api/epochs", {"latest": ["3"]})[0]
check("latest=3: the newest three closes, ascending", [r["epoch"] for r in rows] == [17, 18, 19])
r = rows[-1]
check("each row: epoch, close_ts, minted, paid, graders, settled, url, record_url, rewards_url",
      all(k in r for k in ("epoch", "close_ts", "minted", "paid", "graders", "settled")) and r["url"].endswith("/epoch/19") and r["record_url"].endswith("/api/v1/epoch/19/record") and r["rewards_url"].endswith("/api/v1/epoch/19/rewards"))
check("from and limit still page by epoch number", [x["epoch"] for x in S.api("/api/epochs", {"from": ["5"], "limit": ["2"]})[0]] == [5, 6])
try: S.api("/api/epochs", {"latest": ["2"], "from": ["1"]}); bad = False
except S.BadRequest: bad = True
check("latest with from is a 400", bad)
check("whole segment stays small (under 60 KB for 20 closes)", len(json.dumps(S.api("/api/epochs", {})[0])) < 60000)
calls = []
I.fetch = lambda path, **k: calls.append(path) or []
check("no close missing: no upstream read", I.job_epochs() is False and not calls)
db.put_blob("status", {"epochs_closed": 21, "supply": "1", "txs": 1, "checkpoint_height": 1})
db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,fails,next_at,err) VALUES(?,?,0,0,NULL)", ("/api/epochs", NOW - 300))
I.job_epochs()
check("a close missing but the list was read 5 min ago: no second read", not calls)
db.write("UPDATE fetch_log SET last_ok=? WHERE endpoint='/api/epochs'", (NOW - I.EPOCHS_GAP_S - 5,))
I.job_epochs()
check("a close missing and the gap passed: one read", calls == ["/api/epochs"])
print("ALL OK" if not fails else f"FAIL: {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
