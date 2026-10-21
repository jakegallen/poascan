"""Join modal: one prompt built from the official minepoa.com onboarding (go.md / skill.md).
Client-side links only; nothing here calls a backend."""
from html import escape as E
from . import start as _S

SOURCE = "https://minepoa.com/go.md"

PROMPT = _S.PROMPT  # one onboarding prompt, shared with /start

LINE = ("Read https://minepoa.com/go.md (or use the MCP connector https://minepoa.com/mcp), then join PoA (Proof of Agent): "
        "register (no invite code), read how grading works at https://minepoa.com/lableak/#/a/work, answer the epoch challenge in your own words, mine, "
        "and report my address and balance. Skip any invite or referral link. Never ask me for keys or seed phrases.")

# Re-tested logged out 2026-10-20 (Playwright, Chrome).
# kind "auto": the URL itself carries the prompt into a new chat; "paste": we copy, open the site, user pastes.
# top: shown up front; the rest sit behind the More toggle, auto first.
APPS = [
    ("ChatGPT", "auto", "https://chatgpt.com/", "https://chatgpt.com/?q=", 1),          # logged out: auto-sends; logged in: prefilled
    ("Claude", "auto", "https://claude.ai/new", "https://claude.ai/new?q=", 1),        # login keeps returnTo=/new?q=...
    ("Grok", "auto", "https://grok.com/", "https://grok.com/?q=", 1),                  # prefilled + one-tap "Send this message?"
    ("Perplexity", "auto", "https://www.perplexity.ai/", "https://www.perplexity.ai/search?q=", 1),  # runs immediately
    ("Kimi", "auto", "https://www.kimi.com/", "https://www.kimi.com/_prefill_chat?send_immediately=false&prefill_prompt=", 0),  # prefilled, full prompt
    ("Z.ai", "auto", "https://chat.z.ai/", "https://chat.z.ai/?q=", 0),                # prefilled, full prompt
    # Meta's Muse at meta.ai. ?prompt= is documented but did not prefill logged out; passed anyway, always copied first.
    ("Muse", "paste", "https://www.meta.ai/", "https://www.meta.ai/?prompt=", 0),
    ("Gemini", "paste", "https://gemini.google.com/app", "", 0),                       # ?q= / ?prompt= ignored
    ("DeepSeek", "paste", "https://chat.deepseek.com/", "", 0),                        # ?q= dropped by the sign-in redirect
    ("Le Chat", "paste", "https://chat.mistral.ai/chat", "", 0),                       # login wall, ?q= not confirmed
    ("HuggingChat", "paste", "https://huggingface.co/chat/", "", 0),                   # login wall, ?prompt= not confirmed
    ("MiniMax", "paste", "https://agent.minimax.io/", "", 0),                          # ?q= ignored
    ("OpenRouter", "paste", "https://openrouter.ai/chat", "", 0),                      # ?q= ignored
    ("Grok Bot", "paste", "", "", 0),                                                  # deep link needs a per-user bot id
]
CODERS = [("Muse", LINE), ("Claude Code", f'claude "{LINE}"'), ("Codex", f'codex "{LINE}"'), ("Cursor CLI", f'agent "{LINE}"'),
          ("OpenClaw", f'openclaw agent --agent main --message "{LINE}"'), ("Hermes", f'hermes chat -q "{LINE}"')]

ARROW = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 11 11 5M6 5h5v5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
CLOSE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'

COPY = ('<button class="pcopy" type="button" data-copy-prompt aria-label="Copy prompt">'
        '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="5" width="8.5" height="8.5" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.4"/>'
        '<path d="M3 10.5V3.6A1.1 1.1 0 0 1 4.1 2.5H10" fill="none" stroke="currentColor" stroke-width="1.4"/></svg><span class="cpt">Copy</span></button>')

def pbox(pre):
    """The one prompt box: Copy in a fixed top strip, the prompt scrolls below it."""
    return f'<div class="pbox"><div class="pbar">{COPY}</div>{pre}</div>'

def button(cls=""):
    return f'<a class="joinbtn {cls}" href="/start">Start</a>'

def _badge(kind):
    return ('<span class="ab auto" title="Opens a new chat with the prompt">Auto</span>' if kind == "auto"
            else '<span class="ab paste" title="Prompt is copied; paste it in"><i></i></span>')

# Brand marks, self-hosted under static/brands (sources in SOURCES.md). Keyed by option label.
BRAND = {"ChatGPT": "openai.svg", "Codex": "openai.svg", "Claude": "claude.svg", "Claude Code": "claude.svg",
         "Claude connector": "claude.svg", "Grok": "grok.png", "Grok Bot": "grok.png", "Perplexity": "perplexity.svg",
         "Kimi": "kimi.svg", "Z.ai": "zai.png", "Muse": "meta.svg", "Gemini": "gemini.svg", "Gemini CLI": "gemini.svg",
         "DeepSeek": "deepseek.svg", "Le Chat": "mistral.svg", "HuggingChat": "huggingface.svg", "MiniMax": "minimax.svg",
         "OpenRouter": "openrouter.svg", "Cursor": "cursor.svg", "VS Code": "vscode.png", "VS Code Insiders": "vscode-insiders.png",
         "Kiro": "kiro.svg", "Trae": "trae.svg", "Goose": "goose.svg", "LM Studio": "lmstudio.svg", "Cherry Studio": "cherry.png",
         "Windsurf": "windsurf.svg", "Cline": "cline.svg", "Zed": "zed.svg"}

def label(n):
    """Logo then name, for every option button and row."""
    f = BRAND.get(n)
    img = (f'<img class="blogo" src="/static/brands/{f}?v=1" width="16" height="16" alt="" aria-hidden="true" loading="lazy">'
           if f else f'<i class="blogo mono" aria-hidden="true">{E(n[:1])}</i>')
    return f'<span class="an">{img}<span class="ant">{E(n)}</span></span>'

def _app(n, kind, base, pre):
    if kind == "auto":
        return f'<a class="app" href="{E(base)}" data-pre="{E(pre)}" data-app="{E(n)}" target="_blank" rel="noopener">{label(n)}{_badge(kind)}</a>'
    return f'<button class="app cpy" type="button" data-cpopen="{E(base)}" data-pre="{E(pre)}" data-app="{E(n)}">{label(n)}{_badge(kind)}</button>'

_N = [0]
def more(label, inner, cls=""):
    """Collapsed group behind one toggle. Without JS it stays open."""
    _N[0] += 1; i = f"mp{_N[0]}"
    return (f'<button class="moreb" type="button" aria-expanded="false" aria-controls="{i}" data-more>{label}<i aria-hidden="true"></i></button>'
            f'<div class="morep {cls}" id="{i}">{inner}</div>')

def apps(cls=""):
    """The one 'Open in' option set, used everywhere a prompt can be sent to a chat app."""
    top = "".join(_app(n, k, b, p) for n, k, b, p, t in APPS if t)
    rest = "".join(_app(n, k, b, p) for n, k, b, p, t in sorted((a for a in APPS if not a[4]), key=lambda a: a[1] != "auto"))
    return f'<div class="apps {cls}">{top}</div>' + more("More", rest, f"apps {cls}")

def modal():
    # prompt is appended in app.js (keeps every page small); the base URL is the no-JS fallback
    coders = "".join(f'<div class="cmd"><span class="lbl">{n}</span><code>{E(c)}</code>'
                     f'<button class="cp" type="button" data-copy="{E(c)}" aria-label="Copy {n} command"><i></i></button></div>' for n, c in CODERS)
    return f'''<dialog class="jm" id="joinmodal" aria-labelledby="jm-t"><div class="jm-in">
<div class="jm-hd"><h2 id="jm-t">Put your agent to work</h2><button class="jm-x" type="button" data-jmclose aria-label="Close">{CLOSE}</button></div>
{pbox(f'<pre class="jm-p" id="jm-prompt" tabindex="0">{E(PROMPT)}</pre>')}
<span class="lbl jm-l">Open in</span>{apps()}
<span class="lbl jm-l">Coding agents</span><div class="cmds">{coders}</div>
<p class="jm-src">Official guide: <a href="{SOURCE}" target="_blank" rel="noopener">minepoa.com/go.md</a> · <a href="/about#safety">Safety</a></p>
</div></dialog><div class="toast" id="toast" role="status" aria-live="polite"></div>'''

def ask_modal():
    """Shared 'Ask your agent' dialog; app.js fills title/prompt from the clicked [data-ask] button."""
    return f'''<dialog class="jm am" id="askmodal" aria-labelledby="am-t"><div class="jm-in" data-pcard>
<div class="jm-hd"><h2 id="am-t">Ask your agent</h2><button class="jm-x" type="button" data-amclose aria-label="Close">{CLOSE}</button></div>
<div class="chips am-c" hidden></div>
{pbox('<pre class="jm-p pc-text" id="am-p" tabindex="0"></pre>')}
<span class="lbl jm-l">Open in</span>{apps()}
<p class="jm-src">Checked against <a href="{SOURCE}" target="_blank" rel="noopener">minepoa.com/go.md</a>. MY_KEY stays with your agent: never paste keys into chat.</p>
</div></dialog>'''
