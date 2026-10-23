"""Lazy Join dialog (1.26.54) and swap state names. Pages carry only the empty Join dialog shell (data-src /fragment/join);
app.js fetches the content once on the first hover, focus or open of a [data-join] trigger (or /#join), keeps it, and falls
back to /start when the load fails. The fragment is the same markup the pages used to inline, so the prompt text is byte
identical and template_sha256 stays the same. /start carries the three variant templates once, outside main. llms.txt,
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

TS = "990e681f0dada4bc9bf65c032c9e8f8b0d8b459c7fdd67276c16bde172ffd60f"
from poascan import onboarding_prompt as OP, start as S, swapflag as SF
check("join prompt template_sha256 unchanged (990e681f)", hashlib.sha256(S.prompt("YOUR_NAME", "full").encode()).hexdigest() == TS == S.template_sha256())
check("coming_soon is the swap status value in the code", "coming_soon" in SF.STATUSES)

js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("app.js: loads data-src once (in-flight promise kept), inits the dialog's cards, falls back to /start, prefetches on hover/focus/touch, opens on #join",
      "fetch(jm.dataset.src" in js and "JQ=fetch" in js and '$$("[data-go]",jm).forEach(goInit)' in js and 'location.href="/start"' in js
      and '["pointerover","focusin","touchstart"]' in js and 'W.location.hash==="#join"' in js and "function goInit(go)" in js and "go.dataset.goOn" in js)

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
    from poascan import join as J
    shell = '<dialog class="jm" id="joinmodal" data-pid="join" aria-labelledby="jm-t" data-src="/fragment/join"></dialog>'
    pages = {r: get(base + r) for r in ("/", "/address/poa1" + "A" * 40, "/about", "/start", "/epochs")}
    for r, (c, h, t) in pages.items():
        check(f"{r} ({c}): empty Join shell once, no inlined dialog content, app.js v54, Ask dialog still inline", c in (200, 404) and t.count(shell) == 1
              and 'id="jm-prompt"' not in t and 'data-rname="jclient"' not in t and "/static/app.js?v=54" in t and 'id="askmodal"' in t and 'id="toast"' in t)
    st = pages["/start"][2]; m = st[st.index("<main"):st.index("</main>")]
    check("/start: the three variant templates once, outside main, the full one is the canonical template",
          re.findall(r'<pre hidden data-variant="([^"]+)">', st) == ["full", "chat-browse", "connector"] and "data-variant" not in m
          and unescape(re.search(r'<pre hidden data-variant="full">(.*?)</pre>', st, re.S).group(1)) == OP.TEMPLATE)
    check("other pages carry no variant templates", all("data-variant" not in t for r, (c, h, t) in pages.items() if r != "/start"))
    c, h, f = get(base + "/fragment/join")
    check(f"/fragment/join ({c}): HTML, ETag, Cache-Control no-cache", c == 200 and h.get("Content-Type", "").startswith("text/html") and h.get("ETag") and h.get("Cache-Control") == "no-cache")
    c2, _, _ = get(base + "/fragment/join", {"If-None-Match": h.get("ETag", "")})
    check(f"/fragment/join revalidates with a 304 ({c2})", c2 == 304)
    norm = lambda s: re.sub(r"\bmp\d+\b", "mpN", s)
    full = J.modal_full(); inner = full[full.index(">") + 1:full.rindex("</dialog>")]
    check("fragment is the dialog markup pages used to inline, byte for byte (toggle ids aside)", norm(f) == norm(inner) and len(f) > 20000)
    jp = unescape(re.search(r'id="jm-prompt" tabindex="0">(.*?)</pre>', f, re.S).group(1))
    v0 = S.chats()[0][0]["variant"] or "full"   # the first client's variant, as the dialog always showed
    check(f"fragment prompt is byte identical to the served {v0} variant (YOUR_NAME slot) and its variant_sha256",
          jp == S.prompt("YOUR_NAME", v0) and hashlib.sha256(jp.encode()).hexdigest() == S.variant_sha256(v0))
    check("fragment variant templates are byte identical to VARIANTS", [unescape(x) for x in re.findall(r'<pre hidden data-variant="[^"]+">(.*?)</pre>', f, re.S)] == list(OP.VARIANTS.values()))
    jr = re.findall(r'<input type="radio" name="jclient" value="([^"]+)"', f)
    i_more = f.index("data-more")
    first = [v for v in jr if f.index(f'name="jclient" value="{v}"') < i_more]; more = [v for v in jr if f.index(f'name="jclient" value="{v}"') > i_more]
    check(f"button order: first row Claude, ChatGPT, Grok, Muse; Grok Bot first under More, Cursor under More ({first}, {more[:2]})",
          first == ["Claude", "ChatGPT", "Grok", "Muse"] and more[:2] == ["Grok Bot", "Cursor"])
    check("Muse can't-mine panel in the fragment", "data-nopath" in f and re.search(r'value="Muse" data-kind="none" data-tier="none"', f) is not None)
    check(f"prompt hash line in the fragment ({TS[:12]})", f'data-phash="{TS}"' in f)
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
