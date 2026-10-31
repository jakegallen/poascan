"""Join with Anything on /start (1.26.238, lanes 1.26.240, v1.0 handoff 1.26.243). The connector is never a way to join.
Hosted chat apps: 1 Create your agent on minepoa.com (its page solves the join puzzle; POAScan only links, keyless), 2 Let {App}
mine (optional, mining after you join), 3 Paste the prompt. Code apps (Grok Bot, Cursor, Codex): 1 Copy prompt only, 2 the
connector (Codex: its run-once command lives here). Not tested yet per the v1.0 coverage (desktop and phone). While
/api/join-pow answers 503: the notice under step 1, every copy or join button off (server and client), back on when POAScan's
own read turns open. No key in any URL or query in the prompts, prefills or /start; no leak-term links. Usage: python3 tools/connector_first_test.py"""
import os, re, sys, tempfile
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "c.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, start as S
from html import unescape
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
from poascan import maint as M, join as J
M.join_halt = lambda: None
top, rest = S.chats(); by = {c["id"]: c for c in top + rest}
gpt = by["chatgpt"]; h = unescape(S.go_block(gpt)); hr = S.go_block(gpt)
pos = lambda x, t=h: t.index(x)
check("ChatGPT (hosted): steps 1, 2, 3 in order, the button in step 3", pos("1. Create your agent") < pos("2. Let ChatGPT mine (optional)") < pos("3. Paste the prompt") < pos("data-slot3") < pos("data-go ")
      and '<div class="jwslot" data-slot1></div>' in h)
check("step 1: the exact line (join puzzle) and Join on minepoa.com, new tab, no query", S.S1_HOSTED in h and S.S1_HOSTED == "Open minepoa.com and complete the signup there. Your browser solves the join puzzle, and minepoa creates your agent. POAScan never sees your key."
      and '<a class="jwbtn" href="https://minepoa.com/" target="_blank" rel="noopener noreferrer" data-mpjoin>Join on minepoa.com</a>' in h and "signup puzzle" not in h)
check("step 2 heading: (mining after you join, not joining)", '<span data-s2h>2. Let ChatGPT mine (optional)</span> <span class="jwl">(mining after you join, not joining)</span>' in h and S.S2_LABEL == "(mining after you join, not joining)")
check("step 2: for mining after you join, not for joining; the URL with copy; where; turn on; exactly one ChatGPT paid-plan note",
      "Add the PoA connector so ChatGPT can answer challenges and check in for the agent you created. For mining after you join, not for joining." in h
      and '<code data-cfval>https://minepoa.com/mcp</code><button class="cp" type="button" data-copy="https://minepoa.com/mcp" data-cfcopy' in h
      and f'Add it in ChatGPT: </span><span data-cfwhere>{gpt["connector"]["where"]}</span>' in h and "<li>Turn it on for the chat.</li>" in h
      and h.count("Needs a paid ChatGPT plan") == 1 and '<p class="cfn" data-cfnote>Needs a paid ChatGPT plan with developer mode turned on.</p>' in h and "Open ChatGPT settings" in h)
check("the connector is never a way to join: no fallback paste line, no Add the connector first", "Can't add connectors" not in h and "Add the connector first" not in h and "data-cffb" not in hr)
cx = unescape(S.go_block(by["codex"]))
check("Codex (code app, full prompt): step 1 the prompt line, the allow network note and Copy prompt only; no connector step, no command (1.26.245)",
      by["codex"]["tier"] == "full" and not by["codex"].get("connector") and S.s1_code("Codex") in cx
      and pos("1. Create your agent", cx) < pos("Allow network access in Codex first. Its default sandbox blocks web requests.", cx) < pos("data-slot1>", cx) < pos("data-go ", cx)
      and " data-cfirst hidden" in cx and not any(x in cx for x in ("npx", "npm ", "mcp add", "Run this once", "emblem", "Emblem"))
      and " data-s1join hidden" in cx and " data-s3h hidden" in cx and '<div class="jwslot" data-slot3></div>' in cx)
check("regroup: Runs code (Grok Bot, Claude Code, Cursor, Codex), Chat with connector (Claude, ChatGPT, Grok, Perplexity, Le Chat), Not supported behind one toggle",
      [x["id"] for x in top + rest if x["tier"] == "full"] == ["grok-bot", "claude-code", "cursor", "codex"]
      and [x["id"] for x in top + rest if x["tier"] == "connector"] == ["claude", "chatgpt", "grok", "perplexity", "le-chat"]
      and {"muse", "gemini", "huggingchat"} <= {x["id"] for x in rest if x["tier"] == "none"}
      and pos('data-group="full">Runs code', S.clients()) < pos('data-group="connector">Chat with connector', S.clients()) < pos("Not supported<i", S.clients()))
check("code apps never get a connector step or command; no connector install rows on /start",
      all(" data-cfirst hidden" in S.go_block(c) for c in top + rest if c["tier"] == "full") and all(x not in S.clients() for x in ("mcp add", "data-mcp=", 'value="mcp:')))
check("chat apps: the key warning sits in step 2, right under its line", all(pos("data-s2b", g) < pos(S.KEY_WARN, g) < pos("data-cflines", g) for g in (S.go_block(c) for c in top if c["tier"] == "connector"))
      and S.KEY_WARN == "Your key is sent through this chat app on every call. Use a fresh Agent just for mining, with no other funds, and move earnings to a wallet you control.")
check("Claude: Add opens Claude's documented prefill (name Proof of Agent, minepoa's /mcp URL), no key or referral; the plain URL and copy stay as the fallback",
      by["claude"]["connector"]["settings_url"] == "https://claude.ai/customize/connectors?modal=add-custom-connector&connectorName=Proof%20of%20Agent&connectorUrl=https%3A%2F%2Fminepoa.com%2Fmcp"
      and 'href="https://claude.ai/customize/connectors?modal=add-custom-connector&amp;connectorName=Proof%20of%20Agent&amp;connectorUrl=https%3A%2F%2Fminepoa.com%2Fmcp"' in S.go_block(by["claude"])
      and '<code data-cfval>https://minepoa.com/mcp</code><button class="cp" type="button" data-copy="https://minepoa.com/mcp" data-cfcopy' in S.go_block(by["claude"]))
check("code apps: no run-once command in step 1 for any app", all("mcp add" not in (lambda g: g[:g.index("data-cfirst")])(unescape(S.go_block(c))) for c in top + rest))
check("tested per v1.0 coverage: desktop Claude, ChatGPT, Grok, Grok Bot, Voice; phone Claude, ChatGPT, Voice",
      S.TESTED == {"claude", "chatgpt", "grok", "grok-bot", "voice"} and S.TESTED_PHONE == {"claude", "chatgpt", "voice"})
g = S.go_block(by["cursor"])
check("cursor: step 1 with the button and Not tested yet, no connector step", S.s1_code("Cursor") in g and " data-cfirst hidden" in g
      and '<p class="stnt" data-untested><span class="tag">Not tested yet</span><span>Uses the default prompt.</span></p>' in g and pos("data-slot1>", g) < pos("data-go ", g))
g = S.go_block(by["grok-bot"])
check("grok-bot: step 1 with the button, tested (no note), no connector step", S.s1_code("Grok Bot") in g and " data-cfirst hidden" in g and " data-untested hidden" in g)
check("tested apps: no Not tested yet note", " data-untested hidden" in hr and " data-untested hidden" in S.go_block(by["claude"]))
check("Muse (no prompt): no steps, no note", " data-untested hidden" in S.go_block(by["muse"]) and " data-s1h hidden" in S.go_block(by["muse"]))
check("radios carry tested (desktop), tphone (phone) and the note for app.js", ' data-tested="1"' in S._chat(gpt) and ' data-tphone="1"' in S._chat(gpt)
      and ' data-tested="1"' in S._chat(by["grok-bot"]) and ' data-tphone' not in S._chat(by["grok-bot"]) and ' data-tested' not in S._chat(by["cursor"]) and 'data-cnote="Needs a paid ChatGPT plan' in S._chat(gpt))
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("app.js mirrors the lanes: the same lines, the button moves to its slot, the command builds in step 2", S.S1_HOSTED in js and "This is the step that creates your PoA agent." in js
      and "For mining after you join, not for joining." in js and "The connector does not create a new agent." in js and "var slot=h?sl3:sl1" in js and "cffb" not in js and "data-s1cli" not in js)
check("app.js: no minepoa polling; while paused it reads only POAScan's own /api/v1/prompts/join, every 5 min, when visible",
      "minepoa.com/api" not in js[js.index("function PZ"):js.index("function PZ") + 1500] and '"/api/v1/prompts/join"' in js and "},300000)" in js and "D.hidden" in js)

# no key in any URL or query: every prompt variant for every app, every prefill and open link, the rendered /start
URLQ = re.compile(r"https?://[^\s\"'<>)]+")
KQ = re.compile(r"[?&#](?:[a-z_]*key|token|api_key|secret|pk)=", re.I)
texts = {v: S.prompt("test-agent-7", v) for v in ("full", "connector")}
bad = {v: [u for u in URLQ.findall(t) if KQ.search(u) or "YOUR_KEY" in u or "SAVED_KEY" in u] for v, t in texts.items()}
check(f"no key in any URL or query in either prompt variant {bad}", not any(bad.values()) and all(not KQ.search(t) for t in texts.values()))
leak = [c["id"] for c in top + rest for u in (c.get("open") or "", c.get("prefill") or "", (c.get("connector") or {}).get("open") or "") if KQ.search(u) or "KEY" in u]
check(f"no key in any app's open or prefill link {leak}", not leak)
from poascan import combined as CB
ct = open(os.path.join(ROOT, "poascan", "combined_prompt.txt"), encoding="utf-8").read()
check("no key in any URL in the combined prompt", not any(KQ.search(u) or "KEY" in u for u in URLQ.findall(ct)))
pagehtml = unescape(S.go_block(gpt) + "".join(S.go_block(c) for c in top + rest))
check("no key in any link or prefill on /start", not KQ.search(pagehtml) and not re.search(r"(href|data-copy|data-prefill)=\"[^\"]*(key|token)=", pagehtml))
LEAK = ("lableak", "grading-guide", "grading guide")
check("no link whose path holds a leak term, in the prompts and the /start steps", not any(x in (t + pagehtml).lower() for t in texts.values() for x in LEAK)
      and not any(v and any(x in v.lower() for x in LEAK) for _, v, _n in S.STEPS))
check("the prompt never lets the agent show the key: header only, stop on a URL credential", all("X-Api-Key" in t or "poa_" in t for t in texts.values())
      and "Never put a key or token in a URL" in texts["full"] and "never show it in this chat" in texts["full"] and "direct reply" not in texts["full"] + texts["connector"])

# 1.26.244: every served prompt, Ask prompt and llms text, sitewide: no key or token in any URL or query, no grading guide link
from poascan import prompts as PR, agentapi as AG
from poascan.swap import prompts as SP
CRED = re.compile(r"[?&#](?:[a-z_]*key|token|guid|secret|pk)=", re.I)
_a = "poa1" + "x" * 40
asks = {t: PR.opened(b) for t, b in [v for v in vars(PR).values() if isinstance(v, tuple) and len(v) == 2 and all(isinstance(x, str) for x in v)]
        + [PR.answer_epoch(), PR.answer_epoch(1), PR.explain_epoch(1), PR.addr_rewards(_a), PR.addr_send(_a), PR.addr_invites(_a), PR.explain_tx("0" * 64), PR.swap_status("0" * 64)]}
served = dict(asks, **{"llms.txt": AG.llms_txt(), "llms-full.txt": AG.llms_full_txt(), "JOIN_MD": AG.JOIN_MD, "ask dialog": unescape(J.ask_modal()), "wallet": SP.WALLET_PROMPT,
              "combined": ct, "full": texts["full"], "connector": texts["connector"]})
served.update({f"swap {k}": v for k, v in (SP.templates().items() if isinstance(SP.templates(), dict) else enumerate(SP.templates())) if isinstance(v, str)})
badq = {k: CRED.findall(v) for k, v in served.items() if CRED.search(v)}
check(f"no key, token or guid in any URL or query in {len(served)} served texts (every Ask prompt, llms.txt, llms-full.txt, join, combined, wallet, swap) {badq}", not badq and len(asks) >= 20)
badw = [k for k, v in served.items() if "lableak/#/a/work" in v or re.search(r"[?&](key|token)=(SAVED_KEY|YOUR_KEY|MY_)", v)]
check(f"no grading guide link and no key placeholder in a link in any served text {badw}", not badw)
keyed = [t for t, v in asks.items() if "SAVED_KEY" in v]
check("every Ask prompt that uses the key says header only and stops on a 401 or 403 or a URL credential",
      keyed and all("only in an X-Api-Key header" in asks[t] and "401 or 403" in asks[t] and "show it in this chat" in asks[t] for t in keyed))
check("v2.9.4: the key error line once in both join variants", all(t.count(__import__("poascan.onboarding_prompt", fromlist=["x"]).AUTH_FIX) == 1 for t in texts.values())
      and "401 or 403 saying the key is missing or invalid" in ct)

P = "New PoA signups are paused. Check back later. Existing balances and pending grades are safe."
check("open (200): no paused notice, no button off, on /start or in the Ask dialog", S.join_halt_html() == "" and "data-joinhalt" not in h and "data-pzoff" not in h + cx and "data-joinhalt" not in J.ask_modal())
M.join_halt = lambda: dict(since_ts=1793000000, as_of_ts=1793000300)
ph = unescape(S.go_block(gpt))
check("halted (503): the exact notice right under the step 1 heading, step 1 says Signups are paused", S.PAUSED == P and P in ph and pos("data-s1h", ph) < pos(P, ph) < pos("data-mpjoin", ph)
      and " data-s1b hidden" in ph and '<p class="jwb jwpz" data-s1paused>Signups are paused. Check back later.</p>' in ph and "while minepoa hardens" not in ph)
OFF = ' off" aria-disabled="true" tabindex="-1" data-pzoff href='
check("halted (503): Join on minepoa.com and Copy and open are disabled, with the note beside them", ('<a class="jwbtn' + OFF) in ph and ('<a class="gobtn' + OFF) in ph
      and f'<p class="jwoff" data-pauseoff>{S.PAUSED_OFF}</p>' in ph and S.PAUSED_OFF == "Signups are paused. Check back later. Copy and open and Copy prompt are off until joins open again.")
pc = unescape(S.go_block(by["codex"]))
check("halted: code apps, Copy prompt disabled, notice under step 1, mining command untouched", ('<a class="gobtn' + OFF) in pc and pos("data-s1h", pc) < pos(P, pc) < pos("data-go ", pc) < pos("data-cfirst", pc)
      and "data-pzoff" not in pc[pc.index("data-s2cmd"):pc.index("data-cflines")])
pm = unescape(S.go_block(by["muse"]))
check("halted: the not supported panel has no join link (it points to apps that run code)", "npj" not in pm and "data-npjoin" not in pm)
check("halted: the notice in the Ask dialog too", P in unescape(J.ask_modal()))
hf = S.hash_fields()
check("the prompt is v2.9.4: template 438bec61, combined a7210d16", hf["template_sha256"].startswith("438bec61") and hf["combined_sha256"].startswith("a7210d16"))
check("no em or en dash", not re.search("[\u2013\u2014]", h + cx + ph + pc + js[js.index("1.26.240"):js.index("1.26.240") + 3000] + js[js.index("function PZ"):js.index("function PZ") + 1500]))

# 1.26.241: server render for every app (the default Claude included): nothing for a lane that does not apply
M.join_halt = lambda: None
EMPTY = re.compile(r"<code[^>]*>\s*</code>")
for c in top + rest:
    g = unescape(S.go_block(c)); cli = bool((c.get("connector") or {}).get("cli")); un = c["id"] not in S.TESTED and c["kind"] != "none"
    check(f"server {c['id']}: run-once block {'in step 2' if cli else 'absent'}, Not tested yet {'shown' if un else 'absent'}, no empty code span",
          ("Run this once" in g) == cli and (not cli or g.index("Run this once") > g.index("data-cfirst")) and ("Not tested yet" in g) == un and not EMPTY.search(g))
check("server: Claude is the default and shows neither", S.default_client()["id"] == "claude" and not any(x in unescape(S.go_block(S.default_client())) for x in ("Run this once", "Not tested yet")))

# client side (1.26.246 flow): name, Next, the picker, each card, at 390 and 1280
def location_hash(pg): return pg.evaluate("location.hash")
import socket, subprocess, time, urllib.request
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
    check("playwright installed for the client-side check (CI installs it before this step)", os.environ.get("CI") != "true")
if sync_playwright:
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close(); base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1")
    srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(150):
            try: urllib.request.urlopen(base + "/healthz", timeout=2); break
            except Exception: time.sleep(0.2)
        urls = ["/", "/start", "/help", "/about", "/upgrade", "/earn", "/network", "/swap", "/wallet", "/llms.txt", "/llms-full.txt", "/api/v1/prompts/join", "/api/v1/prompts/combined"]
        try: urls += [u.replace("https://poascan.io", "") for u in re.findall(r"<loc>([^<]+)</loc>", urllib.request.urlopen(base + "/sitemap.xml", timeout=20).read().decode())]
        except Exception: pass
        hits = {}
        for u in dict.fromkeys(urls):
            try: body = unescape(urllib.request.urlopen(base + u, timeout=30).read().decode("utf-8", "replace"))
            except Exception: continue
            f = [m for m in CRED.findall(body)] + (["a/work"] if "lableak/#/a/work" in body else [])
            if f: hits[u] = f
        check(f"served pages ({len(set(urls))}, sitemap included): no key, token or guid in any URL or query, no grading guide link {hits}", not hits and len(set(urls)) >= 13)
        # 1.26.246: the client side of the new /start: name, Next, the picker (Claude preselected), each app's card
        apps = [c for c in top + rest if c["kind"] != "none"]
        HOOK = ("window.__opened=0;window.open=function(){window.__opened++;return null};window.__c='';"
                "document.addEventListener('copy',function(){var a=document.activeElement;window.__c=(a&&a.value)?a.value.substring(a.selectionStart,a.selectionEnd):String(document.getSelection())},true)")
        with sync_playwright() as p:
            b = p.chromium.launch()
            for w in (390, 1280):
                ctx = b.new_context(viewport={"width": w, "height": 844 if w < 400 else 900})
                ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base) else r.abort()); ctx.add_init_script(HOOK)
                pg = ctx.new_page(); pg.goto(base + "/start", wait_until="networkidle")
                vis = lambda sel: pg.evaluate(f"()=>{{const e=document.querySelector('{sel}');return !!e&&!!(e.offsetWidth||e.offsetHeight)}}")
                nm = pg.input_value("[data-sv-n0]")
                check(f"{w}px: the name step shows first, prefilled {nm}; the picker is hidden", vis("[data-sv-name0]") and not vis("[data-sv-pick]") and re.fullmatch(r"[a-z]+-[a-z]+-\d{3}", nm))
                pg.click("[data-sv-next]"); pg.wait_for_timeout(300)
                check(f"{w}px: one tap on Next shows the picker, Claude preselected, Continue with Claude", vis("[data-sv-pick]") and not vis("[data-sv-name0]")
                      and pg.evaluate("()=>[...document.querySelectorAll('.sv-t.sel')].map(e=>e.dataset.app)") == ["claude"] and vis(".sv-go") and location_hash(pg) == "#apps")
                for c in apps:
                    pg.click(f'.sv-grid [data-app="{c["id"]}"]'); pg.wait_for_timeout(250)
                    d = pg.evaluate("""()=>{const b=document.querySelector('[data-sv-body]'),t=b.innerText.toLowerCase(),v=e=>!!e&&!!(e.offsetWidth||e.offsetHeight);
                        return {copied:window.__c.length,btns:[...b.querySelectorAll('.sv-btn')].filter(v).map(e=>e.innerText.trim()),warn:v(b.querySelector('.sv-warn'))?b.querySelector('.sv-warn').innerText:'',
                                url:(b.querySelector('.sv-url code')||{}).textContent||'',note:[...b.querySelectorAll('.sv-note')].map(e=>e.innerText).join('|'),mcp:t.includes('mcp add')||t.includes('run this once'),
                                empty:[...b.querySelectorAll('code')].filter(e=>v(e)&&!e.textContent.trim()).length,head:document.querySelector('[data-sv-app]').textContent,hash:location.hash}}""")
                    if c["tier"] == "full":
                        good = (d["copied"] == 0 and d["btns"] == ["Copy prompt"] + (["Open " + c["name"]] if c["open"] else []) and not d["warn"] and not d["mcp"]
                                and d["note"] == (c.get("note") or "") and d["head"] == c["name"] and d["hash"] == "#" + c["id"])
                    else:
                        co = c.get("connector") or {}
                        good = (d["copied"] == 0 and d["btns"][0] == "Join on minepoa.com" and (("Add to " + c["name"]) in d["btns"]) == bool(co.get("prefills_url"))
                                and d["btns"][-1] in ("Copy prompt", "Copy and open " + c["name"]) and d["warn"] == S.KEY_WARN and d["url"] == "https://minepoa.com/mcp"
                                and not d["mcp"] and d["empty"] == 0 and ("Needs a paid ChatGPT plan" in d["note"]) == (c["id"] == "chatgpt"))
                    check(f"{w}px {c['id']}: the tap opens its card and copies nothing; {'Copy prompt' + (' and Open' if c['open'] else '') if c['tier'] == 'full' else 'join, connector with the warning, paste'} {d}", good)
                    if c["tier"] == "full":
                        pg.click('[data-sv-body] .sv-btn >> nth=0'); pg.wait_for_timeout(150)
                        cp = pg.evaluate("window.__c"); pg.evaluate("window.__c=''")
                        check(f"{w}px {c['id']}: Copy prompt copies the full prompt with the name", cp == S.prompt(nm) and "{NAME}" not in cp and "YOUR_NAME" not in cp)
                    pg.click("[data-sv-panel] [data-sv-back]"); pg.wait_for_timeout(250)
                    if not vis("[data-sv-pick]"): check(f"{w}px {c['id']}: Back returns to the picker", False)
                pg.click(".sv-other summary"); pg.click('.sv-o[data-app="muse"]'); pg.wait_for_timeout(250)
                ns = pg.evaluate("()=>({t:document.querySelector('.sv-no').innerText,a:[...document.querySelectorAll('.sv-alts [data-app]')].map(e=>e.dataset.app),f:!!document.querySelector('[data-sv-foot]').offsetParent})")
                check(f"{w}px not supported: one line and the three apps that can, no prompt footer {ns}", ns["t"] == "Muse can't run an Agent yet. Use one of these:" and ns["a"] == ["claude-code", "cursor", "grok-bot"] and not ns["f"])
                pg.click('.sv-alts [data-app="cursor"]'); pg.wait_for_timeout(250)
                check(f"{w}px not supported: a redirect tile opens that app's card", pg.inner_text("[data-sv-app]") == "Cursor")
                pg.keyboard.press("Escape"); pg.wait_for_timeout(250); h1 = location_hash(pg)
                pg.keyboard.press("Escape"); pg.wait_for_timeout(250); h2 = location_hash(pg)
                check(f"{w}px: Escape goes back one level at a time ({h1}, {h2})", h1 == "#muse" and h2 == "#apps" and vis("[data-sv-pick]") and not vis("[data-sv-panel]"))
                pg.goto(base + "/start#claude", wait_until="networkidle"); pg.wait_for_timeout(250)
                check(f"{w}px: /start#claude opens Claude's strip directly", pg.inner_text("[data-sv-app]") == "Claude" and vis(".sv-tml"))
                pg.goto(base + "/start", wait_until="networkidle"); pg.fill("[data-sv-n0]", "bad name"); pg.click("[data-sv-next]"); pg.wait_for_timeout(200)
                check(f"{w}px: a bad name stays on step 1 with one line", vis("[data-sv-name0]") and pg.inner_text("[data-sv-err0]") == "Letters, numbers, _ or - only.")
                ctx.close()
            # paused (503): nothing copies or opens; POAScan's own read turning open re-enables the card, no reload
            db2 = os.path.join(tempfile.mkdtemp(), "p.db"); e2 = dict(env, POASCAN_DB=db2)
            subprocess.run([sys.executable, "-c", "import time;from poascan import db,routewatch as RW;db.init();n=int(time.time());"
                            "db.write('INSERT OR REPLACE INTO fetch_log(endpoint, last_ok, last_err, err, fails) VALUES(?,?,?,?,?)',('/api/join-pow',n-600,n-60,'HTTP 503 halted',1));RW.job(n)"], cwd=ROOT, env=e2, check=True)
            sk = socket.socket(); sk.bind(("127.0.0.1", 0)); p2 = sk.getsockname()[1]; sk.close(); base2 = f"http://127.0.0.1:{p2}"
            srv2 = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=dict(e2, PORT=str(p2)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(150):
                try: urllib.request.urlopen(base2 + "/healthz", timeout=2); break
                except Exception: time.sleep(0.2)
            ctx = b.new_context(viewport={"width": 390, "height": 844}); ctx.add_init_script(HOOK); pg = ctx.new_page(); pg.clock.install()
            pg.goto(base2 + "/start#claude-code", wait_until="networkidle")
            offs = lambda: pg.evaluate("()=>[...document.querySelectorAll('[data-sv-body] .sv-btn')].map(e=>e.getAttribute('aria-disabled'))")
            o1 = offs(); pg.locator("[data-sv-body] .sv-btn").first.dispatch_event("click")
            pg.goto(base2 + "/start#claude", wait_until="networkidle"); o2 = offs()
            for i in range(len(o2)): pg.locator("[data-sv-body] .sv-btn").nth(i).dispatch_event("click")
            st = pg.evaluate("()=>({o:window.__opened,c:window.__c,halt:!!document.querySelector('[data-sv] .sthalt'),u:location.href})")
            check(f"client paused: every Copy, Open, Join and Add is off; clicks copy and open nothing; the notice shows {o1} {o2} {st}", o1 and o2 and all(x == "true" for x in o1 + o2)
                  and st["o"] == 0 and not st["c"] and st["halt"])
            pg.route("**/api/v1/prompts/join*", lambda r: r.fulfill(status=200, content_type="application/json", body='{"join":{"state":{"state":"open"}}}'))
            pg.clock.run_for(301000); pg.wait_for_timeout(300)
            st = pg.evaluate("()=>({off:document.querySelectorAll('.sv-btn.off,[aria-disabled=true]').length,halt:!!document.querySelector('[data-sv] .sthalt'),p:document.querySelector('[data-sv]').dataset.paused||''})")
            check(f"client: when POAScan reads joins open again, the card renders with every button on and the notice gone {st}", st["off"] == 0 and not st["halt"] and not st["p"])
            ctx.close(); srv2.terminate(); srv2.wait(10)
            b.close()
    finally:
        srv.terminate(); srv.wait(10)
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
