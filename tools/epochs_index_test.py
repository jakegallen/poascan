"""1.26.324/1.26.325: /api/epochs is an index; missing close bodies are fetched from /api/epochs/<n> and stored
only when the raw JSON sha256 matches the index. The raw body is not kept: close_rows holds the parsed fields plus
the index sha256 and byte count, and the blobs row is a stub. The old all-bodies list still works. No credential in a URL.

Usage: python3 tools/epochs_index_test.py
"""
import hashlib, http.server, json, os, sys, tempfile, threading, time
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "e.db")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

def close(n, ts=None):
    return {"epoch": n, "ts": int(ts or (1792878384 + n * 21900)), "pool": 1000, "rewards": {}, "basis": {"pending": {}}}

def raw_of(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()

def sha(b):
    return hashlib.sha256(b).hexdigest()

C0, C1, C2 = close(0), close(1), close(2)
B0, B1, B2 = raw_of(C0), raw_of(C1), raw_of(C2)
# a body with the wrong hash
BAD = raw_of(dict(C1, pool=9999))
INDEX = {
    "chain_id": "poa-mainnet-1", "v": 1, "closed_through": 2, "count": 3,
    "epochs": [
        {"n": 0, "sha256": sha(B0), "bytes": len(B0), "close_ts": C0["ts"], "key": "epochs/poa-mainnet-1/0.json"},
        {"n": 1, "sha256": sha(B1), "bytes": len(B1), "close_ts": C1["ts"], "key": "epochs/poa-mainnet-1/1.json"},
        {"n": 2, "sha256": sha(B2), "bytes": len(B2), "close_ts": C2["ts"], "key": "epochs/poa-mainnet-1/2.json"},
    ],
}

bodies = {"/api/epochs": json.dumps(INDEX).encode(), "/api/epochs/0": B0, "/api/epochs/1": B1, "/api/epochs/2": B2}
hits = []
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = self.path.split("?")[0]
        hits.append(path)
        b = bodies.get(path)
        if b is None:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["POA_BASE"] = "http://127.0.0.1:%d" % srv.server_address[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, indexer as I, analytics as A, strain as ST, keysafe as KS, closestore as CS, segments as S
db.init()

def stored_closes():
    A._cache.clear(); A._epochs.clear()
    return [A.full_close(e) for e in (A.epochs_raw() or [])]
I.EPOCHS_BODY_PACE_S = 0

# --- strain ---
check("strain accepts the live index shape", ST.detect("/api/epochs", INDEX) is None)
check("strain still accepts a list of close records", ST.detect("/api/epochs", [C0, C1]) is None)
check("strain still refuses an error object as if it were data", ST.detect("/api/epochs", {"error": "slow down"}) is not None)
check("strain accepts /api/epochs/76 as a close body", ST.detect("/api/epochs/76", C2) is None)
check("strain refuses /api/epochs/76 without epoch", ST.detect("/api/epochs/76", {"ts": 1}) is not None)

# --- allowlist and credentials ---
check("ALLOWED matches /api/epochs and /api/epochs/76",
      bool(I.ALLOWED.match("/api/epochs") and I.ALLOWED.match("/api/epochs/76")))
try:
    I.fetch("/api/epochs/76?token=pk_secret")
    check("fetch refused a credential in the path", False)
except ValueError:
    check("fetch refused a credential in the path", True)

# --- job_epochs fetches only missing, checks sha256, keeps already-stored closes ---
db.put_blob("status", {"epochs_closed": 3, "supply": 1, "txs": 1, "checkpoint_height": 1, "as_of": "2026-11-13T00:00:00Z"})
db.put_blob("epochs", [C0])
A._cache.clear()
hits.clear()
wrote = I.job_epochs(force=True)
A._cache.clear()
stored = stored_closes()
ns = [int(e["epoch"]) for e in stored]
check("job_epochs stored the missing closes and kept epoch 0", wrote is True and ns == [0, 1, 2])
check("only the index and missing bodies were fetched (not epoch 0 again)",
      hits.count("/api/epochs") == 1 and "/api/epochs/0" not in hits
      and hits.count("/api/epochs/1") == 1 and hits.count("/api/epochs/2") == 1)
check("stored E1 and E2 match the served bodies",
      any(e.get("pool")==C1["pool"] and e.get("epoch")==1 for e in stored)
      and any(e.get("epoch")==2 for e in stored))
blob = db.get_blob("epochs")[0]
check("the epochs blob is a stub, not the raw close list", CS.is_stub(blob) and not isinstance(blob, list))
kind = db.q1("SELECT kind FROM close_rows WHERE epoch=1")["kind"]
row1 = db.q1("SELECT raw_sha256, raw_bytes FROM close_rows WHERE kind=? AND epoch=1", (kind,))
check("raw sha256 and bytes from the index are stored on the new close",
      row1 and row1["raw_sha256"] == sha(B1) and int(row1["raw_bytes"] or 0) == len(B1))

# sha256 mismatch is skipped; already stored rows remain; the good missing close is stored
bodies["/api/epochs/1"] = BAD   # index still has sha(B1)
db.put_blob("epochs", [C0])
db.write("DELETE FROM fetch_log")
A._cache.clear(); hits.clear()
wrote = I.job_epochs(force=True)
A._cache.clear()
stored = stored_closes()
ns = [int(e["epoch"]) for e in stored]
check("sha256 mismatch skips that close and does not drop already-stored rows",
      0 in ns and 1 not in ns and 2 in ns)
check("the mismatched body was requested once", hits.count("/api/epochs/1") == 1)

# legacy all-bodies list still stores
LIST = [close(0), close(1)]
bodies["/api/epochs"] = json.dumps(LIST).encode()
db.put_blob("epochs", [])
db.write("DELETE FROM fetch_log")
A._cache.clear(); hits.clear()
wrote = I.job_epochs(force=True)
A._cache.clear()
stored = stored_closes()
check("legacy all-bodies list is still stored", wrote is True and [e["epoch"] for e in stored] == [0, 1]
      and hits == ["/api/epochs"])
check("legacy store also uses a stub blob", CS.is_stub(db.get_blob("epochs")[0]))

srv.shutdown()
print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
