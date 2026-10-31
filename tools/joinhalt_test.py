"""Joins paused (1.26.232): a 503 halt on minepoa's /api/join-pow. The indexer reads it at most every 5 min (keeping only kind
and bits), routewatch marks route "joining" Halted on one halt read, /start shows a terse paused state, join_shape carries it,
and prompt v2.9.2 tells the agent to stop and report. Temp database. Usage: python3 tools/joinhalt_test.py"""
import os, sys, tempfile, time, re
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "d.db"); os.environ.setdefault("POASCAN_INDEXER", "0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, indexer as I, routewatch as RW, maint as M, start as S, onboarding_prompt as OP
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
check("job listed, 5 min, keyed on /api/join-pow", ("join_pow", I.job_join_pow, 300, "/api/join-pow") in I.JOBS and I.EVERY.get("/api/join-pow") == 300)
check("path allowed", bool(I.ALLOWED.match("/api/join-pow")))
check("route joining watches the fetch key, one halt read", any(r[0] == "joining" and r[2].get("fetch") == ("/api/join-pow",) and r[2].get("halt_n") == 1 for r in RW.ROUTES))
check("no read yet: open, no banner", M.join_halt() is None and S.join_halt_html() == "" and S.join_state()["state"] == "open" and M.state()["join_state"] in ("open", "paused"))
# a good read keeps only kind and bits
real = I.fetch
I.fetch = lambda path, **k: {"kind": "pow", "challenge": "secret", "bits": 21, "expires_ts": 1}
I.job_join_pow(); b = db.get_blob("join_pow")[0]
check("good read keeps kind and bits, never the challenge", b.get("kind") == "pow" and b.get("bits") == 21 and "challenge" not in b)
# a halt: fetch_log row as indexer.fetch writes it
now = int(time.time())
db.write("INSERT OR REPLACE INTO fetch_log(endpoint, last_ok, last_err, err, fails) VALUES(?,?,?,?,?)", ("/api/join-pow", now - 600, now - 60, "HTTP 503 halted", 1))
RW.job(now)
r = next(x for x in RW.state(now)["routes"] if x["id"] == "joining")
check("one halt read: Halted", r["state"] == "halted" and "joining" in RW.state(now)["halted"])
h = M.join_halt()
check("join_halt gives since and as_of", h and h["since_ts"] == now - 60 and h["as_of_ts"] == now - 60)
# 1.26.247 (minepoa v0.71-mcpjoin): the direct HTTP GET /api/join-pow 503 is tracked but is NOT a blanket pause,
# because MCP joins (poa_join_pow then poa_register) stay open. The /start banner and API join_state do not read halted
# from this route alone; join_pow_route reports the route on its own.
_jpr = M.join_pow_route()
check("join_pow_route: halted true with since and as_of; note names MCP joins as unaffected",
      _jpr["halted"] is True and _jpr["since"] and _jpr["as_of"] and "poa_register" in _jpr["note"] and "GET /api/join-pow" in _jpr["note"])
check("the HTTP-route halt does not show the /start Joins paused banner (MCP joins open)",
      M.join_open() is True and S.join_halt_html() == "" and "data-joinhalt" not in S.page(lambda title, body, *a, **k: body))
st = M.state()
check("API join_state not halted from the HTTP-route 503; join_pow_route carries the route; join_open stays a bool",
      st["join_state"] in ("open", "paused") and st["join_state"] != "halted" and st["join_pow_route"]["halted"] is True and isinstance(st["join_open"], bool) and M.join_state() in ("open", "paused"))
# a real operator or tracker halt (join_open false) is what shows the paused state
_jo = M.join_open
try:
    M.join_open = lambda: False
    html = S.join_halt_html()
    check("operator halt (join_open false): the /start Joins paused banner shows with the public text",
          "Joins paused" in html and "data-joinhalt" in html and S.PAUSED == "New PoA signups are paused. Check back later. Existing balances and pending grades are safe."
          and S.paused() is True)
finally:
    M.join_open = _jo
js = S.join_shape()
check("join_shape: the route state and the 503 rule are still reported for the direct HTTP path", js["state"]["state"] == "halted" and js["halted"]["status"] == 503 and js["halted"]["say"] == "Joins are paused. Check back later.")
from poascan import agentapi as AA
check("schema keeps the open, paused, halted enum", '"enum": ["open", "paused", "halted"]' in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "agentapi.py")).read())
# a plain timeout is not a halt: two bad reads still needed
db.write("DELETE FROM blobs WHERE kind=?", (RW.BLOB,))
db.write("UPDATE fetch_log SET err=?, fails=1 WHERE endpoint=?", ("timed out", "/api/join-pow"))
RW.job(now)
check("one timeout is not paused", M.join_halt() is None)
# recovery: two good reads
db.write("DELETE FROM blobs WHERE kind=?", (RW.BLOB,))
db.write("UPDATE fetch_log SET err=?, fails=1 WHERE endpoint=?", ("HTTP 503 halted", "/api/join-pow")); RW.job(now)
db.write("UPDATE fetch_log SET last_ok=?, fails=0 WHERE endpoint=?", (now + 300, "/api/join-pow")); RW.job(now + 300)
db.write("UPDATE fetch_log SET last_ok=?, fails=0 WHERE endpoint=?", (now + 600, "/api/join-pow")); RW.job(now + 600)
check("two good reads: open again, banner gone, API join_state back", M.join_halt() is None and S.join_halt_html() == "" and M.state()["join_state"] in ("open", "paused"))
I.fetch = real
p = OP.POW
check("prompt v2.9.4", OP.VERSION == "v2.9.4")
check("POW: a 503 stops with the exact line, no mining or retry", 'On a 503, stop without mining or retrying and tell me: Joins are paused. Check back later.' in p)
check("POW still reads kind and bits from each challenge", "If kind is not pow" in p and "bits" in p)
full = S.prompt("NAME", "full")
check("full prompt carries it", "Joins are paused. Check back later." in full)
check("no em or en dash", not re.search("[\u2013\u2014]", p + html + str(js)))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
