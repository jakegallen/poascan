#!/usr/bin/env python3
"""The /api/params mirror is reliable and complete.

Two defects were reported: /api/params intermittently returned 503 (it took a heavy-work slot, so an API storm shed it),
and /api/v1/params returned 200 without seal_load_frozen_from_epoch.

This covers the fix: the mirror serves the hourly "params" blob POAScan already holds (minus swap_fee*) with a last-good
in-memory fallback, it is slot-exempt (served with the heavy pool full, never 503 under load), and /api/params and its
/api/v1 alias resolve to one route that forwards every upstream key, the emission set (seal_load_frozen_from_epoch,
emission_ceiling, emission_carry_from_epoch) included.

Run: python3 tools/params_mirror_test.py (in-process, no network; a temp db for the module import)."""
import os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "p.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9",
                  POASCAN_MAINTENANCE="0", POASCAN_MAX_WORKERS="1", POASCAN_HEAVY_WAIT="0.3")
from poascan import db, guard as GD
import poascan.server as S
db.init()

fails = []
def ok(c, m): print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

# A params blob shaped like minepoa's: the emission keys present, two swap_fee* keys that the mirror drops.
UP = {"auto_epoch_seconds": 21600, "vesting_epochs": 100, "pending_ttl_epochs": 16,
      "emission_ceiling": "1000000", "emission_carry_from_epoch": 44, "seal_load_frozen_from_epoch": 71,
      "swap_fee_bps": 50, "swap_fee_min": "1"}
db.put_blob("params", UP)

# ---------------------------------------------------------------- 1. the body forwards the emission keys, drops swap_fee*
d = S._params_mirror()
ok(d.get("seal_load_frozen_from_epoch") == 71, "mirror includes seal_load_frozen_from_epoch=71 (not dropped, not fabricated)")
for k in ("emission_ceiling", "emission_carry_from_epoch"):
    ok(k in d, f"mirror includes the emission key {k}")
ok(not any(str(k).startswith("swap_fee") for k in d), "mirror drops the swap_fee* keys")
ok(d.get("pending_ttl_epochs") == 16 and d.get("auto_epoch_seconds") == 21600, "every other upstream key passes straight through")

# ---------------------------------------------------------------- 2. /api/params and /api/v1/params are one route, same bytes
a = S.api("/api/params", {})[0]
ok(a.get("seal_load_frozen_from_epoch") == 71, "api(/api/params) carries seal_load_frozen_from_epoch")
# /api/v1/params is rewritten to /api/params in _get before api() runs; _norm proves both classify as the same route.
class Stub(S.H):
    def __init__(self, path): self.path = path; self.sent = []; self.command = "GET"; self.headers = {}
    def send(self, code, *a, **k): self.sent.append(code); return code
ok(Stub("/api/v1/params")._norm() == "/api/params" == Stub("/api/params")._norm(),
   "/api/v1/params and /api/params normalize to the one route (identical bytes, emission keys included)")

# ---------------------------------------------------------------- 3. slot-exempt: no 503 under load
for p in ("/api/params", "/api/params/", "/api/v1/params"):
    ok(Stub(p)._is_params() is True, f"{p} is classified as the params mirror (slot-exempt)")
ok(Stub("/api/status")._is_params() is False, "/api/status is not the params mirror (still gated)")

got = GD.slots.acquire(timeout=1); ok(got, "test holds the only heavy slot (an API storm in flight)")
for p in ("/api/params", "/api/v1/params"):
    called = []; t0 = time.time()
    r = Stub(p)._gated(lambda: (called.append(1), "SERVED")[1]); dt = time.time() - t0
    ok(called == [1] and r == "SERVED", f"{p} served with every heavy slot held (no 503)")
    ok(dt < 0.2, f"{p} answered immediately, did not wait for a slot ({dt*1000:.0f} ms)")
# a normal API path still sheds when no slot is free (the exemption is params-only)
gated = Stub("/api/status"); ran = []
gated._gated(lambda: (ran.append(1), "RENDER")[1])
ok(gated.sent == [503] and not ran, f"a non-exempt API path still sheds 503 under load (sent={gated.sent})")
GD.slots.release()

# ---------------------------------------------------------------- 4. last-good: an empty blob read serves the previous copy
db.put_blob("params", {})
d2 = S._params_mirror()
ok(d2.get("seal_load_frozen_from_epoch") == 71, "an empty blob read still serves the last-good copy (mirror never goes blank)")

ok(not any(c in (S._params_mirror.__doc__ or "") + (S.H._is_params.__doc__ or "") for c in "\u2014\u2013"), "no em or en dash in the new copy")

print(("\nFAILED: " + ", ".join(fails)) if fails else "\nall passed")
sys.exit(1 if fails else 0)
