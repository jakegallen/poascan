"""Route halts from POAScan's existing probes (routewatch.py): hysteresis (one bad or one good read never flips a route),
since and as-of times, every source (fetch_log lookups, the private prober, the swap write check, the route check), and
every surface: /api/v1/health route_halts, /api/v1/routes, MCP get_route_status, meta.maintenance.route_halts, the header
status note (reader's time, UTC without script), Network > Health Routes (Stale tag) and /upgrade, whose maintenance block
never says Upgrade complete while a route is halted. Temp database, no network. Usage: python3 tools/routewatch_test.py"""
import os, re, sys, tempfile, time, json, inspect
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "r.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

import fixture; fixture.seed()
from poascan import db, routewatch as RW, pulse as P, hosted as HO, maint as M, analytics as A, server as SV, agentapi as AG, ui as U, views2 as V2, og as OG
NOW = int(time.time())
def rec(rid): return next(r for r in RW.state()["routes"] if r["id"] == rid)
def fresh(): A._cache.clear(); M.grading_memo_clear()
def fl(ep, lo, le, err, fails): db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,last_err,err,fails,next_at) VALUES(?,?,?,?,?,0)", (ep, lo, le, err, fails))

# ---- hysteresis on one record
r = dict(state="unknown")
r = RW.step(r, 100, "ok", "t"); check("first good read: open", r["state"] == "open")
r = RW.step(r, 200, "halt", "t"); check("one halted read does not flip it", r["state"] == "open")
r = RW.step(r, 300, "halt", "t"); check("two halted reads in a row: halted since the first", r["state"] == "halted" and r["since"] == 200)
r = RW.step(r, 400, "ok", "t"); check("one good read does not clear it", r["state"] == "halted" and r["since"] == 200)
r = RW.step(r, 500, "fail", "t"); check("a bad read after it keeps the same run and since", r["state"] == "halted" and r["since"] == 200)
r = RW.step(r, 600, "ok", "t"); r = RW.step(r, 700, "ok", "t")
check("two good reads in a row clear it; the halt is kept in ended", r["state"] == "open" and r["since"] == 700 and r["ended"][0] == dict(state="halted", since=200, until=700))
r = RW.step(r, 800, "fail", "t"); r = RW.step(r, 900, "fail", "t"); check("two failures without the halt text: down", r["state"] == "down" and r["since"] == 800)
r = RW.step(r, 950, "halt", "t"); check("the halt text later in the same run: halted, same since", r["state"] == "halted" and r["since"] == 800)
r2 = RW.step(RW.step(dict(state="open"), 100, "halt", "t"), 150, "ok", "t"); r2 = RW.step(r2, 200, "halt", "t")
check("bad, good, bad: never two in a row, stays open", r2["state"] == "open")

# ---- fetch_log: the tx lookup halt as it stood live (three keys, 503 halted after their last good read)
fl("/api/explorer/tx/:id", NOW - 1800, NOW - 1790, "HTTP 503 halted", 1)
RW.job(NOW); check("one halted lookup read: tx lookup not halted yet", rec("tx_lookup")["state"] == "open")   # its last good read came first
fl("/api/explorer/tx/:id (on demand)", NOW - 2000, NOW - 1480, "HTTP 503 halted", 1)
RW.job(NOW + 60); t = rec("tx_lookup")
check(f"a second halted read (another key): halted since the first ({t['since']})", t["state"] == "halted" and t["since_ts"] == NOW - 1790 and t["as_of_ts"] == NOW - 1480)
fl("/api/explorer/address/:addr", NOW - 100, NOW - 50, "HTTP 401", 1); fl("/api/assignments/:addr", NOW - 300, NOW - 200, "HTTP 404", 3)
RW.job(NOW + 120); check("401 and 404 are not route reads", rec("address_lookup")["state"] == "open" and rec("assignments")["state"] == "open")
fl("/api/explorer/address/:addr", NOW - 100, NOW - 40, "TimeoutError: The read operation timed out", 1); RW.job(NOW + 130)
fl("/api/explorer/address/:addr", NOW - 100, NOW - 30, "TimeoutError: The read operation timed out", 2); RW.job(NOW + 140)
check("two timeouts in a row: address lookup down", rec("address_lookup")["state"] == "down" and rec("address_lookup")["since_ts"] == NOW - 40)
fl("/api/explorer/address/:addr", NOW - 20, NOW - 30, "TimeoutError", 0); RW.job(NOW + 150)
check("one good read after: still down", rec("address_lookup")["state"] == "down")
fl("/api/explorer/address/:addr", NOW - 10, NOW - 30, "TimeoutError", 0); RW.job(NOW + 160)
check("second good read: open again", rec("address_lookup")["state"] == "open")

# ---- the private prober: per route answers of each run
FIX = json.load(open(os.path.join(ROOT, "tools", "pulse_fixture.json")))
k = P.route_kinds(FIX)
check(f"prober: halted hosted endpoints read halt for hosted mining and assignments ({k})", k.get("hosted_mining") == "halt" and k.get("assignments") == "halt")
db.put_blob(P.BLOB, dict(groups={}, seen=[], routes={"hosted_mining": "halt"}, ok=True, ts=NOW - 600)); RW.job(NOW + 200)
check("one prober run halted: hosted mining not halted yet", rec("hosted_mining")["state"] != "halted")
RW.job(NOW + 210); check("the same run read twice counts once", rec("hosted_mining")["state"] != "halted")
db.put_blob(P.BLOB, dict(groups={}, seen=[], routes={"hosted_mining": "halt"}, ok=True, ts=NOW - 300)); RW.job(NOW + 300)
check("second run halted: hosted mining halted since the first run", rec("hosted_mining")["state"] == "halted" and rec("hosted_mining")["since_ts"] == NOW - 600)

# ---- swap write check: Down after two failing reads
def boom(): raise TimeoutError("timed out")
HO.write_job(now=NOW - 900, get=boom, force=True); RW.job(NOW + 310)
check("one swap write timeout: not down yet", rec("swap_writes")["state"] != "down")
HO.write_job(now=NOW - 280, get=boom, force=True); RW.job(NOW + 320)
check("two in a row: swap writes down since the first", rec("swap_writes")["state"] == "down" and rec("swap_writes")["since_ts"] == NOW - 900)

# ---- the maintenance route check (grading)
hb = db.get_blob(HO.BLOB)[0] or {}; rr = dict(hb.get("routes") or {})
for i, tt in enumerate((NOW - 2000, NOW - 1000)):
    rr["grading"] = dict(state="paused", since=NOW - 2000, checked=tt, tried=tt, code=503, streak=i + 1); db.put_blob(HO.BLOB, dict(hb, routes=rr)); RW.job(NOW + 330 + i)
check("two halted route check reads: grading halted", rec("grading")["state"] == "halted")

# ---- API and MCP
st = RW.state()
check(f"halted list ({st['halted']})", set(st["halted"]) == {"tx_lookup", "hosted_mining", "swap_writes", "grading"})
h, _ = SV.api("/api/health", {}); rt, _ = SV.api("/api/routes", {})
check("/api/v1/health route_halts and /api/v1/routes", h["route_halts"]["halted"] == st["halted"] and rt["halted"] == st["halted"] and "swap_route" in rt)
check("every route has id, label, state, since, as_of, stale", all({"id", "label", "state", "since", "as_of", "stale", "sources"} <= set(x) for x in rt["routes"]))
check("since and as_of are ISO UTC", re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", rec("tx_lookup")["since"] or "") is not None)
m = AG.TOOL_FN["get_route_status"]({}); tl = {t["name"] for t in AG.tools_list()}
check("MCP get_route_status answers like the API", m["halted"] == st["halted"] and "get_route_status" in tl)
check("OpenAPI and llms.txt", "/api/routes" in json.dumps(AG.openapi()) and "get_route_status" in AG.llms_txt() and "/routes" in AG.llms_txt())

# ---- maintenance block after the completion notice: never 'Upgrade complete' while routes are halted
db.put_blob(M.COMPLETE_BLOB, dict(at=NOW - 86400, notice_id="2026-10-23-grading-resumed", txid="a" * 64, seen_at=NOW)); fresh()
s = M.state()
check(f"headline: routes halted, not Upgrade complete ({s['headline']!r})", "Upgrade complete" not in s["headline"] + s["headline_short"] and "Tx lookup" in s["headline"] and s["headline_short"] == "Routes halted.")
check("meta.maintenance.route_halts lists them", {x["id"] for x in s["route_halts"]["halted"]} == set(st["halted"]))
check("paused lists hosted mining and grading per the probes; working does not", "hosted_mining" in s["paused"] and "grading" in s["paused"] and "hosted_mining" not in s["working"])
up = V2.upgrade_body()
check("/upgrade: Routes halted, never Upgrade complete", '<h1 class="uph-t" id="uph-t">Routes halted</h1>' in up and "Upgrade complete" not in up)
check("/upgrade: Halted group with each route and its since time (reader's zone, UTC without script)", 'data-grp="halted"' in up and "Tx lookup halted since " in up and re.search(r'<time class="t lt" datetime="[^"]+Z" data-ts="\d+" data-f="dt">[A-Z][a-z]{2} \d+, \d\d:\d\d UTC</time>', up))
check("/upgrade: hosted mining not in Working while halted", "<span>Hosted mining</span>" not in up.split('data-grp="working"')[1].split("</ul>")[0])
check("og: Routes halted", OG._upgrade()[1] == "Routes halted" and "Upgrade complete" not in M.og_desc())

# ---- header status note
p = U.status_pill(dict(state="live", label="Live", why="Live", fetched_at=NOW))
check("header: Live turns Partial", p["state"] == "partial" and p["label"] == "Partial")
check("header: one line per halted route with its start time", any(x.startswith("Tx lookup halted since ") for x in p["reasons"]) and any(x.startswith("Swap writes down since ") for x in p["reasons"]))
check("header: the time is in the reader's zone with HH:MMZ without script, plus a probes as-of line",
      re.search(r'Tx lookup halted since <time data-upts="\d+" datetime="[^"]+Z">\d\d:\d\dZ</time>\.', p["pop"]) is not None and "Probes as of <time data-upts=" in p["pop"])

# ---- Health: Routes card, Stale tag on an old read
db.put_blob(RW.BLOB, dict(db.get_blob(RW.BLOB)[0], routes=dict(db.get_blob(RW.BLOB)[0]["routes"], path_actions=dict(state="open", since=NOW - 9 * 3600, as_of=NOW - 9 * 3600))))
hh = V2.status_body()
check("Health: Routes card with Halted tags and since times", 'aria-label="Routes"' in hh and '<li data-route="tx_lookup" data-st="halted">' in hh and "since <time" in hh)
check("Health: a route last read 9 h ago has a Stale tag", re.search(r'data-route="path_actions".{0,400}?>Stale</summary>', hh, re.S) is not None)
check("Health: count of halted routes in the card head", 'data-halted="4"' in hh)

# ---- cleared: two good reads on every source, Upgrade complete again
for i in (1, 2):
    tt = NOW + 1000 * i
    for ep in ("/api/explorer/tx/:id", "/api/explorer/tx/:id (on demand)"): fl(ep, tt, NOW - 1480, "HTTP 503 halted", 0)
    db.put_blob(P.BLOB, dict(groups={}, seen=[], routes={"hosted_mining": "ok"}, ok=True, ts=tt))
    HO.write_job(now=tt, get=lambda: (401, b'{"error":"missing key"}'), force=True)
    rr["grading"] = dict(state="open", since=tt, checked=tt, tried=tt, code=401, streak=i); db.put_blob(HO.BLOB, dict(db.get_blob(HO.BLOB)[0], routes=rr))
    RW.job(tt + 1)
fresh(); s = M.state()
check(f"after two good reads everywhere: nothing halted ({RW.state()['halted']})", RW.state()["halted"] == [])
check("headline back to the completion line", "Routes halted" not in s["headline_short"] and "Routes halted" not in V2.upgrade_body())
check("past halts kept in ended", rec("tx_lookup")["ended"] and rec("tx_lookup")["ended"][0]["state"] == "halted")

# ---- no new request to minepoa.com; copy rules
src = inspect.getsource(RW)
check("routewatch makes no request (no urllib, no fetch)", "urllib" not in src and "fetch(" not in src and "_get(" not in src)
for f in ("routewatch.py", "pulse.py", "maint.py", "views2.py", "ui.py", "og.py", "agentapi.py", "server.py"):
    t = open(os.path.join(ROOT, "poascan", f), encoding="utf-8").read()
    check(f"no em or en dash in {f}", "\u2014" not in t and "\u2013" not in t)
check("no 'Accounts' in the new copy", "Accounts" not in src and "Accounts" not in hh)
print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
