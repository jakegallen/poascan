"""Swap order-placement write check (1.26.127, poascan/hosted.py write_job): the probe is a keyless, unsigned, empty GET
that can never place an offer; open, paused and down map from its answer; the schedule backs off; /api/v1/swaps/status
writes and swaps_writable, the message, the hosted_routes swap_offer entry and the Swap writes health feed follow.
Temp database, no network. Usage: python3 tools/swap_writes_test.py"""
import os, sys, tempfile, urllib.parse
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "w.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import db, hosted as HO, analytics as A
db.init()

# ---- the request can never place an offer ----
req = HO.write_request(); u = urllib.parse.urlsplit(req.full_url); hdr = {k.lower(): v for k, v in req.header_items()}
check("probe is a GET to /api/hosted/swap-offer", req.get_method() == "GET" and u.path == "/api/hosted/swap-offer")
check("probe has no query string (no key, amount, chain, asset, want_amount or to): an invalid order", u.query == "" and "key=" not in req.full_url)
check("probe has no body", req.data is None)
check("probe has no Authorization, key, token, cookie or signature header",
      not any(h in hdr for h in ("authorization", "x-api-key", "x-key", "cookie", "x-signature", "signature", "x-poa-signature", "proxy-authorization")))
check("probe sends only User-Agent and Accept", set(hdr) == {"user-agent", "accept"})
import inspect, re
code = "".join(re.sub(r'""".*?"""|#.*', "", inspect.getsource(f), flags=re.S) for f in (HO.write_request, HO._write_get, HO.write_job))
check("write check code never reads a key, vault or signer", not any(w in code.lower() for w in ("key", "keysafe", "sign", "vault", "authorization", "environ")))

# ---- classification ----
halt = b'{"error":"endpoint temporarily halted, API hardening in progress"}'
check("400/401/403/422 JSON: open", all(HO.write_classify(c, b'{"error":"missing key"}') == "open" for c in (400, 401, 403, 422)))
check("503 with the halt text: paused (maintenance mapping)", HO.write_classify(503, halt) == "paused")
check("502, 503 without halt text, 500: down", all(HO.write_classify(c, b"bad gateway") == "down" for c in (500, 502, 503)))
check("HTML 403 edge page and 404, 429: unknown", HO.write_classify(403, b"<html>blocked") is None and HO.write_classify(404, b"{}") is None and HO.write_classify(429, b"{}") is None)

# ---- job, schedule and outputs ----
T = 1_800_000_000; calls = []
def g(code, body):
    def f(): calls.append(1); return code, body
    return f
HO.write_job(now=T, get=g(503, halt)); w, ok = HO.writes(T + 1)
check("paused recorded with http and checked_at; not writable", w["swap_offer"]["state"] == "paused" and w["swap_offer"]["http"] == 503 and w["swap_offer"]["checked_at"] and ok is False)
check("hosted_routes swap_offer updated outside maintenance", HO.current(T + 1)["swap_offer"]["state"] == "paused" and HO.current(T + 1)["swap_offer"]["checked"] == T)
HO.write_job(now=T + 60, get=g(503, halt)); check("no second probe before next_at", len(calls) == 1)
nx = db.get_blob(HO.WRITE_BLOB)[0]["next_at"]; check("next probe in 10 min with jitter", 540 <= nx - T <= 660)
t = T
for _ in range(3): t = db.get_blob(HO.WRITE_BLOB)[0]["next_at"]; HO.write_job(now=t, get=g(503, halt))
nx = db.get_blob(HO.WRITE_BLOB)[0]["next_at"]; check("backs off to 30 min after repeated identical results", 1740 <= nx - t <= 1860)
t = nx; HO.write_job(now=t, get=g(401, b'{"error":"missing key"}')); w, ok = HO.writes(t + 1); nx = db.get_blob(HO.WRITE_BLOB)[0]["next_at"]
check("open on 401: writable, back to 10 min", w["swap_offer"]["state"] == "open" and ok is True and 540 <= nx - t <= 660 and HO.current(t + 1)["swap_offer"]["state"] == "open")
def boom(): raise TimeoutError("timed out")
t = nx; HO.write_job(now=t, get=boom); w, ok = HO.writes(t + 1)
check("timeout: down, http null", w["swap_offer"]["state"] == "down" and w["swap_offer"]["http"] is None and ok is False)
check("hosted_routes swap_offer reads unknown (its enum) while writes say down, checked kept current", HO.current(t + 1)["swap_offer"]["state"] == "unknown" and HO.current(t + 1)["swap_offer"]["checked"] == t)

from poascan.swap import market as M
import time as _t
HO.write_job(now=int(_t.time()), get=boom, force=True)
d = M._writes(dict(message="Swaps are live."))
check("swaps/status: writes and swaps_writable, message says order placement is failing", d["writes"]["swap_offer"]["state"] == "down" and d["swaps_writable"] is False
      and d["message"] == "Order placement is failing on the network.")
A._cache.clear(); fd = A.feeds(); row = [f for f in fd["feeds"] if f["label"] == "Swap writes"]
check("health: Swap writes feed is Down", bool(row) and row[0]["state"] == "Down")
HO.write_job(now=int(_t.time()), get=g(422, b'{"error":"bad request"}'), force=True); A._cache.clear()
d = M._writes(dict(message="Swaps are live."))
check("open: message untouched, writable true, feed OK", d["message"] == "Swaps are live." and d["swaps_writable"] is True and [f for f in A.feeds()["feeds"] if f["label"] == "Swap writes"][0]["state"] == "OK")

print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
