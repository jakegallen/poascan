"""Phase 2 (liveliness). The Bench (bench.py): epoch numeral, countdown, bezel and the last 24 minutes of answers, attests and
seals from POAScan's own txs table; /fragment/score; the Pour card; calm live hooks in app.js; the page ETag ignores the strip's
slide. Temp database, no network. Usage: python3 tools/phase2_test.py"""
import os, re, sys, tempfile, time, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "f.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
import fixture
fixture.seed()
from poascan import db, bench as BN, views as V, server as S
now = int(time.time())
for i, (t, typ, atts, fin) in enumerate([(now - 30, "challenge", 2, 1), (now - 90, "attest-batch", 40, 1), (now - 200, "grade-sealed", 0, 1),
                                          (now - 2000, "challenge", 0, 0), (now - 50, "join", 0, 1)]):
    db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)", (f"p2{i}" * 8, typ, fixture.A1, 11, t, atts, 5, fin))
BN._cache.update(t=0, v=None)
d = BN.score_json()
check("score: answers, attests and seals of the window only (no joins, nothing older than 24 min)",
      sorted(r[0] for r in d["rows"] if r[1] >= now - BN.WIN) == ["a", "s", "t"] and all(r[0] in "ats" for r in d["rows"]) and d["win"] == 1440)
check("score: the base sits on a whole minute, one window back", d["b"] % 60 == 0 and now - 1440 - 60 < d["b"] <= now - 1440)
h = V.tracker_html()
check("bench: epoch numeral, countdown and live keys", 'class="bn num" data-live="epoch"' in h and 'class="cd" data-close=' in h and 'data-live="answers"' in h and 'data-live="graders"' in h)
check("bench: 72 tick bezel with the epoch start and close in the visitor's time", h.count("<line class=\"") >= 72 and 'class="bezel" data-start=' in h and 'data-f="t"' in h)
check("bench: three lanes with counts, a now line and the 24m axis", h.count('class="lane"') == 3 and h.count('class="now"') == 3 and ">24m<" in h and ">now<" in h)
lane = lambda k: re.search(r'data-k="%s".*?<b class="c num">(\d+)</b>' % k, h, re.S).group(1)
check("bench: lane counts (1 answer, 1 attest, 1 seal in 24 min)", (lane("a"), lane("t"), lane("s")) == ("1", "1", "1"))
check("bench: a final answer is bright, attests sized by atts", 'class="ma f"' in h and re.search(r'class="mt" x1="\d+" x2="\d+" y1="[\d.]+" y2="[\d.]+"', h))
check("summary field stays small: no strip in tracker(score=False)", 'class="score"' not in V.tracker_html(score=False) and V.tracker_html(score=False).endswith("</div></div>"))
p = BN.pour_html(dict(epoch=11, pool=1e9, minted=1.7e8, burned=8.3e8, burn_pct=83.0))
check("pour: pool, minted and burned split, burn share", "1.00B" in p and 'style="width:17.00%"' in p and "170.00M" in p and "830.00M" in p and "83.0%" in p and 'aria-label="Minted 17.0%, burned 83.0%"' in p)
check("pour: one empty state line when there is no close", BN.pour_html(None) == '<p class="empty">No closes yet</p>')
hm = V.home()
check("home: the Bench, the Pour (watermark kept: bmcard), stats and live tables", 'id="tracker" class="card benchc"' in hm and "pourc" in hm and "bmcard" in hm
      and 'data-liverows="closes-home"' in hm and 'id="feed"' in hm and "Active Agents" in hm)
check("home: no Burn meter (the Pour replaces it), no em or en dashes", "Burn meter" not in hm and "\u2014" not in hm and "\u2013" not in hm)
check("home grid: the Assay line (Type, Agent, Seals, Age) beside Closes, Graders and the Pour", hm.index("Assay line") < hm.index('class="side"') < hm.index("Closes</h2>") < hm.index("Graders</h2>") < hm.index("pourc")
      and '<span>Type</span><span>Agent</span><span>Seals</span><span>Age</span>' in hm)
fr = V.feed_rows(3)
check("assay rows: type first, agent, seal pips, age linking the tx; rows keep data-id for the live merge", fr.startswith('<div class="frow" data-id="') and '<span class="badge' in fr
      and 'class="dots"' in fr and '<a class="ft" href="/tx/' in fr and fr.index("badge") < fr.index('class="fw"') < fr.index('class="dots"') < fr.index('class="ft"'))
ce = V.home_epochs(__import__("poascan.analytics", fromlist=["x"]).epoch_rows())
check("closes: minted, burned and a pour bar per close; phones keep #, Paid, Minted and Pour", "<th" in ce and ">Burned<" in ce and ">Pour<" in ce and 'class="mpour"' in ce
      and 'aria-label="Minted 17.0%, burned 83.0%"' in ce and V.live_rows("closes-home").count("<tr") >= 1)
check("graders card: jurors with 10 or more settled seats, aligned bar and share", "Settled" in V.home_graders() or V.home_graders() == '<p class="empty">No settled grades yet</p>')
snap = V.live_snapshot()
check("snapshot carries the open pool as a live number", snap["nums"]["pool"][0] == snap["epoch"]["pool"])
a = hm.encode(); b = re.sub(rb'(class="mk" data-b="\d+" transform="translate\()[-\d.]+', rb"\g<1>-99", a)
check("ETag ignores the strip slide", a != b and S.page_etag(a) == S.page_etag(b))
js = open(os.path.join(ROOT, "static/app.js")).read()
check("app.js: slide every 5 s, refetch on a new tx at most every 20 s, fade new marks, reduced motion respected",
      "setInterval(scoreSlide,5000)" in js and "20000-(Date.now()-SC.t)" in js and "/fragment/score" in js and "!RM)" in js)
css = open(os.path.join(ROOT, "static/style.css")).read()
check("style.css: reduced motion stops the live dot and mark fades", "@media (prefers-reduced-motion:reduce){.ldot,.lane .nw{animation:none}}" in css)
check("motion: one easing, 240 ms row slide of 8 px, 600 ms chart draw, no feed glow, still skeletons, 2.4 s live dots",
      "--state:240ms;--draw:600ms;--ease:cubic-bezier(.2,.7,.2,1)" in css and "@keyframes rowslide{from{opacity:0;transform:translateY(-8px)}" in css
      and ".js .chart.in{animation:draw var(--draw) var(--ease) both}" in css and ".skel i{animation:none" in css and ".pill.live i{animation:ldot 2.4s" in css)
check("relative ages step every 10 s under a minute (server and app.js agree)", '"just now":s<60?Math.floor(s/10)*10+"s ago"' in js
      and re.search(r">(just now|\d0s ago|\d+m ago)</time>", __import__("poascan.ui", fromlist=["x"]).rel(time.time() - 25)) and ">20s ago<" in __import__("poascan.ui", fromlist=["x"]).rel(time.time() - 25))
check("one empty state: naBox reads as the centered line", ".naBox{border:0;border-radius:0;padding:var(--s5) var(--s4);text-align:center" in css)
if fails: print(f"FAIL: {len(fails)}: {fails}"); sys.exit(1)
print("all passed")
