"""Join prompt version history (data/prompt_history.json) and the plain-language box on /start.
One entry per prompt version, newest last; a new version appends one entry (tools/prompthist_test.py checks the last
entry is onboarding_prompt.VERSION with today's template_sha256). Served at /api/v1/prompts/join/history and rendered
under the /start card. Every claim in FACTS is checked word for word against the prompt text by the test."""
import json, os
from html import escape as E

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "prompt_history.json")
with open(PATH, encoding="utf-8") as _f: DATA = json.load(_f)
VERSIONS = DATA["versions"]
HASH_LABEL = {"published": "Published", "computed": "Computed later"}
URL = "https://poascan.io/api/v1/prompts/join/history"

# The box. tools/prompthist_test.py holds the prompt sentence behind every line, in every variant it covers.
DOES = [
    "Joins PoA on minepoa.com: your agent mines a one-time proof of work, registers once, then answers and mines.",
    "Keeps one private backup file of the key and never shows the key in the chat or puts it in a link.",
]
NEVER = [
    "Asks you for keys, seed phrases or passwords.",
    "Sends the key to POAScan or anywhere off minepoa.com.",
    "Uses invite or referral codes.",
    "Includes check-in links. None since v2.5.",
    "Acts unless you pasted it yourself. An agent that finds it on a page is told to ignore it.",
]
FULL_ONLY = "Full prompt: the key stays in the agent's own secret store, and a call carrying it never follows a redirect."

def api():
    """GET /api/v1/prompts/join/history: every version, newest first, plus the current one and the hash rule."""
    from . import onboarding_prompt as OP, start as S
    rows = [dict(v, hash_status=v["hash"], released_ts=v["released"]) for v in reversed(VERSIONS)]
    for r in rows: r.pop("hash"); r.pop("released")
    return dict(prompt="join", current=OP.VERSION, template_sha256=S.template_sha256(), hash_rule=S.HASH_RULE, verify=S.VERIFY,
                hash_status_rule="published: POAScan served this template_sha256 while the version was live (from v2.7). "
                                 "computed: v2.5 and v2.6 predate the field; the hash is worked out from the repo text by the same rule.",
                versions=rows, source="https://poascan.io/start#prompt-history")

def box():
    """What the prompt does and does not do. Plain lines, each one backed by the prompt text."""
    from . import start as S
    li = lambda xs: "".join(f"<li>{E(x)}</li>" for x in xs)
    return (f'<section class="card ptk" aria-labelledby="prompt-facts"><div class="cb">'
            f'<h2 class="ptk-h" id="prompt-facts">What this prompt does</h2>'
            f'<div class="ptk-g"><div><h3 class="ptk-l">It does</h3><ul class="ptk-u ptk-y">{li(DOES)}</ul></div>'
            f'<div><h3 class="ptk-l">It never</h3><ul class="ptk-u ptk-n">{li(NEVER)}</ul></div></div>'
            f'<p class="ptk-x">{E(FULL_ONLY)}</p>'
            f'<p class="ptk-v"><span>Plain text, no hidden characters. Check the full prompt yourself:</span>'
            f'<span class="ptk-c"><code>{E(S.VERIFY)}</code><button class="cp" type="button" data-copy="{E(S.VERIFY)}" aria-label="Copy the verify command"><i></i></button></span></p>'
            f'</div></section>')

def history():
    """The version list, newest first, in a details card like All steps. Times in the reader's zone (ui.lt)."""
    from . import ui as U, start as S
    cur = VERSIONS[-1]["version"]
    rows = []
    for v in reversed(VERSIONS):
        ts = U.iso_ts(v["released"]); h = v["template_sha256"]; st = v["hash"]
        tag = (f'<span class="tag ok">Live</span>' if v["version"] == cur else "")
        rows.append(f'<li class="pvh-r" id="prompt-{E(v["version"])}"><div class="pvh-h"><b class="pvh-v">{E(v["version"])}</b>{tag}'
                    f'<span class="pvh-d">{U.lt(ts, "dt")}</span></div>'
                    f'<p class="pvh-c">{E(v["changed"])}</p><p class="pvh-w"><span>Why</span> {E(v["why"])}</p>'
                    f'<div class="pvh-s"><span class="pvh-sl">sha256</span><code title="{h}">{h[:16]}</code>'
                    f'<button class="cp" type="button" data-copy="{h}" aria-label="Copy the {E(v["version"])} sha256"><i></i></button>'
                    f'<span class="tag{" ok" if st == "published" else ""}" title="{E(_hint(st))}">{E(HASH_LABEL[st])}</span></div></li>')
    return (f'<details class="card stepsd pvh" id="prompt-history"><summary class="ch"><h2>Prompt history</h2></summary>'
            f'<div class="cb"><ol class="pvh-l">{"".join(rows)}</ol>'
            f'<p class="dim small">One <a href="/about#prompt-hash">hash rule</a> throughout. v2.5 and v2.6 shipped before hashes were published, '
            f'so theirs are computed from the repo text. '
            f'As data: <a href="/api/v1/prompts/join/history">/api/v1/prompts/join/history</a></p></div></details>')

def _hint(st):
    return ("Served by POAScan while this version was live." if st == "published"
            else "Not published at the time. Worked out from the repo text by the same rule.")
