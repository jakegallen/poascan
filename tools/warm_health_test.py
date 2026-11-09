"""Honest warm-health accounting (1.26.284, E3, poascan/htmlcache.py): warm_once records a per-path success only when a
render actually stored a new copy (put ran), not when render() returned an existing pin and only fired a background
refresh. The warm_paths / self_render_ms telemetry shape is unchanged. In process, temp database, no request leaves the
box. Usage: python3 tools/warm_health_test.py"""
import os, sys, tempfile, threading, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "wh.db"), POASCAN_INDEXER="0", POASCAN_HTML_CACHE="1")
from poascan import db, htmlcache as HC, guard as GD
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# a single warm path keeps the test deterministic
HC.WARM = ["/warma"]; HC._warm_set.clear(); HC._warm_url_by.clear(); HC.warm_paths.clear(); HC.stats.update(warm=0)
calls = [0]
def rp(p, qs): calls[0] += 1; return f"<html>{p}</html>"
k = HC.key("/warma", {}, None, False)
check("the test path is a warm key", HC._pinned_key(k))

# Case A: a pinned but expired copy, with the background refresh unable to get a slot -> render() returns the old copy
# and stores nothing. warm_once must NOT record a success (no new render happened).
HC.put(k, "<html>old</html>", now=time.time() - 1000)   # expired pin
_cheap = GD.cheap
GD.cheap = threading.BoundedSemaphore(1); GD.cheap.acquire()   # no reserve slot: the background refresh is a no-op
HC.warm_once(rp, force=False)
wp = HC.warm_paths.get("/warma", {})
check("a no-render warm pass does not run the renderer", calls[0] == 0)
check("a no-render warm pass does not bump ok or last_ok", wp.get("ok", 0) == 0 and wp.get("last_ok") is None)
check("the old pin is still served", HC.last(k) == "<html>old</html>")
GD.cheap = _cheap

# Case B: a forced pass renders and stores a new copy -> exactly one success, last_ok set, the pin replaced
HC.warm_once(rp, force=True)
wp = HC.warm_paths.get("/warma", {})
check("a real render bumps ok and sets last_ok", wp.get("ok", 0) == 1 and wp.get("last_ok") and calls[0] == 1)
check("the pin is replaced by the new render", HC.last(k) == "<html>/warma</html>")

# Case C: a background refresh that actually stores a copy is credited as a real warm success (in _refresh)
HC.warm_paths.clear(); calls[0] = 0
HC.put(k, "<html>stale</html>", now=time.time() - 1000)   # expired pin again
ev = HC._refresh(k, lambda: rp("/warma", {}))   # fires the background render (a reserve slot is free now)
for _ in range(100):
    if HC.warm_paths.get("/warma", {}).get("ok"): break
    time.sleep(0.02)
wp = HC.warm_paths.get("/warma", {})
check("a background render that stores a copy counts as a warm success", wp.get("ok", 0) == 1 and wp.get("last_ok") and calls[0] == 1)

# telemetry shape is preserved
HC.WARM = ["/", "/start"]; HC._warm_set.clear(); HC._warm_url_by.clear()
s = HC.state()
check("state keeps warm_paths and self_render_ms shape", "warm_paths" in s and set(s["self_render_ms"]) == {"p50", "p95", "n"} and "warm_total_paths" in s)

import re
src = open(os.path.join(ROOT, "poascan", "htmlcache.py"), encoding="utf-8").read()
check("no em or en dash", not re.search(r"[\u2013\u2014]", src + open(__file__, encoding="utf-8").read()))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
