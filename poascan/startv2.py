"""/start (1.26.246): name first, then the app, then the card morphs into what that app needs.

Step 1: the Agent name, generated and prefilled, so Next is one tap (checked only against POAScan's own archive). Step 2:
"What are you using?", Claude preselected with Continue; Runs code tiles carry a terminal glyph with a live dot, chat tiles
a plug, not supported apps sit behind Something else. Then: Runs code apps get Copy prompt (Cursor also Open Cursor; Codex
its network note); chat apps a three point strip (join on minepoa.com, add minepoa's connector with the key warning, paste
the prompt); not supported apps one line and the apps that can. POASCAN_STARTV2=0 serves the 1.26.245 layout (rollback).
Static markup plus static/startv2.js and static/startv2.css. POAScan never sees, asks for or links a key."""
import json, os
from html import escape as _e

def E(s): return _e(str(s), quote=True)

FLAG = "POASCAN_STARTV2"
def on(): return os.environ.get(FLAG, "1") != "0"

def _apps():
    from . import start as S, clients as C
    from .join import BRAND
    top, rest = S.chats(); out = []
    for c in top + rest:
        co = c.get("connector") or {}
        out.append(dict(id=c["id"], name=c["name"], tier=c["tier"], kind=c["kind"], open=c["open"], pre=c["pre"],
                        logo=BRAND.get(c["name"], ""), note=c.get("note") or "", cset=co.get("settings_url") or "",
                        cfill=bool(co.get("prefills_url")), where=co.get("where") or "", cnote=S.CON_NOTE.get(c["id"], "")))
    return out

GLYPH_CODE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5 6.5 8 3 11.5M8 12h5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
GLYPH_PLUG = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 2v3M10 2v3M4.5 5h7v2.5a3.5 3.5 0 0 1-7 0zM8 11v3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
CHECK = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5 6.5 11.5 12.5 4.5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>'
PEN = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10.5 3.2 12.8 5.5 6 12.3 3.4 12.6 3.7 10z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>'
BACK = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3.5 5.5 8l4.5 4.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'

def _logo(a):
    return (f'<img src="/static/brands/{E(a["logo"])}?v=1" width="28" height="28" alt="" aria-hidden="true">' if a["logo"]
            else f'<i class="mono" aria-hidden="true">{E(a["name"][:1])}</i>')

PRESELECT = "claude"

def _tile(a, i):
    b = {"full": f'<span class="sv-b sv-bc" title="Runs code">{GLYPH_CODE}<i class="sv-live"></i></span>',
         "connector": f'<span class="sv-b sv-bp" title="Chat + connector">{GLYPH_PLUG}</span>'}.get(a["tier"], "")
    sel = a["id"] == PRESELECT
    return (f'<button type="button" class="sv-t sv-{a["tier"]}{" sel" if sel else ""}" data-app="{E(a["id"])}" style="--i:{i}"{' aria-current="true"' if sel else ""}>'
            f'<span class="sv-tl">{_logo(a)}</span><span class="sv-tn">{E(a["name"])}</span>{b}</button>')

def body():
    from . import start as S, onboarding_prompt as OP
    from .earnview import tabs
    from .join import CLOSE, pbox
    apps = _apps(); sup = [a for a in apps if a["tier"] != "none"]; ns = [a for a in apps if a["tier"] == "none"]
    pz = S.paused()
    grid = "".join(_tile(a, i) for i, a in enumerate(sup))
    other = "".join(f'<button type="button" class="sv-o" data-app="{E(a["id"])}">{E(a["name"])}</button>' for a in ns)
    tpl = (f'<pre hidden data-sv-tpl="full">{E(OP.VARIANTS["full"])}</pre><pre hidden data-sv-tpl="connector">{E(OP.VARIANTS["connector"])}</pre>')
    data = json.dumps(dict(apps=apps, join=S.JOIN_URL, mcp=S.MCP, alts=["claude-code", "cursor", "grok-bot"], slot=OP.SLOT,
                           warn=S.KEY_WARN, paused=pz), separators=(",", ":")).replace("</", "<\\/")
    name = S.default_name()
    hero = (f'<div class="sv-hero">{tabs("/start")}<h1>Start mining PoA</h1>'
            f'<a class="jm-x" href="/" data-back aria-label="Close">{CLOSE}</a></div>')
    namescr = (f'<div class="sv-name0" data-sv-name0><label for="sv-n0">Name your Agent</label>'
               f'<div class="sv-n0r"><input id="sv-n0" value="{E(name)}" autocomplete="off" autocapitalize="off" spellcheck="false" data-sv-n0>'
               f'<button type="button" class="sv-btn" data-sv-next>Next</button></div><p class="sv-err" data-sv-err0 hidden></p></div>')
    pick = (f'<div class="sv-pick" data-sv-pick hidden><div class="sv-qh"><button type="button" class="sv-back" data-sv-back aria-label="Back to the name">{BACK}</button><p class="sv-q">What are you using?</p></div>'
            f'<div class="sv-grid" role="list">{grid}</div>'
            f'<button type="button" class="sv-btn sv-go" data-app="{PRESELECT}">Continue with {E(next(a["name"] for a in apps if a["id"] == PRESELECT))}</button>'
            f'<div class="sv-key" aria-hidden="true"><span class="sv-b sv-bc">{GLYPH_CODE}<i class="sv-live"></i></span>Runs code'
            f'<span class="sv-b sv-bp">{GLYPH_PLUG}</span>Chat + connector</div>'
            f'<details class="sv-other"><summary>Something else</summary><div class="sv-ol">{other}</div></details></div>')
    panel = (f'<div class="sv-panel" data-sv-panel hidden aria-live="polite">'
             f'<div class="sv-ph"><button type="button" class="sv-back" data-sv-back aria-label="All apps">{BACK}</button>'
             f'<span class="sv-pl" data-sv-logo></span><b data-sv-app></b><span class="sv-ptag" data-sv-tag></span></div>'
             f'<div data-sv-body></div></div>')
    foot = (f'<div class="sv-foot" data-sv-foot hidden>{S.notice()}{S.phash()}'
            f'<details class="sv-view"><summary>View prompt</summary>' + pbox(f'<pre class="pc-text jm-p sv-pre" data-sv-pre tabindex="0">{E(S.prompt("YOUR_NAME"))}</pre>') + '</details>' + S.HELP_LINE
            + S.WALLET_LINK + '</div>')
    return (f'<div class="s2v" data-sv data-svname="{E(name)}"{" data-paused=\"1\"" if pz else ""}>'
            f'<section class="sv-card">{hero}{S.join_halt_html()}{namescr}{pick}{panel}{foot}</section>'
            f'{tpl}<script type="application/json" data-sv-json>{data}</script>{S.below()}</div>')

def page(page_fn):
    from . import ui as U
    v = lambda n: U._asset_v(n) if hasattr(U, "_asset_v") else "1"
    head = (f'<link rel="stylesheet" href="/static/startv2.css?v={v("startv2.css")}">'
            f'<script src="/static/startv2.js?v={v("startv2.js")}" defer></script>')
    return page_fn("Start", body(), "/start", head=head)
