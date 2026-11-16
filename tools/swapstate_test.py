"""1.26.348 (#1214): the swap indexer tolerates upstream's new per-offer 'state' field (open, held, expired) as a
pass-through no-op, and _state_mismatch flags the one disagreement worth watching (upstream state=expired while our
derived book status still reads open) for an ops-only log, without changing what we store or show. No network, no DB.
Usage: python3 tools/swapstate_test.py"""
import os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan.swap import indexer as IX

NOW = 1_000_000
SOON = NOW + 3600     # not yet expired by our clock -> our status is open
PAST = NOW - 3600     # expired by our clock -> our status is expired

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# the one watched disagreement: upstream says expired, our clock still says open
check("state=expired while our status is open is flagged as (expired, open)",
      IX._state_mismatch({"offer_id": "a", "state": "expired", "expires_ts": SOON}, NOW) == ("expired", "open"))

# no disagreement to flag: our clock agrees it is expired
check("state=expired and already past expires_ts is not flagged (we agree it is expired)",
      IX._state_mismatch({"offer_id": "a", "state": "expired", "expires_ts": PAST}, NOW) is None)

# only expired-vs-open is watched; other upstream states are left alone
check("state=open is not a mismatch", IX._state_mismatch({"offer_id": "a", "state": "open", "expires_ts": SOON}, NOW) is None)
check("state=held is not a mismatch (watched signal is expired-vs-open only)",
      IX._state_mismatch({"offer_id": "a", "state": "held", "expires_ts": SOON}, NOW) is None)

# pass-through no-op: a row without the field (the array is still bare upstream) never flags, and never raises
check("a row with no state field is a pass-through no-op (None, no raise)",
      IX._state_mismatch({"offer_id": "a", "expires_ts": SOON}, NOW) is None)
check("a bare row with no state and no expires_ts is a no-op", IX._state_mismatch({"offer_id": "a"}, NOW) is None)

# the field does not perturb the derived book status: _book_status ignores 'state' entirely (status stays our own)
check("_book_status is unchanged by the presence of a state field (we derive status, upstream state never overrides)",
      IX._book_status(SOON, NOW) == "open" and IX._book_status(PAST, NOW) == "expired")

check("no em or en dash in the module or this test",
      not any(c in open(os.path.join(ROOT, f), encoding="utf-8").read() for f in ("poascan/swap/indexer.py", "tools/swapstate_test.py") for c in "\u2013\u2014"))

print("FAILED: " + "; ".join(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
