"""Private ops stats for POASwap's dashboard (poascan/opsinternal.py) and GET /ops/internal.
* Shape: from, to, generated_ts, version, fetch_log, invalid_txs, probes, upstream_budget, each with its documented keys.
* Counters: the hosted route check logs code, latency and clear reads per route; upstream denials are counted by reason
  (visitor caps, the 429 pause, backoff once per window) and persisted, so a range query works across restarts.
* Privacy: no IP, user agent, hash, address, tx id or body in the response, whatever the stored error text holds.
* No upstream request: urllib and the indexer fetch are trapped in the unit run; the server run points POA_BASE at a
  local counter that must see zero requests.
* Auth as /ops/visits: the normal 404 with the env unset, no header, a wrong token or a non-Bearer scheme; ?token= gets
  the key guard's 400; any other query parameter with the right header is a 400; same per-IP limit as /ops/visits.
* Range: default the last 7 days, at most 31, bad dates and from after to are 400 with a JSON error. Cache-Control no-store,
  no CORS. Not in the sitemap, OpenAPI, llms.txt, robots, MCP or README.
Test tokens are generated at runtime. Usage: python3 tools/opsinternal_test.py"""
import datetime as dt, json, os, re, secrets, socket, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

NOW = int(time.time()); TODAY = NOW // 86400
def iso(d): return time.strftime("%Y-%m-%d", time.gmtime(d))
TX1, TX2, TX3 = "ab" * 32, "cd" * 32, "ef" * 32
ADDR = "poa1" + "Q" * 40
TOP = {"from", "to", "generated_ts", "version", "fetch_log", "invalid_txs", "probes", "upstream_budget"}
BAD_KEYS = {"ip", "ips", "client_ip", "user_agent", "ua", "useragent", "txid", "txids", "tx_id", "hash", "hashes", "body", "addr", "address"}

def fixture(db):
    db.write("INSERT INTO fetch_log(endpoint,last_ok,last_err,err,fails,next_at,bytes) VALUES(?,?,?,?,?,?,?)",
             [("/api/status", NOW - 30, NOW - 600, "HTTP 503", 0, 0, 2048),
              ("/api/explorer/tx/:id (on demand)", NOW - 90, NOW - 60, f"URLError: <urlopen error {TX1} at {ADDR}>", 3, NOW + 120, None),
              ("/api/epochs", None, NOW - 5, "non-JSON response (load page?)", 1, NOW + 30, None)], many=True)
    db.write("INSERT INTO invalid_txs VALUES(?,?,?)", [(TX1, f"insufficient balance: have 5, need 10 for {ADDR}", (TODAY - 1) * 86400 + 100),
                                                       (TX2, f"Bad signature on {TX2}", (TODAY - 1) * 86400 + 200),
                                                       (TX3, "insufficient balance: have 1, need 2", TODAY * 86400 + 5)], many=True)

def unit():
    tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "u.db")
    from poascan import db, indexer as I, hosted as HO, opsinternal as OI
    db.DB_PATH = os.environ["POASCAN_DB"]; db.init(); OI.start(NOW - 3600)
    calls = []
    def trap(*a, **k): calls.append(1); raise AssertionError("upstream call during /ops/internal")
    orig = (I.fetch, urllib.request.urlopen, HO._get); urllib.request.urlopen = trap; HO._get = trap
    fixture(db)
    # hosted route check: one clear read, one unknown 429 that ends the round; then a round with a timeout
    answers = iter([(503, b'{"error":"halted"}'), (429, b"slow down")])
    HO.job(now=NOW - 2000, get=lambda p: next(answers))
    def tmo(p): raise TimeoutError("timed out")
    db.put_blob(HO.BLOB, dict(db.get_blob(HO.BLOB)[0], skip_until=None, ts=NOW - 5000))
    HO.job(now=NOW - 1000, get=tmo)
    rc = db.q("SELECT route, code, ok FROM route_checks ORDER BY ts, rowid")
    check(f"route check logged per read ({len(rc)})", [r["code"] for r in rc[:2]] == ["503", "429"] and rc[0]["ok"] == 1 and rc[1]["ok"] == 0
          and len(rc) == 2 + len(HO.ROUTES) and all(r["code"] == "timeout" and r["ok"] == 0 for r in rc[2:]))
    # a round inside skip_until: one backoff denial per route, nothing fetched
    db.put_blob(HO.BLOB, dict(db.get_blob(HO.BLOB)[0], skip_until=NOW + 600))
    HO.job(now=NOW, get=trap)
    # visitor caps, the 429 pause, backoff (scheduled once per window, visitor every time)
    up_na = lambda t: db.write("UPDATE fetch_log SET next_at=? WHERE endpoint=?", (t, I.TX_EP))
    up_na(0); ob = (I.CLIENT_BUDGET, I._hold[0]); I.CLIENT.ip = "203.0.113.9"; I.CLIENT_BUDGET = I.Bucket(0.001, 0)
    for _ in range(3):
        try: I.fetch_ondemand(f"/api/explorer/tx/{TX1}", I.TX_EP, TX1)
        except I.Limited: pass
    I._hold[0] = time.time() + 300
    try: I.fetch("/api/status")
    except I.Limited: pass
    I._hold[0] = 0; I.CLIENT_BUDGET = ob[0]; up_na(NOW + 120)
    for _ in range(4): I.skip_backoff("/api/epochs")
    try: I.fetch_ondemand(f"/api/explorer/tx/{TX2}", I.TX_EP, TX2)   # the on-demand key is backing off (fetch_log next_at)
    except I.Busy: pass
    check("no upstream call while counting", not calls)
    t0 = time.time(); out = OI.report(iso((TODAY - 6) * 86400), iso(TODAY * 86400), "9.9.9"); ms = (time.time() - t0) * 1000
    check(f"top-level shape ({ms:.0f} ms)", set(out) == TOP and out["version"] == "9.9.9" and isinstance(out["generated_ts"], int)
          and out["from"] == iso((TODAY - 6) * 86400) and out["to"] == iso(TODAY * 86400))
    fl = out["fetch_log"]["endpoints"]; fk = {"last_ok_ts", "last_error_ts", "last_error", "fails", "next_try_ts", "bytes"}
    check(f"fetch_log keys and short error classes ({ {k: v['last_error'] for k, v in fl.items()} })", all(set(v) == fk for v in fl.values())
          and fl["/api/status"]["last_error"] == "http_503" and fl["/api/explorer/tx/:id (on demand)"]["last_error"] == "URLError"
          and fl["/api/epochs"]["last_error"] == "non_json" and fl["/api/status"]["bytes"] == 2048 and fl["/api/explorer/tx/:id (on demand)"]["fails"] == 3)
    iv = out["invalid_txs"]
    check(f"invalid_txs by class, per first-seen day ({iv['by_error']})", iv["total"] == 3 and iv["by_error"] == {"insufficient balance": 2, "bad signature on": 1}
          and [d["day"] for d in iv["days"]] == [iso(TODAY * 86400), iso((TODAY - 1) * 86400)] and iv["since_ts"] == (TODAY - 1) * 86400 + 100)
    pr = out["probes"]; pd = {d["day"]: d["endpoints"] for d in pr["days"]}
    allp = {}
    for eps in pd.values():
        for k, v in eps.items():
            a = allp.setdefault(k, dict(count=0, ok=0, codes={}))
            a["count"] += v["count"]; a["ok"] += v["ok"]
            for c, n in v["status_codes"].items(): a["codes"][c] = a["codes"].get(c, 0) + n
    mine = allp.get("/api/hosted/mine") or {}
    check(f"probes per route: count, ok, status codes ({mine})", mine.get("count") == 2 and mine.get("ok") == 1 and mine.get("codes") == {"503": 1, "timeout": 1}
          and all(set(v) == {"count", "ok", "p50_ms", "p95_ms", "status_codes"} for eps in pd.values() for v in eps.values()) and pr["since_ts"] == NOW - 3600)
    ub = out["upstream_budget"]; ud = {d["day"]: d["endpoints"] for d in ub["days"]}.get(iso(NOW)) or {}
    od = ud.get(I.TX_EP) or {}
    check(f"visitor caps and backoff per endpoint ({od})", od.get("visitor_cap") == 3 and od.get("visitor_cap_by") == {"client": 3} and od.get("backoff") == 1
          and od.get("total") == 4)
    check(f"429 pause counted ({ud.get('/api/status')})", (ud.get("/api/status") or {}).get("pause_429") == 1)
    check(f"scheduled backoff counted once per window ({ud.get('/api/epochs')})", (ud.get("/api/epochs") or {}).get("backoff") == 1)
    check("skipped route-check round: one backoff per route", all((ud.get(p + " (route check)") or {}).get("backoff") == 1 for _, _, p in HO.ROUTES))
    check("upstream_budget since_ts", ub["since_ts"] == NOW - 3600)
    raw = json.dumps(out)
    check("no tx id, address, IP or user agent in the response", TX1 not in raw and TX2 not in raw and TX3 not in raw and ADDR not in raw and "203.0.113" not in raw)
    def keys(o):
        if isinstance(o, dict): return set(o) | set().union(*[keys(v) for v in o.values()]) if o else set()
        if isinstance(o, list): return set().union(*[keys(v) for v in o]) if o else set()
        return set()
    check("no IP, UA, txid, hash or body field names", not ({k.lower() for k in keys(out)} & BAD_KEYS))
    # persisted: a fresh read after the in-memory counter is gone sees the same counts
    I._deny.clear(); again = OI.report(out["from"], out["to"], "9.9.9")
    check("denials persisted (a restart keeps them)", again["upstream_budget"]["days"] == ub["days"])
    # range parsing
    P = lambda **q: OI.parse_range({k: [v] for k, v in q.items()}, NOW)
    check("default range is the last 7 days", P() == (iso((TODAY - 6) * 86400), iso(NOW)))
    check("31 days ok", P(**{"from": iso((TODAY - 30) * 86400), "to": iso(NOW)}) == (iso((TODAY - 30) * 86400), iso(NOW)))
    for q in ({"from": iso((TODAY - 31) * 86400), "to": iso(NOW)}, {"from": "2026-02-30"}, {"to": "2026-1-1"}, {"from": "x"}, {"from": iso(NOW), "to": iso((TODAY - 1) * 86400)}):
        try: P(**q); ok = False
        except ValueError: ok = True
        check(f"bad range {q} is refused", ok)
    check("no em dash in the module or response", chr(0x2014) not in raw and chr(0x2014) not in open(os.path.join(ROOT, "poascan", "opsinternal.py")).read())
    check(f"no upstream call ({len(calls)})", not calls)
    urllib.request.urlopen, HO._get = orig[1], orig[2]

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def req(base, path, headers=None):
    r = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=20) as f: return f.status, dict(f.headers), f.read()
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read()

UPSTREAM = []
class Counter(BaseHTTPRequestHandler):
    def do_GET(self): UPSTREAM.append(self.path); self.send_response(503); self.end_headers()
    do_HEAD = do_POST = do_GET
    def log_message(self, *a): pass

def serve(dbp, token, up):
    port = free_port(); env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POA_BASE=up)
    env.pop("POASCAN_STATS_TOKEN", None)
    if token: env["POASCAN_STATS_TOKEN"] = token
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    return p, base

MPID = re.compile(rb'"mp\d+"')
def same(b1, b2): return MPID.sub(b"", b1) == MPID.sub(b"", b2)
def shape(h): return {k: v for k, v in h.items() if k not in ("Date", "Content-Length")}

def server():
    up = ThreadingHTTPServer(("127.0.0.1", 0), Counter); threading.Thread(target=up.serve_forever, daemon=True).start()
    upb = f"http://127.0.0.1:{up.server_address[1]}"
    tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "s.db"); tok = secrets.token_urlsafe(32); wrong = secrets.token_urlsafe(32)
    from poascan import db
    db.DB_PATH = dbp; db._local.c = None; db.init(); fixture(db)
    db.write("INSERT INTO route_checks VALUES(?,?,?,?,?)", [(NOW - 100, "/api/hosted/mine", "503", 40, 1), (NOW - 90, "/api/hosted/mine", "503", 60, 1),
                                                           (NOW - 80, "/api/hosted/send", "timeout", 10000, 0)], many=True)
    db.write("INSERT INTO upstream_denials VALUES(?,?,?,?)", [(iso(NOW), "/api/explorer/address/:addr", "visitor_cap:global", 5)], many=True)
    db._local.c.close(); db._local.c = None
    p, base = serve(dbp, None, upb)
    try:
        ref = req(base, "/ops/internal")
        c, h, b = req(base, "/ops/internal", {"Authorization": "Bearer " + tok})
        check(f"env unset: 404 with or without a token ({ref[0]}, {c})", ref[0] == 404 and c == 404 and same(b, ref[2]) and shape(h) == shape(ref[1]))
    finally: p.terminate(); p.wait(10)
    p, base = serve(dbp, tok, upb)
    try:
        nf = req(base, "/ops/internal"); nv = req(base, "/ops/visits", {"Fly-Client-IP": "198.51.100.2"})
        check(f"no header: the normal 404, as /ops/visits ({nf[0]}, {nv[0]})", nf[0] == 404 and b"<html" in nf[2].lower() and nv[0] == 404 and b"fetch_log" not in nf[2])
        for name, hd in [("wrong token", {"Authorization": "Bearer " + wrong}), ("token without Bearer", {"Authorization": tok}), ("Basic scheme", {"Authorization": "Basic " + tok})]:
            c, h, b = req(base, "/ops/internal", hd)
            check(f"{name}: identical normal 404", c == 404 and same(b, nf[2]) and shape(h) == shape(nf[1]))
        for q in ("token", "access_token", "key"):
            c, _, b = req(base, f"/ops/internal?{q}=" + tok, {"Fly-Client-IP": "198.51.100.3"})
            check(f"?{q}= in the query string is refused ({c})", c == 400 and b"fetch_log" not in b)
        H = {"Authorization": "Bearer " + tok, "User-Agent": "OpsTestAgent/7.7", "Fly-Client-IP": "198.51.100.4"}
        c, _, b = req(base, "/ops/internal?authorization=" + tok, H)
        check(f"any other parameter with the right header is a 400 ({c})", c == 400 and b"fetch_log" not in b and json.loads(b).get("error"))
        t0 = time.time(); c, h, b = req(base, f"/ops/internal?from={iso((TODAY - 2) * 86400)}&to={iso(NOW)}", H); ms = (time.time() - t0) * 1000
        d = json.loads(b) if c == 200 else {}
        check(f"right token: 200 JSON with the expected keys in {ms:.0f} ms", c == 200 and set(d) == TOP)
        check("headers: no-store, noindex, no CORS", h.get("Cache-Control") == "no-store" and "noindex" in (h.get("X-Robots-Tag") or "")
              and not any(k.lower().startswith("access-control") for k in h))
        pm = (d.get("probes", {}).get("days") or [{}])[0].get("endpoints", {})
        check(f"probes from the stored route checks ({pm.get('/api/hosted/mine')})", pm.get("/api/hosted/mine") == {"count": 2, "ok": 2, "p50_ms": 40, "p95_ms": 60, "status_codes": {"503": 2}}
              and pm.get("/api/hosted/send", {}).get("p50_ms") is None and pm.get("/api/hosted/send", {}).get("status_codes") == {"timeout": 1})
        ue = (d.get("upstream_budget", {}).get("days") or [{}])[0].get("endpoints", {}).get("/api/explorer/address/:addr", {})
        check(f"upstream_budget from the stored denials ({ue})", ue.get("visitor_cap") == 5 and ue.get("visitor_cap_by") == {"global": 5})
        check("since_ts set at startup for the new counters", isinstance(d["probes"]["since_ts"], int) and isinstance(d["upstream_budget"]["since_ts"], int)
              and d["invalid_txs"]["since_ts"] == (TODAY - 1) * 86400 + 100)
        check("no IP, UA or tx id in the response", b"198.51.100" not in b and b"OpsTestAgent" not in b and TX1.encode() not in b and ADDR.encode() not in b)
        c, _, b = req(base, "/ops/internal", dict(H, **{"Fly-Client-IP": "198.51.100.5"})); d = json.loads(b) if c == 200 else {}
        check(f"default range is the last 7 days ({c})", c == 200 and d.get("to") == iso(NOW) and d.get("from") == iso((TODAY - 6) * 86400))
        for i, q in enumerate(("from=" + iso((TODAY - 31) * 86400) + "&to=" + iso(NOW), "from=2026-02-30", "from=x", "to=2026-1-1",
                               "from=" + iso(NOW) + "&to=" + iso((TODAY - 1) * 86400))):
            c, h, b = req(base, "/ops/internal?" + q, dict(H, **{"Fly-Client-IP": f"198.51.101.{i}"}))
            e = json.loads(b) if c == 400 else {}
            check(f"bad range {q} -> {c} {e}", c == 400 and isinstance(e.get("error"), str) and len(e["error"]) < 80 and h.get("Cache-Control") == "no-store")
        c, _, _ = req(base, "/ops/internal?from=" + iso((TODAY - 30) * 86400) + "&to=" + iso(NOW), dict(H, **{"Fly-Client-IP": "198.51.102.1"}))
        check(f"31 days is allowed ({c})", c == 200)
        # the per-IP limit is the /ops/visits one (burst 10), shared: visits first, then internal is refused with the same 404
        L = dict(H, **{"Fly-Client-IP": "198.51.103.1"})
        codes = [req(base, "/ops/visits", L)[0] for _ in range(10)] + [req(base, "/ops/internal", L)[0] for _ in range(3)]
        check(f"same per-IP limit as /ops/visits ({codes})", codes[:10] == [200] * 10 and codes[10:] == [404] * 3)
        pub = b"".join(req(base, x)[2] for x in ("/", "/sitemap.xml", "/openapi.json", "/openapi-gpt.json", "/llms.txt", "/llms-full.txt", "/.well-known/mcp.json", "/robots.txt", "/api"))
        tl = urllib.request.urlopen(urllib.request.Request(base + "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
                                    {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}), timeout=20).read()
        check("/ops/internal not in the home page, sitemap, OpenAPI, llms.txt, robots, /api or MCP", b"ops/internal" not in pub and b"ops/internal" not in tl)
    finally: p.terminate(); p.wait(10)
    up.shutdown()
    check(f"no request reached the upstream ({len(UPSTREAM)})", not UPSTREAM)
    check("README does not mention /ops/internal", "/ops/internal" not in open(os.path.join(ROOT, "README.md")).read())

if __name__ == "__main__":
    unit(); server()
    print("FAILED: " + ", ".join(fails) if fails else "all ops internal checks passed")
    sys.exit(1 if fails else 0)
