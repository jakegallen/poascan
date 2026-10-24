"""Paused lookups and dropped answers (1.26.89). No request leaves the box: a fake minepoa.com runs in this process and
answers /api/explorer/tx/<id>, /api/notices and /api/chains the way minepoa's API hardening halt did on Oct 24, 2026
(HTTP 503, Retry-After 3600, {"error": "endpoint temporarily halted ...", "notice": {...}, "system_notice": {...}}).
* strain.detect() names it a halt (strong); real bodies are not; the site strip and meta.upstream_notice stay clear.
* indexer.fetch() raises Notice, stores nothing, logs "HTTP 503 halted" and backs off at least 300 s (Retry-After honoured).
* /tx/<indexed> shows the indexed copy under the one line note; /tx/<never indexed> is a clean 200 state with the txid and
  a retry link; the API carries upstream_notice; nothing is a 5xx; a second visit does not reach minepoa again.
* Dropped at close: answers pending at one close and in neither pending nor settled at the next are counted as dropped,
  never as settled; pending rows without since (minepoa from E14) take the archived answer epoch, not E0.
Usage: python3 tools/halt_test.py"""
import json, os, re, socket, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# The exact body minepoa.com sent on Oct 24, 2026 (9:2x AM PT) for all three reads, the system_notice text shortened.
HALT = {"error": "endpoint temporarily halted \u2014 API hardening in progress",
        "notice": {"msg": "We're hardening the API surface. Mining/grading paths are paused and return instantly while we work. Check back hourly at a RANDOM minute.",
                   "until": "surface re-enabled as soon as cleared"},
        "system_notice": {"id": "2026-10-23-grading-economics", "severity": "action", "msg": "ALL PATHS OPEN (answers resumed after a brief protective pause).",
                          "show": "always", "source": "server-override"}}
HITS = []
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        HITS.append(self.path); b = json.dumps(HALT).encode()
        self.send_response(503); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Retry-After", "3600")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
fk = ThreadingHTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=fk.serve_forever, daemon=True).start()
FAKE = f"http://127.0.0.1:{fk.server_address[1]}"
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "h.db")
os.environ.update(POASCAN_DB=DB, POASCAN_INDEXER="0", POA_BASE=FAKE)
subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=dict(os.environ), check=True, capture_output=True)
from poascan import db, strain as ST, indexer as I, analytics as A
db.init()

# ---- detection ----
for p in ("/api/explorer/tx/" + "ab" * 32, "/api/notices", "/api/chains", "/api/tx/" + "ab" * 32):
    h = ST.detect(p, HALT)
    check(f"detect: {p[:22]} is a halt, strong", ST.is_halt(h) and ST.strong(h) and h["signals"][0] == "halt:error")
check("detect: the halt text is sanitized, no em dash", ST.sanitize(ST.detect("/api/chains", HALT)["text"]) == "endpoint temporarily halted, API hardening in progress")
real = {"/api/explorer/tx/" + "ab" * 32: {"id": "ab" * 32, "type": "challenge", "body": {"answer": "endpoint temporarily halted is a phrase"}},
        "/api/notices": {"g0": "poa1" + "S" * 40, "active": [{"id": "x", "msg": "endpoint temporarily halted for maintenance"}]},
        "/api/chains": {"poa1" + "S" * 40: {"solana": {"address": "x", "verified": True}}}}
check("detect: real bodies are never a halt, even when their data quotes the phrase", all(not ST.is_halt(ST.detect(p, d)) for p, d in real.items()))

# ---- fetch: stores nothing, backs off, keeps the last copy ----
db.put_blob("chains", {"poa1" + "K" * 40: {"solana": {"address": "keep", "verified": True}}}); db.put_blob("notices", {"g0": "poa1" + "G" * 40, "active": []})
I.job_meta(); I.job_hourly_meta()
for ep in ("/api/notices", "/api/chains"):
    r = db.q1("SELECT err, next_at, last_err FROM fetch_log WHERE endpoint=?", (ep,))
    check(f"{ep}: logged HTTP 503 halted, next read at least 3600 s away (Retry-After)", r and r["err"] == "HTTP 503 halted" and r["next_at"] - r["last_err"] >= 3600)
check("last real copies kept (chains, notices)", "poa1" + "K" * 40 in db.get_blob("chains")[0] and db.get_blob("notices")[0]["active"] == [])
check("halted() for notices and chains; not shown as strain (no site strip, meta flag null)", I.halted(I.NOTICES_TPL) and I.halted(I.CHAINS_TPL) and ST.public() is None and ST.banner() == "")
n0 = len(HITS); I.job_meta(); I.job_hourly_meta()
check("backing off: a second run reads neither endpoint", not [h for h in HITS[n0:] if h in ("/api/notices", "/api/chains")])
try: I.fetch("/api/explorer/tx/" + "cd" * 32, endpoint="/api/explorer/tx/:id (test)", soft=True); check("tx fetch raises", False)
except I.Notice as e: check("tx fetch: Notice with a retry of at least 300 s", (e.retry or 0) >= 300)
ST._halts.clear()
check("halted() survives a restart from fetch_log (memory cleared)", I.halted(I.CHAINS_TPL) is not None and I.halted(I.NOTICES_TPL) is not None)

# ---- server ----
row = db.q1("SELECT id FROM txs WHERE id NOT IN (SELECT id FROM tx_detail WHERE final=1) ORDER BY ts DESC LIMIT 1")
IDX = row["id"]; NEW = "ef" * 32
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1")
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f"http://127.0.0.1:{port}"
def get(path):
    try:
        with urllib.request.urlopen(base + path, timeout=20) as r: return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    n0 = len(HITS)
    c1, h1 = get("/tx/" + IDX)
    check("/tx/<indexed>: 200 with the indexed copy and the one line note", c1 == 200 and '<p class="ntin" role="status">minepoa.com paused this lookup. Showing indexed data.</p>' in h1 and IDX in h1)
    c2, h2 = get("/tx/" + NEW)
    check("/tx/<never indexed>: 200, the paused state, the txid and a retry link, no error wording",
          c2 == 200 and "Not available while minepoa.com has this lookup paused." in h2 and NEW in h2 and f'href="/tx/{NEW}"' in h2 and "Try again later" in h2
          and "node is busy" not in h2 and "Tx not found" not in h2)
    a1 = json.loads(get("/api/v1/tx/" + IDX)[1]); c3, b3 = get("/api/v1/tx/" + NEW); a2 = json.loads(b3)
    un = a1.get("upstream_notice") or {}
    check("/api/v1/tx/<indexed>: found from the archive with upstream_notice kind halt",
          a1["found"] is True and un.get("kind") == "halt" and un.get("text") == ST.HALT_NOTE and un.get("endpoint") == "/api/explorer/tx/:id" and un.get("data") == "indexed" and un.get("retry_after_ts"))
    check("/api/v1/tx/<never indexed>: 200 found false, available false, node paused, upstream_notice",
          c3 == 200 and a2["found"] is False and a2["available"] is False and a2["node"] == "paused" and a2["upstream_notice"]["kind"] == "halt")
    tx_hits = [h for h in HITS[n0:] if h.startswith("/api/explorer/tx/")]
    get("/tx/" + NEW); get("/api/v1/tx/" + NEW); get("/tx/" + "12" * 32)
    check(f"one minepoa tx read at most, then backed off ({len(tx_hits)} then {len([h for h in HITS[n0:] if h.startswith('/api/explorer/tx/')])})",
          len(tx_hits) <= 1 and len([h for h in HITS[n0:] if h.startswith("/api/explorer/tx/")]) == len(tx_hits))
    ch = json.loads(get("/api/v1/chains")[1]); nv = json.loads(get("/api/v1/notices/verified")[1])
    check("/api/v1/chains: the last copy plus upstream_notice (last_known, as_of)", "poa1" + "K" * 40 in ch and ch["upstream_notice"]["data"] == "last_known" and ch["upstream_notice"]["endpoint"] == "/api/chains")
    check("/api/v1/notices/verified: upstream_notice for /api/notices", (nv.get("upstream_notice") or {}).get("endpoint") == "/api/notices")
    ad = json.loads(get("/api/v1/agents/poa1" + "K" * 40 + "/addresses")[1])
    check("/api/v1/agents/<a>/addresses: upstream_notice", (ad.get("upstream_notice") or {}).get("endpoint") == "/api/chains")
    check("meta.upstream_notice stays null and no site strip for a halt", a1["meta"]["upstream_notice"] is None and 'id="ntbar"' not in h1)
    codes = [get(u)[0] for u in ("/", "/chain/txs", "/chain", "/epoch/1", "/network?tab=health", "/about", "/api/v1/summary", "/llms.txt")]
    check(f"no 5xx anywhere {codes}", all(c < 500 for c in codes))
    db.write("UPDATE fetch_log SET next_at = 0"); ST._halts.clear()
    # the server keeps its own memory; its halt records lapse only with their until. A real read clears them; here the fake keeps halting,
    # so check the no-halt shape in process instead.
finally:
    p.terminate(); p.wait(10)
import importlib
db.write("DELETE FROM fetch_log WHERE err LIKE '% halted'")
from poascan import server as SV
check("no halt: /api/chains has no upstream_notice key, tx notice null", "upstream_notice" not in SV.api("/api/chains", {})[0] and I.halt_notice(I.TX_TPL) is None)

# ---- dropped at close and missing since ----
P = lambda since=None: dict({"kind": "short", "panel": [], "grades": []}, **({"since": since} if since is not None else {}))
def close(n, pending, settled=()): return {"epoch": n, "ts": 2_000_000 + n * 21600, "pool": 1e9, "rewards": {}, "challenges": {},
                                           "basis": {"pending": pending, "settled": [{"answer": t, "passed": True, "jury": []} for t in settled]}}
ids = {k: k * 64 for k in "abcdef"}
eps = [close(1, {ids["a"]: P(1), ids["b"]: P(1)}), close(2, {ids["a"]: P(1), ids["c"]: P(2)}),
       close(3, {ids["d"]: P(), ids["e"]: P()}, settled=[ids["a"]])]
db.put_blob("epochs", eps); A._cache.clear(); A._sf["ts"] = None
db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,epoch,ts,atts,final,first_seen,last_seen,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
         (ids["d"], "challenge", "poa1" + "D" * 40, 3, 2_000_000 + 2 * 21600 + 5, 5, 1, 0, 0, "test"))
rows = {r["epoch"]: r for r in A.epoch_rows()}
check("dropped: null at the first close, 1 at E2 (b), 1 at E3 (c); the settled answer is not dropped", [rows[n]["dropped"] for n in (1, 2, 3)] == [None, 1, 1])
check("settled counts only the settled list (dropped never settled)", rows[3]["settled"] == 1 and rows[2]["settled"] == 0)
check("missing since: the archived answer epoch, else the first close; never E0", rows[3]["pending_by_origin"] == {3: 2} and A.since_of(ids["d"], P()) == 3 and A.since_of(ids["e"], P()) == 3)
bl = A.backlog()["closes"]
check("backlog: dropped 1 at E3, by origin E2", bl[-1]["dropped"] == 1 and bl[-1]["dropped_by_epoch"] == {2: 1})
from poascan import cohorts as CO, views as V
CO._cache = None if hasattr(CO, "_cache") else None
co = {c["birth"]: c for c in CO.cohorts()["cohorts"]}
check("cohorts: the since-less E3 answers form the E3 cohort", 3 in co and co[3]["answers"] == 2)
html = V.epoch(3) if hasattr(V, "epoch") else ""
check("epoch view: Dropped at close row with the count, linked to /about#dropped", '<a href="/about#dropped">Dropped at close</a>' in html and ">1<" in html.split("Dropped at close", 1)[1][:200])
check("epoch view: no Dropped row when nothing dropped", "Dropped at close" not in V.epoch(1))
ab = V.about() if hasattr(V, "about") else ""
check("/about: #dropped and #halts methods", 'id="dropped"' in ab and 'id="halts"' in ab)
check("no em or en dash in the new text", not any(ch in (ab + html + ST.HALT_NOTE + ST.HALT_NONE) for ch in "\u2014\u2013"))
fk.shutdown()
print("ALL OK" if not fails else f"{len(fails)} FAILED"); sys.exit(1 if fails else 0)
