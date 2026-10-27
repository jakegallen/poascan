"""Milestone hover text in the visitor's zone (1.26.179). Every milestone marker's hover (Home sparkline labels and their
hover-only ticks, chart milestone chips, legend entries, the SVG title on the milestone line, aria labels) reads in the
reader's zone in the one format ("Oct 25, 7:17 PM Sample mark"); the UTC text is only the no-script fallback. Chromium with
the zone set to America/Los_Angeles and to Asia/Tokyo. In CI (CI set) a missing Playwright is a failure, locally it is skipped.
Usage: python3 tools/marker_local_test.py"""
import os, re, sys, tempfile, shutil, threading, functools, http.server
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "m.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
from poascan import ui, milestones as MS, bench as BN
T0 = 1792800000; SAMPLE = 1792981020   # Oct 26, 02:17 UTC (Oct 25, 7:17 PM PDT; Oct 26, 11:17 AM JST)
pts = [(T0 + i * 3600, 100 + i) for i in range(60)] + [(SAMPLE + 3600 * k, 300 + k) for k in range(1, 30)]
marks = [dict(ts=SAMPLE, label="Sample mark"), dict(ts=SAMPLE - 7200, label="Genesis cut")]   # close together: one label, one hover-only tick
sp = ui.spark(pts, marks=marks)
check("sparkline: UTC fallback on the title, the local template in data-ltt", 'title="Oct 26, 02:17 UTC Sample mark"' in sp and f'data-ltt="{{t:{SAMPLE}}} Sample mark"' in sp)
check("sparkline: the hover-only tick carries the same", 'class="spkd"' in sp and f'data-ltt="{{t:{SAMPLE - 7200}}} Genesis cut"' in sp)
gm = MS.group([dict(key="sample_mark", ts=SAMPLE, label="Sample mark", url=None), dict(key="genesis_cut", ts=T0 + 3600 * 20, label="Genesis cut", url="/segments")], pts[0][0], pts[-1][0])
ln = ui.line(pts, marks=gm)
check("chart: milestone title text is the UTC fallback", "Oct 26, 02:17 UTC Sample mark" in ln and "<title>" in ln)
S0 = 1793060990   # 00:29:50 UTC Oct 27 (5:29:50 PM PDT Oct 26)
seal = "".join(f'<i class="sm" title="{BN.seal_tip(c)}" data-ltt="{BN.seal_ltt(c)}">{c[1]}</i>' for c in ([0, 76, S0, S0 + 266], [0, 1, S0 + 300, S0 + 300]))
check("Live strip seals: UTC fallback title plus the local template", 'title="76 Seals · 00:29:50 to 00:34:16 UTC"' in seal and f'data-ltt="76 Seals · {{t:{S0}:ts}} to {{t:{S0 + 266}:ts}}"' in seal)
src_b = open(os.path.join(ROOT, "poascan", "bench.py")).read()
check("seal_layer emits the template on every mark", src_b.count('data-ltt="{seal_ltt(c)}"') == 2)
page = f'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/static/style.css"></head><body><div class="stat" style="width:300px">{sp}</div><div class="card" style="width:600px">{ln}</div><section class="stats three kstats kmore krow"><div class="stat"><span class="sl">Holders</span><div class="sv">1,665</div>{sp}</div></section><div class="sealx">{seal}</div><script src="/static/app.js"></script></body></html>'
os.makedirs(os.path.join(tmp, "www", "static")); open(os.path.join(tmp, "www", "t.html"), "w").write(page)
for f in ("app.js", "style.css"): shutil.copy(os.path.join(ROOT, "static", f), os.path.join(tmp, "www", "static", f))
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None
    check("Playwright is installed in CI", not os.environ.get("CI"))
    print("skip browser checks (Playwright not installed)")
GET = """()=>{const o=[];document.querySelectorAll('.spkl,.spkd,.mkc,.mk title,.mkl [title],ol [title],[aria-label]').forEach(e=>{
 if(e.tagName.toLowerCase()==='title')o.push(['svg',e.textContent]);else{if(e.title)o.push(['title',e.title]);const a=e.getAttribute('aria-label');if(a&&/\\d:\\d/.test(a))o.push(['aria',a])}});
 return o.filter(x=>/Sample mark|Genesis cut/.test(x[1]))}"""
if sync_playwright:
    H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=os.path.join(tmp, "www"))
    class Q(H.func):
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=os.path.join(tmp, "www")))
    threading.Thread(target=srv.serve_forever, daemon=True).start(); base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with sync_playwright() as p:
            kw = {"executable_path": os.environ["PW_CHROME"]} if os.environ.get("PW_CHROME") else {}
            b = p.chromium.launch(args=["--no-sandbox"], **kw)
            for tz, want, w in (("America/Los_Angeles", "Oct 25, 7:17 PM Sample mark", 390), ("America/Los_Angeles", "Oct 25, 7:17 PM Sample mark", 1280), ("Asia/Tokyo", "Oct 26, 11:17 AM Sample mark", 1280)):
                ctx = b.new_context(timezone_id=tz, locale="en-US", viewport={"width": w, "height": 900})
                pg = ctx.new_page(); pg.goto(base + "/t.html", wait_until="load"); pg.wait_for_timeout(200)
                got = pg.evaluate(GET)
                kinds = sorted({k for k, _ in got})
                check(f"{tz} {w}: every Sample mark hover reads {want!r} ({len(got)} texts: {', '.join(kinds)})",
                      got and all(want in t for k, t in got if "Sample mark" in t) and {"title", "svg"} <= set(kinds))
                check(f"{tz} {w}: no UTC left in any milestone hover", all(" UTC" not in t for _, t in got))
                st = pg.evaluate("[...document.querySelectorAll('.sealx .sm')].map(e=>e.title)")
                want_s = {"America/Los_Angeles": ["76 Seals · 5:29:50 PM to 5:34:16 PM", "Seal · 5:34:50 PM"], "Asia/Tokyo": ["76 Seals · 9:29:50 AM to 9:34:16 AM", "Seal · 9:34:50 AM"]}[tz]
                check(f"{tz} {w}: Live strip seal hover is local ({st})", st == want_s)
                vis = pg.evaluate("[...document.querySelectorAll('.kmore .spkl')].filter(e=>e.offsetParent!==null).length")
                check(f"{tz} {w}: a row card shows no sparkline milestone label ({vis} visible)", vis == 0)
                check(f"{tz} {w}: the standard format (Mon D, h:mm AM)", all(re.search(r"\b[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d\d [AP]M ", t) for _, t in got))
                ctx.close()
            b.close()
    finally:
        srv.shutdown()
src = open(os.path.join(ROOT, "static", "app.js")).read()
css = open(os.path.join(ROOT, "static", "style.css")).read()
check("row cards (Home Holders, Chain height) hide the sparkline and its milestone labels, so no label lands on the value", ".kmore .stat .spk,.kmore .stat .spkw{display:none}" in css)
check("app.js localizes aria labels and SVG titles", "[aria-label*=' UTC']" in src and '"svg title"' in src)
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
