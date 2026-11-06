"""swaps/status clearance (1.26.278). Local copy, no heavy slot, no upstream wait.
UNKNOWN is not DOWN. A halt answer is DOWN. A stale copy is UNKNOWN and available is false.
write_ok is true only when every write route is OK and fresh. Join clearance is separate.
Usage: python3 tools/swapstatus_test.py"""
import json, os, sys, tempfile, threading, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "s.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_MAX_WORKERS"] = "4"
os.environ["POASCAN_SERVE_RESERVE"] = "1"
os.environ["POASCAN_HEAVY_WAIT"] = "0.2"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
sys.path.insert(0, ROOT)
from poascan import db, hosted as HO, guard as GD
from poascan.swap import hoststatus as SS
import poascan.server as SV

fails = []
def check(n, c):
    print(("ok   " if c else "FAIL ") + n); c or fails.append(n)

db.init()
HALT = b'{"error":"endpoint temporarily halted, API hardening in progress"}'
now = time.time()

def probe(code, body, t=None):
    HO.write_job(now=int(t or time.time()), get=lambda: (code, body), force=True)

# cold: no pin, UNKNOWN, not DOWN, available false, under the call itself (no wait)
SS.reset()
t0 = time.time(); cold = SS.serve(); dt = time.time() - t0
check("cold serve is fast", dt < 1)
check("cold: available false, write_ok false, stale, state unknown",
      cold["available"] is False and cold["write_ok"] is False and cold["stale"] is True and cold["state"] == "unknown")
check("cold: join and swap_writes are UNKNOWN, not DOWN",
      cold["join"]["state"] == "UNKNOWN" and cold["swap_writes"]["state"] == "UNKNOWN"
      and cold["swap_writes"]["routes"]["swap_offer"]["state"] == "UNKNOWN" and "DOWN" not in json.dumps(cold["swap_writes"]))
check("stale_after_s is 2160 in the body", cold["stale_after_s"] == 2160 == SS.STALE_AFTER_S)
check("cold legacy fields are present and not open",
      cold["writes"]["swap_offer"]["state"] == "unknown" and cold["swap_route"]["state"] == "unknown"
      and cold["join_state"] == "unknown" and cold["maintenance_active"] is True and cold["swaps_writable"] is None)

# a builder that hangs must not block serve
def hang():
    time.sleep(3)
SS._refresh = hang
SS._building[0] = False
SS._pin.update(facts=None, extra=None, built_at=None)
t0 = time.time(); hung = SS.serve(); dt = time.time() - t0
check(f"upstream hang: serve returns without waiting ({dt:.2f}s)", dt < 1 and hung["write_ok"] is False)
time.sleep(0.05)

db.put_blob("upgrade_complete", dict(at=int(now) - 10, notice_id="2026-10-23-grading-resumed", seen_at=int(now)))
db.write("INSERT OR REPLACE INTO fetch_log(endpoint, last_ok, fails, next_at) VALUES('/api/notices', ?, 0, 0)", (int(now),))
db.put_blob("notices", {"active": []})
# halt answer: DOWN, available false, write_ok false. Join stays separate.
def boom(): raise TimeoutError("timed out")
probe(503, HALT)
body = SS.build()
check("halt: swap_offer DOWN, write_ok false, available false",
      body["swap_writes"]["routes"]["swap_offer"]["state"] == "DOWN" and body["swap_writes"]["state"] == "DOWN"
      and body["write_ok"] is False and body["available"] is False)
check("halt does not force join DOWN", body["join"]["state"] in ("OK", "UNKNOWN"))
check("halt keeps writes.swap_offer paused, not open",
      body["writes"]["swap_offer"]["state"] == "paused" and body["swap_route"]["state"] == "paused"
      and body["swaps_writable"] is False and body["join_state"] != "halted")

# timeout: UNKNOWN, not DOWN, and a previous open does not stay available
probe(401, b'{"error":"missing key"}')
opened = SS.build()
check("open probe: swap_offer OK and write_ok true", opened["swap_writes"]["routes"]["swap_offer"]["state"] == "OK" and opened["write_ok"] is True and opened["available"] is True)
check("open probe: legacy swap_offer and swap_route are open",
      opened["writes"]["swap_offer"]["state"] == "open" and opened["swap_route"]["state"] == "open" and opened["swaps_writable"] is True)
HO.write_job(now=int(time.time()), get=boom, force=True)
timed = SS.build()
check("timeout after open: UNKNOWN, available false, not DOWN",
      timed["swap_writes"]["routes"]["swap_offer"]["state"] == "UNKNOWN" and timed["available"] is False
      and timed["write_ok"] is False and timed["swap_writes"]["state"] != "DOWN")
check("timeout does not leave a stale open on the legacy fields",
      timed["writes"]["swap_offer"]["state"] == "unknown" and timed["swap_route"]["state"] == "unknown" and timed["swaps_writable"] is None)

# stale copy: a stored DOWN must be served as UNKNOWN
facts = {"join_route": {"kind": "DOWN", "ts": now}, "notices": {"kind": "OK", "ts": now},
         "maintenance": {"kind": "OK", "ts": now}, "writes": {"swap_offer": {"kind": "DOWN", "ts": now}},
         "flag_status": "live", "flag_basis": "poaswap"}
old = now - SS.STALE_AFTER_S - 50
stale = SS.render(facts, {"status": "live"}, old, now)
check("stale copy: UNKNOWN not DOWN, available false, write_ok false",
      stale["stale"] is True and stale["available"] is False and stale["write_ok"] is False
      and stale["swap_writes"]["state"] == "UNKNOWN" and stale["swap_writes"]["routes"]["swap_offer"]["state"] == "UNKNOWN"
      and stale["join"]["state"] == "UNKNOWN" and "DOWN" not in json.dumps(stale["swap_writes"]) + json.dumps(stale["join"])
      and stale["writes"]["swap_offer"]["state"] == "unknown" and stale["swap_route"]["state"] == "unknown"
      and stale["join_state"] == "unknown" and stale["maintenance_active"] is True and stale["swaps_writable"] is None)

# fresh DOWN stays DOWN and overrides available even if the flag says live
fresh = SS.render(facts, {"status": "live", "available": True}, now, now)
check("fresh halt facts: DOWN overrides available",
      fresh["swap_writes"]["routes"]["swap_offer"]["state"] == "DOWN" and fresh["available"] is False and fresh["write_ok"] is False and fresh["stale"] is False)

# join DOWN does not clear a good write, and a good write does not clear a bad join
facts_j = dict(facts, writes={"swap_offer": {"kind": "OK", "ts": now}})
both = SS.render(facts_j, {"status": "live"}, now, now)
check("join DOWN and write OK stay separate: write_ok true, join DOWN",
      both["write_ok"] is True and both["available"] is True and both["join"]["state"] == "DOWN")

# full heavy pool: the HTTP route still answers quickly
SS.build()
srv = SV.Server(("127.0.0.1", 0), SV.H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
held = 0
while GD.slots.acquire(blocking=False): held += 1
t0 = time.time()
raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/swaps/status", timeout=2).read()
dt = time.time() - t0
got = json.loads(raw)
m = got.get("meta", {}).get("maintenance") or {}
check(f"full heavy pool ({held} slots): 200 in under 1s ({dt:.2f}s)", dt < 1 and got["stale_after_s"] == 2160 and "write_ok" in got and "swap_offer" in got["swap_writes"]["routes"])
check("http keeps meta.maintenance.active, join_state, swap_route and writes.swap_offer, and unknown is not open",
      "active" in m and m.get("join_state") == got.get("join_state") and (m.get("swap_route") or {}).get("state") == got["writes"]["swap_offer"]["state"]
      and got["writes"]["swap_offer"]["state"] in ("open", "paused", "down", "unknown")
      and got["writes"]["swap_offer"]["state"] != "open")
for _ in range(held):
    try: GD.slots.release()
    except ValueError: pass
srv.shutdown()

# samples for the contract (printed once, not a failure)
ok_body = SS.render({"join_route": {"kind": "OK", "ts": now}, "notices": {"kind": "OK", "ts": now},
                     "maintenance": {"kind": "OK", "ts": now}, "writes": {"swap_offer": {"kind": "OK", "ts": now}},
                     "flag_status": "live"}, {"status": "live"}, now, now)
_KEYS = ("as_of", "age_s", "stale", "stale_after_s", "available", "write_ok", "state", "join_state", "maintenance_active", "writes", "swap_route", "join", "swap_writes", "gate")
print("SAMPLE_OK", json.dumps({k: ok_body[k] for k in _KEYS}))
print("SAMPLE_DOWN", json.dumps({k: fresh[k] for k in _KEYS}))
print("SAMPLE_UNKNOWN", json.dumps({k: cold[k] for k in _KEYS}))
print("SAMPLE_STALE", json.dumps({k: stale[k] for k in _KEYS}))

print(f"\n{len(fails)} FAILED" if fails else "\nall ok")
sys.exit(1 if fails else 0)
