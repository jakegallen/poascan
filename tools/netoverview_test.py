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
check(f"tx feed down, status fresh: Partial, not Stale ({f['state']}, {f['why']})", f["state"] == "partial" and f["label"] == "Partial" and f["tx_feed_down"] and "Explorer txs" in f["why"])
A._cache.clear() if hasattr(A, "_cache") else None
fd = A.feeds()
st = {x["label"]: x["state"] for x in fd["feeds"]}
check(f"feeds: chain Live, headline Partial, Explorer txs Down, Status OK ({fd['chain']}, {fd['state']}, {st})",
      fd["chain"] == "Live" and fd["state"] == "Partial" and not fd["ok"] and st.get("Explorer txs") == "Down" and st.get("Status") == "OK")
check(f"Close records Down when the live network counts a close we do not hold ({st.get('Close records')})", st.get("Close records") == "Down")
from poascan import views2 as V2
hb = V2.status_body()
check("Health shows the Feeds card with the same headline and chain", 'data-health="Partial"' in hb and 'data-feed="Explorer txs"' in hb and ">Live<" in hb)
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

print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
