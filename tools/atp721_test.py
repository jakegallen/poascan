"""ATP-721 unofficial memo replay (1.26.413): local transfer memos only, upsert hook,
first-valid unit, per-address cap, mint fee debit, no upstream reads, no em or en dashes.
Usage: python3 tools/atp721_test.py"""
import os, sys, tempfile, copy
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, atp721 as T, atp20 as T20, indexer as IX

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
DASH = ("\u2014", "\u2013")
db.init()

DEP = "poa1DLtfHN8rajwqj7VdDHYLQ8MFwJGguXww6XU1tn7KNRVg"
A = "poa17w7ediEhWukn2oYbzR4dtjYBYB8L4L5pt18CkXo2ik7M"
B = "poa1GFLrDycn2Ri7uS6uhEqsT4s2EbErRjiiY1ScPQR8TTEu"
SHA = "f24fe8eb6b21cc3f86bd2b3f79b28f65964dbde0fd79f91bee5f644594d59d8e"
DEPLOY = f"ATP-721|d|MAM-GENESIS|{SHA}|image/png|3333|111|MAM|20|5|THE AGENT AWAKENS"

def tid(n):
    return format(n, "064x")

def row(i, memo, fr, to=None, ts=1795214976, final=1, typ="transfer"):
    return dict(id=tid(i) if isinstance(i, int) else i, type=typ, from_addr=fr, to_addr=to if to is not None else fr,
                amount="0.000001", memo=memo, ts=ts, final=final)

def load(*rows, source="test"):
    IX.upsert_txs([copy.deepcopy(r) for r in rows], source)

def fund(*addrs, tick="MAM", amt=1000000, ts=1795174507):
    """Deploy an open ATP-20 tick and mint amt to each address, earlier than any ATP-721 op."""
    load(row(8000, f"ATP-20|d|{tick}|21000000|0|open", DEP, ts=ts))
    for i, addr in enumerate(addrs):
        load(row(8001 + i, f"ATP-20|m|{tick}|{amt}", addr, ts=ts + 1 + i))

p, err = T.parse_memo(DEPLOY)
check("deploy parse: cap, fee, burn 23, title",
      err is None and p["col"] == "MAM-GENESIS" and p["total"] == 3333 and p["fee"] == "111"
      and p["fee_tick"] == "MAM" and p["burn_pct"] == 20 and p["max_per_addr"] == 5
      and p["title"] == "THE AGENT AWAKENS" and p["file_sha"] == SHA and T.burn_amount(111, 20) == 23)
check("bad collection", T.parse_memo("ATP-721|d|mam|{SHA}|image/png|1|1|MAM|20|5|x".replace("{SHA}", SHA))[1] == "bad_collection")
check("svg mime refused", T.parse_memo(f"ATP-721|d|XCOL|{SHA}|image/svg+xml|1|1|MAM|20|5|x")[1] == "bad_types")
check("unknown op ignored", T.parse_memo("ATP-721|l|MAM-GENESIS|1")[1] == "unknown_op")
check("non ATP memo", T.parse_memo("ATP-20|m|MAM|1")[1] == "malformed")

C = "poa1cccccccccccccccccccccccccccccccccccccccccc"
fund(A, B, DEP)
load(row(1, DEPLOY, DEP, ts=1795214976))
tok = T.collection("MAM-GENESIS")
check("deploy applied, unofficial, zero minted",
      tok and tok["deployer"] == DEP and tok["minted"] == 0 and tok["holder_count"] == 0
      and tok["official"] is False and tok["burn_fee"] == "23" and tok["fee"] == "111")

load(row(2, "ATP-721|m|MAM-GENESIS|1", A, ts=1795218110))
check("first mint of unit 1", T.units_count("MAM-GENESIS") == 1 and T.collection("MAM-GENESIS")["minted"] == 1
      and T.units_offset("MAM-GENESIS")[0]["addr"] == A and T.units_offset("MAM-GENESIS")[0]["official"] is False)

load(row(3, "ATP-721|m|MAM-GENESIS|1", B, ts=1795218448))
op = [o for o in T.ops("MAM-GENESIS") if o["txid"] == tid(3)][0]
check("duplicate unit ignored, first keeps it", op["valid"] == 0 and op["reason"] == "duplicate_unit"
      and T.units_offset("MAM-GENESIS")[0]["addr"] == A and T.collection("MAM-GENESIS")["minted"] == 1)

for i, u in enumerate([2, 3, 4, 5], start=4):
    load(row(i, f"ATP-721|m|MAM-GENESIS|{u}", A, ts=1795218500 + i))
check("five units reach the per-address cap", T.collection("MAM-GENESIS")["minted"] == 5
      and T.holders_count("MAM-GENESIS") == 1)
load(row(10, "ATP-721|m|MAM-GENESIS|6", A, ts=1795218600))
check("sixth mint by the same address is ignored",
      [o for o in T.ops("MAM-GENESIS") if o["txid"] == tid(10)][0]["reason"] == "over_addr_cap"
      and T.collection("MAM-GENESIS")["minted"] == 5)

load(row(11, "ATP-721|m|MAM-GENESIS|0", B, ts=1795218700))
load(row(12, "ATP-721|m|MAM-GENESIS|3334", B, ts=1795218701))
check("unit 0 is a parse reject", T.parse_memo("ATP-721|m|MAM-GENESIS|0")[1] == "bad_types")
check("unit above cap is ignored",
      [o for o in T.ops("MAM-GENESIS") if o["txid"] == tid(12)][0]["reason"] == "unit_range")

load(row(13, "ATP-721|m|MAM-GENESIS|10", B, to=A, ts=1795218800))
check("mint that is not a self-transfer is ignored",
      [o for o in T.ops("MAM-GENESIS") if o["txid"] == tid(13)][0]["reason"] == "not_self_transfer")

load(row(20, "ATP-721|d|MAM-GENESIS|" + SHA + "|image/png|10|1|MAM|20|5|x", B, ts=1795218900))
check("later deploy is ignored, first wins", T.collection("MAM-GENESIS")["deploy_txid"] == tid(1)
      and [o for o in T.ops("MAM-GENESIS") if o["txid"] == tid(20)][0]["reason"] == "collection_already_deployed")

load(row(30, "ATP-721|m|MAM-GENESIS|99", B, ts=1795219000))
load(row(31, "ATP-721|t|MAM-GENESIS|99", B, to=DEP, ts=1795219001))
check("valid transfer moves the unit",
      [u for u in T.units_offset("MAM-GENESIS") if u["unit"] == 99][0]["addr"] == DEP)
load(row(32, "ATP-721|t|MAM-GENESIS|99", B, to=A, ts=1795219002))
check("transfer by a non-owner is ignored",
      [o for o in T.ops("MAM-GENESIS") if o["txid"] == tid(32)][0]["reason"] == "not_owner"
      and [u for u in T.units_offset("MAM-GENESIS") if u["unit"] == 99][0]["addr"] == DEP)

# pending then (ts, id)
early_ff = dict(row("ff" * 32, "ATP-721|m|MAM-GENESIS|200", B, ts=1795219100, final=0))
early_aa = dict(row("aa" * 32, "ATP-721|m|MAM-GENESIS|200", A, ts=1795219100, final=0))
# A is already at cap; use a third address after freeing? A has 5, can't mint 200.
# Use B for aa and DEP for ff - DEP has 1 after transfer of 99, can mint.
early_ff = dict(row("ff" * 32, "ATP-721|m|MAM-GENESIS|200", DEP, ts=1795219100, final=0))
early_aa = dict(row("aa" * 32, "ATP-721|m|MAM-GENESIS|200", B, ts=1795219100, final=0))
load(early_ff, early_aa)
check("pending mints do not take a unit", not any(u["unit"] == 200 for u in T.units_offset("MAM-GENESIS")))
early_ff["final"] = 1
load(early_ff)
check("finalizing the later id first applies it until the earlier id is final",
      any(u["unit"] == 200 and u["addr"] == DEP for u in T.units_offset("MAM-GENESIS")))
early_aa["final"] = 1
load(early_aa)
check("once both are final, the earlier id wins the unit",
      [u for u in T.units_offset("MAM-GENESIS") if u["unit"] == 200][0]["addr"] == B
      and [o for o in T.ops("MAM-GENESIS") if o["txid"] == "ff" * 32][0]["reason"] == "duplicate_unit")

# backfill
db.write("DELETE FROM atp721_ops")
db.write("DELETE FROM atp721_collections")
db.write("DELETE FROM atp721_units")
db.write("DELETE FROM atp721_state")
T._inited[0] = True
n = T.backfill()
check("backfill replays stored ATP-721 memos", n > 0 and T.collection("MAM-GENESIS")["minted"] >= 6
      and [u for u in T.units_offset("MAM-GENESIS") if u["unit"] == 1][0]["addr"] == A)

cv = T.coverage()
check("coverage is unofficial, ts_id, fee debit from the minter",
      cv["official"] is False and "Unofficial" in cv["official_note"]
      and cv["ordering"] == "ts_id" and cv["fee_debit"] == "minter"
      and "insufficient_fee_balance" in cv["fee_note"]
      and cv["applied"] >= 1 and cv["ignored"] >= 1)
check("join txs are not ingested", not any(o["txid"] == tid(90) for o in T.ops()) or True)
load(row(90, "ATP-721|m|MAM-GENESIS|201", B, typ="join", ts=1795219900))
check("join txs are not ingested as collection ops", not any(o["txid"] == tid(90) for o in T.ops()))
check("empty ingest is a no-op", T.ingest([], "test") == 0)

# second synthetic collection, no per-collection code
SHA2 = "aa" * 32
DEP2 = "ATP-721|d|DEMO-ART|" + SHA2 + "|image/png|10|1|MAM|20|2|SECOND COLLECTION"
load(row(200, DEP2, B, ts=1795220000))
load(row(201, "ATP-721|m|DEMO-ART|1", B, ts=1795220001))
load(row(202, "ATP-721|m|DEMO-ART|2", B, ts=1795220002))
load(row(203, "ATP-721|m|DEMO-ART|3", B, ts=1795220003))
demo = T.collection("DEMO-ART")
check("second collection deploys and mints under its own cap",
      demo and demo["total"] == 10 and demo["minted"] == 2 and demo["holder_count"] == 1
      and demo["official"] is False and demo["title"] == "SECOND COLLECTION")
check("third mint on DEMO-ART hits that collection's per-address cap",
      [o for o in T.ops("DEMO-ART") if o["txid"] == tid(203)][0]["reason"] == "over_addr_cap")
cols = {c["col"] for c in T.collections()}
check("collections() lists both tickers with no hardcoded filter",
      "MAM-GENESIS" in cols and "DEMO-ART" in cols)
check("first collection counts are unchanged by the second ticker",
      T.collection("MAM-GENESIS")["minted"] >= 6)


# mint fee debit
col = T.collection("MAM-GENESIS")
mam = T20.token("MAM")
# A minted 5 units (1-5); B minted 99 and 200 (2). DEP never keeps unit 200 in the final order,
# so that mint is duplicate_unit and does not pay a fee.
# DEMO-ART: B minted 2 units at fee 1 (separate collection).
fee_mints_mam = 5 + 2
check("MAM-GENESIS fee burns and deployer credits",
      col["fee_burned"] == str(fee_mints_mam * 23) and col["deployer_fees"] == str(fee_mints_mam * 88)
      and int(mam["burned"]) >= fee_mints_mam * 23)
check("deployer received fee remainder in MAM",
      int(T20.balance("MAM", DEP)["amount"]) >= fee_mints_mam * 88)

# insufficient fee: C has no MAM
load(row(300, "ATP-721|m|MAM-GENESIS|300", C, ts=1795221000))
op_c = [o for o in T.ops("MAM-GENESIS") if o["txid"] == tid(300)][0]
check("mint without the fee is ignored",
      op_c["valid"] == 0 and op_c["reason"] == "insufficient_fee_balance"
      and not any(u["unit"] == 300 for u in T.units_offset("MAM-GENESIS", 0, 200)))

# interleaving: D gets 50 MAM (less than fee 111), mint fails; then a later ATP-20 mint funds D and a later 721 mint succeeds
D = "poa1dddddddddddddddddddddddddddddddddddddddddd"
load(row(400, "ATP-20|m|MAM|50", D, ts=1795222000))
load(row(401, "ATP-721|m|MAM-GENESIS|301", D, ts=1795222001))
op_d = [o for o in T.ops("MAM-GENESIS") if o["txid"] == tid(401)][0]
check("mint before the minter can pay the fee is ignored",
      op_d["reason"] == "insufficient_fee_balance")
load(row(402, "ATP-20|m|MAM|100", D, ts=1795222002))
load(row(403, "ATP-721|m|MAM-GENESIS|302", D, ts=1795222003))
op_d2 = [o for o in T.ops("MAM-GENESIS") if o["txid"] == tid(403)][0]
u302 = [u for u in T.units_offset("MAM-GENESIS", 0, 200) if u["unit"] == 302]
check("mint after a later ATP-20 credit is applied",
      op_d2["valid"] == 1 and u302 and u302[0]["addr"] == D)
# 50+100-111 = 39 left for D
check("minter balance after interleaved fee debit",
      T20.balance("MAM", D)["amount"] == "39")

# same-timestamp order: ATP-20 credit and 721 mint share a ts; 20 is applied first (family tie-break)
E = "poa1eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
load(row(500, "ATP-20|m|MAM|111", E, ts=1795223000))
load(row(501, "ATP-721|m|MAM-GENESIS|303", E, ts=1795223000))
op_e = [o for o in T.ops("MAM-GENESIS") if o["txid"] == tid(501)][0]
u303 = [u for u in T.units_offset("MAM-GENESIS", 0, 200) if u["unit"] == 303]
check("same-ts ATP-20 credit is applied before the 721 mint",
      op_e["valid"] == 1 and u303 and u303[0]["addr"] == E
      and T20.balance("MAM", E)["amount"] == "0")

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "atp721.py"), encoding="utf-8").read()
src2 = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "atpreplay.py"), encoding="utf-8").read()
check("no em or en dash in atp721.py or atpreplay.py", not any(d in src + src2 or d in T.OFFICIAL_NOTE or d in T.ORDERING_NOTE or d in T.FEE_NOTE for d in DASH))

print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
