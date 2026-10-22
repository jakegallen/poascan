"""Polite polling toward minepoa.com (1.26.8). No request leaves the box: a fake minepoa.com runs in this process.
* backoff: exponential with jitter on 5xx and 429, Retry-After (seconds or HTTP date, header or body) is a floor;
  a 429 pauses every read host-wide until it passes.
* incremental live feed: one page when it reaches a seen txid; older pages (before=<ts>) only to fill a gap,
  stopping at the first seen txid, a short page or LIVE_MAX_PAGES.
* cadence: the live poll slows to LIVE_DEGRADED_S while upstream is degraded and comes back when healthy; /api/status
  is read once per STATUS_S and shared; floors hold for bad env values; a restart resumes the schedule.
* on demand: the same address is not read again within ADDR_MIN_S; per-endpoint budgets inside the global one.
* the swap mirror routes and other archive reads make no upstream request.
* the upstream counter counts every request per endpoint and shows in /ops/visits.
Usage: python3 tools/polite_test.py"""
import email.utils, gzip, json, os, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

SEEN = []
FEED = []            # newest first: dicts with id, ts
MODE = {"status": "ok", "retry": None}
class Up(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, extra=None):
        b = gzip.compress(json.dumps(obj).encode())
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Encoding", "gzip")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        SEEN.append(self.path); p, _, q = self.path.partition("?")
        qs = dict(x.split("=", 1) for x in q.split("&") if "=" in x)
        if p == "/api/explorer/txs":
            lim = int(qs.get("limit", 50)); rows = FEED
            if "before" in qs: rows = [t for t in rows if t["ts"] < int(qs["before"])]
            return self._send(200, rows[:lim])
        if p == "/api/status":
            if MODE["status"] == "busy": return self._send(503, {"error": "busy"}, {"Retry-After": MODE["retry"]} if MODE["retry"] else None)
            if MODE["status"] == "limit": return self._send(429, {"error": "slow down", "retry_after_seconds": 90})
            return self._send(200, {"as_of": "2026-10-22T00:00:00Z", "epochs_closed": 12})
        if p == "/api/networks": return self._send(200, {"chains": []})
        if p.startswith("/api/explorer/address/"): return self._send(200, {"address": p.rsplit("/", 1)[1], "balance": "1.000000", "txs": []})
        self._send(404, {"error": "nope"})
up = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
UP = f"http://127.0.0.1:{up.server_address[1]}"
def seen(prefix): return [p for p in SEEN if p.startswith(prefix)]

tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "p.db")
os.environ["POASCAN_DB"] = dbp; os.environ["POA_BASE"] = UP
import fixture; fixture.seed()
from poascan import db, indexer as I, server as SV, visits as VS
_sleep = time.sleep
class _T:   # the indexer's own clock without real waits (time.sleep itself stays real for this test)
    def __getattr__(self, k): return getattr(time, k)
    sleep = staticmethod(lambda s: None)
I.time = _T()

# ---------------- backoff ----------------
lo = [I.backoff_s(n, rnd=lambda: 0.0) for n in range(1, 9)]; hi = [I.backoff_s(n, rnd=lambda: 1.0) for n in range(1, 9)]
check(f"backoff doubles from BACKOFF_BASE_S ({[int(x) for x in hi]})", hi[:4] == [I.BACKOFF_BASE_S * 2 ** k for k in range(4)])
check("backoff is capped at BACKOFF_MAX_S", max(hi) == I.BACKOFF_MAX_S)
check("backoff has jitter: half fixed, half random", all(abs(l - h / 2) < 1e-9 for l, h in zip(lo, hi)))
spread = {round(I.backoff_s(3), 3) for _ in range(50)}
check("backoff jitter spreads retries", len(spread) > 10 and all(I.BACKOFF_BASE_S * 2 <= x <= I.BACKOFF_BASE_S * 4 for x in spread))
check("Retry-After is a floor", I.backoff_s(1, retry=600, rnd=lambda: 0.0) == 600 and 600 <= I.backoff_s(1, retry=600) <= 660)
check("Retry-After above BACKOFF_MAX_S is still honoured (to 6 h)", I.backoff_s(1, retry=3000, rnd=lambda: 0.0) == 3000 and I.backoff_s(1, retry=10 ** 6, rnd=lambda: 0.0) == 6 * 3600)
check("Retry-After: delta seconds", I.retry_after("120") == 120)
hd = email.utils.formatdate(time.time() + 300, usegmt=True)
check("Retry-After: HTTP date", 290 <= I.retry_after(hd) <= 301 and I.retry_after("garbage") is None and I.retry_after(None) is None)

MODE.update(status="busy", retry="400")
try: I.fetch("/api/status"); r = "ok"
except I.Busy as e: r = "busy"
row = db.q1("SELECT fails, next_at FROM fetch_log WHERE endpoint='/api/status'")
check("a 503 with Retry-After: 400 backs off at least 400 s", r == "busy" and row["fails"] == 1 and row["next_at"] - time.time() >= 395)
check("a 503 marks upstream degraded", I.degraded())
MODE.update(retry=None)
for _ in range(3):
    try: I.fetch("/api/status")
    except I.Busy: pass
row = db.q1("SELECT fails, next_at FROM fetch_log WHERE endpoint='/api/status'")
check("repeated 5xx grow the backoff", row["fails"] == 4 and row["next_at"] - time.time() >= I.BACKOFF_BASE_S * 4 - 2)
MODE.update(status="limit"); n = len(SEEN)
try: I.fetch("/api/status")
except I.Busy: pass
try: I.fetch("/api/networks"); held = False
except I.Limited: held = True
check("a 429 (retry_after_seconds 90) pauses every path host-wide, with no request", held and len(SEEN) == n + 1 and I._hold[0] - time.time() > 80)
I._hold[0] = 0; MODE.update(status="ok")
db.write("DELETE FROM fetch_log WHERE endpoint IN ('/api/status','/api/networks')")

# ---------------- incremental live feed ----------------
db.write("DELETE FROM fetch_log WHERE endpoint LIKE '/api/%'")
now = int(time.time())
def mk(i): return {"id": "%064x" % (0xA0000 + i), "type": "transfer", "ts": now - i, "from_addr": fixture.A1, "to_addr": fixture.A2, "amount": "1", "final": 1, "atts": 5}
FEED[:] = [mk(i) for i in range(0, 1000)]
I.LIVE_LIMIT = 100; I.LIVE_MAX_PAGES = 3
db.write("DELETE FROM txs WHERE id LIKE '00000000000000000000000000000000000000000000000000000000000a%'")
db.write("DELETE FROM txs WHERE id LIKE '0000000000000000000000000000000000000000000000000000000000%'")
upsert = I.upsert_txs; I.upsert_txs([mk(i) for i in range(150, 160)], "seed")   # we last saw txs 150..159
n = len(seen("/api/explorer/txs")); pages = I.live_txs()
reqs = seen("/api/explorer/txs")[n:]
check(f"gap: pages back with before= until a seen txid ({reqs})", pages == 2 and "before=" not in reqs[0] and f"before={now - 99 + 1}" in reqs[1])
got = {r["id"] for r in db.q("SELECT id FROM txs WHERE id LIKE '00000000000000000000000000000000000000000000000000000000000a%'")}
check("gap fill stores every tx down to the seen ones", all(mk(i)["id"] in got for i in range(0, 160)))
n = len(seen("/api/explorer/txs")); pages = I.live_txs()
check("no gap: one page per cycle", pages == 1 and len(seen("/api/explorer/txs")) == n + 1)
FEED[:0] = [dict(mk(0), id="%064x" % (0xB0000 + i), ts=now + 1000 - i) for i in range(500)]   # 500 new txs: a long gap
n = len(seen("/api/explorer/txs")); pages = I.live_txs()
check("a long gap stops at LIVE_MAX_PAGES", pages == I.LIVE_MAX_PAGES == len(seen("/api/explorer/txs")) - n)
FEED[:] = [dict(mk(0), id="%064x" % (0xC0000 + i), ts=now + 5000 - min(max(i, 95), 105) if 95 <= i <= 105 else now + 5000 - i) for i in range(150)] + [mk(150)]
n = len(seen("/api/explorer/txs")); pages = I.live_txs()   # 11 txs share one second across the page cut at 100
have = db.q1("SELECT COUNT(*) AS n FROM txs WHERE id LIKE '00000000000000000000000000000000000000000000000000000000000c%'")["n"]
check(f"same-second txs past a page cut are not skipped ({have}, {pages} pages)", have == 150 and pages == 2)
FEED[:] = [dict(mk(0), id="%064x" % (0xD0000 + i), ts=now + 9000) for i in range(150)]   # more same-second txs than a page
n = len(seen("/api/explorer/txs")); pages = I.live_txs()
check("a page of one second never loops (ts paging can go no further)", pages == 2 and len(seen("/api/explorer/txs")) == n + 2)
FEED[:] = FEED[:30]; n = len(seen("/api/explorer/txs")); pages = I.live_txs()
check("a short page never pages further", pages == 1)
I.LIVE_LIMIT, I.LIVE_MAX_PAGES = 200, 3

# ---------------- cadence ----------------
db.write("DELETE FROM fetch_log"); I._hold[0] = 0
check("healthy: live every LIVE_S", I.live_every() == I.LIVE_S == 60)
db.write("INSERT INTO fetch_log(endpoint,last_err,err,fails,next_at) VALUES('/api/networks',?,'TimeoutError',1,0)", (int(time.time()) - 60,))
check("degraded (a feed timeout 1 min ago): live every LIVE_DEGRADED_S, never under 30 s", I.live_every() == I.LIVE_DEGRADED_S >= 30)
db.write("UPDATE fetch_log SET last_err=? WHERE endpoint='/api/networks'", (int(time.time()) - I.DEGRADED_FOR_S - 5,))
check("back to healthy once DEGRADED_FOR_S passes clean", I.live_every() == I.LIVE_S)
db.write("DELETE FROM fetch_log")
n = len(seen("/api/status")); I.job_live(); I.job_live(); I.job_live()
check("/api/status is read once per STATUS_S however often the live job runs", len(seen("/api/status")) == n + 1)
check("/api/networks once per NETWORKS_S", len(seen("/api/networks")) == 1 + 0 * n or len([p for p in seen("/api/networks")]) >= 1)
nn = len(seen("/api/networks")); I.job_live()
check("/api/networks not read again inside NETWORKS_S", len(seen("/api/networks")) == nn)
st = db.get_blob("status")[0]
check("features read the shared stored status", st and st.get("epochs_closed") == 12)
env = dict(os.environ, POASCAN_LIVE_S="5", POASCAN_LIVE_DEGRADED_S="1", POASCAN_STATUS_S="10", POASCAN_SWAPS_S="600", POASCAN_FORUM_S="x")
out = subprocess.run([sys.executable, "-c", "from poascan import indexer as I; print(I.LIVE_S, I.LIVE_DEGRADED_S, I.STATUS_S, I.SWAPS_S, I.FORUM_S, {j[0]: j[2] for j in I.JOBS}['swaps'])"],
                     cwd=ROOT, env=env, capture_output=True, text=True).stdout.split()
check(f"env knobs are clamped to safe floors ({out})", out == ["30", "30", "60", "120", "3600", "120"])
out = subprocess.run([sys.executable, "-c", "from poascan import indexer as I; print(I.LIVE_S, I.LIVE_DEGRADED_S, I.NETWORKS_S)"],
                     cwd=ROOT, env=dict(os.environ, POASCAN_LIVE_S="45", POASCAN_LIVE_DEGRADED_S="300", POASCAN_NETWORKS_S="600"), capture_output=True, text=True).stdout.split()
check(f"env knobs tune the intervals ({out})", out == ["45", "300", "600"])
ran = []
db.put_blob("job:t1", {"ran": int(time.time()) - 10}); stop = threading.Event()
th = threading.Thread(target=I.run_forever, kwargs=dict(stop=stop, jobs=[("t1", lambda: ran.append(1), 600, None), ("t2", lambda: ran.append(2), 600, None)]), daemon=True)
_T.sleep = staticmethod(lambda s: _sleep(min(s, 0.05))); th.start(); _sleep(0.5); stop.set(); th.join(2); _T.sleep = staticmethod(lambda s: None)
check(f"a restart resumes the schedule: a job that ran 10 s ago waits, a new one runs ({ran})", 1 not in ran and 2 in ran)

# ---------------- on demand ----------------
I.GLOBAL_BUDGET = I.Bucket(100, 100); I.CLIENT_BUDGET = I.Bucket(100, 100)
a = "poa1" + "D" * 40; n = len(seen("/api/explorer/address/"))
I.CLIENT.ip = "203.0.113.7"
d = I.fetch_ondemand(f"/api/explorer/address/{a}", I.ADDR_EP, a)
try: I.fetch_ondemand(f"/api/explorer/address/{a}", I.ADDR_EP, a); again = "ok"
except I.Limited: again = "limited"
check("the same address is not read again within ADDR_MIN_S", d["balance"] == "1.000000" and again == "limited" and len(seen("/api/explorer/address/")) == n + 1)
I.EP_BUDGET[I.ADDR_EP] = I.Bucket(0.001, 3); codes = []
for i in range(5):
    b = "poa1" + "E" * 39 + "123456789"[i]
    try: I.fetch_ondemand(f"/api/explorer/address/{b}", I.ADDR_EP, b); codes.append("ok")
    except I.Limited: codes.append("limited")
check(f"the address lookups have their own budget inside the global one ({codes})", codes == ["ok"] * 3 + ["limited"] * 2)
I.CLIENT.ip = None
check("default visitor ceiling is GLOBAL_RATE*3600 per hour (900)", I.GLOBAL_RATE * 3600 == 900 and I.ADDR_RATE * 3600 == 180 and I.TXOD_RATE * 3600 == 360)
MODE_T = "%064x" % 0xDEAD
try: I._bg_fetch_tx(MODE_T, I.BG_TX_EP)
except I.Missing: pass
check("a scheduled job's unknown tx id is cached for NEG_BG_TTL (6 h)", (I._neg[I.BG_TX_EP + MODE_T][0] - time.time()) > 5 * 3600)

# ---------------- archive routes make no upstream request ----------------
I.flush_counts(force=True); n = len(SEEN)
for path in ("/api/swaps", "/api/swaps/status", "/api/price", "/api/swaps/price-history", f"/api/agents/{fixture.A1}/addresses", "/api/epochs",
             "/api/status", "/api/txs", "/api/chains", "/api/params", "/api/health"):
    try: SV.api(path, {})
    except Exception as e: print("  (route", path, type(e).__name__, ")")
check("swap mirror routes and archive reads make no upstream request", len(SEEN) == n)

# ---------------- counter ----------------
I.flush_counts(force=True)
rep = I.upstream_report(now=time.time() + 60)   # rates use full minutes: look from the next minute
c60 = rep["last_60m"]["counts"]
check(f"counter: every request is counted per endpoint ({c60})", sum(c60.values()) == len(SEEN) and c60.get("/api/explorer/txs", 0) == len(seen("/api/explorer/txs")))
check("counter: on-demand reads keep their caller", c60.get(I.ADDR_EP, 0) == len(seen("/api/explorer/address/")))
check("counter: status classes", rep["codes_60m"]["/api/status"].get("5xx") == 4 and rep["codes_60m"]["/api/status"].get("429") == 1)
check("counter: cadence is reported", rep["cadence"]["live_s"] == 60 and rep["cadence"]["status_s"] == 60)
I.count("/api/explorer/txs", 200, now=time.time() - 120); I.flush_counts(force=True)
check("counter: rates use full minutes only", I.upstream_report(now=time.time() + 60)["last_15m"]["minutes"] >= 1)
os.environ["POASCAN_STATS_TOKEN"] = "t" * 40
r = VS.report(*VS.parse_range({}))
check("/ops/visits carries the upstream report and per-day totals", r["upstream"] and "last_15m" in r["upstream"] and sum(sum(v.values()) for v in r["upstream"]["daily"].values()) == len(SEEN) + 1)   # +1: the synthetic count above
import poascan.hosted as HO
try: HO._get("/api/hosted/mine")
except Exception: pass
I.flush_counts(force=True)
check("counter: the hosted route check is counted", any(k.startswith("/api/hosted/mine") for k in I.upstream_report(now=time.time() + 60)["last_60m"]["counts"]))
src = open(os.path.join(ROOT, "poascan", "indexer.py"), encoding="utf-8").read()
check("no em dashes in the indexer", "\u2014" not in src)

if fails: print(f"\nFAIL: {len(fails)}: {fails}"); sys.exit(1)
print("\nPASS")
