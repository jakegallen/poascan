"""Header on one row (1.26.150): at 360 and 390 px (and 430, 1280) the logo, the status pill, POASwap, Start and the menu stay on
one row with every pill state, including the longest label. Up to 430 px the pill is a compact status line under the wordmark:
dot and word in the state color, still the status button (1.26.169: it opens the status note), never hidden or clipped. Renders the fixture site in Chromium with
Playwright. The compact pill has the same clear background and no border in every state (1.26.151). In CI (CI set) a missing Playwright is a failure, locally it is skipped. Usage: python3 tools/header_row_test.py"""
import os, re, socket, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
src = open(os.path.join(ROOT, "poascan", "analytics.py"), encoding="utf-8").read()
m = re.search(r'label=\{("live": "Live",[^}]*)\}\[state\]', src)
check("pill labels read from analytics.freshness", m is not None)
LABELS = dict(re.findall(r'"(\w+)": "([^"]+)"', m.group(1))) if m else {}
SHOWN = {k: v for k, v in LABELS.items() if k != "up"}   # Upgrading hides the pill (the header shows the update dot instead)
check(f"every shown state has a label {SHOWN}", {"live", "partial", "lag", "stale"} <= set(SHOWN))
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None
    check("Playwright is installed in CI", not os.environ.get("CI"))
    print("skip browser checks (Playwright not installed)")
PROBE = """([cls,lab])=>{const d=document.getElementById('livepill'),p=d.querySelector('summary');d.hidden=false;p.className='pill '+cls;p.querySelector('span').textContent=lab;
 const u=document.getElementById('updot');if(u)u.hidden=true;
 const R=e=>e.getBoundingClientRect(),h=document.querySelector('.hdr');
 const row=['.brand','.swaplink','.joinbtn','.burger'].map(s=>h.querySelector(s)).filter(e=>e&&getComputedStyle(e).display!=='none');
 const cy=row.map(e=>R(e).top+R(e).height/2),pr=R(p),sp=R(p.querySelector('span'));
 const others=[...h.querySelectorAll('.brand .mark,.wm b,.swaplink,.joinbtn,.burger')].filter(e=>getComputedStyle(e).display!=='none');
 const hit=others.filter(e=>{const r=R(e);return !(r.right<=pr.left||r.left>=pr.right||r.bottom<=pr.top||r.top>=pr.bottom)}).map(e=>String(e.getAttribute("class")||e.tagName));
 const top=Math.min(...row.map(e=>R(e).top)),bot=Math.max(...row.map(e=>R(e).bottom));
 return {n:row.length,spread:Math.round(Math.max(...cy)-Math.min(...cy)),pin:pr.top>=top-1&&pr.bottom<=bot+1&&pr.left>=0&&pr.right<=innerWidth,
   text:p.innerText.trim(),textw:Math.round(sp.width),hit,ox:document.documentElement.scrollWidth-innerWidth,vis:getComputedStyle(p).visibility,bg:(c=>[c.backgroundColor,c.backgroundImage,c.borderTopWidth].join(' '))(getComputedStyle(p)),href:p.tagName==='SUMMARY'&&p.tabIndex>=0&&!!d.querySelector('.qbox a[href]')}}"""
if sync_playwright:
    def free_port():
        s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
    tmp = tempfile.mkdtemp(); port = free_port()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "h.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
    subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
    srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try: urllib.request.urlopen(base + "/healthz", timeout=1); break
            except Exception: time.sleep(.25)
        with sync_playwright() as p:
            kw = {"executable_path": os.environ["PW_CHROME"]} if os.environ.get("PW_CHROME") else {}
            b = p.chromium.launch(args=["--no-sandbox"], **kw)
            for w in (360, 390, 430, 1280):
                mob = w < 600
                ctx = b.new_context(viewport={"width": w, "height": 800}, is_mobile=mob, has_touch=mob)
                for path in ("/", "/chain"):
                    pg = ctx.new_page(); pg.goto(base + path, wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(400)
                    res = {k: pg.evaluate(PROBE, [k, v]) for k, v in SHOWN.items()}
                    longest = max(res, key=lambda k: res[k]["textw"])
                    for k, r in res.items():
                        tag = f"{w} {path} {k}{' (longest)' if k == longest else ''}"
                        check(f"{tag}: logo, POASwap, Start and menu on one row (spread {r['spread']} px)", r["n"] >= (4 if mob else 3) and r["spread"] <= 4)
                        check(f"{tag}: the pill sits inside that row and the viewport, over nothing else {r['hit']}", r["pin"] and not r["hit"])
                        check(f"{tag}: the state word shows in full ({r['text']!r}, {r['textw']} px)", r["text"].lower() == SHOWN[k].lower() and r["textw"] >= 18 and r["vis"] == "visible")
                        check(f"{tag}: still the status button with a link in its note, no horizontal overflow", bool(r["href"]) and r["ox"] <= 0)
                    if mob:
                        bgs = {k: r["bg"] for k, r in res.items()}
                        check(f"{w} {path}: the compact pill has the same background in every state, no box ({sorted(set(bgs.values()))})",
                              len(set(bgs.values())) == 1 and next(iter(bgs.values())) == "rgba(0, 0, 0, 0) none 0px")
                    pg.close()
                ctx.close()
            b.close()
    finally:
        srv.terminate(); srv.wait(timeout=10)
print("\n" + ("all passed" if not fails else f"{len(fails)} failed"))
sys.exit(1 if fails else 0)
