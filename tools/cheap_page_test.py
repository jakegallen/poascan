"""Cheap pages stay servable from the rendered copy (1.26.272).

A cache buster on / or /chain is not a different page, so it must reuse the canonical copy instead of taking a reserved
slot. Filling the page cache with other pages must not evict the warmed homepage or /chain. When every cheap slot is
held, those paths still return the stored copy instead of 503.

Run: python3 tools/cheap_page_test.py (temp db, in-process, no network)."""
import os, sys, tempfile, threading, time, urllib.error, urllib.request
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "cheap.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_HTML_CACHE"] = "1"
os.environ["POASCAN_MAX_WORKERS"] = "4"
os.environ["POASCAN_SERVE_RESERVE"] = "2"
os.environ["POASCAN_HEAVY_WAIT"] = "0.3"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

from poascan import guard as GD, db, htmlcache as HC, segments as SG
import poascan.server as SV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

db.init()
HUMAN = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

# ---------------------------------------------------------------- 1. canonical query
ok(HC.canon_qs("/", {"nocache": ["1"], "fbclid": ["x"]}) == {}, "homepage query is not part of the page")
ok(HC.canon_qs("/chain", {"nocache": ["1"], "tab": ["pending"]}) == {"tab": ["pending"]},
   "/chain keeps tab and drops a cache buster")
ok(HC.canon_qs("/chain", {"sort": ["pool"], "dir": ["asc"], "utm": ["a"]}) == {"sort": ["pool"], "dir": ["asc"]},
   "/chain keeps sort and dir")
seg = SG.selected()
class Req(SV.H):
    def __init__(self, path):
        self.path = path; self.headers = {"User-Agent": HUMAN}
bits = Req("/?nocache=1")._bits()
ok(bits[0] == "/" and bits[1] == {} and bits[3] is False, f"a nocache homepage request canonicalises ({bits})")
ok(HC.key(*bits) == HC.key("/", {}, seg, False), "that request uses the canonical homepage key")

# ---------------------------------------------------------------- 2. eviction keeps the warmed homepage and /chain
mb = HC.MAX_BYTES
try:
    HC._c.clear(); HC._bytes[0] = 0
    HC.MAX_BYTES = 8000
    k_old = HC.key("/about", {}, seg, False)
    k_home = HC.key("/", {}, seg, False)
    k_chain = HC.key("/chain", {}, seg, False)
    HC.put(k_old, "OLD-PAGE", now=time.time())
    HC.put(k_home, "HOME-COPY", now=time.time())
    HC.put(k_chain, "CHAIN-COPY", now=time.time())
    for i in range(20):
        HC.put(HC.key("/address/poa1%04d" % i, {}, seg, False), "z" * 900, now=time.time())
    ok(HC.within(k_home, 30) == "HOME-COPY" and HC.within(k_chain, 30) == "CHAIN-COPY",
       "flooding the page cache does not evict the warmed homepage or /chain")
    ok(HC.within(k_old, 30) is None, "an ordinary page is still evicted when the cache is over its cap")
    ok(HC.within(HC.key("/address/poa1%04d" % 19, {}, seg, False), 30), "the newest ordinary page is kept")
finally:
    HC.MAX_BYTES = mb; HC._c.clear(); HC._bytes[0] = 0

# ---------------------------------------------------------------- 3. cheap slots full: stale canonical copy is served, a real /chain tab is not collapsed
age = time.time() - 200   # past the homepage TTL plus warm grace, inside CHEAP_STALE
HC.put(HC.key("/", {}, seg, False), "<html>HOME-COPY</html>", now=age)
HC.put(HC.key("/chain", {}, seg, False), "<html>CHAIN-COPY</html>", now=age)
calls = []
def bomb(p, qs):
    calls.append(p); time.sleep(30); return "RENDERED-NOT-CACHE"
SV.page = bomb
held = []
while GD.cheap.acquire(blocking=False): held.append(1)
ok(len(held) == GD.RESERVE_CAP, f"test holds every cheap slot ({len(held)})")
srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()

def get(path):
    rq = urllib.request.Request(base + path, headers={"User-Agent": HUMAN})
    try:
        r = urllib.request.urlopen(rq, timeout=3); return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)

for path, marker in (("/?nocache=1", "HOME-COPY"), ("/?fbclid=abc", "HOME-COPY"), ("/", "HOME-COPY"),
                     ("/chain?nocache=1", "CHAIN-COPY"), ("/chain", "CHAIN-COPY")):
    t0 = time.time(); code, body = get(path); dt = time.time() - t0
    ok(code == 200 and marker in body and dt < 1.0, f"{path} serves the stored copy with the reserve full ({code}, {dt*1000:.0f} ms)")
code, body = get("/chain?tab=pending")
ok(code == 503 and "HOME-COPY" not in body and "CHAIN-COPY" not in body,
   f"a real /chain tab is not replaced by the default page ({code})")
time.sleep(0.3)
ok(calls == [], f"serving the stored copy does not render ({calls})")
for _ in held: GD.cheap.release()
srv.shutdown()

ok(not any(chr(0x2013) in ln or chr(0x2014) in ln for ln in open(__file__, encoding="utf-8")), "no em or en dash in this test")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
