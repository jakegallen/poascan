"""Every tooltip and popover opens above everything around it and inside the viewport (tipfix, Jake 2026-10-26: the
Governance Established Unconfirmed note rendered behind the next row of stat cards). In Chromium at 390 px (tap) and 1280 px
(click) on Home, Governance (overview and tabs), Network, Token, an address page, /start, Census and an epoch page, this opens
every kind of note: the ? tips, the Stale, Unconfirmed and estimate tags, table header tips, the header status note, the chart
? and chart hover readouts, the seal timeline tip, the Ask agent dialog and every Grader patterns note. For each open note it checks with
document.elementFromPoint at the centre and four corners (inside the rounded edge) that the note (or something inside it) is the topmost element,
and that its whole box is inside the viewport. Fixture site; no request leaves the box. In CI (CI set) a missing Playwright is
a failure, locally it is skipped. Usage: python3 tools/tip_layer_test.py"""
import os, socket, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None
    check("Playwright is installed in CI", not os.environ.get("CI"))
    print("skip browser checks (Playwright not installed)")

# minepoa's grading list leaves out the fixture's established Agents, so the Unconfirmed tags (stat cards, rows) render
SEED = """import time
from poascan import db
db.put_blob("grading", {"rows": [], "open": [], "stats": {}, "epoch": 11, "fetched_at": time.time(), "as_of": time.time(),
                        "established": ["poa1" + "Z" * 40], "trusted": [], "leaderboard": []})
# Grader patterns (1.26.183): settled seats with scores for four graders, answer txs and seal times, so the card, its four
# charts and every header tip render
from poascan import gradehist as GH, grading as GR, segments as SG
GH._ensure(); GR._ensure(); now = int(time.time()); gs = ["poa1" + c * 40 for c in "ABCD"]
db.write("INSERT OR IGNORE INTO grade_history(seg, answer, grader, close, aligned, passed, score) VALUES(?,?,?,?,?,?,?)",
         [(SG.CURRENT, "gp%062x" % i, g, 10, 1 if (i + k) % 3 else 0, 1, (i + k) % 4) for i in range(40) for k, g in enumerate(gs)], many=True)
db.write("INSERT OR IGNORE INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)",
         [("gp%062x" % i, "challenge", gs[0], 9, now - 90000, 5, 5, 1) for i in range(40)], many=True)
db.write("INSERT OR IGNORE INTO grading_seals(answer, grader, ts, t, q, first_seen) VALUES(?,?,?,?,?,?)",
         [("gp%062x" % i, g, now - 90000 + 3600 * (1 + i % 30), 0, 1, now) for i in range(40) for g in gs[:2]], many=True)
"""
PAGES = ["/", "/governance", "/governance?tab=established", "/governance?tab=at-risk", "/governance?tab=queue", "/governance?tab=graders",
         "/governance?tab=payouts", "/governance?tab=directory", "/governance?tab=charts", "/governance?tab=rules", "/governance?tab=protocol",
         "/network", "/network?tab=token", "/network?tab=health", "/address/poa1" + "A" * 40, "/start", "/agents/census", "/epoch/10"]

# Is box the topmost element at its centre and four inset corners, and fully inside the viewport? Notes that ignore the
# pointer (chart readouts) take pointer events for the measurement only, since elementFromPoint skips pointer-events:none.
PROBE = """(box)=>{if(!box)return {err:'no box'};const pe=box.style.pointerEvents;box.style.pointerEvents='auto';
 const r=box.getBoundingClientRect(),W=innerWidth,H=innerHeight,cs=getComputedStyle(box);
 const k=Math.min(Math.max(4,(parseFloat(cs.borderTopLeftRadius)||0)*0.3+4),r.width/2,r.height/2);   /* inside the rounded corners */
 const pts=[[r.left+r.width/2,r.top+r.height/2],[r.left+k,r.top+k],[r.right-k,r.top+k],[r.left+k,r.bottom-k],[r.right-k,r.bottom-k]];
 const miss=[];for(const [x,y] of pts){const e=document.elementFromPoint(Math.min(Math.max(x,0),W-1),Math.min(Math.max(y,0),H-1));
  if(!(e===box||box.contains(e)))miss.push((e&&(e.tagName+'.'+(e.className&&e.className.baseVal!==undefined?e.className.baseVal:e.className)).slice(0,60))||'none')}
 box.style.pointerEvents=pe;
 return {w:r.width,h:r.height,l:r.left,t:r.top,r:r.right,b:r.bottom,W,H,vis:cs.visibility,op:+cs.opacity,miss,
  inside:r.left>=-0.5&&r.top>=-0.5&&r.right<=W+0.5&&r.bottom<=H+0.5,text:(box.innerText||'').trim().slice(0,50)}}"""
# up to 3 notes per kind (classes of the note plus the nearest card-like box), so every kind is opened without opening hundreds
LIST = """()=>{const seen={},out=[];document.querySelectorAll('details.qtip').forEach((d,i)=>{const s=d.querySelector(':scope>summary');
 if(!s)return;const r=s.getBoundingClientRect();if(!r.width||!r.height||getComputedStyle(s).visibility==='hidden')return;
 const host=d.closest('.stat,th,td,.card,.chartbox,header,.cpop,.kv,li,p,div');
 const k=d.className+'|'+(host?host.tagName+'.'+String(host.className).split(' ')[0]:'')+'|'+(s.className||'');
 seen[k]=(seen[k]||0)+1;if(seen[k]<=3){d.dataset.tt=i;out.push({i,k,label:(s.innerText||s.getAttribute('aria-label')||'').trim().slice(0,30)})}});return out}"""

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def run(base, p, w, h, mobile, kinds):
    kw = {"executable_path": os.environ["PW_CHROME"]} if os.environ.get("PW_CHROME") else {}
    b = p.chromium.launch(args=["--no-sandbox"], **kw)
    ctx = b.new_context(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile, timezone_id="America/Los_Angeles")
    ctx.route("**/*", lambda rt: rt.continue_() if rt.request.url.startswith(base) or rt.request.url.startswith("data:") else rt.abort())
    pg = ctx.new_page(); n_all = 0
    def judge(name, r):
        nonlocal n_all; n_all += 1
        ok = not r.get("err") and r["w"] > 0 and r["h"] > 0 and r["vis"] == "visible" and r["op"] > 0.5 and not r["miss"] and r["inside"]
        if not ok: check(f"{w}: {name}: topmost and inside ({r})", False)
        return ok
    for path in PAGES:
        pg.goto(base + path, wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(400)
        good = bad = 0
        for q in pg.evaluate(LIST):
            sel = f'details.qtip[data-tt="{q["i"]}"]'
            pg.evaluate("()=>document.querySelectorAll('details.qtip[open]').forEach(d=>d.removeAttribute('open'))")
            s = pg.locator(sel + " > summary").first
            try:
                s.scroll_into_view_if_needed(timeout=3000)
                # in a sideways scrolling table, bring the ? to the right edge, clear of the sticky first column a reader scrolls past
                pg.evaluate(f"""()=>{{const s=document.querySelector('{sel} > summary');let c=s.parentElement;
                  while(c&&!(c.scrollWidth>c.clientWidth&&/auto|scroll/.test(getComputedStyle(c).overflowX)))c=c.parentElement;
                  if(c){{const a=s.getBoundingClientRect(),b=c.getBoundingClientRect();c.scrollLeft+=a.right-(b.right-8)}}}}""")
                (s.tap if mobile else s.click)(timeout=3000)
            except Exception as e:
                check(f"{w}: {path} {q['k']} '{q['label']}': opens ({type(e).__name__})", False); bad += 1; continue
            pg.wait_for_timeout(180)
            r = pg.evaluate(f"()=>{{const d=document.querySelector('{sel}');return d&&d.open}}")
            if not r: check(f"{w}: {path} {q['k']} '{q['label']}': open after a {'tap' if mobile else 'click'}", False); bad += 1; continue
            res = pg.evaluate(PROBE, pg.locator(sel + " .qbox").first.element_handle())
            kinds.add("qtip " + q["k"].split("|")[0])
            if judge(f"{path} note {q['k']} '{q['label']}'", res): good += 1
            else: bad += 1
            pg.keyboard.press("Escape"); pg.wait_for_timeout(60)
        # chart hover readouts (.xt) at the left edge, middle and right edge of up to 4 charts
        nch = pg.evaluate("()=>{let n=0;document.querySelectorAll('.chartbox').forEach((c,i)=>{const r=c.getBoundingClientRect();if(r.width&&r.height&&n<4){c.dataset.tc=n++}});return n}")
        for i in range(nch):
            c = pg.locator(f'.chartbox[data-tc="{i}"]').first
            try: c.scroll_into_view_if_needed(timeout=3000)
            except Exception: continue
            bb = c.bounding_box()
            if not bb: continue
            for fx in (0.02, 0.5, 0.98):
                pg.mouse.move(bb["x"] + bb["width"] * fx, bb["y"] + bb["height"] * 0.5); pg.wait_for_timeout(120)
                el = pg.evaluate_handle(f"()=>{{const c=document.querySelector('.chartbox[data-tc=\"{i}\"]');const t=c&&c.querySelector('.xt');return c&&c.classList.contains('hov')&&t&&t.textContent.trim()?t:null}}")
                if pg.evaluate("e=>!!e", el):
                    kinds.add("chart readout")
                    if judge(f"{path} chart {i} readout at {fx:.0%}", pg.evaluate(PROBE, el)): good += 1
                    else: bad += 1
            pg.mouse.move(1, 1)
        # seal timeline tip (.stip) on the epoch page
        if pg.locator("#score .sm").count():
            m = pg.locator("#score .sm").first; m.scroll_into_view_if_needed(timeout=3000); m.hover(); pg.wait_for_timeout(150)
            el = pg.evaluate_handle("()=>{const t=document.querySelector('#score .stip.on');return t}")
            if pg.evaluate("e=>!!e", el):
                kinds.add("seal tip")
                if judge(f"{path} seal tip", pg.evaluate(PROBE, el)): good += 1
                else: bad += 1
        # the Ask agent dialog
        if pg.locator(".askb").count():
            a = pg.locator(".askb").first; a.scroll_into_view_if_needed(timeout=3000); (a.tap if mobile else a.click)(); pg.wait_for_timeout(200)
            kinds.add("ask dialog")
            if judge(f"{path} Ask agent dialog", pg.evaluate(PROBE, pg.locator("#askmodal").element_handle())): good += 1
            else: bad += 1
            pg.keyboard.press("Escape"); pg.wait_for_timeout(80)
        # Grader patterns (1.26.183): every ? on its charts and table headers, not only the first 3 of a kind
        if "tab=graders" in path:
            # every one shown at this width (at 390 the dk columns, Peers, Top score, Distance and Mix, are hidden with their ?)
            ids = pg.evaluate("""()=>{const o=[];document.querySelectorAll('#patterns details.qtip, .gpc details.qtip').forEach((d,i)=>{const s=d.querySelector(':scope>summary'),r=s&&s.getBoundingClientRect();
              if(r&&r.width&&r.height){d.dataset.gp=i;o.push(i)}});return o}""")
            gp_ok = 0
            for i in ids:
                sel = f'details.qtip[data-gp="{i}"]'
                pg.evaluate("()=>document.querySelectorAll('details.qtip[open]').forEach(d=>d.removeAttribute('open'))")
                s = pg.locator(sel + " > summary").first
                try:
                    s.scroll_into_view_if_needed(timeout=3000)
                    pg.evaluate(f"""()=>{{const s=document.querySelector('{sel} > summary');let c=s.parentElement;
                      while(c&&!(c.scrollWidth>c.clientWidth&&/auto|scroll/.test(getComputedStyle(c).overflowX)))c=c.parentElement;
                      if(c){{const a=s.getBoundingClientRect(),b=c.getBoundingClientRect();c.scrollLeft+=a.right-(b.right-8)}}}}""")
                    (s.tap if mobile else s.click)(timeout=3000); pg.wait_for_timeout(150)
                    res = pg.evaluate(PROBE, pg.locator(sel + " .qbox").first.element_handle())
                except Exception as e:
                    check(f"{w}: grader patterns note {i} opens ({type(e).__name__})", False); bad += 1; continue
                if judge(f"{path} grader patterns note {i} '{res.get('text')}'", res): good += 1; gp_ok += 1
                else: bad += 1
                pg.keyboard.press("Escape"); pg.wait_for_timeout(60)
            check(f"{w}: Grader patterns: {gp_ok} of {len(ids)} notes topmost and inside (4 chart ?, plus 6 header ? at 1280, 2 at 390)", len(ids) >= (6 if mobile else 10) and gp_ok == len(ids))
            if gp_ok and gp_ok == len(ids): kinds.add("grader patterns")
        check(f"{w}: {path}: {good} notes topmost and inside the viewport, {bad} not", bad == 0)
    b.close()
    return n_all

if sync_playwright:
    tmp = tempfile.mkdtemp(); port = free_port()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
    subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
    subprocess.run([sys.executable, "-c", SEED], cwd=ROOT, env=env, check=True, capture_output=True)
    srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try: urllib.request.urlopen(base + "/healthz", timeout=1); break
            except Exception: time.sleep(.25)
        gov = urllib.request.urlopen(base + "/governance", timeout=30).read().decode()
        check("fixture: the Governance Established stat card carries the Unconfirmed tag", "grading list" in gov and "Unconfirmed" in gov)
        kinds = set()
        with sync_playwright() as p:
            for w, h, mob in ((390, 844, True), (1280, 900, False)):
                n = run(base, p, w, h, mob, kinds)
                check(f"{w}: opened {n} notes", n >= 30)
        for k in ("qtip qtip", "qtip qtip sflag", "qtip qtip hv spill", "qtip qtip hv btip", "chart readout", "ask dialog", "grader patterns"):
            check(f"covered: {k} ({sorted(kinds)})" if k not in kinds else f"covered: {k}", k in kinds)
    finally:
        srv.terminate()
print("FAILS:", len(fails)) if fails else print("ALL OK")
sys.exit(1 if fails else 0)
