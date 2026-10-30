"""Join with Anything on /start (1.26.238, lanes 1.26.240). The connector is never a way to join.
Hosted chat apps (tier connector without a command: Claude, ChatGPT, Grok and the others in data/clients.json):
1 Create your agent on minepoa.com (its page solves the signup puzzle; POAScan only links, keyless), 2 Let {App} mine
(optional, the connector), 3 Paste the prompt. Apps that run code (Grok Bot, Cursor, Codex): 1 the prompt (Codex: its
run-once command too), 2 the connector (optional). Not tested yet notes; the joins paused notice under step 1 and in the
Ask dialog while /api/join-pow answers 503. The prompt text is unchanged. Usage: python3 tools/connector_first_test.py"""
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
check("step 1: the exact line and Join on minepoa.com, new tab, no query", S.S1_HOSTED in h and S.S1_HOSTED == "Open minepoa.com and complete the signup there. Your browser solves the signup puzzle, and minepoa creates your agent. POAScan never sees your key."
      and '<a class="jwbtn" href="https://minepoa.com/" target="_blank" rel="noopener noreferrer" data-mpjoin>Join on minepoa.com</a>' in h)
check("step 2: for mining after you join, not for joining; the URL with copy; where; turn on; the ChatGPT note",
      "Add the PoA connector so ChatGPT can answer challenges and check in for the agent you created. For mining after you join, not for joining." in h
      and '<code data-cfval>https://minepoa.com/mcp</code><button class="cp" type="button" data-copy="https://minepoa.com/mcp" data-cfcopy' in h
      and f'Add it in ChatGPT: </span><span data-cfwhere>{gpt["connector"]["where"]}</span>' in h and "<li>Turn it on for the chat.</li>" in h
      and '<p class="cfn" data-cfnote>Needs a paid ChatGPT plan with developer mode turned on.</p>' in h and "Open ChatGPT settings" in h)
check("the connector is never a way to join: no fallback paste line, no Add the connector first", "Can't add connectors" not in h and "Add the connector first" not in h and "data-cffb" not in hr)
cx = unescape(S.go_block(by["codex"]))
check("Codex (code app): step 1 the prompt line, its run-once command, then the button; no step 3",
      S.s1_code("Codex") in cx and S.s1_code("Codex") == "Copy the prompt and paste it into Codex. This is the step that creates your PoA agent."
      and pos("1. Create your agent", cx) < pos("codex mcp add poa --url https://minepoa.com/mcp", cx) < pos("data-slot1>", cx) < pos("data-go ", cx) < pos("data-cfirst", cx)
      and " data-s1join hidden" in cx and " data-s3h hidden" in cx and '<div class="jwslot" data-slot3></div>' in cx)
check("Codex step 2: optional, the connector does not create a new agent, added by the step 1 command",
      "2. Let Codex mine (optional)" in cx and "Add the PoA connector so Codex can answer challenges and check in for the agent you just created. The connector does not create a new agent." in cx
      and "The command in step 1 adds it." in cx and " data-cflines hidden" in cx and " data-conrow hidden" in cx)
for k in ("cursor", "grok-bot"):
    g = S.go_block(by[k])
    check(f"{k}: step 1 with the button and Not tested yet, no connector step", S.s1_code(by[k]["name"]) in g and " data-cfirst hidden" in g
          and '<p class="stnt" data-untested><span class="tag">Not tested yet</span><span>Uses the default prompt.</span></p>' in g and pos("data-slot1>", g) < pos("data-go ", g))
check("tested apps: no Not tested yet note", " data-untested hidden" in hr and " data-untested hidden" in S.go_block(by["claude"]))
check("Muse (no prompt): no steps, no note", " data-untested hidden" in S.go_block(by["muse"]) and " data-s1h hidden" in S.go_block(by["muse"]))
check("radios carry tested and the note for app.js", ' data-tested="1"' in S._chat(gpt) and ' data-tested' not in S._chat(by["cursor"]) and 'data-cnote="Needs a paid ChatGPT plan' in S._chat(gpt))
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("app.js mirrors the lanes: the same lines, the button moves to its slot", S.S1_HOSTED in js and "This is the step that creates your PoA agent." in js
      and "For mining after you join, not for joining." in js and "The connector does not create a new agent." in js and "var slot=h?sl3:sl1" in js and "cffb" not in js)
P = "New PoA signups are paused while minepoa hardens its API. Check back later. Existing balances and pending grades are safe."
check("open (200): no paused notice on /start or in the Ask dialog", S.join_halt_html() == "" and "data-joinhalt" not in h and "data-joinhalt" not in J.ask_modal())
M.join_halt = lambda: dict(since_ts=1793000000, as_of_ts=1793000300)
ph = unescape(S.go_block(gpt))
check("halted (503): the exact notice under step 1 (under Join on minepoa.com), the button still there", P in ph and pos("data-mpjoin", ph) < pos(P, ph) < pos("data-cfirst", ph) and "data-go " in ph)
pc = unescape(S.go_block(by["codex"]))
check("halted: under step 1 for code apps too, after the button", pos("data-go ", pc) < pos(P, pc) < pos("data-cfirst", pc))
check("halted: the notice in the Ask dialog too", P in unescape(J.ask_modal()))
check("no key in any link or prefill", not re.search(r"(key|api_key|token)=", h + cx))
hf = S.hash_fields()
check("the prompt is unchanged: v2.9.2 template 7a2a6016, combined 2cce09a9", hf["template_sha256"].startswith("7a2a6016") and hf["combined_sha256"].startswith("2cce09a9"))
check("no em or en dash", not re.search("[\u2013\u2014]", h + cx + ph + js[js.index("1.26.240"):js.index("1.26.240") + 3000]))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
