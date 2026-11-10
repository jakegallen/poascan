"""Shared User-Agent API throttle (1.26.287, poascan/guard.py ua_throttle, server._ua_throttled). An exact
poa-dashboard/1.0 match shares one token bucket across every IP: the burst passes, the next request is a 429 with
Retry-After, no-store and a short JSON body, sent before any heavy slot is taken. minepoa-dashboard/1.0, browsers,
health checks and non-API pages are never throttled. The bucket refills at the configured rate, and the 429 count shows
in guard telemetry (/api/status diagnostics.mem_guard.ua_throttle). Stdlib only, no network, no database.
Usage: python3 tools/ua_throttle_test.py"""
import email.message, json, os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(POASCAN_INDEXER="0", POASCAN_MAINTENANCE="0", POASCAN_DB=os.path.join(ROOT, "nonexistent-uathrottle-test.db"))
for k in ("POASCAN_UA_THROTTLE", "POASCAN_UA_THROTTLE_RATE", "POASCAN_UA_THROTTLE_BURST"): os.environ.pop(k, None)

from poascan import server as SV, guard as GD

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

def hdrs(d):
    m = email.message.Message()
    for k, v in d.items():
        if v is not None: m[k] = v
    return m

SLOT_TAKES = []
class Sem:
    """Wraps a slot semaphore and records every acquire, so a 429 can be shown to take none."""
    def __init__(self, s): self.s = s
    def acquire(self, *a, **k): SLOT_TAKES.append(1); return self.s.acquire(*a, **k)
    def release(self): return self.s.release()
GD.slots = Sem(GD.slots); GD.scrape = Sem(GD.scrape)
if GD.cheap is not None: GD.cheap = Sem(GD.cheap)

class TH(SV.H):
    def __init__(self, path, ua):
        self.sent = []; self._t0 = None; self.path = path; self.command = "GET"
        self.client_address = ("172.16.5.2", 1)
        self.headers = hdrs({"User-Agent": ua, "Host": "poascan.io", "Fly-Client-IP": "45.39.75.21"})
    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None, pre=None):
        self.sent.append((code, body, dict(extra or {}))); return None
    def _get(self):   # the real router is not under test: a request that got past the gate is recorded as 200
        self.sent.append((200, "routed", {})); return None
    def _html_hit(self): return False

def drive(path, ua):
    h = TH(path, ua); h.do_GET(); return h.sent[-1]

DASH = "poa-dashboard/1.0"
check("defaults: exact poa-dashboard/1.0, 1 per second, burst 5", GD.UA_THROTTLE == (DASH,) and GD.UA_THROTTLE_RATE == 1 and GD.UA_THROTTLE_BURST == 5)

# the pure bucket, on a fixed clock
GD._ua_bucket.clear(); t = 1000.0
got = [GD.ua_throttle(DASH, now=t) for _ in range(6)]
check("bucket: burst of 5 passes, the 6th waits", got[:5] == [0] * 5 and got[5] >= 1)
check("bucket: one token back after 1 s", GD.ua_throttle(DASH, now=t + 1.0) == 0 and GD.ua_throttle(DASH, now=t + 1.0) >= 1)
check("bucket: other agents never spend a token", all(GD.ua_throttle(u, now=t) == 0 for u in ("minepoa-dashboard/1.0", "poa-dashboard/1.0 extra", "POA-DASHBOARD/1.0", "", None, "Mozilla/5.0")))

# through the request gate (real clock; the burst is spent faster than it refills)
GD._ua_bucket.clear(); GD.ua_stats.update(throttled=0, allowed=0)
codes = [drive("/api/v1/address/poa1abc/earn", DASH)[0] for _ in range(5)]
check("gate: first 5 poa-dashboard API requests pass", codes == [200] * 5)
SLOT_TAKES.clear()
code, body, hd = drive("/api/v1/address/poa1abc/earn", DASH)
check("gate: next poa-dashboard API request is 429", code == 429)
check("gate: 429 takes no heavy, scrape or cheap slot", SLOT_TAKES == [])
check("gate: 429 has Retry-After >= 1 and no-store", int(hd.get("Retry-After", "0")) >= 1 and hd.get("Cache-Control") == "no-store")
j = json.loads(body)
check("gate: 429 body is short JSON with retry_after_seconds", j.get("error") == "too many requests" and j.get("retry_after_seconds") == int(hd["Retry-After"]) and len(body) < 300)
check("gate: no dashes in the 429 body", "\u2014" not in body and "\u2013" not in body)
check("gate: /api/receipts and /api (unversioned) are throttled too", drive("/api/receipts", DASH)[0] == 429 and drive("/api", DASH)[0] == 429)
check("gate: health is never throttled", drive("/api/health", DASH)[0] == 200 and drive("/api/v1/health", DASH)[0] == 200)
check("gate: a non-API page is not throttled here", drive("/agents", DASH)[0] == 200)
check("gate: minepoa-dashboard/1.0 is untouched", all(drive("/api/v1/address/poa1abc/earn", "minepoa-dashboard/1.0")[0] == 200 for _ in range(20)))
check("gate: a browser is untouched", all(drive("/api/v1/summary", "Mozilla/5.0")[0] == 200 for _ in range(20)))

tel = GD.telemetry().get("ua_throttle") or {}
check("telemetry: throttled and allowed counts on guard telemetry", tel.get("throttled") == GD.ua_stats["throttled"] >= 3 and tel.get("allowed") == 5 and tel.get("agents") == [DASH])

print("ALL OK" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
