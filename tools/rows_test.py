"""Rows and columns (1.26.305): a table or list over 20 rows shows 20 and a Show more button that adds 20 a click until
none are left; up to 20 rows get no button; a second side by side panel taller than its neighbour is capped at the
neighbour's height (360 px at least) and scrolls inside, so the pair ends level; under 900 px nothing is capped.
Usage: python3 tools/rows_test.py"""
import os, socket, subprocess, sys, tempfile, time, urllib.request
from playwright.sync_api import sync_playwright
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
check("CSS: hidden rows, the Show more button, the level cap", ".rc-h{display:none!important}" in css and ".rcmore{" in css and ".evcap>.cb{" in css)
tmp = tempfile.mkdtemp(); s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "d.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
SYN = """()=>{const m=document.querySelector('main');const r=n=>Array.from({length:n},(_,i)=>'<tr><td>'+i+'</td></tr>').join('');
  m.insertAdjacentHTML('beforeend','<section class="card" id="t45"><div class="cb"><div class="tw"><table class="t"><tbody>'+r(45)+'</tbody></table></div></div></section>'
   +'<section class="card" id="t20"><div class="cb"><table class="t"><tbody>'+r(20)+'</tbody></table></div></section>'
   +'<section class="card" id="l30"><div class="cb"><ul>'+Array.from({length:30},(_,i)=>'<li>'+i+'</li>').join('')+'</ul></div></section>'
   +'<div class="grid2" id="g2"><section class="card" id="ga"><div class="ch"><h2>A</h2></div><div class="cb"><div style="height:420px"></div></div></section>'
   +'<section class="card" id="gb"><div class="ch"><h2>B</h2></div><div class="cb"><div style="height:1400px"></div></div></section></div>');
  window.poaRows.cap();window.poaRows.even()}"""
VIS = "s=>[...document.querySelectorAll(s)].filter(e=>getComputedStyle(e).display!='none').length"
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    with sync_playwright() as p:
        kw = {"executable_path": os.environ["PW_CHROME"]} if os.environ.get("PW_CHROME") else {}
        b = p.chromium.launch(args=["--no-sandbox"], **kw)
        for w, h in ((1280, 900), (390, 844)):
            pg = b.new_page(viewport={"width": w, "height": h}); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load"); pg.wait_for_timeout(400); pg.evaluate(SYN); pg.wait_for_timeout(200)
            check(f"{w}: 45 rows show 20 and Show more · 25", pg.evaluate(VIS, "#t45 tbody tr") == 20 and pg.inner_text("#t45 .rcmore").strip().lower() == "show more · 25")
            pg.click("#t45 .rcmore"); pg.wait_for_timeout(100)
            check(f"{w}: one click adds 20 (40 shown, 5 left)", pg.evaluate(VIS, "#t45 tbody tr") == 40 and "5" in pg.inner_text("#t45 .rcmore"))
            pg.click("#t45 .rcmore"); pg.wait_for_timeout(100)
            check(f"{w}: the last click shows every row and drops the button", pg.evaluate(VIS, "#t45 tbody tr") == 45 and pg.locator("#t45 .rcmore").count() == 0)
            check(f"{w}: 20 rows get no button", pg.evaluate(VIS, "#t20 tbody tr") == 20 and pg.locator("#t20 .rcmore").count() == 0)
            check(f"{w}: a 30 item list shows 20 and Show more · 10", pg.evaluate(VIS, "#l30 li") == 20 and "10" in pg.inner_text("#l30 .rcmore"))
            ga, gb = pg.evaluate("()=>[document.getElementById('ga').offsetHeight,document.getElementById('gb').offsetHeight]")
            capped = pg.evaluate("()=>document.getElementById('gb').classList.contains('evcap')")
            if w > 900: check(f"{w}: the taller panel is capped level with its neighbour and scrolls inside {ga} {gb}", capped and abs(ga - gb) <= 2 and pg.evaluate("()=>{const c=document.querySelector('#gb>.cb');return c.scrollHeight>c.clientHeight&&getComputedStyle(c).overflowY=='auto'}"))
            else: check(f"{w}: stacked panels are not capped", not capped)
            check(f"{w}: no page errors {errs[:2]}", not errs)
        b.close()
finally:
    srv.terminate(); srv.wait(10)
print(f"\n{len(fails)} failure(s)"); sys.exit(1 if fails else 0)
