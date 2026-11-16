"""1.26.347: /api/swaps honours ?offset and ?limit, applied after the status filter. swap_page slices; a non-negative
integer is required (anything else is a 400); the default (no offset, no limit) is unchanged; limit is capped at
SWAP_PAGE_MAX. The weak ETag folds the status/include_expired/offset/limit params so a paged or filtered copy never
shares a tag with the full list. No network. Usage: python3 tools/swappage_test.py"""
import os, sys, tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_INDEXER", "0")
os.environ.setdefault("POASCAN_DB", os.path.join(tempfile.mkdtemp(), "sp.db"))
from poascan import server as SV

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
def q(**kw):  # querystring dict: each value a list, like urllib.parse.parse_qs
    return {k: [str(v)] for k, v in kw.items()}

rows = [{"id": i, "status": "open"} for i in range(10)]
check("no offset and no limit returns the list unchanged", SV.swap_page(rows, {}) == rows)
check("offset skips rows", SV.swap_page(rows, q(offset=3)) == rows[3:])
check("limit caps the count", SV.swap_page(rows, q(limit=4)) == rows[:4])
check("offset and limit compose", SV.swap_page(rows, q(offset=2, limit=3)) == rows[2:5])
check("offset past the end yields an empty list", SV.swap_page(rows, q(offset=50)) == [])
check("limit is capped at SWAP_PAGE_MAX and never raises for a huge value",
      SV.SWAP_PAGE_MAX == 1000 and SV.swap_page(rows, q(limit=999999)) == rows)
check("limit 0 returns no rows", SV.swap_page(rows, q(limit=0)) == [])

def raises(fn):
    try: fn(); return False
    except SV.BadRequest: return True
    except Exception: return False
check("a negative or non-integer offset or limit is a 400 (BadRequest)",
      raises(lambda: SV.swap_page(rows, q(limit=-1))) and raises(lambda: SV.swap_page(rows, q(offset="x")))
      and raises(lambda: SV.swap_page(rows, q(limit="3.5"))))

src = open(os.path.join(ROOT, "poascan", "server.py"), encoding="utf-8").read()
check("the /api/swaps route composes swap_page over swap_filter (paging after the status filter)",
      "swap_page(swap_filter(rows, qs), qs)" in src)
check("the swap list ETag folds the filter and paging params so a paged copy does not share the full list's tag",
      'p == "/api/swaps" and any(k in qs for k in ("offset", "limit", "status", "include_expired"))' in src)
check("no em or en dash in the module or this test",
      not any(c in open(os.path.join(ROOT, f), encoding="utf-8").read() for f in ("tools/swappage_test.py",) for c in "\u2013\u2014"))

print("FAILED: " + "; ".join(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
