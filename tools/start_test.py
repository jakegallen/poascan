"""/start v2 and the shared onboarding prompt. Checks the three-step structure (name, one radio set of clients with the four
up front and the rest behind one More, one primary button, View prompt collapsed, one key line), the client wiring and
beacon ids, the frozen prompt (tools/start_prompt_fixture.txt) and GET /api/v1/prompts/join (blocks join back to the text,
strong ETag with a 304, cache and CORS headers, 400 on a bad name, no keys or codes, counted as an API route).
Usage: python3 tools/start_test.py"""
import hashlib, json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
from html import unescape
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "st.db"), POASCAN_MAINTENANCE="1", POA_BASE="http://127.0.0.1:9")
sys.path.insert(0, ROOT)
from poascan import db, start as S, onboarding_prompt as OP, join as J, prompts as PR, regcode as RC, visits as VS
db.init()
fails = []
def check(n, c): print(("ok   " if c else "FAIL ") + n); c or fails.append(n)

# ---- the template: one file, frozen wording
fx = open(os.path.join(ROOT, "tools", "start_prompt_fixture.txt")).read()
check("template: one {NAME} slot inside the register link, identical to the frozen v1 fixture", OP.TEMPLATE == fx and OP.TEMPLATE.count(OP.SLOT) == 1
      and "register?label=" + OP.SLOT in OP.TEMPLATE)
check("start.prompt() renders the template with the cleaned name; PROMPT, the Join modal and llms text use it",
      S.prompt("test-agent-7") == fx.replace("{NAME}", "test-agent-7") and S.PROMPT == fx.replace("{NAME}", "YOUR_NAME") and J.PROMPT == S.PROMPT
      and S.prompt("bad name!!") == fx.replace("{NAME}", "badname"))
check("registry step anchors still exist in the template", ("\n\n" + OP.REG_STEP["before"]) in OP.TEMPLATE and "step 6" in OP.REG_STEP["lead"]
      and RC.fill(S.prompt("a"), OP.REG_STEP["lead"], OP.REG_STEP["before"], "s_" + "a" * 16) != S.prompt("a"))
for nm in ("test-agent-7", "YOUR_NAME", "x" * 32):
    b = OP.blocks(S.prompt(nm))
    check(f"blocks for {nm[:12]}: join back to the full text, in order, ids unique", "".join(t for _, t in b) == S.prompt(nm) and [i for i, _ in b] == [i for i, _ in OP.BLOCKS] and all(t for _, t in b))
bl = dict(OP.blocks(S.prompt("n")))
check("blocks: registration has the link, key_safety the key rule, wallet Emblem Wallet; closing the payment rule",
      bl["registration"].startswith("Open this exact link") and "register?label=n" in bl["registration"] and bl["key_safety"].startswith("1. Key:")
      and "Emblem Wallet" in bl["wallet"] and "Never send payment outside the network." in bl["closing"])
d = S.api_join("test-agent-7")
check("api_join: version, updated_ts (UTC ISO), text == /start prompt, sha256, blocks", d["version"] == OP.VERSION and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", d["updated_ts"])
      and d["text"] == S.prompt("test-agent-7") and d["sha256"] == hashlib.sha256(d["text"].encode()).hexdigest() and "".join(x["text"] for x in d["blocks"]) == d["text"])
bad = []
for n in ("a b", "x" * 33, "<b>", "name;", "é"):
    try: S.api_join(n); bad.append(n)
    except ValueError: pass
check(f"api_join: bad names refused {bad}", not bad and S.api_join(None)["name"] == "YOUR_NAME")
check("api_join: no setup code, referral or key in the text", "{SETUP_CODE}" not in d["text"] and not re.search(r"\bs_[a-z2-7]{16}\b", d["text"]) and "invited_by" not in d["text"]
      and not re.search(r"(p?sk|pk)_[A-Za-z0-9_\-]{12,}", json.dumps(d)))

# ---- clients
top, rest = S.chats()
check("client order lives in one constant: Claude, ChatGPT, Grok Bot, Muse", S.TOP == ("Claude", "ChatGPT", "Grok Bot", "Muse") and [x[0] for x in top] == list(S.TOP))
check("every chat app is offered once; Cursor's prompt deeplink is under More", len(top) + len(rest) == len(J.APPS) + 1 and len({x[0] for x in top + rest}) == len(top) + len(rest)
      and ("Cursor", "auto", "https://cursor.com/link/prompt", "https://cursor.com/link/prompt?text=") in rest)
from urllib.parse import quote
check("Cursor deeplink stays under its 10,000 character limit with the longest name and the registry step",
      len(S.CURSOR[3] + quote(RC.fill(S.prompt("x" * 32), OP.REG_STEP["lead"], OP.REG_STEP["before"], "s_" + "a" * 16), safe="")) < 10000)
check("beacon ids used by /start are on the /ops/e allowlist", all(i in PR.ids() for i in ("start.app", "start.appreg", "start.copy", "start.copyreg", "start.regshow", "mcp-poa.add")))

# ---- the page, end to end
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close(); base = f"http://127.0.0.1:{port}"
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0"))
def req(u, h=None):
    try: r = urllib.request.urlopen(urllib.request.Request(base + u, headers=h or {}), timeout=30); return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read().decode()
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    c, _, h = req("/start"); m = h[h.index("<main"):h.index("</main>")]
    steps = re.findall(r'<li class="sts[^"]*"><span class="stn" aria-hidden="true">(\d)</span><div class="stb"><h2 class="stt" id="st\d">([^<]+)</h2>', m)
    check(f"/start: three numbered steps in order {steps}", c == 200 and steps == [("1", "Name your agent"), ("2", "Pick where it runs"), ("3", "Start mining")])
    check("/start: one visible h1, the name field labelled by step 1, Enter hint next", m.count("<h1") == 1 and "<h1>Start mining PoA</h1>" in m
          and 'id="stname"' in m and 'aria-labelledby="st1"' in m and 'enterkeyhint="next"' in m and "data-name" in m)
    i_more = m.index('class="morep')
    up = re.findall(r'<input type="radio" name="client" value="([^"]+)"', m[:i_more]); allr = re.findall(r'<input type="radio" name="client" value="([^"]+)"', m)
    check(f"/start: one radio group, Claude first and checked, four up front {up}", up == list(S.TOP) and m.count('role="radiogroup"') == 1
          and re.search(r'value="Claude" data-kind="auto"[^>]* checked>', m) and m.count(" checked>") == 1)
    check("/start: everything else behind the single More (other chats, 8 connectors, 7 commands)", m.count("data-more") == 1 and ">More<" in m
          and len(allr) == len(J.APPS) + 1 + 8 and m[i_more:].count('class="cmd"') == 7 and "Other clients" not in m and "One click" not in m)
    check("/start: one primary button, defaulting to the first client", len(re.findall(r"data-go[ >]", m)) == 1 and '<a class="gobtn" href="https://claude.ai/new" target="_blank" rel="noopener noreferrer" data-go data-kind="auto"><span data-golbl>Open Claude</span>' in m
          and 'data-gofb role="status" aria-live="polite"' in m)
    view = m[m.index('<details class="stview">'):]
    check("/start: the prompt sits collapsed behind View prompt, with its Copy, and is the template text", '<details class="stview"><summary>View prompt</summary>' in m
          and "<details class=\"stview\" open" not in m and m.count("data-copy-prompt") == 1 and m.index("data-go") < m.index("stview") < m.index("data-copy-prompt")
          and unescape(re.search(r'<pre class="pc-text jm-p" tabindex="0" data-reg="[^"]*" data-reg-at="[^"]*">(.*?)</pre>', view, re.S).group(1)).startswith("Open this exact link"))
    check("/start: one short key line, no red warning and no repeat outside the prompt", m.count(S.KEYLINE) == 1 and 'class="kwarn"' not in m
          and "Treat a leaked key" not in m and "Never paste your pk_" not in m)
    check("/start: live status strip with the Updated stamp and responding wording, never reopened", m.count('<p class="upstrip stup" role="status" data-live>') == 1
          and "<span data-upstamp>" in m and "<span data-upline>" in m and "reopened" not in m.lower())
    st = m[m.index('<details class="card stepsd">'):]
    check("/start: Emblem Wallet and the payment rule tucked in the collapsed All steps", "<details class=\"card stepsd\" open" not in m and "Install Emblem Wallet" in st
          and "Never send payment outside the network." in st and "Emblem Wallet" not in m[:m.index('class="stview"')].split('class="morep')[0])
    check("/start: setup-code flow kept (data-reg on the prompt), keys never asked", 'data-reg="' in view and "{SETUP_CODE}" in unescape(view) and "api_key" not in m[:m.index("stview")]
          and not any(x in m for x in ("\u2014", "Trac", "RESET", "intercom-dex", "Playbay", "invite code=", "Accounts")))
    js = open(os.path.join(ROOT, "static", "app.js")).read(); css = open(os.path.join(ROOT, "static", "style.css")).read()
    check("client: one button handler with the existing beacons; Enter on the name moves to step 2, Enter on a choice to the button",
          '[data-go]' in js and 'ev("start."+(rg?"appreg":"app"))' in js and 'ev("mcp-poa.add")' in js and 'e.key==="Enter"' in js and "go.focus()" in js and "r.focus()" in js)
    check("css: visible focus rings on choices, button, name and summaries", ".cl input:focus-visible+.clb{outline" in css and ".gobtn:focus-visible{outline" in css
          and ".stin:focus{" in css and ".stview>summary:focus-visible" in css)

    # ---- the endpoint
    u = "/api/v1/prompts/join?name=test-agent-7"
    c, hd, b = req(u); j = json.loads(b) if c == 200 else {}
    et = hd.get("ETag", "")
    check(f"GET {u}: 200 JSON, blocks join back, same text as /start renders", c == 200 and "".join(x["text"] for x in j["blocks"]) == j["text"] == S.prompt("test-agent-7"))
    check("headers: strong ETag (sha256 of the body), public max-age=600, CORS for GET", re.fullmatch(r'"[0-9a-f]{64}"', et) is not None and et.strip('"') == hashlib.sha256(b.encode()).hexdigest()
          and hd.get("Cache-Control") == "public, max-age=600" and hd.get("Access-Control-Allow-Origin") == "*" and "GET" in hd.get("Access-Control-Allow-Methods", ""))
    c2, h2, b2 = req(u, {"If-None-Match": et}); c3, _, _ = req("/api/prompts/join?name=test-agent-7", {"If-None-Match": et})
    check(f"If-None-Match: 304 with no body ({c2}), alias path too ({c3})", c2 == 304 and b2 == "" and h2.get("ETag") == et and c3 == 304)
    c4, _, b4 = req("/api/v1/prompts/join"); 
    check("no name: YOUR_NAME, like llms.txt", c4 == 200 and json.loads(b4)["name"] == "YOUR_NAME" and json.loads(b4)["text"] == S.PROMPT)
    codes = [req("/api/v1/prompts/join?" + q)[0] for q in ("name=a%20b", "name=" + "x" * 33, "name=%3Cb%3E", "name=a&name=b", "name=%C3%A9")]
    check(f"bad names: 400 {codes}", codes == [400] * 5)
    import poascan.agentapi as AG; VS.API_SRC = lambda: AG.openapi()["paths"]; VS._API[0] = None
    check("counted as its own API route (OpenAPI path), docs and llms list it, not an MCP tool",
          VS.api_route("/api/v1/prompts/join") == "/api/v1/prompts/join" and "/api/v1/prompts/join" in req("/openapi.json")[2] and "/prompts/join" in req("/llms.txt")[2]
          and "/api/v1/prompts/join" in req("/api")[2] and "prompts/join" not in json.dumps(AG.TOOLS, default=str))
finally:
    p.terminate(); p.wait(10)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
