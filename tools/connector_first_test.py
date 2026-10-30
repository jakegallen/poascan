"""1.26.238 (Join with Anything, stage 1): connector-tier apps (ChatGPT, Claude, Grok and the others in data/clients.json)
show "Add the connector first" before the copy or open button: copy the MCP URL (or run the app's command), where to add it,
turn it on for the chat, the app's note (ChatGPT: paid plan, developer mode), its settings link, then a fallback for anyone
who can't add connectors. Apps not checked live get a Not tested yet note; the joins paused notice sits on /start and in
the Ask dialog while /api/join-pow answers 503 halted. The prompt text is unchanged.
Usage: python3 tools/connector_first_test.py"""
import os, re, sys, tempfile, json
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "c.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, start as S, clients as C, onboarding_prompt as OP
from html import unescape
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
top, rest = S.chats(); by = {c["id"]: c for c in top + rest}
gpt = by["chatgpt"]; h = S.go_block(gpt)
check("ChatGPT: the step comes before the button", 'data-cfirst' in h and ' data-cfirst hidden' not in h and h.index("data-cfirst") < h.index("data-gorow"))
check("the step reads Add the connector first", '<p class="cfh">Add the connector first</p>' in h)
check("the MCP URL with a one-click copy", '<code data-cfval>https://minepoa.com/mcp</code><button class="cp" type="button" data-copy="https://minepoa.com/mcp" data-cfcopy' in h)
check("ChatGPT's steps: add it in ChatGPT with the where text, turn it on for the chat", f'<span data-cfin>Add it in ChatGPT: </span><span data-cfwhere>{gpt["connector"]["where"]}</span>' in h
      and "Plugins, +, Add custom MCP server, No authentication." in h and '<li data-cfon>Turn it on for the chat.</li>' in h)
check("ChatGPT's note: paid plan with developer mode", '<p class="cfn" data-cfnote>ChatGPT needs a paid plan with developer mode on.</p>' in h)
check("its settings link inside the step", 'href="https://chatgpt.com/plugins"' in h and "Open ChatGPT settings" in h and h.index("data-conrow") < h.index("data-gorow"))
check("the fallback for anyone who can't add connectors, after the steps and before the button",
      "Can&#x27;t add connectors? <button type=\"button\" data-cffb>Copy the prompt to paste instead</button>" in h and h.index("data-cfnote") < h.index("data-cffb") < h.index("data-gorow"))
cl = S.go_block(by["claude"])
check("Claude: the same steps, no plan note", "Add it in Claude: " in cl and " data-cfnote hidden" in cl and " data-cfirst hidden" not in cl)
check("tested apps: no Not tested yet note", " data-untested hidden" in h and " data-untested hidden" in cl)
for k in ("cursor", "grok-bot", "codex"):
    check(f"{k}: Not tested yet, default prompt", '<p class="stnt" data-untested><span class="tag">Not tested yet</span><span>Uses the default prompt.</span></p>' in S.go_block(by[k]))
check("Muse (no prompt): no note", " data-untested hidden" in S.go_block(by["muse"]))
check("radios carry tested and the note for app.js", ' data-tested="1"' in S._chat(gpt) and ' data-tested' not in S._chat(by["cursor"]) and 'data-cnote="ChatGPT needs' in S._chat(gpt))
cx = S.go_block(by["codex"])
check("Codex: run the command once instead of the URL, no turn on step, no settings link", "codex mcp add poa --url https://minepoa.com/mcp" in unescape(cx) and " data-conrow hidden" in cx
      and "<span data-cfl1>Run this once</span>" in cx and "<li data-cfon hidden>" in cx)
for k in ("cursor", "grok-bot"):
    check(f"{k} (full tier): the step is hidden", " data-cfirst hidden" in S.go_block(by[k]))
radio = S._chat(gpt)
check("the ChatGPT radio carries the where text for app.js", f'data-cwhere="{gpt["connector"]["where"]}"' in unescape(radio).replace("&#x27;", "'"))
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("app.js fills the steps for the picked app, the note, the fallback copy and the untested note", 'tier=="connector"&&!!r.dataset.ccopy&&k!="mcp"' in js and "cfc.dataset.copy=r.dataset.ccopy" in js
      and "cfw.textContent=r.dataset.cwhere" in js and "hide(cfs,!cf)" in js and 'hide(ut,none||k=="mcp"||r.dataset.tested=="1")' in js and "t=TPL.full" in js and "r.dataset.cnote" in js)
from poascan import maint as M, join as J
P = "New PoA signups are paused while minepoa hardens its API. Check back later. Existing balances and pending grades are safe."
M.join_halt = lambda: None
check("open (200): no paused notice on /start or in the Ask dialog", S.join_halt_html() == "" and "data-joinhalt" not in J.ask_modal())
M.join_halt = lambda: dict(since_ts=1793000000, as_of_ts=1793000300)
ph = S.join_halt_html()
check("halted (503): the exact public notice", f"<span>{P}</span>" in unescape(ph) and "Joins paused" in ph)
check("halted: the notice in the Ask dialog too", "data-joinhalt" in J.ask_modal() and P in unescape(J.ask_modal()))
hf = S.hash_fields()
check("the prompt is unchanged: v2.9.2 template 7a2a6016, combined 2cce09a9", hf["template_sha256"].startswith("7a2a6016") and hf["combined_sha256"].startswith("2cce09a9"))
check("no em or en dash", not re.search("[\u2013\u2014]", h + cx + radio + ph))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
