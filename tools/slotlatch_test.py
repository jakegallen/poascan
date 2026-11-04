"""Slot latch pins (1.26.263): /api/params slot_latch_overrides (minepoa v0.84) pins nonce slots to a fixed winner. The
winner is tagged Pinned, a twin on the same author and nonce Superseded with the winner linked; twins are left out of the
sent and type counts and their seals do not count; the tx page, the address history, the tx list and /api/v1/tx carry
it; malformed overrides are skipped; no em or en dash. Usage: python3 tools/slotlatch_test.py (temp database, no network)."""
import json, os, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, slotlatch as SL, history as HI, views as V, server as SV

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
DASH = ("\u2014", "\u2013")
db.init()
AU, AV = "poa1EiqCA7qPyds7mQ2EJhS62CCG6eeEkjAbzUhqf1nU7Pmf", "poa1BRUGgAVtgdNy2d3qzmd1Gy7ZVMAZtaPxnpY3U6ce9wDg"
WIN, TWIN, OTHER = "4b751ca654ee3a7bfa8325e2d8a4c387ccc1347919d073b2da0a6ec86ad06452", "2cac65df415e210018418091b8ed1b0c016aa5091ad70b2e671797a4a6235382", "ab" * 32
W461 = "5828918244aa35da5902fe5a75cb07213c5196de796e20c601b32aa13a4a4164"
OV = [{"author": AU, "nonce": 526, "txid": WIN, "provenance_height": 268383, "provenance_root": "bf" * 32, "reason": "lived winner (single claimant never latched; late twin 2cac65df); parity trip 2026-11-04"},
      {"author": AV, "nonce": 461, "txid": W461, "provenance_height": 262362, "provenance_root": "cf" * 32, "reason": "lived winner"},
      {"author": "nope", "nonce": 1, "txid": "x"}, {"author": AV, "nonce": "z", "txid": "cd" * 32}, "junk"]
db.put_blob("params", {"auto_epoch_seconds": 21600, "slot_latch_overrides": OV}); A._cache.clear()
T0 = 1793789000
def tx(i, t, nonce, ts, asg):
    db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, to_addr, amount, epoch, ts, atts, k, final, first_seen, last_seen, source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (i, t, AU, None, None, 43, ts, 9, 5, 1, ts, ts, "fast-index"))
    db.write("INSERT OR REPLACE INTO tx_detail(id, json, fetched, final) VALUES(?,?,?,?)",
             (i, json.dumps({"id": i, "type": t, "from_addr": AU, "ts": ts, "final": True, "body": {"type": t, "from": AU, "nonce": nonce, "ts": ts, "assignment": asg, "cid": "poa-mainnet-1"}}), ts, 1))
tx(WIN, "grade-sealed", 526, T0 + 111, "d5" * 32); tx(TWIN, "grade-sealed", 526, T0 + 256, "ef" * 32); tx(OTHER, "grade-sealed", 527, T0 + 300, "aa" * 32)

check("overrides: 2 valid of 5 rows", [(o["author"], o["nonce"]) for o in SL.overrides()] == [(AU, 526), (AV, 461)])
check("state: winner pinned, twin superseded, other none", SL.state_of(WIN, AU, 526)["state"] == "pinned" and SL.state_of(TWIN, AU, 526)["state"] == "superseded"
      and SL.state_of(TWIN, AU, 526)["winner"] == WIN and SL.state_of(OTHER, AU, 527) is None)
ix = SL.index()
check("index: the winner and the archived twin", ix[WIN]["state"] == "pinned" and ix[TWIN]["state"] == "superseded" and OTHER not in ix and ix[W461]["state"] == "pinned")
tc = HI.type_counts(AU)
check(f"type counts: the twin is not counted ({tc})", tc == {"grade-sealed": 2})
cv = HI.coverage(AU)
check(f"coverage: 2 sent, 1 superseded, no nonce double count ({cv['indexed_sent']}, {cv['superseded']})", cv["indexed_sent"] == 2 and cv["superseded"] == 1 and cv["by_segment"][0]["indexed_sent"] == 2)
rows, _ = HI.txs_page(AU, None, 10)
st = {r["id"]: (r["slot_latch"] or {}).get("state") for r in rows}
check("history rows keep every tx and carry slot_latch", st == {WIN: "pinned", TWIN: "superseded", OTHER: None})
h = V.hist_rows(rows)
check("history: Pinned and Superseded tags", h.count(">Pinned<") == 1 and h.count(">Superseded<") == 1)
tt = V.tx_table(db.q("SELECT * FROM txs ORDER BY ts DESC"), {})
check("tx list: Pinned and Superseded tags", ">Pinned<" in tt and ">Superseded<" in tt)
out, summ, _ = HI._assign_all(AU)
check(f"seals: the twin's assignment is not linked ({summ['seal_txs_indexed']})", summ["seal_txs_indexed"] == 2 and not any(o["answer"] == "ef" * 32 for o in out))
for t, word in ((WIN, ">Pinned<"), (TWIN, ">Superseded<")):
    try: r = V.tx(t); html = r[1] if isinstance(r, tuple) else r
    except Exception as e: html = "error " + type(e).__name__
    check(f"tx page {t[:8]}: {word.strip('><')} tag, no crash", word in html and (t != TWIN or f"/tx/{WIN}" in html))
api = SV.tx_api(TWIN)
check("/api/v1/tx twin: superseded, winner named", api["slot_latch"]["state"] == "superseded" and api["slot_latch"]["winner"] == WIN)
check("/api/v1/tx winner: pinned", SV.tx_api(WIN)["slot_latch"]["state"] == "pinned" and SV.tx_api(OTHER)["slot_latch"] is None)
db.put_blob("params", {"auto_epoch_seconds": 21600}); A._cache.clear()
check("no overrides: nothing tagged, counts as before", SL.index() == {} and HI.type_counts(AU) == {"grade-sealed": 3} and SL.tag(None) == "")
check("no em or en dash", not any(d in h + tt + SL.PINNED_TIP for d in DASH))
print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
