"""health-fix 1026: minepoa's single-id sheds (503 "origin busy" for an id its edge does not hold, 503 "global capacity
guard" when the chain tx path's cross-IP ceiling is full) are not endpoint failures; shed ids are negative cached for at
least the Retry-After; a full ceiling holds that path; every single-tx request shares a 30 a minute budget; a failed
hourly read is retried after its backoff. Temp database, a local fake minepoa, no network. Usage: python3 tools/healthfix_test.py"""
import http.server, json, os, sys, tempfile, threading, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), None)
os.environ.pop("POASCAN_SEGMENTS", None)
os.environ.update(POASCAN_DB=os.path.join(tmp, "h.db"), POASCAN_INDEXER="0", POA_BASE=f"http://127.0.0.1:{srv.server_port}", POASCAN_MAINTENANCE="0")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

KNOWN = "a" * 64; UNKNOWN = "b" * 64; OTHER = "c" * 64
MODE = {"chain": "full", "explorer": "edge", "params": "ok"}; HITS = []
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, retry=None):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        if retry: self.send_header("Retry-After", str(retry))
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path; HITS.append(p)
        if p.startswith("/chain/"):
            if MODE["chain"] == "full": return self._send(503, {"error": "global capacity guard: tx is serving at its cross-IP ceiling (60/min, 4 concurrent) \u2014 retry shortly", "retry_after_seconds": 60}, 60)
            return self._send(200, {"id": p[-64:], "type": "transfer", "final": 1})
        if p.startswith("/api/explorer/tx/"):
            tid = p[-64:]
            if MODE["explorer"] == "down": return self._send(503, {"error": "origin busy \u2014 retry shortly", "retry_after_seconds": 60}, 60)
            if tid == UNKNOWN: return self._send(503, {"error": "origin busy \u2014 retry shortly", "retry_after_seconds": 60}, 60)
            return self._send(200, {"id": tid, "type": "transfer", "final": 1})
        if p.startswith("/api/params"):
            if MODE["params"] == "timeout": time.sleep(3)
            return self._send(200, {"K": 5})
        if p.startswith("/api/release") or p.startswith("/api/chains"): return self._send(200, {})
        if p.startswith("/api/networks"): return self._send(200, {"default_chain": "poa-mainnet-1", "chains": [{"chain_id": "poa-mainnet-1", "status": "live", "default": True}]})
        return self._send(404, {"error": "nope"})
srv.RequestHandlerClass = H
threading.Thread(target=srv.serve_forever, daemon=True).start()

from poascan import db
db.init()
db.put_blob("networks", {"default_chain": "poa-mainnet-1", "chains": [{"chain_id": "poa-mainnet-1", "status": "live", "default": True}]})
from poascan import indexer as I, analytics as A
log = lambda ep: db.q1("SELECT * FROM fetch_log WHERE endpoint=?", (ep,)) or {}

# 1) chain path full, explorer serves the known id: one chain try, then the chain path is held; fails stay 0
HITS.clear(); d = I.fetch_tx(KNOWN, I.TX_EP, 5)
check(f"known id: chain path shed, explorer answers ({HITS})", d["id"] == KNOWN and len(HITS) == 2 and HITS[0].startswith("/chain/"))
check(f"a capacity guard shed is not an endpoint failure (fails {log(I.TX_EP).get('fails')}, next_at {log(I.TX_EP).get('next_at')})", not log(I.TX_EP).get("fails") and not log(I.TX_EP).get("next_at"))
check(f"the chain path is on hold for at least its Retry-After ({I.shed_state()['path_hold']})", I.shed_state()["path_hold"].get("chain", 0) >= 55)
HITS.clear(); I.fetch_tx(OTHER, I.TX_EP, 5)
check(f"while held, the chain path is not asked again ({HITS})", HITS == ["/api/explorer/tx/" + OTHER])

# 2) an id the edge does not hold: 503 origin busy -> Shed, no endpoint backoff, negative cached >= 60 s, never re-asked
HITS.clear()
try: I.fetch_ondemand("/api/explorer/tx/" + UNKNOWN, I.TX_EP, UNKNOWN); r = None
except I.Shed as e: r = e
check(f"origin busy for one id is Shed with the Retry-After ({r!r})", isinstance(r, I.Shed) and r.retry >= 60)
check(f"one shed id does not back off the endpoint (fails {log(I.TX_EP).get('fails')})", not log(I.TX_EP).get("fails") and I.can_fetch(I.TX_EP))
until = I._neg[I.TX_EP + UNKNOWN][0] - time.time()
check(f"the shed id is negative cached for at least 60 s ({int(until)} s)", until >= 60 and I._neg[I.TX_EP + UNKNOWN][1] is I.Shed)
n = len(HITS)
try: I.fetch_ondemand("/api/explorer/tx/" + UNKNOWN, I.TX_EP, UNKNOWN)
except I.Busy: pass
check("a cached shed id makes no request", len(HITS) == n)
check("Shed is a Busy (pages show the busy state, the API falls back to the archive)", issubclass(I.Shed, I.Busy) and not issubclass(I.Shed, I.Missing))
d = I.fetch_ondemand("/api/explorer/tx/" + KNOWN, I.TX_EP, KNOWN)
check("other ids still read after a shed id", d["id"] == KNOWN)

# 3) scheduled reads: a shed id is cached as Shed (not Missing, so a swap is never marked dropped by it)
try: I._bg_fetch_tx(UNKNOWN, I.SWAP_TX_EP); r = None
except I.Busy as e: r = e
check(f"swap tx read: shed, not missing ({type(r).__name__})", type(r) is I.Shed)
try: I._bg_fetch_tx(UNKNOWN, I.SWAP_TX_EP); r = None
except I.Busy as e: r = e
check(f"the cached entry raises Shed again, not Missing ({type(r).__name__})", type(r) is I.Shed)

# 4) feeds: sheds alone keep Tx lookup and Swaps OK
db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,fails,next_at) VALUES('/api/swaps',?,0,0)", (int(time.time()),))
A._cache.clear(); st = {f["label"]: f["state"] for f in A.feeds()["feeds"]}
check(f"Tx lookup and Swaps OK after sheds only ({st.get('Tx lookup')}, {st.get('Swaps')})", st.get("Tx lookup") == "OK" and st.get("Swaps") in ("OK", None))

# 5) 1.26.166: sheds of different ids never add up (the answer sample reads ids minepoa's edge may not hold), on any key
MODE["explorer"] = "down"; I._path_hold.clear(); MODE["chain"] = "full"
for i in range(I.SHED_RUN + 3):
    I._neg.clear(); I._path_hold.clear(); I._tx_window.clear()
    try: I._bg_fetch_tx("%064x" % (i + 200), I.BG_TX_EP)
    except I.Busy: pass
check(f"{I.SHED_RUN + 3} sheds of different ids on the sample key: no failure, no backoff ({log(I.BG_TX_EP).get('fails')}, {I.shed_state()['sheds'].get(I.BG_TX_EP)})",
      not log(I.BG_TX_EP).get("fails") and I.can_fetch(I.BG_TX_EP) and I.shed_state()["sheds"][I.BG_TX_EP]["id_run"] == 1)
A._cache.clear(); st = {f["label"]: f["state"] for f in A.feeds()["feeds"]}
check(f"Tx lookup stays OK after sample sheds of many ids ({st.get('Tx lookup')})", st.get("Tx lookup") == "OK")
# 5b) minepoa really busy for one id: SHED_RUN sheds of the same id with no good read count as a failure (endpoint backoff, Degraded)
tid = "%064x" % 100
for i in range(I.SHED_RUN):
    I._neg.clear(); I._path_hold.clear(); I._tx_window.clear(); MODE["chain"] = "full"
    try: I.fetch_tx(tid, I.SWAP_TX_EP, 5)
    except I.Busy: pass
check(f"{I.SHED_RUN} sheds of one id in a row with no good read: a failure ({log(I.SWAP_TX_EP).get('fails')})", (log(I.SWAP_TX_EP).get("fails") or 0) >= 1)
MODE["explorer"] = "edge"; I._path_hold.clear(); I._neg.clear()
I.fetch_tx(KNOWN, I.SWAP_TX_EP, 5)
check("a good read ends the run and clears the failure", not log(I.SWAP_TX_EP).get("fails") and I.SWAP_TX_EP not in I._sheds)

# 6) one budget for every single-tx request: at most 30 in any 60 s
I._tx_window.clear(); t0 = 1_000_000.0
took = [I.tx_budget_take(t0 + i * 0.1) for i in range(31)]
check(f"budget: 30 taken, the 31st waits ({took.count(0)}, {took[-1]})", took.count(0) == 30 and took[-1] > 0)
check("budget: free again 60 s after the first", I.tx_budget_take(t0 + 60.01) == 0)
check("budget: never above 30 even if the env asks for more", I.TX_PER_MIN <= 30)
I._tx_window.clear()
for _ in range(I.TX_PER_MIN): I.tx_budget_take()
HITS.clear()
try: I.fetch_tx(OTHER, I.TX_EP, 5); r = None
except I.Limited as e: r = e
check(f"budget spent: fetch_tx sends nothing and says Limited ({r!r}, {HITS})", isinstance(r, I.Limited) and HITS == [])
I._tx_window.clear()

# 7) hourly retry: one failed params read is retried after its backoff, once, not an hour later
I.fetch.__globals__  # noqa
now = int(time.time())
db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,last_err,err,fails,next_at) VALUES('/api/params',?,?,'TimeoutError',1,?)", (now - 6600, now - 2900, now - 2800))
HITS.clear(); n = I.job_hourly_retry()
check(f"failed hourly read retried once after its backoff ({n}, {HITS})", n == 1 and HITS == ["/api/params"] and not log("/api/params").get("fails"))
HITS.clear(); n = I.job_hourly_retry()
check(f"nothing to retry when the last read was good ({n}, {HITS})", n == 0 and HITS == [])
db.write("UPDATE fetch_log SET fails=1, last_err=?, next_at=? WHERE endpoint='/api/params'", (now + 5, now + 900))
HITS.clear(); n = I.job_hourly_retry()
check("still backing off: no retry", n == 0 and HITS == [])
check("hourly_retry is scheduled every 5 min", ("hourly_retry", I.job_hourly_retry, 300, None) in [tuple(j) for j in I.JOBS])

# 8) /api/health shows the shed state, never a key or an id
from poascan import server as SV
ah = SV.api("/api/health", {})[0]
check("/api/health carries tx_reads (sheds, holds, budget)", set(ah["tx_reads"]) >= {"sheds", "path_hold", "tx_requests_last_min", "tx_per_min"} and ah["tx_reads"]["tx_per_min"] <= 30)
check("tx_reads holds no tx id", UNKNOWN not in json.dumps(ah["tx_reads"]) and KNOWN not in json.dumps(ah["tx_reads"]))
src = open(os.path.join(ROOT, "poascan", "indexer.py")).read()
check("no em or en dash added in the new code", all(c not in src[src.index("health-fix 1026: shed"):src.index("_hold = [0.0]")] for c in "\u2013\u2014"))
srv.shutdown()
print("all passed" if not fails else f"{len(fails)} failed"); sys.exit(1 if fails else 0)
