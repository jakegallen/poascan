"""Chart pop-out never blank (1.26.157). On Oct 26, 2026 the server was CPU throttled and /fragment/chart took 15 to 40 s; on a
phone the Active Agents pop-out showed only its header, close button and an empty panel (the still skeleton read as nothing,
no chips, no line) with no timeout and no way to retry. Now the panel shows a visible Loading line, a load that fails or takes
longer than CPT_MS ends in a terse "Chart did not load" state with a Retry button, and Retry draws the chart. Home hero cards
and Network charts, 390 px in Chromium and WebKit (iPhone engine) and 1280 px in Chromium. Also the Stale tag on the Home
headline numbers: server side when the live read is stale, client side when the data's as_of is too old.
In CI (CI set) a missing Playwright or WebKit is a failure, locally it is skipped.
Usage: python3 tools/chartpop_blank_test.py"""
import os, re, socket, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
load = js[js.index(" function load(c,r){var n=++seq;"):js.index(" /* a one line definition from the server")]
check("the pop-out load has a timeout and aborts the fetch", "CPT_MS" in load and "AbortController" in load and "signal" in load)
check("a failed load shows the retry state, never an empty panel", "Chart did not load" in load and "data-cpretry" in load and ".catch(fail)" in load)
check("the loading skeleton carries a visible line", "<span>Loading chart</span>" in load)
check("closing the dialog aborts a pending load", "cpAc.abort()" in js[js.index("function closed(){"):js.index("function closed(){") + 200])

# ---------------- server side Stale tag on the Home headline numbers ----------------
tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "s.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import views as V, analytics as A
h = V.home() if not isinstance(V.home(), tuple) else V.home()[1]
body = h if isinstance(h, str) else str(h)
check("fresh data: no Stale tag on the headline numbers", "hstale" not in body and 'data-asof="' in body)
_f = A.freshness
A.freshness = lambda: dict(_f(), state="stale", fetched_at=time.time() - 900)
try:
    body = V.home(); body = body if isinstance(body, str) else str(body)
    kp = body[body.find('class="stats four kpis"'):]; kp = kp[:kp.find("</section>")]
    check("stale live read: all four headline numbers carry Stale", kp.count("hstale") == 4 and "Last read 15m ago" in kp and 'data-stale="1"' in body)
    km = body[body.find('class="stats three kstats'):]; km = km[:km.find("</section>")]
    check("stale live read: Holders carries Stale too", km.count("hstale") == 1)
finally:
    A.freshness = _f

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None
    check("Playwright is installed in CI", not os.environ.get("CI"))
    print("skip browser checks (Playwright not installed)")

STATE = """()=>{const c=document.querySelector('.cpop'),bx=c&&c.querySelector('.cp-box');if(!bx)return null;const sp=bx.querySelector('.cskel span'),
 er=bx.querySelector('.cp-err'),rb=er&&er.querySelector('[data-cpretry]'),R=e=>e.getBoundingClientRect(),cs=e=>getComputedStyle(e);
 return {open:c.hasAttribute('open'),text:bx.innerText.trim(),loading:!!sp&&R(sp).height>0&&cs(sp).visibility==='visible'&&cs(sp).color!=='rgba(0, 0, 0, 0)',
  err:!!er,retry:!!rb&&R(rb).width>=44&&R(rb).height>=32,svg:!!bx.querySelector('.cpchart path'),chips:c.querySelectorAll('.cp-rng button').length,boxH:Math.round(R(bx).height)}}"""
if sync_playwright:
    def free_port():
        s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
    port = free_port()
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
            runs = [(eng, b, 390) for eng, b in engines] + [("chromium", engines[0][1], 1280)]
            for eng, b, w in runs:
                mob = w < 600
                for path, sel in (("/", '.kpis [data-chart="active"]'), ("/", '.kpis [data-chart="agents"]'), ("/network?tab=charts", '[data-chart="supply"]')):
                    tag = f"{eng} {w} {path} {sel.split('=')[-1].strip(']')}"
                    ctx = b.new_context(viewport={"width": w, "height": 844 if mob else 900}, is_mobile=mob and eng == "chromium", has_touch=mob, device_scale_factor=2 if mob else 1)
                    ctx.add_init_script("window.POASCAN_CPT_MS=1500")
                    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
                    mode = {"m": "hang"}; held = []
                    def route(r):
                        if mode["m"] == "hang": held.append(r)   # never answered: a throttled server
                        elif mode["m"] == "500": r.fulfill(status=500, body="busy")
                        else: r.continue_()
                    pg.route("**/fragment/chart*", route)
                    pg.goto(base + path, wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(400)
                    loc = pg.locator(sel).first; loc.scroll_into_view_if_needed()
                    (loc.tap if mob else loc.click)(); pg.wait_for_timeout(300)
                    s0 = pg.evaluate(STATE)
                    check(f"{tag}: a slow load shows a visible Loading line, not an empty panel ({s0})", s0 and s0["open"] and s0["loading"] and "Loading chart" in s0["text"] and s0["boxH"] > 150)
                    pg.wait_for_timeout(1800); s1 = pg.evaluate(STATE)
                    check(f"{tag}: a load that never answers ends in the retry state ({s1})", s1 and s1["err"] and s1["retry"] and s1["text"].startswith("Chart did not load") and not s1["svg"])
                    mode["m"] = "500"; pg.locator(".cp-err [data-cpretry]").click(); pg.wait_for_timeout(400); s2 = pg.evaluate(STATE)
                    check(f"{tag}: a 500 also ends in the retry state ({s2})", s2 and s2["err"] and s2["retry"])
                    mode["m"] = "ok"; pg.locator(".cp-err [data-cpretry]").click()
                    try: pg.wait_for_selector(".cpop[open] .cpchart path", timeout=15000)
                    except Exception: pass
                    s3 = pg.evaluate(STATE)
                    check(f"{tag}: Retry draws the chart, or the fixture's terse No data line ({s3})", s3 and not s3["err"] and (s3["svg"] or s3["text"] == "No data for this range yet"))
                    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
                    check(f"{tag}: no page errors {errs}", not errs)
                    for r in held:
                        try: r.abort()
                        except Exception: pass
                    ctx.close()
                # client side Stale: the page's as_of is 20 min old and no snapshot arrives (socket and polling blocked)
                ctx = b.new_context(viewport={"width": w, "height": 844 if mob else 900}, is_mobile=mob and eng == "chromium", has_touch=mob)
                pg = ctx.new_page()
                pg.route("**/api/summary*", lambda r: r.abort())
                def old_home(r):
                    resp = r.fetch(); html = resp.text()
                    html = re.sub(r'data-asof="\d*"', f'data-asof="{int(time.time()) - 1200}"', html, count=1)
                    r.fulfill(response=resp, body=html)
                pg.route(re.compile(r".*:%d/$" % port), old_home)
                pg.add_init_script("window.WebSocket=undefined")
                pg.goto(base + "/", wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(800)
                n = pg.evaluate("document.querySelectorAll('.kpis .hstale').length"); t = pg.evaluate("(document.querySelector('.kpis .hstale .qbox')||{}).textContent||''")
                check(f"{eng} {w}: old as_of with no snapshot tags the four headline numbers Stale ({n}, {t!r})", n == 4 and t.startswith("Last read 20m ago"))
                ctx.close()
            for _, b in engines: b.close()
    finally:
        srv.terminate(); srv.wait(timeout=10)
print("\n" + ("all passed" if not fails else f"{len(fails)} failed"))
sys.exit(1 if fails else 0)
