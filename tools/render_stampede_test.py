"""Cold-start stampede guard (1.26.284, E4, poascan/htmlcache.py): a render that outlives the waiter wait must not turn
N waiters into N parallel renders on the one core. Waiters serve any stored copy first, then wait once more on the single
in-flight render, and render themselves only as a last resort when nothing is stored (so a caller is never served
nothing). In process, temp database, no request leaves the box. Usage: python3 tools/render_stampede_test.py"""
import os, sys, tempfile, threading
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "rs.db"), POASCAN_INDEXER="0", POASCAN_HTML_CACHE="1")
from poascan import db, htmlcache as HC
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# a render in flight that already signalled (no fresh copy landed), with a stale copy stored: waiters serve the stale
# copy and do NOT render.
k = HC.key("/stamp", {}, None, False)   # not a warm key, so not pinned
HC.put(k, "<html>stale</html>", now=__import__("time").time() - 1000)   # stored but expired
ev = threading.Event(); ev.set()
with HC._lock: HC._inflight[k] = ev   # pretend one render is in flight
calls = [0]
def fn(): calls[0] += 1; return "<html>new</html>"
res = []
def waiter(): res.append(HC.render(k, 15, fn))
ts = [threading.Thread(target=waiter) for _ in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
check("8 concurrent waiters serve the stored copy", all(r == "<html>stale</html>" for r in res))
check("none of the 8 waiters started a render", calls[0] == 0)
with HC._lock: HC._inflight.pop(k, None)

# nothing stored and a stale (signalled) in-flight event: the waiter renders as a last resort rather than serving nothing
k2 = HC.key("/stamp2", {}, None, False)
ev2 = threading.Event(); ev2.set()
with HC._lock: HC._inflight[k2] = ev2
cold = [0]
def fn2(): cold[0] += 1; return "<html>c</html>"
r = HC.render(k2, 15, fn2)
check("a cold waiter with nothing stored renders rather than serving nothing", r == "<html>c</html>" and cold[0] == 1)
with HC._lock: HC._inflight.pop(k2, None)

# the single-render-per-key intent still holds for a true cold key under concurrency (the classic case, fast render)
n = [0]
def slow():
    n[0] += 1; __import__("time").sleep(0.3); return "<html>x</html>"
k3 = HC.key("/stamp3", {}, None, False)
ts = [threading.Thread(target=lambda: HC.render(k3, 15, slow)) for _ in range(6)]
[t.start() for t in ts]; [t.join() for t in ts]
check("six concurrent cold requests render once", n[0] == 1 and HC.get(k3, 15) == "<html>x</html>")

import re
src = open(os.path.join(ROOT, "poascan", "htmlcache.py"), encoding="utf-8").read()
check("no em or en dash", not re.search(r"[\u2013\u2014]", src + open(__file__, encoding="utf-8").read()))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
