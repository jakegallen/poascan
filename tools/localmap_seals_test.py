"""1.26.135: the Agent activity map in the visitor's zone, and Seals on the Bench strip that never overlap. Server side: the map is
drawn in UTC (the no-JS view, labelled UTC) and ships 15 minute UTC slots; the Seals lane clusters marks at the narrowest lane width.
Client side (static/app.js, run under node with TZ set): pbucket rebuilds the map by local hour and day, matched against zoneinfo
for whole, half and quarter hour zones; sealCluster gives the same clusters as bench.seal_clusters. Temp database, no network.
Usage: python3 tools/localmap_seals_test.py"""
import json, os, random, re, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "f.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
import fixture
fixture.seed()
from poascan import db, bench as BN, profile as PF, views as V, server as S
js = open(os.path.join(ROOT, "static/app.js"), encoding="utf-8").read()
css = open(os.path.join(ROOT, "static/style.css"), encoding="utf-8").read()
NODE = shutil.which("node")

# 1. the activity map
A = "poa1" + "Q" * 38
now = int(time.time()); d0 = now // 86400 * 86400 - 6 * 86400
rnd = random.Random(7); stamps = sorted(rnd.randrange(d0 - 86400, now) for _ in range(400)) + [d0 + 3 * 86400 + 14 * 3600 + 5] * 3
for i, t in enumerate(stamps):
    db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)", (f"lm{i:06d}".ljust(64, "0"), "challenge", A, 11, t, 0, 5, 1))
h = PF.activity(A, now=now)
check("map: the server view is UTC days and hours, labelled UTC (no-JS fallback)", 'aria-label="Txs by hour, last 7 days, UTC"' in h and h.count('class="phr"') == 7
      and " UTC: " in h and time.strftime("%b %-d", time.gmtime(d0)) in h)
utc = {}
for t in stamps:
    if t >= d0: utc[((t - d0) // 86400, t % 86400 // 3600)] = utc.get(((t - d0) // 86400, t % 86400 // 3600), 0) + 1
day3 = time.strftime("%b %-d", time.gmtime(d0 + 3 * 86400))
check("map: a UTC cell counts its hour (title and shade)", f'title="{day3}, 14:00 UTC: {PF.txs(utc[(3, 14)])}"' in h)
m = re.search(r'data-q0="(\d+)" data-days="7" data-q="([^"]*)"', h)
q0, dq = int(m.group(1)), m.group(2)
slots = {int(a): int(b) for a, b in (p.split(":") for p in dq.split())}
check("map: data-q holds every tx in 15 minute UTC slots from a day before the first row", q0 == d0 - 86400 and sum(slots.values()) == len(stamps)
      and all(slots[q] == sum(1 for t in stamps if (t - q0) // 900 == q) for q in slots))
ov = PF.overview(A, None, [])
check("map: the card header names the zone in a span app.js relabels, UTC by default", 'Txs by hour · <span class="phz">UTC</span>' in ov)
check("map: no txs is one empty line", PF.activity("poa1" + "Z" * 38, now=now) == '<p class="empty">No txs in the last 7 days</p>')
check("map: app.js rebuilds it in the visitor's zone, relabels it and runs with the other local times",
      "function pheat(root)" in js and "function lt(root){pheat(root);" in js and '$(".phz",c)' in js and "tzn()||\"local\"" in js and '" UTC"' not in js[js.index("function pheat"):js.index("/* a dated UTC")])
check("map: server and client share the five steps", all(PF.step(n, mx) == (0 if not n else (1 + min(3, int(4 * (n - 1) / mx)) if mx > 1 else 4)) for mx in (1, 2, 9, 40) for n in range(mx + 1))
      and "function pstep(n,mx){return !n?0:mx>1?1+Math.min(3,Math.floor(4*(n-1)/mx)):4}" in js)

def js_fn(*names):
    return "\n".join(re.search(r"^function %s\(.*?(?=^function |^var |^D\.|^/\*)" % n, js, re.S | re.M).group(0) for n in names)
def node(code, tz="UTC"):
    r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, env=dict(os.environ, TZ=tz), timeout=60)
    if r.returncode: print(r.stderr[-800:])
    return json.loads(r.stdout or "null")
if NODE:
    for tz in ("UTC", "America/Los_Angeles", "Asia/Kolkata", "Asia/Kathmandu", "Pacific/Kiritimati", "America/St_Johns"):
        z = ZoneInfo(tz); ln = datetime.fromtimestamp(now, z); starts = [datetime(ln.year, ln.month, ln.day, tzinfo=z) - timedelta(days=6 - i) for i in range(8)]
        st = [int(s.timestamp()) for s in starts]; want = {}
        for t in stamps:
            if st[0] <= t < st[7]:
                d = max(i for i in range(7) if t >= st[i]); k = d * 24 + datetime.fromtimestamp(t, z).hour; want[str(k)] = want.get(str(k), 0) + 1
        got = node(js_fn("pstep", "pbucket") + f"\nvar B=pbucket({q0},7,{json.dumps(dq)},new Date({now}*1000));console.log(JSON.stringify(B))", tz)
        check(f"map in {tz}: every tx lands in its local hour and local day (zoneinfo agrees)", got and got["g"] == want and got["st"] == st and got["mx"] == max(want.values()))
else: print("skip node checks (no node)")

# 2. Seals that never overlap
def spaced(cl, pxs):
    return all((b[0] - a[0]) * pxs >= (BN.seal_w(a[1]) + BN.seal_w(b[1])) / 2 + BN.GAP - 1e-6 for a, b in zip(cl, cl[1:]))
rs = random.Random(3); bursts = []
for _ in range(30):
    c = rs.randrange(0, 1440); bursts += [c + rs.choice((0, 0, 1, 2, 3)) for _ in range(rs.choice((1, 1, 3, 12, 40)))]
for px in (150, 260, 460, 700, 1200):
    pxs = px / 1440; cl = BN.seal_clusters(bursts, pxs, right=1440)
    check(f"seals at {px} px: clusters keep every seal, never touch, stay inside the now line", sum(c[1] for c in cl) == len(bursts) and spaced(cl, pxs)
          and all(c[2] <= c[3] for c in cl) and (cl[-1][0] + BN.seal_w(cl[-1][1]) / 2 / pxs) <= 1440)
one = BN.seal_clusters([100, 400, 900], 260 / 1440)
check("seals: lone seals far apart stay single, at their own times", [c[:2] for c in one] == [[100.0, 1], [400.0, 1], [900.0, 1]])
same = BN.seal_clusters([500] * 25, 260 / 1440)
check("seals: a burst in one second is one mark with its count", same == [[500.0, 25, 500, 500]] and BN.seal_tip(same[0]) == "25 Seals · " + time.strftime("%H:%M:%S", time.gmtime(500)) + " UTC")
check("seals: a capsule fits its count", BN.seal_w(1) == 6 and BN.seal_w(9) == 18 and BN.seal_w(40) == 24 and BN.seal_w(480) == 30)
if NODE:
    for px in (260, 358, 700):
        want = BN.seal_clusters(bursts, px / 1440, right=1440)
        got = node(js_fn("sealW", "sealCluster") + f"\nconsole.log(JSON.stringify(sealCluster({json.dumps(bursts)},{px}/1440,1440)))")
        check(f"seals at {px} px: app.js sealCluster matches bench.seal_clusters", got is not None and len(got) == len(want)
              and all(abs(g[0] - w[0]) < 1e-9 and g[1:] == w[1:] for g, w in zip(got, want)))
for i in range(60):
    db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)", (f"sl{i:06d}".ljust(64, "0"), "grade-sealed", fixture.A1, 11, now - 300 - (i % 3), 0, 5, 1))
BN._cache.update(t=0, v=None)
tr = V.tracker_html()
lane = re.search(r'<div class="lane" data-k="s">.*?</b></div>', tr, re.S).group(0) if 'data-k="s"' in tr else ""
check("Seals lane: HTML clusters over the SVG, raw times for app.js, no stretched strokes", '<div class="plot">' in lane and '<div class="sk" data-b="' in lane and 'data-s="' in lane
      and 'class="ms"' not in lane and '<i class="sm" style="left:' in lane and ">60</i>" in lane)
check("Seals lane: the count still counts every seal in the window", re.search(r'<b class="c num">(\d+)</b>', lane).group(1) == str(sum(1 for r in BN.score_rows() if r[0] == "s" and r[1] >= time.time() - BN.WIN)))
check("Seals lane: no-JS hover reads UTC", re.search(r'title="60 Seals · \d\d:\d\d:\d\d to \d\d:\d\d:\d\d UTC"', lane))
check("summary field stays small: no strip in tracker(score=False)", 'class="score"' not in V.tracker_html(score=False) and V.tracker_html(score=False).endswith("</div></div>"))
hm = V.home().encode()
b2 = re.sub(rb'(<div class="sk" data-b="\d+" data-s="[^"]*" style="transform:translateX\()[-\d.]+', rb"\g<1>-9", hm)
b3 = re.sub(rb'(<i class="sm(?: s1)?" style="left:)[\d.]+', rb"\g<1>1", b2)
check("ETag ignores the Seals slide and the hold at the now line", hm != b3 and S.page_etag(hm) == S.page_etag(b3))
check("app.js: Seals recluster at the real width and on resize, slide with the strip, fade only new ones, tip on hover and tap",
      "sealDraw(sk,old)" in js and "W.addEventListener(\"resize\"" in js and "sealSlide(l,sk,now)" in js and "c[3]>old&&!RM" in js
      and 'e.pointerType==="mouse"' in js and "sealTip(m,1)" in js)
check("style.css: round capsules, a separating ring, a hit area for touch, no motion when reduced",
      ".sm{position:absolute;top:50%" in css and "box-shadow:0 0 0 2px var(--ink-2)" in css and ".sm::after{" in css
      and "@media (prefers-reduced-motion:reduce){.sm,.stip{transition:none}}" in css and "@media (prefers-reduced-motion:reduce){.ldot,.lane .nw{animation:none}}" in css)
for p in ("poascan/bench.py", "poascan/profile.py", "static/app.js", "static/style.css", "tools/localmap_seals_test.py"):
    check(f"no em or en dashes in {p}", not any(ch in open(os.path.join(ROOT, p), encoding="utf-8").read() for ch in "\u2014\u2013"))
if fails: print(f"FAIL: {len(fails)}: {fails}"); sys.exit(1)
print("all passed")
