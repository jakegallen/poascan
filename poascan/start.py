"""/start: one-prompt onboarding. Every step comes from minepoa.com/go.md (Steps 0-5, LINK) and skill.md, checked
against copies from 2026-10-20. Emblem Wallet is POAScan's wallet recommendation (npm @emblemvault/agentwallet, run pinned with npx, never installed globally).
Rules: never include keys or referral codes; any step that touches payment says 'Never send payment outside the network.'"""
from html import escape as E

GO, SKILL, MCP = "https://minepoa.com/go.md", "https://minepoa.com/skill.md", "https://minepoa.com/mcp"
B = "https://minepoa.com"
INSTALL = "npx -y -p @emblemvault/agentwallet@3.3.0 emblemai --hustle-url https://emblemvault.ai"   # pinned, no global install (swap/prompts.EMB; Oct 22 incident)
WALLET_NOTE = ("Needs Node 20.18+ (macOS: brew install node; Linux: nvm install 22; Windows: winget install OpenJS.NodeJS.LTS). "
               "npx cache or permission error: retry once with npx --cache \"$(mktemp -d)\" (Windows: any new empty folder); network error: retry once. "
               "Back up ~/.emblemai first (cp -a), always pass --profile NAME and --hustle-url https://emblemvault.ai, never -p or EMBLEM_PASSWORD. "
               "Before reading: emblemai profile inspect NAME must show Credentials: present, else stop. One attempt; ask before creating a new wallet.")
EMB_REPO = "https://github.com/EmblemCompany/EmblemAi-AgentWallet"
PAY = "Never send payment outside the network."
KEY_RULE = ("The agent stores the PoA key in the OS secret store (or its own; else a mode 600 file under umask 077) and offers one private backup "
            "(a poa-backup-key.txt file, else the key once in a direct reply). After that it never appears in plaintext: never echoed or on a command line, "
            "confirmed only as ••••LAST4 plus the store's name.")

TITLE = "Start mining PoA"

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

def prompt(name=None, variant="full"):
    """The onboarding prompt, from poascan/onboarding_prompt.py with the agent name filled in. variant "full" (default) is
    the canonical TEMPLATE every untagged surface serves; "chat-browse" and "connector" are the v2.4 short variants.
    No invited_by, no referral."""
    from . import onboarding_prompt as OP
    return OP.variant(variant).replace(OP.SLOT, clean_name(name))

def client_prompt(name, cid):
    """The text a /start button copies for one registry client: its variant, the name, check-ins tagged with its id.
    None for a no-path client. KeyError for an unknown id."""
    from . import onboarding_prompt as OP, clients as C
    c = C.BY_ID[cid]; v = C.variant(c)
    return OP.tagged(prompt(name, v), cid) if v else None

# Prompt v2 is mining only: no wallet setup, so no wallet registry setup code goes into this prompt (no data-reg on its <pre>).
# Wallet setup lives on POASwap (https://poaswap.io/start), linked as "Add a wallet on POASwap" under step 3.
WALLET_HREF = "https://poaswap.io/start"
WALLET_LINK = f'<p class="stwal"><a href="{WALLET_HREF}" target="_blank" rel="noopener noreferrer" data-wallet>Add a wallet on POASwap</a></p>'

PROMPT = prompt("YOUR_NAME")   # text form for llms.txt and the MCP tool; pages render prompt() with a real default name

# v2.7 (LabLeak 1398, comment 3476): a published hash so a reader can check which prompt they got without trusting page text.
# template_sha256 is the SHA-256 of the canonical template: the full variant exactly as GET /api/v1/prompts/join returns it
# with no name and no client (YOUR_NAME left in place), UTF-8 with no BOM, LF newlines only, no trailing newline. Each
# variant gets variant_sha256 by the same rule (connector and chat-browse via ?client=). A filled-in name changes the text,
# so a copy with your agent's name will not match; the hash is of the placeholder text.
HASH_RULE = ("SHA-256 of the UTF-8 text from /api/v1/prompts/join with no name and no client: YOUR_NAME left in place, "
             "LF newlines, no BOM, no trailing newline.")
VERIFY = "curl -s https://poascan.io/api/v1/prompts/join | jq -j .text | sha256sum"

def text_sha256(t):
    import hashlib
    assert "\r" not in t and not t.startswith("\ufeff") and not t.endswith("\n"), "hash rule: LF only, no BOM, no trailing newline"
    return hashlib.sha256(t.encode("utf-8")).hexdigest()

def variant_sha256(variant="full"):
    """SHA-256 of one variant with the YOUR_NAME placeholder (HASH_RULE); "full" is template_sha256."""
    return text_sha256(prompt("YOUR_NAME", variant))

def template_sha256():
    return variant_sha256("full")

def hash_fields(variant="full"):
    """The v2.7 fields every surface carries: prompt_version, template_sha256, variant_sha256 (None without a prompt), the rule."""
    from . import onboarding_prompt as OP
    return dict(prompt_version=OP.VERSION, template_sha256=template_sha256(), variant_sha256=variant_sha256(variant) if variant else None,
                hash_rule=HASH_RULE, verify=VERIFY)

def phash():
    """The small line beside the widget on /start and in the Join dialog: version and a 12 character hash prefix; the button
    copies the full value (also in its title), Verify goes to the /about method."""
    from . import onboarding_prompt as OP
    h = template_sha256()
    return (f'<p class="phash"><button type="button" data-phash="{h}" title="Template sha256 {h}" aria-label="Copy the template sha256">'
            f'<span>Prompt {E(OP.VERSION)}</span><span>sha256 <code>{h[:12]}</code></span></button><a href="/about#prompt-hash">Verify</a></p>')

# v2.3 check-in tags. Each /start chat choice carries data-tag; its copy buttons tag the two check-in URLs with it
# (onboarding_prompt.tagged). The API, MCP and llms.txt serve the untagged text. POASwap renders the API prompt and may tag
# it as "poaswap" itself (the API's checkin field says how). checkin.py accepts only these ids, plus "none" for untagged.
def client_tag(name):
    """'Grok Bot' -> 'grok-bot', 'Z.ai' -> 'z-ai': lower case a-z 0-9 and single hyphens, at most 24 characters."""
    import re
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", (name or "").lower())).strip("-")[:24].strip("-")
EXTRA_TAGS = ("poaswap",)
def checkin_clients():
    """Every client id a check-in may carry: the shared registry (data/clients.json, every /start choice, no-path ones too,
    so older tagged copies keep counting), the Join modal apps and EXTRA_TAGS."""
    from . import join as J, clients as C
    return frozenset(C.ids() + [client_tag(x[0]) for x in J.APPS] + list(EXTRA_TAGS))
HELP_MAIL = "jakegallen@gmail.com"
HELP_LINE = f'<p class="sthelp"><a href="mailto:{HELP_MAIL}?subject=PoA%20join%20got%20stuck">If it got stuck, share the chat with us</a></p>'

# (title, copyable value or None, short note)
STEPS = [
    # v2.5: links are written whole. The register one carries the YOUR_NAME placeholder, so a crawler or HowTo reader that
    # fetched it could only hit a placeholder name, never a real one; key links carry YOUR_KEY.
    ("Register", f"{B}/api/hosted/register?label=YOUR_NAME", "Unique name. No invite code. Your agent opens it once."),
    ("Store the key", None, "OS secret store only. One private backup, then never shown; confirm as ••••LAST4."),
    ("Read how grading works", f"{B}/lableak/#/a/work", ""),
    ("Answer the challenge", f"{B}/api/hosted/challenge?key=YOUR_KEY", "Own words, 120-600 characters, all 3 words."),
    ("Mine", f"{B}/api/hosted/mine?key=YOUR_KEY", ""),
    ("Check in", f"{B}/api/hosted/me?key=YOUR_KEY", "Once or twice a day."),
]

def data():
    """Same content as /start, for the MCP onboarding tool and llms.txt."""
    from . import onboarding_prompt as OP
    return dict(title=TITLE, notice=OP.NOTICE, prompt=PROMPT, **hash_fields(), steps=[dict(step=i, title=t, value=v, note=n or None) for i, (t, v, n) in enumerate(STEPS, 1)],
                wallet=dict(name="Emblem Wallet", install=INSTALL, source=EMB_REPO, note=WALLET_NOTE), connector=MCP,
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

KEYLINE = "Your agent keeps its key private and gives you one backup. Never share it."

def notice():
    """v2.5 (LabLeak post 1398): the visible line next to every copy of a prompt, in the fetched HTML too."""
    from . import onboarding_prompt as OP
    return f'<p class="pnote" data-pnote>{E(OP.NOTICE)}</p>'

# Step 2: one set of client choices from the shared registry (data/clients.json, poascan/clients.py): the four in row "top"
# up front, every other app behind one More (registry order), then the connector install links and commands.
# v2.4: Muse moved out of the first row (no working path today); Cursor took its place (shell agent, prompt deeplink,
# cursor.com/docs/reference/deeplinks). Connector clients get two buttons in step 3: add the connector, then the prompt.
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
CLIENTS_URL = "https://poascan.io/api/v1/prompts/clients"

# Internal fetch ids for /api/v1/prompts/join: accepted only so a partner's own server fetch is counted under its id in
# /ops/dashboard offchain.setup_signals. They are not registry clients: never on /start, in the Ask buttons, llms.txt or
# /api/v1/prompts/clients, and they get exactly the no-client response (the plain untagged full text).
INTERNAL_CLIENTS = frozenset({"poaswap"})

def api_join(name=None, client=None):
    """GET /api/v1/prompts/join[?client=&name=]: the /start prompt as data, for other sites (POASwap) to reuse. No setup code,
    key or referral. Without client: the canonical untagged text (unchanged since v2). With a registry client id (v2.4): that
    client's variant with its check-ins tagged, exactly what its /start button copies, plus tier, prefill and connector
    details; a no-path client gets text null and the panel. ValueError on a bad name or an unknown client."""
    import re, hashlib
    from . import onboarding_prompt as OP, keysafe as KS
    if name is None or name == "": nm = "YOUR_NAME"
    elif KS.has_key(name): raise ValueError("name: 1 to 32 of A-Z a-z 0-9 _ -")
    elif not re.fullmatch(NAME_RX, name): raise ValueError(name_error(name) or "name: 1 to 32 of A-Z a-z 0-9 _ -")
    else: nm = name
    if client is not None and client not in INTERNAL_CLIENTS: return _api_client(nm, client)
    t = prompt(nm)
    return dict(version=OP.VERSION, updated_ts=OP.UPDATED_TS, name=nm, notice=OP.NOTICE, **hash_fields(), text=t, sha256=hashlib.sha256(t.encode()).hexdigest(),
                blocks=[dict(id=b, text=x) for b, x in OP.blocks(t)], source="https://poascan.io/start",
                # 1.26.44: base is null because the text has no check-ins (since v2.5). The v2.4 base stays as legacy_base, only
                # for copies of older prompts still in chats; /j/ keeps answering those.
                checkin=dict(base=None, in_text=False, legacy_base=OP.CHECKIN, legacy_versions="v2.3 to v2.4", tag_rule="nothing to tag: the text has no check-in URLs",
                             client_rx=OP.TAG_RX.pattern, clients=sorted(checkin_clients()), suggested_client="poaswap",
                             note="The prompt text has no check-ins since v2.5, so base is null. legacy_base is the v2.4 check-in base, kept only for older copies still in chats."),
                variant="full", clients_url=CLIENTS_URL,
                notes="Joining the blocks in order gives text. Wording is frozen per version; check version or the ETag. Since v2 there is no wallet block: /start is mining only, and wallets are set up separately on request. Since v2.4, ?client=<id> (ids in clients_url) returns that client's variant. Show notice next to the text wherever you render it.")

def _api_client(nm, cid):
    import hashlib
    from urllib.parse import quote
    from . import onboarding_prompt as OP, clients as C
    c = C.get(cid) if isinstance(cid, str) else None
    if not c: raise ValueError("client: one of the ids in " + CLIENTS_URL)
    v = C.variant(c)
    base = dict(version=OP.VERSION, updated_ts=OP.UPDATED_TS, name=nm, notice=OP.NOTICE, **hash_fields(v), client=cid, client_name=c["name"], tier=c["tier"], variant=v,
                open=c["open"] or None, connector=dict(c["connector"], url=C.MCP_URL) if c.get("connector") else None, clients_url=CLIENTS_URL,
                source="https://poascan.io/start")
    if not v:
        alt = [dict(id=a, name=C.BY_ID[a]["name"]) for a in C.NOPATH["alternatives"]]
        return dict(base, text=None, sha256=None, blocks=[], prefill=None, prefill_ok=False, link_chars=None,
                    panel=dict(line=C.NOPATH["line"], alternatives=alt),
                    notes="No working path in this app today, so there is no prompt. Offer one of the alternatives.")
    t = client_prompt(nm, cid)
    ok = bool(c["prefill"]) and fits_client(c)
    return dict(base, text=t, sha256=hashlib.sha256(t.encode()).hexdigest(), blocks=[dict(id=b, text=x) for b, x in OP.blocks(t, v)],
                prefill=c["prefill"] if ok else None, prefill_ok=ok, chars=len(t),
                link_chars=len(c["prefill"] + quote(t, safe="")) if ok else None,
                notes="text is exactly what the /start button for this client copies: the " + v + " variant (no check-ins since v2.5)"
                      + ". Joining the blocks in order gives text. Show notice next to the text wherever you render it.")

URL_MAX = 8000                        # every prefill link stays under this (longest name, tagged); longer falls back to copy and open

def link_len(c, name="x" * 32):
    """Length of a registry client's prefill link with its variant, tagged, for this name (0 without a prefill or prompt)."""
    from urllib.parse import quote
    t = client_prompt(name, c["id"])
    return len(c["prefill"] + quote(t, safe="")) if c["prefill"] and t else 0

def fits_client(c):
    return link_len(c) < URL_MAX

def fits(n, pre):
    """True when the canonical prompt's prefill URL, tagged for client name n, with the longest name stays under URL_MAX."""
    from urllib.parse import quote
    from . import onboarding_prompt as OP
    return len(pre + quote(OP.tagged(prompt("x" * 32), client_tag(n) or "x"), safe="")) < URL_MAX

def chats():
    """/start step 2 choices from the shared registry, as dicts: top row, then More (registry order, Grok Bot first).
    kind: auto (the link carries the prompt), paste (copy, then open) or none (no-path panel)."""
    from . import clients as C
    a = []
    for c in C.CLIENTS:
        v = C.variant(c)
        k = "none" if not v else ("auto" if c["prefill"] and fits_client(c) else "paste")
        a.append(dict(c, kind=k, pre=c["prefill"] if k == "auto" else "", variant=v))
    return [x for x in a if x["row"] == "top"], [x for x in a if x["row"] == "more"]

def _opt(value, shown, attrs, checked=False, rn="client"):
    from .join import label
    return (f'<label class="cl"><input type="radio" name="{rn}" value="{E(value)}"{attrs}{" checked" if checked else ""}>'
            f'<span class="clb">{label(shown)}</span></label>')

def _chat(c, checked=False, rn="client"):
    co = c.get("connector") or {}
    con = (f' data-cset="{E(co.get("settings_url") or "")}" data-ccopy="{E(co.get("cli") or MCP)}"' + (' data-cauto="1"' if co.get("prefills_url") else "")) if co else ""
    return _opt(c["name"], c["name"], f' data-kind="{c["kind"]}" data-tier="{c["tier"]}" data-base="{E(c["open"])}" data-pre="{E(c["pre"])}" '
                f'data-app="{E(c["name"])}" data-tag="{E(c["id"])}"{con}', checked, rn)

def nopath_panel():
    """Step 3 for a no-path client (tier none): one line and the working alternatives, each picks that client. No prompt."""
    from . import clients as C
    from .join import label
    b = "".join(f'<button class="npb" type="button" data-pick="{E(C.BY_ID[a]["name"])}">{label(C.BY_ID[a]["name"])}</button>' for a in C.NOPATH["alternatives"])
    return f'<div class="nopath" data-nopath role="status" hidden><p>{E(C.NOPATH["line"])}</p><div class="npg">{b}</div></div>'

def variant_templates():
    """The three variant templates, untagged with the {NAME} slot, for app.js to render the picked client's prompt."""
    from . import onboarding_prompt as OP
    return "".join(f'<pre hidden data-variant="{v}">{E(t)}</pre>' for v, t in OP.VARIANTS.items())

def clients(rn="client"):
    """Step 2 markup: a radio group, so the arrow keys move between choices and one is always picked. rn is the radio
    name: "client" on /start, "jclient" in the Join dialog (both sit on /start, and radios group by name page-wide)."""
    from . import oneclick as OC
    from .join import more, label
    top, rest = chats()
    l, fb = OC.links("poa", MCP), OC.fallback("poa", MCP)
    con = "".join(_opt("mcp:" + k.replace("_", "-"), n, f' data-kind="mcp" data-href="{E(l[k])}" data-mcpc="{E(fb[k])}" data-app="{E(n)}"'
                       + (' data-web="1"' if k in OC.WEB else ""), False, rn) for k, n in OC.BUTTONS)
    row = lambda k, n: (f'<div class="cmd" data-mcp="{k.replace("_", "-")}"><span class="lbl">{label(n)}</span><code>{E(l[k])}</code>'
                        f'<button class="cp" type="button" data-copy="{E(l[k])}" aria-label="Copy {n}"><i></i></button></div>')
    inner = (f'<div class="clg" role="presentation">{"".join(_chat(x, False, rn) for x in rest)}</div>'
             f'<p class="clh">Add the PoA connector</p><div class="clg">{con}</div>'
             f'<p class="clh">Command line and config</p><div class="cmds">{"".join(row(k, n) for k, n in OC.COPY)}</div>')
    return (f'<div class="clg clt">{"".join(_chat(x, (i == 0), rn) for i, x in enumerate(top))}</div>'
            + more("More", inner, "clm"))

# One button (one button): the step 3 button copies the prompt in every case. Auto apps (the link carries the prompt): one click
# copies and opens. Paste apps with an open URL: the first click copies and the button becomes "Copied. Open X"; the second
# opens. Apps with no open URL: one click copies, "Copied. Paste it into X". A connector app adds one small text link under
# the button. app.js setup() mirrors go_label() and con_label() for the picked app.
COPYI = ('<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="5" width="8.5" height="8.5" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.5"/>'
         '<path d="M3 10.5V3.6A1.1 1.1 0 0 1 4.1 2.5H10" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>')
CHECKI = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5 6.5 11.5 12.5 4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'

def go_label(c):
    """(long label, short label for 390px, icon) of the step 3 button before a click: auto apps copy and open, the rest copy."""
    n = c["name"]
    if c["kind"] == "auto": return f"Copy prompt and open {n}", f"Copy and open {n}", "a"
    return f"Copy prompt for {n}", f"Copy for {n}", "c"

def con_label(c):
    """The small connector link under the button, or "" when the app has no PoA connector."""
    co = c.get("connector") or {}
    if not co: return ""
    return f"Or add the PoA connector to {c['name']}" if co.get("settings_url") else f"Or copy the {c['name']} connector command"

def go_block(c0):
    """Step 3: the one button, the connector link, the no-path panel and the copy fallback; shared by /start and the Join dialog."""
    from .join import ARROW
    co0 = c0.get("connector") or {}; ll, ls, ic = go_label(c0); cl = con_label(c0)
    ico = (f'<span class="gi gi-a" data-gi="a"{"" if ic == "a" else " hidden"}>{ARROW}</span><span class="gi gi-c" data-gi="c"{"" if ic == "c" else " hidden"}>{COPYI}</span>'
           f'<span class="gi gi-k" data-gi="k" hidden>{CHECKI}</span>')
    return (f'<div class="gorow" data-gorow><a class="gobtn" href="{E(c0["open"] or "#")}" target="_blank" rel="noopener noreferrer" data-go data-kind="{c0["kind"]}">'
            f'<span data-golbl><span class="gll">{E(ll)}</span><span class="gls">{E(ls)}</span></span><em class="gauto"{"" if c0["kind"] == "auto" else " hidden"}>Auto</em>{ico}</a></div>'
            f'<p class="gocl" data-conrow{"" if cl else " hidden"}><a href="{E(co0.get("settings_url") or "#")}" target="_blank" rel="noopener noreferrer" data-gocon>'
            f'<span data-conlbl>{E(cl)}</span>{ARROW}</a></p>'
            + nopath_panel() + '<p class="sr-only" data-gofb role="status" aria-live="polite"></p>'
            '<div class="gofail" data-gofail hidden><p>Select and copy this prompt</p><textarea readonly rows="8" aria-label="Prompt"></textarea></div>')

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
    from . import maint as M, onboarding_prompt as OP
    from .join import CLOSE, pbox
    nm = default_name()
    # no maxlength: a longer name is reported, never cut (app.js checks 1 to 32 of A-Z a-z 0-9 _ -, like POASwap)
    field = (f'<input id="stname" class="stin" name="label" value="{E(nm)}" aria-labelledby="st1" aria-describedby="stname-hint stname-err" aria-invalid="false" '
             f'autocomplete="off" autocapitalize="off" spellcheck="false" pattern="[A-Za-z0-9_\\-]{{1,32}}" required enterkeyhint="next" data-name>'
             '<p class="sthint" id="stname-hint">Letters, numbers, - and _</p>'
             '<p class="sterr" id="stname-err" data-nameerr role="status" aria-live="assertive" hidden></p>')
    pick = f'<div class="clw" role="radiogroup" aria-labelledby="st2">{clients()}</div>'
    c0 = chats()[0][0]
    go = (go_block(c0)
          + WALLET_LINK + f'<p class="stkey" data-stkey>{LOCK}<span>{KEYLINE}</span></p>' + notice() + phash()
          + '<details class="stview" data-stview><summary>View prompt</summary>'
          # v2.5: the HTML carries the YOUR_NAME placeholder; app.js puts the visitor's name in (render() on load), so a crawler
          # that pulled the register link out of the page text could only hit the placeholder, never a fresh name each hour.
          + pbox(f'<pre class="pc-text jm-p" tabindex="0">{E(prompt("YOUR_NAME", c0["variant"] or "full"))}</pre>') + '</details>' + HELP_LINE)
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
