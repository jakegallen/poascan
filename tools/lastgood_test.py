"""Last-good visitor pages through an epoch close (1.26.275).

Warmed pages sit outside the 24 MB FIFO and are served at any age with no worker slot. /fragment/chart?c=agents and
/status do the same when the heavy pool is full. Address, tx and epoch-record reads still take a heavy slot, but only
SCRAPE_MAX run at once and a waiter does not sit out a long upstream read. A close republishes without clearing the pin.

Run: python3 tools/lastgood_test.py (temp db, in-process, no network)."""
import os, sys, tempfile, threading, time, urllib.error, urllib.request
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "lg.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_HTML_CACHE"] = "1"
os.environ["POASCAN_MAX_WORKERS"] = "4"
os.environ["POASCAN_SERVE_RESERVE"] = "2"
os.environ["POASCAN_HEAVY_WAIT"] = "0.3"
os.environ["POASCAN_VISITOR_WAIT"] = "0.2"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

from poascan import guard as GD, db, htmlcache as HC, segments as SG, indexer as I, views as V, chartpop as CP, live as LV
import poascan.server as SV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

db.init()
HUMAN = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
seg = SG.selected()
src_ix = open(os.path.join(ROOT, "poascan", "indexer.py"), encoding="utf-8").read()
ok('POASCAN_ONDEMAND_TIMEOUT", "3"' in src_ix and 'POASCAN_VISITOR_WAIT", "2"' in src_ix,
   "a visitor upstream read gives up in 3 s and a waiter in 2 s")
ok(I.VISITOR_WAIT == 0.2 and I.ONDEMAND_TIMEOUT == 3, f"this process uses the short waiter ({I.VISITOR_WAIT}, timeout {I.ONDEMAND_TIMEOUT})")

# ---------------------------------------------------------------- 1. pin is outside the FIFO
mb = HC.MAX_BYTES
HC._c.clear(); HC._pin.clear(); HC._bytes[0] = 0
HC.MAX_BYTES = 20000
home = HC.key("/", {}, seg, False)
HC.put(home, "PINNED-HOME", now=time.time() - 10000)
ok(home in HC._pin and home not in HC._c and HC._bytes[0] == 0, "the homepage pin is not counted in the 24 MB FIFO")
for i in range(40):
    HC.put(HC.key("/privacy", {"n": [str(i)]}, seg, False), "z" * 800, now=time.time())
ok(HC.last(home) == "PINNED-HOME" and 0 < HC._bytes[0] <= HC.MAX_BYTES and len(HC._c) < 40,
   f"flooding the FIFO evicts ordinary pages and keeps the pin ({len(HC._c)} entries, {HC._bytes[0]} bytes)")
ok(HC.within(home, SV.H.CHEAP_STALE) is None and HC.last(home) == "PINNED-HOME",
   "a pin older than CHEAP_STALE is still last-good")
HC.MAX_BYTES = mb

# ---------------------------------------------------------------- 2. close republishes without blanking
k = HC.key("/", {}, seg, False)
HC.put(k, "OLD-HOME", now=time.time())
seen = []
def rp(p, qs):
    if p == "/":
        seen.append(HC.last(HC.key("/", {}, seg, False)))
        time.sleep(0.15)
        return "NEW-HOME"
    return "PAGE"
def reader():
    time.sleep(0.05)
    seen.append(HC.last(k))
threading.Thread(target=reader, daemon=True).start()
HC.note_close()
ok(HC._close_due[0] is True, "note_close marks a rebuild")
with HC._lock:
    force = HC._close_due[0]; HC._close_due[0] = False
HC.warm_once(rp, lambda: seg, force=True)
time.sleep(0.05)
ok(seen and all(x == "OLD-HOME" for x in seen), f"readers kept the previous homepage during the rebuild ({seen})")
ok(HC.last(k) == "NEW-HOME" and k in HC._pin, "the new render replaced the pin only when it was finished")
job = src_ix.split("def job_epochs")[1].split("\nclass ")[0]
ok("note_close" in job and "_c.clear" not in job and "_pin.clear" not in job,
   "close ingest wakes a republish and does not clear the page cache")

# ---------------------------------------------------------------- 3. a second address read does not hold the worker for the upstream timeout
a = "poa1" + "Q" * 40
ev = threading.Event()
with V._addr_lock:
    V._addr_inflight[a] = ev
t0 = time.time()
d, err, at = V.address_read(a)
dt = time.time() - t0
with V._addr_lock:
    V._addr_inflight.pop(a, None)
ok(err and dt < 1.0, f"address waiter sheds from local data in about VISITOR_WAIT ({dt*1000:.0f} ms, err={err!r})")

# ---------------------------------------------------------------- 4. scrape cap: past SCRAPE_MAX, 503 without taking a heavy slot
class Req(SV.H):
    def __init__(self, path):
        self.path = path; self.command = "GET"; self.headers = {"User-Agent": HUMAN}; self.sent = []
    def send(self, code, *a, **k):
        self.sent.append(code); return code

ok(Req("/api/v1/address/poa1" + "A" * 40)._is_scrape() and Req("/api/epoch/51/rewards")._is_scrape()
   and Req("/api/epoch/51/record")._is_scrape() and Req("/tx/" + "ab" * 32)._is_scrape(),
   "address, tx and epoch record/rewards are capped")
ok(not Req("/api/summary")._is_scrape() and not Req("/")._is_scrape(), "the homepage and the live snapshot are not scrape work")
held_s = []
while GD.scrape.acquire(blocking=False): held_s.append(1)
ok(len(held_s) == GD.SCRAPE_MAX, f"test holds every scrape slot ({len(held_s)})")
ran = []
t0 = time.time()
addr = Req("/api/v1/address/poa1" + "B" * 40)
addr._gated(lambda: (ran.append(1), "ADDR")[1])
dt = time.time() - t0
ok(addr.sent == [503] and not ran and dt < 0.2, f"an extra address read 503s without waiting out HEAVY_WAIT ({dt*1000:.0f} ms)")
n = 0
while GD.slots.acquire(blocking=False): n += 1
ok(n == GD.HEAVY_CAP, f"that 503 did not take a heavy slot ({n} still free)")
for _ in range(n): GD.slots.release()
rew = Req("/api/v1/epoch/51/rewards"); ran = []
t0 = time.time()
rew._gated(lambda: (ran.append(1), "RW")[1])
ok(rew.sent == [503] and not ran and time.time() - t0 < 0.2, "an extra epoch rewards read 503s the same way")
for _ in held_s: GD.scrape.release()

# ---------------------------------------------------------------- 5. FIFO full and both pools exhausted: / and the Agents chart are last-good, no slot
HC._c.clear(); HC._bytes[0] = 0
age = time.time() - 10000   # far past CHEAP_STALE
HC.put(HC.key("/", {}, seg, False), "<html>HOME-OLD</html>", now=age)
HC.put(HC.key("/network", {"tab": ["health"]}, seg, False), "<html>HEALTH-OLD</html>", now=age)
CP.remember("agents", "", 800, '{"title":"Agents","pin":"AGENTS-CHART"}')
chart_calls, page_calls = [], []
def slow_payload(*a, **k):
    chart_calls.append(1); time.sleep(30); return {"title": "Agents", "pin": "REBUILT"}
CP.payload = slow_payload
def bomb(p, qs):
    page_calls.append(p); time.sleep(30); return "RENDERED"
SV.page = bomb
heavy, cheap = [], []
while GD.slots.acquire(blocking=False): heavy.append(1)
while GD.cheap is not None and GD.cheap.acquire(blocking=False): cheap.append(1)
ok(len(heavy) == GD.HEAVY_CAP and len(cheap) == GD.RESERVE_CAP, f"holds heavy {len(heavy)} and cheap {len(cheap)}")
HC.MAX_BYTES = 20000
for i in range(40):
    HC.put(HC.key("/privacy", {"n": [str(i)]}, seg, False), "q" * 800, now=time.time())
ok(HC.last(HC.key("/", {}, seg, False)) == "<html>HOME-OLD</html>" and len(HC._c) < 40 and HC._bytes[0] <= HC.MAX_BYTES,
   f"the homepage pin survived a full FIFO ({len(HC._c)} entries)")
srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()

class _NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        return None
_opener = urllib.request.build_opener(_NoRedir)

def get(path):
    rq = urllib.request.Request(base + path, headers={"User-Agent": HUMAN})
    t0 = time.time()
    try:
        r = _opener.open(rq, timeout=4)
        return r.status, dict(r.headers), r.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as e:
        return None, {}, str(e), time.time() - t0

c, _, body, dt = get("/")
ok(c == 200 and "HOME-OLD" in body and dt < 1.0, f"GET / serves last-good with both pools full ({c}, {dt*1000:.0f} ms)")
c, _, body, dt = get("/?nocache=1")
ok(c == 200 and "HOME-OLD" in body and dt < 1.0, f"GET /?nocache=1 is the same pin ({c}, {dt*1000:.0f} ms)")
c, hd, body, dt = get("/fragment/chart?c=agents")
ok(c == 200 and "AGENTS-CHART" in body and "Agents" in body and "REBUILT" not in body and dt < 1.0,
   f"GET /fragment/chart?c=agents serves last-good with the heavy pool full ({c}, {dt*1000:.0f} ms)")
c, hd, body, dt = get("/status")
loc = hd.get("Location") or ""
ok(c == 301 and "/network?tab=health" in loc and dt < 1.0, f"/status redirects with no slot ({c}, {loc}, {dt*1000:.0f} ms)")
c, _, body, dt = get("/network?tab=health")
ok(c == 200 and "HEALTH-OLD" in body and dt < 1.0, f"the /status target is last-good too ({c}, {dt*1000:.0f} ms)")
time.sleep(0.2)
ok(page_calls == [], f"visitor pages were not rebuilt on the request ({page_calls})")
ok(not GD.slots.acquire(blocking=False), "GET / and the chart did not take a heavy slot")
ok(GD.cheap is None or not GD.cheap.acquire(blocking=False), "they did not take a reserved slot either")

# snapshot: a reader is not blocked on a refresh when a copy already exists
hub = LV.Hub(lambda: (time.sleep(2), {"n": 1})[1])
hub.last_json = '{"t":"snap","n":0}'; hub.last_at = time.time() - 30
t0 = time.time(); got = hub.snapshot(); dt = time.time() - t0
ok(got == '{"t":"snap","n":0}' and dt < 0.3, f"live snapshot returns the pinned copy without waiting ({dt*1000:.0f} ms)")

for _ in heavy: GD.slots.release()
for _ in cheap: GD.cheap.release()
srv.shutdown()
ok(not any(chr(0x2013) in ln or chr(0x2014) in ln for ln in open(__file__, encoding="utf-8")), "no em or en dash in this test")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
