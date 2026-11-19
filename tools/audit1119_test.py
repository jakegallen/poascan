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
# ---- batch 4: medium cleanup ----
from poascan import ui as UI, views as V, bench as BN, htmlcache as HC, nethub as NH
card = UI.card("t", "b", '<a class="more" href="/x.csv" download>CSV \u2192</a><a class="more" href="/x">API \u2192</a><a class="more" href="/y">Source JSON</a>')
check("card(): API and CSV header links are not drawn, other header links stay", "CSV" not in card and "API" not in card and "Source JSON" in card)
check("card(): the For agents card keeps its API link", "API" in UI.card("For agents", "b", '<a class="more" href="/api">API \u2192</a>', id="for-agents"))
check("Home and Chain: the open epoch row says Submitted, so Answers is the lane label only", "Submitted" in BN.bench_html.__code__.co_consts.__repr__() or "Submitted" in SRC("poascan/bench.py"))
check("Home Epochs chart reads Per close, not Answers", "Per close</span>" in SRC("poascan/views.py"))
rows = [dict(epoch=e, close_ts=now - (5 - e) * 21600, paid=10, minted=1.0, burned=1.0, burn_pct=14.0, median=1.0, pause=None, segment=2, g=e) for e in range(3)]
t = V.epochs_table(rows, qs={}, base="/chain")
check("epochs table: no status column when every close is Finalized", "FINALIZED" not in t and ">Status<" not in t and ">Minted<" in t)
t = V.epochs_table(rows, qs={}, base="/chain", pend=[dict(epoch=3, close_ts=now)])
check("epochs table: the status column returns while a record is pending", "RECORD PENDING" in t and ">Status<" in t)
check("Network Charts opens on Answers, not the flat Joins line", NH.DEFAULT_METRIC == "answers")
UI.REQ.path = "/governance"; UI.REQ.qs = {"tab": ["at-risk"]}
check("canonical: an old Governance tab URL names the tab it renders", UI.canonical().endswith("/governance"))
UI.REQ.qs = {"tab": ["settleage"]}; check("canonical: settleage is Closes", UI.canonical().endswith("/governance?tab=closes"))
UI.REQ.qs = {"tab": ["nonsense"]}; check("canonical: an unknown tab is the bare page", UI.canonical().endswith("/governance"))
UI.REQ.qs = {"tab": ["payouts"]}; check("canonical: a real tab is its own", UI.canonical().endswith("/governance?tab=payouts"))
from poascan import server as S
dead = ("at-risk", "established", "queue", "directory", "forum", "protocol", "settleage", "charts")
check("sitemap: the eight Governance aliases are gone, Closes is in", not any(f"/governance?tab={d}" == r for d in dead for r in S.STATIC_ROUTES) and "/governance?tab=closes" in S.STATIC_ROUTES)
check("warm list: the slow first renders are warmed and the two Standing aliases are not", all(u in HC.WARM for u in ("/agents/community?tab=social", "/agents/community?tab=answers", "/agents/community?tab=topics", "/agents/top?tab=active", "/agents/top?tab=rising", "/network?tab=anchors")) and "/governance?tab=at-risk" not in HC.WARM)

# ---- batch 3: /help and /wallet move into Start ----
a = "poa1" + "A" * 40
check("/help 301s to Start Earn", S.moved("/help", {}) == "/start?tab=earn")
check("/help?address= keeps a valid address on the Check tab", S.moved("/help", {"address": [a]}) == f"/start?tab=check&address={a}")
check("/wallet 301s to Start Check and keeps a valid address", S.moved("/wallet", {}) == "/start?tab=check" and S.moved("/wallet", {"address": [a]}) == f"/start?tab=check&address={a}")
check("a key-shaped or junk address is dropped from the redirect, never echoed", S.moved("/wallet", {"address": ["pk_" + "Q" * 30]}) == "/start?tab=check" and S.moved("/help", {"address": ["<script>"]}) == "/start?tab=earn")
check("sitemap: /help and /wallet are out", "/help" not in S.STATIC_ROUTES and "/wallet" not in S.STATIC_ROUTES)
check("the Earn and Check tabs are the Start tabs", [t[0] for t in SH.TABS] == ["join", "check", "earn"])
check("/upgrade carries no Ask agent prompt box; the one Ask agent is in Start", "Ask agent" not in SRC("poascan/views2.py") and "pbox" not in SRC("poascan/views2.py") and "PR.ask(" in SRC("poascan/starthub.py") and "PR.ask(" not in SRC("poascan/views.py"))
check("Agent pages link the earn check to the Check tab", '/help?address=' not in SRC("poascan/views.py").replace('<code>/help?address=&lt;poa1 address&gt;</code>', ''))

for p in ("poascan/starthub.py", "static/start.css"):
    check(f"no em or en dash in {p}", not re.search("[\u2013\u2014]", SRC(p)))

# ---- batch 2: the epoch page on the kit ----
from poascan import epochhub as EH
EHS = SRC("poascan/epochhub.py")
check("epoch hub: Payouts capped at 20 rows with offset paging", EH.PAGE == 20 and "allr[off:off + PAGE]" in EHS)
pg = EH._pager(45, 20, lambda o: f"/x?offset={o}")
check("epoch pager: Prev and Next with the range", "offset=0" in pg and "offset=40" in pg and "21 to 40 of 45" in pg and EH._pager(20, 0, lambda o: "") == "")
check("epoch hub: six KPI cards, Payouts, Record and Forum tabs, no header CSV link", EHS.count("KIT.kpi(") == 6 and "KIT.tabmod(" in EHS and "rewards.csv" not in EHS.replace("the CSV route stays at /api/v1/epoch/N/rewards.csv", ""))
check("epoch hub: no em or en dash", not re.search("[\u2013\u2014]", EHS) and not re.search("[\u2013\u2014]", SRC("static/epoch.css")))
check("epoch page: views.epoch hands off to the hub", "EH.page(" in SRC("poascan/views.py") and "split_stats" not in SRC("poascan/views.py"))
check("epoch.css respects reduced motion", "prefers-reduced-motion" in SRC("static/epoch.css") or "animation" not in SRC("static/epoch.css"))

# ---- batch 6: the expiry horizon strip on Chain Pending and the Intake line on the Agent page ----
from poascan import intake as IK, horizon as HZ, views as V
IK.closes = lambda: [dict(close=40, waitlist_epochs=3, rows=[dict(address="poa1X", state="admitted"), dict(address="poa1Y", state="not_admitted")]),
                     dict(close=41, waitlist_epochs=3, rows=[dict(address="poa1Z", state="not_admitted"), dict(address="poa1W", state="admitted_unlisted")]),
                     dict(close=45, waitlist_epochs=3, rows=[])]
check("intake_of: the newest admitting close", IK.intake_of("poa1X") == dict(state="admitted", close=40) and IK.intake_of("poa1W") == dict(state="admitted", close=41))
check("intake_of: nothing once the waitlist lapsed or when no close names the Agent", IK.intake_of("poa1Y") is None and IK.intake_of("poa1Z") is None and IK.intake_of("poa1Q") is None)
IK.closes = lambda: [dict(close=40, waitlist_epochs=3, rows=[dict(address="poa1Z", state="not_admitted")]), dict(close=41, waitlist_epochs=3, rows=[])]
check("intake_of: a waitlisted Agent reads Held with its last close", IK.intake_of("poa1Z") == dict(state="held", close=40, keeps_until=43))
fact = lambda k, v, t="": f"<{k}|{v}|{t}>"
check("intake line: Admitted E40, Held to E43, empty when unknown", V.intake_fact("poa1Z", fact).startswith("<Intake|Held to E43|")
      and (setattr(IK, "closes", lambda: [dict(close=40, waitlist_epochs=0, rows=[dict(address="poa1X", state="admitted")])]) or V.intake_fact("poa1X", fact).startswith("<Intake|Admitted E40|"))
      and V.intake_fact("poa1none", fact) == "")
HZ.horizon = lambda: dict(ttl=16, rows=[dict(source="close", pending=500, closes_left=0), dict(source="close", pending=100, closes_left=5), dict(source="close", pending=50, closes_left=15),
                                        dict(source="open", pending=999, closes_left=16)])
hs = V.horizon_strip()
check("horizon strip: 16 bars, the next close gold with its count, the open cohort left out", hs.count('<i class="hzb') == 16 and 'hzb nx' in hs and ">500<" in hs and "999" not in hs and "Expiry" in hs)
check("horizon strip: tallest bar is full height, empty closes keep a stub", 'height:100%' in hs and 'height:4%' in hs)
HZ.horizon = lambda: dict(ttl=0, rows=[])
check("horizon strip: left out when the TTL is unknown", V.horizon_strip() == "")
check("horizon strip is drawn above the queue", V.pending_body.__code__.co_names.count("horizon_strip") == 1)

print("all passed" if not fails else f"{len(fails)} FAILED"); sys.exit(1 if fails else 0)
