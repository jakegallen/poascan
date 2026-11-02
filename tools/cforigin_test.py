"""Cloudflare-only origin guard (1.26.253): with POASCAN_CF_ONLY on, a request that reached the origin directly (a public
Fly-Client-IP that is not a Cloudflare edge, e.g. a hit straight to poascan.fly.dev) is refused with a cheap 403 before any
routing, DB or upstream work; a request through Cloudflare passes to normal handling; /healthz, a request with no
Fly-Client-IP, and a loopback/private peer are never blocked; with the flag off the guard is a no-op. Stdlib only, no
network, no real database (db.q1 is stubbed to a recorder so a reject can be shown to touch it zero times and a pass-through
to reach it). Usage: python3 tools/cforigin_test.py"""
import email.message, os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(POASCAN_INDEXER="0", POASCAN_MAINTENANCE="0", POASCAN_DB=os.path.join(ROOT, "nonexistent-cforigin-test.db"))
os.environ.pop("POASCAN_CF_ONLY", None)

from poascan import server as SV

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

CF_IP = "173.245.48.5"     # inside Cloudflare's 173.245.48.0/20: a genuine edge
PUB_IP = "8.8.8.8"         # a globally-routable address that is not Cloudflare: a direct-to-fly.dev hit
LOOPBACK = "127.0.0.1"     # a Fly-internal / health-check socket peer

DB_HITS = []
SV.db.q1 = lambda *a, **k: (DB_HITS.append(a) or [{"x": 1}])   # any DB read is recorded, not run; the reject path must never reach it

def hdrs(d):
    m = email.message.Message()
    for k, v in d.items():
        if v is not None: m[k] = v
    return m

class TH(SV.H):
    """A handler with no socket: send() is captured, everything else is the real request code (_get, do_POST, the guard)."""
    def __init__(self, path="/", command="GET", fci=None, peer=PUB_IP):
        self.sent = []; self._t0 = None
        self.path = path; self.command = command
        self.client_address = (peer, 12345)
        self.headers = hdrs({"Fly-Client-IP": fci, "User-Agent": "test", "Host": "poascan.fly.dev"})
    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None, pre=None):
        self.sent.append((code, body, dict(extra or {}))); return None

def drive(path="/", command="GET", fci=None, peer=PUB_IP):
    DB_HITS.clear(); h = TH(path, command, fci, peer)
    if command == "POST": h.do_POST()
    else: h.do_GET()
    return h

# --- the guard in isolation: cf_origin_blocked() returns True (sent a 403) or False (let the request through) ---
os.environ["POASCAN_CF_ONLY"] = "on"
check("ON: a direct public hit (non-CF Fly-Client-IP) is blocked", TH(fci=PUB_IP).cf_origin_blocked() is True)
check("ON: a Cloudflare-edge Fly-Client-IP passes the guard", TH(fci=CF_IP).cf_origin_blocked() is False)
check("ON: no Fly-Client-IP (local/internal/health) passes the guard", TH(fci=None).cf_origin_blocked() is False)
check("ON: /healthz is never blocked even from a public peer", TH(path="/healthz", fci=PUB_IP).cf_origin_blocked() is False)
check("ON: /api/health is never blocked even from a public peer", TH(path="/api/health", fci=PUB_IP).cf_origin_blocked() is False)
check("ON: a loopback socket peer passes even with a public-looking Fly-Client-IP", TH(fci=PUB_IP, peer=LOOPBACK).cf_origin_blocked() is False)
check("ON: a private socket peer (10.x) passes", TH(fci=PUB_IP, peer="10.0.0.9").cf_origin_blocked() is False)

# (b) a direct hit gets a cheap 403 with a tiny body, no-store, and touches NO DB
h = drive(path="/", fci=PUB_IP)
code, body, extra = h.sent[0]
check("ON: direct GET / -> single 403 response", len(h.sent) == 1 and code == 403)
check("ON: 403 body is small and points at poascan.io", isinstance(body, str) and len(body) < 120 and "poascan.io" in body)
check("ON: 403 is no-store and not indexed", extra.get("Cache-Control") == "no-store" and "noindex" in (extra.get("X-Robots-Tag") or ""))
check("ON: the reject path makes zero DB reads (no routing/DB/upstream work)", DB_HITS == [])

# (b') the same for POST /mcp: refused before the body is read or the rate limiter is touched
h = drive(path="/mcp", command="POST", fci=PUB_IP)
check("ON: direct POST /mcp -> single 403, zero DB reads", len(h.sent) == 1 and h.sent[0][0] == 403 and DB_HITS == [])

# (a) a Cloudflare request passes THROUGH to normal handling: /healthz reaches the DB read and returns 200
h = drive(path="/healthz", fci=CF_IP)
check("ON: Cloudflare GET /healthz passes through to handling (200, DB read reached)", h.sent[-1][0] == 200 and DB_HITS != [])

# (c) /healthz from a direct public hit is still served normally, never a 403
h = drive(path="/healthz", fci=PUB_IP)
check("ON: /healthz direct still served (200, not 403)", h.sent[-1][0] == 200 and all(c != 403 for c, _, _ in h.sent))

# (d) a request with no Fly-Client-IP (internal/health) passes through to handling
h = drive(path="/healthz", fci=None, peer=LOOPBACK)
check("ON: no Fly-Client-IP -> served normally (200)", h.sent[-1][0] == 200)

# (e) flag OFF: the guard is a pure no-op, even a direct public hit is served normally
os.environ["POASCAN_CF_ONLY"] = "off"
check("OFF: cf_origin_blocked() is False for a direct public hit", TH(fci=PUB_IP).cf_origin_blocked() is False)
h = drive(path="/healthz", fci=PUB_IP)
check("OFF: direct GET /healthz served normally (200, no 403)", h.sent[-1][0] == 200 and all(c != 403 for c, _, _ in h.sent))
os.environ.pop("POASCAN_CF_ONLY", None)
check("UNSET: cf_origin_blocked() is False (ships inert)", TH(fci=PUB_IP).cf_origin_blocked() is False)

# no em or en dash in this test's source
src = open(os.path.abspath(__file__), encoding="utf-8").read()
check("no em or en dash in the test source", "\u2013" not in src and "\u2014" not in src)

print("all passed" if not fails else f"{len(fails)} failed"); sys.exit(1 if fails else 0)
