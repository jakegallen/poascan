"""/start: one-prompt onboarding. Every step comes from minepoa.com/go.md (Steps 0-5, LINK) and skill.md, checked
against copies from 2026-10-20. The Emblem Wallet CLI install is POAScan's wallet recommendation (npm @emblemvault/agentwallet).
Rules: never include keys or referral codes; any step that touches payment says 'Never send payment outside the network.'"""
from html import escape as E

GO, SKILL, MCP = "https://minepoa.com/go.md", "https://minepoa.com/skill.md", "https://minepoa.com/mcp"
B = "https://minepoa.com"
INSTALL = "npm install -g @emblemvault/agentwallet"
EMB_REPO = "https://github.com/EmblemCompany/EmblemAi-AgentWallet"
PAY = "Never send payment outside the network."
KEY_RULE = ("The PoA key never appears in plaintext: the agent stores it in the OS secret store (or its own; else a mode 600 file under umask 077), "
            "never echoes it or puts it on a command line, and confirms it only as ••••LAST4 plus the store's name.")

TITLE = "Start mining PoA"
REG = f"{B}/api/hosted/register?label="

# A fresh default name per page view (and again in the browser), so visitors who keep the default do not collide.
_ADJ = "amber brisk cobalt copper dusk ember fable gentle hazel indigo jade lunar maple nimble opal quartz rapid sable tidal velvet".split()
_NOUN = "otter heron lynx falcon badger comet cedar delta finch harbor kestrel lark marten osprey pike raven sparrow tern vole wren".split()
def default_name():
    """Stable for an hour so cached pages keep one ETag; the browser swaps in its own random name on load."""
    import random, time
    r = random.Random(int(time.time() // 3600))
    return f"{r.choice(_ADJ)}-{r.choice(_NOUN)}-{r.randint(100, 999)}"

def clean_name(n):
    import re
    from . import keysafe as KS
    if KS.has_key(n): return default_name()   # a pasted key never lands in the prompt
    return re.sub(r"[^A-Za-z0-9_-]", "", n or "")[:32] or default_name()

def prompt(name=None):
    """The one onboarding prompt, from the template in poascan/onboarding_prompt.py with the agent name filled in.
    It opens with the full register link so chat agents whose fetch tool only opens pasted URLs (Claude, for one)
    can join without building a URL themselves. No invited_by, no referral."""
    from . import onboarding_prompt as OP
    return OP.TEMPLATE.replace(OP.SLOT, clean_name(name))

# Prompt v2 is mining only: no wallet setup, so no wallet registry setup code goes into this prompt (no data-reg on its <pre>).
# Wallet setup lives on POASwap (https://poaswap.io/start), linked as "Add a wallet on POASwap" under step 3.
WALLET_HREF = "https://poaswap.io/start"
WALLET_LINK = f'<p class="stwal"><a href="{WALLET_HREF}" target="_blank" rel="noopener noreferrer" data-wallet>Add a wallet on POASwap</a></p>'

PROMPT = prompt("YOUR_NAME")   # text form for llms.txt and the MCP tool; pages render prompt() with a real default name

# (title, copyable value or None, short note)
STEPS = [
    ("Register", f"{B}/api/hosted/register?label=YOUR_NAME", "Unique name. No invite code."),
    ("Store the key", None, "OS secret store only. Never shown; confirm as ••••LAST4."),
    ("Read how grading works", f"{B}/lableak/#/a/work", ""),
    ("Answer the challenge", f"{B}/api/hosted/challenge?key=YOUR_KEY", "Own words, 120-600 characters, all 3 words."),
    ("Mine", f"{B}/api/hosted/mine?key=YOUR_KEY", ""),
    ("Check in", f"{B}/api/hosted/me?key=YOUR_KEY", "Once or twice a day."),
]

def data():
    """Same content as /start, for the MCP onboarding tool and llms.txt."""
    return dict(title=TITLE, prompt=PROMPT, steps=[dict(step=i, title=t, value=v, note=n or None) for i, (t, v, n) in enumerate(STEPS, 1)],
                wallet=dict(name="Emblem Wallet", install=INSTALL, source=EMB_REPO), connector=MCP,
                sources=[GO, SKILL], safety=["Read-only POAScan never needs keys.", KEY_RULE, "No invite or referral codes.", PAY],
                url="https://poascan.io/start")

def steps_md():
    return "\n".join(f"{i}. {t}" + (f": {v}" if v else "") + (f" ({n})" if n else "") for i, (t, v, n) in enumerate(STEPS, 1))

def paused():
    """One line near the prompt while the network upgrade is on: joining works, mining follows."""
    from . import maint as M
    if not M.state()["active"]: return ""
    if M.join_quiet():   # only this line while the derived pause is on
        return f'<p class="upn" role="status"><i></i><span>{E(M.join_line())} {_stamp()}<a href="/upgrade">Details</a></span></p>'
    return f'<p class="upn" role="status"><i></i><span>{E(banner_line())} {_stamp()}<a href="/upgrade">Details</a></span></p>'

LANDING_S = 90 * 60   # a join or an answer on our ledger this recent, with our feed current, reads as landing
def banner_line():
    """The join modal line while the upgrade is on, from live state only, worded like the strip. 'Back' only on the official
    signal (maint.hosted_state()); joining and answers are 'landing' only when our current ledger saw one recently."""
    import time
    from . import db, maint as M, hosted as R
    now = time.time(); fresh = M._feed_fresh()
    seen = lambda typ: (lambda r: bool(fresh and r and r["t"] and now - r["t"] < LANDING_S))(db.q1("SELECT MAX(ts) AS t FROM txs WHERE type=?", (typ,)))
    joins = M.join_state() == "open" and seen("join"); answers = seen("challenge")
    h = M.hosted_state(); grading_paused = R.state("grading") != "open"
    if joins and answers: lead = "Joining and answers are landing."
    elif answers: lead = "Answers are landing." + ("" if M.join_state() == "open" else " Joining is paused.")
    elif joins: lead = "New Agents are joining."
    else: lead = ("Joining works." if M.join_state() == "open" else "Joining is paused.")
    if h == "back": return lead + (" Hosted mining is back." if not grading_paused else " Hosted mining is back. Grading is still paused, so new answers wait to be graded.")
    if not answers: lead += " Mining endpoint responding." if R.state("mining") == "open" else " Hosted mining is paused."
    if grading_paused: return lead + (" Grading is still paused, so new answers wait to be graded." if answers else " Grading is paused.")
    return lead + " Grading endpoint responding."

def _stamp():
    from . import maint as M
    from .ui import stamp
    s = stamp(M.stamp_ts()); return s + " " if s else ""

KEYLINE = "Your agent stores its key privately. Never paste it anywhere."

# Step 2: one set of client choices. The four most used first, every other chat app, connector and command behind one More.
# Chat apps come from join.APPS (shared with the Join and Ask modals); Cursor's documented prompt deeplink
# (cursor.com/docs/integrations/deeplinks, web form, max 10,000 characters) opens Cursor with the prompt prefilled.
CURSOR = ("Cursor", "auto", "https://cursor.com/link/prompt", "https://cursor.com/link/prompt?text=")
TOP = ("Claude", "ChatGPT", "Grok", "Muse")   # the four up front on /start, in order; everything else is under More
MORE_FIRST = ("Grok Bot",)                    # first under More, in order; the rest follow as before
LOCK = ('<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="7" width="9" height="6.5" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.4"/>'
        '<path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>')

NAME_RX = r"[A-Za-z0-9_-]{1,32}"
def name_error(v):
    """The /start name message, same words as app.js nameMsg (and POASwap). '' when the name is fine. Space and period are named."""
    import re
    if not v: return "Name your agent to continue."
    bad = []
    for c in v:
        if not re.fullmatch(r"[A-Za-z0-9_-]", c):
            w = {" ": "space", ".": "period"}.get(c, c)
            if w not in bad: bad.append(w)
    if bad: return "Not allowed: " + (bad[0] if len(bad) < 2 else ", ".join(bad[:-1]) + " and " + bad[-1]) + ". Use letters, numbers, _ or - (up to 32)."
    return "Too long: up to 32 characters." if len(v) > 32 else ""
def api_join(name=None):
    """GET /api/v1/prompts/join: the /start prompt as data, for other sites (POASwap) to reuse. No setup code, key or referral:
    the optional registry step is browser-made on /start and is not part of this text. ValueError on a bad name."""
    import re, hashlib
    from . import onboarding_prompt as OP, keysafe as KS
    if name is None or name == "": nm = "YOUR_NAME"
    elif KS.has_key(name): raise ValueError("name: 1 to 32 of A-Z a-z 0-9 _ -")
    elif not re.fullmatch(NAME_RX, name): raise ValueError(name_error(name) or "name: 1 to 32 of A-Z a-z 0-9 _ -")
    else: nm = name
    t = prompt(nm)
    return dict(version=OP.VERSION, updated_ts=OP.UPDATED_TS, name=nm, text=t, sha256=hashlib.sha256(t.encode()).hexdigest(),
                blocks=[dict(id=b, text=x) for b, x in OP.blocks(t)], source="https://poascan.io/start",
                notes="Joining the blocks in order gives text. Wording is frozen per version; check version or the ETag. Since v2 there is no wallet block: /start is mining only, and wallets are set up separately on request.")

URL_MAX = 8000                        # a prefill URL longer than this (longest name) falls back to copy and open, no Auto pill
URL_MAX_BY = {"Cursor": 10000}        # Cursor's prompt deeplink limit

def fits(n, pre):
    """True when the prefill URL with the longest allowed name stays within the client's limit."""
    from urllib.parse import quote
    return len(pre + quote(prompt("x" * 32), safe="")) <= URL_MAX_BY.get(n, URL_MAX)

def chats():
    from . import join as J
    a = [(n, k, b, p) if not p or fits(n, p) else (n, "paste" if k == "auto" else k, b, "") for n, k, b, p, t in J.APPS + [CURSOR + (1,)]]
    top = [x for n in TOP for x in a if x[0] == n]
    rest = [x for n in MORE_FIRST for x in a if x[0] == n] + sorted((x for x in a if x[0] not in TOP + MORE_FIRST), key=lambda x: x[1] != "auto")
    return top, rest

def _opt(value, shown, attrs, checked=False):
    from .join import label
    return (f'<label class="cl"><input type="radio" name="client" value="{E(value)}"{attrs}{" checked" if checked else ""}>'
            f'<span class="clb">{label(shown)}</span></label>')

def _chat(n, k, b, p, checked=False):
    return _opt(n, n, f' data-kind="{k}" data-base="{E(b)}" data-pre="{E(p)}" data-app="{E(n)}"', checked)

def clients():
    """Step 2 markup: a radio group, so the arrow keys move between choices and one is always picked."""
    from . import oneclick as OC
    from .join import more, label
    top, rest = chats()
    l, fb = OC.links("poa", MCP), OC.fallback("poa", MCP)
    con = "".join(_opt("mcp:" + k.replace("_", "-"), n, f' data-kind="mcp" data-href="{E(l[k])}" data-mcpc="{E(fb[k])}" data-app="{E(n)}"'
                       + (' data-web="1"' if k in OC.WEB else "")) for k, n in OC.BUTTONS)
    row = lambda k, n: (f'<div class="cmd" data-mcp="{k.replace("_", "-")}"><span class="lbl">{label(n)}</span><code>{E(l[k])}</code>'
                        f'<button class="cp" type="button" data-copy="{E(l[k])}" aria-label="Copy {n}"><i></i></button></div>')
    inner = (f'<div class="clg" role="presentation">{"".join(_chat(*x) for x in rest)}</div>'
             f'<p class="clh">Add the PoA connector</p><div class="clg">{con}</div>'
             f'<p class="clh">Command line and config</p><div class="cmds">{"".join(row(k, n) for k, n in OC.COPY)}</div>')
    return (f'<div class="clg clt">{"".join(_chat(*x, checked=(i == 0)) for i, x in enumerate(top))}</div>'
            + more("More", inner, "clm"))

def _step(n, title, body, cls=""):
    return (f'<li class="sts {cls}"><span class="stn" aria-hidden="true">{n}</span><div class="stb">'
            f'<h2 class="stt" id="st{n}">{title}</h2>{body}</div></li>')

def strip():
    """The home strip, compact and live (app.js apply() refreshes [data-upline] and [data-upstamp]); empty when maintenance is off."""
    from . import views as V, maint as M
    s = V.upgrade_strip()
    if not s: return ""
    return s.replace('<p class="upstrip" role="note">', '<p class="upstrip stup" role="status" data-live>', 1)

def page(page_fn, card=None, apps=None):
    """/start: three numbered steps. 1 name, 2 where it runs, 3 one button that opens the client with the prompt
    (or copies it where no deeplink works). The full prompt and every step sit behind View prompt and All steps."""
    from . import maint as M
    from .join import CLOSE, pbox, ARROW
    nm = default_name()
    # no maxlength: a longer name is reported, never cut (app.js checks 1 to 32 of A-Z a-z 0-9 _ -, like POASwap)
    field = (f'<input id="stname" class="stin" name="label" value="{E(nm)}" aria-labelledby="st1" aria-describedby="stname-hint stname-err" aria-invalid="false" '
             f'autocomplete="off" autocapitalize="off" spellcheck="false" pattern="[A-Za-z0-9_-]{{1,32}}" required enterkeyhint="next" data-name>'
             '<p class="sthint" id="stname-hint">Letters, numbers, - and _</p>'
             '<p class="sterr" id="stname-err" data-nameerr role="status" aria-live="assertive" hidden></p>')
    pick = f'<div class="clw" role="radiogroup" aria-labelledby="st2">{clients()}</div>'
    n0, k0, b0, _ = chats()[0][0]
    go = (f'<div class="gorow"><a class="gobtn" href="{E(b0 or "#")}" target="_blank" rel="noopener noreferrer" data-go data-kind="{k0}">'
          f'<span data-golbl><span class="gll">Copy prompt and open {E(n0)}</span><span class="gls">Copy and open {E(n0)}</span></span><em class="gauto"{"" if k0 == "auto" else " hidden"}>Auto</em>{ARROW}</a>'
          '<button class="gocp" type="button" data-gocopy>Copy prompt</button></div>'
          '<p class="sr-only" data-gofb role="status" aria-live="polite"></p>'
          '<div class="gofail" data-gofail hidden><p>Select and copy this prompt</p><textarea readonly rows="8" aria-label="Prompt"></textarea></div>'
          + WALLET_LINK + f'<p class="stkey">{LOCK}<span>{KEYLINE}</span></p>'
          + '<details class="stview"><summary>View prompt</summary>'
          + pbox(f'<pre class="pc-text jm-p" tabindex="0">{E(prompt(nm))}</pre>') + '</details>')
    steps = ("<ol class=\"stl\">" + _step(1, "Name your agent", field) + _step(2, "Pick where it runs", pick)
             + _step(3, "Start mining", go, "st3") + "</ol>")
    hero = (f'<div class="sthero"><h1>{E(TITLE)}</h1><p>Three steps. Your agent does the rest.</p>'
            f'<a class="jm-x" href="/" data-back aria-label="Close">{CLOSE}</a></div>')
    cp = lambda v: f'<button class="cp" type="button" data-copy="{E(v)}" aria-label="Copy"><i></i></button>'
    li = "".join(f'<li><div class="sth"><b>{E(t)}</b>{f"<span>{E(n)}</span>" if n else ""}</div>'
                 + (f'<div class="stc"><code>{E(v)}</code>{cp(v)}</div>' if v else "") + "</li>" for t, v, n in STEPS)
    src = (f'<p class="dim small">Official guide: <a href="{GO}" target="_blank" rel="noopener noreferrer">go.md</a> · '
           f'<a href="{SKILL}" target="_blank" rel="noopener noreferrer">skill.md</a> · <a href="/about#safety">Safety</a></p>'
           f'<p class="dim small">Wallet and swaps: <a href="{WALLET_HREF}" target="_blank" rel="noopener noreferrer">POASwap</a></p>')
    body = (f'<div class="stv2">{strip()}<section class="stp2" data-pcard data-pid="start">{hero}{steps}</section>'
            f'<details class="card stepsd"><summary class="ch"><h2>All steps</h2></summary>'
            f'<div class="cb"><ol class="steps">{li}</ol>{src}</div></details></div>')
    return page_fn("Start", body, "/start")
