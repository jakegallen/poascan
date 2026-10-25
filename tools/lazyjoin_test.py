"""Join dialog retired (1.26.86; lazy since 1.26.54) and swap state names. The header Start goes to /start, so pages carry no
Join dialog: no shell, no /fragment/join fetch, no [data-join] trigger. An old cached page that asks for /fragment/join gets a 301
to /start, and an old /#join link lands on /start. /start carries the three variant templates once, outside main. llms.txt,
llms-full.txt and the MCP tool descriptions write the swap state value coming_soon, never "coming soon", where they name it.
Usage: python3 tools/lazyjoin_test.py"""
import hashlib, json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
from html import unescape
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(TMP, "l.db")   # the server and the in-process checks share one DB
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

TS = "6762aa1cb3bf173a20f6d25af3045b10ef4463a962754e8f1f58dc28878b5cdd"
from poascan import onboarding_prompt as OP, start as S, swapflag as SF
check("join prompt template_sha256 unchanged (6762aa1c, v2.8)", hashlib.sha256(S.prompt("YOUR_NAME", "full").encode()).hexdigest() == TS == S.template_sha256())
check("coming_soon is the swap status value in the code", "coming_soon" in SF.STATUSES)

js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("app.js: no Join dialog code (no joinmodal, fetch of /fragment/join, data-join or jm-prompt); /#join lands on /start; cards still wired",
      not any(x in js for x in ("joinmodal", "jm.dataset.src", "fragment/join", "data-join", "jm-prompt", "poaJoin", "jmOpen"))
      and 'if(W.location.hash==="#join")location.replace("/start")' in js and "function goInit(go)" in js and "go.dataset.goOn" in js and 'D.getElementById("askmodal")' in js)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(u, h=None):
    try:
        with op.open(urllib.request.Request(u, None, h or {}), timeout=30) as f: return f.status, dict(f.headers), f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
port = free_port(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try: get(base + "/healthz"); break
        except Exception: time.sleep(0.2)
    pages = {r: get(base + r) for r in ("/", "/address/poa1" + "A" * 40, "/about", "/start", "/chain")}
    for r, (c, h, t) in pages.items():
        check(f"{r} ({c}): no Join dialog or trigger, app.js v89, Ask dialog still inline", c in (200, 404) and "joinmodal" not in t and "data-join" not in t
              and 'id="jm-prompt"' not in t and 'data-rname="jclient"' not in t and re.search(r'/static/app\.js\?v=[0-9a-f]{12}"', t) is not None and 'id="askmodal"' in t and 'id="toast"' in t
              and '<a class="joinbtn hdrjoin" href="/start">' in t)
    st = pages["/start"][2]; m = st[st.index("<main"):st.index("</main>")]
    check("/start: the three variant templates once, outside main, the full one is the canonical template",
          re.findall(r'<pre hidden data-variant="([^"]+)">', st) == ["full", "chat-browse", "connector"] and "data-variant" not in m
          and unescape(re.search(r'<pre hidden data-variant="full">(.*?)</pre>', st, re.S).group(1)) == OP.TEMPLATE)
    check("other pages carry no variant templates", all("data-variant" not in t for r, (c, h, t) in pages.items() if r != "/start"))
    nr = urllib.request.build_opener(urllib.request.ProxyHandler({}), type("NR", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *a, **k: None})())
    try: nr.open(base + "/fragment/join", timeout=30); c, loc = 200, ""
    except urllib.error.HTTPError as e: c, loc = e.code, e.headers.get("Location", "")
    check(f"/fragment/join ({c}) is a 301 to /start for old cached pages", c == 301 and loc == "/start")
    check(f"/start prompt hash line ({TS[:12]})", f'data-phash="{TS}"' in st)
    c, _, j = get(base + "/api/v1/prompts/join"); check("/api/v1/prompts/join template_sha256 unchanged", c == 200 and json.loads(j)["template_sha256"] == TS)
    check("robots.txt keeps /fragment/ out of crawls", "Disallow: /fragment/" in get(base + "/robots.txt")[2])
    BAD = re.compile(r"(live|paused),? (paused,? )?(or )?coming soon", re.I)
    for path in ("/llms.txt", "/llms-full.txt"):
        c, _, t = get(base + path)
        check(f"{path}: swap state written coming_soon, not 'coming soon'", c == 200 and not BAD.search(t) and "live, paused, coming_soon or unknown" in t)
    req = urllib.request.Request(base + "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(), {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    tl = json.loads(op.open(req, timeout=30).read())["result"]["tools"]
    d = [x["description"] for x in tl if x["name"] == "get_swap_status"][0]
    check("MCP get_swap_status: Whether swaps are live, paused, coming_soon or unknown", d.startswith("Whether swaps are live, paused, coming_soon or unknown") and not BAD.search(json.dumps(tl)))
    check("agent card skill names coming_soon", not BAD.search(get(base + "/.well-known/agent-card.json")[2]))
finally:
    srv.terminate()
    try: srv.wait(10)
    except Exception: srv.kill()
print("\n%d failure(s)" % len(fails) if fails else "\nall ok"); sys.exit(1 if fails else 0)
