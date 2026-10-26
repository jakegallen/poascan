"""The shared Agent cell (1.26.152): every table and list that names an Agent uses ui.agent(): identicon, the name linking to its
LabLeak profile when it has one, otherwise the short address linking to /address, in one color, the named style (1.26.172), the copy button right after it, then any tag.
One line; the label ends in an ellipsis when the column is narrow. Static checks on the HTML, then Playwright renders the fixture
site with a 47-character name with spaces, a 44-character name with no spaces and a no-name address at 360, 390 and 1280 px and
checks that no Agent cell overlaps a neighbouring cell or another Agent cell, and that its parts never overlap each other. In CI
(CI set) a missing Playwright is a failure; locally the browser part is skipped. Usage: python3 tools/agent_cell_test.py"""
import os, re, socket, sqlite3, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
from poascan import ui as H
A1, A2, A3 = ("poa1" + c * 40 for c in "ABC")
LONG = "Northwind Research Collective Agent Number 07"        # 46 characters with spaces
NOSP = "inifikryVeryLongAgentNameWithoutAnySpaces00AI"         # 45 characters, no spaces
check("test names are 40+ characters", len(LONG) >= 40 and len(NOSP) >= 40 and " " not in NOSP)
# static: the cell markup
c = H.agent(A1, LONG)
check("named: identicon links the address page, name links the LabLeak profile, copy right after the name",
      re.fullmatch(r'<span class="al ag" data-a="%s"><a class="agi" href="/address/%s"[^>]*><i class="idn"[^>]*></i></a><a class="agn aname" href="https://minepoa\.com/lableak/#/u/%s" target="_blank" rel="noopener noreferrer" title="[^"]+">%s</a><button class="cp"[^>]*data-copy="%s"[^>]*><i></i></button></span>' % (A1, A1, A1, LONG, A1), c) is not None)
c = H.agent(A3)
check("no name: the short address links /address, copy right after it", re.search(r'<a class="agn mono addr" href="/address/%s" title="%s">poa1CC…CCCC</a><button class="cp"' % (A3, A3), c) is not None and "lableak" not in c)
check("one label per cell: a named cell does not also print the address", H.short(A1, 6, 4) not in H.agent(A1, LONG))
check("a tag goes after the copy button", H.agent(A3, tail='<span class="tag">system</span>').endswith('</button><span class="tag">system</span></span>'))
check("#standing reaches both address links", H.agent(A1, LONG, frag="#standing").count('/address/%s#standing"' % A1) == 1 and H.agent(A3, frag="#standing").count('#standing"') == 1)
check("addr_link in tables is the Agent cell, always with the 6 + 4 short address", H.addr_link(A1, {A1: LONG}, (6, 4)) == H.agent(A1, LONG) and H.addr_link(A3, {}, (8, 6)) == H.agent(A3) and H.addr_link(A3, {}, (10, 6)) == H.agent(A3))
check("author_link with a poa1 id is the Agent cell", H.author_link(LONG, {LONG: A1}) == H.agent(A1, LONG))
check("malformed and empty addresses keep their plain forms", 'class="mono bad"' in H.agent("poa1-bad") and 'class="na"' in H.agent(""))
src = {f: open(os.path.join(ROOT, "poascan", f), encoding="utf-8").read() for f in ("views.py", "governance.py", "gradingview.py", "views4.py")}
check("no hand-built name over a <small> address left in views, governance and gradingview",
      not any(re.search(r'name_link\([^)]*\)\s*\+[^\n]*<small>', s) for s in src.values()))
css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
check("style.css: named and no-name labels share one color (inherit, no gold address), gold underline on hover",
      re.search(r"(^|[,}])a\.aname,[^{]*:where\(\.ag\)>a\.agn\{color:inherit;", css, re.M) is not None and re.search(r":where\(\.ag\)>a\.agn:hover[^{]*\{color:var\(--hi\);border-bottom-color:var\(--amber\)", css) is not None)
check("style.css: the label shrinks first and ends in an ellipsis", re.search(r"\.ag>\.agn\{[^}]*min-width:0[^}]*overflow:hidden;text-overflow:ellipsis;white-space:nowrap", css) is not None)
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("ticker: reads the address from the cell; a name links LabLeak, no name links /address", '$(".ag",r)' in js and "it.a&&it.n?" in js and 'href="/address/\'+encodeURIComponent(it.a)' in js)

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None
    check("Playwright is installed in CI", not os.environ.get("CI"))
    print("skip browser checks (Playwright not installed)")
PAGES = ["/", "/chain/txs", "/agents", "/agents/top", "/agents/top?tab=grading", "/agents/top?tab=referrals", "/agents/community", "/network?tab=token",
         "/governance?tab=established", "/governance?tab=at-risk", "/governance?tab=queue", "/governance?tab=payouts",
         "/governance?tab=graders", "/governance?tab=directory", "/governance?tab=forum", f"/address/{A2}"]
PROBE = """()=>{const R=e=>e.getBoundingClientRect(),vis=e=>{const r=R(e);return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'};
 const ov=(a,b)=>Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1;
 const cells=[...document.querySelectorAll('.ag')].filter(vis),bad=[];
 cells.forEach((g,i)=>{const host=g.closest('td,th,li,.fw,.kv>div')||g.parentElement,hr=R(host),gr=R(g);
  const sc=g.closest('.tw,.lbw,.scroll,[style*=overflow]');
  if(gr.right>hr.right+1||gr.left<hr.left-1)bad.push(['spills out of its cell',g.dataset.a,Math.round(gr.right-hr.right)]);
  const row=g.closest('tr');if(row)[...row.cells].filter(c=>c!==host&&!c.contains(g)).forEach(c=>{[...c.children].filter(vis).forEach(k=>{if(ov(gr,R(k)))bad.push(['overlaps the next cell',g.dataset.a,c.cellIndex])})});
  const parts=[...g.children].filter(vis);for(let a=0;a<parts.length;a++)for(let b=a+1;b<parts.length;b++)if(ov(R(parts[a]),R(parts[b])))bad.push(['parts overlap',g.dataset.a,parts[a].className+' / '+parts[b].className]);
  const n=g.querySelector('.agn'),cp=g.querySelector('.cp');
  if(n&&vis(n)){if(R(n).width<20)bad.push(['label squeezed',g.dataset.a,Math.round(R(n).width)]);
   if(n.classList.contains('addr')&&n.scrollWidth>n.clientWidth+1)bad.push(['short address cut a second time',g.dataset.a,n.scrollWidth-n.clientWidth]);
   if(n.scrollWidth>n.clientWidth+1&&(getComputedStyle(n).textOverflow!=='ellipsis'||getComputedStyle(n).overflowX==='visible'))bad.push(['text runs past its box',g.dataset.a,n.scrollWidth-n.clientWidth]);
   if(cp&&vis(cp)&&(R(cp).left<R(n).right-1||R(cp).left-R(n).right>12))bad.push(['copy not right after the label',g.dataset.a,Math.round(R(cp).left-R(n).right)])}
  if(n&&n.tagName==='A'){const k=n.classList.contains('addr')?'a':'n',c=getComputedStyle(n).color,ctx=(g.closest('[class]:not(.ag):not(td):not(tr)')||document.body).className;(window.__agc=window.__agc||{})[ctx]=window.__agc[ctx]||{};window.__agc[ctx][k]=window.__agc[ctx][k]||new Set();window.__agc[ctx][k].add(c);if(c==='rgb(255, 176, 0)')bad.push(['label in gold',g.dataset.a,c])}
  cells.slice(i+1).forEach(h=>{if(ov(gr,R(h)))bad.push(['two Agent cells overlap',g.dataset.a,h.dataset.a])})});
 const cut=cells.filter(g=>{const n=g.querySelector('.agn');return n&&n.scrollWidth>n.clientWidth+1}).length;
 const mix=Object.entries(window.__agc||{}).filter(([k,v])=>v.a&&v.n&&[...v.a].some(c=>!v.n.has(c))).map(([k,v])=>[k,[...v.a],[...v.n]]);if(mix.length)bad.push(['named and no-name labels differ in color',mix.slice(0,2)]);
 return {n:cells.length,named:cells.filter(g=>g.querySelector('.aname')).length,cut,bad:bad.slice(0,6),nbad:bad.length,ox:document.documentElement.scrollWidth-innerWidth}}"""
if sync_playwright:
    def free_port():
        s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
    tmp = tempfile.mkdtemp(); port = free_port(); dbp = os.path.join(tmp, "a.db")
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
    subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
    con = sqlite3.connect(dbp)
    con.executemany("INSERT INTO forum_posts(id, community, title, author, author_public_id, created_at, score, comment_count, deleted, pinned, fetched, body) VALUES(?,?,?,?,?,?,0,0,0,0,0,'')",
                    [(9001, "intros", "Hello", LONG, A1, "2026-10-25 10:00:00"), (9002, "intros", "Hi", NOSP, A2, "2026-10-25 11:00:00")])
    con.commit(); con.close()
    srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=open(os.path.join(tmp, "server.log"), "w"))
    print("server log:", os.path.join(tmp, "server.log"))
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try: urllib.request.urlopen(base + "/healthz", timeout=1); break
            except Exception: time.sleep(.25)
        seen = {"n": 0, "named": 0, "cut": 0}
        with sync_playwright() as p:
            kw = {"executable_path": os.environ["PW_CHROME"]} if os.environ.get("PW_CHROME") else {}
            b = p.chromium.launch(args=["--no-sandbox"], **kw)
            for w in (360, 390, 1280):
                mob = w < 600
                ctx = b.new_context(viewport={"width": w, "height": 900}, is_mobile=mob, has_touch=mob)
                pg = ctx.new_page()
                for path in PAGES:
                    st = pg.goto(base + path, wait_until="domcontentloaded", timeout=60000).status; pg.wait_for_timeout(250)
                    r = pg.evaluate(PROBE); r["nbad"] += st >= 500; r["bad"] += [["HTTP", st]] if st >= 500 else []
                    for k in seen: seen[k] += r[k]
                    check(f"{w} {path}: {r['n']} Agent cells ({r['named']} named, {r['cut']} cut with an ellipsis), no overlap {r['bad']}", r["nbad"] == 0)
                if os.environ.get("AGENT_CELL_SHOTS"):
                    for path, sel in (("/", "table.grs"), ("/governance?tab=graders", "table"), ("/chain/txs", "table")):
                        pg.goto(base + path, wait_until="domcontentloaded"); pg.wait_for_timeout(400); el = pg.query_selector(sel)
                        if el: el.scroll_into_view_if_needed(); el.screenshot(path=os.path.join(os.environ["AGENT_CELL_SHOTS"], f"fixture-{w}-{path.strip('/').replace('?', '-').replace('=', '-') or 'home'}.png"))
                ctx.close()
            b.close()
        check(f"the run covered named, no-name and ellipsis-cut cells {seen}", seen["named"] > 10 and seen["n"] - seen["named"] > 10 and seen["cut"] > 5)
    finally:
        srv.terminate(); srv.wait(timeout=10)
print("\n" + ("all passed" if not fails else f"{len(fails)} failed"))
sys.exit(1 if fails else 0)
