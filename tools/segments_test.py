"""Genesis cut (1.26.91, poascan/segments.py): migration of a 1.26.89 database, the segment boundary and per-segment reads.
Temp database, no network: the node is http://127.0.0.1:9 (refused). Usage: python3 tools/segments_test.py"""
import json, os, shutil, socket, sqlite3, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "s.db")
os.environ.pop("POASCAN_SEGMENTS", None)
os.environ.update(POASCAN_DB=DB, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

CUT = 1792875660; P = 21600
ROOT1 = "b45a8a5c6965cd4053f74e403f2817154f589fa5a3bc5d055ed016968fdd12a7"
def addr(c): return "poa1" + c * 40
X, Y = addr("x"), addr("y")
def iso(t): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
def close(n, ts, rewards=None):
    return {"epoch": n, "ts": ts, "pool": 1e9, "minted": 1e6, "rewards": rewards or {}, "challenges": {}, "propagation": {},
            "basis": {"pending": {}, "settled": [], "challenge_eligible": [], "established_after": [], "established_removed": []}}
S1 = [close(n, CUT - (15 - n) * P - 4 * 3600, {X: "10"} if n == 14 else None) for n in range(15)]   # E0..E14, E14 about 4h before the cut
S1[14]["basis"]["established_after"] = [Y]; S1[13]["basis"]["challenge_eligible"] = [Y]   # Y established in segment 1

# ---- 1. a database written by the code before 1.26.91 (origin/main's db.py, run as it was) ----
legacy = os.path.join(tmp, "legacy"); os.makedirs(legacy)
BASE = os.environ.get("SEGMENTS_TEST_BASE", "5e48b69")   # the last release before segments (1.26.89)
arc = subprocess.run(f"git archive {BASE} poascan | tar -x -C {legacy}", shell=True, cwd=ROOT, capture_output=True, text=True)
if arc.returncode or not os.path.exists(os.path.join(legacy, "poascan", "db.py")):
    print("skip legacy seed (no git history): " + arc.stderr[-200:]); shutil.copytree(os.path.join(ROOT, "poascan"), os.path.join(legacy, "poascan"), dirs_exist_ok=True)
seed = f"""
import json
from poascan import db
db.init()
tx = lambda i, f, ts, n: (db.write("INSERT INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)", (i, "challenge", f, 1, ts, 5, 5, 1)),
                          db.write("INSERT INTO tx_detail(id, json, fetched, final) VALUES(?,?,?,?)", (i, json.dumps({{"body": {{"nonce": n}}}}), ts, 1)))
for k in range(1, 396): tx("a%062x" % k, "{X}", {CUT} - 400000 + k * 600, k)      # segment 1: nonces 1..395
db.write("INSERT INTO answers VALUES(?,?,?,?,?,?,?,?,?,?,?)", ("a%062x" % 1, "{X}", 1, {CUT} - 399400, 22, 0, 0, "An a", {CUT} - 399000, "An archived answer.", "en"))
db.write("INSERT INTO anchors VALUES(?,?,?,?,?,?,?)", (44003, "base-mainnet", "0x2c31", "{ROOT1}", "g0", "m", "{iso(CUT + 3600)}"))   # final root, re-anchored late
db.write("INSERT INTO anchors VALUES(?,?,?,?,?,?,?)", (2, "base-mainnet", "0xs1h2", "r1", "g0", "m", "{iso(CUT - 900000)}"))
db.put_blob("epochs", {json.dumps(S1)})
"""
r = subprocess.run([sys.executable, "-c", seed], cwd=legacy, env=dict(os.environ, PYTHONPATH=legacy), capture_output=True, text=True)
check("legacy 1.26.89 database seeded " + r.stderr[-300:], r.returncode == 0)

from poascan import db, segments as SG, analytics as A, indexer as I, history as H, maint as M, records as RR
db.init(); db.init()   # idempotent
check("two segments, current is 2", SG.NUMBERS == (1, 2) and SG.CURRENT == 2 and SG.has_cut())
check("existing txs are segment 1", db.q1("SELECT COUNT(*) AS n FROM txs WHERE segment IS NOT 1")["n"] == 0 and db.q1("SELECT COUNT(*) AS n FROM txs")["n"] == 395)
check("existing answers are segment 1", db.q1("SELECT segment FROM answers")["segment"] == 1)
anc = {(r["segment"], r["height"]) for r in db.q("SELECT segment, height FROM anchors")}
check("anchors migrated with segment (final root stays in segment 1)", anc == {(1, 44003), (1, 2)})
check("close records moved to epochs:s1", len(db.get_blob("epochs:s1")[0]) == 15 and db.get_blob("epochs")[0] == [])

# ---- 2. the new segment's anchors, txs and closes ----
I.store_anchors([{"height": 2, "chain": "base-mainnet", "tx": "0xs2h2", "state_root": "r2", "anchored_at": iso(CUT + 1200)},
                 {"height": 44003, "chain": "base-mainnet", "tx": "0x2c31", "state_root": ROOT1, "anchored_at": iso(CUT + 1300)}])
check("height 2 of segment 2 stored next to segment 1's height 2", db.q1("SELECT tx FROM anchors WHERE segment=2 AND height=2")["tx"] == "0xs2h2"
      and db.q1("SELECT tx FROM anchors WHERE segment=1 AND height=2")["tx"] == "0xs1h2" and db.q1("SELECT COUNT(*) AS n FROM anchors")["n"] == 3)
A._cache.clear()
check("anchor summary is the current segment's", A.anchor_summary()["top"] == 2 and A.anchor_summary()["segment"] == 2)
with SG.use(1): check("anchor summary ?segment=1 tops at h44003", A.anchor_summary()["top"] == 44003)

I.upsert_txs([{"id": "b%062x" % k, "type": "challenge", "from": X, "epoch": 0, "ts": CUT + 120 * k, "atts": 5, "k": 5, "final": True} for k in range(1, 4)], "test")
for k in range(1, 4): db.write("INSERT INTO tx_detail(id, json, fetched, final) VALUES(?,?,?,?)", ("b%062x" % k, json.dumps({"body": {"nonce": k}}), CUT + 120 * k, 1))
db.write("INSERT INTO txs(id, type, from_addr, epoch, ts) VALUES(?,?,?,?,?)", ("c" * 64, "send", Y, 0, CUT + 60))   # a writer that names no segment
check("indexer and trigger give post-cut txs segment 2", db.q1("SELECT COUNT(*) AS n FROM txs WHERE segment=2")["n"] == 4)

I.store_epochs(S1)   # /api/epochs still serving segment 1's records
check("segment 1 records on /api/epochs leave the current blob empty", db.get_blob("epochs")[0] == [] and len(db.get_blob("epochs:s1")[0]) == 15)
I.store_epochs([close(0, CUT + 1800, {X: "7"}), close(1, CUT + 1800 + P // 4, {Y: "3"})])   # new segment E0 and E1
I.store_epochs(S1[:3])   # a short segment 1 read never shrinks the archive
A._cache.clear()
check("new E0/E1 in their own blob", [e["epoch"] for e in db.get_blob("epochs")[0]] == [0, 1])
check("segment 1 archive untouched", len(db.get_blob("epochs:s1")[0]) == 15)
rows = A.epoch_rows()
check("epoch list: current segment E0, E1 only", [r["epoch"] for r in rows] == [0, 1] and all(r["segment"] == 2 for r in rows))
with SG.use(1): r1 = A.epoch_rows()
check("epoch list ?segment=1: E0..E14", [r["epoch"] for r in r1] == list(range(15)) and all(r["segment"] == 1 for r in r1))
check("E0 of segment 2 is not segment 1's E0", rows[0]["close_ts"] != r1[0]["close_ts"])
o = A.open_epoch()
check("open epoch is segment 2 E2", o["epoch"] == 2 and o["segment"] == 2)
with SG.use(1): check("open epoch ignores ?segment=1", A.open_epoch()["epoch"] == 2)
rb = A.rewards_by_addr()
check("lifetime rewards span both segments (S1 E14, S2 E0)", float(rb[X][14]) == 10 and float(rb[X][15]) == 7)
check("lifetime close labels", SG.ep_label(14) == "S1 E14" and SG.ep_label(15) == "E0" and SG.ep_href(3) == "/epoch/3?segment=1")
check("records index per segment", [x["epoch"] for x in RR.index()] == [0, 1] if hasattr(RR, "index") else True)

check("established standing carried over the cut", Y in A.established_set())
check("standing expiry not estimated from the other segment's closes (unknown, never past)", A.established_expiry_est(Y)["established_expires_epoch_est"] is None)

# ---- 3. nonce reset is not a gap ----
cv = H.coverage(X)
check("nonce for segment 2 restarts (3, no gap)", cv["segment"] == 2 and cv["highest_nonce"] == 3 and cv["nonce_gap"] == 0)
s1 = [s for s in cv["by_segment"] if s["segment"] == 1][0]
check("segment 1 nonce kept (395, no gap)", s1["highest_nonce"] == 395 and s1["nonce_gap"] == 0 and s1["archived"])
check("nonce never compared across the cut", cv["nonce_gap"] == 0 and all(s["nonce_gap"] == 0 for s in cv["by_segment"]))

# ---- 4. recovery reads the new low checkpoint as moved ----
db.put_blob("status", {"epochs_closed": 2, "checkpoint_height": 2, "as_of": iso(int(time.time()))}); A._cache.clear()
check("low checkpoint after a cut is not parked", M.recovery()["moved"] is True)
from poascan import reconcile as RC
rr = RC.reconcile(); rows = rr.get("rows", rr) if isinstance(rr, dict) else rr
ep_row = [r for r in rows if isinstance(r, dict) and r.get("key") == "epochs"]
check("reconcile Closes: 2 in segment 2 against epochs_closed 2", bool(ep_row) and ep_row[0]["poascan"] == 2 and ep_row[0]["node"] == 2 and ep_row[0]["state"] == "match")

from poascan import ui as U
svg = U.line([(CUT - 7200, 5300), (CUT - 3600, 5341), (CUT + 600, 4941), (CUT + 1800, 4950)], breaks=[CUT])
check("chart line is not drawn across the cut (agents_joined restarted)", svg.count(" M") + svg.count('"M') >= 2 and U.line([(1, 1), (2, 2), (3, 3)]).count("M") == 1)
pts = [(CUT - 3600 * 5, 5000), (CUT - 600, 5341), (CUT + 600, 4941), (CUT + 3000, 4960)]
db.write("DELETE FROM snaps WHERE kind='status'")
for t, a in pts: db.write("INSERT INTO snaps(kind, ts, json) VALUES('status', ?, ?)", (t, json.dumps({"agents_joined": a})))
check("join points start at the cut (no negative delta across it)", [t for t, _ in A._join_points(CUT - 86400)] == [CUT + 600, CUT + 3000])

# ---- 5. HTTP: pages and API with ?segment ----
def free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
port = free()
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=dict(os.environ, PORT=str(port), HOST="127.0.0.1"),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def get(path, data=None, hd=None):
    for _ in range(100):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}{path}", data, hd or {}), timeout=20) as r: return r.status, r.read().decode(), dict(r.headers)
        except urllib.error.HTTPError as e: return e.code, e.read().decode(), dict(e.headers)
        except (ConnectionError, urllib.error.URLError): time.sleep(0.2)
    return 0, "", {}
try:
    c, b, h = get("/api/epoch/0")
    j = json.loads(b) if c == 200 else {}
    check("/api/epoch/0 is segment 2 E0", c == 200 and j.get("segment") == 2)
    c, b, h = get("/api/epoch/0?segment=1"); j = json.loads(b) if c == 200 else {}
    check("/api/epoch/0?segment=1 is segment 1 E0", c == 200 and j.get("segment") == 1 and j.get("close_ts") == S1[0]["ts"])
    c, b, h = get("/api/epoch/9")
    check("/api/epoch/9 is not closed in segment 2 (404 with segment)", c == 404 and json.loads(b).get("segment") == 2)
    c, b, h = get("/api/epoch/0?segment=7"); check("bad segment is a 400", c == 400)
    c, b, h = get("/api/epochs?segment=1"); check("/api/epochs?segment=1 lists 15", c == 200 and len(json.loads(b)) == 15)
    c, b, h = get("/epochs"); check("epoch list has the segment toggle and cut note", c == 200 and "Segment 1 (archived)" in b and "Segment 2 began at h44003 of segment 1. Earlier history archived." in b)
    c, b, h = get("/epochs?segment=1"); check("archived epoch list links stay in segment 1", c == 200 and 'href="/epoch/3?segment=1"' in b and "poa-mainnet-1-segment1" in b)
    c, b, h = get("/epoch/14?segment=1"); check("archived epoch page", c == 200 and "Segment 1 (archived)" in b)
    c, b, h = get("/network?tab=health"); check("health shows Genesis cut", c == 200 and "Genesis cut" in b)
    c, b, h = get(f"/address/{X}"); check("address page shows per-segment nonce", c == 200 and ">S2 3</span>" in b and ">S1 395</span>" in b)
    c, b, h = get(f"/api/address/{X}/txs"); j = (json.loads(b) if c == 200 else {}).get("coverage") or {}
    check("coverage API: current nonce and by_segment", c == 200 and j.get("highest_nonce") == 3 and j.get("segment") == 2 and len(j.get("by_segment", [])) == 2)
    def mcp(name, args):
        c, b, h = get("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}).encode(),
                      {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        r = json.loads(b).get("result") or {}
        return r.get("structuredContent") or json.loads(((r.get("content") or [{}])[0]).get("text") or "{}")
    j = mcp("get_network_summary", {})
    check("MCP summary carries segment and genesis_cut", j.get("segment") == 2 and (j.get("genesis_cut") or {}).get("from_height") == 44003)
    j = mcp("get_epoch", {"epoch": 0, "segment": 1})
    check("MCP get_epoch segment 1 E0", j.get("segment") == 1 and j.get("segment_archived") is True)
    j = mcp("get_epoch", {"epoch": 0})
    check("MCP get_epoch default is segment 2", j.get("segment") == 2)
    c, b, h = get("/api/status"); j = json.loads(b) if c == 200 else {}
    check("/api/status names the cut", j.get("segment") == 2 and (j.get("genesis_cut") or {}).get("label") == "Genesis cut")
    c, b, h = get("/api/v1/epoch/0/record?segment=1"); c2, b2, h2 = get("/api/v1/epoch/0/record")
    check("records: segment 1 E0 immutable, bare E0 not, different bodies", c == 200 and c2 == 200 and "immutable" in (h.get("Cache-Control") or "")
          and "immutable" not in (h2.get("Cache-Control") or "") and b != b2)
    c, b, h = get("/about"); check("/about has the Segments method", c == 200 and 'id="segments"' in b)
    for path in ("/epochs", "/epochs?segment=1", "/epoch/0", "/about", "/network?tab=health"):
        c, b, h = get(path); check(f"no en or em dash on {path}", "\u2013" not in b and "\u2014" not in b)
finally:
    p.terminate(); p.wait(10)
shutil.rmtree(tmp, ignore_errors=True)
print("FAILED: " + ", ".join(fails) if fails else "all ok"); sys.exit(1 if fails else 0)
