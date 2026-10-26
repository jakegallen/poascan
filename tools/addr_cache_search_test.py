"""Address balance freshness and hosted join name search (1.26.75). No request leaves the box: a fake minepoa.com runs
in this process and search reads POAScan's archive only.
* fetch_address / address_read never return a cached minepoa.com copy read more than ADDR_STALE (30 min) ago; it is
  dropped. The address page and /api/v1/address/<a> show the newer of that copy and the stored agent-list row
  (accounts.last_seen), with balance_as_of and balance_source. The on-demand read limits are unchanged.
* Agents are found by the name in their join tx memo ("hosted join: <name>"): MCP search, /api/v1/search?q= and /search
  (302 to the address page). Exact names come first; LIKE wildcards in q are literal; no upstream read.
Usage: python3 tools/addr_cache_search_test.py"""
import json, os, socket, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
os.environ["POASCAN_SEGMENTS"] = "1"   # one segment: the explorer serves the current state
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

SEEN = []; UPBAL = {}; MODE = {"addr": "ok"}
class Up(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        SEEN.append(self.path)
        if self.path.startswith("/api/explorer/address/") and MODE["addr"] == "ok":
            a = self.path.rsplit("/", 1)[1]; b = json.dumps({"address": a, "balance": UPBAL.get(a, "0.000000"), "txs": [{"id": "ee" * 32, "type": "transfer", "from_addr": a, "to_addr": a, "amount": "1", "ts": 1, "final": 1}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        self.send_response(503); self.send_header("Content-Length", "0"); self.end_headers()
up = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
UP = f"http://127.0.0.1:{up.server_address[1]}"

tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "c.db")
os.environ.update(POASCAN_DB=dbp, POA_BASE=UP, POASCAN_INDEXER="0")
import fixture; fixture.seed()
from poascan import db, indexer as I, agentapi as AG, server as SV, views as V
A1, A2, A3 = fixture.A1, fixture.A2, fixture.A3
P1 = "poa169z9r55C33n8bhwUXJwTnMutdATCV8sVR7Lm2SMXXZBC"   # the real Plus1 / test agent addresses, ids only
T1 = "poa18u1PiDvvzvKBocrErLFzfLNr4WXTWpc1sFePmLEePdEy"; T2 = "poa1E9WV4vmY7vR1fE9GUkvER7hDraY8giaj6CPtg5YsxdMk"
T10 = "poa1" + "T" * 40; ODD = "poa1" + "Q" * 40

# ---------------- limits unchanged ----------------
check("on-demand read limits unchanged (addr 0.05/s burst 10, 300 s per address, global 0.25/s, client 0.2/s, 3 in flight)",
      (I.ADDR_RATE, I.ADDR_BURST, I.ADDR_MIN_S, I.GLOBAL_RATE, I.CLIENT_RATE, I.ONDEMAND_MAX) == (0.05, 10, 300, 0.25, 0.2, 3))
check("cache windows: fresh 60 s, shown while revalidating up to 30 min", (V.ADDR_TTL, V.ADDR_STALE) == (60, 1800))

# ---------------- fix 1: balance freshness ----------------
now = int(time.time())
def acc(a, bal, seen):
    db.write("INSERT INTO accounts(addr,invited_by,balance,balance_s,api_ts,api_joined_epoch,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?) "
             "ON CONFLICT(addr) DO UPDATE SET balance=excluded.balance, balance_s=excluded.balance_s, last_seen=excluded.last_seen", [(a, None, float(bal), bal, None, None, seen, seen)], many=True)
def put(a, bal, age):   # a cached minepoa.com copy read `age` s ago
    with V._addr_lock: V._addr_cache[a] = (time.time() - age, {"address": a, "balance": bal, "txs": []}, time.time() - age)

# The 4:31 to 4:37 PM case: copy read before the sweeps (8,276,539.296435), the agents job wrote the swept balance since.
OLD, NEW = "8276539.296435", "8297349.296435"
acc(P1, NEW, now - 120); put(P1, OLD, 3 * 3600); MODE["addr"] = "down"
I.neg_put(I.ADDR_EP + P1, False)   # the live read fails (as with "upstream budget for this lookup spent")
d, err, at = V.address_read(P1)
check("a cached copy read 3 h ago is dropped, not returned, when the live read fails", d is None and err and at is None and P1 not in V._addr_cache)
r, _ = SV.api(f"/api/address/{P1}", {})
check("API: the stored agent-list balance wins over a 3 h old copy, with as_of and source", r["balance"] == NEW and r["balance_source"] == "agents" and r["balance_as_of"] == now - 120)
put(P1, OLD, 900)   # inside the 30 min window but older than the 2 min old agent list row
d, err, at = V.address_read(P1)
check("a 15 min old copy is still served (stale while revalidate)", d and d["balance"] == OLD and abs(at - (time.time() - 900)) < 5)
r, _ = SV.api(f"/api/address/{P1}", {})
check("API: the newer copy wins (agent list 2 min old beats a 15 min old address read)", r["balance"] == NEW and r["balance_source"] == "agents")
html = V.address(P1)
check("address page shows the newer balance", "8,297,349" in html and "8,276,539" not in html)
put(P1, NEW, 10); acc(P1, OLD, now - 600)
r, _ = SV.api(f"/api/address/{P1}", {})
check("API: a fresh address read beats an older agent list row", r["balance"] == NEW and r["balance_source"] == "explorer/address" and abs(r["balance_as_of"] - (now - 10)) < 5)
b = V.address_balance(ODD)
check("no copy at all: balance null, no source", b["balance"] is None and b["as_of"] is None and b["source"] is None)
with V._addr_lock: V._addr_cache.pop(T1, None)
acc(T1, "20000.000000", now - 60); UPBAL[T1] = "0.000000"; MODE["addr"] = "ok"
I.upsert_txs([{"id": "a0" * 32, "type": "transfer", "from_addr": T1, "to_addr": T2, "amount": "20000", "ts": now - 30, "final": 1}], "test")   # 1.26.166: a 0 beats a fresh nonzero agent list row only after an archived outgoing tx
r, _ = SV.api(f"/api/address/{T1}", {})
check("API: a live read just now beats the agent list (swept to 0, the sweep tx archived)", r["balance"] == "0.000000" and r["balance_source"] == "explorer/address" and r["fetch_error"] is None)
check("one upstream read for that address", sum(1 for p in SEEN if p.endswith(T1)) == 1)
r, _ = SV.api(f"/api/address/{T1}", {})
check("a second read within 60 s is served from cache, no new upstream read", sum(1 for p in SEEN if p.endswith(T1)) == 1 and r["balance"] == "0.000000")
spec = AG.openapi()["paths"]
check("OpenAPI documents balance_as_of and balance_source", "balance_source" in json.dumps(spec["/api/v1/address/{address}"]))

# ---------------- fix 2: hosted join name search ----------------
n0 = len(SEEN)
I.upsert_txs([{"id": "a1" * 32, "type": "join", "from_addr": T1, "memo": "hosted join: poaswap-test-1", "ts": now - 999, "final": 1},
              {"id": "a2" * 32, "type": "join", "from_addr": T2, "memo": "hosted join: pswap-test-c71d29", "ts": now - 998, "final": 1},
              {"id": "a3" * 32, "type": "join", "from_addr": T10, "memo": "hosted join: poaswap-test-10", "ts": now - 997, "final": 1},
              {"id": "a4" * 32, "type": "join", "from_addr": ODD, "memo": "hosted join: 100% real_agent", "ts": now - 996, "final": 1}], "test")
res = AG.t_search({"query": "poaswap-test-1"})["results"]
check("MCP search: the exact join name is first, linked to the address page", res and res[0]["id"] == T1 and res[0]["name"] == "poaswap-test-1"
      and res[0]["name_source"] == "join" and res[0]["url"].endswith("/address/" + T1))
check("MCP search: substring join names follow", any(h["id"] == T10 for h in res[1:]))
res = AG.t_search({"query": "PSWAP-TEST-C71D29"})["results"]
check("MCP search: case-insensitive", [h["id"] for h in res if h.get("kind") == "address"] == [T2])
check("LIKE wildcards are literal: '%' and '_' match only names that contain them",
      [h["id"] for h in AG.t_search({"query": "%"})["results"]] == [] and [h["id"] for h in AG.t_search({"query": "0% real_"})["results"]] == [ODD]
      and [h["id"] for h in AG.t_search({"query": "t_s"})["results"]] == [])
check("search makes no upstream read", len(SEEN) == n0)
r, _ = SV.api("/api/search", {"q": ["pswap-test-c71d29"]})
check("/api/v1/search returns the same results", r["results"][0]["id"] == T2 and r["query"] == "pswap-test-c71d29")
for qs in ({}, {"q": [""]}, {"q": ["a", "b"]}, {"q": ["x" * 121]}):
    try: SV.api("/api/search", qs); ok = False
    except SV.BadRequest: ok = True
    check(f"/api/v1/search rejects {list(qs.values()) or 'no q'}"[:80], ok)
# Live 1.26.75 gap: the archive held both join txs with their memos, yet the labels rows were blank, so search found nothing.
I.upsert_txs([{"id": "a1" * 32, "type": "join", "from_addr": T1, "ts": now - 999, "final": 1}], "explorer/address")   # same join, memo omitted
check("a later memo-less copy of a join keeps its label and custody",
      dict(db.q1("SELECT label, custody FROM labels WHERE addr=?", (T1,))) == {"label": "poaswap-test-1", "custody": "hosted"})
T3 = "poa1" + "R" * 40
I.upsert_txs([{"id": "a5" * 32, "type": "join", "from_addr": T3, "memo": "hosted join: blank-label-agent", "ts": now - 995, "final": 1}], "test")
db.write("UPDATE labels SET label='', custody='non-hosted join (likely self-custody)' WHERE addr=?", (T3,))   # a row blanked before this fix
res = AG.t_search({"query": "blank-label-agent"})["results"]
check("a blank labels row still finds the name from the archived join tx memo", res and res[0]["id"] == T3 and res[0]["name"] == "blank-label-agent" and res[0]["name_source"] == "join")
from poascan import names as NM
check("repair refills the blanked join label and custody from the archived memo", I.repair_join_labels() == 1
      and dict(db.q1("SELECT label, custody, source FROM labels WHERE addr=?", (T3,))) == {"label": "blank-label-agent", "custody": "hosted", "source": "join memo"})
check("repair is idempotent and leaves named rows alone", I.repair_join_labels() == 0 and db.q1("SELECT label FROM labels WHERE addr=?", (T1,))["label"] == "poaswap-test-1")
from poascan import analytics as _AN; _AN._cache.pop(("agent_names",), None)   # drop any cached name index
check("name-available: a repaired join name reads taken", NM.taken("blank-label-agent") and NM.taken("poaswap-test-1"))
check("llms.txt lists /api/v1/search", "/api/v1/search?q=" in AG.llms_txt() and "/api/v1/search" in spec)

# ---------------- over HTTP: /search redirect, /api/v1/search, /api/v1/address ----------------
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
op = urllib.request.build_opener(NoRedir)
def get(url):
    try:
        with op.open(url, timeout=30) as r: return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e: return e.code, e.read().decode(), dict(e.headers)
port = free_port(); base = f"http://127.0.0.1:{port}"
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=dict(os.environ, PORT=str(port), HOST="127.0.0.1"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=1); break
        except Exception: time.sleep(0.2)
    c, b, h = get(base + "/search?q=poaswap-test-1")
    check("/search?q=poaswap-test-1 redirects to its address page (exact beats poaswap-test-10)", c == 302 and h.get("Location") == "/address/" + T1)
    c, b, h = get(base + "/search?q=pswap-test-c71d29")
    check("/search?q=pswap-test-c71d29 redirects to its address page", c == 302 and h.get("Location") == "/address/" + T2)
    c, b, h = get(base + "/api/v1/search?q=poaswap-test")
    ids = [x["id"] for x in json.loads(b)["results"]]
    check("/api/v1/search over HTTP: 200 JSON, both poaswap-test names", c == 200 and T1 in ids and T10 in ids and "meta" in json.loads(b))
    c, b, h = get(base + "/api/v1/search")
    check("/api/v1/search without q is a JSON 400", c == 400 and "q is required" in b)
    c, b, h = get(base + f"/api/v1/address/{P1}")
    d = json.loads(b)
    check("/api/v1/address over HTTP carries balance_as_of and balance_source", c == 200 and "balance_as_of" in d and d.get("balance_source") in ("agents", "explorer/address"))
finally:
    p.terminate(); p.wait(10)

print("\n" + ("ALL OK" if not fails else f"{len(fails)} FAILED"))
sys.exit(1 if fails else 0)
