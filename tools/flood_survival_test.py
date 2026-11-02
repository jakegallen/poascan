"""Flood survival (1.26.252): a crawler walking random addresses and tx hashes no longer forces full table scans or
on-demand upstream reads. Five additive, read-only changes, each checked here:
  1. New indexes (forum_posts/forum_comments author, grade_history seg+close) exist after db.init().
  2. A cheap known check and a tx negative cache skip the heavy work and the minepoa read for an unknown probe.
  3. A valid but unknown /tx and /address 404 is edge-cacheable; other errors stay no-store.
  4. The API micro cache keeps a ~30 s TTL, a 16 MB byte cap (gzip copy counted) and drops expired on put.
  5. The per-IP limiter key is the IPv6 /64, and the limiter evicts a bounded oldest slice.
Run: python3 tools/flood_survival_test.py (temp db, a local counting stand-in for minepoa, no real network)."""
import http.server, os, socket, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)

fails = []
def ok(c, m): print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

# ---------------------------------------------------------------- 1. indexes exist after db.init()
tmp = tempfile.mkdtemp()
os.environ["POASCAN_DB"] = os.path.join(tmp, "idx.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
from poascan import db, indexer as I, gradehist as GH, clientip as CIP, agentapi as AG, views as V

def indexes():
    return {r["name"] for r in db.q("SELECT name FROM sqlite_master WHERE type='index'")}

db.init()
have = indexes()
ok("forum_posts_author" in have, "forum_posts(author_public_id) index after db.init()")
ok("forum_comments_author" in have, "forum_comments(author_public_id) index after db.init()")
GH._ensure()   # creates grade_history (as a prod DB already has it) and its indexes
ok("grade_history_seg_close" in indexes(), "grade_history(seg, close) index exists once the table does")
# db.init() must (re)apply it on boot to an existing prod table: drop it, re-init, it is back
db.write("DROP INDEX grade_history_seg_close")
ok("grade_history_seg_close" not in indexes(), "dropped grade_history(seg, close) to simulate an old prod DB")
db.init()
ok("grade_history_seg_close" in indexes(), "db.init() recreates grade_history(seg, close) on boot for the existing table")

# ---------------------------------------------------------------- 2. cheap known check + the heavy work is skipped for a probe
KNOWN_A = "poa1" + "K" * 40; UNKNOWN_A = "poa1" + "Z" * 40
db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, ts) VALUES(?,?,?,?)", ("ab" * 32, "challenge", KNOWN_A, int(time.time())))
ok(V._addr_known_cheap(KNOWN_A) is True, "known address (a tx) passes the cheap check")
ok(V._addr_known_cheap(UNKNOWN_A) is False, "unknown address fails the cheap check")
db.write("INSERT OR REPLACE INTO labels(addr, label, source, ts) VALUES(?,?,?,?)", ("poa1" + "L" * 40, "x", "t", 0))
ok(V._addr_known_cheap("poa1" + "L" * 40) is True, "an address with only a label still passes (established/forum covered too)")
# a probe (not in the archive, no live read) 404s WITHOUT running the heavy profile work (POA_BASE is a dead port, so the read fails fast)
called = []
_orig_profile = V.G.profile
V.G.profile = lambda a: called.append(a) or {}
try: r = V.address(UNKNOWN_A)
finally: V.G.profile = _orig_profile
ok(isinstance(r, tuple) and r[0] == 404 and not called, f"an unknown address 404s without the heavy profile/established/settled work (profile calls: {called})")

# ---------------------------------------------------------------- 4. micro cache: TTL, byte cap (gzip counted), drop expired on put
import poascan.server as S
ok(S.MICRO_S >= 30 and S.MICRO_TOTAL_MAX == 16 * 1024 * 1024, f"micro cache TTL ~30 s and 16 MB byte cap (S={S.MICRO_S:g})")
with S._micro_lock: S._micro.clear()
S._micro_put("k1", b"x" * 1000, {})
with S._micro_lock:
    S._micro["k1"][1][2] = b"z" * 400   # a send() gzip copy
    ok(S._micro_total() == 1400, f"byte total counts the body plus the gzip copy ({S._micro_total()})")
    S._micro["old"] = (time.time() - S.MICRO_S - 5, [b"y" * 10, {}, None])   # already expired
S._micro_put("k2", b"x" * 10, {})
ok("old" not in S._micro, "expired entries are dropped on put")
# byte cap: many near-max bodies must evict down under 16 MB and keep the newest
with S._micro_lock: S._micro.clear()
big = b"q" * 1_400_000
for i in range(40): S._micro_put("b%d" % i, big, {})
ok(S._micro_total() <= S.MICRO_TOTAL_MAX, f"byte total stays under the 16 MB cap ({S._micro_total()})")
ok("b39" in S._micro and "b0" not in S._micro, "oldest entries evicted, newest kept")
# entry cap still holds
with S._micro_lock: S._micro.clear()
for i in range(S.MICRO_MAX + 20): S._micro_put("e%d" % i, b"x" * 10, {})
ok(len(S._micro) <= S.MICRO_MAX, f"entry cap still holds ({len(S._micro)} <= {S.MICRO_MAX})")

# ---------------------------------------------------------------- 5a. IPv6 /64 limiter keying
v6a, v6b = "2606:4700:1:2:aaaa:bbbb:cccc:dddd", "2606:4700:1:2:0000:1111:2222:3333"   # same /64
v6c = "2606:4700:9:9:aaaa:bbbb:cccc:dddd"   # different /64
ok(CIP.limiter_key(v6a) == CIP.limiter_key(v6b), "two IPv6 addresses in one /64 share a limiter key")
ok(CIP.limiter_key(v6a) != CIP.limiter_key(v6c), "a different /64 is a different key")
ok(CIP.limiter_key(v6a).endswith("/64"), "the IPv6 key is a /64 network")
ok(CIP.limiter_key("198.51.100.7") == "198.51.100.7", "IPv4 keeps its full address")
ok(CIP.limiter_key("not-an-ip") == "not-an-ip", "a non-address is returned unchanged (local runs)")

# ---------------------------------------------------------------- 5b. Limiter bounded eviction
lim = AG.Limiter(rate=1.0, burst=5)
for i in range(lim.CAP + 10): lim.b["ip%d" % i] = (5.0, time.time())   # fill past the cap, oldest first
before = len(lim.b)
lim.allow("fresh")   # triggers one bounded eviction
ok(len(lim.b) == before - lim.EVICT + 1, f"over cap, allow() drops a bounded slice of EVICT, not the whole dict ({before} -> {len(lim.b)})")
ok("ip0" not in lim.b and "ip%d" % (lim.CAP + 9) in lim.b, "the oldest keys are evicted, recent ones kept")
o1, w1 = lim.allow("newip"); ok(o1 is True and w1 == 0, "a fresh IP still gets its burst (behaviour otherwise identical)")
for _ in range(5): lim.allow("newip")
o2, w2 = lim.allow("newip"); ok(o2 is False and w2 >= 1, "an IP over its burst is still refused with a wait")

# ---------------------------------------------------------------- 3. HTTP: unknown /address 404 is edge-cacheable; a crawler probe reads no upstream; other errors no-store
class _Count(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self): _hits[0] += 1; self.send_response(503); self.send_header("Content-Length", "0"); self.end_headers()
    def do_HEAD(self): self.do_GET()
_hits = [0]
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
up_port = free_port(); up = http.server.ThreadingHTTPServer(("127.0.0.1", up_port), _Count)
threading.Thread(target=up.serve_forever, daemon=True).start()

def req(base, path, hd=None):
    try:
        r = urllib.request.urlopen(urllib.request.Request(base + path, headers=hd or {}), timeout=30); return r.status, r.headers
    except urllib.error.HTTPError as e: return e.code, e.headers

port = free_port(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "http.db"),
           POASCAN_INDEXER="0", POA_BASE=f"http://127.0.0.1:{up_port}")
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(150):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    UA = "poa1" + "W" * 40
    c1, h1 = req(base, "/address/" + UA)
    ok(c1 == 404, f"unknown /address is a 404 ({c1})")
    ok(h1.get("Cache-Control") == "public, max-age=60, s-maxage=300", f"unknown /address 404 is edge-cacheable ({h1.get('Cache-Control')!r})")
    # a crawler's probe (the real flood) reads the archive only, so it spends no on-demand minepoa budget
    _hits[0] = 0
    cc, _ = req(base, "/address/poa1" + "Y" * 40, {"User-Agent": "GPTBot/1.0 (+https://openai.com/gptbot)"})
    ok(cc == 404 and _hits[0] == 0, f"a crawler's unknown-address probe 404s with no upstream read ({cc}, {_hits[0]} upstream hits)")
    cg, hg = req(base, "/nope-not-a-page")
    ok(cg == 404 and hg.get("Cache-Control") == "no-store", f"a generic 404 stays no-store ({cg}, {hg.get('Cache-Control')!r})")
    cm, hm = req(base, "/address/poa1$$$")   # malformed address: not cacheable
    ok(hm.get("Cache-Control") == "no-store", f"a malformed address 404 stays no-store ({cm}, {hm.get('Cache-Control')!r})")
finally:
    p.terminate(); p.wait(10); up.shutdown()

ok(not any(chr(0x2013) in l or chr(0x2014) in l for l in open(__file__, encoding="utf-8")), "no em or en dash in this test")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED"); sys.exit(1 if fails else 0)
