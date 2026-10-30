"""Network > Health (/status) says how old its data is (1.26.231): 'Data as of <age>' from our last good /api/status read,
the node's as_of in the tooltip, nothing when there is no read. Temp database. Usage: python3 tools/dataasof_test.py"""
import os, sys, tempfile, time, re
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "d.db"); os.environ.setdefault("POASCAN_INDEXER", "0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, views2 as V2
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
check("no status read: no line", V2.data_asof() == "")
db.put_blob("status", {"epochs_closed": 23, "checkpoint_height": 129073, "as_of": "2026-10-30T11:48:16.546Z"})
db.write("UPDATE blobs SET ts=? WHERE kind='status'", (int(time.time()) - 3 * 3600 - 300,))
h = V2.data_asof(); ts = db.q1("SELECT ts FROM blobs WHERE kind='status'")["ts"]
check("line reads Data as of <age>, live time element on the read time", h.startswith('<span class="dasof"') and "Data as of <time" in h and f'data-ts="{ts}"' in h and "3h 5m ago" in h)
check("tooltip names the source and the node as_of", 'title="Our last good read of minepoa.com /api/status (node as of 11:48Z). An older copy of this page is stale."' in h)
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "views2.py"), encoding="utf-8").read()
check("the Health tab note carries it (one line, no sub-line under a stat)", "{_board()}{data_asof()}</p>" in src)
check("no em or en dash", not re.search("[\u2013\u2014]", h + src))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
