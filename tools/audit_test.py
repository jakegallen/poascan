"""Fixes for the 1.26.2 audit (1.26.3). No request leaves the box: a fake minepoa.com runs in this process.
* SC-002 every numeric query parameter and MCP input is clamped; non-integers are a JSON 400 (MCP: isError), never a 500.
* SC-003 on-demand reads: format check, negative cache, per-client and global budget (429), own backoff key, so a visitor
  miss never pauses swap fill ingest; API and MCP mirror reads are never limited; budget spent: stored balance.
* SC-004 swap API responses are cached per data version (TTL), the swap read runs on its own phase with jitter.
* SC-005 fills and cancels apply only when final; the earliest final one wins (ts, then txid); pending, dropped.
* SC-006 offers past expires_ts are expired in storage and at read time (status, counts, /ops/network).
* SC-009 gzip and If-None-Match on upstream reads; 304 keeps what is stored.
* SC-010, SC-012 to SC-018, SC-021, SC-027 and the /privacy copy (SC-007).
Usage: python3 tools/audit_test.py"""
import gzip, json, os, socket, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# ---------------- fake minepoa.com ----------------
SEEN = []   # (path, headers)
TXS = {}    # id -> detail served by /api/explorer/tx/<id>
MODE = {"tx": "normal"}
class Up(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, etag=None):
        b = json.dumps(obj).encode(); gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gz: b = gzip.compress(b)
        self.send_response(code); self.send_header("Content-Type", "application/json")
        if gz: self.send_header("Content-Encoding", "gzip")
        if etag: self.send_header("ETag", etag)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        SEEN.append((self.path, dict(self.headers)))
        if self.path == "/api/params":
            et = 'W/"12c9-abc"'
            if self.headers.get("If-None-Match") == et: self.send_response(304); self.send_header("ETag", et); self.end_headers(); return
            return self._send(200, {"K": 5, "swap_fee_bp": 100}, et)
        if self.path.startswith("/api/explorer/tx/"):
            tid = self.path.rsplit("/", 1)[1]
            if MODE["tx"] == "busy": return self._send(503, {"error": "origin busy", "retry_after_seconds": 60})
            if tid in TXS: return self._send(200, TXS[tid])
            if tid.startswith("0f"): return self._send(404, {"error": "not found"})
            # live minepoa: an unknown id is a 307 to its HTML app (which can itself fail)
            self.send_response(307); self.send_header("Location", "/pub/poa/poa-read-node" + self.path); self.send_header("Content-Length", "0"); self.end_headers(); return
        if self.path.startswith("/pub/"):
            b = b"<!DOCTYPE html><html></html>"; self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        if self.path.startswith("/api/explorer/address/"):
            a = self.path.rsplit("/", 1)[1]; return self._send(200, {"address": a, "balance": "0.000000", "txs": []})
        self._send(404, {"error": "nope"})
up = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
UP = f"http://127.0.0.1:{up.server_address[1]}"
def seen(prefix): return [p for p, _ in SEEN if p.startswith(prefix)]

tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "a.db")
os.environ["POASCAN_DB"] = dbp; os.environ["POA_BASE"] = UP
import fixture; fixture.seed()
from poascan import db, indexer as I, agentapi as AG, server as SV
from poascan.swap import indexer as SI, store as SS, market as SM
SA = sys.modules["poascan.swap.api"]
A1, A2, A3 = fixture.A1, fixture.A2, fixture.A3

# ---------------- SC-009 gzip and conditional requests ----------------
d = I.fetch("/api/params", cond=True)
h = SEEN[-1][1]
check("SC-009 asks for gzip and inflates it", d == {"K": 5, "swap_fee_bp": 100} and "gzip" in h.get("Accept-Encoding", ""))
check("SC-009 first read is a plain GET", "If-None-Match" not in h)
d2 = I.fetch("/api/params", cond=True)
check("SC-009 second read sends If-None-Match and a 304 returns NOT_MODIFIED", d2 is I.NOT_MODIFIED and SEEN[-1][1].get("If-None-Match") == 'W/"12c9-abc"')
r = db.q1("SELECT fails, last_ok FROM fetch_log WHERE endpoint='/api/params'")
check("SC-009 a 304 counts as a healthy read", r and r["fails"] == 0 and r["last_ok"])
I.fetch("/api/params")
check("SC-009 without cond no If-None-Match is sent", "If-None-Match" not in SEEN[-1][1])
try: I._decode(gzip.compress(b"x" * (I.MAX_BODY + 10)), "gzip"); big = False
except I.Busy: big = True
check("SC-009 inflated size is capped", big)
db.put_blob("params", {"K": 5, "old": True}); I.job_hourly_meta.__globals__["time"].sleep = time.sleep
n0 = len(seen("/api/params")); I._etags["/api/params"] = 'W/"12c9-abc"'
for kind, path in (("params", "/api/params"),):
    x = I.fetch(path, cond=True)
    if x is not I.NOT_MODIFIED: db.put_blob(kind, x)
check("SC-009 a 304 keeps the stored blob", db.get_blob("params")[0] == {"K": 5, "old": True})

# ---------------- SC-003 on-demand budget and negative cache ----------------
I.GLOBAL_BUDGET = I.Bucket(0.001, 50); I.CLIENT_BUDGET = I.Bucket(0.001, 4)
def tx_req(tid, ip="203.0.113.9"):
    I.CLIENT.ip = ip
    try: return I.get_tx_detail(tid)
    finally: I.CLIENT.ip = None
n = len(seen("/api/explorer/tx/"))
for bad in ("zz" * 32, "AB" * 32, "ab" * 31):
    try: tx_req(bad); out = "ok"
    except I.Missing: out = "missing"
    check(f"SC-003 malformed id {bad[:6]}... is refused before any request", out == "missing")
check("SC-003 no request for malformed ids", len(seen("/api/explorer/tx/")) == n)
U = "00" * 32
try: tx_req(U); out = "ok"
except I.Missing: out = "missing"
check("SC-003 an unknown id is Missing (minepoa's 307 to its app)", out == "missing" and len(seen("/api/explorer/tx/")) == n + 1)
check("SC-003 the redirect is not followed", not seen("/pub/"))
try: tx_req(U); out = "ok"
except I.Missing: out = "missing"
check("SC-003 negative cache: the same unknown id again makes no request", out == "missing" and len(seen("/api/explorer/tx/")) == n + 1)
U4 = "0f" * 32
try: tx_req(U4); out = "ok"
except I.Missing: out = "missing"
check("SC-003 a 404 id is Missing too", out == "missing" and len(seen("/api/explorer/tx/")) == n + 2)
n += 1
fl = db.q1("SELECT fails FROM fetch_log WHERE endpoint=?", (I.TX_EP,))
check("SC-003 a 307 or 404 is not an endpoint failure (no backoff)", not fl or not fl["fails"])
codes = []
for i in range(1, 7):
    try: tx_req("%064x" % (0x1000 + i)); codes.append("ok")
    except I.Limited as e: codes.append("limited")
    except I.Missing: codes.append("missing")
check(f"SC-003 per-client budget: new ids past the burst are Limited ({codes})", codes[:2] == ["missing"] * 2 and codes[-1] == "limited")
try: tx_req("%064x" % 0x2001, ip="198.51.100.4"); other = "ok"
except I.Limited: other = "limited"
except I.Missing: other = "missing"
check("SC-003 another client still has its own budget", other == "missing")
I.CLIENT_BUDGET = I.Bucket(0.001, 100); I.GLOBAL_BUDGET = I.Bucket(0.001, 2)
g = []
for i in range(4):
    try: tx_req("%064x" % (0x3000 + i), ip=f"192.0.2.{i}"); g.append("ok")
    except I.Limited: g.append("limited")
    except I.Missing: g.append("missing")
check(f"SC-003 global budget across clients ({g})", g[-1] == "limited" and g.count("missing") == 2)
I.GLOBAL_BUDGET = I.Bucket(100, 100); I.CLIENT_BUDGET = I.Bucket(100, 100)
MODE["tx"] = "busy"
for i in range(3):
    try: tx_req("%064x" % (0x4000 + i))
    except I.Busy: pass
MODE["tx"] = "normal"
check("SC-003 visitor failures back off the on-demand key only", not I.can_fetch(I.TX_EP) and I.can_fetch(I.SWAP_TX_EP) and I.can_fetch(I.BG_TX_EP))
FT = "fe" * 32; TXS[FT] = {"id": FT, "type": "swap-fill", "final": True, "ts": int(time.time()), "from_addr": A2, "body": {"offer": "ab" * 32}}
d = I.get_tx_detail(FT, bg=I.SWAP_TX_EP)
check("SC-003 swap fill ingest still reads while the visitor key backs off", d and d["id"] == FT)
check("SC-003 negative cache is bounded", I.NEG_MAX <= 5000)
db.write("DELETE FROM fetch_log WHERE endpoint=?", (I.TX_EP,))

# ---------------- SC-005, SC-006, SC-021 swap state ----------------
now = int(time.time())
def offer(oid, exp=None, status="open"):
    db.write("INSERT OR REPLACE INTO swaps(offer_id,maker,poa,chain,asset,want,expires_ts,created_ts,status,last_open_seen,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
             (oid, A1, 1000.0, "solana", "SOL", 0.01, exp if exp is not None else now + 86400, now - 600, status, now, now))
def tx(tid, kind, oid, ts, final, frm=A2):
    return {"id": tid, "type": kind, "ts": ts, "final": final, "from_addr": frm, "body": {"offer": oid, "proof": {"ref": "sig" + tid[:4]}}}
def st(oid): return SS.offer(oid)["status"]
O1, O2, O3, O4, O5, O6 = ("%064x" % (0xa0 + i) for i in range(6))
for o in (O1, O2, O3, O4, O5, O6): offer(o)
# cancel then fill, both final: the cancel is earlier and wins
SI.ingest_swap_tx(tx("c1" * 32, "swap-cancel", O1, now - 100, True), now=now); SI.ingest_swap_tx(tx("f1" * 32, "swap-fill", O1, now - 50, True), now=now); SI.resolve(O1, now)
check("SC-005 fill after a final cancel does not overwrite it", st(O1) == "cancelled" and SS.offer(O1)["fill_txid"] is None)
SI.ingest_swap_tx(tx("f2" * 32, "swap-fill", O2, now - 100, True), now=now); SI.ingest_swap_tx(tx("c2" * 32, "swap-cancel", O2, now - 50, True), now=now); SI.resolve(O2, now)
check("SC-005 cancel after a final fill does not overwrite it", st(O2) == "filled" and SS.offer(O2)["fill_txid"] == "f2" * 32 and SS.offer(O2)["cancel_txid"] is None)
SI.ingest_swap_tx(tx("f3" * 32, "swap-fill", O3, now - 7200, False), now=now); SI.resolve(O3, now)
check("SC-005 a non-final fill two hours old stays pending (offer open)", st(O3) == "open")
check("SC-005 the pending fill is stored with final=0 and not in the timeline", db.q1("SELECT final FROM swap_events WHERE txid=?", ("f3" * 32,))["final"] == 0
      and O3 not in SS.events_all())
SI.ingest_swap_tx(tx("f3" * 32, "swap-fill", O3, now - 7200, True), now=now); SI.resolve(O3, now)
check("SC-005 once final it applies", st(O3) == "filled")
SI.ingest_swap_tx(tx("1f" * 32, "swap-fill", O4, now - 100, True), now=now); SI.ingest_swap_tx(tx("0c" * 32, "swap-cancel", O4, now - 100, True), now=now); SI.resolve(O4, now)
check("SC-005 same ledger ts: the lower txid wins", st(O4) == "cancelled" and SS.offer(O4)["cancel_txid"] == "0c" * 32)
# dropped: pending fill whose detail is gone upstream
SI.ingest_swap_tx(tx("d5" * 32, "swap-fill", O5, now - 100, False), now=now)
db.write("UPDATE swap_events SET checked=? WHERE txid=?", (now - 10000, "d5" * 32))
db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,ts,atts,final) VALUES(?,?,?,?,?,?)", ("d5" * 32, "swap-fill", A2, now - 100, 1, 0))
db.write("DELETE FROM tx_detail WHERE id=?", ("d5" * 32,))
SI.ingest_events(now)
check("SC-005 a young pending tx the node does not know yet is kept pending", db.q1("SELECT dropped FROM swap_events WHERE txid=?", ("d5" * 32,))["dropped"] in (0, None) and st(O5) == "open")
db.write("UPDATE swap_events SET checked=?, first_seen=? WHERE txid=?", (now - 10000, now - SI.DROP_AFTER_S - 10, "d5" * 32))
SI.ingest_events(now)
check("SC-005 a pending tx the node no longer knows is dropped and never applies", db.q1("SELECT dropped FROM swap_events WHERE txid=?", ("d5" * 32,))["dropped"] == 1 and st(O5) == "open")
# finality from the explorer feed, with no upstream read
SI.ingest_swap_tx(tx("e6" * 32, "swap-fill", O6, now - 100, False), now=now)
db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,ts,atts,final) VALUES(?,?,?,?,?,?)", ("e6" * 32, "swap-fill", A2, now - 100, 5, 1))
k = len(SEEN); SI.ingest_events(now)
check("SC-005 the feed marking a pending fill final applies it without an upstream read", st(O6) == "filled" and not [p for p, _ in SEEN[k:] if "e6e6" in p])
mk = SM.swap_stats()
check("SC-005 fills count only final ones", mk["fills"] == len([o for o in (O2, O3, O6) if st(o) == "filled"]) + sum(1 for r in SS.swaps_all() if r["status"] == "filled" and r["offer_id"] not in (O2, O3, O6)))
# SC-006 expiry
X1, X2 = "%064x" % 0xb1, "%064x" % 0xb2
book = [{"offer_id": X1, "maker": A1, "poa_locked": "55272", "want": {"chain": "solana", "asset": "SOL", "amount": "0.1"}, "expires_ts": now - 60},
        {"offer_id": X2, "maker": A1, "poa_locked": "100", "want": {"chain": "solana", "asset": "SOL", "amount": "0.1"}, "expires_ts": now + 3600}]
SI.apply_book(book, now)
check("SC-006 an offer still listed past its expiry is stored as expired", st(X1) == "expired" and st(X2) == "open")
db.write("UPDATE swaps SET status='open' WHERE offer_id=?", (X1,))   # as 1.26.2 left it
check("SC-006 read time: a stored 'open' past expiry reads as expired", st(X1) == "expired" and all(r["status"] != "open" for r in SS.swaps_all() if r["offer_id"] == X1))
oc = SS.open_count(); ss = SM.swap_stats()
check(f"SC-006 open count and stats leave it out ({oc}, {ss['open']})", oc == ss["open"] and X1 not in [r["offer_id"] for r in SS.swaps_all() if r["status"] == "open"])
check("SC-006 swaps/status open_offers matches", SA._build("/api/swaps/status")[0]["open_offers"] == oc)
from poascan import network as NW
rep = json.loads(NW.report(time.strftime("%Y-%m-%d", time.gmtime(now)), time.strftime("%Y-%m-%d", time.gmtime(now))))
oso = [x for x in json.dumps(rep).split('"open_swap_offers": ')[1:2]]
check(f"SC-006 /ops/network open_swap_offers matches ({oso[0][:4] if oso else None})", bool(oso) and oso[0].split(",")[0].split("}")[0].strip() == str(oc))
# SC-021: one empty book does not flip open offers
SI.apply_book([], now)
check("SC-021 one empty book: still open", st(X2) == "open")
SI.apply_book([], now)
check("SC-021 two reads in a row without it: delisted", st(X2) == "delisted")
SI.apply_book(book, now)
check("SC-021 back in the book: open again", st(X2) == "open")

# ---------------- SC-004 cache and phase ----------------
calls = [0]; real = SA._build
def counted(p): calls[0] += 1; return real(p)
SA._build = counted; SA._rc.clear()
SA.api("/api/swaps", {}); SA.api("/api/swaps", {}); SA.etag("/api/swaps")
check(f"SC-004 /api/swaps is built once for repeated reads ({calls[0]})", calls[0] == 1)
db.write("UPDATE swaps SET updated=updated+1 WHERE offer_id=?", (X2,)); SA.api("/api/swaps", {})
check("SC-004 a data change rebuilds it", calls[0] == 2)
SA._rc["/api/swaps"] = (time.time() - SA.CACHE_TTL - 1,) + SA._rc["/api/swaps"][1:]; SA.api("/api/swaps", {})
check("SC-004 a copy older than the TTL is rebuilt", calls[0] == 3 and SA.CACHE_TTL <= 60)
SA._build = real
t0 = 1000.0
check("SC-004 swap read is phased away from the live read", I._phase("swaps", 60, t0) == t0 - 60 + I.SWAP_PHASE_S and I._phase("live", 60, t0) == 0 and 0 < I.SWAP_JITTER_S <= 10)
check("SC-025 live and swaps run in their own thread", set(I.FAST) == {"live", "swaps"})

# ---------------- small units ----------------
check("SC-015 CSV: formula cells get an apostrophe, numbers stay", SV.cell("=1+1") == "'=1+1" and SV.cell("@x") == "'@x" and SV.cell("-1.5") == "-1.5"
      and SV.cell("+cmd") == "'+cmd" and SV.cell(-3) == -3 and SV.cell("plain") == "plain" and "'=HYPERLINK" in SV.to_csv([{"memo": "=HYPERLINK(\"x\")"}]))
check("SC-013 batch size counts messages", AG.batch_size(b'[{"a":1},{"a":2},{"a":3}]') == 3 and AG.batch_size(b'{"a":1}') == 1 and AG.batch_size(b"[" + b",".join([b"{}"] * 50) + b"]") == 20)
L = AG.Limiter(0.001, 5)
check("SC-013 limiter spends a batch all or nothing", L.allow("x", 5)[0] and not L.allow("x", 1)[0])
for v in ("abc", None, 1e400, True, [1]):
    try: AG._int({"limit": v}, "limit", 5, 1, 10) if v is not None else None; r = "ok"
    except AG.ToolError: r = "err"
    check(f"SC-002 MCP integer input {v!r} -> {r}", r == "err" or v is None)
check("SC-002 MCP integer clamps", AG._int({"limit": -5}, "limit", 5, 1, 10) == 1 and AG._int({"limit": 10**30}, "limit", 5, 1, 10) == 10)

# ---------------- server ----------------
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
port = free_port(); base = f"http://127.0.0.1:{port}"; tok = "t" * 40; logp = os.path.join(tmp, "server.log")
db.write("INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
         (991, "c", "t", "Zebrafish", 'pid"><x3>', "2026-10-22 00:00:00", 1, 0, 0, 0, 0))
db.write("INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
         (992, "c", "t", "Zebrafinch", A2, "2026-10-22 00:00:00", 1, 0, 0, 0, 0))
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POASCAN_MAINTENANCE="1", POA_BASE=UP,
           POASCAN_STATS_TOKEN=tok, POASCAN_UPSTREAM_CLIENT_BURST="4", POASCAN_UPSTREAM_CLIENT_RATE="0.001", POASCAN_UPSTREAM_BURST="8",
           POASCAN_UPSTREAM_RATE="0.001", POASCAN_MCP_BURST="10", POASCAN_MCP_RATE="0.01")
lf = open(logp, "w"); p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=lf, stderr=lf)
def get(path, hd=None, data=None, method=None):
    r = urllib.request.Request(base + path, headers=hd or {}, data=data, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as x: return x.status, dict(x.headers), x.read()
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read()
import re
def norm(b): return re.sub(rb'"mp\d+"', b"", b)   # per-render toggle ids
class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
try:
    for _ in range(150):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    # SC-002 fuzz
    BAD = ["abc", "1e3", "5.5", "0x10", "99999999999999999999999", "-99999999999999999999", "%00", "1%20OR%201", "%2B"]
    OK = ["-1", "0", "1", "", "+5", "999999999"]
    API = [("/api/v1/txs?limit=", True), ("/api/v1/txs?offset=", True), ("/api/v1/txs.csv?limit=", True), ("/api/v1/txs?format=csv&offset=", True),
           (f"/api/v1/receipts?address={A1}&limit=", True), (f"/api/v1/address/{A1}/txs?limit=", True), (f"/api/v1/address/{A1}/assignments?limit=", True),
           ("/api/v1/agents/view?limit=", True), ("/api/v1/epoch-records?from=0&limit=", True)]
    bad500 = []; not400 = []
    for path, strict in API:
        for v in BAD + OK:
            c, h, b = get(path + v)
            if c >= 500: bad500.append((path + v, c))
            if v in BAD and strict and v != "%2B" and not (c == 400 and b.startswith(b"{") and b"error" in b): not400.append((path + v, c))
    check(f"SC-002 no 500 on any numeric API parameter ({bad500[:3]})", not bad500)
    check(f"SC-002 non-integers are a JSON 400 ({not400[:3]})", not not400)
    c, _, b = get("/api/v1/txs?limit=-1"); rows = json.loads(b)
    check(f"SC-002 limit=-1 is clamped to 1, not the whole archive ({len(rows)})", c == 200 and len(rows) <= 1)
    c, _, b = get("/api/v1/txs?limit=100000"); check("SC-002 limit is capped at 1000", c == 200 and len(json.loads(b)) <= 1000)
    c, _, b = get("/api/v1/txs?offset=-5"); check("SC-002 negative offset reads from 0", c == 200 and len(json.loads(b)) >= 1)
    PATHS = ["/api/v1/epoch/", "/api/v1/epoch/%s/record", "/epoch/", "/txs?page=", "/fragment/lb?tab=richlist&offset=", "/epochs?tab=", "/agents/top?tab=",
             "/api/v1/epoch-records?from=", "/fragment/addr?a=" + A1 + "&cursor=", "/api/v1/leaderboard/richlist?limit=", "/network?range="]
    bad = []
    for path in PATHS:
        for v in BAD + OK + ["99999999999999999999"]:
            c, _, _ = get((path % v) if "%s" in path else path + v)
            if c >= 500: bad.append((path, v, c))
    check(f"SC-002 no 500 on numeric path and page parameters ({bad[:3]})", not bad)
    c, _, _ = get("/epoch/99999999999999999999"); check(f"SC-018 an epoch that does not exist is a 404 ({c})", c == 404)
    c, _, b = get("/api/v1/address/poa1___"); check(f"SC-018 a malformed address is a 400 ({c})", c == 400 and b"error" in b)
    mcp = lambda body, ip="198.51.100.200": get("/mcp", {"Content-Type": "application/json", "Fly-Client-IP": ip}, body if isinstance(body, bytes) else json.dumps(body).encode(), "POST")
    bad = []
    for tool, arg in (("list_transactions", "limit"), ("get_richlist", "limit"), ("list_swap_offers", "limit"), ("get_epoch", "epoch"), ("get_address", "tx_limit")):
        for v in ('"abc"', "-1", "1e400", "99999999999999999999999999", "null", "true", "[1]"):
            raw = ('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"%s","arguments":{"%s":%s%s}}}' % (tool, arg, v, ',"address":"' + A1 + '"' if tool == "get_address" else "")).encode()
            c, _, b = mcp(raw, ip=f"10.9.{len(bad)}.{abs(hash(v)) % 250}")
            if c >= 500 or b"internal error" in b: bad.append((tool, v, c))
    check(f"SC-002 MCP numeric inputs never error internally ({bad[:3]})", not bad)
    # SC-003 over HTTP
    k = len(seen("/api/explorer/tx/"))
    U2 = "0d" * 32
    c, _, b = get("/api/v1/tx/" + U2, {"Fly-Client-IP": "203.0.113.50"})
    check(f"SC-003 API unknown tx: 404 JSON ({c})", c == 404 and b"not found" in b)
    c, _, _ = get("/api/v1/tx/" + U2, {"Fly-Client-IP": "203.0.113.50"}); c2, _, _ = get("/tx/" + U2, {"Fly-Client-IP": "203.0.113.50"})
    check("SC-003 the same unknown id again (API and page) makes no upstream request", len(seen("/api/explorer/tx/")) == k + 1 and c == 404)
    codes = [get("/api/v1/tx/%064x" % (0x5000 + i), {"Fly-Client-IP": "203.0.113.51"}) for i in range(6)]
    check(f"SC-003 one client walking new ids gets 429 with Retry-After ({[x[0] for x in codes]})", codes[-1][0] == 429 and int(codes[-1][1].get("Retry-After", "0")) >= 1)
    c, _, b = mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_receipt", "arguments": {"hash": "%064x" % 0x5999}}}, ip="203.0.113.51")
    check(f"SC-003 MCP get_receipt from that client makes no upstream read ({c})", c == 200 and not seen("/api/explorer/tx/%064x" % 0x5999))
    c, _, b = get(f"/api/v1/address/{A1}", {"Fly-Client-IP": "203.0.113.51"}); d = json.loads(b)
    check(f"SC-003 /api/v1/address when the budget is spent: 200 with the stored balance ({c}, {d.get('balance')})", c == 200 and d.get("balance") is not None)
    mirror = [get(pth, {"Fly-Client-IP": "203.0.113.51"})[0] for _ in range(15) for pth in ("/api/v1/swaps", "/api/v1/swaps/status", "/api/v1/price",
              f"/api/v1/agents/{A1}/addresses", "/api/v1/epochs", "/api/v1/txs?limit=5", "/api/v1/chains", f"/api/v1/swaps/{X2}")]
    check(f"SC-003 mirror reads from the same client are never limited ({set(mirror)})", set(mirror) <= {200, 404} and mirror.count(200) >= 100)
    hz = [h.get("Accept-Encoding", "") for pth, h in SEEN if pth.startswith("/api/explorer/")]
    check("SC-009 on-demand reads ask for gzip too", hz and all("gzip" in x for x in hz))
    # SC-010 ETag on /api/v1/swaps
    c, h, _ = get("/api/v1/swaps"); et = h.get("ETag")
    c2, _, b2 = get("/api/v1/swaps", {"If-None-Match": et or "x"})
    check(f"SC-010 /api/v1/swaps has an ETag and answers 304 ({c2})", bool(et) and c2 == 304 and b2 == b"")
    c, _, b = get("/api/v1/swaps/" + X1); check("SC-006 an expired offer reads expired by id", c == 200 and json.loads(b)["offer"]["status"] == "expired")
    # SC-012 ops gate
    wrong = [get("/ops/visits", {"Authorization": "Bearer " + "x" * 40, "Fly-Client-IP": "203.0.113.60"}) for _ in range(12)]
    good = get("/ops/visits", {"Authorization": "Bearer " + tok, "Fly-Client-IP": "203.0.113.60"})
    check(f"SC-012 over the limit even the right token gets the same 404 ({good[0]})", all(w[0] == 404 for w in wrong) and good[0] == 404 and norm(good[2]) == norm(wrong[0][2]))
    good2 = get("/ops/visits", {"Authorization": "Bearer " + tok, "Fly-Client-IP": "203.0.113.61"})
    check(f"SC-012 the right token from another client works ({good2[0]})", good2[0] == 200)
    # SC-013 batch charges per message
    batch = json.dumps([{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(12)]).encode()
    c, _, _ = mcp(batch, ip="203.0.113.70")
    check(f"SC-013 a 12-message batch over a 10-token burst is 429 ({c})", c == 429)
    c, _, _ = mcp(json.dumps([{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(3)]).encode(), ip="203.0.113.71")
    check(f"SC-013 a small batch is fine ({c})", c == 200)
    # SC-014 suggest
    c, _, b = get("/fragment/suggest?q=zebra"); ids = [x["id"] for x in json.loads(b)]
    check(f"SC-014 suggest returns poa1 addresses only ({ids})", A2 in ids and not any("<" in i or '"' in i for i in ids))
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    check("SC-014 app.js escapes the id", "esc(x.id)" in js and "'+x.id+'" not in js)
    # SC-017 headers and www
    o = urllib.request.build_opener(NoRedir)
    try: o.open(urllib.request.Request(base + "/x?y=1", headers={"Host": "www.evil.example"}), timeout=10); loc = None
    except urllib.error.HTTPError as e: loc = e.headers.get("Location")
    check(f"SC-017 www redirect is never built from Host ({loc})", loc == "https://poascan.io/x?y=1")
    c, h, b = get("/txs"); html = b.decode()
    check("SC-017 COOP header", h.get("Cross-Origin-Opener-Policy") == "same-origin")
    check("SC-027 /txs has an h1", "<h1" in html and ">Transactions</h1>" in html)
    check("SC-027 active nav item has aria-current", 'aria-current="page"' in html)
    c, h, b = get("/txs?page=abc"); check(f"SC-002 /txs?page=abc renders page 1 ({c})", c == 200)
    # SC-007 privacy and SC-019 about
    c, _, b = get("/privacy"); pv = b.decode()
    check("SC-007 /privacy: CC BY 4.0, Fly-Client-IP, retention, client and app_version, logs without IP", c == 200 and "CC BY 4.0" in pv and "creativecommons.org/licenses/by/4.0/" in pv
          and "Fly-Client-IP" in pv and "Retention." in pv and "400 days" in pv and "app_version" in pv and "IP addresses and query strings are not logged" in pv
          and "a hash of the code" in pv)
    check("SC-007 /privacy: no em dash, no 'not sold or shared' claim", chr(0x2014) not in pv and "sold" not in pv.lower())
    c, _, b = get("/about"); ab = b.decode()
    check("SC-019 /about: swaps every 60 s, links, probes, CoinGecko; no stale 'no market' line", "<code>/api/swaps</code>: every 60 s" in ab and "chains-update" in ab
          and "CoinGecko SOL and ETH every 15 min" in ab and "no market exists" not in ab and chr(0x2014) not in ab)
    c, _, b = get("/llms.txt"); check("SC-019 llms.txt date", "2026-10-20" not in b.decode())
finally:
    p.terminate(); p.wait(10); lf.close()
log = open(logp).read()
check("SC-007 the request log holds no client IP", not any(x in log for x in ("203.0.113.", "198.51.100.", "127.0.0.1 -")))
check("no Traceback in the server log", "Traceback" not in log)
up.shutdown()
print("\n%d failure(s)" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
