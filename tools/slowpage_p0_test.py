"""Slow-page P0 serving-path hardening (1.26.291). Six items, each proved here with no network:
  E1: grading._auth is memoized once per db generation (not per call); a write bumps db.GEN and recomputes once.
  S2: HEAVY_CAP honors POASCAN_HEAVY_CAP, clamped to [1, MAX_WORKERS]; unset keeps the derived value.
  A1: CANON_QS now covers the remaining static page routes, so a cache buster collapses to the canonical key.
  R2: a per-IP concurrency gate sheds a second concurrent heavy request from the same IP BEFORE it takes a heavy slot;
      a different IP is still admitted, and a request with no Fly address is never gated.
  A2: the API micro-cache key is canonical (order independent, empty values dropped, unknown keys off /api/txs dropped).
  A3: /api/txs rejects an over-cap offset and an unknown type before the query runs.
Run: python3 tools/slowpage_p0_test.py (temp db, in-process, no upstream calls)."""
import os, sys, tempfile, time

os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "slowpage.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_MAX_WORKERS"] = "4"
os.environ["POASCAN_SERVE_RESERVE"] = "2"
os.environ["POASCAN_HEAVY_WAIT"] = "0.3"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

from poascan import db, guard as GD, grading as GR, htmlcache as HC
import poascan.server as SV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

db.init()
HUMAN = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

# ---------------------------------------------------------------- E1: _auth memoized once per db generation
calls = [0]
def fake_compute():
    calls[0] += 1
    return (frozenset({"poa1A"}), 7)
_real_compute = GR._auth_compute
GR._auth_compute = fake_compute
GR._auth_clear()
try:
    g0 = db.GEN[0]
    vals = [GR._auth() for _ in range(50)]
    ok(calls[0] == 1, f"_auth computes once for a generation across 50 calls ({calls[0]})")
    ok(all(v == vals[0] for v in vals), "every call in a generation returns the same memoized value")
    db.write("INSERT OR REPLACE INTO labels(addr, label, source, ts) VALUES(?,?,?,?)", ("poa1" + "M" * 40, "x", "t", 0))
    ok(db.GEN[0] != g0, f"a db write bumped db.GEN ({g0} -> {db.GEN[0]})")
    for _ in range(10): GR._auth()
    ok(calls[0] == 2, f"a new generation recomputes exactly once ({calls[0]})")
    GR.EST_MEMO_S, before = 0, calls[0]
    for _ in range(5): GR._auth()
    ok(calls[0] == before + 5, f"POASCAN_EST_MEMO_S <= 0 turns the memo off (every call computes) ({calls[0]})")
finally:
    GR._auth_compute = _real_compute; GR.EST_MEMO_S = 20.0; GR._auth_clear()

# ---------------------------------------------------------------- S2: POASCAN_HEAVY_CAP override, clamped
base = GD.MAX_WORKERS - GD._reserve
old = os.environ.get("POASCAN_HEAVY_CAP")
try:
    os.environ.pop("POASCAN_HEAVY_CAP", None)
    ok(GD._heavy_cap() == base, f"unset: HEAVY_CAP is the derived value ({GD._heavy_cap()} == {base})")
    os.environ["POASCAN_HEAVY_CAP"] = "1"
    ok(GD._heavy_cap() == 1, f"POASCAN_HEAVY_CAP=1 is honored ({GD._heavy_cap()})")
    os.environ["POASCAN_HEAVY_CAP"] = "0"
    ok(GD._heavy_cap() == 1, f"a 0 override clamps up to 1 ({GD._heavy_cap()})")
    os.environ["POASCAN_HEAVY_CAP"] = str(GD.MAX_WORKERS + 9)
    ok(GD._heavy_cap() == GD.MAX_WORKERS, f"an over-max override clamps to MAX_WORKERS ({GD._heavy_cap()})")
    os.environ["POASCAN_HEAVY_CAP"] = "notanint"
    ok(GD._heavy_cap() == base, f"a non-integer override falls back to the derived value ({GD._heavy_cap()})")
finally:
    if old is None: os.environ.pop("POASCAN_HEAVY_CAP", None)
    else: os.environ["POASCAN_HEAVY_CAP"] = old

# ---------------------------------------------------------------- A1: CANON_QS covers the remaining page routes
for p in ("/index.html", "/join", "/onboarding", "/unlocks", "/upgrade", "/swaps", "/wallet"):
    ok(p in HC.CANON_QS, f"CANON_QS covers {p}")
ok(HC.canon_qs("/join", {"utm_source": ["x"], "nocache": ["1"]}) == {}, "a buster on /join drops to the canonical empty query")
ok(HC.canon_qs("/wallet", {"address": ["poa1AAA"], "ref": ["x"]}) == {"address": ["poa1AAA"]}, "/wallet keeps only ?address")
seg = 0
k_plain = HC.key("/unlocks", HC.canon_qs("/unlocks", {}), seg, False)
k_bust = HC.key("/unlocks", HC.canon_qs("/unlocks", {"x": ["1"]}), seg, False)
ok(k_plain == k_bust, "a /unlocks cache buster shares the canonical cache key (one render, one slot)")

# ---------------------------------------------------------------- R2: per-IP concurrency gate before the heavy slot
class Req(SV.H):
    def __init__(self, path, ip=None):
        self.path = path; self.command = "GET"; self.sent = []
        self.headers = {"User-Agent": HUMAN}
        if ip: self.headers["Fly-Client-IP"] = ip
    def send(self, code, *a, **k):
        self.sent.append(code); return code

def slots_value():
    try:
        with GD.slots._cond: return GD.slots._value
    except Exception: return None

# unit level
ok(GD.ip_heavy_acquire(None) is True, "a falsy ip (no Fly address) is always admitted")
GD.ip_heavy_release(None)   # no-op, must not raise
GD._ip_heavy.clear(); GD.IP_HEAVY_MAX = 2
ok(GD.ip_heavy_acquire("9.9.9.9") and GD.ip_heavy_acquire("9.9.9.9"), "two heavy requests from one ip are admitted at max 2")
ok(GD.ip_heavy_acquire("9.9.9.9") is False, "a third concurrent heavy request from the same ip is refused")
GD.ip_heavy_release("9.9.9.9")
ok(GD.ip_heavy_acquire("9.9.9.9") is True, "a release frees one in-flight slot for that ip")
GD._ip_heavy.clear()

# through _gated on a heavy scrape API route (address txs; the 1.26.319 light /api/v1/address path does not shed):
# the second concurrent request from one ip sheds before a slot
GD.IP_HEAVY_MAX = 1; GD._ip_heavy.clear()
ADDR = "/api/v1/address/poa1" + "D" * 40 + "/txs"
cap_before = slots_value()
ok(GD.ip_heavy_acquire("1.2.3.4") is True, "first request from the ip is in flight (reserved)")
ran = []
r2 = Req(ADDR, ip="1.2.3.4")
r2._gated(lambda: (ran.append(1), "SERVED")[1])
ok(r2.sent == [503] and not ran, f"a second concurrent heavy request from the same ip sheds 503 without running ({r2.sent}, ran={ran})")
ok(slots_value() == cap_before, f"the shed took no heavy slot ({slots_value()} == {cap_before})")
# a different ip is admitted and served
ran2 = []
rB = Req(ADDR, ip="5.6.7.8")
rB._gated(lambda: (ran2.append(1), "OK")[1])
ok(ran2 == [1] and not rB.sent, f"a different ip is admitted and served ({ran2}, {rB.sent})")
ok(slots_value() == cap_before, "the served request released its heavy slot")
# a request with no Fly address is never gated even while the ip is at cap
ran3 = []
rN = Req(ADDR)   # no Fly-Client-IP
rN._gated(lambda: (ran3.append(1), "OK")[1])
ok(ran3 == [1] and not rN.sent, f"a request with no Fly address is never per-IP gated ({ran3}, {rN.sent})")
GD.ip_heavy_release("1.2.3.4"); GD._ip_heavy.clear(); GD.IP_HEAVY_MAX = 2

# ---------------------------------------------------------------- A2: canonical API micro-cache key
ck = SV._micro_ck
ok(ck("/api/foo", {"a": ["1"], "b": ["2"]}) == ck("/api/foo", {"b": ["2"], "a": ["1"]}), "micro key is order independent")
ok(ck("/api/foo", {"a": ["1"], "z": []}) == ck("/api/foo", {"a": ["1"]}), "an empty-list value is dropped from the micro key")
ok(ck("/api/txs", {"limit": ["5"], "nocache": ["1"]}) == ck("/api/txs", {"limit": ["5"]}), "an unknown key off /api/txs is dropped (a buster shares the entry)")
ok(ck("/api/txs", {"limit": ["5"], "offset": ["10"]}) != ck("/api/txs", {"limit": ["5"]}), "a real /api/txs parameter still keys apart")

# ---------------------------------------------------------------- A3: /api/txs offset cap and type whitelist
def txs(qs):
    try:
        SV.api("/api/txs", qs); return None
    except SV.BadRequest as e:
        return str(e)
ok(txs({"offset": [str(SV.OFFSET_MAX + 1)]}) is not None, "an over-cap offset is a 400, not a silent clamp or a deep scan")
ok(txs({"offset": [str(SV.OFFSET_MAX)]}) is None, "an offset at the cap is accepted")
ok(txs({"type": ["grade-sealed"]}) is None, "a well-formed tx type token is accepted")
ok(txs({"type": ["DROP TABLE"]}) is not None, "an unknown/junk type is a 400 before the query")
ok(txs({"type": ["UPPER"]}) is not None, "an upper-case type (not a real token) is a 400")

# ---------------------------------------------------------------- no em or en dash anywhere in this test
ok(not any(chr(0x2013) in ln or chr(0x2014) in ln for ln in open(__file__, encoding="utf-8")), "no em or en dash in this test")

print("\nall ok" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
