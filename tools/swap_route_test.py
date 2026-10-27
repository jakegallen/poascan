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
check(f"timeout: state down, display down (never slow), label Down, writable false, feed Down ({r})", r["state"] == "down" and r["display"] == "down" and r["label"] == "Down" and r["writable"] is False and r["feed"] == "Down")
check("timeout: raw hosted_routes.swap_offer stays unknown (its enum)", st["hosted_routes"]["swap_offer"] == "unknown")
check("timeout: hosted_routes_display.swap_offer is down (1.26.191, was slow)", st["hosted_routes_display"]["swap_offer"] == "down")
check("timeout: meta.maintenance.swap_route is the resolver", st["swap_route"] == r)
check("timeout: Swap writes feed Down; header Partial with Swap writes", feed()["state"] == "Down" and "Swap writes" in A.feeds()["not_ok"])
sw = MK._writes(dict(message="Swaps are live."))
check("timeout: swaps/status swap_route, writes and swaps_writable agree", sw["swap_route"] == r and sw["swaps_writable"] is False and sw["writes"]["swap_offer"]["state"] == "down")
h, _ = SV.api("/api/health", {})
check("timeout: /api/health swap_route is the resolver", h["swap_route"] == r)
mcp = AG.TOOL_FN["get_swap_status"]({})
check("timeout: MCP get_swap_status carries swap_route", mcp.get("swap_route") == r)

# 5xx without the halt text: down, display down (not unknown, not open)
probe(g(502, b"bad gateway"))
r = HO.swap_route()
check(f"502: down, display down, http 502, feed Down ({r['display']})", r["state"] == "down" and r["display"] == "down" and r["http"] == 502 and r["feed"] == "Down" and M.route_display()["swap_offer"] == "down")

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

# 1.26.191: display, label, writable and feed follow state alone, for every read (timeout, 5xx, halt, 4xx open,
# 404 unknown kept, never read) x age (fresh, just inside and just past WRITE_STALE_S) x basis (write check, newer route check)
EXP = {"open": ("open", "Open", True, "OK"), "paused": ("paused", "Paused", False, "Degraded"), "down": ("down", "Down", False, "Down"),
       "unknown": ("unknown", "Unknown", None, None)}
READS = {"timeout": (boom, "down"), "502": (g(502, b"bad gateway"), "down"), "500": (g(500, b"oops"), "down"), "halt": (g(503, HALT), "paused"),
         "401": (g(401), "open"), "400": (g(400), "open")}
def consistent(tag, r, t):
    st = r["state"]; d, lab, w, f = EXP[st]
    if r["stale"]: f = "Down"
    ok = (r["display"] == d and r["label"] == lab and r["display"] == r["label"].lower() and r["writable"] is w and r["feed"] == f
          and r["display"] != "slow" and (r["display"] != "open" or (st == "open" and not r["stale"])))
    hd = M.route_display()["swap_offer"]; sw = MK._writes(dict(message="Swaps are live."))
    ok = ok and hd in (d, "responding" if d == "open" else d) and sw["swap_route"]["display"] == d and sw["swaps_writable"] is w
    import importlib; SA = importlib.import_module("poascan.swap.api")
    with SA._rc_lock: SA._rc.clear()   # the swaps/status copy is cached CACHE_TTL s
    ok = ok and HO.writes(t)[1] is w and AG.TOOL_FN["get_swap_status"]({})["swap_route"]["display"] == d
    return ok
bad = []
db.put_blob(HO.WRITE_BLOB, {}); hb = db.get_blob(HO.BLOB)[0] or {}; hb.setdefault("routes", {}).pop("swap_offer", None); db.put_blob(HO.BLOB, hb)
A._cache.clear(); r = HO.swap_route()
if not consistent("never read", r, time.time()): bad.append(("never read", r))
for name, (get, want) in READS.items():
    for age, stale in ((0, False), (HO.WRITE_STALE_S - 30, False), (HO.WRITE_STALE_S + 30, True)):
        for basis in ("write_check", "route_check"):
            db.put_blob(HO.WRITE_BLOB, {}); now = int(time.time()); t0 = now - age
            hb = db.get_blob(HO.BLOB)[0] or {}; hb.setdefault("routes", {}).pop("swap_offer", None); db.put_blob(HO.BLOB, hb)
            probe(get, t=t0)
            if basis == "route_check":   # the maintenance route check read the same answer a moment later
                w = db.get_blob(HO.WRITE_BLOB)[0]; hb = db.get_blob(HO.BLOB)[0]
                hb["routes"]["swap_offer"] = dict(hb["routes"]["swap_offer"], checked=t0 + 1)
                if w["http"] is None: hb["routes"]["swap_offer"]["slow_since"] = t0 + 1
                db.put_blob(HO.BLOB, hb)
            r = HO.swap_route(now)
            tag = f"{name} age {age}s {basis}"
            exp_state = "unknown" if stale else want
            if not (r["state"] == exp_state and r["probe_state"] == want and r["stale"] is stale and r["basis"] == basis and consistent(tag, r, now)):
                bad.append((tag, r))
    # an unclear answer (404) after this read keeps the clear state
    probe(g(404, b"nf")); r = HO.swap_route()
    if not (r["probe_state"] == want and consistent(name + " then 404", r, time.time())): bad.append((name + " then 404", r))
check(f"every state x read x age x basis: display == label.lower() == state word, writable and feed from state ({len(bad)} bad: {bad[:2]})", not bad)
check("no display value outside open, paused, down, unknown", set(HO.SWAP_DISPLAY.values()) == {"open", "paused", "down", "unknown"} and set(HO.SWAP_DISPLAY) == set(HO.SWAP_LABEL))
check("label is display capitalised for every state", all(HO.SWAP_LABEL[k] == HO.SWAP_DISPLAY[k].capitalize() for k in HO.SWAP_DISPLAY))
check(f"stale after the longest cadence gap plus grace ({HO.WRITE_STALE_S}s = WRITE_SLOW {HO.WRITE_SLOW} + jitter {HO.WRITE_JITTER} + grace {HO.WRITE_GRACE})",
      HO.WRITE_STALE_S == HO.WRITE_SLOW + HO.WRITE_JITTER + HO.WRITE_GRACE and HO.WRITE_SLOW + HO.WRITE_JITTER + 60 < HO.WRITE_STALE_S < 2 * HO.WRITE_SLOW)
# the live case of Oct 27: Down since 14:22Z, read at 15:43:58Z, served at 16:15Z (31 min): inside the slow cadence, not stale
probe(boom, t=int(time.time()) - 1870); r = HO.swap_route()
check(f"down read 31 min old (inside WRITE_SLOW + jitter + tick): stale false, display down ({r['display']})", r["stale"] is False and r["display"] == "down")
probe(boom, t=int(time.time()) - 40 * 60); r = HO.swap_route()
check(f"down read 40 min old: stale true, state unknown, display unknown, feed Down ({r})", r["stale"] is True and r["state"] == "unknown" and r["display"] == "unknown" and r["feed"] == "Down")
src_h = open(os.path.join(ROOT, "poascan", "hosted.py")).read()
check("swap_route display has no slow path (display from SWAP_DISPLAY[state] only)", "disp = SWAP_DISPLAY[st]" in src_h and '"slow" if s["http"]' not in src_h)
check("/upgrade and app.js tag a down route Down", '"down": ("warn", "Down")' in open(os.path.join(ROOT, "poascan", "views2.py")).read() and 'v=="down"?"Down"' in open(os.path.join(ROOT, "static", "app.js")).read())

# every surface reads the resolver: no other code maps the write state to a display or feed word
src = {f: open(os.path.join(ROOT, "poascan", f)).read() for f in ("analytics.py", "maint.py", "views2.py", "ui.py")}
check("analytics feeds() and maint route_display() call swap_route/swap_display", "HO.swap_route(" in src["analytics.py"] and "R.swap_display(" in src["maint.py"])
check("OpenAPI documents swap_route", "swap_route" in str(AG.openapi()))
for f in ("hosted.py", "maint.py", "analytics.py", "swap/market.py", "agentapi.py"):
    t = open(os.path.join(ROOT, "poascan", f), encoding="utf-8").read()
    check(f"no em or en dash added in {f}", "\u2014" not in t and "\u2013" not in t)
print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
