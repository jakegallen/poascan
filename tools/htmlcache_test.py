"""Rendered page cache (1.26.202, poascan/htmlcache.py): per-path TTLs, one render per key at a time, byte cap, crawler
and segment kept apart, off by default when the indexer is off; served through the real server it returns the same
page a second time without rendering it again, keeps query strings apart, and never caches an error or API answer.
The background warmer fills the heavy pages. Address freshness window is 300 s. In-process, temp database, no request
leaves the box. Usage: python3 tools/htmlcache_test.py"""
import os, sys, tempfile, threading, time, urllib.error, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "hc.db"), POA_BASE="http://127.0.0.1:9", POASCAN_INDEXER="0", POASCAN_HTML_CACHE="1")
import fixture; fixture.seed()
from poascan import server as SV, indexer as I, htmlcache as HC, views as V

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# ---- module
check("enabled by POASCAN_HTML_CACHE=1 even with the indexer off", HC.ENABLED)
check("TTLs: Health 60, other Network tabs default, Governance 60, About 300, address 30, home 15",
      (HC.ttl("/network", {"tab": ["health"]}), HC.ttl("/network", {"tab": ["token"]}), HC.ttl("/governance", {}), HC.ttl("/about", {}),
       HC.ttl("/address/poa1x", {}), HC.ttl("/", {})) == (60, 15, 60, 300, 30, 15))
check("key: query order does not matter; crawler and segment kept apart",
      HC.key("/a", {"x": ["1"], "y": ["2"]}, None, False) == HC.key("/a", {"y": ["2"], "x": ["1"]}, None, False)
      and HC.key("/a", {}, None, True) != HC.key("/a", {}, None, False) and HC.key("/a", {}, 1, False) != HC.key("/a", {}, None, False))
n = [0]
def slow():
    n[0] += 1; time.sleep(0.3); return "<html>x</html>"
k = HC.key("/slow", {}, None, False)
ts = [threading.Thread(target=lambda: HC.render(k, 15, slow)) for _ in range(6)]
[t.start() for t in ts]; [t.join() for t in ts]
check("six concurrent cold requests render once", n[0] == 1)
check("then served from memory", HC.render(k, 15, slow) == "<html>x</html>" and n[0] == 1)
HC.put(HC.key("/old", {}, None, False), "y", now=time.time() - 100)
check("expired copy is not served", HC.get(HC.key("/old", {}, None, False), 15) is None)
check("non string results (redirects, errors) are not cached", HC.render(HC.key("/t", {}, None, False), 15, lambda: (404, "no")) == (404, "no")
      and HC.get(HC.key("/t", {}, None, False), 15) is None)
mb = HC.MAX_BYTES; HC.MAX_BYTES = 8000
for i in range(20): HC.put(HC.key(f"/e{i}", {}, None, False), "z" * 900, now=time.time() + i)
check("byte cap evicts the oldest", HC.state()["bytes"] <= 8000 and HC.get(HC.key("/e19", {}, None, False), 15) and not HC.get(HC.key("/e0", {}, None, False), 15))
HC.MAX_BYTES = mb
check("address freshness window 300 s", V.ADDR_TTL == 300)

# ---- through the server
def _no(*a, **k): raise I.Busy("no upstream in tests")
I.fetch_tx = _no; I.fetch = _no
srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
HUMAN = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
def get(path):
    rq = urllib.request.Request(base + path, headers={"User-Agent": HUMAN})
    try:
        r = urllib.request.urlopen(rq, timeout=30); return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace")
calls = []
real = SV.page
def counting(p, qs): calls.append(p); return real(p, qs)
SV.page = counting
t0 = time.time(); a = get("/network?tab=health"); t1 = time.time(); b = get("/network?tab=health"); t2 = time.time()
check("Health: 200 twice, rendered once", a[0] == b[0] == 200 and calls.count("/network") == 1)
print(f"     cold {1000*(t1-t0):.0f} ms, cached {1000*(t2-t1):.0f} ms")
get("/network?tab=token")
check("another tab is its own entry", calls.count("/network") == 2)
c = get("/api/v1/health")
check("API answers bypass the page cache and report it", c[0] in (200, 503) and '"page_cache"' in c[1] and "/api/health" not in calls)
check("an unknown page stays a 404", get("/no-such-page")[0] == 404)
# warmer: one pass fills the heavy pages without a request
HC._c.clear(); calls.clear()
stop = threading.Event(); HC.WARM_EVERY = 0.2
wt = threading.Thread(target=HC.warm_loop, args=(SV._warm_render, SV.SG.selected, stop), daemon=True); wt.start()
for _ in range(100):
    if HC.state()["warm"] >= len(HC.WARM): break
    time.sleep(0.2)
stop.set()
check("warmer renders every heavy page", HC.state()["warm"] >= len(HC.WARM))
calls.clear(); get("/governance")
check("a warmed page is served without a render", "/governance" not in calls)
print("FAILS:", fails) if fails else print("ALL OK")
sys.exit(1 if fails else 0)
