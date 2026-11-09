"""Swap offer resilience to an upstream minepoa.com read-shed (1.26.283). Two POAScan-side fixes, both correctness-first,
both local (no upstream read in the test):
 1. created_ts fallback: an offer first learned from the book (apply_book) has a null created_ts until the offer's own
    swap-offer detail is read, which has been shed since Nov 4. POAScan already holds the creation time in its core txs
    table (txs.ts), so backfill_offer_fields backfills created_ts from the offer's OWN swap-offer tx (exact id match), and
    never from any other tx. An offer with no matching swap-offer tx stays null (never guessed). memo is left for the body.
 2. fast-index cancel resolve: a final swap-cancel is read from the fast index / stored cache (node=False), never the shed
    minepoa.com per-tx read, so it resolves its offer to cancelled from body.offer without the shed read. A non-final
    swap-cancel does not change the offer.
Usage: python3 tools/swap_resilience_test.py (temp database, no network)."""
import os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "s.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
os.environ["POASCAN_INDEXER"] = "0"; os.environ["POASCAN_SWAP_EVIDENCE"] = ""
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import db, indexer as I
import importlib
SWI = importlib.import_module("poascan.swap.indexer")
SH = importlib.import_module("poascan.swap.host")
db.init()
def no_upstream(*a, **k): raise AssertionError("upstream read")
I.fetch = no_upstream   # any plain minepoa.com read is a test failure

NOW = int(time.time())
OID = lambda c: c * 8   # short offer ids
def put_offer(oid, **cols):
    base = dict(offer_id=oid, maker="poa1" + "A" * 40, poa=1000.0, chain="SOL", asset="USDC", want=100.0,
                status="open", created_ts=None, expires_ts=NOW + 3600, last_open_seen=NOW, updated=NOW)
    base.update(cols); keys = list(base)
    db.write(f"INSERT OR REPLACE INTO swaps({','.join(keys)}) VALUES({','.join('?' * len(keys))})", tuple(base[k] for k in keys))
def put_tx(tid, typ, ts, final=0, atts=0):
    db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,ts,atts,k,final) VALUES(?,?,?,?,?,?,?)", (tid, typ, "poa1" + "A" * 40, ts, atts, 5, final))
def swap_row(oid): return db.q1("SELECT * FROM swaps WHERE offer_id=?", (oid,))

# ---- Fix 1: created_ts backfilled only from the offer's OWN swap-offer tx ----
A, B, C = OID("a"), OID("b"), OID("c")
put_offer(A, created_ts=None)                       # has a matching swap-offer tx
put_tx(A, "swap-offer", NOW - 5000, final=1, atts=5)
put_offer(B, created_ts=None)                       # a tx with the same id but the wrong type: must NOT be used
put_tx(B, "transfer", NOW - 4000, final=1, atts=5)
put_offer(C, created_ts=None)                       # no tx at all
SWI.backfill_offer_fields(NOW)
check("created_ts backfilled from the offer's own swap-offer tx (txs.ts)", swap_row(A)["created_ts"] == NOW - 5000)
check("never guessed: a same-id tx of another type does not backfill created_ts", swap_row(B)["created_ts"] is None)
check("never guessed: an offer with no swap-offer tx stays null", swap_row(C)["created_ts"] is None)
check("backfill leaves memo for the real body read (not taken from txs)", swap_row(A)["memo"] is None)
D = OID("d")                                        # an offer that already has a created_ts is left untouched
put_offer(D, created_ts=NOW - 10); put_tx(D, "swap-offer", NOW - 9999, final=1, atts=5)
SWI.backfill_offer_fields(NOW)
check("an offer that already has created_ts is not overwritten", swap_row(D)["created_ts"] == NOW - 10)

# ---- Fix 2: a final swap-cancel resolves the offer from the fast index, never the shed minepoa.com read ----
# The fake get_tx_detail serves the signed cancel body only on the fast-index path (node=False); the minepoa.com path
# (node=True) raises Shed, as it has in production since Nov 4. So a resolve that depends on the shed read would not happen.
SH.fast_index_up = lambda: True
calls = []
def fake_detail(tid, allow_fetch=True, bg=None, node=True):
    calls.append((tid, node))
    if not node:   # fast index / stored cache
        body = BODIES.get(tid)
        if body is None: raise SH.Busy("not indexed yet")
        return body
    raise SH.Shed("HTTP 503 shed: origin busy", 3000)   # minepoa.com per-tx read is shed
SH.get_tx_detail = fake_detail

EXP = OID("e")   # an expired offer whose maker cancels after expiry: the cancel must still record, status cancelled
put_offer(EXP, status="expired", created_ts=NOW - 7200, expires_ts=NOW - 3600)
CANCEL = "ca" * 32
put_tx(CANCEL, "swap-cancel", NOW - 60, final=1, atts=5)   # the core feed (fast-index sync) already marks it final
BODIES = {CANCEL: {"id": CANCEL, "type": "swap-cancel", "from_addr": "poa1" + "A" * 40, "ts": NOW - 60, "final": True, "body": {"offer": EXP}}}

NF = OID("f")   # a non-final swap-cancel: must not change the offer
put_offer(NF, status="expired", created_ts=NOW - 7200, expires_ts=NOW - 3600)
NFCANCEL = "cf" * 32
put_tx(NFCANCEL, "swap-cancel", NOW - 50, final=0, atts=1)   # not final on the ledger

SWI.ingest_events(NOW)
e = swap_row(EXP)
check("a final swap-cancel resolves the offer to cancelled from body.offer", e["status"] == "cancelled")
check("cancelled with the right cancel txid and ledger ts", e["cancel_txid"] == CANCEL and e["cancel_ts"] == NOW - 60)
check("the cancel was read on the fast-index path (node=False), never the shed minepoa.com read",
      (CANCEL, False) in calls and (CANCEL, True) not in calls)
check("a non-final swap-cancel leaves the offer unchanged (still expired)", swap_row(NF)["status"] == "expired")
# the cancel after expiry still carries the real cancel time, later than expiry (api layer reads cancelled_after_expiry)
check("cancel-after-expiry keeps the real cancel ts, later than the expiry", e["cancel_ts"] > e["expires_ts"])

print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
