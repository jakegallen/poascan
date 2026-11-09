"""Audit 2026-11-09 fixes (1.26.285). In process plus one local server on a temp database, no upstream reads.
1) A feed minepoa paused upstream (1.26.280 label "Paused upstream") reads degraded on the route rows, never a bare down,
   and the Swaps detail says paused upstream.
2) X-API-Commit carries the deployed git SHA next to X-API-Version (and is exposed to CORS readers); /api/health commit
   equals it; with no GIT_SHA (a local build) the header is absent and commit is null.
3) Persisted warm pins are stamped with the build. A different build reloads them as already expired (1.26.286: boots
   warm, the warm pass replaces them first); the same build keeps their timestamps.
4) /api/v1/txs answers 400 for an offset past the cap instead of silently clamping it (a clamp served the wrong page).
Usage: python3 tools/audit1109_test.py"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "a.db"), POASCAN_INDEXER="0", POASCAN_HTML_CACHE="1", POA_BASE="http://127.0.0.1:9")
os.environ.pop("GIT_SHA", None)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# ---- 1) route rows: Paused upstream is degraded
from poascan import routehealth as RH, db, htmlcache as HC
now = time.time()
rows = [dict(label="Swaps", state="Paused upstream", last_ok=now - 60), dict(label="Anchors", state="Paused upstream", last_ok=now - 60)]
rts = {r["id"]: r for r in RH.routes(rows, now)}
check("Swaps paused upstream reads degraded, not down", rts["swaps"]["state"] == "degraded")
check("Swaps detail says paused upstream", "paused upstream" in rts["swaps"]["detail"])
check("Anchors paused upstream reads degraded, not down", rts["anchors"]["state"] == "degraded")
rts = {r["id"]: r for r in RH.routes([dict(label="Swaps", state="Down", last_ok=now - 60)], now)}
check("a real Down feed still reads down", rts["swaps"]["state"] == "down" and rts["swaps"]["detail"] == "Swap reads down")

# ---- 3) pins are per build
db.init()
k = HC.key("/network", {}, None, False)
HC.put(k, "<html>old build</html>", now=time.time())
os.environ["GIT_SHA"] = "a" * 40
check("persist stamps the build", HC.persist_pins(force=True) >= 1 and db.get_blob(HC.PIN_BLOB)[0]["build"] == "sha:" + "a" * 40)
HC._pin.clear(); HC._c.clear()
os.environ["GIT_SHA"] = "b" * 40
t_net = HC.ttl("/network", {})
check("another build reloads the pins as already expired, past TTL plus grace (boots warm, replaced first)",
      HC.load_pins() == 1 and HC.last(k) == "<html>old build</html>" and HC.get(k, t_net) is None
      and time.time() - HC._stored_ts(k) > t_net + HC.WARM_GRACE)
HC._pin.clear(); HC._c.clear()
os.environ["GIT_SHA"] = "a" * 40
check("the same build reloads them with their own timestamp (OOM or guard restart)", HC.load_pins() == 1 and HC.get(k, t_net) == "<html>old build</html>")
blob = db.get_blob(HC.PIN_BLOB)[0]; blob.pop("build"); db.put_blob(HC.PIN_BLOB, blob); HC._pin.clear(); HC._c.clear()
check("an unstamped blob (written before 1.26.285) reloads as expired", HC.load_pins() == 1 and HC.get(k, t_net) is None)
os.environ.pop("GIT_SHA", None)

# ---- 2) and 4) on a local server
SHA = "c0ffee" + "0" * 34
def serve(extra):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, f"s{port}.db"), POASCAN_INDEXER="0", **extra)
    if "GIT_SHA" not in extra: env.pop("GIT_SHA", None)
    subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    return p, base
def get(base, path):
    try:
        r = urllib.request.urlopen(base + path, timeout=30); return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read().decode()

p, base = serve({"GIT_SHA": SHA})
try:
    st, hd, body = get(base, "/api/v1/summary")
    check("X-API-Commit equals the stamped SHA on an API response", hd.get("X-API-Commit") == SHA and hd.get("X-API-Version"))
    check("X-API-Commit is exposed to CORS readers", "X-API-Commit" in (hd.get("Access-Control-Expose-Headers") or ""))
    st, hd, body = get(base, "/api/health")
    check("/api/health commit equals X-API-Commit", json.loads(body).get("commit") == SHA == hd.get("X-API-Commit"))
    st, hd, body = get(base, "/api/v1/txs?offset=10001&limit=1")
    check("/api/v1/txs offset past the cap is a 400 that names the cursor", st == 400 and "cursor" in body)
    st, hd, body = get(base, "/api/v1/txs?offset=10000&limit=1")
    check("/api/v1/txs offset at the cap still answers 200", st == 200)
finally:
    p.terminate(); p.wait(10)
p, base = serve({})
try:
    st, hd, body = get(base, "/api/health")
    check("no GIT_SHA: no X-API-Commit header and commit null", "X-API-Commit" not in hd and json.loads(body).get("commit") is None)
finally:
    p.terminate(); p.wait(10)
check("no em or en dash in this test", not any(c in open(__file__, encoding="utf-8").read() for c in "\u2014\u2013"))
sys.exit(1 if fails else 0)
