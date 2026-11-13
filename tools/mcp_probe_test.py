"""MCP directory probes do not take a heavy slot (1.26.273). Glama checks a connector hourly by opening an MCP
connection and listing tools. When every heavy slot is held, initialize, tools/list, ping, GET /mcp and the discovery
JSON (mcp.json, server-card, ai-catalog, agent-card) still answer their normal statuses. A single get_swap_status tools/call is also light (1.26.321). Other tools/call still shed 503, and once a slot is free they run (the body was already read to classify).
Run: python3 tools/mcp_probe_test.py (temp db, in-process, no network)."""
import json, os, sys, tempfile, threading, time, urllib.error, urllib.request
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "mcp.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_MAX_WORKERS"] = "4"
os.environ["POASCAN_SERVE_RESERVE"] = "2"
os.environ["POASCAN_HEAVY_WAIT"] = "0.3"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

from poascan import guard as GD, db, agentapi as AG
import poascan.server as SV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

db.init()

# ---------------------------------------------------------------- 1. classification, no socket
ok(AG.mcp_light(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})), "initialize is light")
ok(AG.mcp_light(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})), "tools/list is light")
ok(AG.mcp_light(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})), "ping is light")
ok(AG.mcp_light(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})), "a notification is light")
ok(AG.mcp_light(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_swap_status", "arguments": {}}})),
   "a single get_swap_status tools/call is light")
ok(not AG.mcp_light(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_route_status", "arguments": {}}})),
   "other tools/call stay heavy")
batch = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
         {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_swap_status", "arguments": {}}}]
ok(not AG.mcp_light(json.dumps(batch)), "a batch that contains tools/call is heavy")
ok(AG.mcp_light(b"not json"), "an unparseable body is light (the handler answers 400)")

# ---------------------------------------------------------------- 2. live server, both pools full
heavy, cheap = [], []
while GD.slots.acquire(blocking=False): heavy.append(1)
while GD.cheap is not None and GD.cheap.acquire(blocking=False): cheap.append(1)
ok(len(heavy) == GD.HEAVY_CAP and len(cheap) == GD.RESERVE_CAP, f"heavy {len(heavy)} and cheap {len(cheap)} slots held")
ran = []
real = AG.handle_mcp
def wrapped(raw):
    try: ran.append(json.loads(raw).get("method"))
    except Exception: ran.append("bad")
    return real(raw)
AG.handle_mcp = wrapped
srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": "Glama-health"}

def post(method, params=None, note=False):
    body = {"jsonrpc": "2.0", "method": method}
    if not note: body["id"] = 1
    if params is not None: body["params"] = params
    raw = json.dumps(body).encode()
    rq = urllib.request.Request(base + "/mcp", data=raw, headers=H)
    t0 = time.time()
    try:
        r = urllib.request.urlopen(rq, timeout=5); return r.status, r.read(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - t0
    except Exception as e:
        return None, str(e).encode(), time.time() - t0

def get(path, headers):
    rq = urllib.request.Request(base + path, headers=headers)
    t0 = time.time()
    try:
        r = urllib.request.urlopen(rq, timeout=5); return r.status, r.read(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - t0

c, b, dt = post("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "glama", "version": "0"}})
info = json.loads(b).get("result", {}).get("serverInfo", {}) if c == 200 else {}
ok(c == 200 and info.get("version") == AG.VERSION and dt < 0.5, f"initialize 200 while slots are full ({c}, {info.get('version')}, {dt*1000:.0f} ms)")
c, b, dt = post("tools/list")
tools = json.loads(b).get("result", {}).get("tools", []) if c == 200 else []
ok(c == 200 and len(tools) == 54 and dt < 0.5, f"tools/list 200 with 54 tools while slots are full ({c}, {len(tools)}, {dt*1000:.0f} ms)")
c, b, dt = post("ping")
ok(c == 200 and json.loads(b).get("result") == {} and dt < 0.5, f"ping 200 while slots are full ({c}, {dt*1000:.0f} ms)")
c, b, dt = post("notifications/initialized", note=True)
ok(c == 202 and dt < 0.5, f"notifications/initialized 202 while slots are full ({c}, {dt*1000:.0f} ms)")
c, b, dt = get("/mcp", {"Accept": "text/event-stream", "User-Agent": "Glama-health"})
ok(c == 405 and dt < 0.5 and b"server busy" not in b, f"GET /mcp is 405, not 503, while slots are full ({c}, {dt*1000:.0f} ms)")
for path, pred in (
    ("/.well-known/mcp.json", lambda d: d.get("url") == "https://poascan.io/mcp" and len(d.get("tools") or []) == 54),
    ("/mcp/server-card", lambda d: d.get("version") == AG.VERSION and d.get("name") == "io.github.jakegallen/poascan"),
    ("/.well-known/ai-catalog.json", lambda d: (d.get("entries") or [{}])[0].get("type") == "application/mcp-server-card+json"),
    ("/.well-known/agent-card.json", lambda d: d.get("version") == AG.VERSION),
):
    c, b, dt = get(path, {"Accept": "application/json", "User-Agent": "Glama-health"})
    body = {}
    try: body = json.loads(b)
    except Exception: pass
    ok(c == 200 and pred(body) and dt < 0.5, f"GET {path} 200 while slots are full ({c}, {dt*1000:.0f} ms)")
ran.clear()
c, b, dt = post("tools/call", {"name": "get_swap_status", "arguments": {}})
sc = json.loads(b).get("result", {}) if c == 200 else {}
ok(c == 200 and "tools/call" in ran and "structuredContent" in sc and dt < 0.5,
   f"get_swap_status 200 with no heavy slot ({c}, ran={ran}, {dt*1000:.0f} ms)")
body = (sc.get("structuredContent") or {})
ok("write_ok" in body and "swap_writes_up" in body and "chain" in body and "last_incident" in body,
   "get_swap_status under load carries the bot snapshot fields")
ran.clear()
c, b, dt = post("tools/call", {"name": "get_route_status", "arguments": {}})
ok(c == 503 and b"server busy" in b and "tools/call" not in ran and dt >= 0.25,
   f"other tools/call still shed 503 when the heavy pool is full ({c}, ran={ran}, {dt*1000:.0f} ms)")

# the classify step already read the body; a later heavy call with a free slot must still run
for _ in heavy: GD.slots.release()
for _ in cheap: GD.cheap.release()
c, b, dt = post("tools/call", {"name": "get_route_status", "arguments": {}})
sc = json.loads(b).get("result", {}) if c == 200 else {}
ok(c == 200 and "tools/call" in ran and "structuredContent" in sc, f"a heavy tools/call runs once a slot is free ({c}, {dt*1000:.0f} ms)")

srv.shutdown()
ok(not any(chr(0x2013) in ln or chr(0x2014) in ln for ln in open(__file__, encoding="utf-8")), "no em or en dash in this test")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
