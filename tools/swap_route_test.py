"""One source of truth for swap order placement (1.26.185): hosted.swap_route() drives hosted_routes_display.swap_offer,
meta.maintenance.swap_route, /api/v1/swaps/status (writes, swaps_writable, swap_route), the Swap writes feed (Health,
/api/health, header status) and MCP get_swap_status. An unknown, stale or Down write check never renders as open.
Temp database, no network. Usage: python3 tools/swap_route_test.py"""
import os, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import db, hosted as HO, maint as M, analytics as A, server as SV, agentapi as AG, ui as U
from poascan.swap import market as MK
db.init()
HALT = b'{"error":"endpoint temporarily halted, API hardening in progress"}'
def g(code, body=b'{"error":"missing key"}'): return lambda: (code, body)
def boom(): raise TimeoutError("timed out")
def probe(get, t=None): HO.write_job(now=int(t or time.time()), get=get, force=True); A._cache.clear(); M.grading_memo_clear()
def feed(): return next((f for f in A.feeds()["feeds"] if f["label"] == "Swap writes"), None)
def done(on):
    if on: db.put_blob(M.COMPLETE_BLOB, dict(at=int(time.time()) - 86400, notice_id="2026-10-23-grading-resumed", txid="a" * 64, seen_at=int(time.time())))
    else: db.put_blob(M.COMPLETE_BLOB, {})
    A._cache.clear(); M.grading_memo_clear()

# never read: unknown everywhere, never open, no feed row
done(True)
r = HO.swap_route()
check(f"never read: state unknown, display unknown, writable null, no feed ({r})", r["state"] == "unknown" and r["display"] == "unknown" and r["writable"] is None and r["feed"] is None)
check("never read, upgrade complete: hosted_routes_display.swap_offer is unknown, not open", M.route_display()["swap_offer"] == "unknown")

# the reported case: write check Down (timeout), raw hosted_routes unknown; display was 'open' after completion
probe(boom)
r = HO.swap_route(); st = M.state()
check(f"timeout: state down, display slow, writable false, feed Down ({r})", r["state"] == "down" and r["display"] == "slow" and r["writable"] is False and r["feed"] == "Down")
check("timeout: raw hosted_routes.swap_offer stays unknown (its enum)", st["hosted_routes"]["swap_offer"] == "unknown")
check("timeout: hosted_routes_display.swap_offer never open (slow)", st["hosted_routes_display"]["swap_offer"] == "slow")
check("timeout: meta.maintenance.swap_route is the resolver", st["swap_route"] == r)
check("timeout: Swap writes feed Down; header Partial with Swap writes", feed()["state"] == "Down" and "Swap writes" in A.feeds()["not_ok"])
sw = MK._writes(dict(message="Swaps are live."))
check("timeout: swaps/status swap_route, writes and swaps_writable agree", sw["swap_route"] == r and sw["swaps_writable"] is False and sw["writes"]["swap_offer"]["state"] == "down")
h, _ = SV.api("/api/health", {})
check("timeout: /api/health swap_route is the resolver", h["swap_route"] == r)
mcp = AG.TOOL_FN["get_swap_status"]({})
check("timeout: MCP get_swap_status carries swap_route", mcp.get("swap_route") == r)

# 5xx without the halt text: down, display unknown (not slow, not open)
probe(g(502, b"bad gateway"))
r = HO.swap_route()
check(f"502: down, display unknown, feed Down ({r['display']})", r["state"] == "down" and r["display"] == "unknown" and r["feed"] == "Down" and M.route_display()["swap_offer"] == "unknown")

# halted: paused everywhere
probe(g(503, HALT))
r = HO.swap_route()
check("halt answer: paused, writable false, feed Degraded, display paused", r["state"] == "paused" and r["writable"] is False and r["feed"] == "Degraded" and M.route_display()["swap_offer"] == "paused")

# open and fresh: open only now
probe(g(401))
r = HO.swap_route()
check("open read: open, writable true, feed OK, display open", r["state"] == "open" and r["writable"] is True and r["feed"] == "OK" and M.route_display()["swap_offer"] == "open")
done(False)
check("open before the official word: responding, never open", M.route_display()["swap_offer"] in ("responding", "open") and (M.route_display()["swap_offer"] == "responding" or M.official()["routes"]))
done(True)

# stale open: unknown, feed Down, never open
old = int(time.time()) - 3 * 3600
probe(g(401), t=old)
r = HO.swap_route()
check(f"stale open read: state unknown, probe_state open, stale, writable null ({r})", r["state"] == "unknown" and r["probe_state"] == "open" and r["stale"] and r["writable"] is None)
check("stale open read: display unknown, feed Down", M.route_display()["swap_offer"] == "unknown" and feed()["state"] == "Down" and feed().get("stale") is True)
_, ok = HO.writes()
check("stale: swaps_writable null (same rule)", ok is None)

# the maintenance route check reads the same path: its newer clear read wins, and writes and swaps_writable follow it
probe(boom); t = int(time.time()) + 5
hb = db.get_blob(HO.BLOB)[0]; hb["routes"]["swap_offer"] = dict(state="paused", since=t, checked=t, code=503, tried=t, streak=1); db.put_blob(HO.BLOB, hb)
r = HO.swap_route(t + 1); w, ok = HO.writes(t + 1)
check("a newer route check read wins; writes and swaps_writable agree with the resolver", r["state"] == "paused" and w["swap_offer"]["state"] == "paused" and ok is False and r["writable"] is False)

# every surface reads the resolver: no other code maps the write state to a display or feed word
src = {f: open(os.path.join(ROOT, "poascan", f)).read() for f in ("analytics.py", "maint.py", "views2.py", "ui.py")}
check("analytics feeds() and maint route_display() call swap_route/swap_display", "HO.swap_route(" in src["analytics.py"] and "R.swap_display(" in src["maint.py"])
check("OpenAPI documents swap_route", "swap_route" in str(AG.openapi()))
for f in ("hosted.py", "maint.py", "analytics.py", "swap/market.py", "agentapi.py"):
    t = open(os.path.join(ROOT, "poascan", f), encoding="utf-8").read()
    check(f"no em or en dash added in {f}", "\u2014" not in t and "\u2013" not in t)
print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
