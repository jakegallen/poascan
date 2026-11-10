"""Development banner removed (1.26.288, Jake's call) and the home credit. No page carries the devbar markup or its CSS;
every page carries exactly one quiet credit in the footer row (1.26.300; X logo plus @Jakegallen, x.com/Jakegallen in a new
tab with rel noopener noreferrer, never @jakegallen_), none inside main and no floating pill; no share button; no em or en
dash; join prompt unchanged. Usage: python3 tools/devbar_test.py"""
import os, re, socket, subprocess, sys, tempfile, time, urllib.request, json
import os as _os, time as _time; _os.environ.setdefault("POASCAN_MAINT_STARTED", str(int(_time.time()) - 86400))
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

css = re.sub(r"/\*.*?\*/", "", open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read(), flags=re.S)
ui = open(os.path.join(ROOT, "poascan", "ui.py"), encoding="utf-8").read()
check("no devbar CSS left", ".devbar" not in css)
check("no DEV_BANNER in the layout", "DEV_BANNER" not in ui and "System development in progress" not in ui)
check("credit CSS present, muted with a gold hover, no pill", ".foot .fcredit{" in css and "color:var(--mute)" in css.split(".foot .fcredit{")[1].split("}")[0] and ".fcredit:hover" in css and ".credit" not in css)
check("cache key follows the file (style.css?v= is its hash since 1.26.150)", 'style.css?v={ASSET_V["style.css"]}' in ui)
CRED = '<a href="https://x.com/Jakegallen" target="_blank" rel="noopener noreferrer" aria-label="Built by @Jakegallen on X">'
tmp = tempfile.mkdtemp(); s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "d.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="1")
subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    get = lambda p: urllib.request.urlopen(base + p, timeout=30).read().decode()
    for p in ("/", "/start", "/address/poa1" + "A" * 40, "/chain", "/about", "/upgrade", "/network", "/governance"):
        h = get(p); body = h[h.index("<body"):]; body = body[body.index(">") + 1:]
        check(f"{p}: no dev banner", 'devbar' not in h and "System development in progress" not in h and body.lstrip().startswith('<header class="top">'))
        n = h.count('class="fcredit"')
        i = h.find('class="fcredit"')
        check(f"{p}: one credit, in the footer, not in main", n == 1 and h.index("<footer") < i < h.index("</footer>") and 'class="credit"' not in h)
        seg = h[i:h.index("</a>", i)]
        check(f"{p}: credit links x.com/Jakegallen in a new tab, X logo, @Jakegallen", CRED.replace('<a href', '<a class="fcredit" href') in h and "<svg" in seg and "<b>@Jakegallen</b>" in seg and "jakegallen_" not in seg.lower())
        check(f"{p}: no dashes and no share in the credit", "\u2014" not in seg and "\u2013" not in seg and "share" not in seg.lower())
    j = json.loads(get("/api/v1/prompts/join")); check("join prompt is v2.9.6 (ec1d7608)", j.get("template_sha256", "").startswith("ec1d7608"))
finally:
    srv.terminate(); srv.wait(10)
print(f"\n{len(fails)} failure(s)"); sys.exit(1 if fails else 0)
