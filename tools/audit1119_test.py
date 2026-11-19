"""1.26.398+ audit fixes (Nov 19): Start halted state and Check preview, Chain Backlog label; later batches add their checks below.
Usage: python3 tools/audit1119_test.py"""
import os, sys, tempfile, time, re
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, starthub as SH, maint
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)
SRC = lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read()
now = int(time.time()); day = 86400

# ---- batch 1: Start halted state ----
A.open_epoch = lambda: {"epoch": 7, "est_close": now + 3600, "last_close": now - 18000}
hrs = [[(now - 5 * day) // 3600 * 3600 + i * 3600, 30] for i in range(8)]   # one burst five days ago, nothing since
SH.joiners = lambda days=30: dict(days=30, joiners=240, joins_per_hour=hrs, median_s_to_first_pass=3 * day, median_s_to_first_pay=int(3.4 * day), reached_first_pass=0, reached_first_pay=0)
SH._last_join = lambda: now - 4 * day - 3600
maint.join_halt = lambda: dict(since_ts=now - 4 * day, as_of_ts=now)
maint.join_state_api = lambda: "open"
h = SH.live_panel()
check("halted: a Direct halted tag with the since date and an MCP open tag", "Direct halted" in h and "MCP open" in h and re.search(r'class="ststate"', h) is not None)
check("halted: Joined today becomes Last join with the age", "Last join" in h and "Joined today" not in h and "4.0d" in h)
check("halted: 240 joiners all older than the median wait and none passed is a real 0%", ">0%<" in h)
young = [[(now - 86400) // 3600 * 3600 + i * 3600, 30] for i in range(8)]
SH.joiners = lambda days=30: dict(days=30, joiners=240, joins_per_hour=young, median_s_to_first_pass=3 * day, median_s_to_first_pay=None, reached_first_pass=0, reached_first_pay=0)
y = SH.live_panel()
check("joiners younger than the median wait never read 0%: n/a", ">n/a<" in y and ">0%<" not in y)
SH.joiners = lambda days=30: dict(days=30, joiners=240, joins_per_hour=hrs, median_s_to_first_pass=3 * day, median_s_to_first_pay=int(3.4 * day), reached_first_pass=0, reached_first_pay=0)
check("halted: Median to pay uses days (3.4d), not hours", "3.4d" in h and "81." not in h)
check("halted: the sparkline is drawn from a zero filled daily series", 'class="spk"' in h)
hrs2 = [[(now - 6 * 86400 + i * 3600) // 3600 * 3600, 30] for i in range(24)] + [[now // 3600 * 3600, 5]]
SH.joiners = lambda days=30: dict(days=30, joiners=725, joins_per_hour=hrs2, median_s_to_first_pass=86400, median_s_to_first_pay=90000, reached_first_pass=500, reached_first_pay=300)
SH._last_join = lambda: now - 60
maint.join_halt = lambda: None
h = SH.live_panel()
check("open: no state tags, Joined today shown, Pass rate a real percent over eligible joiners", "ststate" not in h and "Joined today" in h and "Last join" not in h and re.search(r">\d+%<", h) is not None)
maint.join_halt = lambda: None; maint.join_state_api = lambda: "paused"
check("paused: a Paused tag", ">Paused<" in SH.live_panel())
check("span: minutes, hours, days", SH._span_s(300) == "5m" and SH._span_s(7200) == "2h" and SH._span_s(3 * day) == "3.0d")
SH.joiners = lambda days=30: None
check("no joiners data: panel still renders with placeholders", "Pass rate" in SH.live_panel())
c = SH.check_body({})
check("Check tab with no address previews the four stages", c.count("stl-wait") == 4 and "First payout" in c and "stnext" in c)
check("Check stage times read in days past 48 hours", SH._ago(now - 358 * 3600, now) == "14.9d ago" and SH._ago(now - 3 * 3600, now) == "3h ago")

# ---- batch 1: Chain labels ----
check("Chain Backlog KPI says at close and the Pending tab stays the live count", 'KIT.kpi("Backlog at close"' in SRC("poascan/views.py") and 'KIT.kpi("Backlog",' not in SRC("poascan/views.py"))
for p in ("poascan/starthub.py", "static/start.css"):
    check(f"no em or en dash in {p}", not re.search("[\u2013\u2014]", SRC(p)))

print("all passed" if not fails else f"{len(fails)} FAILED"); sys.exit(1 if fails else 0)
