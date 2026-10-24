"""Private daily network aggregates (poascan/network.py) and GET /ops/network.
* Every series comes from the archive: fixture txs, snapshots, swaps, epochs, chains and uptime rows give the expected daily numbers.
* The rollup is incremental: a late tx on an old day and a new snapshot are picked up; nothing else is recomputed.
* Aggregates only: no address appears anywhere in the response.
* No upstream request: the indexer's fetch and urllib are trapped in the unit run, and the server run points POA_BASE at a
  local counter that must see zero requests.
* /ops/network is the normal 404 with the token env unset, with no header, a wrong token or a non-Bearer scheme; ?token= gets
  the key guard's 400; 200 with the right Bearer token; over 400 days is a 400. Not in the sitemap, OpenAPI, llms.txt or MCP.
Test tokens are generated at runtime. Usage: python3 tools/network_test.py"""
import json, os, re, secrets, socket, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

TODAY = int(time.time()) // 86400
D = [(TODAY - 3 + i) * 86400 for i in range(4)]          # four UTC day starts, the last is today
A1, A2, A3, A4 = ("poa1" + c * 40 for c in "BCDE")
SOL1, ETH1 = "So1" + "a" * 40, "0x" + "ab" * 20
def iso(d): return time.strftime("%Y-%m-%d", time.gmtime(d))

def fixture(db):
    tx = lambda i, typ, fr, ts, to=None, amt=None: (f"{i:064x}", typ, fr, to, amt, None, None, None, ts, 3, 5, 1, ts, ts, "test")
    rows = [tx(1, "join", A1, D[0] + 100), tx(2, "join", A2, D[0] + 200), tx(3, "challenge", A1, D[0] + 300), tx(4, "challenge", A2, D[0] + 400),
            tx(5, "grade-sealed", A3, D[1] + 10), tx(6, "grade-sealed", A3, D[1] + 20), tx(7, "transfer", A1, D[1] + 30, A2, "12.5"),
            tx(8, "transfer", A2, D[1] + 40, A1, "0.5"), tx(9, "attest-batch", A4, D[2] + 50), tx(10, "chains-update", A1, D[1] + 60),
            tx(11, "challenge", A1, 0)]                    # ts 0 stays out of every series
    db.write("INSERT INTO txs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)", rows, many=True)
    db.write("INSERT INTO tx_detail VALUES(?,?,?,?)", (f"{10:064x}", json.dumps({"id": f"{10:064x}", "final": 1, "body": {"chains": {"solana": SOL1, "ethereum": ETH1}}}), D[1], 1))
    db.put_blob("chains", {A1: {"solana": {"addr": SOL1, "verified": True}, "ethereum": {"addr": ETH1.upper().replace("0X", "0x"), "verified": True}},
                           A2: {"solana": {"addr": "So2" + "b" * 40, "verified": True}}, A3: {"ethereum": {"addr": "0x" + "cd" * 20, "verified": False}}})
    for t, a, h, ck in ((D[0] + 50, 10, 1, 100), (D[0] + 80000, 14, 2, 120), (D[1] + 80000, 20, 3, 150), (D[2] + 1000, 21, 3, 150)):
        db.add_snap("status", {"agents_joined": a, "holders": h, "supply": "1000.5", "checkpoint_height": ck}, t)
    db.add_snap("accounts", {"total": 20, "with_balance": 3}, D[1] + 70000)
    db.add_snap("height", {"height": 999, "checkpoint_height": 150}, D[1] + 70000)
    db.put_blob("status", {"agents_joined": 21, "holders": 3, "supply": "1000.5", "epochs_closed": 2, "checkpoint_height": 150})
    db.write("INSERT INTO accounts VALUES(?,?,?,?,?,?,?,?)", [(A1, None, 15000.0, "15000", D[0], 0, D[0], D[2]), (A2, None, 5.0, "5", D[0], 0, D[0], D[2]),
                                                               (A3, None, 0.0, "0", D[0], 0, D[0], D[2]), (A4, None, 0.5, "0.5", D[0], 0, D[0], D[2])], many=True)
    db.put_blob("epochs", [{"epoch": 0, "ts": D[0] + 500, "pool": "100", "rewards": {A1: "60", A2: "20"}, "basis": {"settled": [{"passed": True}, {"passed": False}]}, "challenges": {A1: 1}},
                           {"epoch": 1, "ts": D[1] + 500, "pool": "100", "rewards": {A1: "50"}, "basis": {"settled": [{"passed": True}], "slashed": [A2]}, "challenges": {}}])
    sw = "INSERT INTO swaps(offer_id,maker,poa,chain,asset,want,created_ts,status,taker,fill_ts,cancel_ts,expires_ts,fill_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
    db.write(sw, [("o1", A1, 1000.0, "solana", "SOL", 2.0, D[1] + 100, "filled", A2, D[1] + 700, None, D[3], 150.0),
                  ("o2", A1, 1000.0, "solana", "SOL", 4.0, D[1] + 200, "filled", A3, D[1] + 300, None, D[3], 150.0),
                  ("o3", A2, 500.0, "ethereum", "ETH", 1.0, D[1] + 300, "cancelled", None, None, D[1] + 900, D[3], None),
                  ("o4", A2, 500.0, "ethereum", "ETH", 1.0, D[0] + 300, "expired", None, None, None, D[1] + 5, None),
                  ("o5", A4, 10.0, "solana", "SOL", 1.0, D[2] + 300, "open", None, None, None, D[3] + 86400 * 5, None)], many=True)
    db.write("INSERT INTO uptime_daily VALUES(?,?,?,?,?)", [(D[1], "probe /api/status", 900, 899, 40), (D[1], "/api/agents", 96, 96, 300), (D[1], "probe /", 144, 144, 80),
                                                             (D[2], "/api/explorer/txs", 1440, 1440, 50)], many=True)

def unit():
    tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "n.db")
    from poascan import db, indexer as I, network as NW, analytics as A
    db.DB_PATH = os.environ["POASCAN_DB"]; db.init()
    calls = []
    def trap(*a, **k): calls.append(a[:1]); raise AssertionError("upstream call during /ops/network")
    orig = (I.fetch, urllib.request.urlopen); I.fetch = trap; urllib.request.urlopen = trap
    fixture(db)
    t0 = time.time(); out = json.loads(NW.report(iso(D[0] - 86400 * 5), iso(D[3]))); ms = (time.time() - t0) * 1000
    check(f"top-level shape ({ms:.0f} ms)", set(out) == {"from", "to", "as_of", "metrics", "days", "snapshot"} and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d\d:\d\d:\d\dZ", out["as_of"]))
    days = {d["day"]: d for d in out["days"]}
    check("days newest first, from the first archived day to today", [d["day"] for d in out["days"]] == [iso(x) for x in reversed(D)])
    keys = {"day", "agents", "supply", "txs", "transfers", "epochs", "mining", "swaps", "wallets", "upstream"}
    check("every day has the same keys", all(set(d) == keys for d in out["days"]))
    a, b, c = days[iso(D[0])], days[iso(D[1])], days[iso(D[2])]
    check("agents day 1: new within the first day, total, first seen, joins, active", a["agents"]["new"] == 4 and a["agents"]["total"] == 14
          and a["agents"]["first_seen"] == 2 and a["agents"]["join_txs"] == 2 and a["agents"]["active"] == 2 and a["agents"]["holders_reported"] == 2)
    check("agents day 2: new vs previous day end, listed and with_balance from /api/agents snaps", b["agents"]["new"] == 6 and b["agents"]["total"] == 20
          and b["agents"]["first_seen"] == 1 and b["agents"]["listed"] == 20 and b["agents"]["with_balance"] == 3)
    check("tx by type with distinct senders", a["txs"]["total"] == 4 and a["txs"]["by_type"]["challenge"] == {"n": 2, "agents": 2}
          and b["txs"]["by_type"]["grade-sealed"] == {"n": 2, "agents": 1})
    check("transfers count and POA volume", b["transfers"] == {"count": 2, "poa": 13.0, "senders": 2, "recipients": 2})
    check("epochs closed and rewards", a["epochs"]["closed"] == 1 and a["epochs"]["numbers"] == [0] and a["epochs"]["minted"] == 80.0 and a["epochs"]["burned"] == 20.0
          and a["epochs"]["accepted"] == 1 and a["epochs"]["settled"] == 2 and b["epochs"]["slashed"] == 1 and c["epochs"]["closed"] == 0)
    check("mining from txs and snapshots", a["mining"]["submissions"] == 2 and b["mining"]["grade_seals"] == 2 and b["mining"]["graders"] == 1
          and c["mining"]["attesters"] == 1 and b["mining"]["checkpoint_height"] == 150 and b["mining"]["checkpoint_advance"] == 30 and b["mining"]["height"] == 999)
    s = b["swaps"]
    check(f"swaps: created, filled, cancelled, expired, fill rate, median, volume, USD", s["created"] == 3 and s["filled"] == 2 and s["cancelled"] == 1
          and s["expired"] == 1 and s["fill_rate"] == 0.5 and s["median_fill_s"] == 350 and s["volume_poa"] == 2000.0 and s["volume_usd"] == 900.0
          and s["makers"] == 2 and s["takers"] == 2)
    sol = s["by_asset"].get("SOL") or {}
    check(f"swap OHLC and vwap in quote per POA ({sol})", sol.get("open") == 0.004 and sol.get("close") == 0.002 and sol.get("high") == 0.004
          and sol.get("low") == 0.002 and sol.get("vwap") == 0.003 and sol.get("fills") == 2 and sol.get("quote") == 6.0)
    check("wallet cohorts: dated by the chains-update tx, EVM case-insensitive, unverified ignored", b["wallets"] == {"solana_new": 1, "ethereum_new": 1,
          "solana_total": 1, "ethereum_total": 1, "any_total": 1} and c["wallets"]["any_total"] == 1 and a["wallets"]["solana_total"] == 0)
    check("upstream calls per endpoint, probe prefix folded", b["upstream"]["total"] == 1140 and b["upstream"]["by_endpoint"] == {"/api/status": 900, "/": 144, "/api/agents": 96}
          and a["upstream"] is None and c["upstream"]["total"] == 1440)
    sn = out["snapshot"]; h = sn["holders"]
    check(f"snapshot holders: current only, buckets, top shares ({h['buckets']})", h["current_only"] is True and h["buckets"] == {"0": 1, "lt1": 1, "lt10": 1, "lt100": 0, "lt1k": 0, "lt10k": 0, "ge10k": 1}
          and h["holders"] == 3 and h["top1_share"] == round(15000 / 15005.5, 6) and h["top10_share"] == 1.0)
    check("snapshot wallets and history bounds", sn["wallets"]["verified"] == {"solana": 2, "ethereum": 1, "any": 2, "both": 1} and sn["wallets"]["dated"] == {"solana": 1, "ethereum": 1}
          and sn["history_from"] == iso(D[0]) and sn["upstream_from"] == iso(D[1]) and "holders_history" in sn["skipped"])
    flat = {k.split(".")[0] for k in out["metrics"]}
    check("metrics describe every per-day section", keys - {"day"} <= flat and all(isinstance(v, str) and v for v in out["metrics"].values()))
    raw = json.dumps(out)
    check("aggregate only: no address in the response", "poa1" not in raw and SOL1 not in raw and ETH1 not in raw)
    check("no em dash in the response or the module", chr(0x2014) not in raw and chr(0x2014) not in open(os.path.join(ROOT, "poascan", "network.py")).read())
    # incremental rollup: a late tx on day 1 and a new snapshot today are picked up on the next refresh
    db.write("INSERT INTO txs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)", (f"{99:064x}", "transfer", A4, A1, "7", None, None, None, D[0] + 900, 1, 5, 1, 0, 0, "test"))
    db.add_snap("status", {"agents_joined": 25, "holders": 4, "supply": "1001", "checkpoint_height": 160}, D[3] + 10)
    NW._cache.clear(); NW._last_refresh[0] = 0
    out2 = json.loads(NW.report(iso(D[0]), iso(D[3]))); d2 = {d["day"]: d for d in out2["days"]}
    check("late tx updates its own day, its sender is first seen that day", d2[iso(D[0])]["transfers"]["count"] == 1 and d2[iso(D[0])]["agents"]["first_seen"] == 3
          and d2[iso(D[2])]["agents"]["first_seen"] == 0)
    check("new snapshot today: total and checkpoint", d2[iso(D[3])]["agents"]["total"] == 25 and d2[iso(D[3])]["agents"]["new"] == 4 and d2[iso(D[3])]["mining"]["checkpoint_advance"] == 10)
    wm = db.get_blob(NW.WM_KIND)[0]
    check("watermarks saved", wm["txs"] == db.q1("SELECT MAX(rowid) AS m FROM txs")["m"] and wm["snaps"] == db.q1("SELECT MAX(rowid) AS m FROM snaps")["m"])
    t0 = time.time(); NW.report(iso(D[0]), iso(D[3])); check("cached second call is fast", time.time() - t0 < 0.05)
    check(f"no upstream call ({len(calls)})", not calls)
    I.fetch, urllib.request.urlopen = orig

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
    db.DB_PATH = dbp; db._local.c = None; db.init(); fixture(db); db._local.c.close(); db._local.c = None
    p, base = serve(dbp, None, upb)
    try:
        ref = req(base, "/ops/network")
        c, h, b = req(base, "/ops/network", {"Authorization": "Bearer " + tok})
        check(f"env unset: 404 with or without a token ({ref[0]}, {c})", ref[0] == 404 and c == 404 and same(b, ref[2]) and shape(h) == shape(ref[1]))
    finally: p.terminate(); p.wait(10)
    p, base = serve(dbp, tok, upb)
    try:
        nf = req(base, "/ops/network"); nf_h = shape(nf[1]); nv = req(base, "/ops/visits")
        check(f"no header: normal 404, same page as /ops/visits ({nf[0]})", nf[0] == 404 and b"<html" in nf[2].lower() and nv[0] == 404)
        for name, hd in [("wrong token", {"Authorization": "Bearer " + wrong}), ("token without Bearer", {"Authorization": tok}), ("Basic scheme", {"Authorization": "Basic " + tok})]:
            c, h, b = req(base, "/ops/network", hd)
            check(f"{name}: identical normal 404", c == 404 and same(b, nf[2]) and shape(h) == nf_h)
        c, _, b = req(base, "/ops/network?token=" + tok)
        check(f"?token= is refused by the key guard ({c})", c == 400 and b"days" not in b)
        H = {"Authorization": "Bearer " + tok}
        t0 = time.time(); c, h, b = req(base, f"/ops/network?from={iso(D[0])}&to={iso(D[3])}", H); ms = (time.time() - t0) * 1000
        d = json.loads(b) if c == 200 else {}
        check(f"right token: 200 JSON in {ms:.0f} ms", c == 200 and set(d) == {"from", "to", "as_of", "metrics", "days", "snapshot"} and len(d["days"]) == 4)
        check("headers: no-store, noindex, no CORS", h.get("Cache-Control") == "no-store" and "noindex" in (h.get("X-Robots-Tag") or "")
              and not any(k.lower().startswith("access-control") for k in h))
        c, _, b = req(base, "/ops/network", H); d = json.loads(b) if c == 200 else {}
        check(f"default range is the last 30 days ({c})", c == 200 and d.get("to") == iso(TODAY * 86400))
        for q in ("from=2020-01-01&to=" + iso(D[3]), "from=x", "from=2026-10-23&to=2026-10-22"):
            c, _, _ = req(base, "/ops/network?" + q, H); check(f"bad range {q} -> {c}", c == 400)
        pub = b"".join(req(base, x)[2] for x in ("/", "/sitemap.xml", "/openapi.json", "/openapi-gpt.json", "/llms.txt", "/llms-full.txt", "/.well-known/mcp.json", "/robots.txt"))
        tl = urllib.request.urlopen(urllib.request.Request(base + "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
                                    {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}), timeout=20).read()
        check("/ops/network not in the home page, sitemap, OpenAPI, llms.txt, robots or MCP", b"/ops/network" not in pub and b"ops/network" not in tl)
    finally: p.terminate(); p.wait(10)
    up.shutdown()
    check(f"no request reached the upstream ({len(UPSTREAM)}: {UPSTREAM[:3]})", not UPSTREAM)
    check("README does not mention /ops/network", "/ops/network" not in open(os.path.join(ROOT, "README.md")).read())

if __name__ == "__main__":
    unit(); server()
    print("FAILED: " + ", ".join(fails) if fails else "all network checks passed")
    sys.exit(1 if fails else 0)
