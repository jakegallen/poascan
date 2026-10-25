"""Bench motion (1.26.145): the ticker under the strip, the bezel head, the dev only demo gate, and the client rules (no new
requests, reduced motion, paused while hidden, no layout shift hooks). No network. Usage: python3 tools/bench_motion_test.py"""
import os, re, subprocess, sys, tempfile, time
os.environ.setdefault("POASCAN_SEGMENTS", "1")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "t.db")
os.environ.pop("POASCAN_DEV_DEMO", None)
import fixture; fixture.seed()
from poascan import db, bench as BN, views as V, devdemo as DD, ui
now = int(time.time()); A1 = "poa1" + "A" * 40
db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,ts,atts,final) VALUES(?,?,?,?,?,?)",
         [("f0" * 32, "challenge", A1, now - 6, 1, 0), ("f1" * 32, "grade-sealed", A1, now - 40, 3, 1)], many=True)
h = V.tracker_html()
tk = re.search(r'<div class="btk">.*?</div></div>', h, re.S)
check("the ticker sits under the strip, inside #score, lane aligned with a Latest label", tk is not None and 'class="lbl">Latest<' in tk.group(0) and h.index('class="btk"') > h.index('class="sax"'))
t = tk.group(0) if tk else ""
check("ticker: newest first, verb and age, the first item shown", re.search(r'<span class="tki on"><i class="sw a"></i><a class="tkn" [^>]*>[^<]+</a> answered <time class="tkt" data-ts="\d+">\d+s ago</time>', t) is not None)
check("ticker: Agent names link to their LabLeak profile in a new tab", f'href="{ui.PROFILE_URL.format(A1)}" target="_blank" rel="noopener noreferrer"' in t)
check("ticker: sealed a grade reads in Seals green", '<i class="sw s"></i>' in t and "sealed a grade" in t)
check("ticker: an empty archive reads one line", "Waiting for the next tx" in BN.ticker_html([]))
check("summary payload leaves the strip and ticker out", 'class="btk"' not in V.tracker_html(score=False) and 'class="score"' not in V.tracker_html(score=False))
check("bezel: a head and a glint over the ticks, the fill as --f", re.search(r'<div class="bzw" style="--f:[\d.]+"><svg[^>]*>.*?</svg><i class="bzs"></i><i class="bzh"></i></div>', h, re.S) is not None)
check("the now line glow sits over the lanes", '<i class="nowg" aria-hidden="true"></i>' in h)
snap = V.live_snapshot()
check("snapshot last close carries settled (the close summary)", "settled" in snap["last"])
# the demo is dev only
check("demo off without POASCAN_DEV_DEMO", DD.ENABLED is False and DD.route("/dev/demo-seed") is None and DD.route("/dev/demo-motion.js") is None)
ui.REQ.qs = {"demo": ["motion"]}; ui.REQ.path = "/"
check("?demo=motion adds nothing while off", DD.html_attr() == "" and DD.script() == "")
page = ui.layout("", "<p>x</p>", "/")
check("page: no data-demo and no demo script while off", "data-demo" not in page and "/dev/" not in page)
env = dict(os.environ, POASCAN_DEV_DEMO="1", FLY_APP_NAME="poascan")
r = subprocess.run([sys.executable, "-c", "from poascan import devdemo as D; print(D.ENABLED)"], cwd=ROOT, env=env, capture_output=True, text=True)
check("never on Fly, even with the flag set", r.stdout.strip() == "False")
env.pop("FLY_APP_NAME")
r = subprocess.run([sys.executable, "-c", "from poascan import devdemo as D, ui; ui.REQ.qs={'demo':['motion']}; print(D.ENABLED, D.html_attr(), D.script())"], cwd=ROOT, env=env, capture_output=True, text=True)
check("local dev with the flag: the attribute and the script", r.stdout.startswith("True") and 'data-demo="motion"' in r.stdout and "/dev/demo-motion.js" in r.stdout)
check("the demo script lives outside static/ (never served by /static/)", os.path.exists(os.path.join(ROOT, "poascan/devdemo.js")) and not os.path.exists(os.path.join(ROOT, "static/devdemo.js")))
srv = open(os.path.join(ROOT, "poascan/server.py")).read()
check("server: /dev/* answers 404 unless the demo is on", 'if path.startswith("/dev/"):' in srv and "DD.route(path)" in srv)
# client rules
js = open(os.path.join(ROOT, "static/app.js")).read()
i = js.index("/* 1.26.145 Bench motion"); blk = js[i:js.index("/* apply a snapshot", i)]
check("bench motion makes no requests of its own", "fetch(" not in blk and "XMLHttpRequest" not in blk and "WebSocket" not in blk)
check("bench motion: one rAF loop, stopped while hidden or under reduced motion", "requestAnimationFrame(benchFrame)" in blk and "if(D.hidden||RM)return" in blk)
check("bench motion: reduced motion sets values in place", blk.count("if(RM||D.hidden)") >= 3)
check("demo hook only with data-demo, and no socket in the demo", 'BM.demo)D.addEventListener("poa:demo"' in js and "if(BM.demo)wantLive=false;" in js)
check("the clock ticks on the second", "1000-Date.now()%1000" in js)
css = open(os.path.join(ROOT, "static/style.css")).read()
c0 = css.index("1.26.145 Bench motion"); c = css[c0:css.index(".bench.final .cd,.bench.closing .cd{animation:none}}", c0)]
check("motion css: reduced motion block", "@media (prefers-reduced-motion:reduce){.ldot,.lane .nw,.sm.nw,.lspk,.bump,.od>span,.flp>span" in c)
props = set(re.findall(r"transition:([a-z-]+)", c))
check(f"motion css transitions transform, opacity and color only {sorted(props)}", props <= {"transform", "color", "opacity", "none"})
def frames(t):
    out = []
    for m in re.finditer(r"@keyframes\s+([\w-]+)\s*\{", t):
        d, j = 1, m.end()
        while d and j < len(t): d += {"{": 1, "}": -1}.get(t[j], 0); j += 1
        out.append((m.group(1), t[m.end():j - 1]))
    return out
kf = frames(c); bad = [n for n, b in kf if re.search(r"(?<![\w-])(?:width|height|top|left|right|bottom|margin|padding)\s*:", b)]
check(f"no layout property in a motion keyframe ({len(kf)} keyframes) {bad}", len(kf) >= 12 and not bad)
print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
