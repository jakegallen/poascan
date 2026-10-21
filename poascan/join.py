"""Join modal: one prompt built from the official minepoa.com onboarding (go.md / skill.md).
Client-side links only; nothing here calls a backend."""
from html import escape as E
from . import start as _S

SOURCE = "https://minepoa.com/go.md"

PROMPT = _S.PROMPT  # one onboarding prompt, shared with /start

LINE = ("Read https://minepoa.com/go.md (or use the MCP connector https://minepoa.com/mcp), then join PoA (Proof of Agent): "
        "register (no invite code), read how grading works at https://minepoa.com/lableak/#/a/work, answer the epoch challenge in your own words, mine, "
        "and report my address and balance. Skip any invite or referral link. Never ask me for keys or seed phrases.")

# Re-tested logged out 2026-10-20 (Playwright, headed Chrome). See README "Join links".
# kind "auto": the URL itself carries the prompt into a NEW chat; "paste": we copy, open a new chat, user pastes.
APPS = [
    # Meta's Muse (Muse Spark, Meta Superintelligence Labs) at meta.ai. ?prompt= is the documented param but did not
    # prefill logged out; we still pass it (harmless) and always copy first.
    ("Muse", "paste", "https://www.meta.ai/", "https://www.meta.ai/?prompt="),
    ("ChatGPT", "auto", "https://chatgpt.com/", "https://chatgpt.com/?q="),          # logged out: auto-sends; logged in: prefilled
    ("Grok", "auto", "https://grok.com/", "https://grok.com/?q="),                  # prefilled + one-tap "Send this message?"
    ("Claude", "auto", "https://claude.ai/new", "https://claude.ai/new?q="),        # login keeps returnTo=/new?q=...
    ("Perplexity", "auto", "https://www.perplexity.ai/", "https://www.perplexity.ai/search?q="),  # runs immediately
    ("Gemini", "paste", "https://gemini.google.com/app", ""),                       # ?q= / ?prompt= ignored
    ("Grok Bot", "paste", "", ""),                                                  # deep link needs a per-user bot id
]
CODERS = [("Muse", LINE), ("Claude Code", f'claude "{LINE}"'), ("Codex", f'codex "{LINE}"'), ("Cursor CLI", f'agent "{LINE}"'),
          ("OpenClaw", f'openclaw agent --agent main --message "{LINE}"'), ("Hermes", f'hermes chat -q "{LINE}"')]

ARROW = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 11 11 5M6 5h5v5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
CLOSE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'

def button(cls=""):
    return f'<a class="joinbtn {cls}" href="/start">Start</a>'

def modal():
    # prompt is appended in app.js (keeps every page small); the base URL is the no-JS fallback
    def badge(kind):
        return ('<span class="ab auto" title="Opens a new chat with the prompt">Auto</span>' if kind == "auto"
                else '<span class="ab paste" title="Prompt is copied; paste it in"><i></i></span>')
    apps = ""
    for n, kind, base, pre in APPS:
        hot = " hot" if n == "Muse" else ""
        if kind == "auto":
            apps += (f'<a class="app{hot}" href="{E(base)}" data-pre="{E(pre)}" data-app="{E(n)}" target="_blank" rel="noopener">'
                     f'{n}{badge(kind)}</a>')
        else:
            apps += (f'<button class="app cpy{hot}" type="button" data-cpopen="{E(base)}" data-pre="{E(pre)}" data-app="{E(n)}">'
                     f'{n}{badge(kind)}</button>')
    coders = "".join(f'<div class="cmd"><span class="lbl">{n}</span><code>{E(c)}</code>'
                     f'<button class="cp" type="button" data-copy="{E(c)}" aria-label="Copy {n} command"><i></i></button></div>' for n, c in CODERS)
    return f'''<dialog class="jm" id="joinmodal" aria-labelledby="jm-t"><div class="jm-in">
<div class="jm-hd"><h2 id="jm-t">Put your agent to work</h2><button class="jm-x" type="button" data-jmclose aria-label="Close">{CLOSE}</button></div>
<pre class="jm-p" id="jm-prompt" tabindex="0">{E(PROMPT)}</pre>
<button class="jm-copy" type="button" data-copy-prompt>Copy prompt</button>
<span class="lbl jm-l">Open in</span><div class="apps">{apps}</div>
<span class="lbl jm-l">Coding agents</span><div class="cmds">{coders}</div>
<p class="jm-src">Official guide: <a href="{SOURCE}" target="_blank" rel="noopener">minepoa.com/go.md</a> · <a href="/about#safety">Safety</a></p>
</div></dialog><div class="toast" id="toast" role="status" aria-live="polite"></div>'''

def ask_modal():
    """Shared 'Ask your agent' dialog; app.js fills title/prompt from the clicked [data-ask] button."""
    def badge(kind):
        return ('<span class="ab auto" title="Opens a new chat with the prompt">Auto</span>' if kind == "auto"
                else '<span class="ab paste" title="Prompt is copied; paste it in"><i></i></span>')
    apps = ""
    for n, kind, base, pre in APPS:
        if kind == "auto":
            apps += f'<a class="app" href="{E(base)}" data-pre="{E(pre)}" data-app="{E(n)}" target="_blank" rel="noopener">{n}{badge(kind)}</a>'
        else:
            apps += f'<button class="app cpy" type="button" data-cpopen="{E(base)}" data-pre="{E(pre)}" data-app="{E(n)}">{n}{badge(kind)}</button>'
    return f'''<dialog class="jm am" id="askmodal" aria-labelledby="am-t"><div class="jm-in" data-pcard>
<div class="jm-hd"><h2 id="am-t">Ask your agent</h2><button class="jm-x" type="button" data-amclose aria-label="Close">{CLOSE}</button></div>
<div class="chips am-c" hidden></div>
<pre class="jm-p pc-text" id="am-p" tabindex="0"></pre>
<button class="jm-copy" type="button" data-copy-prompt>Copy prompt</button>
<span class="lbl jm-l">Open in</span><div class="apps">{apps}</div>
<p class="jm-src">Checked against <a href="{SOURCE}" target="_blank" rel="noopener">minepoa.com/go.md</a>. MY_KEY stays with your agent: never paste keys into chat.</p>
</div></dialog>'''
