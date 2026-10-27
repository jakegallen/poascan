"""No chart gaps (1.26.175): every line (Home sparklines, the pop-out, Network and Governance charts) runs continuously across a
genesis cut or missing data, as a straight segment between real points (no point is made up); the cut is a milestone on the
charts it affects instead of a break. Temp database, no network. Usage: python3 tools/nogap_test.py"""
import glob, json, os, re, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ.pop("POASCAN_SEGMENTS", None)
os.environ.update(POASCAN_DB=os.path.join(tmp, "a.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
from poascan import db
db.init()
db.put_blob("networks", {"default_chain": "poa-mainnet-1", "chains": [{"chain_id": "poa-mainnet-1-segment1", "status": "halted", "default": False},
                                                                       {"chain_id": "poa-mainnet-1", "status": "live", "default": True}]})
from poascan import segments as SG, analytics as A, chartpop as CP, ui as U, milestones as MS
cut = SG.CUT_TS; now = int(time.time())
# status snaps on both sides of the cut with a 9 h hole (missing data) after it; counters restart at the cut
for i, t in enumerate(list(range(cut - 30 * 3600, cut, 900)) + list(range(cut + 9 * 3600, now, 900))):
    db.write("INSERT INTO snaps(kind, ts, json) VALUES('status', ?, ?)", (t, json.dumps({"agents_joined": 5000 + i if t < cut else 4900 + i, "holders": 700 + i // 10, "supply": 1e9 + i, "txs": i})))
A._cache.clear()
seen = 0
for k in CP.CHARTS:
    for r in CP.ranges(k, time.time()) or []:
        p = CP.payload(k, r, 800); seen += 1
        if p.get("breaks"): check(f"pop-out {k} {r}: no breaks", False)
check(f"pop-out: no chart sends a break, every key and range ({seen} payloads)", seen > 4 and not [f for f in fails if f.startswith("pop-out ")])
check("chartpop has no break list left", not hasattr(CP, "BREAK_AT_CUT"))
pts = [(cut - 7200, 5300), (cut - 3600, 5341), (cut + 9 * 3600, 4941), (cut + 10 * 3600, 4950)]
ln = U.line(pts); d = re.findall(r' d="([^"]+)"', ln)
check("Network chart line: one path across the cut and a 9 h hole, one M, straight L segments", d and all(x.count("M") == 1 for x in d))
sv = U.spark(pts)
check("sparkline: one polyline through every real point (none made up)", sv.count("<polyline") == 1 and len(re.search(r'points="([^"]+)"', sv).group(1).split()) == len(pts))
src = "".join(open(f, encoding="utf-8").read() for f in glob.glob(os.path.join(ROOT, "poascan", "*.py")))
check("no caller passes breaks= to a chart", "breaks=" not in src.replace("breaks=[])", ""))
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("app.js pop-out never splits the line", "d.breaks" not in js and "runs=[P]" in js)
on = MS.charts_of("genesis_cut")
check(f"the genesis cut stays a milestone on the charts it affects, sparklines included ({sorted(on)})",
      all(c in on for c in ("agents", "holders", "joins", "active", "home-agents", "home-active", "home-holders")))
print("\n" + ("all passed" if not fails else f"{len(fails)} failed")); sys.exit(1 if fails else 0)
