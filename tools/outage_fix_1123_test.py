"""Outage fix (1.26.424):
1. Connection reserve for /healthz when GD.conns is completely full.
2. Bounded wait + stale fallback / 503 Retry-After on swap/api.py _cached, /api/summary, and /api/v1/summary.
3. Long analytics locks (_heavy exhausted or _inflight blocked) serve stale data at any age in fast mode or fail fast 503 on cold miss.
Run: python3 tools/outage_fix_1123_test.py (temp db, in-process loopback server, no network)."""
import importlib, json, os, re, sys, tempfile, threading, time, urllib.error, urllib.request

tmp = tempfile.mkdtemp()
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tmp, "outage1123.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_HTML_CACHE"] = "0"
os.environ["POASCAN_MAX_CONNS"] = "2"
os.environ["POASCAN_CONN_WAIT"] = "0.05"
os.environ["POASCAN_HEALTH_CONNS"] = "2"
os.environ["POASCAN_SWAP_WAIT_S"] = "0.25"
os.environ["POASCAN_SUMMARY_WAIT_S"] = "0.25"
os.environ["POASCAN_HEAVY_MAX"] = "2"
os.environ["POASCAN_SWAP_EVIDENCE"] = ""
os.environ["POA_BASE"] = "http://127.0.0.1:9"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import fixture
fixture.seed()

from poascan import db, guard as GD, analytics as A, live as L, agentapi as AG, segments as SG
SW = importlib.import_module("poascan.swap.api")
import poascan.server as SV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)

# Seed a valid status/networks/blob so meta & summary work cleanly
db.put_blob("status", {"network": "PoA prototype", "K": 5, "supply": "1000", "txs": 1, "final": 1, "agents_joined": 2, "epochs_closed": 1, "holders": 2, "as_of": "2026-11-23T16:00:00Z"})
db.put_blob("networks", {"chains": [{"chain_id": "poa-mainnet-1", "height": 100, "checkpoint_height": 99}]})
SV.HUB.snapshot()
AG.meta()

srv = SV.Server(("127.0.0.1", 0), SV.H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{port}"

def http_get(path, timeout=3.0):
    req = urllib.request.Request(BASE + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf-8", "replace")

# ---------------------------------------------------------------- 1. /healthz connection reserve
held_conns = []
while GD.conns.acquire(blocking=False):
    held_conns.append(1)
try:
    ok(len(held_conns) == 2, f"exhausted GD.conns ({len(held_conns)}/2)")
    t0 = time.time()
    st, hd, body = http_get("/healthz", timeout=2.0)
    dt = time.time() - t0
    ok(st == 200 and body.strip() == "ok" and dt < 1.0, f"/healthz answers 200 when GD.conns is full ({st}, {dt*1000:.0f}ms)")

    t0 = time.time()
    st2, hd2, body2 = http_get("/api/summary", timeout=2.0)
    dt2 = time.time() - t0
    ok(st2 == 503 and "server busy" in body2 and dt2 < 1.0, f"non-health route on reserve sheds fast with 503 ({st2}, {dt2*1000:.0f}ms)")

    st3, _, body3 = http_get("/healthz", timeout=2.0)
    ok(st3 == 200 and body3.strip() == "ok", f"/healthz still works after reserve shed ({st3})")
finally:
    for _ in held_conns:
        GD.conns.release()

# ---------------------------------------------------------------- 2. swap/api.py _cached stale fallback + cold fail fast
# Warm swap caches first
SW._cached("/api/swaps/status")
SW._cached("/api/swaps")
SW._cached("/api/price")

# Expire entries so next call wants a rebuild
with SW._rc_lock:
    for k in list(SW._rc):
        _, ver, val = SW._rc[k]
        SW._rc[k] = (0.0, ver, val)

gate = threading.Event()
entered = threading.Event()
orig_build = SW._build
def blocked_build(path):
    entered.set()
    gate.wait(5)
    return orig_build(path)

SW._build = blocked_build
try:
    refresher = threading.Thread(target=lambda: SW._cached("/api/swaps/status"), daemon=True)
    refresher.start()
    entered.wait(2)
    t0 = time.time()
    res = SW.api("/api/swaps/status", {})
    dt = time.time() - t0
    ok(isinstance(res[0], dict) and dt < 0.15, f"warm stale swap/api returns last cached value immediately while refresher works ({dt*1000:.0f}ms)")

    # Summary endpoints also succeed immediately using stale swaps
    t0 = time.time()
    st_s, _, _ = http_get("/api/summary", timeout=2.0)
    st_v1, _, _ = http_get("/api/v1/summary", timeout=2.0)
    dt_s = time.time() - t0
    ok(st_s == 200 and st_v1 == 200 and dt_s < 0.5, f"/api/summary and /api/v1/summary return 200 while swap refresher is blocked ({st_s}, {st_v1}, {dt_s*1000:.0f}ms)")
finally:
    gate.set()
    refresher.join(2)
    SW._build = orig_build

# Cold miss fail-fast on swap/api.py + HTTP 503 with Retry-After
SW._rc.clear(); SW._rc_build.clear()
with SV._SUMMARY_LOCK:
    SV._SUMMARY_LAST["swaps"] = None
    SV._SUMMARY_LAST["concentration"] = None

gate2 = threading.Event()
entered2 = threading.Event()
def blocked_cold_build(path):
    entered2.set()
    gate2.wait(5)
    return orig_build(path)

SW._build = blocked_cold_build
try:
    t_status = threading.Thread(target=lambda: SW._cached("/api/swaps/status"), daemon=True)
    t_status.start()
    entered2.wait(2)

    t0 = time.time()
    caught = False
    try:
        SW._cached("/api/swaps/status")
    except SW.Busy:
        caught = True
    dt = time.time() - t0
    ok(caught and 0.18 <= dt < 1.0, f"cold swap/api waiter fails fast with SW.Busy after ~BUILD_WAIT ({dt*1000:.0f}ms)")

    for ep in ("/api/summary", "/api/v1/summary"):
        t0 = time.time()
        st, hd, body = http_get(ep, timeout=2.0)
        dt = time.time() - t0
        ok(st == 503 and "retry-after" in hd and dt < 1.0, f"cold {ep} fails fast with 503 + Retry-After ({st}, ra={hd.get('retry-after')}, {dt*1000:.0f}ms)")

    # Also test direct /api/v1/swaps cold fail-fast
    entered_sw = threading.Event()
    def blocked_sw(path):
        if path == "/api/swaps": entered_sw.set()
        gate2.wait(5)
        return orig_build(path)
    SW._build = blocked_sw
    t_sw = threading.Thread(target=lambda: SW._cached("/api/swaps"), daemon=True)
    t_sw.start()
    entered_sw.wait(2)
    t0 = time.time()
    st, hd, body = http_get("/api/v1/swaps", timeout=2.0)
    dt = time.time() - t0
    ok(st == 503 and "retry-after" in hd and dt < 1.0, f"cold /api/v1/swaps fails fast with 503 + Retry-After ({st}, ra={hd.get('retry-after')}, {dt*1000:.0f}ms)")
finally:
    gate2.set()
    t_status.join(2)
    t_sw.join(2)
    SW._build = orig_build

# ---------------------------------------------------------------- 3. Long analytics locks don't block /api/summary or swap/api.py
# Populate analytics caches, then age them PAST STALE_MAX (1000s old)
A.concentration()
A.supply_split()
A.forum_names()
with A._lock:
    for k in list(A._cache):
        _, val = A._cache[k]
        A._cache[k] = (time.time() - A.STALE_MAX - 500, val)

# Exhaust all _heavy slots
held_heavy = []
while A._heavy.acquire(blocking=False):
    held_heavy.append(1)
try:
    ok(len(held_heavy) == 2, f"exhausted analytics._heavy ({len(held_heavy)}/2)")
    # Expire swap cache too so _build runs inside analytics.fast()
    with SW._rc_lock:
        for k in list(SW._rc):
            _, ver, val = SW._rc[k]
            SW._rc[k] = (0.0, ver, val)

    t0 = time.time()
    st1, _, b1 = http_get("/api/summary", timeout=2.0)
    st2, _, b2 = http_get("/api/v1/summary", timeout=2.0)
    dt = time.time() - t0
    ok(st1 == 200 and st2 == 200 and dt < 0.6, f"ancient stale analytics (>STALE_MAX) served immediately when _heavy is full ({st1}, {st2}, {dt*1000:.0f}ms)")
    d1 = json.loads(b1)
    ok(isinstance(d1.get("swaps"), dict) and isinstance(d1.get("concentration"), dict), "summary still includes swaps and concentration from stale analytics")

    # Cold analytics miss with _heavy held -> fast mode fails fast with 503 when _SUMMARY_LAST cleared
    A._cache.clear()
    with SV._SUMMARY_LOCK:
        SV._SUMMARY_LAST["swaps"] = None
        SV._SUMMARY_LAST["concentration"] = None
    t0 = time.time()
    st3, hd3, _ = http_get("/api/summary", timeout=2.0)
    dt3 = time.time() - t0
    ok(st3 == 503 and "retry-after" in hd3 and dt3 < 1.2, f"cold analytics miss with _heavy full fails fast 503 + Retry-After ({st3}, {dt3*1000:.0f}ms)")
finally:
    for _ in held_heavy:
        A._heavy.release()

# Also verify _inflight blocked on concentration in fast mode serves stale immediately
A.concentration()
ck = ("concentration", SG.selected())
with A._lock:
    _, val = A._cache[ck]
    A._cache[ck] = (time.time() - 1000, val)
    A._inflight[ck] = threading.Event()
try:
    t0 = time.time()
    st4, _, _ = http_get("/api/summary", timeout=2.0)
    dt4 = time.time() - t0
    ok(st4 == 200 and dt4 < 0.4, f"_inflight blocked on concentration still serves stale /api/summary immediately ({st4}, {dt4*1000:.0f}ms)")
finally:
    with A._lock:
        ev = A._inflight.pop(ck, None)
    if ev:
        ev.set()

# No em or en dash in touched files
for rel in ("poascan/guard.py", "poascan/analytics.py", "poascan/swap/api.py", "poascan/server.py", "tools/outage_fix_1123_test.py"):
    txt = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    ok(not re.search(r"[\u2013\u2014]", txt), f"no em/en dash in {rel}")

srv.shutdown()
srv.server_close()
print(f"\n{len(fails)} FAILED" if fails else "\nall ok")
sys.exit(1 if fails else 0)
