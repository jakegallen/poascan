"""Epoch-frozen endpoints say how far behind the network they are (1.26.284): data_as_of_close (the close the data
reflects) and a short stale_reason set only when that close lags the network's epochs_closed, on the epoch-dependent JSON
endpoints (board, cohorts, pending-by-epoch, pending-horizon, governance overview/at-risk/established). Additive: no
existing field changes and meta.stale keeps its meaning. In process, temp database, no request leaves the box.
Usage: python3 tools/close_freshness_test.py"""
import os, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "cf.db"), POASCAN_INDEXER="0")
import fixture; fixture.seed()   # 12 closes (epochs 0..11), status.epochs_closed = 12
from poascan import analytics as A, cohorts as CO, board as BD, horizon as HO, governance as GV, segments as S, db
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# fresh: a fresh set of epoch records ends at epochs_closed - 1
check("network_last_close is epochs_closed - 1", A.network_last_close() == 11)
check("data_close is the last epoch row", A.data_close() == 11)
check("close_lag is None when the data is current", A.close_lag(11) is None and A.close_lag(12) is None)
p = A.pending_by_epoch()
check("pending-by-epoch: data_as_of_close present, no stale_reason when current", p["data_as_of_close"] == 11 and p["stale_reason"] is None)
check("as_of_close is unchanged (additive)", p["as_of_close"] == 11)

# freeze: the network keeps closing epochs while the epoch records stay at E11 (/api/epochs paused upstream)
st = db.get_blob("status")[0]; st["epochs_closed"] = 17; db.put_blob("status", st)
A._cache.clear()   # the endpoints are time-cached 60 s; drop it so the test reads the new network close at once
check("network_last_close advances with status", A.network_last_close() == 16)
check("close_lag names both closes and the gap when frozen behind",
      A.close_lag(11) == "epoch records frozen at close E11; network has closed through E16 (5 behind)")
p = A.pending_by_epoch()
check("pending-by-epoch stale_reason set, data_as_of_close unchanged", p["data_as_of_close"] == 11 and p["stale_reason"] and "frozen at close E11" in p["stale_reason"])

for name, d in [("cohorts", CO.cohorts()), ("board", BD.api()), ("pending-horizon", HO.horizon()),
                ("governance at-risk", GV.api_at_risk()), ("governance overview", GV.api_overview()),
                ("governance established", GV.api_established())]:
    check(f"{name}: carries data_as_of_close and a stale_reason when frozen", "data_as_of_close" in d and d.get("stale_reason"))
check("board data_as_of_close equals its last_close", BD.api()["data_as_of_close"] == BD.api()["last_close"])
check("horizon data_as_of_close equals its as_of_close", HO.horizon()["data_as_of_close"] == HO.horizon()["as_of_close"])

# an archived segment is intentionally frozen: never flagged
_arch = S.archived; S.archived = lambda *a: True
check("an archived segment is never flagged stale", A.close_lag(11) is None)
S.archived = _arch

# unknown network close: no flag (never a false signal)
st2 = db.get_blob("status")[0]; st2.pop("epochs_closed", None); db.put_blob("status", st2); A._cache.clear()
check("unknown epochs_closed: no flag", A.network_last_close() is None and A.close_lag(5) is None)
p = A.pending_by_epoch()
check("pending-by-epoch stale_reason clears when the network close is unknown", p["stale_reason"] is None)

import re
srcs = "".join(open(os.path.join(ROOT, "poascan", f), encoding="utf-8").read() for f in ("analytics.py", "cohorts.py", "board.py", "horizon.py", "governance.py"))
check("no em or en dash", not re.search(r"[\u2013\u2014]", srcs + open(__file__, encoding="utf-8").read()))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
