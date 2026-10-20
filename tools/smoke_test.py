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
        c, b = req(base + "/openapi.json"); spec = json.loads(b) if c == 200 else {}
        check("openapi.json 3.1 with paths", spec.get("openapi", "").startswith("3.1") and len(spec.get("paths", {})) > 20)
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
        check(f"mcp tools/list ({len(tools)} tools)", len(tools) >= 10)
        for t in tools:
            args = {"address": "poa1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"} if t == "get_address" else {"hash": "0" * 64} if t == "get_transaction" else \
                   {"offer_id": "x"} if t == "get_swap_offer" else {"query": "plus1"} if t == "search" else {}
            c, b = rpc("tools/call", {"name": t, "arguments": args}); r = json.loads(b) if c == 200 else {}
            check(f"mcp tools/call {t}", c == 200 and "result" in r and r["result"]["content"][0]["type"] == "text")
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
        c, _ = req(base + "/find"); check(f"GET /find -> {c}", c == 200)
        txt = b"".join(req(base + x)[1] for x in ["/", "/about", "/api", "/find", "/epochs", "/llms.txt", "/llms-full.txt", "/openapi.json"]).decode()
        check("no em/en dashes in output", chr(0x2014) not in txt and chr(0x2013) not in txt)
    finally:
        p.terminate(); p.wait(10)
    print(f"{len(fails)} failure(s)"); sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
