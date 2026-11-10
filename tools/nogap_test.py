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
        if any(m[1] == "Genesis cut" for m in p.get("marks") or []): check(f"pop-out {k} {r}: no Genesis cut label", False)
check(f"pop-out: no chart sends a break, every key and range ({seen} payloads)", seen > 4 and not [f for f in fails if f.startswith("pop-out ")])
check("chartpop has no break list left", not hasattr(CP, "BREAK_AT_CUT"))
pts = [(cut - 7200, 5300), (cut - 3600, 5341), (cut + 9 * 3600, 4941), (cut + 10 * 3600, 4950)]
ln = U.line(pts); d = re.findall(r' d="([^"]+)"', ln)
check("Network chart line: one path across the cut and a 9 h hole, one M, straight L segments", d and all(x.count("M") == 1 for x in d))
sv = U.spark(pts)
_sl = re.search(r'class="sl" d="([^"]+)"', sv)
check("sparkline: one line path through every real point (none made up): one M, one curve per gap (UI/UX P3)", sv.count('class="sl"') == 1 and _sl.group(1).count("M") == 1 and _sl.group(1).count("C") + _sl.group(1).count("L") == len(pts) - 1)
src = "".join(open(f, encoding="utf-8").read() for f in glob.glob(os.path.join(ROOT, "poascan", "*.py")))
check("no caller passes breaks= to a chart", "breaks=" not in src.replace("breaks=[])", ""))
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("app.js pop-out never splits the line", "d.breaks" not in js and "box.innerHTML=d.html" in js)   # 1.26.310: the kit line from the server
on = MS.charts_of("genesis_cut")
check("the genesis cut is not a chart or sparkline label (1.26.277); the line stays continuous and the table keeps the event",
      on == () and any(e["key"] == "genesis_cut" and e["label"] == "Genesis cut" for e in MS.events())
      and not any(e["label"] == "Genesis cut" for c in ("agents", "holders", "joins", "active", "home-agents") for e in MS.events(c)))
print("\n" + ("all passed" if not fails else f"{len(fails)} failed")); sys.exit(1 if fails else 0)
