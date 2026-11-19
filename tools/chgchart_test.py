"""1.26.312 (Jake t530u): no change pill beside a chart's headline number (home cards, pop-outs); the period change reads
inside the chart, a quiet label under (or, near the floor, above) the value chip at the end point."""
import os, re, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_DB", os.path.join(tempfile.mkdtemp(), "t.db")); os.environ["POASCAN_INDEXER"] = "0"
from poascan import ui as U
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)
t0 = 1_790_000_000
ln = U.line([(t0 + i * 3600, 100 + i) for i in range(30)], height=220)
hd = ln[ln.find('<div class="chd">'):]; hd = hd[:hd.find("</div>")]
check("line: no pill in the headline row", 'class="chg' not in hd and 'class="chv"' in hd)
check("line: the change sits in the value chip", re.search(r'<span class="lv"[^>]*><b>[^<]+</b><i class="lvc up">\+29\.0%</i></span>', ln) is not None)
br = U.bars([(f"E{i}", [10 + i]) for i in range(8)], height=220, fmt=lambda v: f"{int(v):,}")
check("bars: no pill in the headline, change in the chip", 'class="chg' not in br and '<i class="lvc up">' in br)
dn = U.line([(t0 + i * 3600, 100 - 3 * i) for i in range(30)], height=220)
check("down: reads dn, above the chip near the floor", '<i class="lvc dn">' in dn and 'class="lv lvu"' in dn)
nh = U.line([(t0 + i * 3600, 100 + i) for i in range(30)], height=220, head=False)
check("no headline, no change label", "lvc" not in nh)
css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
check("css: quiet label, no pill background", ".lv .lvc{position:absolute;left:0;top:100%" in css and ".lv.lvu .lvc{top:auto;bottom:100%" in css)
check("no em or en dash", not re.search("[\u2013\u2014]", ln + br))
print("\nall passed" if not fails else f"\n{len(fails)} failed"); sys.exit(1 if fails else 0)
