""" /api/v1/txs micro-cache hits skip the heavy slot (1.26.315).

The default first-page list, and any other identical query already in the micro cache, is served without taking
a heavy-work slot, the same way /api/summary and /api/swaps/status are exempt. Cache-Control is TXS_CDN. The
default key is filled by warm_txs_micro() at boot. Response bytes and shape are the usual JSON list.

Run: python3 tools/txs_micro_test.py (temp db, in-process, no network)."""
import json, os, sys, tempfile, time, urllib.error, urllib.request

os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "txs_micro.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_MAX_WORKERS"] = "1"
os.environ["POASCAN_HEAVY_WAIT"] = "0.3"
os.environ["POA_BASE"] = "http://127.0.0.1:9"

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

from poascan import db, guard as GD
import poascan.server as SV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

db.init()
now = int(time.time())
rows = [("t%02d" % i, "transfer", "poa1" + ("A" if i % 2 == 0 else "B") * 40, now - (20 - i)) for i in range(8)]
for tid, typ, addr, ts in rows:
    db.write("INSERT INTO txs(id, type, from_addr, ts) VALUES(?, ?, ?, ?)", (tid, typ, addr, ts))

TXS_CDN = "public, max-age=15, s-maxage=30, stale-while-revalidate=15, stale-if-error=60"
ok(SV.H.TXS_CDN == TXS_CDN, "TXS_CDN is the agreed Cache-Control")

class Stub(SV.H):
    def __init__(self, path, command="GET"):
        self.path = path; self.command = command; self.headers = {}; self.sent = []
    def send(self, code, *a, **k): self.sent.append(code); return code

# ---------------------------------------------------------------- 1. classification
ok(Stub("/api/v1/txs")._txs_micro_parts()[0] == "/api/txs", "/api/v1/txs is the txs list")
ok(Stub("/api/txs")._txs_micro_parts()[0] == "/api/txs", "/api/txs is the same list")
ok(Stub("/api/v1/txs?limit=5")._txs_micro_parts()[0] == "/api/txs", "a limit query is still the txs list")
ok(Stub("/api/v1/txs.csv")._txs_micro_parts() is None, "CSV is not a JSON micro-cache hit")
ok(Stub("/api/v1/summary")._txs_micro_parts() is None, "/api/v1/summary is not the txs list")
ok(Stub("/api/v1/txs", "POST")._txs_micro_parts() is None, "POST is not a micro-cache hit")
ok(Stub("/api/v1/txs")._txs_micro_hit() is False, "a cold default key is not a hit")

# ---------------------------------------------------------------- 2. warm fills the default key; body matches a live build
ck, body, hd = SV.warm_txs_micro()
ok(ck[0] == "/api/txs" and ck[2] == "json", f"warm key is the default JSON list ({ck[0]}, {ck[2]})")
ok(isinstance(body, (bytes, bytearray)) and body[:1] == b"[", "warm body is a JSON list")
live = json.loads(body)
ok(isinstance(live, list) and len(live) == 8 and live[0]["id"] == "t07" and live[-1]["id"] == "t00",
   f"warm body is the newest-first default page ({len(live)} rows, first={live[0].get('id') if live else None})")
direct, is_list = SV.api("/api/txs", {})
ok(is_list is True and [r["id"] for r in direct] == [r["id"] for r in live],
   "warm body shape and row ids match api() for the default query")
ok(hd.get("Cache-Control") == TXS_CDN and hd.get("Access-Control-Allow-Origin") == "*",
   f"warm headers use TXS_CDN ({hd.get('Cache-Control')!r})")
ok(Stub("/api/v1/txs")._txs_micro_hit() is True, "after warm, the default /api/v1/txs is a hit")
ok(Stub("/api/txs")._txs_micro_hit() is True, "after warm, /api/txs is the same hit")
ok(Stub("/api/v1/txs?limit=3")._txs_micro_hit() is False, "a different query is still cold")

# ---------------------------------------------------------------- 3. a hit is served while every heavy slot is held
got = GD.slots.acquire(timeout=1)
ok(got, "test acquired the single heavy slot")

def ran_ok(path):
    called = []
    t0 = time.time()
    r = Stub(path)._gated(lambda: (called.append(1), "SERVED")[1])
    dt = time.time() - t0
    return called == [1] and r == "SERVED", dt, called

hit, dt, called = ran_ok("/api/v1/txs")
ok(hit, f"default /api/v1/txs served while the heavy slot is held (fn ran={called})")
ok(dt < 0.2, f"the hit answered immediately, did not wait for a slot ({dt*1000:.0f} ms)")
hit, dt, called = ran_ok("/api/txs")
ok(hit and dt < 0.2, f"/api/txs is the same slot-exempt hit ({dt*1000:.0f} ms)")

# a cold txs query still sheds
cold = Stub("/api/v1/txs?limit=3"); ran = []
t0 = time.time()
cold._gated(lambda: (ran.append(1), "RENDER")[1])
dt = time.time() - t0
ok(cold.sent == [503] and not ran, f"a cold ?limit=3 sheds with 503 when no slot is free (sent={cold.sent}, ran={bool(ran)})")
ok(0.25 <= dt < 1.5, f"it shed after about HEAVY_WAIT ({dt*1000:.0f} ms)")

# another API path is still gated
other = Stub("/api/v1/epochs"); ran = []
other._gated(lambda: (ran.append(1), "RENDER")[1])
ok(other.sent == [503] and not ran, "a different API path still takes a slot and sheds")

GD.slots.release()

# ---------------------------------------------------------------- 4. filling an identical-query key, then a hit skips the slot
ran = []
ok(Stub("/api/v1/txs?limit=3")._gated(lambda: (ran.append(1), "OK")[1]) == "OK" and ran == [1],
   "a cold ?limit=3 runs once a slot is free")
# Put that key in the cache the way _get would, then hold the slot and check the hit path.
data, _ = SV.api("/api/txs", {"limit": ["3"]})
b = SV.H.prep(json.dumps(data, default=str), "application/json")
ck3 = ("/api/txs", SV._micro_ck("/api/txs", {"limit": ["3"]}), "json", Stub("/api/v1/txs?limit=3")._txs_micro_parts()[3], False)
SV._micro_put(ck3, b, {"Cache-Control": TXS_CDN, "Access-Control-Allow-Origin": "*"})
ok(Stub("/api/v1/txs?limit=3")._txs_micro_hit() is True, "the identical ?limit=3 query is now a hit")

got = GD.slots.acquire(timeout=1); ok(got, "test re-acquired the single heavy slot")
hit, dt, called = ran_ok("/api/v1/txs?limit=3")
ok(hit and dt < 0.2, f"an identical-query hit is slot-exempt ({dt*1000:.0f} ms)")
cold = Stub("/api/v1/txs?limit=4"); ran = []
cold._gated(lambda: (ran.append(1), "RENDER")[1])
ok(cold.sent == [503] and not ran, "a different limit still sheds while the slot is held")
GD.slots.release()

# ---------------------------------------------------------------- 5. live HTTP: header and bytes through the server
import threading
srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()

def get(path):
    rq = urllib.request.Request(base + path)
    try:
        r = urllib.request.urlopen(rq, timeout=3)
        return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)

# slot held: default list still 200 from the warm copy
held = GD.slots.acquire(timeout=1)
ok(held, "held the heavy slot for the HTTP check")
code, raw, headers = get("/api/v1/txs")
ok(code == 200, f"HTTP default list is 200 while the slot is held ({code})")
ok((headers.get("Cache-Control") or headers.get("cache-control")) == TXS_CDN,
   f"HTTP Cache-Control is TXS_CDN ({headers.get('Cache-Control') or headers.get('cache-control')!r})")
ok(raw == body, "HTTP body bytes match the warm default key (shape unchanged)")
code2, raw2, _ = get("/api/v1/txs?limit=3")
ok(code2 == 200 and json.loads(raw2) == json.loads(b),
   "HTTP identical ?limit=3 is 200 from the micro cache while the slot is held")
code3, _, _ = get("/api/v1/txs?limit=4")
ok(code3 == 503, f"HTTP cold ?limit=4 is 503 while the slot is held ({code3})")
GD.slots.release()
srv.shutdown()

ok(not any(chr(0x2013) in ln or chr(0x2014) in ln for ln in open(__file__, encoding="utf-8")), "no em or en dash in this test")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
