"""401s and the shared degraded cadence (1.26.147). No request leaves the box: a fake minepoa.com runs in this process.
* a single 401 on a shared feed endpoint does not slow the live poll (live_every stays LIVE_S);
* RUN401 (3) 401s in a row from the same endpoint do (LIVE_DEGRADED_S), and a good read ends the streak;
* 401s spread over different endpoints, or broken by a good read, never add up to a streak;
* a 429, a 5xx and a timeout still slow it at once, as before;
* a 503 is not masked by a later 401 on the same endpoint; a pre-1.26.147 row (no hard_err) counts unless it was a 401.
Usage: python3 tools/backoff_401_test.py"""
import gzip, json, os, socket, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

CODE = {}   # path -> status code to answer with (200 when absent); "slow" sleeps past the read timeout
class Up(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        p = self.path.partition("?")[0]; c = CODE.get(p, 200)
        if c == "slow": time.sleep(1.5); c = 200
        body = {"chains": []} if c == 200 else {"error": "nope"}
        b = gzip.compress(json.dumps(body).encode())
        self.send_response(c); self.send_header("Content-Type", "application/json"); self.send_header("Content-Encoding", "gzip")
        if c == 429: self.send_header("Retry-After", "1")
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        try: self.wfile.write(b)
        except Exception: pass
up = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
UP = f"http://127.0.0.1:{up.server_address[1]}"

tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "b.db"); os.environ["POA_BASE"] = UP
os.environ.pop("POASCAN_UPSTREAM_DEGRADED", None)
import fixture; fixture.seed()
from poascan import db, indexer as I
I.BASE = UP

def reset():
    CODE.clear(); I._hold[0] = 0.0; db.write("DELETE FROM fetch_log")
def hit(path, code, timeout=60):
    CODE[path] = code
    try: I.fetch(path, timeout=timeout); return "ok"
    except Exception as e: return type(e).__name__
def slow(): return I.live_every() == I.LIVE_DEGRADED_S
cols = {r[1] for r in db.conn().execute("PRAGMA table_info(fetch_log)")}
check(f"fetch_log migrated with hard_err and run401 ({sorted(cols)})", {"hard_err", "run401"} <= cols)

reset()
check("healthy: live poll at LIVE_S", not I.degraded() and I.live_every() == I.LIVE_S == 60)
r = hit("/api/networks", 401)
row = db.q1("SELECT err, fails, run401, hard_err FROM fetch_log WHERE endpoint='/api/networks'")
check(f"a single 401 is logged ({dict(row)}) and the read fails", r == "Busy" and row["err"] == "HTTP 401" and row["fails"] == 1 and row["run401"] == 1)
check("a single 401: no slowdown (live_every stays LIVE_S)", not slow() and row["hard_err"] is None)
hit("/api/networks", 401)
check("two 401s in a row: still no slowdown", not slow())
hit("/api/networks", 401)
row = db.q1("SELECT run401, hard_err FROM fetch_log WHERE endpoint='/api/networks'")
check("three 401s in a row from the same endpoint: slowdown to LIVE_DEGRADED_S", slow() and row["run401"] == 3 and row["hard_err"])

reset()
hit("/api/networks", 401); hit("/api/networks", 401); hit("/api/networks", 200); hit("/api/networks", 401); hit("/api/networks", 401)
row = db.q1("SELECT run401, fails FROM fetch_log WHERE endpoint='/api/networks'")
check(f"a good read ends the 401 streak (run401 {row['run401']})", not slow() and row["run401"] == 2)
reset()
hit("/api/networks", 401); hit("/api/status", 401); hit("/api/swaps", 401)
check("one 401 each on three endpoints is not a streak", not slow())

reset()
r = hit("/api/status", 429)
check("a 429 slows at once (host-wide hold, as before)", r == "Busy" and slow())
reset()
r = hit("/api/networks", 503)
check("a 503 slows at once", r == "Busy" and slow())
reset()
hit("/api/swaps", 500)
check("a 500 slows at once", slow())
reset()
r = hit("/api/networks", "slow", timeout=0.3)
row = db.q1("SELECT err FROM fetch_log WHERE endpoint='/api/networks'")
check(f"a timeout slows at once ({r}, {row['err'][:30]})", r == "Busy" and slow())

reset()
hit("/api/networks", 503); hit("/api/networks", 401)
check("a 503 is not masked by a later single 401 on the same endpoint", slow())
reset()
n = int(time.time())
db.write("INSERT INTO fetch_log(endpoint,last_err,err,fails,next_at) VALUES('/api/networks',?,'HTTP 401',1,0)", (n - 30,))
check("a pre-1.26.147 401 row (no hard_err) does not slow the poll", not slow())
db.write("INSERT INTO fetch_log(endpoint,last_err,err,fails,next_at) VALUES('/api/status',?,'HTTP 503',1,0)", (n - 30,))
check("a pre-1.26.147 503 row (no hard_err) still slows it", slow())
db.write("UPDATE fetch_log SET last_err=? WHERE endpoint='/api/status'", (n - I.DEGRADED_FOR_S - 5,))
check("and the slowdown ends after DEGRADED_FOR_S", not slow())
reset()
hit("/api/epochs", 401); hit("/api/epochs", 401); hit("/api/epochs", 401)
check("401s off the shared feed endpoints never slow the live poll", not slow())

up.shutdown()
print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}"); sys.exit(1 if fails else 0)
