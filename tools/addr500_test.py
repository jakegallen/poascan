"""Address pages never answer 500 (Tidewatch, LabLeak comment 5899: 2 of 5 address pages were 500 on 2026-10-26).
Root cause: 1.26.140 added the established basis "import" (an Agent the segment's genesis import flags established, with
no established_after or established_removed since), and views.established_card had no label for it, so every such page
raised KeyError 'import'. One fixture Agent per address shape is rendered over real HTTP (in-process server, no request
leaves the box): genesis import with and without activity, added at a close, removed, never established but answering,
zero balance with no records, outgoing transfers only, plus an unknown future basis. Malformed addresses get 404 on the
page and 400 or 404 on the API, never 500. Usage: python3 tools/addr500_test.py"""
import json, os, sys, tempfile, threading, time, urllib.error, urllib.request
os.environ.setdefault("POASCAN_SEGMENTS", "1")   # synthetic history: one segment, so the genesis import below is segment 1's
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "a5.db"), POA_BASE="http://127.0.0.1:9", POASCAN_INDEXER="0")
import fixture; fixture.seed()
from poascan import db, server as SV, views as V, agents as G, analytics as A, estfold as EF, segments as S, indexer as I

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

UP = []
def _nofetch(*a, **k): UP.append(a[0] if a else "?"); raise I.Busy("no upstream in tests")
I.fetch = _nofetch
V.address_read = lambda a: (None, None, None)   # archive only: no minepoa.com read

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def ad(i): return "poa1" + "T" + B58[i // 58 % 58] + B58[i % 58] + "w" * 37
IMPORTED, IMPORTED_QUIET, LISTED, REMOVED, NEVER, ZERO, OUTGOING, RECEIVER = (ad(i) for i in range(1, 9))
now = int(time.time())
EF.CFG["imports"] = {str(S.selected()): {"established": [IMPORTED, IMPORTED_QUIET, REMOVED], "established_count": 3,
                                         "url": "x", "sha256": "x", "final_checkpoint_height": 1, "agents": 3}}
ep = db.get_blob(S.blob_kind())[0] or []
ep[-3]["basis"]["established_after"] = list(ep[-3]["basis"].get("established_after") or []) + [LISTED]
ep[-2]["basis"]["established_removed"] = [REMOVED]
db.put_blob(S.blob_kind(), ep)
db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,to_addr,amount,ts,atts,final,epoch) VALUES(?,?,?,?,?,?,?,?,?)",
         [("a5" + f"{i:062x}", t, f, to, amt, now - 3600 * (i + 1), 5, 1, len(ep) - 1) for i, (t, f, to, amt) in enumerate([
             ("challenge", IMPORTED, None, None), ("challenge", NEVER, None, None), ("challenge", LISTED, None, None),
             ("transfer", OUTGOING, RECEIVER, 12.5), ("join", IMPORTED, None, None)])], many=True)
A._cache.clear()

est = A.established_set()
check("fixture: genesis import Agents established, the removed one not", IMPORTED in est and IMPORTED_QUIET in est and REMOVED not in est and LISTED in est)
bases = {a: G.established_history(a)["basis"] for a in (IMPORTED, IMPORTED_QUIET, LISTED, REMOVED, NEVER, ZERO)}
check(f"fixture: every basis shape present ({bases})", bases == {IMPORTED: "import", IMPORTED_QUIET: "import", LISTED: "listed",
                                                                 REMOVED: "removed", NEVER: "none", ZERO: "none"})
for a in (IMPORTED, IMPORTED_QUIET):
    try: h = V.established_card(a)
    except Exception as e: h = f"{type(e).__name__}: {e}"
    check(f"established card: genesis import labelled, no KeyError ({a[:8]})", "Genesis import" in h and "Established history" in h)

srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path):
    try:
        r = urllib.request.urlopen(base + path, timeout=30); return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace")

SHAPES = {"genesis import, answering (the 500s)": IMPORTED, "genesis import, no txs": IMPORTED_QUIET, "added at a close": LISTED,
          "removed at a close": REMOVED, "never established, answering": NEVER, "zero balance, no records": ZERO,
          "outgoing transfer only": OUTGOING, "incoming transfer only": RECEIVER, "fixture A1 (rich, established)": fixture.A1,
          "fixture A3 (slashed)": fixture.A3}
for name, a in SHAPES.items():
    for p in (f"/address/{a}", f"/api/v1/address/{a}", f"/api/address/{a}", f"/api/v1/address/{a}/established",
              f"/api/v1/address/{a}/standing", f"/api/v1/address/{a}/txs"):
        c, body = get(p)
        check(f"{name}: {p.split(a)[0]}...{p.split(a)[1]} is 200 (got {c})", c == 200)
c, body = get(f"/address/{IMPORTED}")
check("genesis import page shows its basis", "Genesis import" in body and "Established history" in body)

real = V.established_card; G_hist = G.established_history
G.established_history = lambda a: dict(G_hist(a), basis="future-basis", established=True)
try: h = V.established_card(IMPORTED); ok = "future-basis" in h
except Exception as e: ok = False
G.established_history = G_hist
check("an unknown future basis renders as its name instead of raising", ok)

BAD = ["poa1x", "poa10OIl0OIl0OIl0OIl0OIl0OIl", "poa1" + "1" * 70, "poa1" + "z" * 80, "poa1_abc_def_ghi_jkl_mno_pqr",
       IMPORTED[:-1] + "0", IMPORTED + "I", "POA1abc", "0xdeadbeef", "poa1", "poa1%00abc", "poa1%C3%A9%C3%A9"]
for b in BAD:
    c, _ = get(f"/address/{b}")
    check(f"malformed /address/{b[:24]} is 404 (got {c})", c == 404)
    for p in (f"/api/v1/address/{b}", f"/api/address/{b}"):
        c, _ = get(p)
        check(f"malformed {p[:40]} is 400 or 404 (got {c})", c in (400, 404))
check(f"no upstream request ({len(UP)})", not UP)
srv.shutdown()
print("FAILS:", fails) if fails else print("ALL OK")
sys.exit(1 if fails else 0)
