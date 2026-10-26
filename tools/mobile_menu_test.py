"""Mobile menu (1.26.152): at 360 and 390 px the hamburger opens the drawer with every nav link visible and clickable, on a fresh
load and after scrolling down the page. The drawer sits right under the sticky header (--hdr-h is never negative or zero) and
a tap on a link navigates. Before 1.26.152 the scroll lock made body a scroll container, the sticky header jumped to the top of
the document, --hdr-h went negative and the open drawer was a blank panel. Renders the fixture site with Playwright in Chromium
and, when installed, WebKit (iPhone engine). In CI (CI set) a missing Playwright or WebKit is a failure, locally it is skipped.
Usage: python3 tools/mobile_menu_test.py"""
import os, socket, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
check("the scroll lock never makes body a scroll container (body overflow clip, not hidden)",
      "html.navlock body{overflow:clip" in css and "html.navlock body{overflow:hidden" not in css and "html.navlock,html.navlock body{overflow:hidden" not in css)
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None
    check("Playwright is installed in CI", not os.environ.get("CI"))
    print("skip browser checks (Playwright not installed)")
PROBE = """()=>{const nav=document.getElementById('nav'),h=document.querySelector('.hdr'),R=e=>e.getBoundingClientRect();
 const nr=R(nav),hb=R(h).bottom,ns=getComputedStyle(nav),links=[...nav.querySelectorAll('a')];
 const shown=links.filter(a=>{const b=R(a);if(b.width<=0||b.height<=0||b.top<0||b.bottom>innerHeight)return false;
   const el=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2);return !!el&&(el===a||a.contains(el))});
 return {open:document.body.classList.contains('navopen'),vis:ns.visibility,op:+ns.opacity,top:Math.round(nr.top),bottom:Math.round(nr.bottom),
   hb:Math.round(hb),hdrh:document.documentElement.style.getPropertyValue('--hdr-h'),links:links.length,shown:shown.length,
   y:Math.round(scrollY),href:(shown[0]||{}).getAttribute?shown[0].getAttribute('href'):null}}"""
if sync_playwright:
    def free_port():
        s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
    tmp = tempfile.mkdtemp(); port = free_port()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "m.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
    subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
    srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try: urllib.request.urlopen(base + "/healthz", timeout=1); break
            except Exception: time.sleep(.25)
        with sync_playwright() as p:
            engines = []
            kw = {"executable_path": os.environ["PW_CHROME"]} if os.environ.get("PW_CHROME") else {}
            engines.append(("chromium", p.chromium.launch(args=["--no-sandbox"], **kw)))
            try: engines.append(("webkit", p.webkit.launch()))
            except Exception as e:
                check("WebKit is installed in CI", not os.environ.get("CI")); print("skip WebKit (" + str(e).splitlines()[0][:120] + ")")
            for eng, b in engines:
                for w in (360, 390):
                    for path in ("/", "/chain"):
                        for mode in ("fresh", "scrolled"):
                            ctx = b.new_context(viewport={"width": w, "height": 740}, is_mobile=eng == "chromium", has_touch=True, device_scale_factor=2)
                            pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
                            pg.goto(base + path, wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(500)
                            if mode == "scrolled":
                                pg.evaluate("scrollTo(0, Math.max(600, document.documentElement.scrollHeight - innerHeight - 200))"); pg.wait_for_timeout(300)
                            y0 = pg.evaluate("Math.round(scrollY)")
                            pg.tap(".burger"); pg.wait_for_timeout(500)
                            r = pg.evaluate(PROBE); tag = f"{eng} {w} {path} {mode} (scrollY {y0})"
                            if mode == "scrolled": check(f"{tag}: the page really scrolled", y0 >= 300)
                            check(f"{tag}: the drawer is open and visible ({r['vis']}, opacity {r['op']})", r["open"] and r["vis"] == "visible" and r["op"] > .9)
                            check(f"{tag}: the drawer sits under the header, inside the viewport (top {r['top']}, header bottom {r['hb']}, --hdr-h {r['hdrh']})",
                                  0 < r["top"] <= r["hb"] + 2 and r["top"] >= r["hb"] - 2 and r["bottom"] <= 740 + 1 and r["hdrh"].endswith("px") and int(r["hdrh"][:-2]) > 0)
                            check(f"{tag}: every nav link is visible and clickable ({r['shown']} of {r['links']})", r["links"] >= 3 and r["shown"] == r["links"])
                            if r["href"]:
                                pg.locator(f"#nav a[href='{r['href']}']").first.tap(); pg.wait_for_load_state("domcontentloaded"); pg.wait_for_timeout(300)
                                check(f"{tag}: a tap on {r['href']} navigates", pg.url.split("?")[0].rstrip("/").endswith(r["href"].split("?")[0].rstrip("/")))
                            check(f"{tag}: no page errors {errs}", not errs)
                            ctx.close()
                b.close()
    finally:
        srv.terminate(); srv.wait(timeout=10)
print("\n" + ("all passed" if not fails else f"{len(fails)} failed"))
sys.exit(1 if fails else 0)
