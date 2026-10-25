"""Epoch card tips: a ? note on every term of the Home Epoch card (bench.py TIPS, the qtip pattern), the /about#epoch-card list,
the lane total odometer (no roll from the outgoing digits, no roll when marks age out) and Seals capsules that add up to the
lane total. No network. Usage: python3 tools/epoch_tips_test.py"""
import os, re, sys, tempfile, time
os.environ.setdefault("POASCAN_SEGMENTS", "1")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "t.db")
import fixture; fixture.seed()
from poascan import db, bench as BN, views as V
now = int(time.time()); A1 = "poa1" + "A" * 40
db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,ts,atts,final) VALUES(?,?,?,?,?,?)",
         [("e0" * 32, "challenge", A1, now - 6, 1, 0), ("e1" * 32, "grade-sealed", A1, now - 40, 3, 1), ("e2" * 32, "attest-batch", A1, now - 90, 20, 0)], many=True)
h = V.tracker_html()
labels = re.findall(r'<details class="qtip hv btip"><summary aria-label="About ([^"]+)"', h)
want = ["Epoch", "Closes in", "Timeline", "Answers", "Graders", "Pool", "Last 24 min", "Answers lane", "Attests", "Seals", "Latest"]
check(f"every term on the card has its ? {labels}", sorted(labels) == sorted(want))
check("each ? links its Method to /about#epoch-card", h.count('<a href="/about#epoch-card">Method</a>') == len(want))
for k, t, x in BN.TIPS:
    s = [p for p in re.split(r"(?<=[.!?])\s+", x.strip()) if p]
    check(f"{t}: one or two sentences, no dashes, Agents not Accounts", 1 <= len(s) <= 2 and not re.search("[\u2013\u2014]", x) and "ccount" not in x)
check("facts from the sources: 6 hours, quorum 4, jury of 9, 10% grading, 2,000 per close, 16 epoch TTL, 100 per attest, 5 attests final",
      all(any(f in x for _, _, x in BN.TIPS) for f in ("6 hours", "4 seals", "9 graders", "9 drawn", "10%", "2,000", "16 epochs", "up to 100", "5 attests")))
check("the seal tip never says a sealed grade can be read", "sealed until the answer settles" in BN.TIP["lane_s"][1] and not re.search(r"\b(decode|read|reveal)", BN.TIP["lane_s"][1]))
check("no referral codes in the tips", not re.search(r"poa1|ref=|invite", " ".join(x for _, _, x in BN.TIPS)))
check("the bezel drawing stays hidden from screen readers, its ? does not", '<svg viewBox="0 0 712 22" preserveAspectRatio="none" aria-hidden="true">' in h
      and re.search(r'<div class="bezel" data-start="[^"]*" data-close="[^"]*">', h) is not None)
check("no descriptive sub-lines under the stats (tips only)", re.search(r'<div class="trio">.*?</div></div></div>', h, re.S) is not None and "<p" not in re.search(r'<div class="trio">.*?</div></div></div>', h, re.S).group(0))
check("Graders keeps its detail on the number (title)", re.search(r'data-live="graders" title="[^"]+"', h) is not None)
ab = V.about() if callable(getattr(V, "about", None)) else ""
ab = ab if isinstance(ab, str) else str(ab)
check("/about lists the card terms under #epoch-card", 'id="epoch-card"' in ab and all(f"<b>{t}</b>" in ab for t in want))
# Seals capsules: only seals inside the window, the oldest held inside the start, so the capsules add up to the lane total
lo = now - BN.WIN
ts = [lo - 100 + i for i in range(150)] + [lo + 300 + i // 10 for i in range(40)]   # a burst straddling the window start, then a cluster
inw = [t for t in ts if t >= lo]
cl = BN.seal_clusters(inw, BN.NOMINAL_PX / BN.WIN, right=now, left=lo)
check("Seals capsules add up to the seals inside the window", sum(c[1] for c in cl) == len(inw) == 90)
check("the oldest capsule sits whole inside the window start", all((c[0] - lo) * BN.NOMINAL_PX / BN.WIN >= BN.seal_w(c[1]) / 2 for c in cl))
lay = BN.seal_layer(ts, BN.base(now), lo, now)
check("server render: capsule counts add up to the lane total", sum(int(n or 1) for n in re.findall(r'<i class="sm[^"]*"[^>]*>(\d*)</i>', lay)) == len(inw))
js = open(os.path.join(ROOT, "static/app.js"), encoding="utf-8").read(); css = open(os.path.join(ROOT, "static/style.css"), encoding="utf-8").read()
check("odometer reads the value it is heading to while a roll is in flight", "function odv(n){return n._v!=null&&$(\".od\",n)?n._v:n.textContent}" in js and "function odo(n,t){var o=odv(n);" in js)
check("lane totals: marks ageing out change the number in place, arrivals roll", re.search(r"function laneCount\(c,n,k\)\{var o=\+odv\(c\)\|\|0;if\(o===n\)return;if\(n<o\)\{[^}]*c\.textContent=c\._v;return\}", js) is not None)
check("lane totals roll without the gold flash", ".lane .c .od>span:not(.o){animation-name:odinq}" in css and re.search(r"@keyframes odinq\{0%\{transform:translateY\(\.9em\);opacity:0\}\}", css) is not None)
check("app.js: sealCluster holds the oldest inside the window start, and draws only seals inside it", "function sealCluster(ts,pxs,right,left)" in js and "inw=sealTs(sk).filter(function(t){return t>=lo})" in js)
check("qtip: hover opens a .qtip.hv on a mouse, leaving closes it, a click pins it", 'closest("details.qtip.hv")' in js and "q.dataset.hv=\"1\"" in js and "delete q.dataset.hv" in js)
check("qtip: a tap outside closes on iOS (pointerdown), Escape still closes", 'D.addEventListener("pointerdown"' in js and 'if(e.key!=="Escape")return;var o=D.querySelector("details.qtip[open]")' in js)
print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
