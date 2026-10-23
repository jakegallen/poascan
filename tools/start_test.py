"""/start v2 and the shared onboarding prompt. Checks the three-step structure (name, one radio set of clients with the four
up front and the rest behind one More, one primary button, View prompt collapsed, one key line), the client wiring and
beacon ids, the frozen prompt (tools/start_prompt_fixture.txt) and GET /api/v1/prompts/join (blocks join back to the text,
strong ETag with a 304, cache and CORS headers, 400 on a bad name, no keys or codes, counted as an API route) and
GET /api/v1/agents/name-available (taken, case variants, free, invalid, no upstream read, the name never logged).
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
check("v2: version and wording; no wallet or swap setup, no setup code path (REG_STEP and reg_attrs gone)", OP.VERSION == "v2.1" and "go.md LINK" not in OP.TEMPLATE and "following the swap steps in https://minepoa.com/go.md." in OP.TEMPLATE
      and "Use an Authorization header only if a test call with it actually succeeds." in OP.TEMPLATE and "retry that call once with key= as shown" in OP.TEMPLATE
      and "skill.md" not in OP.TEMPLATE and "MCP connector" not in OP.TEMPLATE and not hasattr(OP, "REG_STEP")
      and not hasattr(S, "reg_attrs") and "{SETUP_CODE}" not in OP.TEMPLATE and "emblem" not in OP.TEMPLATE.lower() and "npm install" not in OP.TEMPLATE
      and "poaswap" not in OP.TEMPLATE.lower() and "guid=" not in OP.TEMPLATE)
check("v2 key rule: never shown, confirmed only as the last 4 characters plus the store; never sent to POAScan; no em or en dashes",
      "Never show it." in OP.TEMPLATE and "Confirm it to me only as the last 4 characters plus the store's name." in OP.TEMPLATE
      and "never send it to POAScan" in OP.TEMPLATE and "curl -K -" in OP.TEMPLATE and not any(c in OP.TEMPLATE for c in "\u2014\u2013")
      and "https://poascan.io/address/YOUR_POA1_ADDRESS" in OP.TEMPLATE and "reopened" not in OP.TEMPLATE.lower())
for nm in ("test-agent-7", "YOUR_NAME", "x" * 32):
    b = OP.blocks(S.prompt(nm))
    check(f"blocks for {nm[:12]}: join back to the full text, in order, ids unique", "".join(t for _, t in b) == S.prompt(nm) and [i for i, _ in b] == [i for i, _ in OP.BLOCKS] and all(t for _, t in b))
bl = dict(OP.blocks(S.prompt("n")))
check("blocks: registration has the link, key_safety rules 1 to 5, mining steps 7 to 9, expectations; no wallet block; closing the payment rule",
      bl["registration"].startswith("Join Proof of Agent for me") and "register?label=n" in bl["registration"] and bl["key_safety"].startswith("Your key (the api_key")
      and all(f"\n{i}. " in "\n" + bl["key_safety"] for i in range(1, 6)) and bl["mining"].startswith("7. Get your challenge") and "9. Mine:" in bl["mining"]
      and bl["expectations"].startswith("The network is coming back") and "wallet" not in bl and "Never send payment outside the network." in bl["closing"]
      and list(bl) == ["registration", "about", "joining", "key_safety", "steps_intro", "grading", "mining", "check_in", "expectations", "receipts", "closing", "follow"])
NE = [("", "Name your agent to continue."), ("ok-name_1", ""), ("x" * 32, ""), ("x" * 33, "Too long: up to 32 characters."),
      ("a@b c", "Not allowed: @ and space. Use letters, numbers, _ or - (up to 32)."), ("a@b c!@", "Not allowed: @, space and !. Use letters, numbers, _ or - (up to 32)."),
      ("é", "Not allowed: é. Use letters, numbers, _ or - (up to 32)."), ("a b" + "x" * 40, "Not allowed: space. Use letters, numbers, _ or - (up to 32)."),
      ("bad.name", "Not allowed: period. Use letters, numbers, _ or - (up to 32)."), ("a.b c", "Not allowed: period and space. Use letters, numbers, _ or - (up to 32).")]
check("no message ever shows two dots in a row", all(".." not in S.name_error(v) for v in ("bad.name", ".", "a..b", "x.y z@", "." * 40)))
check("name messages (Python mirror of app.js): " + "; ".join(S.name_error(v) or "ok" for v, _ in NE[:5]), all(S.name_error(v) == w for v, w in NE))
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
check("client order lives in one constant: Claude, ChatGPT, Grok, Muse; Grok Bot first under More", S.TOP == ("Claude", "ChatGPT", "Grok", "Muse") and [x[0] for x in top] == list(S.TOP)
      and S.MORE_FIRST == ("Grok Bot",) and rest[0][0] == "Grok Bot" and [x[0] for x in rest[1:4]] == ["Perplexity", "Kimi", "Z.ai"])
check("every chat app is offered once; Cursor's prompt deeplink is under More", len(top) + len(rest) == len(J.APPS) + 1 and len({x[0] for x in top + rest}) == len(top) + len(rest)
      and ("Cursor", "auto", "https://cursor.com/link/prompt", "https://cursor.com/link/prompt?text=") in rest)
from urllib.parse import quote
check("Cursor deeplink stays under its 10,000 character limit with the longest name", len(S.CURSOR[3] + quote(S.prompt("x" * 32), safe="")) < 10000)
check("every prefill URL fits its limit with the longest name, so no client falls back to copy only", all(S.fits(n, p) for n, k, b, p in top + rest if p)
      and [x[:2] for x in top + rest] == [(n, k) for n, k, b, p in top + rest] and dict((x[0], x[1]) for x in top + rest)["Claude"] == "auto")
_old = S.URL_MAX; S.URL_MAX = 100; t2, r2 = S.chats(); S.URL_MAX = _old
check("a prefill URL over the limit falls back to copy and open (paste kind, no prefill), Cursor keeps its own limit",
      dict((x[0], x[1:]) for x in t2)["Claude"] == ("paste", "https://claude.ai/new", "") and dict((x[0], x[1]) for x in r2)["Cursor"] == "auto")
import poascan.join as _J
check("Coding agents one-liner carries key rules 1 to 4 in short form, no double quotes", all(x in _J.LINE for x in ("OS secret store", "never show it", "last 4 characters",
      "never put it on a command line", "send it only to minepoa.com, never to POAScan")) and '"' not in _J.LINE and "$" not in _J.LINE)
check("beacon ids used by /start are on the /ops/e allowlist", all(i in PR.ids() for i in ("start.app", "start.appreg", "start.copy", "start.copyreg", "start.regshow", "mcp-poa.add")))

# ---- the join modal banner: live state only, never 'reopened'
from poascan import maint as M, hosted as HR
_sv = (M._feed_fresh, M.join_state, M.hosted_state, HR.state)
def banner(fresh=True, join="open", hosted="paused", grading="closed", mining="open", joins=True, answers=True):
    now = int(time.time())
    with db.conn() as cx:
        cx.execute("DELETE FROM txs WHERE id LIKE 'bn%'")
        if joins: cx.execute("INSERT INTO txs(id, type, ts) VALUES('bn1', 'join', ?)", (now - 60,))
        if answers: cx.execute("INSERT INTO txs(id, type, ts) VALUES('bn2', 'challenge', ?)", (now - 60,))
    M._feed_fresh = lambda: fresh; M.join_state = lambda: join; M.hosted_state = lambda: hosted
    HR.state = lambda rid: {"grading": grading, "mining": mining}.get(rid, "unknown")
    try: return S.banner_line()
    finally: M._feed_fresh, M.join_state, M.hosted_state, HR.state = _sv
B = {"landing": banner(), "stale feed": banner(fresh=False), "no answers": banner(answers=False), "answers only, joining paused": banner(join="paused", joins=False),
     "mining closed, nothing landing": banner(joins=False, answers=False, mining="closed"), "grading responding": banner(grading="open"),
     "official back": banner(hosted="back", grading="open")}
for k, v in B.items(): print("     banner", k, "->", v)
check("banner: joining and answers landing while grading is paused", B["landing"] == "Joining and answers are landing. Grading is still paused, so new answers wait to be graded.")
check("banner: claims only what live state supports (stale feed or no recent tx: no 'landing')", B["stale feed"] == "Joining works. Mining endpoint responding. Grading is paused."
      and B["no answers"] == "New Agents are joining. Mining endpoint responding. Grading is paused." and B["answers only, joining paused"] == "Answers are landing. Joining is paused. Grading is still paused, so new answers wait to be graded."
      and B["mining closed, nothing landing"] == "Joining works. Hosted mining is paused. Grading is paused.")
check("banner: a responding grading route is only 'responding'; 'back' only on the official signal; never 'reopened' or the old wording",
      B["grading responding"] == "Joining and answers are landing. Grading endpoint responding." and B["official back"] == "Joining and answers are landing. Hosted mining is back."
      and not any("reopened" in v.lower() or "Join now" in v or "paused for network upgrades" in v or "\u2014" in v for v in B.values()))
with db.conn() as cx: cx.execute("DELETE FROM txs WHERE id LIKE 'bn%'")

# ---- /upgrade Details cites the operator comments on post 1357, from our forum mirror only
from poascan import views2 as V2
with db.conn() as cx:
    cx.execute("INSERT OR REPLACE INTO forum_posts(id, author, author_public_id, body) VALUES(1357, 'op', 'opid', 'Hardening window')")
    cx.executemany("INSERT OR REPLACE INTO forum_comments(id, post_id, author, author_public_id, created_at, body) VALUES(?,?,?,?,?,?)",
                   [(3121, 1357, "op", "opid", "2026-10-22 23:16:55", "all clear"), (3123, 1357, "op", "opid", "2026-10-22 23:22:29", "grading still halted"),
                    (3124, 1357, "x", "other", "2026-10-22 23:30:00", "not the operator")])
cit = M.citations(); det = V2.upgrade_details()
check(f"/upgrade Details: operator all clear (3121) and grading clarification (3123) cited from the mirror {cit}",
      cit == [("All clear", 3121, "2026-10-22 23:16:55"), ("Grading clarification", 3123, "2026-10-22 23:22:29")]
      and '<dt>Operator</dt><dd>All clear: comment 3121, <time datetime="2026-10-22T23:16:55Z">23:16:55Z</time>; Grading clarification: comment 3123, <time datetime="2026-10-22T23:22:29Z">23:22:29Z</time> on <a href="https://minepoa.com/lableak/#/post/1357"' in det)
with db.conn() as cx: cx.execute("UPDATE forum_comments SET author_public_id='other' WHERE id=3123")
check("/upgrade Details: a comment not by the post author is never cited", [c[1] for c in M.citations()] == [3121])
with db.conn() as cx: cx.execute("DELETE FROM forum_comments"); cx.execute("DELETE FROM forum_posts")

# ---- agent names: POAScan's archive only
from poascan import names as NM
with db.conn() as cx:
    cx.executemany("INSERT INTO labels VALUES(?,?,?,?,?)", [("poa1aa", "GrokByxAI", "hosted", "join memo", 1792700000), ("poa1bb", "GrokByxAI-2", "hosted", "join memo", 1792700100),
                                                           ("poa1cc", "web", "hosted", "census.csv registration label (Oct 19)", 0), ("poa1dd", "edge-leg herd test", "hosted", "join memo", 1792600000)])
    cx.execute("INSERT INTO forum_posts(id, author, author_public_id) VALUES(1, 'ForumOnly_9', 'pub1')")
real_connect = socket.socket.connect; dialed = []
def no_net(self, *a): dialed.append(a); raise OSError("no network in this check")
socket.socket.connect = no_net
try: res = {n: NM.available(n) for n in ("GrokByxAI", "grokbyxai", "GROKBYXAI", " GrokByxAI", "forumonly_9", "Web", "free-name-77", "a b", "", "x" * 33, "bad.name")}
finally: socket.socket.connect = real_connect
check(f"names: answered from the archive with no network at all (dialed {len(dialed)})", not dialed)
check("names: exact spelling taken, with the exact message and a free suggestion past the taken -2",
      res["GrokByxAI"] == (200, dict(name="GrokByxAI", valid=True, available=False, reason="Taken: GrokByxAI is already an agent. Try another.", suggestion="GrokByxAI-3",
                                    checked_ts=res["GrokByxAI"][1]["checked_ts"], synced_ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1792700100)))))
check("names: case variants are taken too (compared case-insensitively; the message echoes what was typed)",
      all(res[n][1]["available"] is False and res[n][1]["reason"] == f"Taken: {n} is already an agent. Try another." for n in ("grokbyxai", "GROKBYXAI", "Web"))
      and res["forumonly_9"][1]["available"] is False)
check("names: a free name is available with an empty reason and no suggestion", res["free-name-77"][0] == 200 and res["free-name-77"][1]["available"] is True
      and res["free-name-77"][1]["reason"] == "" and "suggestion" not in res["free-name-77"][1] and set(res["free-name-77"][1]) == {"name", "valid", "available", "reason", "checked_ts", "synced_ts"})
check("names: invalid names are a 400 with valid false, available null and the /start message",
      [res[n][0] for n in ("a b", "", "x" * 33, "bad.name", " GrokByxAI")] == [400] * 5 and res["a b"][1]["available"] is None and res["a b"][1]["valid"] is False
      and res["a b"][1]["reason"] == S.name_error("a b") == "Not allowed: space. Use letters, numbers, _ or - (up to 32)." and res[""][1]["reason"] == "Name your agent to continue."
      and res["x" * 33][1]["reason"] == "Too long: up to 32 characters." and res["bad.name"][1]["reason"].startswith("Not allowed: period."))
check("names: a suggestion always fits 32 characters", len(NM.suggest("w" * 32)) <= 32 and NM.suggest("web") == "web-2")

# ---- the page, end to end
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close(); base = f"http://127.0.0.1:{port}"
slog = open(os.path.join(tmp, "server.log"), "w+")
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0"), stdout=slog, stderr=subprocess.STDOUT)
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
    check("/start: one primary button for the first client: 'Copy prompt and open Claude' (short form at 390px) with the Auto pill",
          len(re.findall(r"data-go[ >]", m)) == 1 and '<a class="gobtn" href="https://claude.ai/new" target="_blank" rel="noopener noreferrer" data-go data-kind="auto"><span data-golbl><span class="gll">Copy prompt and open Claude</span><span class="gls">Copy and open Claude</span></span><em class="gauto">Auto</em>' in m)
    check("/start: a quiet Copy prompt button next to it; no helper or join lines under the button; the fallback box is hidden",
          '</a><button class="gocp" type="button" data-gocopy>Copy prompt</button></div>' in m and '<p class="sr-only" data-gofb role="status" aria-live="polite"></p>' in m
          and "stjl" not in m and "Opens Claude" not in m and "starts earning once" not in m[m.index("data-go "):]
          and '<div class="gofail" data-gofail hidden><p>Select and copy this prompt</p><textarea readonly' in m)
    check("/start: name field is checked live, never cut: no maxlength, aria-invalid, aria-describedby, an assertive live error line",
          "maxlength" not in m[m.index('id="stname"'):m.index('id="stname"') + 600] and 'aria-describedby="stname-hint stname-err" aria-invalid="false"' in m
          and '<p class="sterr" id="stname-err" data-nameerr role="status" aria-live="assertive" hidden></p>' in m)
    view = m[m.index('<details class="stview">'):]
    check("/start: the prompt sits collapsed behind View prompt, with its Copy, and is the template text", '<details class="stview"><summary>View prompt</summary>' in m
          and "<details class=\"stview\" open" not in m and m.count("data-copy-prompt") == 1 and m.index("data-go") < m.index("stview") < m.index("data-copy-prompt")
          and unescape(re.search(r'<pre class="pc-text jm-p" tabindex="0">(.*?)</pre>', view, re.S).group(1)).startswith("Join Proof of Agent for me"))
    check("/start: one short key line, no red warning and no repeat outside the prompt", m.count(S.KEYLINE) == 1 and 'class="kwarn"' not in m
          and "Treat a leaked key" not in m and "Never paste your pk_" not in m)
    check("/start: live status strip with the Updated stamp and responding wording, never reopened", m.count('<p class="upstrip stup" role="status" data-live>') == 1
          and "<span data-upstamp>" in m and "<span data-upline>" in m and "reopened" not in m.lower())
    st = m[m.index('<details class="card stepsd">'):]
    check("/start: collapsed All steps are mining only: no Emblem Wallet, no wallet steps or payment line, one short POASwap line",
          "<details class=\"card stepsd\" open" not in m and "Emblem" not in st and "Wallet and swaps included" not in st and "link-auto" not in st
          and "Never send payment outside the network." not in st and st.count('Wallet and swaps: <a href="https://poaswap.io/start" target="_blank" rel="noopener noreferrer">POASwap</a>') == 1
          and [x for x, _, _ in S.STEPS] == ["Register", "Store the key", "Read how grading works", "Answer the challenge", "Mine", "Check in"])
    go3 = m[m.index('data-go '):m.index('<details class="stview">')]
    check("/start: Add a wallet on POASwap, low key, under the main and Copy buttons, new tab to https://poaswap.io/start",
          go3.index("data-gocopy") < go3.index('<p class="stwal"><a href="https://poaswap.io/start" target="_blank" rel="noopener noreferrer" data-wallet>Add a wallet on POASwap</a></p>') < go3.index('class="stkey"')
          and m.count("data-wallet") == 1 and "/swaps#xemb" not in m)
    check("/start: no setup code in the v2 prompt path (no data-reg), keys never asked", 'data-reg' not in m and "SETUP_CODE" not in m and "api_key" not in m[:m.index("stview")]
          and not any(x in m for x in ("\u2014", "Trac", "RESET", "intercom-dex", "Playbay", "invite code=", "Accounts")))
    js = open(os.path.join(ROOT, "static", "app.js")).read(); css = open(os.path.join(ROOT, "static", "style.css")).read()
    blk = js[js.index("/* /start: step 2"):js.index("/* /start close")]
    ck = blk[blk.index('go.addEventListener("click"'):]
    check("client: copy first, synchronously (writeText started, textarea execCommand in the same click), then window.open in the same gesture; no await before open",
          'D.execCommand("copy")' in blk and "navigator.clipboard.writeText(v)" in blk and ck.index("var c=copyNow(P)") < ck.index('W.open(u,"_blank","noopener,noreferrer")') < ck.index("c.then(")
          and "await" not in blk and 'done(u?"Copied, opening "+n:"Copied")' in blk and 'fail(P)' in blk and 'say("Select and copy this prompt")' in blk
          and 'ev("start."+(rg?"copyreg":"copy"))' in blk and "lb.innerHTML" not in blk)
    check("client: name messages, exact", 'return "Name your agent to continue."' in blk and '"Not allowed: "+' in blk and '". Use letters, numbers, _ or - (up to 32)."' in blk
          and '"Too long: up to 32 characters."' in blk and 'c===" "?"space":c==="."?"period":c' in blk and 'bad.slice(0,-1).join(", ")+" and "+bad[bad.length-1]' in blk
          and "/^[A-Za-z0-9_-]{1,32}$/.test(v)" in js and 'replace(/[^A-Za-z0-9_-]/g,"")' not in js)
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
    c5, _, b5 = req("/api/v1/prompts/join?name=a%40b%20c"); c6, _, b6 = req("/api/v1/prompts/join?name=bad.name")
    check("API 400 carries the same message as /start (space and period named)", c5 == 400 and json.loads(b5)["error"] == "Not allowed: @ and space. Use letters, numbers, _ or - (up to 32)."
          and c6 == 400 and json.loads(b6)["error"] == "Not allowed: period. Use letters, numbers, _ or - (up to 32).")
    codes = [req("/api/v1/prompts/join?" + q)[0] for q in ("name=a%20b", "name=" + "x" * 33, "name=%3Cb%3E", "name=a&name=b", "name=%C3%A9")]
    check(f"bad names: 400 {codes}", codes == [400] * 5)
    import poascan.agentapi as AG; VS.API_SRC = lambda: AG.openapi()["paths"]; VS._API[0] = None
    check("counted as its own API route (OpenAPI path), docs and llms list it, not an MCP tool",
          VS.api_route("/api/v1/prompts/join") == "/api/v1/prompts/join" and "/api/v1/prompts/join" in req("/openapi.json")[2] and "/prompts/join" in req("/llms.txt")[2]
          and "/api/v1/prompts/join" in req("/api")[2] and "prompts/join" not in json.dumps(AG.TOOLS, default=str))

    # ---- name-available over HTTP
    na = "/api/v1/agents/name-available?name="
    c, hd, b = req(na + "grokbyxai"); j = json.loads(b)
    check("GET name-available: taken case variant, 200, short public cache, CORS GET", c == 200 and j["available"] is False and j["suggestion"] == "grokbyxai-3"
          and hd.get("Cache-Control") == "public, max-age=30" and hd.get("Access-Control-Allow-Origin") == "*" and "GET" in hd.get("Access-Control-Allow-Methods", ""))
    c2, _, b2 = req(na + "zz-unused-404"); c3, h3, b3 = req(na + "a%20b"); c4, _, b4 = req("/api/agents/name-available"); c5, _, _ = req(na + "a&name=b")
    check("GET name-available: free 200, invalid 400 no-store with the /start message, no name 400, two names 400",
          c2 == 200 and json.loads(b2)["available"] is True and c3 == 400 and h3.get("Cache-Control") == "no-store"
          and json.loads(b3)["reason"] == "Not allowed: space. Use letters, numbers, _ or - (up to 32)." and c4 == 400 and json.loads(b4)["reason"] == "Name your agent to continue." and c5 == 400)
    codes = [req(na + "burst-%d" % i)[0] for i in range(60)]
    check(f"GET name-available: rate limited per IP ({codes.count(429)} of 60 got 429)", 429 in codes and codes[0] == 200)
    check("name-available: counted as its own API route, in OpenAPI, /api and llms.txt, not an MCP tool",
          VS.api_route("/api/v1/agents/name-available") == "/api/v1/agents/name-available" and "/api/v1/agents/name-available" in req("/openapi.json")[2]
          and "NameAvailable" in req("/openapi.json")[2] and "/api/v1/agents/name-available" in req("/api")[2] and "/agents/name-available?name=" in req("/llms.txt")[2]
          and "name-available" not in json.dumps(AG.TOOLS, default=str))
    check("client: debounced 300 ms check, 3 s timeout, stale answers ignored, errors never block, Use link, default name regenerated",
          '"Taken: "+v+" is already an agent. Try another."' in blk and '"/api/v1/agents/name-available?name="+encodeURIComponent(v)' in blk and "setTimeout(function(){avail(v)},300)" in blk
          and "if(ac)ac.abort()},3000)" in blk and "q!==tSeq" in blk and ".catch(function(){clearTimeout(to)})" in blk and 'u.textContent="Use "+sg' in blk
          and "dflt&&tries<5&&W.poaNewName" in blk and "W.poaNewName=gen" in js and ".stuse{" in css)
    time.sleep(0.5); slog.flush(); slog.seek(0); lg = slog.read()
    check("logs: request lines carry the path only, never the queried name", "/api/v1/agents/name-available" in lg and "grokbyxai" not in lg.lower()
          and "zz-unused-404" not in lg and "burst-" not in lg and "?name=" not in lg)
finally:
    p.terminate(); p.wait(10)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
