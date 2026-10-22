"""Wallet registry setup code (poascan/regcode.py, static/app.js).
* The code format: 's_' + 16 chars of a-z2-7, from crypto.getRandomValues with an unbiased mapping (256 % 32 == 0, b & 31).
* The server never makes a code: pages carry only the {SETUP_CODE} template slot, and with JS off the prompt has no registry step.
* The filled step lands as the last numbered step, keeps the safety lines, carries only the allowed fields and no key-shaped text.
* POAScan's server makes no request to poaswap.io: no outbound module names it, the indexer allowlist is unchanged, and a
  recording proxy sees no poaswap.io connection while every page renders. CSP connect-src stays 'self'.
Usage: python3 tools/registry_test.py"""
import hashlib, json, os, re, socket, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error
from html import unescape
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# sha256 of poascan/indexer.py ALLOWED.pattern at 1.21.0; the outbound allowlist must not change for this feature
ALLOWED_SHA = "f8db72e2fa1f2a6e1106bda43d0d6ed51a74870e4d2706f2b10ddaaa6895c621"

def js_code(n=2000):
    """Run the app.js generator logic (same alphabet and mapping) with Python's CSPRNG standing in for getRandomValues."""
    from poascan import regcode as RC
    out = []
    for _ in range(n):
        b = os.urandom(16); out.append("s_" + "".join(RC.ALPHABET[x & 31] for x in b))
    return out

def unit():
    from poascan import regcode as RC, keysafe as KS, start as ST
    from poascan.swap import prompts as P
    check("alphabet is exactly a-z2-7, 32 unique chars", RC.ALPHABET == "abcdefghijklmnopqrstuvwxyz234567" and len(set(RC.ALPHABET)) == 32)
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    m = re.search(r"/\* Wallet setup prompts:.*?\}\)\(\);", js, re.S); blk = m.group(0) if m else ""
    check("app.js uses the same alphabet, getRandomValues, 16 bytes and the unbiased &31 mapping",
          '"' + RC.ALPHABET + '"' in blk and "getRandomValues(new Uint8Array(16))" in blk and "&31" in blk and 'k="s_"' in blk and "Math.random" not in blk)
    check("app.js generator stores nothing and sends nothing", not re.search(r"localStorage|sessionStorage|cookie|fetch\(|XMLHttpRequest|sendBeacon|location|history\.", blk.split("*/", 1)[-1]))
    check("app.js fills the slot the server emits", "{SETUP_CODE}" in blk and RC.SLOT == "{SETUP_CODE}" and "dataset.regAt" in blk)
    codes = js_code(); rx = re.compile(RC.CODE_RX)
    check("codes match ^s_[a-z2-7]{16}$", all(rx.match(c) for c in codes) and len(set(codes)) == len(codes))
    seen = set("".join(c[2:] for c in codes)); check("mapping reaches every alphabet char", seen == set(RC.ALPHABET))
    code = codes[0]
    for name, base, reg in (("wallet", P.WALLET_PROMPT, P.WALLET_REG), ("start", ST.prompt("amber-otter-123"), ST.REG_STEP)):
        f = RC.fill(base, reg["lead"], reg["before"], code)
        lines = f.split("\n"); nums = [l for l in lines if re.match(r"^\d+\. ", l)]
        check(f"{name}: step inserted once, as the last numbered step", f.count(code) == 1 and nums[-1].startswith(reg["lead"]) and code in nums[-1])
        check(f"{name}: rest of the prompt unchanged", f.replace("\n" + RC.step(reg["lead"]).replace(RC.SLOT, code), "", 1) == base)
        check(f"{name}: safety lines kept", ("Never paste or show passwords, keys or seed phrases in chat." in f) if name == "wallet"
              else ("Never send payment outside the network." in f and "Never ask me for keys" in f))
        check(f"{name}: no key-shaped text", not KS.has_key(f) and not KS.PARAM_RX.search(RC.step("")))
    st = RC.step("")
    fields = re.findall(r'"([a-z_0-9]+)"', st.split("only these fields:", 1)[1].split(". Public", 1)[0])
    named = [x for x in fields if x not in ("scan", "created", "connected", RC.SLOT)]
    check("step names only the allowed fields", set(named) == set(RC.FIELDS))
    check("no signature or verification fields (created as a field, sig, type)", '"sig"' not in st and '"type"' not in st and '"created":' not in st and "sign" not in st.replace("signatures", ""))
    check("step: JSON body, no query string, public addresses only, skippable", "POST JSON (body only, no query string)" in st and RC.URL + " " in st
          and "?" not in RC.URL and "Public addresses only, never keys" in st and st.endswith("Skip if unsure.") and "Optional" in P.WALLET_REG["lead"])
    check("no em dashes", "\u2014" not in st + P.WALLET_PROMPT + ST.prompt() and "\u2014" not in js)
    check("server-side text has no step (llms.txt, MCP)", "poaswap" not in ST.PROMPT and "poaswap" not in P.WALLET_PROMPT and "poaswap" not in json.dumps(ST.data()))
    # outbound: no module that makes requests names poaswap or imports regcode
    for dp, _, fs in os.walk(os.path.join(ROOT, "poascan")):
        for fn in fs:
            if not fn.endswith(".py"): continue
            s = open(os.path.join(dp, fn)).read()
            if "urlopen" in s or "http.client" in s or "socket" in s:
                check(f"outbound module {fn} never names poaswap", "poaswap" not in s.lower() and "regcode" not in s)
    from poascan import indexer as IX
    sha = hashlib.sha256(IX.ALLOWED.pattern.encode()).hexdigest()
    check("indexer allowlist unchanged and minepoa-only", IX.BASE == "https://minepoa.com" and "poaswap" not in IX.ALLOWED.pattern and (ALLOWED_SHA is None or sha == ALLOWED_SHA))

class Proxy:
    """Records every host the server tries to reach through HTTP(S)_PROXY and refuses it, so nothing leaves the box."""
    def __init__(self):
        self.hosts = []; self.s = socket.socket(); self.s.bind(("127.0.0.1", 0)); self.s.listen(50); self.port = self.s.getsockname()[1]
        threading.Thread(target=self.run, daemon=True).start()
    def run(self):
        while True:
            try: c, _ = self.s.accept()
            except Exception: return
            try:
                line = c.recv(4096).split(b"\r\n", 1)[0].decode("latin-1"); self.hosts.append(line)
                c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except Exception: pass
            finally: c.close()

def live():
    tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "g.db")
    subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {os.path.dirname(os.path.abspath(__file__))!r}); import routes_test as R; R.seed({dbp!r})"], check=True, cwd=ROOT)
    px = Proxy(); purl = f"http://127.0.0.1:{px.port}"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", HTTPS_PROXY=purl, HTTP_PROXY=purl,
               https_proxy=purl, http_proxy=purl, NO_PROXY="", no_proxy="")
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    get = lambda r: op.open(base + r, timeout=30)
    try:
        for _ in range(100):
            try: get("/healthz"); break
            except Exception: time.sleep(0.2)
        pages = {}
        for r in ("/", "/swaps", "/start", "/privacy", "/about", "/llms-full.txt", "/llms.txt"):
            x = get(r); pages[r] = (x.status, dict(x.headers), x.read().decode())
            check(f"GET {r} -> 200", x.status == 200)
        sw, stt, pv = pages["/swaps"][2], pages["/start"][2], pages["/privacy"][2]
        csp = pages["/swaps"][1].get("Content-Security-Policy", "")
        check("CSP connect-src stays 'self' and names no poaswap", "connect-src 'self';" in csp and "poaswap" not in csp)
        check("no s_ code generated by the server on any page", not any(re.search(r"\bs_[a-z2-7]{16}\b", h) for _, _, h in pages.values()))
        pre = re.search(r'<pre class="pc-text" tabindex="0" data-reg="([^"]*)" data-reg-at="([^"]*)">([^<]*)</pre>', sw)
        check("/swaps Add Wallet prompt carries the template slot", bool(pre) and "{SETUP_CODE}" in unescape(pre.group(1)) and unescape(pre.group(1)).startswith("4. Optional: "))
        check("/swaps no-JS prompt text has no registry step", bool(pre) and "poaswap" not in pre.group(3) and "Never paste or show passwords" in unescape(pre.group(3)))
        sp = re.search(r'<pre class="pc-text jm-p" tabindex="0" data-reg="([^"]*)" data-reg-at="([^"]*)">([^<]*)</pre>', stt)
        check("/start prompt carries the template slot, no-JS text has no step", bool(sp) and "{SETUP_CODE}" in unescape(sp.group(1)) and "poaswap" not in sp.group(3))
        check("Start dialog on every page carries the slot", all('id="jm-prompt" tabindex="0" data-reg="' in pages[r][2] for r in ("/", "/swaps", "/privacy")))
        check("llms.txt prompt has no registry step", "poaswap" not in pages["/llms-full.txt"][2] and "poaswap" not in pages["/llms.txt"][2])
        sec = re.search(r"<h3>Setup code \(optional\)</h3><p>(.*?)</p>\s*<h3>Who sees the totals</h3>", pv, re.S)
        check("/privacy: Setup code section before Who sees the totals, Updated 2026-10-22", bool(sec) and "Updated 2026-10-22." in pv
              and 'href="/swaps"' in sec.group(1) and 'href="/start"' in sec.group(1) and "POAScan's server sends nothing to POASwap." in sec.group(1))
        check("no em dashes in the pages", not any("\u2014" in h for r, (_, _, h) in pages.items() if r in ("/swaps", "/start", "/privacy")))
        time.sleep(1)
        bad = [h for h in px.hosts if "poaswap" in h.lower()]
        check(f"server made no request to poaswap.io ({len(px.hosts)} outbound attempts, all refused)", not bad)
    finally:
        p.terminate(); p.wait(10)

if __name__ == "__main__":
    unit(); live()
    print("\n" + ("PASS" if not fails else f"FAIL: {len(fails)}: {fails}")); sys.exit(1 if fails else 0)
