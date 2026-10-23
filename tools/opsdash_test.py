"""Private aggregate feed for POASwap's dashboard (poascan/opsdash.py) and GET /ops/dashboard.
* Shape: traffic, onchain, offchain, service, wallets (null), definitions (one sentence per metric), not_measurable.
* Numbers from a fixture: views, check-in funnel, matched joins next to every chain join, failures, time from the join tx
  to the joined check-in (median, p90), day 1, 7 and 30 retention from the archive, route check p50/p95, 5xx and 404.
* Privacy: no address, IP, user agent, tx id, key or query string in the response; addresses only as counts.
* Cached 60 s per range; no upstream request (urllib trapped in the unit run, POA_BASE a counter that must see zero).
* Auth as /ops/internal: the normal 404 without the token, a wrong one or another scheme; ?token= is the key guard's 400;
  any other parameter (blank too) is a 400; at most 31 days; no-store, noindex, no CORS. Not in public docs or MCP.
* No em or en dash in the module or the response.
* Stop and restarts: fly.toml stops with SIGTERM (kill_timeout 10); SIGINT and SIGTERM both flush the visit counts and exit 0
  with no KeyboardInterrupt traceback. Each start compares FLY_IMAGE_REF with the last: restarts_deploy and restarts_other.
Test tokens are generated at runtime. Usage: python3 tools/opsdash_test.py"""
import json, os, re, secrets, socket, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

NOW = int(time.time()); H = 3600; D = 86400
def iso(t): return time.strftime("%Y-%m-%d", time.gmtime(t))
A = ["poa1" + c * 44 for c in "QRSTUVW"]
TX = "ab" * 32
TOP = {"from", "to", "generated_ts", "version", "cache_ttl_s", "traffic", "onchain", "offchain", "service", "wallets", "definitions", "not_measurable"}
DASHES = (chr(0x2013), chr(0x2014))

def fixture(db, CK, now):
    # A0: joined 40 d ago, tx on day 1 and day 30 (not day 7). A1: joined 10 d ago, tx on day 7. A2: joined 2 h ago.
    # A3: untagged join (baseline only). A4: tagged, no join tx (unmatched). A5: resumed (joined 5 d before its check-in).
    txs = [("j0", "join", A[0], now - 40 * D), ("t0a", "challenge", A[0], now - 39 * D + H), ("t0b", "transfer", A[0], now - 10 * D + H),
           ("j1", "join", A[1], now - 10 * D), ("t1", "challenge", A[1], now - 3 * D + H),
           ("j2", "join", A[2], now - 2 * H), ("c2", "challenge", A[2], now - 1 * H),
           ("j3", "join", A[3], now - 3 * H), ("j5", "join", A[5], now - 6 * D), (TX, "transfer", A[3], now - 2 * H)]
    db.write("INSERT INTO txs(id,type,from_addr,ts) VALUES(?,?,?,?)", txs, many=True)
    db.put_blob("epochs", [])
    CK.record("v2.3.2", "claude", "start", None, now=now - 40 * D - 600); CK.record("v2.3.2", "claude", "joined", A[0], now=now - 40 * D + 120)
    for _ in range(3): CK.record("v2.4", "chatgpt", "start", None, now=now - 10 * D - 600)
    CK.record("v2.4", "chatgpt", "probe", None, now=now - 10 * D - 300); CK.record("v2.4", "chatgpt", "probe", None, now=now - 10 * D - 300)
    CK.record("v2.4", "chatgpt", "joined", A[1], now=now - 10 * D + 600)
    CK.record("v2.4", "none", "start", None, now=now - 3 * H); CK.record("v2.4", "none", "probe", None, now=now - 3 * H)
    CK.record("v2.4", "none", "joined", A[2], now=now - 2 * H - 30)          # 30 s before our copy of the join time: clamped to 0
    CK.record("v2.4", "none", "joined", A[4], now=now - 1 * H)               # unmatched
    CK.record("v2.4", "none", "joined", A[5], now=now - 1 * D)               # resumed
    CK.record("v2.4", "chatgpt", "rate", "register", now=now - 10 * D)
    d = iso(now)
    db.write("INSERT INTO visit_uniques VALUES(?,?,?)", (d, 77, 3))
    db.put_blob("restart_kinds", {"image": "x", "days": {d: {"deploy": 1, "other": 0}}})
    db.write("INSERT INTO visit_views VALUES(?,?,?,?)", [(d, "home", "human", 50), (d, "start", "human", 20), (d, "agents", "bot", 9), (d, "api", "agent", 31)], many=True)
    db.write("INSERT INTO visit_referrers VALUES(?,?,?)", [(d, "x.com", 12)], many=True)
    db.write("INSERT INTO visit_counts VALUES(?,?,?,?)", [(d, "device", "mobile", 40), (d, "country", "US", 30), (d, "api", "/api/v1/summary", 31), (d, "mcp", "get_summary", 4),
        (d, "prompt", "start.copy", 6), (d, "prompt", "join.open", 3), (d, "prompt", "join.copy", 2), (d, "pjoin", "claude", 5), (d, "pjoin", "none", 1),
        (d, "mcp", "get_onboarding_steps", 2), (d, "5xx", "address", 2), (d, "404", "other", 5), (d, "ms", "home.lt100ms", 90), (d, "ms", "address.ge1s", 10)], many=True)
    db.write("INSERT INTO route_checks VALUES(?,?,?,?,?)", [(now - 300, "/api/hosted/mine", "200", 100, 1), (now - 200, "/api/hosted/mine", "200", 300, 1),
                                                           (now - 100, "/api/hosted/mine", "timeout", 10000, 0)], many=True)
    db.write("INSERT INTO uptime_daily VALUES(?,?,?,?,?)", [((now // D) * D, "probe /", 10, 9, 200)], many=True)

def keys(o):
    if isinstance(o, dict): return set(o) | set().union(*[keys(v) for v in o.values()]) if o else set()
    if isinstance(o, list): return set().union(*[keys(v) for v in o]) if o else set()
    return set()

def leaves(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items(): yield from leaves(v, path + "." + k)
    elif isinstance(o, list):
        for v in o: yield from leaves(v, path + "[]")
    else: yield path, o

def unit():
    tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "u.db")
    from poascan import db, checkin as CK, opsdash as OD, opsinternal as OI
    db.DB_PATH = os.environ["POASCAN_DB"]; db.init(); CK.start(NOW - 50 * D); OI.start(NOW - 50 * D)
    calls = []
    def trap(*a, **k): calls.append(1); raise AssertionError("upstream call during /ops/dashboard")
    orig = urllib.request.urlopen; urllib.request.urlopen = trap
    fixture(db, CK, NOW)
    fr, to = iso(NOW - 6 * D), iso(NOW)
    t0 = time.time(); s = OD.report(fr, to, "9.9.9", now=NOW); ms = (time.time() - t0) * 1000; o = json.loads(s)
    check(f"top-level shape ({ms:.0f} ms)", set(o) == TOP and o["wallets"] is None and o["version"] == "9.9.9" and o["cache_ttl_s"] == 60 and o["from"] == fr and o["to"] == to)
    tr = o["traffic"]
    check(f"traffic: uniques, views by kind, top pages, api, mcp, prompt clicks ({tr['totals']})", tr["totals"]["views"] == {"human": 70, "bot": 9, "agent": 31}
          and tr["days"][0]["uniques"] == 77 and tr["top_pages"]["home"]["human"] == 50 and tr["referrers"] == {"x.com": 12} and tr["devices"] == {"mobile": 40}
          and tr["countries"] == {"US": 30} and tr["totals"]["api_calls"] == 31 and tr["totals"]["mcp_calls"] == 6 and tr["totals"]["prompt_clicks"] == 11)
    oc = o["onchain"]; vp = oc["via_poascan"]
    check(f"onchain: matched joins in range next to every chain join ({vp}, {oc['network']['chain_joins']})", vp["joined"] == 1 and vp["joined_by_version"] == {"v2.4": 1}
          and vp["joined_by_client"] == {"none": 1} and vp["tagged_joins"] == 1 and oc["network"]["chain_joins"] == 3 and vp["share_of_chain_joins"] == round(1 / 3, 4))
    check(f"onchain: active Agents distinct over the range ({oc['network']['active_agents']})", oc["network"]["active_agents"] == 4 and oc["network"]["txs_total"] >= 5)
    of = o["offchain"]; f = of["failures"]
    check(f"offchain funnel and failures ({of['funnel']['totals']}, {f})", of["funnel"]["totals"]["started"] == 1 and of["funnel"]["totals"]["probed"] == 1
          and f["unmatched"] == 1 and f["resumed"] == 1 and f["start_no_probe"] == 0)
    ss = of.get("setup_signals") or {}; st = ss.get("totals") or {}; sd = [x for x in ss.get("days", []) if x["day"] == iso(NOW)]
    check(f"1.26.44 offchain.setup_signals: daily copies, Join opens, prompt fetches by client, MCP onboarding calls ({st})",
          st.get("prompt_copies") == {"start": 6, "join": 2} and st.get("join_opens") == 3 and st.get("prompt_fetches_by_client") == {"claude": 5, "none": 1}
          and st.get("prompt_fetches") == 6 and st.get("mcp_onboarding_calls") == 2 and len(ss["days"]) == len(tr["days"]) and len(sd) == 1
          and sd[0] == {"day": iso(NOW), "prompt_copies": {"start": 6, "join": 2}, "join_opens": 3, "prompt_fetches_by_client": {"claude": 5, "none": 1}, "mcp_onboarding_calls": 2}
          and set(ss) == {"totals", "days"} and all(set(x) == {"day", "prompt_copies", "join_opens", "prompt_fetches_by_client", "mcp_onboarding_calls"} for x in ss["days"]))
    dd = OD.DEFINITIONS
    check("setup_signals definitions say plainly these are intent signals, not joins, and daily counts only",
          "Intent signals, not joins" in dd["offchain.setup_signals"] and "Daily counts only" in dd["offchain.setup_signals"]
          and all(("not a join" in dd[k] or "not people or joins" in dd[k] or "not a signup" in dd[k] or "Intent only" in dd[k]) for k in dd if k.startswith("offchain.setup_signals."))
          and "setup_signals" in o["not_measurable"]["untagged_signups"]
          and "poaswap is POASwap's own server fetch (about every 10 minutes), not a visitor" in dd["offchain.setup_signals.prompt_fetches_by_client"])
    tc = of["time_to_checkin"]
    check(f"time to check-in: the clock skew clamped to 0 ({tc})", tc["all"] == {"n": 1, "median_s": 0, "p90_s": 0} and tc["clock_skew_clamped"] == 1)
    rt = of["retention"]
    check(f"retention: a new cohort is not yet eligible ({rt})", rt["cohort"] == 1 and rt["day_1"]["eligible"] == 0 and rt["day_1"]["rate"] is None)
    w = json.loads(OD.report(iso(NOW - 41 * D), iso(NOW - 11 * D), "9.9.9", now=NOW))
    wr, wt = w["offchain"]["retention"], w["offchain"]["time_to_checkin"]
    check(f"retention day 1, 7, 30 from the archive over a 31-day range ({wr})", wr["cohort"] == 1 and wr["day_1"] == {"eligible": 1, "retained": 1, "rate": 1.0}
          and wr["day_7"] == {"eligible": 1, "retained": 0, "rate": 0.0} and wr["day_30"] == {"eligible": 1, "retained": 1, "rate": 1.0}
          and wt["all"]["median_s"] == 120)
    w2 = json.loads(OD.report(iso(NOW - 12 * D), iso(NOW - 9 * D), "9.9.9", now=NOW))["offchain"]
    check(f"failures by step for v2.4: started minus probed, probed minus joined; 429 by route ({w2['failures']})", w2["failures"]["start_no_probe"] == 1
          and w2["failures"]["no_join_after_start"] == 1 and w2["failures"]["rate_429_by_route"] == {"register": 1} and w2["retention"]["day_7"]["retained"] == 1)
    sv = o["service"]; pc = sv["poascan"]; mine = sv["upstream"]["route_checks"].get("/api/hosted/mine") or {}
    check(f"service: success rates, availability, latency buckets, 5xx and 404 ({pc['availability']}, {pc['latency']})", any(r["version"] == "v2.4" for r in sv["success_rates"])
          and pc["responses"] == 100 and pc["errors_5xx"] == 2 and pc["not_found_404"] == 5 and pc["availability"] == 0.98 and pc["restarts"] == 2
          and pc["restarts_deploy"] == 1 and pc["restarts_other"] == 1 and pc["days"][-1]["restarts_deploy"] == 1 and pc["days"][-1]["restarts_other"] == 1
          and all(x["restarts_deploy"] is None and x["restarts_other"] is None for x in pc["days"] if x["day"] != iso(NOW))
          and pc["latency"]["p50"] == "lt100ms" and pc["latency"]["p95"] == "ge1s")
    check(f"service: upstream route check p50/p95 and error rate ({mine})", mine.get("count") == 3 and mine.get("ok") == 2 and mine.get("error_rate") == 0.3333
          and mine.get("p50_ms") in (100, 300) and mine.get("p95_ms") == 300 and sv["upstream"]["probes"]["probe /"]["uptime"] == 0.9)
    def named(d):   # the section (first part) holds a field named by the last part (day_N: day_1, day_7, day_30)
        sec, last = d.split(".")[0], d.split(".")[-1]
        return any(k == last or (last == "day_N" and k.startswith("day_")) for k in keys(o[sec]))
    miss = [d for d in OD.DEFINITIONS if d != "wallets" and not named(d)]
    check(f"every definition names a field in the response ({miss})", not miss and all(isinstance(v, str) and v.endswith(".") for v in OD.DEFINITIONS.values()))
    check("definitions cover wallets and not_measurable covers start-to-join timing", "wallets" in OD.DEFINITIONS and "POASwap" in OD.DEFINITIONS["wallets"]
          and "time_from_start_to_join" in o["not_measurable"])
    raw = s + json.dumps(w)
    check("no address, tx id, IP or user agent in the response (addresses only as counts)", "poa1" not in raw and TX not in raw and not any(a in raw for a in A))
    check("no IP, UA, key, addr or query field names", not ({k.lower() for k in keys(o)} & {"ip", "ips", "user_agent", "ua", "key", "keys", "addr", "addresses", "query", "txid"}))   # "address" is a page group name
    src = open(os.path.join(ROOT, "poascan", "opsdash.py"), encoding="utf-8").read()
    check("no em or en dash in the module or the response", not any(c in raw or c in src for c in DASHES))
    db.write("INSERT INTO txs(id,type,from_addr,ts) VALUES(?,?,?,?)", ("j9", "join", A[6], NOW - H))
    check("cached: a second read inside 60 s is the same text", OD.report(fr, to, "9.9.9", now=NOW) == s)
    OD._cache[(fr, to)] = (time.time() - 61, s)
    check("after 60 s it is recomputed", json.loads(OD.report(fr, to, "9.9.9", now=NOW))["onchain"]["network"]["chain_joins"] == 4)
    check(f"no upstream call ({len(calls)})", not calls)
    urllib.request.urlopen = orig

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
    from poascan import db, checkin as CK
    db.DB_PATH = dbp; db._local.c = None; db.init(); fixture(db, CK, NOW)
    db._local.c.close(); db._local.c = None
    p, base = serve(dbp, None, upb)
    try:
        ref = req(base, "/ops/dashboard"); c, h, b = req(base, "/ops/dashboard", {"Authorization": "Bearer " + tok})
        check(f"env unset: 404 with or without a token ({ref[0]}, {c})", ref[0] == 404 and c == 404 and same(b, ref[2]) and shape(h) == shape(ref[1]))
    finally: p.terminate(); p.wait(10)
    p, base = serve(dbp, tok, upb)
    try:
        nf = req(base, "/ops/dashboard")
        check(f"no header: the normal 404 ({nf[0]})", nf[0] == 404 and b"<html" in nf[2].lower() and b"traffic" not in nf[2])
        for name, hd in [("wrong token", {"Authorization": "Bearer " + wrong}), ("token without Bearer", {"Authorization": tok}), ("Basic scheme", {"Authorization": "Basic " + tok})]:
            c, h, b = req(base, "/ops/dashboard", dict(hd, **{"Fly-Client-IP": "198.51.100.9"}))
            check(f"{name}: identical normal 404", c == 404 and same(b, nf[2]) and shape(h) == shape(nf[1]))
        for i, q in enumerate(("token", "access_token", "key")):
            c, _, b = req(base, f"/ops/dashboard?{q}=" + tok, {"Fly-Client-IP": f"198.51.100.{20 + i}"})
            check(f"?{q}= in the query string is refused ({c})", c == 400 and b"traffic" not in b)
        H_ = {"Authorization": "Bearer " + tok, "User-Agent": "DashTestAgent/1.0", "Fly-Client-IP": "198.51.100.30"}
        t0 = time.time(); c, h, b = req(base, f"/ops/dashboard?from={iso(NOW - 6 * D)}&to={iso(NOW)}", H_); ms = (time.time() - t0) * 1000
        d = json.loads(b) if c == 200 else {}
        check(f"right token: 200 JSON with every section in {ms:.0f} ms", c == 200 and set(d) == TOP and d["wallets"] is None)
        check("headers: no-store, noindex, no CORS", h.get("Cache-Control") == "no-store" and "noindex" in (h.get("X-Robots-Tag") or "")
              and not any(k.lower().startswith("access-control") for k in h))
        check("filled from the stored data", d["traffic"]["totals"]["views"]["human"] == 70 and d["onchain"]["network"]["chain_joins"] == 3
              and d["service"]["upstream"]["route_checks"]["/api/hosted/mine"]["count"] == 3)
        check("no IP, UA, address or tx id in the response", b"198.51.100" not in b and b"DashTestAgent" not in b and b"poa1" not in b and TX.encode() not in b)
        for i, q in enumerate(("x=1", "from=" + iso(NOW) + "&utm=", "debug", "from=" + iso(NOW - 31 * D) + "&to=" + iso(NOW), "from=x", "from=" + iso(NOW) + "&from=" + iso(NOW),
                               "from=" + iso(NOW) + "&to=" + iso(NOW - D))):
            c, h, b = req(base, "/ops/dashboard?" + q, dict(H_, **{"Fly-Client-IP": f"198.51.101.{i}"}))
            e = json.loads(b) if c == 400 else {}
            check(f"bad query {q!r} -> {c}", c == 400 and isinstance(e.get("error"), str) and h.get("Cache-Control") == "no-store" and b"traffic" not in b)
        c, _, b = req(base, "/ops/dashboard", dict(H_, **{"Fly-Client-IP": "198.51.102.1"})); d = json.loads(b) if c == 200 else {}
        check(f"default range is the last 7 days ({c})", c == 200 and d.get("to") == iso(NOW) and d.get("from") == iso(NOW - 6 * D))
        c, _, _ = req(base, "/ops/dashboard?from=" + iso(NOW - 30 * D) + "&to=" + iso(NOW), dict(H_, **{"Fly-Client-IP": "198.51.102.2"}))
        check(f"31 days is allowed ({c})", c == 200)
        L = dict(H_, **{"Fly-Client-IP": "198.51.103.1"})
        codes = [req(base, "/ops/visits", L)[0] for _ in range(10)] + [req(base, "/ops/dashboard", L)[0] for _ in range(2)]
        check(f"same per-IP limit as the other /ops feeds ({codes})", codes[:10] == [200] * 10 and codes[10:] == [404] * 2)
        pub = b"".join(req(base, x)[2] for x in ("/", "/sitemap.xml", "/openapi.json", "/llms.txt", "/llms-full.txt", "/.well-known/mcp.json", "/robots.txt", "/api"))
        check("/ops/dashboard not in the home page, sitemap, OpenAPI, llms.txt, robots or /api", b"ops/dashboard" not in pub)
    finally: p.terminate(); p.wait(10)
    up.shutdown()
    check(f"no request reached the upstream ({len(UPSTREAM)})", not UPSTREAM)
    check("README does not mention /ops/dashboard", "/ops/dashboard" not in open(os.path.join(ROOT, "README.md")).read())

def stops():
    fl = open(os.path.join(ROOT, "fly.toml")).read()
    top = fl.split("\n[", 1)[0]
    check("fly.toml: kill_signal SIGTERM and kill_timeout 10 at the top level", re.search(r'(?m)^kill_signal = "SIGTERM"', top) is not None and re.search(r"(?m)^kill_timeout = 10\b", top) is not None)
    import signal as SG
    tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "r.db"); today = iso(time.time())
    def run(img, sig):
        port = free_port(); env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", FLY_IMAGE_REF=img)
        env.pop("POASCAN_STATS_TOKEN", None)
        p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try: urllib.request.urlopen(base + "/healthz", timeout=2); break
            except Exception: time.sleep(0.2)
        try: urllib.request.urlopen(urllib.request.Request(base + "/", headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/130"}), timeout=10).read()
        except Exception: pass
        p.send_signal(sig)
        try: rc = p.wait(15)
        except subprocess.TimeoutExpired: p.kill(); rc = None
        return rc, p.stderr.read().decode("utf-8", "replace")
    out = [run("registry.fly.io/poascan:deployment-a", SG.SIGINT), run("registry.fly.io/poascan:deployment-a", SG.SIGTERM), run("registry.fly.io/poascan:deployment-b", SG.SIGINT)]
    check(f"SIGINT and SIGTERM exit 0 with no KeyboardInterrupt traceback ({[o[0] for o in out]})", all(o[0] == 0 and "KeyboardInterrupt" not in o[1] and "Traceback" not in o[1] for o in out))
    from poascan import db
    db.DB_PATH = dbp; db._local.c = None
    v = db.q1("SELECT SUM(views) AS n FROM visit_views WHERE day=?", (today,)); u = db.q1("SELECT segments FROM visit_uniques WHERE day=?", (today,))
    check(f"the stop flushed the visit counts on SIGINT ({v['n'] if v else None} views, {u['segments'] if u else None} segments)", v and (v["n"] or 0) >= 3 and u and u["segments"] == 3)
    b = db.get_blob("restart_kinds")[0] or {}
    check(f"restart split: same image is other, a new image is a deploy, raw ref never stored ({b.get('days', {}).get(today)})", b.get("days", {}).get(today) == {"deploy": 1, "other": 1}
          and "deployment" not in json.dumps(b) and len(b.get("image", "")) == 16)
    db._local.c.close(); db._local.c = None

if __name__ == "__main__":
    unit(); server(); stops()
    print("FAILED: " + ", ".join(fails) if fails else "all ops dashboard checks passed")
    sys.exit(1 if fails else 0)
