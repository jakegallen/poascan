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

# ---- batch 5: dead code removed ----
import ast as _ast
def _fns(path): return {n.name for n in _ast.parse(SRC(path)).body if isinstance(n, _ast.FunctionDef)}
check("governance.py: the pre-consolidation tab renderers are gone, the data helpers stay",
      not (_fns("poascan/governance.py") & {"overview", "at_risk", "payouts", "directory", "established", "charts", "forum", "proposals", "page_legacy", "standing_table", "estimate_card"})
      and {"scores", "standing_rows", "rules", "proposals_data", "api_proposals"} <= _fns("poascan/governance.py"))
check("agentapi, startv2 and start: the legacy and rollback pages are gone", "api_page_legacy" not in _fns("poascan/agentapi.py") and "page_legacy" not in _fns("poascan/startv2.py")
      and "page" not in _fns("poascan/start.py") and "POASCAN_STARTV2" not in SRC("poascan/startv2.py") and "ST.page(" not in SRC("poascan/server.py"))
check("views.py: the unused home and agents helpers are gone", not (_fns("poascan/views.py") & {"burnmeter_html", "home_answers", "health_card", "agents_overview", "operators_page", "forum_page", "community_page", "live_hero", "home_graders", "ai_cards", "at_risk_body"}))
check("style.css: a sample of the unused classes is gone and the shared rules stay", not any(c in SRC("static/style.css") for c in (".herogrid", ".bm-hd", ".okdot", ".findf", ".lbtabs", ".navsrc")) and ".stat" in SRC("static/style.css"))

# ---- 1.26.405: Trade link gone, Start reads last_join_at, seal cast label, warm list ----
import importlib
check("home: no Trade on POASwap link above the footer, the CSS for it is gone", "Trade on POASwap" not in SRC("poascan/views.py") and "mtrade" not in SRC("poascan/views.py") and "mtrade" not in SRC("static/style.css"))
check("footer separator CSS is present", ".fsep{" in SRC("static/style.css"))
SH = importlib.reload(SH)   # drop the stubs above: read the real _last_join and stage code
from poascan import agents as AGN
SH.joiners = lambda days=30: dict(days=30, joiners=1, joins_per_hour=[], last_join_at="2026-11-10T12:00:00Z")
check("Start Last join reads last_join_at from the joiners data", SH._last_join() == _cal.timegm((2026, 11, 10, 12, 0, 0)) if (_cal := __import__("calendar")) else False)
SH.joiners = lambda days=30: dict(days=30, joiners=1, joins_per_hour=[])
maint.last_join = lambda: 12345
check("Start Last join falls back to the maintenance value when the joiners data has none", SH._last_join() == 12345)
check("Check stage is labelled First seal cast, not First seal", ("first_seal_cast_ts", "First seal cast") in SH.STAGES and not any(t == "First seal" for _, t in SH.STAGES))
lc = dict(joined_ts=now - 9 * day, first_answer_ts=now - 8 * day, first_seal_cast_ts=None, first_seal_ts=None, first_payout_ts=now - 2 * day)
SH.lifecycle = lambda a: lc
SH.WV = None
c = SH.check_body({"address": ["poa1" + "A" * 40]})
check("a paid Agent with no seal cast is Complete: the seal cast is not waiting before payout", "Complete" in c and "Watching" not in c and "First seal cast" in c)
lc2 = dict(lc, first_payout_ts=None)
SH.lifecycle = lambda a: lc2
c2 = SH.check_body({"address": ["poa1" + "A" * 40]})
check("an unpaid Agent with no seal cast still watches the seal cast stage", "Watching" in c2 and "stl-now" in c2)
SH.lifecycle = lambda a: dict(lc, first_seal_cast_ts=None, first_seal_ts=now - 3 * day)
check("an older payload that carries first_seal_ts only still fills the stage", SH.check_body({"address": ["poa1" + "A" * 40]}).count("stl-done") >= 4)
check("warm list: Network details, Earned and the latest epoch pages", "/network?view=details" in HC.WARM and "/agents/top?tab=richlist" in HC.WARM
      and all(u in HC.WARM for u in ("/agents/community?tab=social", "/agents/community?tab=answers", "/agents/community?tab=topics", "/governance?tab=settleage", "/agents/top?tab=active", "/agents/top?tab=rising")))
HC.LATEST_EPOCH = lambda: 105
HC._refresh_extra()
check("warm list: the latest three closed epochs join, and the set follows a new close", HC.EXTRA == ["/epoch/105", "/epoch/104", "/epoch/103"] and ("/epoch/105", ()) in HC._warm_pairs())
HC.LATEST_EPOCH = lambda: 106
HC._refresh_extra()
check("warm list: E106 replaces E103", HC.EXTRA == ["/epoch/106", "/epoch/105", "/epoch/104"] and ("/epoch/103", ()) not in HC._warm_pairs())
HC.LATEST_EPOCH = lambda: None; HC._refresh_extra()
check("warm list: no closes means no epoch pages", HC.EXTRA == [])
HC.EXTRA[:] = []; HC.LATEST_EPOCH = None; HC._warm_set.clear(); HC._warm_url_by.clear()

# ---- 1.26.406: Home Epochs rows carry no answers/paid count and no trailing reply number ----
from poascan import views as V, topics as TOPX
_hot = {"id": 12, "title": "A thread", "replies": 55}
_o = V.home_open_row({"epoch": 9, "answers": 1428, "last_close": now - 100, "est_close": now + 100, "period": 200})
_c = V.home_epochs([{"epoch": 8, "close_ts": now - 9, "pool": 100, "minted": 20, "paid": 2458}], with_pending=False)
_t = V._thread_line(_hot)
check("home epochs: the open row has no answers count or label", 'class="ep"' not in _o and 'class="epl"' not in _o and "1,428" not in _o and ">answers<" not in _o)
check("home epochs: a closed row has no paid count or label", 'class="ep"' not in _c and 'class="epl"' not in _c and "2,458" not in _c and ">paid<" not in _c)
check("home epochs: the thread line keeps id and title, the reply count moves to the tooltip", "#12" in _t and "A thread" in _t and "<b" not in _t and "55 replies" in _t)
_css = SRC("static/style.css")
check("home epochs: the grid has no count columns and no dead .ep/.epl/.eth b rules", "92px 52px 32px" not in _css and ".er .ep{" not in _css and ".er .epl" not in _css and ".eth b{" not in _css)

# ---- 1.26.407: a feed reads Paused upstream only while every failing key is held by its own live halt ----
def _fl(ep, ok, err, fails, nxt, msg):
    db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,last_err,fails,next_at,err) VALUES(?,?,?,?,?,?)", (ep, ok, err, fails, nxt, msg))
def _sw():
    A._cache.clear(); return next(f for f in A.feeds()["feeds"] if f["label"] == "Swaps")
db.write("DELETE FROM fetch_log")
_fl("/api/swaps", now - 60, None, 0, 0, None)
_fl("/api/explorer/tx/:id (swaps)", now - 90000, now - 300, 12, now + 600, "HTTP 503 halted")
check("feeds: a key held by its own halt reads Paused upstream", _sw()["state"] == "Paused upstream")
_fl("/api/explorer/tx/:id (swaps)", now - 90000, now - 300, 12, now + 600, "TimeoutError: The read operation timed out")
_fl("/api/explorer/tx/:id", now - 900, now - 100, 2, now + 600, "HTTP 503 halted")
_s = _sw()
check("feeds: a timeout on the swap key is not relabeled by a sibling key's halt", _s["state"] != "Paused upstream" and not _s.get("paused_upstream"))
_fl("/api/explorer/tx/:id (swaps)", now - 5, now - 300, 0, 0, None)
check("feeds: the label clears once the key reads again", _sw()["state"] == "OK")
db.write("DELETE FROM fetch_log")

# ---- 1.26.407: protocol.check() names the engine and server hashes of the stored /api/release current, none hardcoded ----
from poascan import protocol as PRO
_rel = {"current": {"version": "v0.123-server-1446", "engine_sha256": "ed86480c" + "0" * 56, "server_sha256": "4f347b54" + "0" * 56, "params_sha256": "bc823648" + "0" * 56,
                    "client_sha256": "ed86480c" + "0" * 56, "web_client_sha256": "911b833b" + "0" * 56, "ts": now, "txid": "e8" * 32}, "history": []}
_ck = PRO.state(_rel)
check("protocol state: engine ed86480c and server 4f347b54 come from the stored release", _ck["engine_sha256"].startswith("ed86480c") and _ck["server_sha256"].startswith("4f347b54") and _ck["params_sha256"].startswith("bc823648"))
check("protocol state: params are not hardcoded to the Oct 25 seed", "4f347b54" not in SRC("poascan/protocol.py") and "ed86480c" not in SRC("poascan/protocol.py"))
# governance rules: the Proposals process card follows go.md
from poascan import governance as GOVX, govhub as GH
GH.GOV._COLLECT.rows = []
try: GOVX.rules(); _rr = GH.GOV._COLLECT.rows
finally: GH.GOV._COLLECT.rows = None
_pc = next((r for r in _rr if r[0] == "process"), None)
check("governance rules: a Proposals card with max(25, 1% of established), 8 epochs, every 4 closes, G0 ballot, straw poll", bool(_pc) and all(t in _pc[2] for t in ("max(25, 1% of established)", "8 epochs", "every 4 closes", "G0 ballot", "straw poll")))
check("governance rules: the new card has no em or en dash", bool(_pc) and not re.search("[\u2013\u2014]", _pc[2] + _pc[3]))

print("all passed" if not fails else f"{len(fails)} FAILED"); sys.exit(1 if fails else 0)
