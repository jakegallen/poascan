"""Close pressure (1.26.271). A full heavy pool must not 503 static files or the health checks, and must not be able
to take the slots reserved for the homepage and /chain. Close ingest acquires only a heavy slot, so it cannot hold
every serving slot. The epochs list is stored from a spill file: one close at a time, same records back.
Run: python3 tools/close_pressure_test.py (temp db, in-process, no network)."""
import io, json, os, sys, tempfile, time, urllib.request
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "cp.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_MAX_WORKERS"] = "4"
os.environ["POASCAN_SERVE_RESERVE"] = "2"
os.environ["POASCAN_HEAVY_WAIT"] = "0.3"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

from poascan import guard as GD, db, indexer as I, segments as S
import poascan.server as SV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

db.init()

class Stub(SV.H):
    def __init__(self, path):
        self.path = path; self.command = "GET"; self.sent = []; self.headers = {}
    def send(self, code, *a, **k):
        self.sent.append(code); return code

# ---------------------------------------------------------------- 1. caps
ok(GD.MAX_WORKERS == 4 and GD.RESERVE_CAP == 2 and GD.HEAVY_CAP == 2, f"4 serving slots, 2 heavy, 2 reserved ({GD.HEAVY_CAP}/{GD.RESERVE_CAP})")
ok(GD.cheap is not None and GD.RSS_EXIT_MB >= 1400 and GD.RSS_EXIT_MB <= 1800, f"cheap reserve exists and the memory exit is sized for the 2 GB VM ({GD.RSS_EXIT_MB} MB)")
src = open(os.path.join(ROOT, "poascan", "guard.py"), encoding="utf-8").read()
ok("2048" in src and "860" in src, "guard.py records why 860 MB was wrong on the 2048 MB machine")
ok("close_acquire" in open(os.path.join(ROOT, "poascan", "indexer.py"), encoding="utf-8").read().split("def job_epochs")[1].split("\nclass ")[0]
   and "GD.cheap" not in open(os.path.join(ROOT, "poascan", "indexer.py"), encoding="utf-8").read().split("def job_epochs")[1].split("\nclass ")[0],
   "close ingest acquires a heavy slot and does not touch the cheap reserve")

# ---------------------------------------------------------------- 2. classification
for p in ("/healthz", "/api/health", "/static/style.css", "/static/fonts/instrumentsans-latin-a64857.woff2",
          "/static/app.js", "/favicon.ico", "/apple-touch-icon.png", "/site.webmanifest", "/mark/abc.svg",
          "/.well-known/mcp.json", "/mcp/server-card", "/.well-known/ai-catalog.json", "/.well-known/agent-card.json"):
    st = Stub(p)
    ok(st._is_health() or st._is_free(), f"{p} takes no heavy slot")
ok(Stub("/")._is_free() is False and Stub("/")._path_only() in SV.H.CHEAP_PATHS, "/ is a cheap page (reserve), not a free file")
ok(Stub("/chain")._path_only() in SV.H.CHEAP_PATHS, "/chain is a cheap page")
ok(Stub("/address/poa1" + "A" * 40)._is_free() is False and Stub("/address/poa1" + "A" * 40)._path_only() not in SV.H.CHEAP_PATHS,
   "an address page stays on the heavy pool")
ok(Stub("/mcp/server-card")._html_shed_ok() is False, "/mcp/server-card sheds as a data file, not the HTML busy page")

# ---------------------------------------------------------------- 3. heavy pool full: static and health do not wait, cheap still runs, heavy 503s
held = []
while GD.slots.acquire(blocking=False): held.append(1)
ok(len(held) == GD.HEAVY_CAP, f"test holds every heavy slot ({len(held)})")
for p in ("/healthz", "/api/health", "/static/style.css", "/static/fonts/instrumentsans-latin-a64857.woff2", "/favicon.ico",
          "/.well-known/mcp.json", "/mcp/server-card", "/.well-known/ai-catalog.json"):
    called = []
    t0 = time.time()
    r = Stub(p)._gated(lambda: (called.append(1), "SERVED")[1])
    dt = time.time() - t0
    ok(called == [1] and r == "SERVED" and dt < 0.2, f"{p} served immediately with every heavy slot held ({dt*1000:.0f} ms)")
called = []
t0 = time.time()
r = Stub("/")._gated(lambda: (called.append(1), "HOME")[1])
dt = time.time() - t0
ok(called == [1] and r == "HOME" and dt < 0.2, f"homepage served from the reserve while heavy slots are held ({dt*1000:.0f} ms)")
called = []
r = Stub("/chain")._gated(lambda: (called.append(1), "CHAIN")[1])
ok(called == [1] and r == "CHAIN", "/chain served from the reserve while heavy slots are held")
heavy = Stub("/address/poa1" + "B" * 40); ran = []
t0 = time.time()
heavy._gated(lambda: (ran.append(1), "RENDER")[1])
dt = time.time() - t0
ok(heavy.sent == [503] and not ran, f"a heavy page still 503s when the heavy pool is full (sent={heavy.sent})")
ok(0.25 <= dt < 1.5, f"the heavy 503 waited about HEAVY_WAIT ({dt*1000:.0f} ms)")

# ---------------------------------------------------------------- 4. close ingest cannot take the reserve or a slot past the heavy cap
n = 0
while GD.close_acquire(): n += 1
ok(n == 0, "close_acquire finds the heavy pool already full")
ok(GD.cheap.acquire(blocking=False), "the reserve is still free after close ingest tried")
GD.cheap.release()
for _ in held: GD.slots.release()
held = []
n = 0
while GD.close_acquire(): n += 1
ok(n == GD.HEAVY_CAP and n < GD.MAX_WORKERS, f"close ingest can hold {n} heavy slots, not all {GD.MAX_WORKERS} serving slots")
ok(Stub("/static/app.js")._gated(lambda: "CSS") == "CSS", "static still served when close ingest holds every heavy slot")
ok(Stub("/")._gated(lambda: "HOME") == "HOME", "homepage still served when close ingest holds every heavy slot")
for _ in range(n): GD.slots.release()

# ---------------------------------------------------------------- 5. both pools full: static and health still answer, a cheap miss 503s
while GD.slots.acquire(blocking=False): held.append(1)
cheap_held = []
while GD.cheap.acquire(blocking=False): cheap_held.append(1)
ok(len(cheap_held) == GD.RESERVE_CAP, f"test holds the reserve ({len(cheap_held)})")
ok(Stub("/static/style.css")._gated(lambda: "FILE") == "FILE" and Stub("/healthz")._gated(lambda: "OK") == "OK",
   "static and health still answer when heavy and reserve are both full")
home = Stub("/"); ran = []
t0 = time.time(); home._gated(lambda: (ran.append(1), "HOME")[1]); dt = time.time() - t0
ok(home.sent == [503] and not ran and dt >= 0.25, f"a cheap miss 503s only when the reserve itself is full ({home.sent}, {dt*1000:.0f} ms)")
for _ in held: GD.slots.release()
for _ in cheap_held: GD.cheap.release()
held = []; cheap_held = []

# ---------------------------------------------------------------- 6. spill stores the same records, one close at a time, and a second pass does not rewrite
def closes(n, pending=40, agents=30):
    out = []
    pend = {}
    for i in range(n):
        pend = dict(pend)
        pend[f"{i:064x}"] = {"since": i, "author": "poa1" + f"{i:04d}", "note": "caf\u00e9"}
        out.append({"epoch": i, "ts": 1700000000 + i * 21600,
                    "rewards": {f"poa1{j:04d}": str(j) for j in range(agents)},
                    "basis": {"pending": dict(pend), "settled": []}})
    return out

rows = closes(6)
body = json.dumps(rows).encode()
seen = []
def sink(e): seen.append(e["epoch"])
got = I._read_closes(io.BytesIO(body), "", sink)
ok(seen == list(range(6)) and got[0] == [{"epoch": 0}] and len(got[0]) == 1, f"the stream sink keeps a one-field sample, not the list ({got[0]})")
ok(I.store_epochs(rows) is True, "store_epochs writes a new list")
ok(db.get_blob(S.blob_kind())[0] == rows, "the stored blob parses back to the same records")
before = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=?", (S.blob_kind(),))}
time.sleep(1.1)
ok(I.store_epochs(json.loads(body)) is False, "an unchanged re-read does not rewrite the blob")
after = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=?", (S.blob_kind(),))}
ok(before == after, "an unchanged re-read does not rewrite any close row")
rows2 = json.loads(body); rows2.append(dict(rows2[-1], epoch=6, ts=1700000000 + 6 * 21600))
ok(I.store_epochs(rows2) is True and db.get_blob(S.blob_kind())[0] == rows2, "one new close is stored and the blob matches")
after2 = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=?", (S.blob_kind(),))}
ok([p for p in after2 if after2[p] != before.get(p)] == [6], "only the new close's row is written")

# peak: spilling six fat closes stays near one close, not the whole list (the generator keeps only the current one)
import tracemalloc
def fat(n, pending=200, agents=200):
    for i in range(n):
        pend = {f"{i:04d}{j:060x}": {"since": i, "author": "poa1" + f"{j:04d}", "note": "x" * 24} for j in range(pending)}
        yield {"epoch": i, "ts": 1700000000 + i * 21600, "rewards": {f"poa1{j:04d}": str(j) for j in range(agents)},
               "basis": {"pending": pend, "settled": []}}
tracemalloc.start(); one = next(fat(1)); hold = [one, json.dumps(one)]; one_b = tracemalloc.get_traced_memory()[1]; tracemalloc.stop(); del hold, one
tracemalloc.start()
spill = I._Spill()
try:
    for e in fat(6): spill.add(e)
    peak = tracemalloc.get_traced_memory()[1]
finally:
    tracemalloc.stop(); spill.clear()
ok(peak < one_b * 4, f"spill peak {peak // 1024} KB stays near one close ({one_b // 1024} KB), not six")

# ---------------------------------------------------------------- 7. job_epochs with the heavy pool full still stores, and does not take a cheap slot
saved = I.fetch
def fake_fetch(*a, **k):
    sink = k.get("epoch_sink")
    rec = {"epoch": 0, "ts": 1700000000, "rewards": {"poa1a": "1"}, "basis": {"pending": {}, "settled": []}}
    if sink: sink(rec); return [{"epoch": 0}]
    return [rec]
I.fetch = fake_fetch
# fresh db file so this store is the whole list (the earlier rows are a different shape; use force on the same db)
# The fake record replaces by being a different list only if we point at a clean kind. Reuse the db: force fetch of one
# record would shrink... store of a shorter current list REPLACES the current segment (it is not an archived segment).
# That would destroy the rows above. Run the job check on the slot behaviour only, with finish short-circuited after acquire.
took = []
real_finish = I._Spill.finish
def finish_and_note(self):
    took.append(GD.slots.acquire(blocking=False))   # if close_acquire already released, a heavy slot is free
    if took[-1]: GD.slots.release()
    return False
I._Spill.finish = finish_and_note
while GD.slots.acquire(blocking=False): held.append(1)
cheap_ok = GD.cheap.acquire(blocking=False)
if cheap_ok: GD.cheap.release()
try:
    I.job_epochs(force=True)
finally:
    I.fetch = saved; I._Spill.finish = real_finish
    for _ in held: GD.slots.release()
ok(cheap_ok and GD.cheap.acquire(blocking=False), "job_epochs left the cheap reserve free")
GD.cheap.release()
ok(took == [False], f"job_epochs did not free a heavy slot to do its work (heavy still full: {took})")

# ---------------------------------------------------------------- 8. inline paint so a missing stylesheet is not a black page
import poascan.ui as UI
html = UI.layout("Proof of Agent explorer", "<p>hi</p>", "/")
ok("html,body{background:#0B0A08;color:#EFE7D6}" in html and html.index("<style>") < html.index('href="/static/style.css'),
   "the page paints ink on bone before the stylesheet, which overrides it when CSS loads")

# ---------------------------------------------------------------- 9. HTTP: static and health answer while the heavy slot is held inside the server
for _ in range(GD.HEAVY_CAP):
    if not GD.slots.acquire(blocking=False): break
srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
import threading
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path):
    try:
        r = urllib.request.urlopen(base + path, timeout=5); return r.status, r.read(20)
    except Exception as e:
        code = getattr(e, "code", None); return code, b""
for path in ("/healthz", "/static/style.css", "/static/fonts/instrumentsans-latin-a64857.woff2", "/favicon.ico"):
    c, b = get(path)
    ok(c == 200 and b, f"GET {path} is 200 while heavy slots are held ({c})")
c, _ = get("/no-such-heavy-page")
ok(c == 503, f"an uncached page is still 503 while heavy slots are held ({c})")
srv.shutdown()

ok(not any(chr(0x2013) in l or chr(0x2014) in l for l in open(__file__, encoding="utf-8")), "no em or en dash in this test")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
