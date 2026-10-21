"""CI smoke test: start POAScan on an empty database with the indexer off (no upstream calls), then check
key pages, the API, openapi.json, llms.txt and the MCP server. Usage: python3 tools/smoke_test.py"""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def req(url, data=None, headers=None):
    r = urllib.request.Request(url, data, headers or {})
    try:
        with urllib.request.urlopen(r, timeout=20) as f: return f.status, f.read()
    except urllib.error.HTTPError as e: return e.code, e.read()

def reqh(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as f: return f.status, dict(f.headers), f.read()
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read()

META_KEYS = {"api_version", "source_height", "checkpoint", "epoch", "node_as_of", "fetched_at", "stale", "stale_after_s"}

def main():
    port = free_port(); base = f"http://127.0.0.1:{port}"; tmp = tempfile.mkdtemp()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "t.db"), POASCAN_INDEXER="0")
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=root, env=env)
    fails = []
    def check(name, cond):
        print(("ok   " if cond else "FAIL ") + name); cond or fails.append(name)
    try:
        for _ in range(50):
            try: req(base + "/api/health"); break
            except Exception: time.sleep(0.2)
        for path in ["/", "/about", "/api", "/token", "/swaps", "/epochs", "/agents", "/agents/top", "/status"]:
            c, _ = req(base + path); check(f"GET {path} -> {c}", c == 200)
        c, b = req(base + "/healthz"); check(f"GET /healthz -> {c}", c == 200)
        c, b = req(base + "/api/health"); h = json.loads(b) if c in (200, 503) else {}
        check(f"GET /api/health -> {c} matches ok={h.get('ok')}", "ok" in h and c == (200 if h["ok"] else 503))
        c, _ = req(base + "/api/agents/series"); c2, _ = req(base + "/api/accounts/series"); check(f"series alias -> {c}/{c2}", c == c2 == 200)
        for path in ["/api/summary", "/api/epochs", "/api/swaps", "/api/unlocks", "/api/leaderboard/richlist", "/api/params", "/api/chains"]:
            c, b = req(base + path); ok = c == 200
            try: json.loads(b)
            except Exception: ok = False
            check(f"GET {path} -> {c} json", ok)
        root_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        ver = re.search(r'VERSION = "([0-9.]+)"', open(os.path.join(root_dir, "poascan", "agentapi.py")).read()).group(1)
        for f in ("server.json", "gemini-extension.json"):
            check(f"{f} version {ver}", json.load(open(os.path.join(root_dir, f))).get("version") == ver)
        check("CHANGELOG has version", f"## [{ver}]" in open(os.path.join(root_dir, "CHANGELOG.md")).read())
        for path in ["/api/summary", "/api/health", "/api/params", "/api/status"]:
            c1, h1, b1 = reqh(base + path); c2, h2, b2 = reqh(base + "/api/v1" + path[4:])
            d1 = json.loads(b1) if b1 else {}; d2 = json.loads(b2) if b2 else {}
            check(f"v1 alias {path} -> {c1}/{c2}", c1 == c2 and set(d1) == set(d2))
            check(f"{path} meta + X-API-Version", META_KEYS <= set(d2.get("meta", {})) and h2.get("X-API-Version") == ver)
        for path in ["/api/v1/epochs", "/api/epochs", "/api/v1/richlist.csv", "/api/agents/series"]:
            c, h, b = reqh(base + path)
            ok = c == 200 and all(k in h for k in ("X-API-Version", "X-Source-Height", "X-Epoch", "X-Fetched-At", "X-Stale"))
            if not path.endswith(".csv"): ok = ok and isinstance(json.loads(b), list)
            check(f"list headers {path}", ok)
        c, h, _ = reqh(base + "/api/v1/nope"); check(f"v1 404 -> {c}", c == 404 and h.get("X-API-Version") == ver)
        c, b = req(base + "/openapi.json"); spec = json.loads(b) if c == 200 else {}
        check("openapi.json 3.1 with paths", spec.get("openapi", "").startswith("3.1") and len(spec.get("paths", {})) > 20)
        check("openapi v1 paths, version, Meta", spec.get("info", {}).get("version") == ver and "/api/v1/summary" in spec.get("paths", {})
              and spec["paths"]["/api/v1/summary"]["get"].get("x-alias") == "/api/summary" and "Meta" in spec.get("components", {}).get("schemas", {}))
        c, b = req(base + "/llms.txt"); check("llms.txt", c == 200 and b.startswith(b"# POAScan") and b"/mcp" in b)
        c, b = req(base + "/.well-known/mcp.json"); check("mcp.json", c == 200 and "tools" in json.loads(b))
        c, _ = req(base + "/api/health", b"x", {"Content-Type": "text/plain"}); check(f"POST /api/health -> {c} (read-only)", c == 405)
        c, _ = req(base + "/mcp"); check(f"GET /mcp -> {c}", c == 405)
        H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        rpc = lambda m, params=None, i=1: req(base + "/mcp", json.dumps({"jsonrpc": "2.0", "id": i, "method": m, "params": params or {}}).encode(), H)
        c, b = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}})
        check("mcp initialize", c == 200 and json.loads(b)["result"]["serverInfo"]["name"] == "poascan")
        c, b = req(base + "/mcp", json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(), H); check(f"mcp notification -> {c}", c == 202)
        c, b = rpc("tools/list"); tools = [t["name"] for t in json.loads(b)["result"]["tools"]] if c == 200 else []
        check(f"mcp tools/list ({len(tools)} tools)", len(tools) == 16 and {"get_swap_status", "get_onboarding_steps"} <= set(tools))
        readme = open(os.path.join(root, "README.md")).read()
        check("README tool count + names", f"* {len(tools)} tools:" in readme and all(f"`{t}`" in readme for t in tools))
        c, b = req(base + "/llms.txt"); check("llms.txt tool count", f"Tools ({len(tools)}):".encode() in b)
        c, b = rpc("tools/call", {"name": "get_swap_status", "arguments": {}}); sc = json.loads(b)["result"]["structuredContent"]
        check("get_swap_status fields", {"available", "state", "last_good_read", "open_offers"} <= set(sc))
        c, b = rpc("tools/call", {"name": "get_onboarding_steps", "arguments": {}}); sc = json.loads(b)["result"]["structuredContent"]
        check("get_onboarding_steps matches /start", sc.get("url") == "https://poascan.io/start" and "npm install -g @emblemvault/agentwallet" in sc.get("prompt", "") and len(sc.get("steps", [])) >= 5)
        for t in tools:
            args = {"address": "poa1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"} if t == "get_address" else {"hash": "0" * 64} if t == "get_transaction" else \
                   {"offer_id": "x"} if t == "get_swap_offer" else {"query": "plus1"} if t == "search" else {}
            c, b = rpc("tools/call", {"name": t, "arguments": args}); r = json.loads(b) if c == 200 else {}
            check(f"mcp tools/call {t}", c == 200 and "result" in r and r["result"]["content"][0]["type"] == "text")
            sc = (r.get("result") or {}).get("structuredContent") or {}
            check(f"mcp tools/call {t} meta", META_KEYS <= set(sc.get("meta", {})))
        c, b = rpc("nope/nope"); check("mcp unknown method -> -32601", json.loads(b).get("error", {}).get("code") == -32601)
        c, b = req(base + "/robots.txt"); check("robots.txt allows AI bots + sitemap", c == 200 and b"GPTBot" in b and b"Sitemap: https://poascan.io/sitemap.xml" in b)
        c, b = req(base + "/sitemap.xml"); check("sitemap.xml", c == 200 and b"<urlset" in b and b"https://poascan.io/about" in b)
        c, b = req(base + "/blocks"); check("canonical /blocks -> /epochs", b'rel="canonical" href="https://poascan.io/epochs"' in b and b'og:url" content="https://poascan.io/epochs"' in b)
        c, b = req(base + "/"); check("home JSON-LD + h1", b"application/ld+json" in b and b'<h1 class="sr-only">Proof of Agent explorer</h1>' in b and b'href="/find"' in b and b"homehead" not in b)
        c, b = req(base + "/llms.txt"); check("llms.txt Join section", b"## Join PoA" in b and b"https://minepoa.com/mcp" in b and b"invite or referral" in b)
        c, b = req(base + "/llms-full.txt"); check(f"llms-full.txt -> {c}", c == 200 and b"## MCP tools" in b and b"## Endpoints" in b)
        for u in ["/mcp/server-card", "/.well-known/mcp/server-card.json", "/.well-known/mcp-server-card"]:
            c, b = req(base + u); check(f"server card {u}", c == 200 and json.loads(b)["remotes"][0]["url"].endswith("/mcp"))
        c, b = req(base + "/.well-known/ai-catalog.json"); check("ai-catalog.json", c == 200 and json.loads(b)["entries"][0]["type"] == "application/mcp-server-card+json")
        for u in ["/.well-known/agent-card.json", "/.well-known/agent.json"]:
            c, b = req(base + u); j = json.loads(b); check(f"agent card {u}", c == 200 and j["supportedInterfaces"][0]["url"].endswith("/mcp") and len(j["skills"]) >= 5)
        INDEXNOW_KEY = re.search(r'INDEXNOW_KEY = "([0-9a-f]+)"', open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "agentapi.py")).read()).group(1)
        c, b = req(base + f"/{INDEXNOW_KEY}.txt"); check("IndexNow key file", c == 200 and b.decode().strip() == INDEXNOW_KEY)
        c, b = req(base + "/BingSiteAuth.xml"); check(f"BingSiteAuth.xml off without env -> {c}", c == 404)
        c, b = req(base + "/privacy"); check("privacy page", c == 200 and b"No cookies" in b and b'href="/privacy"' in b)
        c, b = req(base + "/.well-known/agentpeering-verify"); check("agentpeering verify", c == 200 and b.strip() == b"ap-verify-cec18af41a029ed83d4e21ee0268f52c")
        c, b = req(base + "/epoch/1"); check("epoch breadcrumbs", b"BreadcrumbList" in b)
        c, b = req(base + "/api/v1/swaps/status"); sw = json.loads(b) if c == 200 else {}
        check(f"swaps status -> {c}", c == 200 and {"available", "state", "last_good_read", "open_offers", "meta"} <= set(sw))
        check("swaps status upgrading on empty DB", sw.get("available") is False and sw.get("state") == "upgrading")
        c, b = req(base + "/api/v1/summary"); check("summary swaps block", json.loads(b).get("swaps", {}).get("state") in ("available", "upgrading"))
        c, b = req(base + "/swaps"); low = b.decode().lower()
        check("swaps pill", b"Swaps are being upgraded. Check back soon." in b and not any(w in low.split("xpill")[1][:400] for w in ("down", "broken", "outage", "error")))
        _mn = b.split(b"<main")[1].split(b"</main>")[0]
        check("swap panel: Buy/Sell, pair, upgrading button, safe line, fee once", all(x in _mn for x in (b'data-side="buy"', b'data-side="sell"', b'id="xpair"', b'id="xgo" data-up="0" disabled', b"Only swap through the network. Never send payment outside it.", b"via Emblem", b'href="/how-to-buy-poa#self-custody"')) and _mn.count(b"1%") == 1)
        check("swaps: no wallet card, warn tiles or how-to", not any(x in _mn for x in (b"walletc", b"wtiles", b'id="howto"', b"Get the Emblem Wallet")))
        check("swaps: book, price, fills", all(x in _mn for x in (b'id="xbook"', b"Order book", b"Recent fills", b"No fills yet")) and req(base + "/static/swap.js")[0] == 200)
        check("swap prompts check /api/swaps first", b"Before anything else, GET https://minepoa.com/api/swaps" in b and b"don&#x27;t call swap-take" in b)
        check("openapi SwapStatus", "/api/v1/swaps/status" in spec["paths"] and "SwapStatus" in spec["components"]["schemas"])
        c, b = req(base + "/start"); check("/start: h1 Join, one Copy prompt", b"<h1>Join</h1>" in b and b.split(b"<main")[1].split(b"</main>")[0].count(b"data-copy-prompt") == 1)
        import base64 as _b64, json as _js, re as _re
        from urllib.parse import unquote as _uq, urlparse as _up, parse_qs as _pq
        _m = b.split(b"<main")[1].split(b"</main>")[0].decode()
        _cur = _re.search(r'href="(cursor://[^"]+)"', _m); _vs = _re.search(r'href="(vscode:mcp/install\?[^"]+)"', _m)
        _ok = bool(_cur and _vs)
        if _ok:
            _q = _pq(_up(_cur.group(1).replace("&amp;", "&")).query)
            _ok = _js.loads(_b64.b64decode(_q["config"][0])) == {"url": "https://minepoa.com/mcp"} and _q["name"] == ["poa"]
            _ok = _ok and _js.loads(_uq(_vs.group(1).split("?", 1)[1])) == {"name": "poa", "type": "http", "url": "https://minepoa.com/mcp"}
        check("/start: One click first, Mine deeplinks decode", _ok and _m.index("One click") < _m.index("data-copy-prompt") and "claude mcp add --transport http poa https://minepoa.com/mcp" in _m)
        check("/start: Open in apps + collapsed Steps", b'data-app="ChatGPT"' in b.split(b"<main")[1].split(b"</main>")[0] and b'<details class="card stepsd">' in b)
        check(f"GET /start -> {c}", c == 200 and b"npm install -g @emblemvault/agentwallet" in b and b"Never send payment outside the network" in b
                                              and b'rel="canonical" href="https://poascan.io/start"' in b and b"HowTo" in b)
        c, b = req(base + "/"); check("home has no second onboarding CTA", b"Start mining in one paste" not in b and b.count(b'href="/start"') == 1)
        check("Join button -> /start", b'<a class="joinbtn hdrjoin" href="/start">Join</a>' in b)
        c, b = req(base + "/join"); check("/join alias", c == 200 and b'href="https://poascan.io/start"' in b)
        check("sitemap + llms have /start", b"https://poascan.io/start" in req(base + "/sitemap.xml")[1] and b"https://poascan.io/start" in req(base + "/llms.txt")[1])
        for u in ["/what-is-proof-of-agent", "/how-to-mine-poa", "/how-to-buy-poa", "/what-is-poascan"]:
            c, b = req(base + u)
            check(f"FAQ {u}", c == 200 and b'"FAQPage"' in b and f'rel="canonical" href="https://poascan.io{u}"'.encode() in b and b'og:title' in b
                  and f'href="{u}"'.encode() in req(base + "/about")[1] and f"https://poascan.io{u}".encode() in req(base + "/sitemap.xml")[1] and f"https://poascan.io{u}".encode() in req(base + "/llms.txt")[1])
        for u in ["/api/v1/swaps/price-history", "/api/v1/agents/new-per-day", "/api/v1/uptime", "/api/v1/uptime.csv", "/api/v1/uptime?endpoint=/api/swaps"]:
            c, h, b = reqh(base + u); check(f"history {u} -> {c}", c == 200 and "X-API-Version" in h and (u.endswith(".csv") or isinstance(json.loads(b), list)))
            check(f"openapi has {u.split('?')[0].replace('.csv', '')}", u.split("?")[0].replace(".csv", "") in spec["paths"])
        check("history charts", b"price-history.csv" in req(base + "/swaps")[1] and b"New Agents" in req(base + "/agents")[1] and b"Uptime" in req(base + "/status")[1])
        c, _ = req(base + "/find"); check(f"GET /find -> {c}", c == 200)
        txt = b"".join(req(base + x)[1] for x in ["/", "/start", "/swaps", "/agents", "/status", "/what-is-proof-of-agent", "/how-to-mine-poa", "/how-to-buy-poa", "/what-is-poascan", "/about", "/api", "/find", "/privacy", "/epochs", "/llms.txt", "/llms-full.txt", "/openapi.json"]).decode()
        check("no em/en dashes in output", chr(0x2014) not in txt and chr(0x2013) not in txt)
    finally:
        p.terminate(); p.wait(10)
    print(f"{len(fails)} failure(s)"); sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
