"""Unofficial Apps OG cards (/apps/og/atp20/<tick>, /apps/og/atp721/<col>). Seeds a token and a
collection, then checks the OG route matching and that a PNG (or the generic fallback) is produced.
No upstream reads. Usage: python3 tools/apps_og_test.py"""
import os, sys, tempfile, copy
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, og as OG, indexer as IX

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()

DEP = "poa1DLtfHN8rajwqj7VdDHYLQ8MFwJGguXww6XU1tn7KNRVg"
A1 = "poa1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

def tid(n):
    return format(n, "064x")

def row(i, memo, fr, to=None, ts=1795179000, final=1):
    return dict(id=tid(i) if isinstance(i, int) else i, type="transfer", from_addr=fr,
                to_addr=to if to is not None else fr, amount="0.000001", memo=memo, ts=ts, final=final)

def load(*rows):
    IX.upsert_txs([copy.deepcopy(r) for r in rows], "test")

load(row(1, "ATP-20|d|SEAL|21000000|0||open:1000:50", DEP, ts=1795180000),
     row(2, "ATP-20|m|SEAL|1000", A1, ts=1795180100))
load(row(10, f"ATP-721|d|SEALERS|{'f'*64}|image/png|3333|111|MAM|20|50|The Sealers", DEP, ts=1795180200),
     row(11, "ATP-721|m|SEALERS|1", A1, ts=1795180300))

check("APPS_ROUTE matches an atp20 card path with and without .png",
      bool(OG.APPS_ROUTE.match("/apps/og/atp20/SEAL")) and bool(OG.APPS_ROUTE.match("/apps/og/atp20/SEAL.png")))
check("APPS_ROUTE matches an atp721 card path", bool(OG.APPS_ROUTE.match("/apps/og/atp721/SEALERS")))
check("APPS_ROUTE ignores an unrelated path", OG.APPS_ROUTE.match("/apps/og/nope/x") is None)

def is_png(b):
    return isinstance(b, (bytes, bytearray)) and b[:8] == b"\x89PNG\r\n\x1a\n"

r20 = OG.render("/apps/og/atp20/SEAL")
check("atp20 card renders a PNG with a cache age", r20 is not None and is_png(r20[0]) and r20[1] > 0)
r721 = OG.render("/apps/og/atp721/SEALERS")
check("atp721 card renders a PNG", r721 is not None and is_png(r721[0]))
# a known-but-undeployed tick still renders a card (Unknown tick), not a crash
rzz = OG.render("/apps/og/atp20/ZZZ")
check("unknown tick still yields a PNG card", rzz is not None and is_png(rzz[0]))
# a key that fails the shape check returns None so the server can fall back to the generic card
check("a malformed tick returns None (server serves the generic card)",
      OG.render("/apps/og/atp20/not-a-tick") is None)
check("a non-apps-og path is still None", OG.render("/apps/whatever") is None)

print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
