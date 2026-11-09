"""Warmer owns its pages (1.26.286, poascan/htmlcache.py). When render() serves an old pin and its background refresh
cannot start (the cheap reserve is full under load), the warm pass renders the page itself once it is past TTL plus
grace, so a warmed page can no longer sit stale for most of an hour. Inside the grace window nothing extra renders.
Census and Community are warmed, and Community caches 300 s. In process, temp database, no network.
Usage: python3 tools/warm_direct_test.py"""
import os, sys, tempfile, threading, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "wd.db"), POASCAN_INDEXER="0", POASCAN_HTML_CACHE="1")
from poascan import db, htmlcache as HC
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

check("census and community are warmed", "/agents/census" in HC.WARM and "/agents/community" in HC.WARM)
check("community caches 300 s like census", HC.ttl("/agents/community", {}) == 300 and HC.ttl("/agents/census", {}) == 300)
full = threading.Semaphore(0)   # the cheap reserve, full: every background refresh is refused
HC._reserve = lambda: full
HC.WARM[:] = ["/network?tab=health"]; HC._warm_set.clear(); HC._warm_url_by.clear()
k = HC.key("/network", {"tab": ["health"]}, None, False); t = HC.ttl("/network", {"tab": ["health"]})
renders = []
def rp(p, qs): renders.append((p, qs)); return f"<html>new {len(renders)}</html>"

HC.put(k, "<html>old</html>", now=time.time() - (t + HC.WARM_GRACE - 20))   # past TTL, inside grace
HC.warm_once(rp)
check("inside the grace window: the old pin is served and the warmer does not render it itself", HC.last(k) == "<html>old</html>" and not renders and HC.stats["warm_direct"] == 0)

HC.put(k, "<html>old</html>", now=time.time() - (t + HC.WARM_GRACE + 600))   # ten minutes past grace, refresh refused
HC.warm_once(rp)
check("past TTL plus grace with the refresh refused: the warmer renders and publishes a new copy", HC.last(k) == "<html>new 1</html>" and len(renders) == 1 and HC.stats["warm_direct"] == 1)
check("that direct render counts as a warm success", HC.warm_paths["/network?tab=health"]["ok"] >= 1)
HC.warm_once(rp)
check("the next pass finds a fresh copy and renders nothing", len(renders) == 1)
check("no em or en dash in this test", not any(c in open(__file__, encoding="utf-8").read() for c in "\u2014\u2013"))
sys.exit(1 if fails else 0)
