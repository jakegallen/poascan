"""1.26.89: POAScan's default join prompt is the mining-only v2.8 prompt, byte identical to what shipped from 1.26.67 to 1.26.88.
/api/v1/prompts/join serves it (default true, wallet_setup POASwap); /api/v1/prompts/combined stays available, default false;
/start copies it with one wallet setup line to POASwap and no combined button; the home page and llms.txt carry no combined text
as a prompt. Usage: python3 tools/miningonly_test.py"""
import hashlib, json, os, re, subprocess, sys, tempfile, time, urllib.request
from html import unescape
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
FAIL = []
def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok: FAIL.append(name)
# The published mining-only prompt (v2.8, 1.26.67 6375072 to 1.26.88 7e00135), pinned by length and hash per variant.
PINNED = {"full": (5539, "6762aa1cb3bf173a20f6d25af3045b10ef4463a962754e8f1f58dc28878b5cdd"),
          "chat-browse": (3778, "0e8281f4"), "connector": (3068, "c323d1f2")}
CORE = (5534, "76609ca7")   # the same template with the name slot as NAME: the join core POASwap's combined prompt ends with
from poascan import start as S, combined as CB
for v, (n, h) in PINNED.items():
    t = S.prompt("YOUR_NAME", v).encode()
    check(f"{v}: {n} bytes, sha256 {h[:8]}", len(t) == n and hashlib.sha256(t).hexdigest().startswith(h))
core = S.prompt("NAME", "full")
check("join core: 5,534 bytes, sha256 76609ca7", len(core.encode()) == CORE[0] and hashlib.sha256(core.encode()).hexdigest().startswith(CORE[1]))
check("the default prompt has no wallet setup, Emblem or POASwap in it", not any(x in S.prompt("YOUR_NAME").lower() for x in ("emblem", "poaswap", "agentwallet", "link-auto")))
if CB.TEXT: check("the combined prompt still ends with the join core (POASwap's dependency)", CB.TEXT.endswith(core))

import socket
tmp = tempfile.mkdtemp(); _s = socket.socket(); _s.bind(("127.0.0.1", 0)); port = _s.getsockname()[1]; _s.close(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, POASCAN_DB=os.path.join(tmp, "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", PORT=str(port), HOST="127.0.0.1")
env.pop("POASCAN_COMBINED_PROMPT", None)
subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def get(path):
    for _ in range(100):
        try:
            with urllib.request.urlopen(base + path, timeout=10) as r: return r.status, r.read().decode()
        except urllib.error.HTTPError as e: return e.code, e.read().decode()
        except Exception: time.sleep(0.2)
    raise SystemExit("server did not start")
try:
    j = json.loads(get("/api/v1/prompts/join")[1]); cl = json.loads(get("/api/v1/prompts/join?client=claude")[1])
    c = json.loads(get("/api/v1/prompts/combined")[1])
    check("/api/v1/prompts/join: the v2.8 text byte for byte, default true, wallet_setup https://poaswap.io",
          j["text"] == S.prompt("YOUR_NAME") and hashlib.sha256(j["text"].encode()).hexdigest() == PINNED["full"][1] and len(j["text"].encode()) == PINNED["full"][0]
          and j["default"] is True and j["wallet_setup"] == "https://poaswap.io" and j["prompt_version"] == "v2.8")
    check("/api/v1/prompts/join?client=claude: default true too", cl["default"] is True and cl["wallet_setup"] == "https://poaswap.io")
    check("/api/v1/prompts/join keeps combined_sha256 (POASwap reads it)", "combined_sha256" in j and j["combined_sha256"] == CB.SHA256)
    check("/api/v1/prompts/combined: still available when the slot ships, default false, default_prompt the join endpoint",
          c["default"] is False and c["default_prompt"] == "https://poascan.io/api/v1/prompts/join" and c["available"] is (CB.SHA256 is not None) and c["combined_sha256"] == CB.SHA256)
    st = get("/start")[1]; m = st[st.index("<main"):st.index("</main>")]
    pre = unescape(re.search(r'<pre class="pc-text jm-p" tabindex="0">([^<]*)</pre>', m).group(1))
    check("/start: the prompt it renders is one of the pinned mining-only variants",
          hashlib.sha256(pre.encode()).hexdigest()[:8] in {h[:8] for _, h in PINNED.values()})
    check("/start: exactly one POASwap line (wallet setup, https://poaswap.io), no combined button or combined text",
          m.lower().count("poaswap") == 2 and m.count("class=\"stwal\"") == 1 and '<p class="stwal">Wallet setup is separate, on <a href="https://poaswap.io" target="_blank" rel="noopener noreferrer" data-wallet>POASwap</a></p>' in m
          and "<span>Combined</span>" not in m and (CB.SHA256 or "x" * 64) not in m and "Be my Agent on POASwap" not in m and "Emblem" not in m)
    hm = get("/")[1]
    check("home: no combined prompt text or hash, header Start goes to /start", "Be my Agent on POASwap" not in hm and (CB.SHA256 or "x" * 64) not in hm and 'href="/start"' in hm)
    ll = get("/llms.txt")[1]
    check("llms.txt: the mining-only prompt in full, one wallet setup line, combined marked not the default",
          ("\n" + S.PROMPT + "\n") in ll and ll.count("Wallet setup is separate, on POASwap: https://poaswap.io\n") == 1
          and (not CB.SHA256 or "Combined prompt: POASwap's wallet setup prompt, not the default here.\nCombined prompt sha256: " + CB.SHA256 in ll)
          and "Be my Agent on POASwap" not in ll)
    oa = json.loads(get("/openapi.json")[1])["components"]["schemas"]
    check("OpenAPI documents default and wallet_setup on JoinPrompt, default and default_prompt on CombinedPrompt",
          {"default", "wallet_setup"} <= set(oa["JoinPrompt"]["properties"]) and {"default", "default_prompt"} <= set(oa["CombinedPrompt"]["properties"]))
finally:
    p.terminate(); p.wait(10)
check("CI runs this test", "python tools/miningonly_test.py" in open(os.path.join(ROOT, ".github", "workflows", "deploy.yml")).read())
check("no em or en dash in the files this change touches", not any(ch in open(os.path.join(ROOT, f), encoding="utf-8").read() for f in
      ("tools/miningonly_test.py", "poascan/start.py", "poascan/combined.py") for ch in "\u2014\u2013"))
print("FAILED:", len(FAIL)) if FAIL else print("all passed"); sys.exit(1 if FAIL else 0)
