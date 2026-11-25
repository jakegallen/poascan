"""1.26.429: the swap book adopts upstream per-offer state=expired, and still expires a listed open offer once
expires_ts has passed. A missing state field keeps the clock-only rule. No network, no DB.
Usage: python3 tools/swapstate_test.py"""
import os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan.swap import indexer as IX

NOW = 1_000_000
SOON = NOW + 3600
PAST = NOW - 3600

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

check("state=expired is expired even when expires_ts is still in the future",
      IX._book_status(SOON, NOW, "expired") == "expired")
check("state=expired and expires_ts already past is expired",
      IX._book_status(PAST, NOW, "expired") == "expired")
check("state=open stays open before expiry",
      IX._book_status(SOON, NOW, "open") == "open")
check("state=open is expired once expires_ts has passed",
      IX._book_status(PAST, NOW, "open") == "expired")
check("state=held follows expires_ts (open before expiry)",
      IX._book_status(SOON, NOW, "held") == "open")
check("a row with no state field uses expires_ts only",
      IX._book_status(SOON, NOW) == "open" and IX._book_status(PAST, NOW) == "expired" and IX._book_status(SOON, NOW, None) == "open")
check("no expires_ts and no state is open",
      IX._book_status(None, NOW) == "open" and IX._book_status(None, NOW, "open") == "open")
check("no expires_ts with state=expired is expired",
      IX._book_status(None, NOW, "expired") == "expired")
mod = open(os.path.join(ROOT, "poascan/swap/indexer.py"), encoding="utf-8").read()
check("no em or en dash in the module", chr(0x2013) not in mod and chr(0x2014) not in mod)

print("FAILED: " + "; ".join(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
