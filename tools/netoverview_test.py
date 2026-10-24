"""Network > Overview after a genesis cut (1.26.94): compact cards, live-segment values, Signers, Version fallback, freshness.
Temp database, no network: the node is http://127.0.0.1:9 (refused). Usage: python3 tools/netoverview_test.py"""
import json, os, re, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "n.db")
os.environ.pop("POASCAN_SEGMENTS", None)
os.environ.update(POASCAN_DB=DB, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import db
db.init()
now = int(time.time())
NW = {"default_chain": "poa-mainnet-1", "chains": [
    {"chain_id": "poa-mainnet-1-segment1", "status": "halted", "default": False, "height": 55249, "checkpoint_height": 44003, "epochs_closed": 15},
    {"chain_id": "poa-mainnet-1", "status": "live", "default": True, "height": 2912, "checkpoint_height": 2415, "epochs_closed": 1}]}
db.put_blob("networks", NW)
db.put_blob("status", {"epochs_closed": 1, "checkpoint_height": 2415, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "K": 5})
db.put_blob("release", {"g0": {"addr": "poa1" + "g" * 40, "powers": ["notice"]}, "current": None, "history": [],
                        "note": "No release manifest on-ledger yet (G0 ceremony pending)."})
db.put_blob("params", {"K": 5})
from poascan import segments as SG, analytics as A, views as V, indexer as I
check(f"current segment is 2 ({SG.CURRENT})", SG.CURRENT == 2)
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))
R = "33c6" * 16
rows = [(0, "base-mainnet", "0x47", "", "0xa5", "poa-anchor:v1:genesis-seg2:" + "d0" * 32 + ":pred:" + "b4" * 32, iso(now - 4000), 2)]
for h in (135, 736, 1138, 1850, 2415):
    for ch in ("base-mainnet", "solana-mainnet"): rows.append((h, ch, f"tx{h}{ch[0]}", R, "x", f"poa-anchor:v1:h{h}:{R}:sigs5", iso(now - 600), 2))
rows.append((44003, "base-mainnet", "0x2c", R, "x", f"poa-anchor:v1:h44003:{R}:sigs4", iso(now - 9000), 1))   # segment 1: never on this page
db.write("INSERT OR IGNORE INTO anchors(height,chain,tx,state_root,anchored_by,memo,anchored_at,segment) VALUES(?,?,?,?,?,?,?,?)", rows, many=True)

html = V.network_overview("")
cards = dict((re.sub("<[^>]+>", "", a).strip(), b) for a, b in re.findall(r'<div class="sl">(.*?)</div><div class="sv"[^>]*>(.*?)</div>', html))
txt = lambda k: re.sub("<[^>]+>", "", cards.get(k, "")).strip()
check("stats grid carries netov (rows size to content)", 'class="stats six netov"' in html)
css = open(os.path.join(ROOT, "static", "style.css")).read()
check("CSS: .stats.netov rows auto, clip class", ".stats.netov{grid-auto-rows:auto}" in css and ".netov .sv .clip{" in css)
check(f"Chain height from the live chain ({txt('Chain height')})", txt("Chain height") == "2,912")
check(f"Finalized height from the live chain ({txt('Finalized height')})", txt("Finalized height") == "2,415")
check(f"Finality lag 497, not flagged ({txt('Finality lag')})", txt("Finality lag") == "497" and "Behind" not in html)
check(f"Closes from /api/status when no close record yet ({txt('Closes')})", txt("Closes") == "1")
check(f"Epoch cadence is a plain dash under 2 closes ({txt('Epoch cadence')!r})", txt("Epoch cadence") == "-")
check(f"Signers: 5, not the genesis memo ({txt('Signers')!r})", txt("Signers") == "5" and "genesis-seg2" not in cards.get("Signers", "") and 'title="' in cards.get("Signers", ""))
check(f"Version fallback None yet with the note as title ({txt('Version')!r})", txt("Version") == "None yet" and "G0 ceremony" in cards.get("Version", ""))
check(f"Anchored counts segment 2 heights only ({txt('Anchored')})", txt("Anchored") == "6")
check("no em or en dash on the page", "\u2014" not in html and "\u2013" not in html)
db.put_blob("networks", dict(NW, chains=[NW["chains"][0], dict(NW["chains"][1], height=5000, checkpoint_height=2415)]))
A._cache.clear() if hasattr(A, "_cache") else None
html2 = V.network_overview("")
check("a lag at or over LAG_BLOCKS is flagged Behind", A.LAG_BLOCKS == 2000 and "Behind" in html2)

# freshness: a failing tx feed with fresh status/networks reads is Live, not Stale
db.write("INSERT INTO fetch_log(endpoint,last_ok,last_err,fails,next_at,err) VALUES('/api/explorer/txs',?,?,5,?,'HTTP 404')", (now - 1800, now - 30, now + 600))
db.write("INSERT INTO fetch_log(endpoint,last_ok,fails,next_at) VALUES('/api/status',?,0,0)", (now - 20,))
f = A.freshness.__wrapped__() if hasattr(A.freshness, "__wrapped__") else A.freshness()
check(f"tx feed down, status fresh: Partial, not Stale ({f['state']}, {f['why']})", f["state"] == "partial" and f["label"] == "Partial" and f["tx_feed_down"] and "Tx list" in f["why"])
A._cache.clear() if hasattr(A, "_cache") else None
fd = A.feeds()
st = {x["label"]: x["state"] for x in fd["feeds"]}
check(f"feeds: chain Live, headline Partial, Tx list Down, Status OK ({fd['chain']}, {fd['state']}, {st})",
      fd["chain"] == "Live" and fd["state"] == "Partial" and not fd["ok"] and st.get("Tx list") == "Down" and st.get("Status") == "OK")
check(f"Close records Degraded when the live network counts a close we do not hold ({st.get('Close records')})", st.get("Close records") == "Degraded")
from poascan import views2 as V2
hb = V2.status_body()
check("Health shows the Feeds card with the same headline and chain", 'data-health="Partial"' in hb and 'data-feed="Tx list"' in hb and ">Live<" in hb)
check("Health never says healthy or operational", "healthy" not in hb.lower() and "OPERATIONAL" not in hb)
check("Health copy: no resync, operator or expected changes", not any(w in hb.lower() for w in ("resync", "re-sync", "operator", "expected")))
from poascan import server as SV
ah = SV.api("/api/health", {})[0]
check(f"/api/health carries the same state ({ah.get('ok')}, {ah.get('state')}, {ah.get('chain')})", ah["ok"] is False and ah["state"] == fd["state"] and ah["chain"] == fd["chain"] and [x["label"] for x in ah["feeds"]] == [x["label"] for x in fd["feeds"]])
from poascan import agentapi as AA
AA._META[0] = 0; m = AA.meta()
check(f"API meta: not stale when status was read 20 s ago while the tx feed fails ({m['stale']}, {m['fetched_at']})", m["stale"] is False)
check("no em or en dash on Health", "\u2014" not in hb and "\u2013" not in hb)
db.write("UPDATE fetch_log SET last_ok=? WHERE endpoint='/api/status'", (now - 900,))
f = A.freshness.__wrapped__() if hasattr(A.freshness, "__wrapped__") else A.freshness()
check(f"no fresh read anywhere: Stale ({f['state']})", f["state"] == "stale")

# indexer: a failing tx feed no longer skips the status and networks reads
SEEN = []
def fake(path, timeout=60, endpoint=None, cond=False, soft=False):
    SEEN.append(path)
    if path.startswith("/api/explorer/txs"): raise I.Busy("HTTP 404")
    if path == "/api/status": return {"epochs_closed": 1, "checkpoint_height": 2500, "as_of": "x"}
    return NW
I.fetch = fake
db.write("DELETE FROM fetch_log")
I.job_live()
check(f"job_live reads status and networks after a tx feed failure ({SEEN})", "/api/status" in SEEN and "/api/networks" in SEEN and db.get_blob("status")[0]["checkpoint_height"] == 2500)
check("the live job is not gated on the tx feed backoff", {j[0]: j[3] for j in I.JOBS}["live"] is None)
db.write("INSERT INTO fetch_log(endpoint,last_err,fails,next_at,err) VALUES('/api/explorer/txs',?,3,?,'HTTP 404')", (now, now + 600))
SEEN.clear(); I.job_live()
check("a backing-off tx feed is skipped inside the job", not any(p.startswith("/api/explorer/txs") for p in SEEN))

# ---------------- 1.26.98: moved read paths ----------------
check(f"tx_paths: chain-scoped path from the live chain first, explorer fallback ({I.tx_paths('a' * 64)})",
      I.tx_paths("a" * 64) == ["/chain/poa-mainnet-1/api/tx/" + "a" * 64, "/api/explorer/tx/" + "a" * 64])
db.put_blob("networks", {"chains": [{"chain_id": "poa-mainnet-1", "status": "live", "default": True}, {"chain_id": "bad/../x", "status": "live"}]})
check("a chain id that is not a plain id is never put in a path", all(".." not in p for p in I.tx_paths("b" * 64)))
db.put_blob("networks", NW)
check("allowlist: chain tx path yes, traversal no", I.ALLOWED.match("/chain/poa-mainnet-1/api/tx/" + "c" * 64) and not I.ALLOWED.match("/chain/../api/tx/" + "c" * 64))
CALLS = []; MODE2 = {}
def fake2(path, timeout=60, endpoint=None, cond=False, soft=False):
    CALLS.append(path); m = next((v for k, v in MODE2.items() if path.startswith(k)), None)
    if m == "busy": raise I.Busy("HTTP 404")
    if m == "missing": raise I.Missing("not found")
    if path.startswith("/api/txs"): return {"valid": [{"id": "d" * 64, "type": "challenge", "from": "poa1x", "ts": now, "final": 1}], "invalid": []}
    if path.startswith("/api/explorer/txs"): return [{"id": "e" * 64, "type": "challenge", "from_addr": "poa1x", "ts": now}]
    if "/api/tx/" in path or "/api/explorer/tx/" in path: return {"id": path[-64:], "type": "challenge", "final": 1}
    return NW
I.fetch = fake2
CALLS.clear(); d = I.fetch_tx("f" * 64, I.TX_EP, 5)
check(f"fetch_tx reads the chain path first ({CALLS})", d["id"] == "f" * 64 and CALLS == ["/chain/poa-mainnet-1/api/tx/" + "f" * 64])
MODE2["/chain/poa-mainnet-1/api/tx"] = "busy"; CALLS.clear(); d = I.fetch_tx("f" * 64, I.TX_EP, 5)
check(f"fetch_tx falls back to /api/explorer/tx when the chain path fails ({CALLS})", d["id"] == "f" * 64 and len(CALLS) == 2 and CALLS[1].startswith("/api/explorer/tx/"))
MODE2["/chain/poa-mainnet-1/api/tx"] = "missing"; MODE2["/api/explorer/tx/"] = "busy"
try: I.fetch_tx("f" * 64, I.TX_EP, 5); r = None
except I.Missing: r = "missing"
except I.Busy: r = "busy"
check(f"an id the chain path says is unknown is Missing even when the old path errors ({r})", r == "missing")
MODE2.clear()
db.write("DELETE FROM fetch_log"); CALLS.clear(); used = I.live_list()
check(f"live_list reads /api/txs first and stores it ({used}, {CALLS})", used == "/api/txs" and CALLS == ["/api/txs"] and db.q1("SELECT 1 AS x FROM txs WHERE id=?", ("d" * 64,)))
db.write("INSERT INTO fetch_log(endpoint,last_ok,fails,next_at) VALUES('/api/txs',?,0,0) ON CONFLICT(endpoint) DO UPDATE SET last_ok=excluded.last_ok, fails=0", (int(time.time()),))
CALLS.clear(); used = I.live_list()
check(f"inside TXLIST_S no second read ({used}, {CALLS})", used == "/api/txs" and CALLS == [])
MODE2["/api/txs"] = "busy"; db.write("DELETE FROM fetch_log"); CALLS.clear(); used = I.live_list()
check(f"/api/txs failing: the explorer feed takes over ({used}, {CALLS})", used == "/api/explorer/txs" and CALLS[0] == "/api/txs" and CALLS[1].startswith("/api/explorer/txs"))
MODE2.clear()
check("TXLIST_S floor 60 s, Tx list cadence in EVERY", I.TXLIST_S >= 60 and I.EVERY["/api/txs"] == I.TXLIST_S)
# feed rows after the move
t = int(time.time())
db.write("DELETE FROM fetch_log")
for ep, lo, le, f in (("/api/status", t - 20, None, 0), ("/api/networks", t - 20, None, 0), ("/api/txs", t - 30, None, 0), ("/api/explorer/txs", t - 3000, t - 30, 8),
                      ("/api/epochs", t - 2300, t - 3200, 0), ("/api/explorer/tx/:id (swaps)", t - 50000, t - 8000, 38), ("/api/swaps", t - 30, None, 0),
                      ("/api/explorer/tx/:id (on demand)", t - 60, t - 300, 0)):
    db.write("INSERT INTO fetch_log(endpoint,last_ok,last_err,fails,next_at) VALUES(?,?,?,?,0)", (ep, lo, le, f))
A._cache.clear() if hasattr(A, "_cache") else None
st = {x["label"]: x["state"] for x in A.feeds()["feeds"]}
check(f"Tx list OK on /api/txs while the explorer feed fails ({st.get('Tx list')})", st.get("Tx list") == "OK")
check(f"Epochs OK when it is not needed and not failing ({st.get('Epochs')})", st.get("Epochs") == "OK")
check(f"Swaps OK: book fresh, swap tx reads idle for 2h ({st.get('Swaps')})", st.get("Swaps") == "OK")
check(f"Tx lookup OK after a recent good read ({st.get('Tx lookup')})", st.get("Tx lookup") == "OK")
db.write("UPDATE fetch_log SET fails=3, last_err=? WHERE endpoint='/api/epochs'", (t - 60,))
A._cache.clear() if hasattr(A, "_cache") else None
st = {x["label"]: x["state"] for x in A.feeds()["feeds"]}
check(f"Epochs Degraded while a needed read fails ({st.get('Epochs')})", st.get("Epochs") == "Degraded")

# ---------------- 1.26.100: /api/txs load ----------------
SENT = []
class _R:
    def __init__(s, body, h): s.b, s.headers = body, h
    def read(s): return s.b
    def __enter__(s): return s
    def __exit__(s, *a): return False
import urllib.request as _U, urllib.error as _UE, importlib
I2 = importlib.reload(I)   # undo the fakes above
BODY = [json.dumps({"valid": [{"id": "1" * 64, "type": "challenge", "ts": now}], "invalid": []}).encode()]
def _open(req, timeout=None):
    SENT.append(dict(req.header_items()))
    if req.get_header("If-none-match") == '"e1"' and BODY[0] is None: raise _UE.HTTPError(req.full_url, 304, "nm", {}, None)
    return _R(BODY[0], {"ETag": '"e1"', "Last-Modified": "Sat, 24 Oct 2026 23:00:00 GMT"})
_U.urlopen = _open
db.write("DELETE FROM fetch_log"); I2._etags.clear(); I2._lastmod.clear()
used = I2.live_list()
check(f"first /api/txs read: new rows keep the 2 min cadence ({used}, {I2._txlist_every[0]})", used == "/api/txs" and I2._txlist_every[0] == I2.TXLIST_S == 120)
BODY[0] = None; db.write("UPDATE fetch_log SET last_ok=last_ok-200 WHERE endpoint='/api/txs'")
I2.live_list()
check("conditional headers sent: If-None-Match and If-Modified-Since", SENT[-1].get("If-none-match") == '"e1"' and SENT[-1].get("If-modified-since") == "Sat, 24 Oct 2026 23:00:00 GMT")
check(f"a 304 moves to the 5 min cadence ({I2._txlist_every[0]})", I2._txlist_every[0] == I2.TXLIST_IDLE_S == 300)
n = len(SENT); db.write("UPDATE fetch_log SET last_ok=? WHERE endpoint='/api/txs'", (int(time.time()) - 200,)); I2.live_list()
check("inside the 5 min cadence no read is sent", len(SENT) == n)
BODY[0] = json.dumps({"valid": [{"id": "1" * 64, "type": "challenge", "ts": now}], "invalid": []}).encode()
db.write("UPDATE fetch_log SET last_ok=? WHERE endpoint='/api/txs'", (int(time.time()) - 310,)); I2._etags.clear(); I2.live_list()
check(f"a 200 with no new rows stays at 5 min ({I2._txlist_every[0]})", I2._txlist_every[0] == 300)
BODY[0] = json.dumps({"valid": [{"id": "2" * 64, "type": "challenge", "ts": now}], "invalid": []}).encode()
db.write("UPDATE fetch_log SET last_ok=? WHERE endpoint='/api/txs'", (int(time.time()) - 310,)); I2._etags.clear(); I2.live_list()
check(f"new rows bring back the 2 min cadence ({I2._txlist_every[0]})", I2._txlist_every[0] == 120)
b = I2.bytes_1h().get("/api/txs", 0)
check(f"wire bytes counted per endpoint for the last hour ({b})", b > 0)
I2.flush_counts(force=True)
check("bytes flushed to upstream_bytes and still reported", I2.bytes_1h().get("/api/txs", 0) == b)

print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
