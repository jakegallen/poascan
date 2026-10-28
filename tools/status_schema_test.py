#!/usr/bin/env python3
"""1.26.217: /api/status in its newer shape (from the E16 close, Oct 28 2026: checkpoint {height, cutoff_ts}, no as_of) is
data, not a notice; readers get the flat checkpoint_height, and a newer epochs_closed makes the close records due again."""
import os, sys, tempfile
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, strain as ST, indexer as I, analytics as A, segments as SG, rewardbasis as RB
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NEW = {"checkpoint": {"height": 95992, "cutoff_ts": 1793213223}, "network": "PoA prototype", "K": 5, "open_ballots": 0, "chain_id": "poa-mainnet-1",
       "supply": "3081837077.366097", "txs": 1553, "final": 1289, "invalid": 6, "agents_joined": 7960, "epochs_closed": 17, "holders": 1901}
OLD = {"as_of": "2026-10-28T20:00:00Z", "supply": "1", "txs": 1, "epochs_closed": 16, "checkpoint_height": 95000}
check("the newer status shape is data, not a notice", ST.detect("/api/status", NEW) is None)
check("the older flat shape is still data", ST.detect("/api/status", OLD) is None)
check("a body without a checkpoint in either shape is still caught", ST.detect("/api/status", {"supply": "1", "txs": 1, "epochs_closed": 3}) is not None)
check("a bare notice is still caught", ST.detect("/api/status", {"notice": "API hardening in progress"}) is not None)
n = I.norm_status(NEW)
check("normalized: checkpoint_height 95992 and checkpoint_cutoff_ts, the nested copy kept", n["checkpoint_height"] == 95992 and n["checkpoint_cutoff_ts"] == 1793213223 and n["checkpoint"]["height"] == 95992)
check("the older shape passes through unchanged", I.norm_status(OLD) == OLD)
I._live_status(NEW); A._cache.clear()
check("stored status carries checkpoint_height and epochs_closed 17", A.status().get("checkpoint_height") == 95992 and A.status().get("epochs_closed") == 17)
db.put_blob(SG.blob_kind(SG.CURRENT), [dict(epoch=k, ts=1793000000 + k * 21600, rewards={}) for k in range(16)]); A._cache.clear()
with SG.use(SG.CURRENT): have = A.epochs_count()
check("16 closes held, 17 listed: the close records are behind (job_epochs refetches when have < need)", have == 16 and RB.lag()["kind"] == "missing")
print("ALL OK" if not fails else f"FAIL: {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
