"""Active Agents chart (1.26.146): the Home card's sparkline and pop-out from POAScan's own tx archive.
* active_runs: at each whole hour, the distinct Agents that answered (challenge txs) in the 24 h before it, within that
  segment only; a run starts at the first hour after its first answer (never padded) and the current one ends at now
  with the card value
* the pop-out: all four ranges, a break at each genesis cut, mining milestones only, the one line definition and Method
* Home: the Active Agents card opens the pop-out like its siblings, its label carries the same definition
Temp database, no network. Usage: python3 tools/active_series_test.py"""
import json, os, re, sys, tempfile, time
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
NW = {"default_chain": "poa-mainnet-1", "chains": [{"chain_id": "poa-mainnet-1-segment1", "status": "halted", "default": False},
                                                   {"chain_id": "poa-mainnet-1", "status": "live", "default": True}]}
db.put_blob("networks", NW)
from poascan import segments as SG, analytics as A, chartpop as CP, milestones as MS, views as V

# ---------------- pure: active_runs ----------------
H = 3600; c = 1000 * 24 * H + 1800    # a cut half way through an hour
segs = [dict(n=1, start_ts=None, end_ts=c), dict(n=2, start_ts=c, end_ts=None)]
h0 = c // H - 30
rows = [(1, h0, "a"), (1, h0, "b"), (1, h0 + 1, "a"), (1, h0 + 5, "c"), (1, c // H, "d"),   # segment 1, the last in the cut hour
        (2, c // H + 2, "a"), (2, c // H + 2, "x"), (2, c // H + 3, "y")]
now = (c // H + 6) * H + 900
r = A.active_runs(rows, segs, now, live=3)
s1 = [p for p in r if p[0] <= c]; s2 = [p for p in r if p[0] > c]
check(f"segment 1 starts the hour after its first answer ({s1[0]})", s1[0] == ((h0 + 1) * H, 2))
check("no point before the first real answer (never padded)", min(t for t, _ in r) == (h0 + 1) * H)
check("rolling 24 h: an Agent drops out 24 h after its last answer", dict(s1)[(h0 + 25) * H] == 2 and dict(s1)[(h0 + 26) * H] == 1 and dict(s1)[(h0 + 6) * H] == 3)
check("segment 1 ends at its last hour boundary before the cut", s1[-1][0] == c // H * H)
check("segment 2 starts the hour after its first answer, counting segment 2 only", s2[0] == ((c // H + 3) * H, 2))
check(f"no window crosses the cut: a segment 1 Agent never counts in segment 2 ({s2})", all(v <= 3 for _, v in s2) and dict(s2)[(c // H + 4) * H] == 3)
check("the current segment ends at now with the card value", r[-1] == (now, 3))
check("hour boundaries are whole hours, oldest first", all(t % H == 0 for t, _ in r[:-1]) and [t for t, _ in r] == sorted(t for t, _ in r))
check("a segment with no answers draws nothing", A.active_runs([], segs, now, live=0) == [])
check("an archived segment never takes the live value", A.active_runs([(1, h0, "a")], segs, now, live=9)[-1][1] != 9)

# ---------------- the archive: one indexed read, both segments ----------------
cut = SG.CUT_TS; tnow = int(time.time())
pa = lambda i: "poa1" + str(i) * 40
seed = [("s1a", "challenge", pa(1), cut - 30 * H, 1), ("s1b", "challenge", pa(2), cut - 29 * H, 1), ("s1c", "challenge", pa(9), cut - 60, 1),
        ("s2a", "challenge", pa(1), tnow - 3 * H, 2), ("s2b", "challenge", pa(3), tnow - 2 * H, 2), ("s2c", "challenge", pa(3), tnow - H, 2),
        ("s2g", "grade-sealed", pa(4), tnow - 400, 2), ("s2j", "join", pa(5), tnow - 300, 2)]
db.write("DELETE FROM txs")
for i, t, f, ts, sg in seed: db.write("INSERT INTO txs(id, type, from_addr, ts, epoch, segment) VALUES (?,?,?,?,?,?)", (i * 8, t, f, ts, 1, sg))
A._cache.clear()
ser = A.active_series(); card = A.active_agents()["active_agents"]
check(f"series starts at the chain's first archived answer, an hour boundary after it ({ser[:1]})", ser and ser[0][0] == (cut - 30 * H) // H * H + H)
check(f"series ends at now with the card value ({ser[-1]}, card {card})", ser[-1][1] == card == 2 and ser[-1][0] >= tnow - 5)
check("grades and joins are not answers", max(v for _, v in ser) <= 3)
check("segment 1 points stop at the cut", not any(cut < t < cut + 1 for t, _ in ser) and all(t <= cut for t, v in ser if t < cut))
src = open(os.path.join(ROOT, "poascan", "analytics.py")).read()
fn = src[src.index("def active_runs"):src.index('@cached("joins_rate"')]
check("no upstream call in the series code", not any(w in fn for w in ("urlopen", "requests", "fetch(", "POA_BASE")))

# ---------------- the pop-out ----------------
p = CP.payload("active", "all", 800)
check("pop-out: Active Agents, whole numbers from zero, all four ranges", p["title"] == "Active Agents" and p["fmt"] == "int" and p["y0"] and p["ranges"] == ["24h", "7d", "30d", "all"])
check("pop-out: the same points as the Home sparkline", [x[0] for x in p["pts"]] == [int(t) for t, _ in ser])
check(f"pop-out: the line breaks at the genesis cut ({p['breaks']})", p["breaks"] == [cut])
ev = [e["key"] for e in MS.events("active")]
check(f"milestones: the cut and mining pauses and reopenings only ({ev})", "genesis_cut" in ev and "s2_mining_reopened" in ev and "allclear" in ev and "begins" in ev
      and not any(k in ev for k in ("s2_first_join", "grading_reopened", "ended")))
check("milestone labels on this chart read Mining, not Joining", all(e["label"] != "Joining reopened" for e in MS.events("active")))
tip = p.get("tip") or ""
check(f"tooltip: one plain definition matching the window ({tip!r})", tip == CP.TIPS["active"][0] and "24 hours" in tip and "mined" in tip and "genesis cut" in tip and p.get("method") == "/about#home")
check("tooltip: terse, says Agents, no Accounts, no em or en dash", len(tip) <= 120 and "Agents" in tip and "ccount" not in tip and not re.search("[\u2013\u2014]", tip))
check("other charts carry no tip", "tip" not in CP.payload("mined", "7d", 800))
check("parse accepts the active key", CP.parse({"c": ["active"], "r": ["24h"]})[0] == "active")
q = CP.payload("active", "24h", 800)
check("24h shows the last day of real points (or the last two when quiet)", len(q["pts"]) >= 2 and all(t >= tnow - 86400 for t, _ in q["pts"][-2:]))

# ---------------- Home and app.js ----------------
home = V.home(); home = home if isinstance(home, str) else str(home)
k = re.search(r'<section class="stats four kpis"[^>]*>(.*?)</section>', home, re.S).group(1)
card_html = k[k.index('data-chart="active"') - 40:] if 'data-chart="active"' in k else ""
check("Home: the Active Agents card opens the pop-out (data-chart=active, role=button)", 'data-chart="active" role="button"' in k and 'aria-haspopup="dialog"' in card_html)
check("Home: all four headline cards open a chart", len(re.findall(r'data-chart="(mined|circ|agents|active)"', k)) == 4)
check("Home: the card keeps its sparkline and live value", '<svg class="spk"' in card_html and 'data-live="active"' in card_html)
check("Home: the card label carries the same definition on hover, no sub-line", f'title="{CP.TIPS["active"][0]}"' in card_html and 'class="sub' not in card_html)
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("app.js: active is an allowed chart key with its title", '"active"' in re.search(r"var CPK=\[[^\]]*\]", js).group(0) and 'active:"Active Agents"' in js)
check("app.js: the pop-out ? is the qtip pattern (details, summary, note, Method)", 'class="qtip cp-tip"' in js and 'role="note"' in js and "Method" in js)
check("app.js: hover opens it for a mouse only; Escape closes the note first", 'e.pointerType==="mouse"' in js and 'e.key==="Escape"&&$("details[open]",cq)' in js)
css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
check("style.css: the note opens under the title inside the dialog", ".cp-hd .cp-tip .qbox{position:absolute" in css)
ab = V.about(); ab = ab if isinstance(ab, str) else str(ab)
check("/about: the chart method is stated", "Its sparkline and chart draw the same count at each whole hour" in ab)

print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
