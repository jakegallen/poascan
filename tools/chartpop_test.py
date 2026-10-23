"""Chart pop-out (poascan/chartpop.py, static/app.js).
* URL param parsing and allowlist: app.js cpParse and cpSearch run in node (skipped if node is missing); ?chart= takes a
  known key only, ?range= a known range only, and closing clears both (the Network > Charts page range is kept)
* /fragment/chart: strict params (c, r, w; one value each, nothing else is a 400), known keys and ranges only
* every chart offers all four ranges (24h, 7d, 30d, All, plus Epoch for per epoch data); a range wider than the history
  shows all of it, a quiet 24h still draws, windows are never padded, milestones are grouped with milestones.group, no upstream
* milestone labels sit in lanes above the plot (never over the line, each other or the axis labels)
* the openers are on the page (home headline row and Holders, Network > Charts cards, /token) and there are no share buttons
* nothing in the pop-out can start invisible: no entrance animation and no opacity 0 (the 1.26.28 iOS rule)
Usage: python3 tools/chartpop_test.py"""
import json, os, re, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "c.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"   # nothing listens
import fixture; fixture.seed()
from poascan import db, chartpop as CP, milestones as MS, indexer as I, analytics as A

js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()

# ---------------- URL params in the browser (node) ----------------
m = re.search(r"/\* chartq:begin.*?\*/(.*?)/\* chartq:end \*/", js, re.S)
check("app.js has the cpParse / cpSearch block", bool(m))
node = shutil.which("node")
if m and node:
    cases = [("?chart=supply&range=7d", {"c": "supply", "r": "7d"}), ("?chart=agents", {"c": "agents", "r": ""}), ("?tab=charts&chart=answers&range=epoch", {"c": "answers", "r": "epoch"}),
             ("?chart=supply&range=1y", {"c": "supply", "r": ""}), ("?chart=supply&range=7d&range=24h", {"c": "supply", "r": ""}), ("?chart=nope&range=7d", None),
             ("?chart=Supply", None), ("?chart=supply&chart=agents", None), ("?chart=%3Cscript%3E", None), ("?chart=", None), ("", None), ("?range=7d", None),
             ("?chart=__proto__", None), ("?chart=constructor", None)]
    srch = [(["?tab=charts&range=24h", "supply", "7d", None], "?tab=charts&range=7d&chart=supply"), (["", "agents", "24h", None], "?chart=agents&range=24h"),
            (["?chart=supply&range=7d", None, None, None], ""), (["?tab=charts&range=30d&chart=supply", None, None, "24h"], "?tab=charts&range=24h"),
            (["?chart=supply&range=7d", "evil", "7d", None], ""), (["?chart=txs", "txs", "1y", None], "?chart=txs")]
    prog = m.group(1) + "\nconsole.log(JSON.stringify({p:" + json.dumps([c for c, _ in cases]) + ".map(cpParse),s:" + json.dumps([a for a, _ in srch]) + ".map(function(a){return cpSearch.apply(null,a)})}))"
    out = json.loads(subprocess.run([node, "-e", prog], capture_output=True, text=True, check=True).stdout)
    for (q, want), got in zip(cases, out["p"]): check(f"cpParse({q!r}) is {want}", got == want)
    for (a, want), got in zip(srch, out["s"]): check(f"cpSearch{tuple(a)} is {want!r}", got == want)
    keys = json.loads(re.search(r"var CPK=(\[[^\]]*\])", m.group(1)).group(1)); rngs = json.loads(re.search(r"CPR=(\[[^\]]*\])", m.group(1)).group(1))
    check("browser allowlist matches the server's (keys)", sorted(keys) == sorted(CP.CHARTS))
    check("browser allowlist matches the server's (ranges)", rngs == list(CP.RANGES))
else:
    print("skip node checks (node not installed)")

# ---------------- server param parsing ----------------
def bad(qs):
    try: CP.parse(qs); return False
    except ValueError: return True
check("parse: key, range and width", CP.parse({"c": ["supply"], "r": ["7d"], "w": ["1000"]}) == ("supply", "7d", 1000))
check("parse: width clamps and buckets", CP.parse({"c": ["agents"], "w": ["99"]})[2] == 200 and CP.parse({"c": ["agents"], "w": ["9999"]})[2] == 2400 and CP.parse({"c": ["agents"], "w": ["1013"]})[2] == 1000)
check("parse: no range means the default", CP.parse({"c": ["holders"]})[1] == "")
for name, qs in [("unknown key", {"c": ["nope"]}), ("no key", {}), ("unknown range", {"c": ["supply"], "r": ["1y"]}), ("two keys", {"c": ["supply", "agents"]}),
                 ("two ranges", {"c": ["supply"], "r": ["7d", "24h"]}), ("extra param", {"c": ["supply"], "key": ["pk_x"]}), ("width not a number", {"c": ["supply"], "w": ["1e3"]}),
                 ("width too long", {"c": ["supply"], "w": ["12345"]}), ("key case", {"c": ["Supply"]})]:
    check(f"parse: 400 on {name}", bad(qs))

# ---------------- ranges: always all four ----------------
now = 2_000_000_000; D = 86400
real = CP.series
def fake(pts):
    CP.series = lambda key, rng="": pts
def rg(key, pts): fake(pts); r = CP.ranges(key, now); CP.series = real; return r
FOUR = ["24h", "7d", "30d", "all"]
h35 = [(now - 3.5 * D + i * 900, i) for i in range(int(3.5 * 96))]
check("3.5 days of history: all four ranges", rg("agents", h35) == FOUR)
check("12 hours: all four ranges", rg("agents", [(now - 12 * 3600 + i * 900, i) for i in range(48)]) == FOUR)
check("40 days: all four ranges", rg("supply", [(now - 40 * D + i * 3600, i) for i in range(960)]) == FOUR)
check("stale series (nothing in 24h): still all four", rg("agents", [(now - 3 * D + i * 900, i) for i in range(96)]) == FOUR)
check("per epoch data adds Epoch after the four", rg("circ", h35) == FOUR + ["epoch"])
check("Answers: the four (its bars are per epoch, All is the Epoch view)", rg("answers", [(e, now - 40 * D + e * 21600, [1, 1]) for e in range(160)]) == FOUR)
check("every key offers 24h, 7d, 30d and All", all(rg(k, h35)[:4] == FOUR for k in CP.CHARTS))
check("no data: no ranges", rg("agents", []) == [])
check("pick: what was asked, Epoch on Answers is All, default 7d", CP.pick("30d", FOUR) == "30d" and CP.pick("all", FOUR) == "all" and CP.pick("epoch", FOUR) == "all"
      and CP.pick("", FOUR) == "7d" and CP.pick("epoch", FOUR + ["epoch"]) == "epoch")
w = CP.window([(now - 3 * D, 1), (now - 2 * D, 2)], now - D)
check("window: a quiet 24h draws from the last real points before it, never padded", w == [(now - 3 * D, 1), (now - 2 * D, 2)])
check("window: enough points inside, nothing added", CP.window([(now - 3 * D, 1), (now - 600, 2), (now - 300, 3)], now - D) == [(now - 600, 2), (now - 300, 3)])

# ---------------- payloads from the fixture, no upstream ----------------
t = int(time.time())
for i in range(int(3.5 * 96)):   # 3.5 days of status snaps: Agents, Holders, Supply
    db.add_snap("status", {"agents_joined": 2000 + 5 * i, "holders": 10 + i, "supply": str(1e8 + 1e6 * i)}, t - int(3.5 * D) + i * 900)
I.flush_counts(force=True); before = db.q1("SELECT COALESCE(SUM(n),0) AS n FROM upstream_counts")["n"]
A._cache.clear()
p7 = CP.payload("supply", "7d", 1000); p30 = CP.payload("agents", "30d", 400); pa = CP.payload("answers", "", 800); pe = CP.payload("circ", "epoch", 800)
pj = CP.payload("joins", "24h", 800); pt = CP.payload("txs", "", 800)
I.flush_counts(force=True)
check("no upstream request for any chart", db.q1("SELECT COALESCE(SUM(n),0) AS n FROM upstream_counts")["n"] == before)
check("Supply 7d: line, all four ranges offered", p7["kind"] == "line" and p7["range"] == "7d" and p7["ranges"] == FOUR)
check("window starts at the first real point (no padding)", p7["pts"][0][0] >= t - int(3.5 * D) - 900)
check("30d on 3.5 days of history: 30d, with all of it", p30["range"] == "30d" and len(p30["pts"]) > 1 and p30["pts"][0][0] >= t - int(3.5 * D) - 900)
for k in CP.CHARTS:
    for r_ in ("24h", "7d", "30d", "all"):
        pk = CP.payload(k, r_, 400)
        check(f"{k} {r_}: shows that range with data, no empty state", pk["range"] == r_ and pk["ranges"][:4] == FOUR and (len(pk["pts"]) > 1 if pk["kind"] == "line" else len(pk["bars"]) > 0))
pall = CP.payload("agents", "all", 400); p7a = CP.payload("agents", "7d", 400)
check("All and 7d on short history show the same full history", pall["pts"] == p7a["pts"])
evs = [e for e in MS.events() if p7["pts"][0][0] <= e["ts"] <= p7["pts"][-1][0]]
want = [[a, b, c] for a, b, _u, c in MS.group(evs, p7["pts"][0][0], p7["pts"][-1][0], width=1000 - 64)] if evs else []
check("milestones grouped with milestones.group at the plot width", p7["marks"] == want)
check("Answers per epoch: bars with Answered and Paid", pa["kind"] == "bars" and pa["legend"] == ["Answered", "Paid"] and all(re.fullmatch(r"E\d+", b[0]) for b in pa["bars"]))
check("Circulating Epoch view: one bar per closed epoch", pe["kind"] == "bars" and len(pe["bars"]) == len(A.epoch_rows()))
check("Agents / hr and Txs / hour are lines", pj["kind"] == "line" and pt["kind"] == "line" and pt["title"] == "Txs / hour")
check("every key builds", all(CP.payload(k, "", 800)["c"] == k for k in CP.CHARTS))
check("labels are terse with no em or en dash", all(len(c["title"]) <= 20 for c in CP.CHARTS.values()) and not re.search("[\u2013\u2014]", open(os.path.join(ROOT, "poascan", "chartpop.py"), encoding="utf-8").read()))

# ---------------- page markup and CSS ----------------
from poascan import views as V
home = V.home()["body"] if isinstance(V.home(), dict) else str(V.home())
for k in ("mined", "circ", "agents", "joins", "holders"): check(f"home: {k} stat opens the pop-out", f'data-chart="{k}" role="button" tabindex="0"' in home)
net = str(V.network("charts", "7d"))
for k in ("agents", "holders", "supply", "txs", "answers"): check(f"Network > Charts: {k} card opens the pop-out (card and Expand button)", f'class="cpw" data-chart="{k}"' in net and f'class="cpx" data-chart="{k}"' in net)
tok = str(V.token())
for k in ("supply", "holders", "circ"): check(f"/token: {k} stat opens the pop-out", f'data-chart="{k}"' in tok)
blk = js[js.index("/* chart pop-out"):js.index("if(wantLive)connect();")]
check("dialog: modal dialog with a label, Esc (cancel), close button, focus trap and focus return", all(s in blk for s in ('createElement("dialog")', "aria-labelledby", "showModal", '"cancel"', "data-cpclose", 'e.key!=="Tab"', "o.focus(")))
check("URL follows by replaceState and is cleared on close", blk.count("history.replaceState") == 2 and "cpSearch(location.search,null,null,KEEP)" in blk)
check("no share buttons (Jake's rule)", not re.search(r"share", blk, re.I) and "navigator.share" not in js)
check("data comes from POAScan only", re.findall(r'fetch\("([^"?]+)', blk) == ["/fragment/chart"] and "minepoa" not in blk)
cs = css[css.index("/* chart pop-out (app.js"):]
cs_flat = re.sub(r"/\*.*?\*/", "", cs, flags=re.S)
check("pop-out CSS has no entrance animation and no opacity 0 on content", "animation" not in cs_flat.replace("animation:none", "") and not re.search(r"\.(cpop|cp-in|cp-box|cpchart|cp-hd)[^{]*\{[^}]*opacity:\s*0(?![.\d])", cs_flat))
check("phones: full screen, touch scrub on the plot", re.search(r"@media \(max-width:640px\)\{\s*\.cpop\{width:100%;height:100%", cs_flat) is not None and "touch-action:none" in cs_flat)
check("watermark on the big chart (chartbox)", 'class="chartbox cp-box"' in blk)
check("milestone labels: lanes above the plot with a background, plot top moves down, no labels near the x axis",
      "pt=8+20*ends.length+10" in blk and 'class="mkb"' in blk and "H-pb-8-(j%2)*14" not in blk and ".cpchart .mk .mkb{" in cs_flat)
check("reduced motion covered", "prefers-reduced-motion:reduce){.cpt .cpi,.cp-box .xh,.cp-box .xt" in cs_flat)
check("no em or en dash in the pop-out code", not re.search("[\u2013\u2014]", blk + cs))

# ---------------- HTTP ----------------
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
port = free_port()
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0", POASCAN_MAINTENANCE="0")
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f"http://127.0.0.1:{port}"
def get(path):
    try:
        r = urllib.request.urlopen(base + path, timeout=10); return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e: return e.code, e.read().decode(), e.headers
try:
    for _ in range(80):
        try: urllib.request.urlopen(base + "/robots.txt", timeout=1); break
        except Exception: time.sleep(.25)
    c, b, h = get("/fragment/chart?c=supply&r=7d&w=900")
    check("GET /fragment/chart: 200 JSON, cached 60 s", c == 200 and json.loads(b)["c"] == "supply" and "max-age=60" in (h.get("Cache-Control") or ""))
    for k in CP.CHARTS:
        for r_ in ("30d", "all"):
            c, b, h = get(f"/fragment/chart?c={k}&r={r_}&w=390"); check(f"GET /fragment/chart?c={k}&r={r_}: 200 with that range", c == 200 and json.loads(b)["range"] == r_)
    for q in ("c=nope", "c=supply&r=1y", "c=supply&token=x", "c=supply&c=agents", "", "c=supply&w=-1"):
        c, b, h = get("/fragment/chart?" + q); check(f"GET /fragment/chart?{q}: 400", c == 400 and '"c"' not in b)
    c, b, h = get("/?chart=supply&range=7d"); check("a shared URL renders the page (the browser opens the pop-out)", c == 200 and 'data-chart="mined"' in b)
    c, b, h = get("/robots.txt"); check("/fragment/ stays out of crawlers", "Disallow: /fragment/" in b)
finally:
    srv.terminate(); srv.wait(10)

print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
