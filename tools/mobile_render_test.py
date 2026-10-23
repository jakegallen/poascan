"""Mobile render regression (1.26.28): the home page was blank below the header on iPhone (Brave, 390 px).
Static checks (always run, no browser needed):
* main has no entrance animation (a fill-mode both fade from opacity 0 with a transform kept all page content in one tall
  transformed layer that iOS WebKit could leave unpainted or stuck at the first frame)
* no rule hides main, .wrap or a whole section with opacity 0 and no animation keyframe that starts main from opacity 0
* the fixed full-screen blend layer (body::before, mix-blend-mode) is off on phones, tablets and touch screens
* one spacing step between stacked sections on phones (grid gap only, no card margin on top of it)
* charts held back for the draw-in have a scroll and pageshow backstop, and reduced motion turns the draw-in off
* the CSS and JS cache keys moved with this change
Browser checks (run when Playwright is installed, else skipped): the home page on an empty fixture at 360, 390 and 430 wide
in WebKit and Chromium: main is fully opaque with no transform, every section in main is opaque and painted, no horizontal
overflow, and the vertical gap between stacked sections is at most 16 px at each scroll position.
Usage: python3 tools/mobile_render_test.py"""
import os, re, socket, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
ui = open(os.path.join(ROOT, "poascan", "ui.py"), encoding="utf-8").read()
flat = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

def rules(sel_re):
    return [m.group(2) for m in re.finditer(r"(^|[}\s,])(" + sel_re + r")\s*\{([^{}]*)\}", flat)] and \
           [m.group(3) for m in re.finditer(r"(^|[}\s,])(" + sel_re + r")\s*\{([^{}]*)\}", flat)]

main_rules = rules(r"main")
check("main has no animation", not any("animation" in r for r in main_rules))
check("main, body and .wrap are never opacity 0", not any(re.search(r"opacity:\s*0(?![.\d])", r) for r in rules(r"main") + rules(r"body") + rules(r"\.wrap")))
check("body min-height has a dvh fallback for mobile toolbars", "min-height:100dvh" in flat)
mob = re.search(r"@media \(max-width:1100px\),\(pointer:coarse\)\{body::before\{display:none\}\}", flat)
check("fixed blend layer is off on phones, tablets and touch screens", bool(mob))
check("desktop keeps the grain layer", "body::before{content:\"\";position:fixed" in flat)
check("single column grids: no card margin on top of the gap", ".grid2>.card:not(:last-child),.grid3>.card:not(:last-child){margin-bottom:0}" in flat and ".herogrid>*,.herogrid>.stats.three{margin-bottom:0}" in flat)
check("phones: 12 px between sections", re.search(r"@media \(max-width:640px\)\{\.grid2,\.grid3,\.herogrid\{gap:12px\}", flat) is not None)
check("chart draw-in has a scroll and pageshow backstop", 'W.addEventListener("pageshow",rv)' in js and "{passive:true}" in js and "chart.pre" in js)
check("reduced motion turns the chart draw-in off", re.search(r"prefers-reduced-motion:reduce\)\{\*,\*::before,\*::after\{animation-duration:\.001ms", flat) is not None
      and ".js .chart,.js .chart.pre{clip-path:none;animation:none}" in flat)
v_css = int(re.search(r"style\.css\?v=(\d+)", ui).group(1)); v_js = int(re.search(r"app\.js\?v=(\d+)", ui).group(1))
check("cache keys moved (style.css v92+, app.js v44+)", v_css >= 92 and v_js >= 44)

# ---------------- browser ----------------
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None
    print("skip browser checks (Playwright not installed)")

if sync_playwright:
    def free_port():
        s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
    tmp = tempfile.mkdtemp(); port = free_port()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "m.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
    subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
    srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try: urllib.request.urlopen(base + "/healthz", timeout=1); break
            except Exception:
                try: urllib.request.urlopen(base + "/", timeout=2); break
                except Exception: time.sleep(.25)
        PROBE = """()=>{const m=document.querySelector('main');const cs=getComputedStyle(m);
          const secs=[...m.children].filter(c=>c.getBoundingClientRect().height>1&&!c.classList.contains('sr-only'));
          const bad=secs.filter(c=>parseFloat(getComputedStyle(c).opacity)<1||getComputedStyle(c).visibility!=='visible').map(c=>c.className);
          const blocks=[];const flat=e=>e.matches('.hero,.herogrid,.grid2,.grid3')?[...e.children].flatMap(flat):[e];
          secs.flatMap(flat).forEach(b=>{const r=b.getBoundingClientRect();if(r.height>1)blocks.push([r.top+scrollY,r.bottom+scrollY,b.className])});
          blocks.sort((a,b)=>a[0]-b[0]);let maxgap=0,where='';for(let i=1;i<blocks.length;i++){const g=blocks[i][0]-blocks[i-1][1];if(g>maxgap){maxgap=g;where=blocks[i-1][2]+' -> '+blocks[i][2]}}
          return {op:cs.opacity,tf:cs.transform,anim:cs.animationName,bad,maxgap:Math.round(maxgap),where,ox:document.documentElement.scrollWidth-innerWidth,h:document.documentElement.scrollHeight}}"""
        with sync_playwright() as p:
            for eng in ("webkit", "chromium"):
                try: b = getattr(p, eng).launch()
                except Exception as e:
                    print(f"skip {eng} ({str(e).splitlines()[0][:80]})"); continue
                for w in (360, 390, 430):
                    kw = dict(viewport={"width": w, "height": 844}, has_touch=True)
                    if eng == "chromium": kw["is_mobile"] = True
                    ctx = b.new_context(**kw); pg = ctx.new_page()
                    pg.goto(base + "/", wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(600)
                    r = pg.evaluate(PROBE)
                    check(f"{eng} {w}: main opaque, no transform, no animation", r["op"] == "1" and r["tf"] == "none" and r["anim"] == "none")
                    check(f"{eng} {w}: every section in main is opaque and visible {r['bad']}", not r["bad"])
                    check(f"{eng} {w}: no horizontal overflow ({r['ox']})", r["ox"] <= 0)
                    check(f"{eng} {w}: sections stack tight, largest gap {r['maxgap']} px ({r['where']})", r["maxgap"] <= 16)
                    y = 0; ok = True
                    while y < r["h"]:
                        pg.evaluate(f"window.scrollTo(0,{y})"); pg.wait_for_timeout(60)
                        vis = pg.evaluate("""()=>{const m=document.querySelector('main');const mr=m.getBoundingClientRect();if(mr.bottom<120)return true;
                          const els=[...m.querySelectorAll('.card,.stat,section')].filter(e=>{const r=e.getBoundingClientRect();return r.bottom>120&&r.top<innerHeight});
                          return els.length>0&&els.every(e=>parseFloat(getComputedStyle(e).opacity)>0)}""")
                        ok = ok and vis; y += 700
                    check(f"{eng} {w}: content on screen at every scroll position", ok)
                    ctx.close()
                b.close()
    finally:
        srv.terminate(); srv.wait(timeout=10)

print("\n" + ("ALL OK" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
