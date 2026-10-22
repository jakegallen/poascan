"""Daily event counts (1.23.0, poascan/visits.py visit_counts) and POST /ops/e.
* Every stored key comes from an allowlist or fixed pattern: route templates, tool names, prompt ids, client families,
  device, country, edge, tag, search outcome, path group. No path, query, search text, IP or user agent is stored.
* Memory stays bounded under 200k hits with random tags, user agents, paths and regions.
* POST /ops/e takes allowlisted ids only (204), refuses unknown ids, big bodies, other origins and bursts; sets no cookie.
* Search text never reaches the log, the DB or the counts.
Usage: python3 tools/events_test.py (POASCAN_GEOIP=path/to/country.mmdb also checks country lookups)"""
import json, os, random, re, secrets, socket, sqlite3, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

UA_H = "Mozilla/5.0 (X11; Linux x86_64) TestBrowser/9.9.9 Gecko/20100101"
UA_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
UA_IPAD = "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Safari/604.1"
UA_ATAB = "Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
UA_APHONE = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"
SECRET_Q = "pasteQ" + secrets.token_hex(6)
HEX = "ab" * 32

def allowed(VS):
    from poascan import agentapi as AG
    tpl = set(AG.openapi()["paths"])
    grp = set(VS.GROUPS)
    return {"api": lambda k: k in tpl or k == "other", "mcp": lambda k: k in VS.MCP_TOOLS or k == "other",
            "client": lambda k: k in VS.CLIENT_KEYS, "prompt": lambda k: k in VS.PROMPT_IDS,
            "tag": lambda k: bool(VS.TAG_RX.match(k)), "device": lambda k: k in VS.DEVICES,
            "country": lambda k: bool(re.fullmatch(r"[A-Z]{2}|unknown", k)), "edge": lambda k: k in VS.EDGES or k == "other",
            "search": lambda k: k in VS.SEARCH or k == "other", "404": lambda k: k in grp, "5xx": lambda k: k in grp,
            "ms": lambda k: k.partition(".")[0] in grp and k.partition(".")[2] in {b for _, b in VS.MS_BUCKETS} | {VS.MS_TOP}}

def scan(path, VS):
    con = sqlite3.connect(path); ok = allowed(VS); bad = []
    cols = [r[1] for r in con.execute("PRAGMA table_info(visit_counts)")]
    check("visit_counts columns are day/metric/key/n only", cols == ["day", "metric", "key", "n"])
    rows = con.execute("SELECT day, metric, key, n FROM visit_counts").fetchall(); con.close()
    for d, m, k, n in rows:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or m not in ok or not ok[m](k) or not isinstance(n, int): bad.append((m, k))
        if SECRET_Q.lower() in k.lower() or "203.0.113" in k or "testbrowser" in k.lower() or "?" in k: bad.append((m, k))
    return len(rows), bad

def unit():
    tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "u.db")
    from poascan import db, visits as VS, agentapi as AG, prompts as PR, geo
    from poascan import server  # sets the allowlists, like production
    db.DB_PATH = os.environ["POASCAN_DB"]; db.init()
    check("client families", VS.client("Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)") == "claudebot"
          and VS.client("Mozilla/5.0 AppleWebKit (compatible; GPTBot/1.2)") == "gptbot" and VS.client("curl/8.5.0") == "curl"
          and VS.client("python-requests/2.32") == "python-requests" and VS.client("Mozilla/5.0 (compatible; Googlebot/2.1)") == "googlebot"
          and VS.client("Mozilla/5.0 (compatible; PerplexityBot/1.0)") == "perplexitybot" and VS.client("Cursor/1.2") == "cursor"
          and VS.client(UA_H) == "browser" and VS.client("") == "none" and VS.client("my-own-tool/" + SECRET_Q) == "other")
    check("device class", VS.device(UA_IPHONE) == "mobile" and VS.device(UA_IPAD) == "tablet" and VS.device(UA_ATAB) == "tablet"
          and VS.device(UA_APHONE) == "mobile" and VS.device(UA_H) == "desktop" and VS.device("") == "desktop")
    check("campaign tag: ref only, lowercased, else other", VS.tag("ref=Launch_1") == "launch_1" and VS.tag("q=x&ref=x-y") == "x-y"
          and VS.tag("ref=bad!") == "other" and VS.tag("ref=" + "a" * 25) == "other" and VS.tag("q=launch") is None and VS.tag("") is None
          and VS.tag("ref=") is None)
    check("edge region allowlist", VS.edge("sjc") == "sjc" and VS.edge("SJC") == "sjc" and VS.edge("xyz") == "other" and VS.edge(None) == "other")
    check("response time buckets", [VS.ms_bucket(x) for x in (5, 150, 999, 1000, 9e9)] == ["lt100ms", "lt300ms", "lt1s", "ge1s", "ge1s"])
    rt = VS.api_route
    check("API route templates, never raw paths", rt("/api/v1/tx/" + HEX) == "/api/v1/tx/{hash}" and rt("/api/address/poa1abc/txs") == "/api/v1/address/{address}/txs"
          and rt("/api/v1/epochs.csv") == "/api/v1/epochs" and rt("/api/v1/swaps/status") == "/api/v1/swaps/status"
          and rt("/api/v1/swaps/12") == "/api/v1/swaps/{offer_id}" and rt("/api/v1/epoch/7/record") == "/api/v1/epoch/{n}/record"
          and rt("/api/v1/" + SECRET_Q) == "other" and rt("/api/summary") == "/api/v1/summary")
    check("prompt ids: fixed cards and every Ask agent prompt", {"start.copy", "join.copyreg", "wallet.regshow", "mcp-poa.add", "ask-explain-epoch-n.open"} <= VS.PROMPT_IDS
          and all(re.fullmatch(r"[a-z0-9.-]{3,64}", i) for i in VS.PROMPT_IDS) and len(VS.PROMPT_IDS) < 400)
    btn = PR.ask([PR.BURN, PR.explain_epoch(12)])
    items = json.loads(re.search(r'data-ask="([^"]+)"', btn).group(1).replace("&quot;", '"').replace("&#x27;", "'").replace("&amp;", "&"))
    check("Ask agent items carry their fixed id", [x[2] for x in items] == ["ask-explain-the-burn", "ask-explain-epoch-n"]
          and all(x[2] + ".copy" in VS.PROMPT_IDS for x in items))
    clock = [1792540800.0 + 3600]
    c = VS.Counter(now=lambda: clock[0])
    hit = lambda path, ua, code=200, m="GET", ms=50, region="sjc", ip="203.0.113.9": c.hit(m, code, path, ua, None, lambda: ip, ms, region)
    hit("/?ref=Launch", UA_IPHONE); hit("/start?ref=launch", UA_IPAD, region="ams"); hit("/start?ref=" + SECRET_Q + "!", UA_H, region="zzz")
    hit("/api/v1/tx/" + HEX, "python-requests/2.32", ms=150); hit("/api/v1/epochs.csv", "curl/8", ms=2500); hit("/", "Mozilla/5.0 (compatible; GPTBot/1.2)")
    hit("/nope/" + SECRET_Q, UA_H, code=404, ms=5); hit("/epoch/1", UA_H, code=500, ms=400); hit("/search?q=" + SECRET_Q, UA_H, code=404)
    hit("/mcp", "Claude-User/1.0", m="POST")
    check("event(): unknown prompt id refused, unknown tool is 'other', search outcome only", c.event("prompt", "start.copy") and not c.event("prompt", SECRET_Q)
          and not c.event("prompt", None) and c.event("mcp", "get_epoch") and c.event("mcp", SECRET_Q) and c.event("search", "none") and c.event("search", SECRET_Q)
          and not c.event("tag", "x"))
    check("flush ok", c.flush())
    day = VS.today(clock[0]); r = VS.report(day, day)["days"][0]
    check(f"api by template, any status: {r['api']}", r["api"] == {"/api/v1/epochs": 1, "/api/v1/tx/{hash}": 1})
    check(f"mcp by tool: {r['mcp']}", r["mcp"] == {"get_epoch": 1, "other": 1})
    check(f"clients: {r['clients']}", r["clients"] == {"curl": 1, "gptbot": 1, "python-requests": 1, "claude-user": 1})
    check(f"devices: {r['devices']}", r["devices"] == {"mobile": 1, "tablet": 1, "desktop": 1})
    check(f"edges: {r['edges']}", r["edges"] == {"ams": 1, "sjc": 1, "other": 1})
    check(f"campaigns (today folded on read): {r['campaigns']}", r["campaigns"] == {"other": 3})
    check(f"search: {r['search']}", r["search"] == {"none": 1, "other": 1})
    h = r["health"]
    check(f"health: 404 by group (search excluded), 5xx, response time: {h}", h["not_found"] == {"other": 1} and h["errors"] == {"epochs": 1}
          and h["response_ms"]["api"] == {"lt100ms": 0, "lt300ms": 1, "lt1s": 0, "ge1s": 1} and h["response_ms"]["epochs"]["lt1s"] == 1)
    check(f"funnel: {r['funnel']}", r["funnel"]["start_views_human"] == 2 and r["funnel"]["start_copies"] == 1 and r["funnel"]["registry_copies"] == 0)
    check("prompts", r["prompts"] == {"start.copy": 1})
    # tag folding on a finished day; 3+ a day is kept
    for _ in range(3): hit("/?ref=keepme", UA_H)
    c.flush(); clock[0] += 86400; hit("/", UA_H)
    raw = {(x["metric"], x["key"]): x["n"] for x in db.q("SELECT metric, key, n FROM visit_counts WHERE day=?", (day,))}
    check(f"finished day: tags under 3 folded, 3+ kept: { {k: v for k, v in raw.items() if k[0] == 'tag'} }", raw.get(("tag", "keepme")) == 3 and raw.get(("tag", "other")) == 3
          and ("tag", "launch") not in raw)
    c.flush()
    n, bad = scan(os.environ["POASCAN_DB"], VS)
    check(f"every stored key is allowlisted ({n} rows)", n > 0 and not bad)
    # memory: 200k hits with random paths, tags, user agents and regions
    m = VS.Counter(now=lambda: clock[0]); rnd = random.Random(7)
    for i in range(200000):
        tg = "".join(rnd.choice("abcdefghij0123456789") for _ in range(8))
        ua = UA_H + str(i) if i % 3 else "agent-%d/1.0" % i
        m.hit("GET", rnd.choice((200, 404, 500)), "/api/v1/%s?ref=%s" % (secrets.token_hex(4), tg) if i % 2 else "/address/poa1%d?ref=%s" % (i, tg), ua, None,
              lambda: "10.0.%d.%d" % (i >> 8 & 255, i & 255), rnd.random() * 2000, secrets.token_hex(2))
    for i in range(2000): m.event("prompt", "x%d" % i); m.event("mcp", "t%d" % i); m.event("search", "s%d" % i)
    sz = m.size(); per = {}
    for k in m.ev: per[k[0]] = per.get(k[0], 0) + 1
    bound = 2 + 1 + len(VS.CLIENT_KEYS) + 3 + 300 + len(VS.EDGES) + 1 + VS.TAG_CAP + 6 + len(VS.GROUPS) * 6
    check(f"event keys bounded after 200k random hits: {sz['event_keys']} <= {bound} {per}", sz["event_keys"] <= bound and per.get("tag", 0) <= VS.TAG_CAP
          and per.get("api", 0) <= 1 and per.get("mcp", 0) <= 1 and "prompt" not in per)
    gp = os.environ.get("POASCAN_GEOIP")
    if gp and os.path.isfile(gp):
        check("country lookups (DB-IP Lite)", geo.country("8.8.8.8") == "US" and geo.country("81.2.69.142") == "GB" and geo.country("10.0.0.1") is None
              and geo.country("not-an-ip") is None and (geo.source() or "").startswith("DB-IP Lite"))
    else:
        check("no country file: country is off, not guessed", geo.country("8.8.8.8") is None and geo.source() is None and "country" not in per)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def req(base, path, headers=None, data=None, method=None):
    r = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as f: return f.status, dict(f.headers), f.read()
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read()

def server():
    tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "s.db"); tok = secrets.token_urlsafe(32); logf = os.path.join(tmp, "server.log")
    port = free_port(); env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POASCAN_STATS_TOKEN=tok, POA_BASE="http://127.0.0.1:9")
    lg = open(logf, "wb")
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=lg, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    cookies = []
    try:
        H = {"User-Agent": UA_IPHONE, "Fly-Client-IP": "203.0.113.77", "Fly-Region": "sjc"}
        for path in ["/?ref=launch", "/start", "/search?q=" + SECRET_Q, "/search?q=5", "/search?q=" + HEX, "/no-such-page"]:
            c, h, _ = req(base, path, H); cookies.append(h.get("Set-Cookie"))
        req(base, "/api/v1/epochs", {"User-Agent": "curl/8.5.0"}); req(base, "/api/v1/tx/" + HEX, {"User-Agent": "python-requests/2.32"})
        mc = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_network_summary", "arguments": {}}}).encode()
        req(base, "/mcp", {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": "Claude-User/1.0"}, mc)
        E = lambda body, hd=None: req(base, "/ops/e", dict({"User-Agent": UA_H, "Content-Type": "text/plain;charset=UTF-8", "Fly-Client-IP": "203.0.113.80"}, **(hd or {})), body, "POST")
        c, h, b = E(b'{"e":"start.copy"}', {"Origin": base}); cookies.append(h.get("Set-Cookie"))
        check(f"POST /ops/e known id, same origin -> {c}, no body, no-store", c == 204 and b == b"" and h.get("Cache-Control") == "no-store")
        check("POST /ops/e without Origin (older beacons) -> 204", E(b'{"e":"start.regshow"}')[0] == 204)
        c, _, b = E(json.dumps({"e": SECRET_Q}).encode()); check(f"unknown id rejected -> {c}", c == 400 and SECRET_Q.encode() not in b)
        check("bad JSON, missing e, non-string e rejected", E(b"nope")[0] == 400 and E(b"{}")[0] == 400 and E(b'{"e":1}')[0] == 400)
        check("body over 256 bytes -> 413", E(json.dumps({"e": "start.copy", "x": "a" * 300}).encode())[0] == 413)
        check("other origin -> 403", E(b'{"e":"start.copy"}', {"Origin": "https://evil.example"})[0] == 403)
        c, h, b = req(base, "/ops/e", {"User-Agent": UA_H}); check(f"GET /ops/e is the normal 404 ({c})", c == 404)
        check("CSP still same-origin connect only", "connect-src 'self'" in (h.get("Content-Security-Policy") or ""))
        codes = [E(b'{"e":"join.copy"}', {"Fly-Client-IP": "203.0.113.81"})[0] for _ in range(30)]
        check(f"burst rate limited per IP: {codes.count(204)} x 204, {codes.count(429)} x 429", codes.count(429) > 0 and codes.count(204) <= 21)
        check("no Set-Cookie on any response", not any(cookies))
        c, h, b = req(base, "/ops/visits", {"Authorization": "Bearer " + tok}); d = json.loads(b) if c == 200 else {}
        day = (d.get("days") or [{}])[0]
        need = {"api", "mcp", "clients", "prompts", "funnel", "campaigns", "devices", "countries", "edges", "search", "health"}
        check(f"/ops/visits has the new sections ({c})", c == 200 and need <= set(day) and "metrics" in d and "country_source" in d)
        check(f"api {day.get('api')}, mcp {day.get('mcp')}", day.get("api") == {"/api/v1/epochs": 1, "/api/v1/tx/{hash}": 1} and day.get("mcp") == {"get_network_summary": 1})
        check(f"search outcomes {day.get('search')}", day.get("search") == {"none": 1, "epoch": 1, "tx": 1})
        check(f"prompts {day.get('prompts')}", day.get("prompts", {}).get("start.copy") == 1 and day.get("prompts", {}).get("start.regshow") == 1
              and 1 <= day.get("prompts", {}).get("join.copy", 0) <= 21)
        check(f"devices {day.get('devices')}, edges {day.get('edges')}, campaigns {day.get('campaigns')}", day.get("devices", {}).get("mobile", 0) >= 2
              and day.get("edges", {}).get("sjc", 0) >= 2 and day.get("campaigns") == {"other": 1})
        check(f"funnel {day.get('funnel')}", day.get("funnel", {}).get("start_views_human") == 1 and day.get("funnel", {}).get("start_copies") == 1
              and day.get("funnel", {}).get("registry_shows") == 1)
        check(f"health {day.get('health', {}).get('not_found')}", day.get("health", {}).get("not_found") == {"other": 1, "epochs": 1} and "home" in day.get("health", {}).get("response_ms", {}))
        c, _, b = req(base, "/ops/visits"); check("/ops/visits without the token is still 404", c == 404 and b"days" not in b)
        c, _, pv = req(base, "/privacy"); pv = pv.decode()
        check("/privacy lists the new counts, never search text, no 'not sold' claim, no em dash", c == 200 and "Daily feature counts." in pv and "Never the search text." in pv
              and "campaign tag" in pv and "Device type (mobile, tablet or desktop)" in pv and "IP Geolocation by DB-IP" in pv
              and "Site health." in pv and "not sold" not in pv.lower() and "sold or shared" not in pv.lower() and chr(0x2014) not in pv)
    finally: p.terminate(); p.wait(10); lg.close()
    logs = open(logf, "rb").read()
    check(f"search text never in the server log ({len(logs)} bytes of log)", SECRET_Q.encode() not in logs and b"/search" in logs)
    raw = open(dbp, "rb").read() + (open(dbp + "-wal", "rb").read() if os.path.exists(dbp + "-wal") else b"")
    check("search text, test IP and UA never in the DB bytes", SECRET_Q.encode() not in raw and b"203.0.113.77" not in raw and b"iPhone" not in raw)
    from poascan import visits as VS
    n, bad = scan(dbp, VS); check(f"server DB: every key allowlisted ({n} rows)", n > 0 and not bad)

if __name__ == "__main__":
    unit(); server()
    print("FAILED: " + ", ".join(fails) if fails else "all event checks passed")
    sys.exit(1 if fails else 0)
