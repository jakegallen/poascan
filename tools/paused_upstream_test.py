"""Paused upstream feed (1.26.280). minepoa.com's "temporarily paused" 503 (the Oct 2026 API hardening pause, Retry-After
3600, body {"error": "This endpoint is temporarily paused. ... balances ... are safe ...", "notice": {...}}) is shown as
Paused upstream on the health feeds list and /chain, with the notice, instead of a bare Down or Degraded.

Display only. The fetch, backfill, gating and backoff are unchanged: indexer.fetch() already classifies this body a halt
(strain.py HALT_TEXT), raises Notice, stores nothing, logs "HTTP 503 halted" and respects Retry-After (strain_notice_test
and halt_test cover that path). This test checks the DISPLAY: a paused /api/epochs reads Paused upstream and carries the
notice; the records backfill untouched when a real 200 returns; a plain 503 is still Down. No request leaves the box: a
fake minepoa.com runs in this process. Usage: python3 tools/paused_upstream_test.py"""
import json, os, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ["POASCAN_SEGMENTS"] = "1"
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# The exact shape minepoa.com returns for a paused /api/epochs: HTTP 503, Retry-After 3600, a "temporarily paused" notice.
PAUSED = {"error": "This endpoint is temporarily paused. Your balances, landed answers and pending grades are safe. Retry in a few minutes.",
          "notice": {"severity": "info", "msg": "Hardening the epochs surface; it returns instantly while paused."}}
PLAIN = {"error": "internal server error"}   # an ordinary 503: must still read Down
MODE = ["paused"]
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b = json.dumps(PAUSED if MODE[0] == "paused" else PLAIN).encode()
        self.send_response(503); self.send_header("Content-Type", "application/json; charset=utf-8")
        if MODE[0] == "paused": self.send_header("Retry-After", "3600")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
fk = ThreadingHTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=fk.serve_forever, daemon=True).start()
FAKE = f"http://127.0.0.1:{fk.server_address[1]}"
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "p.db")
os.environ.update(POASCAN_DB=DB, POASCAN_INDEXER="0", POA_BASE=FAKE)
subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=dict(os.environ), check=True, capture_output=True)
from poascan import db, strain as ST, indexer as I, analytics as A, views2 as V2
db.init()

def feed(fd, label):
    return next((f for f in fd["feeds"] if f["label"] == label), None)

# ---- classification (pure): the paused body is a strong halt carrying the notice; a plain 503 is not a halt ----
hit = ST.detect("/api/epochs", PAUSED, {"Retry-After": "3600"})
check("paused body is a halt (strong) and carries the notice text", ST.is_halt(hit) and ST.strong(hit) and "temporarily paused" in hit.get("text", ""))
check("a plain 503 body is not a halt", not ST.is_halt(ST.detect("/api/epochs", PLAIN)))

# Force a close-record gap: /api/status counts more closes than records stored, so Close records would read Degraded.
have = A.epochs_count(); st = db.get_blob("status")[0]; st["epochs_closed"] = have + 4; db.put_blob("status", st); A._cache.clear()

# ---- paused: job_epochs hits the 503, records the halt, keeps every stored close record; the feeds show Paused upstream ----
try: I.job_epochs(force=True); check("job_epochs returns without a stored write on a paused read", True)
except Exception as e: check("job_epochs raised Notice on the paused read (stores nothing, backs off)", type(e).__name__ == "Notice")
r = db.q1("SELECT err, next_at, last_err FROM fetch_log WHERE endpoint='/api/epochs'")
check("fetch unchanged: logged HTTP 503 halted, next read at least Retry-After away (backfill path intact)", r and r["err"] == "HTTP 503 halted" and r["next_at"] - r["last_err"] >= 3600)
check("every stored close record is kept (nothing dropped on a pause)", A.epochs_count() == have)
check("A.epochs_paused() is true while /api/epochs is paused", A.epochs_paused())

A._cache.clear(); fd = A.feeds()
ep = feed(fd, "Epochs"); cr = feed(fd, "Close records")
check("Epochs feed reads Paused upstream, not Down", ep and ep["state"] == "Paused upstream" and ep.get("paused_upstream"))
check("Epochs feed carries the upstream notice", ep and "temporarily paused" in (ep.get("upstream_notice") or ""))
check("Close records reads Paused upstream, not Degraded", cr and cr["state"] == "Paused upstream")
check("a paused feed is not counted a POAScan fault (not in not_ok)", "Epochs" not in fd["not_ok"] and "Close records" not in fd["not_ok"])

html = V2.feeds_html(fd)
seg = html.split('data-feed="Epochs"')[1].split("</li>")[0]
check("the health feeds list shows the Paused upstream tag and a balances-safe note", ">Paused upstream<" in seg and "balances safe" in seg)

# ---- plain 503: no halt, so the feed is still Down ----
ST.reset(); db.write("DELETE FROM fetch_log WHERE endpoint='/api/epochs'"); MODE[0] = "plain"; A._cache.clear()
try: I.job_epochs(force=True)
except Exception: pass
check("A.epochs_paused() is false for a plain 503", not A.epochs_paused())
A._cache.clear(); fd2 = A.feeds()
ep2 = feed(fd2, "Epochs"); cr2 = feed(fd2, "Close records")
check("a plain 503 leaves the Epochs feed Down", ep2 and ep2["state"] == "Down")
check("a plain 503 leaves Close records Degraded (gap, no pause)", cr2 and cr2["state"] == "Degraded")

print("\n" + ("all ok" if not fails else f"{len(fails)} FAILED: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
