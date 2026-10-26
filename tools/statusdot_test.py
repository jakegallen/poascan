"""Header status note (1.26.169): the grading strip under the header is gone (home and /start); the header status dot and word
open a small note (the qtip pattern) with what drives the state, the read time in the reader's zone and links (Details to
/upgrade while grading is not confirmed, Health always). It opens on a tap at 390 px and stays inside the viewport, on a mouse
hover and on keyboard focus at 1280 px, and Escape closes it. The Graders Unconfirmed tag stays. Fixture site in Chromium.
In CI (CI set) a missing Playwright is a failure, locally it is skipped. Usage: python3 tools/statusdot_test.py"""
import os, re, socket, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
check("no grading-only strip rules left", "GRADING_STRIP" not in open(os.path.join(ROOT, "poascan", "views.py"), encoding="utf-8").read() and "_grading_strip" not in open(os.path.join(ROOT, "poascan", "views.py"), encoding="utf-8").read())
check("no a.pill rules left (the pill is a summary now)", "a.pill" not in css)
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None
    check("Playwright is installed in CI", not os.environ.get("CI"))
    print("skip browser checks (Playwright not installed)")
SEED = """import time
from poascan import db
now = int(time.time())
db.put_blob("notices", {"active": [{"id": "2026-10-23-grading-resumed", "issued_ts": now - 3600, "expires_ts": now + 3600, "txid": "a" * 64,
  "msg": "GRADING IS BACK, all paths OPEN (answers, assignments, grades, swaps). Hardening pause over, resume normal cadence."}]})
db.write("DELETE FROM txs WHERE type='grade-sealed'")
"""
BOX = """()=>{const d=document.getElementById('livepill'),b=d.querySelector('.qbox'),r=b.getBoundingClientRect();
 return {open:d.open,vis:getComputedStyle(b).visibility,l:r.left,r:r.right,t:r.top,b:r.bottom,w:innerWidth,h:innerHeight,text:b.innerText,
  links:[...b.querySelectorAll('a')].map(a=>a.getAttribute('href')),time:(b.querySelector('time')||{}).textContent||'',ox:document.documentElement.scrollWidth-innerWidth}}"""
if sync_playwright:
    def free_port():
        s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
    tmp = tempfile.mkdtemp(); port = free_port()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "s.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
    subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
    subprocess.run([sys.executable, "-c", SEED], cwd=ROOT, env=env, check=True, capture_output=True)
    srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try: urllib.request.urlopen(base + "/healthz", timeout=1); break
            except Exception: time.sleep(.25)
        home = urllib.request.urlopen(base + "/", timeout=20).read().decode(); start = urllib.request.urlopen(base + "/start", timeout=20).read().decode()
        check("home and /start: no strip under the header", 'class="upstrip' not in home and 'class="upstrip' not in start)
        check("dev banner stays", 'id="devbar"' in home and "System development in progress." in home)
        hd = home[home.index('id="livepill"'):home.index("</details>", home.index('id="livepill"'))]
        check("header note names grading, Details to /upgrade, Health link", "Grading not yet confirmed. No recent seals." in hd and 'href="/upgrade">Details</a>' in hd and 'href="/network?tab=health">Health</a>' in hd)
        check("Graders Unconfirmed tag unchanged", '<span class="tag warn">Unconfirmed</span>' in home)
        check("no em or en dashes in the note", "\u2014" not in hd and "\u2013" not in hd)
        with sync_playwright() as p:
            kw = {"executable_path": os.environ["PW_CHROME"]} if os.environ.get("PW_CHROME") else {}
            b = p.chromium.launch(args=["--no-sandbox"], **kw)
            ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            pg = ctx.new_page(); pg.goto(base + "/", wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(500)
            r0 = pg.evaluate(BOX)
            check("390: closed on load", not r0["open"])
            pg.tap("#livepill > summary"); pg.wait_for_timeout(300); r = pg.evaluate(BOX)
            check(f"390: a tap opens the note inside the viewport ({r['l']:.0f}..{r['r']:.0f} of {r['w']}, top {r['t']:.0f}, bottom {r['b']:.0f})",
                  r["open"] and r["vis"] == "visible" and r["l"] >= 0 and r["r"] <= r["w"] and r["t"] >= 0 and r["b"] <= r["h"] and r["ox"] <= 0)
            check(f"390: local time with a zone ({r['time']!r})", bool(re.search(r"\d:\d\d\s?(AM|PM)?\s?\S+", r["time"])) and not r["time"].endswith("Z"))
            pg.tap("main"); pg.wait_for_timeout(300)
            check("390: a tap outside closes it", not pg.evaluate(BOX)["open"])
            ctx.close()
            ctx = b.new_context(viewport={"width": 1280, "height": 900})
            pg = ctx.new_page(); pg.goto(base + "/", wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(500)
            pg.hover("#livepill > summary"); pg.wait_for_timeout(300); r = pg.evaluate(BOX)
            check(f"1280: hover opens the note in the viewport ({r['l']:.0f}..{r['r']:.0f})", r["open"] and r["vis"] == "visible" and r["l"] >= 0 and r["r"] <= r["w"])
            pg.mouse.move(r["l"] + 20, r["t"] + 20); pg.wait_for_timeout(200)
            check("1280: moving onto the note keeps it open", pg.evaluate(BOX)["open"])
            pg.mouse.move(10, 600); pg.wait_for_timeout(200)
            check("1280: leaving closes it", not pg.evaluate(BOX)["open"])
            pg.focus(".search input"); pg.keyboard.press("Tab"); pg.wait_for_timeout(50)
            for _ in range(4):
                if pg.evaluate("document.activeElement.matches('#livepill > summary')"): break
                pg.keyboard.press("Tab"); pg.wait_for_timeout(50)
            pg.wait_for_timeout(200)
            check("1280: keyboard focus on the dot opens the note", pg.evaluate("document.activeElement.matches('#livepill > summary')") and pg.evaluate(BOX)["open"])
            pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
            check("1280: Escape closes it, focus stays on the dot", not pg.evaluate(BOX)["open"] and pg.evaluate("document.activeElement.matches('#livepill > summary')"))
            ctx.close(); b.close()
    finally:
        srv.terminate(); srv.wait(timeout=10)
print("\n" + ("all passed" if not fails else f"{len(fails)} failed"))
sys.exit(1 if fails else 0)
