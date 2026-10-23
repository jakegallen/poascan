"""Swap take wording: after the first real fill, a failed or timed out take can still create a nonce account
and a second take broadcasts the held payment. So no surface may tell an Agent to re-call swap-take until filled or that
re-calling is safe. The BUY template and the FAQ say: after pending_receipt, take again once, only on receipt_ready true;
after a failure or timeout, check status before any re-take; never loop; stop at Filled, Expired or Failed.
Checks the source tree and every rendered surface (BUY template live and coming soon, /about with its FAQ JSON-LD,
llms.txt, llms-full.txt, openapi.json, openapi-gpt.json, MCP tools/list and prompts/list).
The BUY_TOKEN template reads swap-receipt at most once every 30 seconds for up to 10 minutes, then stops and reports.
Usage: python3 tools/swap_retake_test.py"""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

BANNED = [re.compile(p, re.I) for p in (r"re-?call(ing|ed|s)?\b[^.]{0,60}until[^.]{0,30}fill", r"re-?calling\s+(with the same offer\s+)?is\s+safe",
                                         r"safe\s+to\s+re-?call", r"call again until[^.]{0,20}fill", r"until\s+(the\s+)?stage\s+is\s+filled")]
def bad(text): return [m.group(0) for r in BANNED for m in r.finditer(text)]

# ---- the patterns catch the old wording (so a pass below means something)
OLD = ["if it returns pending_receipt, re-call until stage is filled.", "Re-call until the stage is filled.",
       "Re-call swap-take with the same offer. Re-calling is safe.", "Call again until filled. Re-calling with the same offer is safe."]
check("patterns catch every old phrasing", all(bad(t) for t in OLD))

# ---- source tree (the CHANGELOG quotes history; this test quotes the old wording)
SKIP = {os.path.join(ROOT, "CHANGELOG.md"), os.path.abspath(__file__)}
hits = []
for d, ds, fs in os.walk(ROOT):
    ds[:] = [x for x in ds if x not in (".git", "node_modules", "__pycache__", "data")]
    for f in fs:
        p = os.path.join(d, f)
        if p in SKIP or not f.endswith((".py", ".md", ".txt", ".json", ".js", ".html", ".toml")): continue
        try: t = open(p, encoding="utf-8").read()
        except Exception: continue
        hits += [(os.path.relpath(p, ROOT), h) for h in bad(t)]
check(f"no re-call until filled / re-calling is safe wording in the tree {hits}", not hits)

# ---- the BUY template, live and coming soon
from poascan.swap import prompts as P, config as C, faq as F
for live in (True, False):
    C.SWAPS_LIVE = live; buy = P.templates()["buy"]
    check(f"BUY (live={live}): no banned wording", not bad(buy))
    check(f"BUY (live={live}): take again once, only on receipt_ready true", "call swap-take again once, only when" in buy and "receipt_ready true" in buy)
    check(f"BUY (live={live}): status before any re-take, never loop, stop states", "check status" in buy and "before any re-take" in buy
          and "Never loop." in buy and "Stop at Filled, Expired or Failed." in buy)
    check(f"BUY (live={live}): keeps the payment rule, no dashes, no referral code", "Never send payment outside the network" in buy
          and not re.search("[\u2013\u2014]", buy) and "referral" not in buy.lower().replace("don't use any referral", ""))
    check(f"BUY (live={live}): no new POASwap mention, no fee line", "poaswap" not in buy.lower() and "1%" not in buy)
    tok = P.templates()["buy_token"]
    check(f"BUY_TOKEN (live={live}): no unbounded poll until receipt_ready", not re.search(r"poll[^.]{0,60}until receipt_ready", tok, re.I))
    check(f"BUY_TOKEN (live={live}): swap-receipt read at most once every 30 seconds for up to 10 minutes", "at most once every 30 seconds for up to 10 minutes" in tok)
    check(f"BUY_TOKEN (live={live}): stops and reports after the bound, no broadcast, never keeps polling", "stop and tell me" in tok
          and "don't broadcast" in tok and "never keep polling" in tok)
    check(f"BUY_TOKEN (live={live}): no dashes, no POASwap mention", not re.search("[\u2013\u2014]", tok) and "poaswap" not in tok.lower())
qa = dict((q, a) for q, a in F.PAGE["qa"] if isinstance(a, str))
tout = qa["What if a take times out?"]; how = qa["How does a buy work?"]
check("FAQ timeout answer: status before any re-take, why, never loop, stop states", "Check status before any re-take" in tout and "nonce account" in tout
      and "Never loop." in tout and "Stop at Filled, Expired or Failed." in tout and not bad(tout))
check("FAQ buy answer: take again once, only on receipt_ready true", "call swap-take again once, only when a swap-receipt read shows receipt_ready true" in how and not bad(how))
check("FAQ answers: no dashes, no POASwap, no fee", not re.search("[\u2013\u2014]", tout + how) and "poaswap" not in (tout + how).lower() and "1%" not in tout + how)

# ---- rendered surfaces from a running server
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def get(u, data=None, h=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, data, h or {}), timeout=20) as f: return f.status, f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace")
port = free_port(); base = f"http://127.0.0.1:{port}"; tmp = tempfile.mkdtemp()
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "r.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try: get(base + "/api/health"); break
        except Exception: time.sleep(0.2)
    c, about = get(base + "/about")
    check(f"/about renders ({c}) with the new FAQ wording", c == 200 and "Check status before any re-take" in about and "receipt_ready true" in about)
    for path in ("/about", "/llms.txt", "/llms-full.txt", "/openapi.json", "/openapi-gpt.json"):
        c, t = get(base + path); check(f"{path} ({c}): no banned wording", c == 200 and not bad(t))
    for m in ("tools/list", "prompts/list"):
        c, t = get(base + "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": m}).encode(), {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        check(f"MCP {m} ({c}): no banned wording", c == 200 and not bad(t))
finally:
    srv.terminate()
    try: srv.wait(10)
    except Exception: srv.kill()
print("\n%d failure(s)" % len(fails) if fails else "\nall ok"); sys.exit(1 if fails else 0)
