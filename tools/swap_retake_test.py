"""Swap take wording: after the first real fill, a failed or timed out take can still create a nonce account
and a second take broadcasts the held payment. So no surface may tell an Agent to re-call swap-take until filled or that
re-calling is safe. The BUY templates and the swap FAQ moved to POASwap with the swap page.
Checks the source tree and every rendered surface (/about with its FAQ JSON-LD, llms.txt, llms-full.txt, openapi.json,
openapi-gpt.json, MCP tools/list and prompts/list).
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
    check(f"/about renders ({c}); the swap FAQ moved to POASwap", c == 200 and "How swaps work" not in about)
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
