"""/api/epochs read as it arrives (1.26.229). 1) _read_closes gives exactly what json.loads gives for gzip and plain
bodies at any chunk size, raises where json.loads raises, and hands anything that is not a JSON array back whole.
2) fetch() over HTTP returns the same records and counts the same wire and inflated bytes. 3) A re-read that brings
nothing new does not rewrite the stored list or make readers parse it again, and still moves its stored time.
Temp database, local HTTP server. Usage: python3 tools/epochs_stream_test.py"""
import gzip, http.server, io, json, os, random, sys, tempfile, threading, time
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "s.db")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

def closes(n, seed=7):   # close records shaped like minepoa's: each close repeats a growing pending list
    rnd = random.Random(seed); pend = {}; out = []
    for i in range(n):
        pend = dict(pend, **{f"a{rnd.getrandbits(64):016x}": {"addr": f"poa1{rnd.getrandbits(64):016x}", "amount": rnd.randint(1, 10**6), "note": "caf\u00e9 \u2713"} for _ in range(40)})
        out.append({"epoch": i, "ts": 1792878384 + i * 21900, "rewards": {f"poa1{j:04d}": j * 3 for j in range(30)}, "basis": {"pending": dict(pend), "k": [1, 2.5, None, True]}})
    return out
BODY = json.dumps(closes(30)).encode()

srv_body = {}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b, enc = srv_body["b"], srv_body["enc"]
        self.send_response(200); self.send_header("Content-Type", "application/json")
        if enc: self.send_header("Content-Encoding", enc)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["POA_BASE"] = f"http://127.0.0.1:{srv.server_address[1]}"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, indexer as I, analytics as A, segments as S
db.init()

# 1) the reader against json.loads
def read(body, enc, chunk):
    I.STREAM_CHUNK = chunk
    try: r = I._read_closes(io.BytesIO(gzip.compress(body) if enc == "gzip" else body), enc)
    except Exception as e: return ("raises", type(e).__name__)
    return ("whole", r[2] == body) if r[0] is I._WHOLE else r[0]
cases = [b"[]", b" [ ]", b'[{"a":1}]', b'[{"a":1} , {"b":[1,2,{"c":"\xc3\xa9"}]}]\n', b"[1,2,3]", b"[12,345]", b'[{"x":"]"},{"y":","}]',
         b'{"error":"busy"}', b"<html>load</html>", b'[{"a":1},]', b'[{"a":1}', b'[{"a":1}] x', b" [1]", BODY]
bad = []
for c in cases:
    try: want = json.loads(c)
    except Exception as e: want = ("raises", type(e).__name__)
    if not c.startswith(b"["): want = ("whole", True)
    for enc in ("", "gzip"):
        for ch in ((1, 2, 3, 7, 64, 4096) if c is not BODY else (997, 65536, 256 * 1024)):
            got = read(c, enc, ch)
            if got != want: bad.append((c[:30], enc, ch, str(got)[:60]))
I.STREAM_CHUNK = 256 * 1024
check(f"reader equals json.loads over {len(cases)} bodies, gzip and plain, chunk sizes 1 byte to 256 KB {bad[:2]}", not bad)
r = read(BODY, "gzip", 256 * 1024)
k0 = next(iter(r[4]["basis"]["pending"]))
check("pending rows equal to the previous close's are shared, not copied", r[5]["basis"]["pending"][k0] is r[4]["basis"]["pending"][k0])
try: I._read_closes(io.BytesIO(b"[]"), "br"); check("an unknown content-encoding is refused", False)
except I.Busy: check("an unknown content-encoding is refused", True)

# 2) fetch over HTTP, the same records and byte counts either way
for enc in ("gzip", ""):
    srv_body.update(b=gzip.compress(BODY) if enc else BODY, enc=enc)
    d = I.fetch("/api/epochs")
    row = db.q1("SELECT bytes FROM fetch_log WHERE endpoint='/api/epochs'")
    check(f"fetch /api/epochs ({enc or 'plain'}) returns the records, inflated bytes {row['bytes']} logged",
          d == json.loads(BODY) and row["bytes"] == len(BODY))
srv_body.update(b=gzip.compress(b'{"error":"slow down"}'), enc="gzip")
try: I.fetch("/api/epochs"); check("an error object goes the old way (the strain notice guard refuses it)", False)
except I.Notice: check("an error object goes the old way (the strain notice guard refuses it)", True)
srv_body.update(b=b"<html>busy</html>", enc="")
try: I.fetch("/api/epochs"); check("a load page is still refused as non-JSON", False)
except I.Busy: check("a load page is still refused as non-JSON", True)

# 3) an unchanged re-read
rows = json.loads(BODY)
db.put_blob(S.blob_kind(), rows)
with S.use(S.CURRENT): first = A.epochs_raw(); ts0 = A.epochs_ts()
g0 = db.blob_gen(S.blob_kind()); time.sleep(1.1)
I.store_epochs(json.loads(BODY)); A._cache.clear()
with S.use(S.CURRENT): again = A.epochs_raw(); ts1 = A.epochs_ts()
check("unchanged re-read: not rewritten, readers keep the parsed list", again is first and db.blob_gen(S.blob_kind()) == g0)
check("and its stored time still moves (Close records feed as of)", ts1 and ts0 and ts1 > ts0)
rows2 = json.loads(BODY) + [dict(json.loads(BODY)[-1], epoch=30, ts=1792878384 + 30 * 21900)]
I.store_epochs(rows2); A._cache.clear()
with S.use(S.CURRENT): new = A.epochs_raw()
check("a re-read with a new close is written and parsed", len(new) == 31 and new is not first and db.get_blob(S.blob_kind())[0] == rows2)
srv.shutdown()
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
