"""Combined prompt hash slot (poascan/combined.py). Absent slot (poascan/combined_prompt.txt, as shipped today): combined_sha256 is null on
/api/v1/prompts/join (with and without ?client=), /api/v1/prompts/combined and MCP get_onboarding_steps, and nothing new renders on /start,
the Join dialog, /about, llms.txt or the MCP tool list. Present (a test file via POASCAN_COMBINED_PROMPT): one SHA-256 by the join rule, the
same on every surface, recomputable from the served text. Bad files (CR, BOM, empty, extra newline) publish nothing. Join prompt unchanged.
Usage: python3 tools/combined_hash_test.py"""
import hashlib, json, os, re, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import combined as CB, start as S
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

TS = "6762aa1cb3bf173a20f6d25af3045b10ef4463a962754e8f1f58dc28878b5cdd"
tmp = tempfile.mkdtemp()
def wr(name, data):
    p = os.path.join(tmp, name); open(p, "wb").write(data); return p

# ---- the slot and its rule, no server
# 1.26.74: POASwap's combined prompt (https://poaswap.io/start/prompt.txt), byte identical. It ends with the v2.8 join core:
# the full template with the name slot filled as NAME (/api/v1/prompts/join?name=NAME), sha256 76609ca7, 5,534 characters.
SHIPPED, SHIPPED_LEN = "58bf46a1c02cc77657c7829d1d801e48fde00e6c4469d7609e715f96f9c086db", 9700
CORE = "76609ca76b599e8cad5711dcf960fbe83b5c107db3d48f26cadc8c6d49d35d96"
if os.path.exists(CB.SLOT):   # once POASwap's text lands, the shipped file must follow the rule
    t, h, err = CB.load(CB.SLOT); raw = open(CB.SLOT, "rb").read()
    check("shipped combined_prompt.txt follows the rule (UTF-8, LF only, no BOM, at most one trailing LF, not empty)", err is None and h is not None)
    check("shipped slot is POASwap's text byte for byte: 9,700 characters, no trailing newline, sha256 58bf46a1", raw == t.encode() and len(t) == SHIPPED_LEN and h == SHIPPED == CB.SHA256 == hashlib.sha256(raw).hexdigest())
    core = S.prompt("NAME", "full")
    check("shipped text ends with the v2.8 join core (full template, name slot NAME, 5,534 characters, sha256 76609ca7), once",
          t.endswith(core) and t.count(core) == 1 and len(core) == 5534 and hashlib.sha256(core.encode()).hexdigest() == CORE)
    check("shipped text: no em or en dash", not any(c in t for c in "\u2014\u2013"))
else:
    check("slot absent: TEXT, SHA256 and ERROR are None", CB.TEXT is None and CB.SHA256 is None and CB.ERROR is None and CB.load(os.path.join(tmp, "none.txt")) == (None, None, None))
    check("slot absent: hash_fields carries combined_sha256 null", S.hash_fields()["combined_sha256"] is None and S.hash_fields("connector")["combined_sha256"] is None)
    check("slot absent: the phash line is byte for byte the v2.7 one", S.phash() == f'<p class="phash"><button type="button" data-phash="{TS}" title="Template sha256 {TS}" aria-label="Copy the template sha256"><span>Prompt v2.8</span><span>sha256 <code>{TS[:12]}</code></span></button><a href="/about#prompt-hash">Verify</a></p>')
TXT = "Combined prompt slot test text.\nSecond line, YOUR_NAME left in place."
H = hashlib.sha256(TXT.encode()).hexdigest()
check("one trailing LF is dropped; the hash is of the text without it", CB.load(wr("a.txt", (TXT + "\n").encode())) == (TXT, H, None) and CB.load(wr("b.txt", TXT.encode())) == (TXT, H, None))
for nm, data, why in (("crlf", TXT.replace("\n", "\r\n").encode(), "CR newline"), ("bom", ("\ufeff" + TXT).encode(), "BOM"), ("empty", b"\n", "empty"),
                      ("blank", b"  \n\n", "empty"), ("two", (TXT + "\n\n").encode(), "more than one trailing newline"), ("latin1", "caf\xe9".encode("latin-1"), "not UTF-8")):
    check(f"bad file ({nm}) publishes nothing: {why}", CB.load(wr(nm + ".txt", data)) == (None, None, why))
check("join prompt template_sha256 unchanged (6762aa1c, v2.8)", S.template_sha256() == TS)
check("Dockerfile ships the slot with poascan/ (COPY poascan/ poascan/)", "COPY poascan/ poascan/" in open(os.path.join(ROOT, "Dockerfile")).read())
check("CI runs this test", "python tools/combined_hash_test.py" in open(os.path.join(ROOT, ".github", "workflows", "deploy.yml")).read())
check("no em or en dash in the module or this test", not any(c in open(os.path.join(ROOT, f), encoding="utf-8").read() for f in ("poascan/combined.py", "tools/combined_hash_test.py") for c in "\u2014\u2013"))

# ---- live server, absent then present
def serve(extra):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, f"d{port}.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", **extra)
    env.pop("POASCAN_COMBINED_PROMPT", None) if not extra else None
    subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    return p, base

def surfaces(base):
    def get(path, data=None, hd=None):
        try:
            r = urllib.request.urlopen(urllib.request.Request(base + path, data, hd or {}), timeout=30); return r.status, r.read().decode()
        except urllib.error.HTTPError as e: return e.code, e.read().decode()
    HD = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    rpc = lambda m, pr=None: json.loads(get("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": pr or {}}).encode(), HD)[1])
    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "combined_test", "version": "0"}})
    d = dict(join=json.loads(get("/api/v1/prompts/join")[1]), claude=json.loads(get("/api/v1/prompts/join?client=claude")[1]),
             muse=json.loads(get("/api/v1/prompts/join?client=muse")[1]), comb=get("/api/v1/prompts/combined"), alias=get("/api/prompts/combined"),
             bad=get("/api/v1/prompts/combined?x=1")[0], start=get("/start")[1], frag=get("/fragment/join")[1], about=get("/about")[1],
             llms=get("/llms.txt")[1], llmsf=get("/llms-full.txt")[1], oa=json.loads(get("/openapi.json")[1]),
             mcp=rpc("tools/call", {"name": "get_onboarding_steps", "arguments": {}})["result"]["structuredContent"],
             tl=[t for t in rpc("tools/list")["result"]["tools"] if t["name"] == "get_onboarding_steps"][0]["description"])
    return d

def common(tag, d):
    oa = d["oa"]
    check(f"{tag}: OpenAPI documents combined_sha256 on JoinPrompt and /api/v1/prompts/combined", "combined_sha256" in oa["components"]["schemas"]["JoinPrompt"]["properties"]
          and "/api/v1/prompts/combined" in oa["paths"] and "CombinedPrompt" in oa["components"]["schemas"])
    check(f"{tag}: /api/v1/prompts/combined 200, /api alias identical, any parameter 400", d["comb"][0] == 200 and d["alias"] == d["comb"] and d["bad"] == 400)
    check(f"{tag}: join prompt unchanged on the API (6762aa1c)", d["join"]["template_sha256"] == TS == d["claude"]["template_sha256"] and d["mcp"]["template_sha256"] == TS)

p, base = serve({"POASCAN_COMBINED_PROMPT": os.path.join(tmp, "none.txt")})   # absent, even once the shipped slot exists
try:
    d = surfaces(base); common("absent", d); c = json.loads(d["comb"][1])
    check("absent: combined_sha256 null on /prompts/join (no client, claude, no-path muse) and MCP get_onboarding_steps",
          all("combined_sha256" in x and x["combined_sha256"] is None for x in (d["join"], d["claude"], d["muse"], d["mcp"])))
    check("absent: /api/v1/prompts/combined available false, text, combined_sha256 and verify null", c["available"] is False and c["text"] is None and c["combined_sha256"] is None and c["verify"] is None)
    check("absent: nothing new renders on /start, the Join dialog, /about, llms.txt or the MCP tool description; llms-full.txt has no hash line",
          not any(re.search(r"combined_sha256|[Cc]ombined prompt|combined-hash|prompts/combined|<span>Combined</span>", x) for x in (d["start"], d["frag"], d["about"], d["llms"], d["tl"]))
          and "Combined prompt sha256" not in d["llmsf"])   # llms-full.txt lists every OpenAPI path, so it names the (null) endpoint
finally:
    p.terminate(); p.wait(10)

p, base = serve({"POASCAN_COMBINED_PROMPT": wr("combined.txt", (TXT + "\n").encode())})
try:
    d = surfaces(base); common("present", d); c = json.loads(d["comb"][1])
    check("present: /api/v1/prompts/combined serves the text and its hash, recomputable (jq -j .text | sha256sum)",
          c["available"] is True and c["text"] == TXT and c["combined_sha256"] == H == hashlib.sha256(c["text"].encode()).hexdigest() and c["verify"] == CB.VERIFY)
    check("present: the same combined_sha256 on /prompts/join (no client, claude, muse) and MCP", all(x["combined_sha256"] == H for x in (d["join"], d["claude"], d["muse"], d["mcp"])))
    btn = f'<button type="button" data-phash="{H}" title="Combined prompt sha256 {H}" aria-label="Copy the combined prompt sha256"><span>Combined</span><span>sha256 <code>{H[:12]}</code></span></button>'
    sm = d["start"][d["start"].index("<main"):d["start"].index("</main>")]
    check("present: /start and the Join dialog show the combined button once, after the template button, before Verify",
          sm.count(btn) == 1 and d["frag"].count(btn) == 1 and sm.index(f'data-phash="{TS}"') < sm.index(btn) < sm.index('href="/about#prompt-hash"'))
    check("present: /about#prompt-hash has the combined paragraph with the hash and verify command", 'id="combined-hash"' in d["about"] and H in d["about"] and "prompts/combined | jq -j .text | sha256sum" in d["about"])
    check("present: llms.txt and llms-full.txt carry Combined prompt sha256 after the template hash",
          all(("Template sha256: " + TS) in x and ("Combined prompt sha256: " + H) in x and x.index(TS) < x.index(H) for x in (d["llms"], d["llmsf"])))
    check("present: the MCP tool description names combined_sha256", "combined_sha256" in d["tl"])
    check("present: no em or en dash on any surface that carries the hash", not any(ch in d["about"] + d["llms"] + d["tl"] + sm for ch in "\u2014\u2013"))
finally:
    p.terminate(); p.wait(10)
if os.path.exists(CB.SLOT):
    p, base = serve({})   # the slot as shipped in the image
    try:
        d = surfaces(base); c = json.loads(d["comb"][1])
        check("shipped: /api/v1/prompts/combined available, text 9,700 characters, combined_sha256 58bf46a1, same on /prompts/join, claude and MCP",
              c["available"] is True and len(c["text"]) == SHIPPED_LEN and c["combined_sha256"] == SHIPPED and all(x["combined_sha256"] == SHIPPED for x in (d["join"], d["claude"], d["mcp"])))
        check("shipped: /start and the Join dialog carry the Combined sha256 button; llms.txt the hash line; join hashes unchanged",
              f'data-phash="{SHIPPED}"' in d["start"] and f'data-phash="{SHIPPED}"' in d["frag"] and ("Combined prompt sha256: " + SHIPPED) in d["llms"]
              and d["join"]["template_sha256"] == TS and S.variant_sha256("chat-browse").startswith("0e8281f4") and S.variant_sha256("connector").startswith("c323d1f2"))
    finally:
        p.terminate(); p.wait(10)
sys.exit(1 if fails else 0)
