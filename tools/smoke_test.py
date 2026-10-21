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
        check(f"mcp tools/list ({len(tools)} tools)", len(tools) == 19 and {"get_pending_by_epoch", "get_swap_status", "get_onboarding_steps", "get_cluster_signals", "list_agents"} <= set(tools))
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
        c, b = req(base + "/privacy"); check("privacy page", c == 200 and b"No cookies" in b and b'href="/privacy"' in req(base + "/")[1])
        c, b = req(base + "/.well-known/agentpeering-verify"); check("agentpeering verify", c == 200 and b.strip() == b"ap-verify-cec18af41a029ed83d4e21ee0268f52c")
        c, b = req(base + "/epoch/1"); check("epoch breadcrumbs", b"BreadcrumbList" in b)
        c, b = req(base + "/api/v1/swaps/status"); sw = json.loads(b) if c == 200 else {}
        check(f"swaps status -> {c}", c == 200 and {"available", "state", "last_good_read", "open_offers", "meta"} <= set(sw))
        check("swaps status coming soon before launch", sw.get("available") is False and sw.get("state") == "coming_soon" and "coming soon" in (sw.get("message") or ""))
        c, b = req(base + "/api/v1/summary"); check("summary swaps block", json.loads(b).get("swaps", {}).get("state") in ("available", "coming_soon", "upgrading"))
        c, b = req(base + "/swaps"); low = b.decode().lower()
        import re as _re0
        _mn0 = _re0.sub(rb'data-tpl="[^"]*"', b"", b.split(b"<main")[1].split(b"</main>")[0])
        check("swaps: Coming soon once, no upgrade copy", _mn0.count(b"Coming soon") == 1 and _mn0.lower().count(b"coming soon") == 1 and b"being upgraded" not in _mn0.lower()
              and b'<button class="xbtn soon" type="button" id="xgo" data-up="0" aria-disabled="true">Coming soon</button>' in _mn0 and b'class="xnote"' not in _mn0)
        _mn = b.split(b"<main")[1].split(b"</main>")[0]
        check("swap panel: Buy/Sell, pair, Coming soon button, Emblem row, safe line, fee once", all(x in _mn for x in (b'data-side="buy"', b'data-side="sell"', b'id="xpair"', b'id="xgo" data-up="0" aria-disabled="true"', b'id="xemb"', b"Never send payment outside the network.", b"via Emblem", b'<summary aria-label="Add Emblem Wallet">', b"<span>Add Wallet</span>")) and b"Self-custody" not in _mn and b'<div class="xembr"><p class="xsafe">' in _mn and _mn.count(b"1%") == 1)
        check("swaps: no wallet card, warn tiles or how-to", not any(x in _mn for x in (b"walletc", b"wtiles", b'id="howto"', b"Get the Emblem Wallet")))
        check("swaps: book, price, fills", all(x in _mn for x in (b'id="xbook"', b"Order book", b"Recent fills", b"No fills yet")) and req(base + "/static/swap.js")[0] == 200)
        check("swap prompts say coming soon and gate on swaps/status", b"Swaps are coming soon. Until https://poascan.io/api/v1/swaps/status shows available:true" in b and b"don&#x27;t call swap-offer, swap-take" in b and b"being upgraded" not in b)
        c, b = req(base + "/api/v1/concentration"); cj = json.loads(b) if c == 200 else {}
        check(f"concentration -> {c}", c == 200 and {"top1_share", "top5_share", "top10_share", "top20_share", "gini", "min_activity", "meta"} <= set(cj))
        check("summary concentration + openapi", "concentration" in json.loads(req(base + "/api/v1/summary")[1]) and "/api/v1/concentration" in spec["paths"] and "Concentration" in spec["components"]["schemas"])
        c, b = req(base + "/api/v1/clusters"); cl = json.loads(b) if c == 200 else {}
        check(f"clusters -> {c}", c == 200 and {"groups", "counts", "thresholds", "note", "meta"} <= set(cl) and "/api/v1/clusters" in spec["paths"])
        check("/agents/operators cluster signals + /about method", b"Cluster signals" in req(base + "/agents/operators")[1] and b'id="signals"' in req(base + "/about")[1])
        c, b = req(base + "/api/v1/agents/view?limit=2"); av = json.loads(b) if c == 200 else {}
        check(f"agents/view -> {c}", c == 200 and {"rows", "next_cursor", "limit", "total", "meta"} <= set(av) and av["limit"] == 2 and "/api/v1/agents/view" in spec["paths"])
        _r = urllib.request.urlopen(base + "/api/v1/agents/view?limit=2"); _et = _r.headers.get("ETag")
        try: _c = urllib.request.urlopen(urllib.request.Request(base + "/api/v1/agents/view?limit=2", headers={"If-None-Match": _et})).status
        except urllib.error.HTTPError as e: _c = e.code
        check(f"agents/view ETag -> 304 ({_c})", bool(_et) and _c == 304)
        check("agents/view bad cursor -> 400", req(base + "/api/v1/agents/view?after=%%%")[0] == 400)
        c, b = req(base + "/live"); check(f"/live -> {c}", c == 200 and b'id="feed"' in b and b'data-live="answers"' in b and b'livehero' in b)
        check("/live in sitemap + llms + home link", b"/live</loc>" in req(base + "/sitemap.xml")[1] and b"/live" in req(base + "/llms.txt")[1] and b'href="/live"' in req(base + "/")[1])
        check("/token concentration card", b"Min-activity Agents" in req(base + "/token")[1])
        import re as _re, sys as _sys, os as _os2
        _sys.path.insert(0, _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), ".."))
        from poascan import agentapi as _AG, indexer as _IX
        from poascan.swapx import _usd as _U
        check("no scientific notation: JSON numbers, USD stats, fill payment ref under proof",
              _AG.plainjson('{"a": 1.059e-05, "s": "1e-05"}') == '{"a": 0.00001059, "s": "1e-05"}'
              and not _re.search(r"\d[eE][-+]\d", req(base + "/api/v1/swaps/status")[1].decode().split('"meta"')[0])
              and [_U(v) for v in (327.56, 10388.08, 0.11, 0.00001059)] == ["$327.56", "$10,388", "$0.11", "$0.000011"]
              and _IX._ref({"proof": {"chain": "solana", "ref": "abc"}}) == "abc" and "node_stale" in req(base + "/api/v1/swaps/status")[1].decode())
        _mk = json.loads(req(base + "/api/v1/swaps/status")[1])["market"]; _sw = req(base + "/swaps")[1].decode()
        check("swaps market: all-time fields added, 24h kept; /swaps row says Trades and Volume once",
              {"trades_all_time", "volume_all_time_usd", "trades_24h", "volume_24h_usd"} <= set(_mk) and isinstance(_mk["trades_all_time"], int)
              and _sw.count('<span class="lbl">Trades</span>') == 1 and _sw.count('<span class="lbl">Volume</span>') == 1 and "24h Trades" not in _sw
              and "trades_all_time" in spec["components"]["schemas"]["SwapStatus"]["properties"]["market"]["properties"])
        check("openapi SwapStatus", "/api/v1/swaps/status" in spec["paths"] and "SwapStatus" in spec["components"]["schemas"])
        c, b = req(base + "/start"); check("/start: title Start, one Copy inside the prompt box, Close", b"<title>Start \xc2\xb7 POAScan</title>" in b and b"<h1 class=\"sr-only\">Start</h1>" in b
              and b.split(b"<main")[1].split(b"</main>")[0].count(b"data-copy-prompt") == 1 and b'<div class="pbox"><div class="pbar"><button class="pcopy"' in b and b'data-back aria-label="Close"' in b)
        import base64 as _b64, json as _js, re as _re
        from urllib.parse import unquote as _uq, urlparse as _up, parse_qs as _pq
        _m = b.split(b"<main")[1].split(b"</main>")[0].decode()
        _cur = _re.search(r'href="(https://cursor\.com/install-mcp\?[^"]+)" data-mcp="cursor" target="_blank" rel="noopener" data-mcpcopy=', _m); _vs = _re.search(r'href="(vscode:mcp/install\?[^"]+)"', _m)
        _ok = bool(_cur and _vs)
        if _ok:
            _q = _pq(_up(_cur.group(1).replace("&amp;", "&")).query)
            _ok = _js.loads(_b64.b64decode(_q["config"][0])) == {"url": "https://minepoa.com/mcp"} and _q["name"] == ["poa"]
            _ok = _ok and _js.loads(_uq(_vs.group(1).split("?", 1)[1])) == {"name": "poa", "type": "http", "url": "https://minepoa.com/mcp"}
        check("/start: Copy before One click, Mine deeplinks decode", _ok and _m.index("data-copy-prompt") < _m.index("One click") and "claude mcp add --transport http poa https://minepoa.com/mcp" in _m)
        check("no in-page status pills", not any(x in req(base + u)[1] for u in ("/swaps", "/live", "/") for x in (b'class="pulse"', b"pill xpill", b"Catching up")))
        check("nav says Swap; page H1 kept but visually hidden", b'href="/swaps" class="on">Swap</a>' in req(base + "/swaps")[1] and b'<h1 class="sr-only">Start</h1>' in req(base + "/start")[1] and b'<h1 class="sr-only">Epochs</h1>' in req(base + "/epochs")[1])
        _lm = _re.search(r'href="(lmstudio://add_mcp\?[^"]+)"', _m); _ki = _re.search(r'href="(https://kiro\.dev/launch/mcp/add\?[^"]+)"', _m)
        check("/start: More toggles closed, extra MCP deeplinks decode", _m.count('aria-expanded="false" aria-controls="mp') == 2 and '>More<' in _m and '>Other clients<' in _m
              and bool(_lm and _ki) and _js.loads(_b64.b64decode(_pq(_up(_lm.group(1).replace("&amp;", "&")).query)["config"][0])) == {"url": "https://minepoa.com/mcp"}
              and _js.loads(_pq(_up(_ki.group(1).replace("&amp;", "&")).query)["config"][0])["url"] == "https://minepoa.com/mcp"
              and all(f'data-app="{n}"' in _m for n in ("Kimi", "Z.ai", "DeepSeek", "Le Chat", "HuggingChat")))
        check("/api: POAScan MCP install options", all(x in req(base + "/api")[1] for x in (b'data-mcp="cursor"', b'data-mcp="goose"', b"codex mcp add poascan --url https://poascan.io/mcp", b">Other clients<")))
        _pb = [req(base + u)[1] for u in ("/start", "/swaps", "/how-to-buy-poa", "/api", "/how-to-mine-poa")]
        check("one prompt box: Copy inside every prompt, no bottom Copy prompt button", all(b"Copy prompt</button>" not in x and x.count(b'<div class="pbox"><div class="pbar"><button class="pcopy"') >= 1 for x in _pb)
              and all(x.count(b'class="pcopy"') == x.count(b'<div class="pbox">') for x in _pb))
        import os as _os
        _bd = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "static", "brands")
        _lg = _re.findall(r'<span class="an">(?:<img class="blogo" src="/static/brands/([^"?]+)\?v=1"[^>]*>|<i class="blogo mono")', _m)
        check("logos: every option on /start has a brand mark, files exist and serve, SOURCES.md listed",
              len(_lg) == _m.count('<span class="an">') == 29 and all(f and _os.path.isfile(_os.path.join(_bd, f)) for f in _lg)
              and all(req(base + "/static/brands/" + f)[0] == 200 for f in set(_lg))
              and all(f in open(_os.path.join(_bd, "SOURCES.md")).read() for f in set(_lg))
              and all(b'<span class="an"><img class="blogo"' in x for x in _pb))
        _mc = _m[_m.index('apps mcpa'):]; _oc = _mc.index('>Other clients<')
        check("/start Mine: every Add button also copies a config", all(_re.search(f'data-mcp="{k}"(?: target="_blank" rel="noopener")? data-mcpcopy="[^"]*minepoa.com/mcp[^"]*" data-app=', _m) for k in ("cursor", "vscode", "lmstudio", "goose", "vscode-insiders", "kiro", "trae", "cherry")))
        check("/start Mine: four one-click Add up front, everything else under Other clients", _mc[:_oc].count('data-mcp=') == 4
              and all(f'data-mcp="{k}"' in _mc[:_oc] for k in ("cursor", "vscode", "lmstudio", "goose")) and 'class="cmd"' not in _mc[:_oc]
              and _mc[_oc:].count('class="cmd"') == 7 and _mc[_oc:].index('data-mcp="cherry"') < _mc[_oc:].index('data-mcp="claude-code"'))
        check("/start: Open in apps + collapsed Steps", b'data-app="ChatGPT"' in b.split(b"<main")[1].split(b"</main>")[0] and b'<details class="card stepsd">' in b)
        check(f"GET /start -> {c}", c == 200 and b"npm install -g @emblemvault/agentwallet" in b and b"Never send payment outside the network" in b
                                              and b'rel="canonical" href="https://poascan.io/start"' in b and b"HowTo" in b)
        c, b = req(base + "/"); check("home has no second onboarding CTA", b"Start mining in one paste" not in b and b.count(b'href="/start"') == 1)
        check("Start button -> /start", b'<a class="joinbtn hdrjoin" href="/start">Start</a>' in b)
        c, b = req(base + "/join"); check("/join alias", c == 200 and b'href="https://poascan.io/start"' in b)
        check("sitemap + llms have /start", b"https://poascan.io/start" in req(base + "/sitemap.xml")[1] and b"https://poascan.io/start" in req(base + "/llms.txt")[1])
        for u in ["/what-is-proof-of-agent", "/how-to-mine-poa", "/how-to-buy-poa", "/what-is-poascan"]:
            c, b = req(base + u)
            check(f"FAQ {u}", c == 200 and b'"FAQPage"' in b and f'rel="canonical" href="https://poascan.io{u}"'.encode() in b and b'og:title' in b
                  and f'href="{u}"'.encode() in req(base + "/about")[1] and f"https://poascan.io{u}".encode() in req(base + "/sitemap.xml")[1] and f"https://poascan.io{u}".encode() in req(base + "/llms.txt")[1])
        for u in ["/api/v1/swaps/price-history", "/api/v1/agents/new-per-day", "/api/v1/uptime", "/api/v1/uptime.csv", "/api/v1/uptime?endpoint=/api/swaps"]:
            c, h, b = reqh(base + u); check(f"history {u} -> {c}", c == 200 and "X-API-Version" in h and (u.endswith(".csv") or isinstance(json.loads(b), list)))
            check(f"openapi has {u.split('?')[0].replace('.csv', '')}", u.split("?")[0].replace(".csv", "") in spec["paths"])
        check("history charts", b"Price</h2>" in req(base + "/swaps")[1] and b"New Agents" in req(base + "/agents")[1] and b"Uptime" in req(base + "/status")[1])
        sb = req(base + "/swaps")[1]; check("swap market row", b'class="xstats"' in sb and all(x in sb for x in (b">Market Cap<", b">FDV<", b">Trades<", b">Volume<")) and sb.count(b"Trades") == 1 and sb.count(b"Volume") == 1)
        mk = json.loads(req(base + "/api/swaps/status")[1]).get("market") or {}; check("swap market api", all(k in mk for k in ("market_cap_usd", "fdv_usd", "trades_24h", "volume_24h_usd")))
        pe = json.loads(req(base + "/api/v1/pending-by-epoch")[1]); check("pending by epoch api", all(k in pe for k in ("current_epoch", "total", "stale_total", "rows")) and isinstance(pe["rows"], list))
        lv = req(base + "/live")[1]; check("live pending panel", b"Pending</h2>" in lv and b"\xe2\x80\x94" not in lv)
        check("emblem toggle logo", b"/static/emblem-32.png" in sb and b"<span>Add Wallet</span>" in sb and b"\xc2\xb7\xc2\xb7\xc2\xb7</span></b>" not in sb.split(b'class="xstats"')[1][:900])
        c, _ = req(base + "/find"); check(f"GET /find -> {c}", c == 200)
        txt = b"".join(req(base + x)[1] for x in ["/", "/start", "/swaps", "/agents", "/status", "/what-is-proof-of-agent", "/how-to-mine-poa", "/how-to-buy-poa", "/what-is-poascan", "/about", "/api", "/find", "/privacy", "/epochs", "/llms.txt", "/llms-full.txt", "/openapi.json"]).decode()
        check("no em/en dashes in output", chr(0x2014) not in txt and chr(0x2013) not in txt)
    finally:
        p.terminate(); p.wait(10)
    fixture_pages(check)
    print(f"{len(fails)} failure(s)"); sys.exit(1 if fails else 0)

def raw(base, path, hdrs=None, method="GET"):
    import http.client
    c = http.client.HTTPConnection(base.split("//")[1], timeout=20); c.request(method, path, headers=hdrs or {})
    r = c.getresponse(); b = r.read(); c.close(); return r.status, {k.lower(): v for k, v in r.getheaders()}, b

def headers(base, check):
    """Caching, HSTS and the www redirect."""
    c, h, _ = raw(base, "/static/style.css?v=1"); check("versioned asset is immutable", c == 200 and h.get("cache-control") == "public, max-age=31536000, immutable")
    c, h, _ = raw(base, "/static/style.css"); check("unversioned asset keeps a short cache", "immutable" not in h.get("cache-control", ""))
    c, h, _ = raw(base, "/token"); et = h.get("etag")
    check("HTML has HSTS (no preload) and an ETag", h.get("strict-transport-security") == "max-age=31536000" and et and h.get("cache-control") == "no-cache")
    c2, _, b2 = raw(base, "/token", {"If-None-Match": et}); check(f"HTML ETag revalidates -> {c2}", c2 == 304 and not b2)
    c, h, _ = raw(base, "/live?a=1&b=2", {"Host": "www.poascan.io"}); check("www redirects to the apex with path and query", c == 301 and h.get("location") == "https://poascan.io/live?a=1&b=2")
    c, _, b = raw(base, "/healthz", {"Host": "172.19.0.2:8080"}); check("health check unaffected", c == 200 and b == b"ok\n")

def fixture_pages(check):
    """Every nav and sitemap page must render (no 500) against seeded data with 12 epochs."""
    port = free_port(); base = f"http://127.0.0.1:{port}"; tmp = tempfile.mkdtemp()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "f.db"), POASCAN_INDEXER="0")
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    subprocess.run([sys.executable, "tools/fixture.py"], cwd=root, env=env, check=True)
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=root, env=env)
    try:
        for _ in range(50):
            try: req(base + "/api/health"); break
            except Exception: time.sleep(0.2)
        home = req(base + "/")[1].decode()
        nav = re.findall(r'<a href="(/[^"]*)" class="(?:on)?">', home)
        site = [u.replace("https://poascan.io", "") or "/" for u in re.findall(r"<loc>([^<]+)</loc>", req(base + "/sitemap.xml")[1].decode())]
        paths = sorted(set(nav + site))
        bad = [(u, c) for u in paths for c in [req(base + u)[0]] if c != 200]
        check(f"fixture (12 epochs): {len(nav)} nav + {len(site)} sitemap pages render, failures {bad[:5]}", len(nav) >= 10 and len(paths) > 30 and not bad)
        g = req(base + "/grading")[1]; check("fixture /grading: older origins grouped", b">Older<" in g)
        op = req(base + "/agents/operators")[1]
        check("fixture: malformed address shown as plain text, never linked", b'href="/address/poa132rY' not in b"".join(req(base + u)[1] for u in ("/agents/operators", "/agents", "/agents/top", "/address/poa1" + b"C".decode() * 40)))
        check("fixture: /network, /community, /agents/operators have their own h1", b"<h1" in req(base + "/network")[1] and b"<h1" in req(base + "/forum")[1]
              and b'<h1 class="sr-only">Operators</h1>' in op)
        headers(base, check)
        from poascan import indexer as _IX
        _jobs = {j[0]: j[2] for j in _IX.JOBS}
        check("probe: only / and /go.md, every 10 min, first 1 KB", _IX.PROBES == ["/", "/go.md"] and _jobs["probe"] == 600
              and _IX.uptime_name("/api/status") == "probe /api/status" and _IX.uptime_name("/api/params") == "/api/params")
        _st = req(base + "/status")[1].decode(); _csv = req(base + "/api/v1/uptime.csv")[1].decode()
        check("uptime: derived /api/status folds into one continuous series", _st.count("<code>/api/status</code>") == 2 and "/api/status,fetch" not in _csv.replace('"', ""))
        check("fixture: /grading has an h1", b"<h1" in g and b">Grading</h1>" in g)
        check("fixture: vesting shows days on /unlocks and in the FAQ", "≈25 days".encode() in req(base + "/unlocks")[1] and "over 100 epochs (≈25 days)".encode() in req(base + "/what-is-proof-of-agent")[1] and "≈ 25 days".encode() in req(base + "/about")[1])
    finally:
        p.terminate(); p.wait(10)

if __name__ == "__main__":
    main()
