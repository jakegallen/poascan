"""Development banner (1.26.69): first element in <body> on every HTML page, above the sticky header, normal flow (not fixed or
sticky), exact text with no em or en dash, @Jakegallen links x.com/Jakegallen in a new tab with rel noopener noreferrer (keysafe rule), no dismiss control,
same look as POASwap's .devbar, the Upgrading strip stays steel, join prompt unchanged. Usage: python3 tools/devbar_test.py"""
import os, re, socket, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

css = re.sub(r"/\*.*?\*/", "", open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read(), flags=re.S)
ui = open(os.path.join(ROOT, "poascan", "ui.py"), encoding="utf-8").read()
dev = " ".join(re.findall(r"(?:^|\})\.devbar[^{]*\{([^}]*)\}", css))
check("banner CSS present", ".devbar{" in css and ".devbar p{" in css and ".devbar a{" in css)
check("banner is in normal flow (no fixed, sticky or absolute)", not re.search(r"position\s*:", dev))
check("banner uses the POASwap amber tint", "rgba(227,163,58,.20)" in css and "#FFC861" in css)
up = re.search(r"\.upstrip\{([^}]*)\}", css).group(1)
check("Upgrading strip stays steel, not a second amber bar", "143,163,184" in up and "227,163,58" not in up and "255,176,0" not in up)
check("cache key moved (style.css v104+)", int(re.search(r"style\.css\?v=(\d+)", ui).group(1)) >= 104)

TEXT = "System development in progress. Follow @Jakegallen for updates."
tmp = tempfile.mkdtemp(); s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "d.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="1")
subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    get = lambda p: urllib.request.urlopen(base + p, timeout=30).read().decode()
    for p in ("/", "/start", "/address/poa1" + "A" * 40, "/chain", "/about", "/upgrade"):
        h = get(p); body = h[h.index("<body"):]; body = body[body.index(">") + 1:]
        m = re.match(r'\s*<div class="devbar" id="devbar" role="note">(.*?)</div></div>', body, re.S)
        inner = m.group(1) if m else ""
        txt = re.sub(r"<[^>]+>", "", inner).strip()
        ok = (m is not None and body.index("devbar") < body.index('<header class="top">') and txt == TEXT and body.count('id="devbar"') == 1
              and '<a href="https://x.com/Jakegallen" target="_blank" rel="noopener noreferrer">@Jakegallen</a>' in inner
              and "\u2014" not in inner and "\u2013" not in inner and "<button" not in inner)
        check(f"{p}: banner first in body, above the header, exact text and link, no dismiss", ok)
    home = get("/"); check("home: Upgrading strip still renders below the header", home.index('class="upstrip"') > home.index('<header class="top">'))
    import json
    j = json.loads(get("/api/v1/prompts/join")); check("join prompt unchanged (6762aa1c)", j.get("template_sha256", "").startswith("6762aa1c"))
finally:
    srv.terminate(); srv.wait(10)
sys.exit(1 if fails else 0)
