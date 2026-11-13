"""MCP get_address and /api/v1/address keep returning a light copy when every heavy slot is held (1.26.319).

Root cause covered: tools/call and the address API used to take a heavy slot and shed 503 "server busy".
This path serves balance, spendable_est, locked_est, as_of, read_at and stale from the stored agent list
and close records, with no minepoa.com read and no heavy slot.

Run: python3 tools/addrlight_test.py (temp db, in-process, no network).
"""
import json, os, sys, tempfile, threading, time, urllib.error, urllib.request

os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "addrlight.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_MAX_WORKERS"] = "2"
os.environ["POASCAN_SERVE_RESERVE"] = "1"
os.environ["POASCAN_HEAVY_WAIT"] = "0.3"
os.environ["POASCAN_SCRAPE_WAIT"] = "0.05"
os.environ["POASCAN_HEAVY_MAX"] = "2"
os.environ["POA_BASE"] = "http://127.0.0.1:9"

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

from poascan import db, guard as GD, analytics as A, segments as S, addrlight as AL, agentapi as AG
import poascan.server as SV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

db.init()
NOW = int(time.time())
ADDR = "poa1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
MISS = "poa1BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
db.write("INSERT INTO accounts(addr, balance, balance_s, first_seen, last_seen, api_ts) VALUES(?,?,?,?,?,?)",
         (ADDR, 100.0, "100.000000", NOW - 3600, NOW - 60, NOW - 60))
# one close so vest has a known spendable/locked split
db.put_blob(S.blob_kind(), [{"epoch": 0, "ts": NOW - 600, "close_ts": NOW - 600, "rewards": {ADDR: "80.0"}, "basis": {}}])
A.rewards_by_addr()  # warm the map so the light path does not wait on a compute slot

# ---------------------------------------------------------------- 1. payload from the archive, no HTTP
row = AL.payload(ADDR, reason="cache")
ok(row and row["address"] == ADDR and str(row["balance"]).startswith("100"),
   f"light payload has balance ({row.get('balance') if row else None})")
ok(row and row["spendable_est"] is not None and row["locked_est"] is not None,
   f"light payload has spendable_est and locked_est ({row.get('spendable_est')}, {row.get('locked_est')})")
ok(row and row.get("read_at") and "T" in row["read_at"] and row["read_at"].endswith("Z"),
   f"read_at is an ISO UTC timestamp ({row.get('read_at') if row else None})")
ok(row and "as_of" in row and "stale" in row and row.get("served") == "light",
   "as_of, stale and served=light are present")
ok(AL.payload(MISS, reason="cache") is None, "an unknown address returns None, never a guessed balance")

ok(AL.is_get_address_call(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "get_address", "arguments": {"address": ADDR}}})),
   "a get_address tools/call is detected")
ok(not AL.is_get_address_call(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                          "params": {"name": "get_swap_status", "arguments": {}}})),
   "other tools/call bodies are not a get_address call")
ok(not AL.is_get_address_call(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})),
   "tools/list is not a get_address call")

class Stub(SV.H):
    def __init__(self, path, command="GET", raw=None):
        self.path = path; self.command = command; self.headers = {}; self.sent = []; self._mcp_raw = raw
    def send(self, code, *a, **k): self.sent.append(code); return code

ok(Stub("/api/v1/address/" + ADDR)._is_address_light_path(), "/api/v1/address/<poa1> is a light path")
ok(Stub("/api/address/" + ADDR)._is_address_light_path(), "/api/address/<poa1> is the same path")
ok(not Stub("/api/v1/address/" + ADDR + "/standing")._is_address_light_path(), "/standing is not the light path")
ok(not Stub("/api/v1/address/" + ADDR + "/txs")._is_address_light_path(), "/txs is not the light path")
ok(not Stub("/address/" + ADDR)._is_address_light_path(), "the HTML address page is not the light path")
raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_address", "arguments": {"address": ADDR}}}).encode()
ok(Stub("/mcp", "POST", raw)._is_address_light_path(), "MCP get_address is a light path")
raw_swap = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_swap_status", "arguments": {}}}).encode()
ok(not Stub("/mcp", "POST", raw_swap)._is_address_light_path(), "MCP get_swap_status stays off the light path")

# ---------------------------------------------------------------- 2. live server, every slot held
heavy, cheap = [], []
while GD.slots.acquire(blocking=False): heavy.append(1)
while GD.cheap is not None and GD.cheap.acquire(blocking=False): cheap.append(1)
# also hold scrape so the old path would have shed
scrape = []
while GD.scrape.acquire(blocking=False): scrape.append(1)
ok(len(heavy) == GD.HEAVY_CAP, f"held every heavy slot ({len(heavy)} of {GD.HEAVY_CAP})")

srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()

def get(path):
    rq = urllib.request.Request(base + path, headers={"User-Agent": "addrlight-test"})
    t0 = time.time()
    try:
        r = urllib.request.urlopen(rq, timeout=5); return r.status, r.read(), dict(r.headers), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers), time.time() - t0
    except Exception as e:
        return None, str(e).encode(), {}, time.time() - t0

def post_mcp(name, args=None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}).encode()
    rq = urllib.request.Request(base + "/mcp", data=body, headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "addrlight-test"})
    t0 = time.time()
    try:
        r = urllib.request.urlopen(rq, timeout=5); return r.status, r.read(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - t0
    except Exception as e:
        return None, str(e).encode(), time.time() - t0

c, b, hd, dt = get("/api/v1/address/" + ADDR)
try: data = json.loads(b)
except Exception: data = {}
ok(c == 200, f"/api/v1/address 200 while every slot is held (got {c}, body {b[:120]!r})")
ok(dt < 1.0, f"light address API did not wait for a heavy slot ({dt*1000:.0f} ms)")
ok(isinstance(data, dict) and str(data.get("balance", "")).startswith("100")
   and "spendable_est" in data and "locked_est" in data
   and data.get("read_at") and "stale" in data,
   f"API light body has balance, spendable_est, locked_est, read_at, stale ({list(data)[:12] if isinstance(data, dict) else None})")
ok(data.get("served") == "light" and "recent_txs" not in data and "txs" not in data,
   "under load the API light copy omits tx history")
# not the plain busy line
ok(b[:12] != b"server busy,", "the body is not the busy 503 line")

c, b, dt = post_mcp("get_address", {"address": ADDR})
try: mcp = json.loads(b)
except Exception: mcp = {}
sc = (mcp.get("result") or {}).get("structuredContent") or {}
ok(c == 200 and not (mcp.get("result") or {}).get("isError"),
   f"MCP get_address 200 while every slot is held (got {c}, err={ (mcp.get('result') or {}).get('isError') })")
ok(dt < 1.0, f"MCP get_address light path did not wait for a heavy slot ({dt*1000:.0f} ms)")
ok(sc.get("balance") is not None and "spendable_est" in sc and "locked_est" in sc
   and sc.get("read_at") and "stale" in sc and sc.get("served") == "light",
   f"MCP light structuredContent has the balance fields ({list(sc)[:12]})")
ok("recent_txs" not in sc, "under load MCP get_address omits tx history")

# a different tools/call still sheds 503 when slots are full
c, b, dt = post_mcp("get_swap_status", {})
ok(c == 503 and b.startswith(b"server busy"), f"MCP get_swap_status still sheds 503 when slots are full (got {c})")

# release slots: a full get_address then includes history and read_at
for _ in scrape: GD.scrape.release()
for _ in heavy: GD.slots.release()
for _ in cheap: GD.cheap.release()

c, b, dt = post_mcp("get_address", {"address": ADDR})
try: mcp = json.loads(b)
except Exception: mcp = {}
sc = (mcp.get("result") or {}).get("structuredContent") or {}
ok(c == 200 and sc.get("read_at") and "recent_txs" in sc and sc.get("served") != "light",
   f"with a free slot, get_address is the full payload plus read_at (keys include { [k for k in ('read_at','recent_txs','served','balance') if k in sc] })")

print(f"\n{len(fails)} FAILED" if fails else "\nall ok")
sys.exit(1 if fails else 0)
