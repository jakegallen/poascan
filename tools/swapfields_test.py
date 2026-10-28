"""Swap API additions for POASwap (1.26.201): expired_at, cancelled_at and cancelled_after_expiry, present only where they
apply; /api/v1/swaps?status= (live is open) and include_expired=1 as opt-in filters, the default list unchanged; bad
values are a 400. Pure functions plus the live API shape on the fixture. Usage: python3 tools/swapfields_test.py"""
import json, os, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "sf.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
from poascan import server as SV
import importlib; SA = importlib.import_module("poascan.swap.api")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

NOW = 1_793_200_000
def f(**r): SA._expiry_fields(r, NOW); return r
# the two offers POASwap asked about, as POAScan holds them
a = f(offer_id="690013f8", status="cancelled", expires_ts=1793109563, cancel_ts=1793154031)
check(f"690013f8: cancelled after expiry, both times given ({a.get('expired_at')}, {a.get('cancelled_at')})",
      a["cancelled_after_expiry"] is True and a["expired_at"] == "2026-10-27T13:59:23Z" and a["cancelled_at"] == "2026-10-28T02:20:31Z")
b = f(offer_id="eac69879", status="cancelled", expires_ts=1793123045, cancel_ts=1793138856)
check("eac69879: cancelled after expiry", b["cancelled_after_expiry"] is True and b["expired_at"] and b["cancelled_at"] == "2026-10-27T22:07:36Z")
c = f(status="cancelled", expires_ts=NOW + 3600, cancel_ts=NOW - 60)
check("cancel before expiry: cancelled_after_expiry false, no expired_at", c["cancelled_after_expiry"] is False and "expired_at" not in c)
d = f(status="filled", expires_ts=NOW - 100, fill_ts=NOW - 5000)
check("fill before expiry: no expiry fields", not any(k in d for k in ("expired_at", "cancelled_at", "cancelled_after_expiry")))
e = f(status="expired", expires_ts=NOW - 100)
check("expired: expired_at only", "expired_at" in e and "cancelled_at" not in e and "cancelled_after_expiry" not in e)
o = f(status="open", expires_ts=NOW + 100)
check("open: no expiry fields (never null placeholders)", not any(k in o for k in ("expired_at", "cancelled_at", "cancelled_after_expiry")))
check("delisted: no expired_at", "expired_at" not in f(status="delisted", expires_ts=NOW - 100))

rows = [dict(status=s) for s in ("open", "open", "expired", "cancelled", "filled", "refunded")]
q = lambda **k: {a: [b] for a, b in k.items()}
check("status=live is open only", [r["status"] for r in SV.swap_filter(rows, q(status="live"))] == ["open", "open"])
check("status=live&include_expired=1 adds expired", {r["status"] for r in SV.swap_filter(rows, q(status="live", include_expired="1"))} == {"open", "expired"})
check("status=filled,cancelled", {r["status"] for r in SV.swap_filter(rows, q(status="filled,cancelled"))} == {"filled", "cancelled"})
check("include_expired alone changes nothing", SV.swap_filter(rows, q(include_expired="1")) == rows)
for bad in (q(status="nope"), q(status="live", include_expired="maybe")):
    try: SV.swap_filter(rows, bad); check(f"bad value {bad} is a 400", False)
    except SV.BadRequest: check(f"bad value {bad} is a 400", True)
from poascan import agentapi as AG
sp = AG.openapi()["paths"]; op = next(v for k, v in sp.items() if k.endswith("/swaps"))["get"]
props = AG.SWAP_ROW["properties"]
check("OpenAPI: status and include_expired params, the three fields, and why there is no dry_run or action_id",
      {p["name"] for p in op["parameters"]} >= {"status", "include_expired"} and {"expired_at", "cancelled_at", "cancelled_after_expiry"} <= set(props)
      and "dry_run" in op["description"] and "action_id" in op["description"])
print("\n%d failed" % len(fails) if fails else "\nall passed"); sys.exit(1 if fails else 0)
