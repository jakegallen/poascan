"""Request cost under load (1.26.81). The live machine sat CPU throttled (70%+ steal) because each page and meta
build ran maint.grading_state up to ~15 times (two COUNT DISTINCT scans, blob decodes) and every polled API answer
was rebuilt, plainjson-scanned and gzipped per request.
* grading_state is computed once per db write generation and at most every GRADING_MEMO_S seconds; a write or
  grading_memo_clear() is seen at once; an explicit now bypasses the memo.
* /api/v1 JSON answers come from a micro cache for POASCAN_API_MICRO_S seconds: same bytes and headers, the gzip
  copy reused; /api/health and /api/search are never cached; errors are never cached.
* plainjson skips the full pass when no JSON number is in e-notation (hex ids inside strings do not trigger it).
Temp database, no network. Usage: python3 tools/perf_test.py"""
import gzip, json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "p.db")
os.environ.update(POASCAN_DB=DB, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
from poascan import db, maint as M, agentapi as AG
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

db.init(); now = int(time.time())
db.put_blob(M.COMPLETE_BLOB, {"at": now - 3600, "notice_id": "2026-10-23-grading-resumed", "txid": "aa" * 32, "seen_at": now - 3600})
db.write("INSERT OR REPLACE INTO fetch_log(endpoint, last_ok, fails, next_at) VALUES('/api/explorer/txs', ?, 0, 0)", (now,))

# ---- grading_state memo
calls = [0]; real = M._grading_state
def counted(now=None): calls[0] += 1; return real(now)
M._grading_state = counted; M.grading_memo_clear()
for _ in range(15): M.grading_state()
check("memo: 15 calls in one build compute grading_state once", calls[0] == 1)
s0 = M.grading_state()["state"]
db.write_tx([("INSERT INTO txs(id, type, from_addr, ts) VALUES(?, 'grade-sealed', ?, ?)", ("s%d" % i, "poa1" + "G" * 39 + str(i), now - 60), False) for i in range(3)])
s1 = M.grading_state(); n1 = calls[0]
check("memo: a db write is seen at once (seals recent -> open)", s0 == "unconfirmed" and s1["state"] == "open" and s1["seals_recent"] == 3 and n1 == 2)
M.grading_state(now=now); check("memo: an explicit now bypasses the memo", calls[0] == 3)
M.grading_memo_clear(); M.grading_state(); check("memo: grading_memo_clear forces a recompute", calls[0] == 4)
d = M.grading_state(); d["state"] = "x"; check("memo: callers get a copy", M.grading_state()["state"] == "open")
M._grading_state = real

# ---- plainjson
check("plainjson: e-notation numbers become plain", AG.plainjson(json.dumps({"a": 1.059e-05, "b": [2e-7]})) == '{"a": 0.00001059, "b": [0.0000002]}')
t = json.dumps({"id": "ab3e5c" * 10, "memo": "ratio: 1e5", "n": 5})
check("plainjson: hex ids and e-notation inside strings are left alone", AG.plainjson(t) == t)
check("plainjson: a string with e-notation next to a real one stays a string", AG.plainjson(json.dumps({"m": "x: 1e5", "v": 3e-6})) == '{"m": "x: 1e5", "v": 0.000003}')

# ---- API micro cache, through the server
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def get(url, gz=False):
    rq = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"} if gz else {})
    try:
        with urllib.request.urlopen(rq, timeout=30) as r: b = r.read(); return r.status, (gzip.decompress(b) if r.headers.get("Content-Encoding") == "gzip" else b).decode(), dict(r.headers)
    except urllib.error.HTTPError as e: return e.code, e.read().decode(), dict(e.headers)
port = free_port(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_API_MICRO_S="3")
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=1); break
        except Exception: time.sleep(0.2)
    c1, b1, h1 = get(base + "/api/v1/txs?limit=5")
    db.write("INSERT INTO txs(id, type, from_addr, ts) VALUES('n1', 'transfer', ?, ?)", ("poa1" + "N" * 40, now))
    c2, b2, h2 = get(base + "/api/v1/txs?limit=5")
    check("micro: a repeat within the window is the same answer", c1 == c2 == 200 and b1 == b2 and "n1" not in b2)
    check("micro: headers kept (meta headers, CORS, max-age=15)", h2.get("X-API-Version") == h1.get("X-API-Version") and h2.get("Access-Control-Allow-Origin") == "*" and h2.get("Cache-Control") == "max-age=15")
    c3, b3, _ = get(base + "/api/v1/txs?limit=6")
    check("micro: another query string is its own entry", c3 == 200)
    cg, bg, hg = get(base + "/api/v1/txs?limit=5", gz=True)
    check("micro: a gzip client gets the same body", cg == 200 and bg == b1)
    time.sleep(3.2); c4, b4, _ = get(base + "/api/v1/txs?limit=5")
    check("micro: after the window the answer is rebuilt", c4 == 200 and '"n1"' in b4)
    ch1 = get(base + "/api/v1/health")[1]; time.sleep(1.1); ch2 = get(base + "/api/v1/health")[1]
    check("micro: /api/v1/health is never cached", json.loads(ch1).get("meta", {}).get("generated_at") != json.loads(ch2).get("meta", {}).get("generated_at") or ch1 != ch2)
    ce, _, _ = get(base + "/api/v1/txs?limit=abc"); ce2, _, _ = get(base + "/api/v1/txs?limit=abc")
    check("micro: errors are not cached (the same 4xx each time, never a cached 200)", ce == ce2 and 400 <= ce < 500)
finally:
    p.terminate(); p.wait(10)
print("ALL OK" if not fails else f"{len(fails)} FAILED"); sys.exit(1 if fails else 0)
