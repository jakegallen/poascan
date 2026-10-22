"""Per-request cost on /address and /tx, and the page rate limit (1.26.2).
* history.assignments() is cached per grader: a second call does not rerun the seal query; a new grade-sealed tx, a late
  tx_detail (INSERT OR REPLACE) or a new epochs blob rebuilds it; results match an uncached build; rows handed out are copies.
* views.chains_linked() parses the chains blob only when the stored copy changes.
* Server (indexer off): /address and /tx HTML pages over the per-client budget get 429 with Retry-After, keyed on
  Fly-Client-IP; another client is unaffected; no header means no limit; /api/v1/*, /healthz and /static are never
  limited at mirror rates and well above; the log notes header presence once and never holds a client IP.
Usage: python3 tools/pagecost_test.py"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "p.db")
os.environ["POASCAN_DB"] = dbp
import fixture; fixture.seed()
from poascan import db, analytics as A, history as HI, views as V
G = fixture.A2

# ---- assignments cache
seal_runs = [0]; real_q = db.q
def q(sql, args=()):
    if "$.body.assignment" in sql and "grade-sealed" in sql: seal_runs[0] += 1
    return real_q(sql, args)
db.q = q
a1 = HI.assignments(G, None, 1); n1 = seal_runs[0]; a2 = HI.assignments(G, None, 50)
check("assignments: built once for two calls", n1 == 1 and seal_runs[0] == 1)
check("assignments: limit still applies to a cached list", len(a1["rows"]) == min(1, a1["assignments"]) and len(a2["rows"]) == min(50, a2["assignments"]))
if a2["rows"]: a2["rows"][0]["status"] = "tampered"
check("assignments: rows handed out are copies", all(r.get("status") != "tampered" for r in HI.assignments(G, None, 50)["rows"]))
before = HI.assignments(G, None, 200)["assignments"]
now = int(time.time()); new = "9e" * 32
db.write("INSERT INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)", (new, "grade-sealed", G, None, now, 5, 5, 1))
db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,1)", (new, json.dumps({"id": new, "type": "grade-sealed", "from_addr": G, "ts": now, "final": True,
         "body": {"type": "grade-sealed", "assignment": "9f" * 32, "from": G, "ts": now}}), now))
r = HI.assignments(G, None, 200)
check("assignments: a new grade-sealed tx rebuilds", seal_runs[0] == 2 and r["assignments"] == before + 1 and any(o["answer"] == "9f" * 32 for o in r["rows"]))
k = seal_runs[0]
db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,1)", (new, json.dumps({"id": new, "type": "grade-sealed", "from_addr": G, "ts": now, "final": True,
         "body": {"type": "grade-sealed", "assignment": "9d" * 32, "from": G, "ts": now}}), now))
r = HI.assignments(G, None, 200)
check("assignments: a late tx_detail rewrite rebuilds", seal_runs[0] == k + 1 and any(o["answer"] == "9d" * 32 for o in r["rows"]))
k = seal_runs[0]
eps, _ = db.get_blob("epochs"); time.sleep(1.1); db.put_blob("epochs", eps); A._cache.clear()   # epochs_raw has its own 15 s TTL
HI.assignments(G, None, 1)
check("assignments: a new epochs blob rebuilds", seal_runs[0] == k + 1)
k = seal_runs[0]; HI.assignments(G, None, 1)
check("assignments: cached again after the rebuild", seal_runs[0] == k)
cached = HI.assignments(G, None, 200); HI._acache.clear(); fresh = HI.assignments(G, None, 200)
check("assignments: cached result equals an uncached build", cached == fresh)
check("assignments: an address with no seals is cached too", HI.assignments(fixture.A3, None, 1)["assignments"] >= 0 and fixture.A3 in HI._acache)
db.q = real_q

# ---- chains blob
gets = [0]; real_get = db.get_blob
def gb(kind):
    if kind == "chains": gets[0] += 1
    return real_get(kind)
db.get_blob = gb
db.put_blob("chains", {G: {"solana": {"addr": "So1" + "a" * 40, "verified": True}}})
c1 = V.chains_linked(); c2 = V.chains_linked()
check("chains_linked: parsed once for two calls", gets[0] == 1 and G in c1 and c1 is c2)
db.put_blob("chains", {G: {}, fixture.A1: {}})
check("chains_linked: a new copy is parsed again", fixture.A1 in V.chains_linked() and gets[0] == 2)
db.get_blob = real_get

# ---- server: page rate limit
from poascan import server as S
check("page limit defaults are generous (>= 60 burst, >= 30 pages/min sustained)", S.PAGE_LIMIT.burst >= 60 and S.PAGE_LIMIT.rate * 60 >= 30)
logp = os.path.join(tmp, "server.log")
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POASCAN_MAINTENANCE="1",
           POASCAN_PAGE_BURST="6", POASCAN_PAGE_RATE="0.01")
lf = open(logp, "w"); p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=lf, stderr=lf)
def get(path, ip=None):
    r = urllib.request.Request(base + path, headers={"Fly-Client-IP": ip} if ip else {})
    try:
        x = urllib.request.urlopen(r, timeout=30); x.read(); return x.status, dict(x.headers)
    except urllib.error.HTTPError as e:
        e.read(); return e.code, dict(e.headers)
IP1, IP2 = "203.0.113.77", "198.51.100.23"   # documentation ranges
try:
    for _ in range(150):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    codes = [get("/address/" + G, IP1)[0] for _ in range(4)] + [get("/tx/" + "4a" * 32, IP1)[0] for _ in range(2)]
    check("pages inside the burst are served", all(c in (200, 404) for c in codes))
    c, h = get("/address/" + G, IP1)
    check(f"over the budget: 429 with Retry-After ({c})", c == 429 and int(h.get("Retry-After", "0")) >= 1 and "no-store" in h.get("Cache-Control", ""))
    c, _ = get("/tx/" + "4a" * 32, IP1)
    check(f"/tx shares the budget ({c})", c == 429)
    c, _ = get("/address/" + G, IP2)
    check(f"another client is unaffected ({c})", c == 200)
    c, _ = get("/address/" + G)
    check(f"no Fly-Client-IP: not limited ({c})", c == 200)
    api = [get(pth, IP1)[0] for _ in range(20) for pth in ("/api/v1/status", "/api/v1/swaps", "/api/swaps")]
    check("API calls from a limited client are never limited", all(c == 200 for c in api))
    hz = [get(pth, IP1)[0] for _ in range(10) for pth in ("/healthz", "/static/style.css", "/")]
    check("/healthz, /static and / are never limited", all(c == 200 for c in hz))
finally:
    p.terminate(); p.wait(10); lf.close()
log = open(logp).read()
check("log notes header presence once", log.count("Fly-Client-IP header present=True") == 1)
check("log never holds a client IP", IP1 not in log and IP2 not in log)

print("\n%d failure(s)" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
