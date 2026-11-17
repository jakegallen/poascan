"""1.26.346: /ops/memory gains a sqlite section (live connection count, cache_size, estimated page-cache MB) and a
summary with the tracked / RSS / untracked split. Cheap reads only, JSON-serializable, each part guarded. No network.
Usage: python3 tools/memstats_test.py"""
import json, os, sys, tempfile, threading

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_INDEXER", "0")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "mem.db")
from poascan import db, memstats as M

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

db.init()
r = M.report()
check("report is JSON-serializable", json.dumps(r) and True)
check("report carries the new sqlite and summary sections alongside the old ones",
      "sqlite" in r and "summary" in r and "resident" in r and "caches" in r and "proc" in r)

sq = r["sqlite"]
check("sqlite: live connection count, cache_size, page_size, cache_kib_each, est_cache_mb",
      isinstance(sq.get("live"), int) and sq["live"] >= 1 and isinstance(sq.get("cache_size"), int)
      and isinstance(sq.get("page_size"), int) and isinstance(sq.get("cache_kib_each"), int) and isinstance(sq.get("est_cache_mb"), int))

# the live count rises while another thread holds a connection (the pileup signal), and since 1.26.357 falls back when
# that thread ends without releasing (its holder closes the connection); the counter never goes negative
base = db.conn_stats()["live"]
go, done = threading.Event(), threading.Event()
def hold(): db.conn(); go.set(); done.wait(10)
t = threading.Thread(target=hold); t.start(); go.wait(10)
check("live connection count rises while a thread holds a connection", db.conn_stats()["live"] == base + 1)
done.set(); t.join()
check("and falls back when that thread ends without releasing", db.conn_stats()["live"] == base)

s = r["summary"]
check("summary: rss, rss_anon, rss_file, tracked and untracked, all ints (or None for a field /proc did not give)",
      all(k in s for k in ("rss_mb", "rss_anon_mb", "rss_file_mb", "tracked_mb", "untracked_mb"))
      and isinstance(s["tracked_mb"], int))
check("summary: untracked = RssAnon minus tracked when RssAnon is known",
      s["untracked_mb"] is None or (isinstance(s["rss_anon_mb"], int) and s["untracked_mb"] == s["rss_anon_mb"] - s["tracked_mb"]))
check("proc exposes RssFile (file-backed RSS, reported apart from the anon split)", "RssFile" in r["proc"])

check("no em or en dash in the module or this test",
      not any(c in open(os.path.join(ROOT, f), encoding="utf-8").read() for f in ("poascan/memstats.py", "tools/memstats_test.py") for c in "\u2013\u2014"))

print("FAILED: " + "; ".join(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
