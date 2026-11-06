"""Inner pages and the live snapshot when the heavy pool is full (1.26.274).

/api/v1/health is the same slot-exempt check as /api/health. /api/summary and /api/v1/summary answer without waiting
for a heavy slot, and the edge is told not to serve an old snapshot after an origin error. /start, /help, /about and
/agents serve a stored copy. An address read and MCP tools/call still shed 503.
Run: python3 tools/visitor_slot_test.py (temp db, in-process, no network)."""
import json, os, sys, tempfile, threading, time, urllib.error, urllib.request
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "vis.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_HTML_CACHE"] = "1"
os.environ["POASCAN_MAX_WORKERS"] = "4"
os.environ["POASCAN_SERVE_RESERVE"] = "2"
os.environ["POASCAN_HEAVY_WAIT"] = "0.3"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

from poascan import guard as GD, db, htmlcache as HC, segments as SG, agentapi as AG
import poascan.server as SV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

db.init()
HUMAN = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

class Req(SV.H):
    def __init__(self, path):
        self.path = path; self.command = "GET"; self.headers = {"User-Agent": HUMAN}; self.sent = []
    def send(self, code, *a, **k):
        self.sent.append(code); return code

ok(Req("/api/v1/health")._is_health() is True and Req("/api/health")._is_health() is True, "/api/v1/health matches /api/health")
ok(Req("/api/v1/health")._norm() == Req("/api/health")._norm() == "/api/health", "v1 health normalises to /api/health before the slot check")
ok(Req("/api/summary")._is_snapshot() and Req("/api/v1/summary")._is_snapshot() and Req("/api/summary?nocache=1")._is_snapshot(),
   "both summary URLs, including a cache buster, are the live snapshot")
ok(not Req("/api/v1/address/poa1" + "A" * 40)._is_health() and not Req("/api/v1/address/poa1" + "A" * 40)._is_snapshot(),
   "an address read stays on the heavy pool")

# classification: health and summary run at once with every slot held; an address read waits then 503s
heavy, cheap = [], []
while GD.slots.acquire(blocking=False): heavy.append(1)
while GD.cheap is not None and GD.cheap.acquire(blocking=False): cheap.append(1)
ok(len(heavy) == GD.HEAVY_CAP and len(cheap) == GD.RESERVE_CAP, f"holds heavy {len(heavy)} and cheap {len(cheap)}")
for p in ("/api/health", "/api/v1/health", "/api/summary", "/api/v1/summary"):
    called = []
    t0 = time.time()
    r = Req(p)._gated(lambda: (called.append(1), "SERVED")[1])
    dt = time.time() - t0
    ok(called == [1] and r == "SERVED" and dt < 0.2, f"{p} does not wait for a heavy slot ({r}, {dt*1000:.0f} ms)")
addr = Req("/api/v1/address/poa1" + "B" * 40); ran = []
t0 = time.time()
addr._gated(lambda: (ran.append(1), "ADDR")[1])
dt = time.time() - t0
ok(addr.sent == [503] and not ran and dt >= 0.25, f"address API still sheds 503 ({addr.sent}, {dt*1000:.0f} ms)")
for _ in heavy: GD.slots.release()
for _ in cheap: GD.cheap.release()
heavy, cheap = [], []

# HTTP: stored inner pages, a real summary, and the shed paths
seg = SG.selected()
age = time.time() - 500   # past TTL and warm grace, inside CHEAP_STALE
for path, marker in (("/start", "START-COPY"), ("/help", "HELP-COPY"), ("/about", "ABOUT-COPY"), ("/agents", "AGENTS-COPY")):
    HC.put(HC.key(path, {}, seg, False), "<html>" + marker + "</html>", now=age)
calls = []
def bomb(p, qs):
    calls.append(p); time.sleep(30); return "RENDERED"
SV.page = bomb
while GD.slots.acquire(blocking=False): heavy.append(1)
while GD.cheap is not None and GD.cheap.acquire(blocking=False): cheap.append(1)
srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()

def get(path, headers=None):
    rq = urllib.request.Request(base + path, headers=headers or {"User-Agent": HUMAN})
    t0 = time.time()
    try:
        r = urllib.request.urlopen(rq, timeout=4); return r.status, dict(r.headers), r.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as e:
        return None, {}, str(e), time.time() - t0

for path, marker in (("/start", "START-COPY"), ("/start?nocache=1", "START-COPY"), ("/help", "HELP-COPY"),
                     ("/about", "ABOUT-COPY"), ("/agents", "AGENTS-COPY")):
    c, _, body, dt = get(path)
    ok(c == 200 and marker in body and dt < 1.0, f"{path} serves the stored copy ({c}, {dt*1000:.0f} ms)")
time.sleep(0.2)
ok(calls == [], f"stored inner pages are not rendered while slots are full ({calls})")

for path in ("/api/summary", "/api/v1/summary", "/api/summary?nocache=1"):
    c, hd, body, dt = get(path)
    ok(c == 200 and dt < 1.0 and hd.get("Cache-Control") == "no-store", f"{path} 200 without a heavy slot ({c}, {dt*1000:.0f} ms, {hd.get('Cache-Control')})")
    if path == "/api/summary":
        cdn = hd.get("CDN-Cache-Control") or ""
        ok("stale-if-error=0" in cdn and "max-age=30" in cdn and "must-revalidate" in cdn,
           f"summary edge cache cannot revive an old epoch on a 503 ({cdn!r})")
        ok("server busy" not in body, "summary body is the snapshot, not the shed text")

c, _, body, dt = get("/api/v1/address/poa1" + "C" * 40)
ok(c == 503 and "server busy" in body, f"address API 503 while the heavy pool is full ({c}, {dt*1000:.0f} ms)")
raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_swap_status", "arguments": {}}}).encode()
rq = urllib.request.Request(base + "/mcp", data=raw, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
t0 = time.time()
try:
    r = urllib.request.urlopen(rq, timeout=4); mc, mb = r.status, r.read()
except urllib.error.HTTPError as e:
    mc, mb = e.code, e.read()
ok(mc == 503 and b"server busy" in mb and time.time() - t0 >= 0.25, f"tools/call still sheds 503 ({mc})")

for _ in heavy: GD.slots.release()
for _ in cheap: GD.cheap.release()
srv.shutdown()
ok(not any(chr(0x2013) in ln or chr(0x2014) in ln for ln in open(__file__, encoding="utf-8")), "no em or en dash in this test")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
