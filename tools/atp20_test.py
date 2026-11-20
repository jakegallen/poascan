"""ATP-20 unofficial memo replay (1.26.409): local transfer memos only, upsert hook, fixtures for
v1.0 SEAL and v1.1 MAM, no upstream reads, no em or en dashes.
Usage: python3 tools/atp20_test.py"""
import json, os, sys, tempfile, copy
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, atp20 as T, indexer as IX

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
DASH = ("\u2014", "\u2013")
db.init()

FIX = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "atp20_fixture.json")))
DEP, HOLDER, OTHER = FIX["deployer"], FIX["holder"], FIX["other"]
SEAL_D, SEAL_M, MAM_D = FIX["txs"]

def tid(n):
    return format(n, "064x")

def row(i, memo, fr, to=None, ts=1795179000, final=1, typ="transfer", nonce=None, amt="0.000001"):
    return dict(id=tid(i) if isinstance(i, int) else i, type=typ, from_addr=fr, to_addr=to if to is not None else fr,
                amount=amt, memo=memo, ts=ts, final=final, nonce=nonce)

def load(*rows, source="test"):
    IX.upsert_txs([copy.deepcopy(r) for r in rows], source)

# ---- parse ----
p, err = T.parse_memo("ATP-20|d|SEAL|21000000|8|1000")
check("SEAL deploy: 6th field is meta_cid, default deployer mint",
      err is None and p["tick"] == "SEAL" and p["decimals"] == 8 and p["max_supply"] == "21000000"
      and p["meta_cid"] == "1000" and p["mint_auth"] == "deployer")
p, err = T.parse_memo("ATP-20|d|MAM|21000000|0||open:1000:5")
check("MAM deploy: empty meta_cid and open:1000:5 auth",
      err is None and p["tick"] == "MAM" and p["decimals"] == 0 and p["meta_cid"] is None
      and p["mint_auth"] == "open:1000:5" and T.parse_auth(p["mint_auth"]) == ("open", 1000, 5))
p, err = T.parse_memo("ATP-20|d|OPEN|1000|0|open")
check("6-field deploy with a mint_auth last field", err is None and p["mint_auth"] == "open" and p["meta_cid"] is None)
check("bad tick", T.parse_memo("ATP-20|d|se|1|0")[1] == "bad_tick")
check("unknown op ignored", T.parse_memo("ATP-20|x|SEAL|1")[1] == "unknown_op")
check("memo longer than 140 is ignored", T.parse_memo("ATP-20|m|SEAL|" + "1" * 200)[1] == "memo_too_long")
check("non ATP memo", T.parse_memo("AC1|m|abcd")[1] == "malformed")

# ---- SEAL and MAM deploys plus first SEAL mint, via the upsert hook ----
load(SEAL_D, SEAL_M, MAM_D)
seal, mam = T.token("SEAL"), T.token("MAM")
check("SEAL token: 8 decimals, meta_cid 1000, deployer mint, unofficial",
      seal and seal["decimals"] == 8 and seal["meta_cid"] == "1000" and seal["mint_auth"] == "deployer"
      and seal["deployer"] == DEP and seal["minted"] == "1000" and seal["official"] is False
      and seal["holder_count"] == 1)
check("MAM token: 0 decimals, open:1000:5, no auto balance",
      mam and mam["decimals"] == 0 and mam["mint_auth"] == "open:1000:5" and mam["minted"] == "0"
      and mam["holder_count"] == 0 and mam["official"] is False)
check("SEAL mint credited the deployer", T.balance("SEAL", DEP)["amount"] == "1000" and T.balance("SEAL", DEP)["official"] is False)

# non-deployer cannot mint SEAL
load(row(10, "ATP-20|m|SEAL|1000", HOLDER, ts=1795179300))
check("SEAL mint by a non-deployer is ignored", T.token("SEAL")["minted"] == "1000" and T.balance("SEAL", HOLDER)["amount"] == "0")
op10 = [o for o in T.ops("SEAL") if o["txid"] == tid(10)][0]
check("ignored mint reason mint_not_authorized", op10["valid"] == 0 and op10["reason"] == "mint_not_authorized")

# duplicate deploy
load(row(11, "ATP-20|d|SEAL|1|0", OTHER, ts=1795179400))
check("later SEAL deploy is ignored, first wins", T.token("SEAL")["deploy_txid"] == SEAL_D["id"]
      and [o for o in T.ops("SEAL") if o["txid"] == tid(11)][0]["reason"] == "tick_already_deployed")

# ---- MAM open mint caps ----
for i in range(5):
    load(row(20 + i, "ATP-20|m|MAM|1000", HOLDER, ts=1795180000 + i))
check("five exact MAM mints credit 5000", T.balance("MAM", HOLDER)["amount"] == "5000" and T.balance("MAM", HOLDER)["mint_count"] == 5)
load(row(30, "ATP-20|m|MAM|1000", HOLDER, ts=1795180100))
check("sixth MAM mint is ignored (per-address cap)", T.balance("MAM", HOLDER)["amount"] == "5000"
      and [o for o in T.ops("MAM") if o["txid"] == tid(30)][0]["reason"] == "mint_cap")
load(row(31, "ATP-20|m|MAM|999", OTHER, ts=1795180110))
check("MAM mint of the wrong amount is ignored", T.balance("MAM", OTHER)["amount"] == "0"
      and [o for o in T.ops("MAM") if o["txid"] == tid(31)][0]["reason"] == "mint_amount")

# ---- overflow ignored whole ----
load(row(40, "ATP-20|d|CAP|1500|0", DEP, ts=1795181000),
     row(41, "ATP-20|m|CAP|1000", DEP, ts=1795181001),
     row(42, "ATP-20|m|CAP|1000", DEP, ts=1795181002))
check("overflow mint ignored whole, minted stays 1000", T.token("CAP")["minted"] == "1000"
      and T.balance("CAP", DEP)["amount"] == "1000"
      and [o for o in T.ops("CAP") if o["txid"] == tid(42)][0]["reason"] == "mint_overflow")

# ---- transfers and burns ----
load(row(50, "ATP-20|t|SEAL|100", DEP, to=DEP, ts=1795182000))
check("token transfer to self is ignored", T.balance("SEAL", DEP)["amount"] == "1000"
      and [o for o in T.ops("SEAL") if o["txid"] == tid(50)][0]["reason"] == "self_transfer")
load(row(51, "ATP-20|t|SEAL|5000", DEP, to=HOLDER, ts=1795182001))
check("transfer above balance is ignored", T.balance("SEAL", DEP)["amount"] == "1000" and T.balance("SEAL", HOLDER)["amount"] == "0")
load(row(52, "ATP-20|t|SEAL|250", DEP, to=HOLDER, ts=1795182002))
check("valid transfer moves 250", T.balance("SEAL", DEP)["amount"] == "750" and T.balance("SEAL", HOLDER)["amount"] == "250"
      and T.token("SEAL")["holder_count"] == 2)
load(row(53, "ATP-20|b|SEAL|50", HOLDER, ts=1795182003))
check("burn debits the signer, not the deployer", T.balance("SEAL", HOLDER)["amount"] == "200" and T.balance("SEAL", DEP)["amount"] == "750"
      and T.token("SEAL")["burned"] == "50")
load(row(54, "ATP-20|b|SEAL|10000", HOLDER, ts=1795182004))
check("burn above balance is ignored", T.balance("SEAL", HOLDER)["amount"] == "200" and T.token("SEAL")["burned"] == "50")

# ---- pending then final, and (ts, id) order ----
# Two same-ts deploys of TIE: lexicographic id, aa.. wins over ff..
early_ff = dict(row("ff" * 32, "ATP-20|d|TIE|10|0", OTHER, ts=1795183000, final=0))
early_aa = dict(row("aa" * 32, "ATP-20|d|TIE|10|0", DEP, ts=1795183000, final=0))
load(early_ff, early_aa)
check("pending deploys do not reserve a tick", T.token("TIE") is None and len(T.pending("TIE")) == 2)
# finalize the later-sorted id first, then the earlier one; apply order must follow (ts, id), not arrival
early_ff["final"] = 1
load(early_ff)
check("finalizing the later id first still leaves no token until replay of the earlier id, or applies ff if only one is final",
      T.token("TIE") is not None)  # ff is now final and aa still pending, so ff wins for now
early_aa["final"] = 1
load(early_aa)
check("once both are final, the earlier id wins the tick", T.token("TIE")["deploy_txid"] == "aa" * 32
      and [o for o in T.ops("TIE") if o["txid"] == "ff" * 32][0]["reason"] == "tick_already_deployed")

# ---- memo coalesce: first sighting without memo, then with memo; a later blank must not wipe ----
bare = row(60, None, DEP, ts=1795184000)
load(bare)
check("transfer without an ATP memo is not an op", not any(o["txid"] == tid(60) for o in T.ops()))
bare["memo"] = "ATP-20|m|MAM|1000"
load(bare, source="later")
check("memo arriving later is applied", any(o["txid"] == tid(60) and o["valid"] == 1 for o in T.ops("MAM"))
      and T.balance("MAM", DEP)["amount"] == "1000")
bare2 = dict(bare); bare2["memo"] = None
load(bare2, source="blank")
check("a later copy without a memo does not blank the stored memo",
      [o for o in T.ops("MAM") if o["txid"] == tid(60)][0]["memo"] == "ATP-20|m|MAM|1000"
      and T.balance("MAM", DEP)["amount"] == "1000")

# ---- backfill from the txs table ----
# wipe ATP-20 state and rebuild from txs only
db.write("DELETE FROM atp20_ops")
db.write("DELETE FROM atp20_tokens")
db.write("DELETE FROM atp20_balances")
db.write("DELETE FROM atp20_state")
T._inited[0] = True
n = T.backfill()
check("backfill replays stored ATP-20 memos", n > 0 and T.token("SEAL")["minted"] == "1000"
      and T.token("MAM") is not None and T.balance("SEAL", HOLDER)["amount"] == "200")

# ---- coverage and unofficial labels ----
cv = T.coverage()
check("coverage is unofficial and names ts_id order and from_addr burns",
      cv["official"] is False and "Unofficial" in cv["official_note"]
      and cv["ordering"] == "ts_id" and cv["burn"] == "from_addr"
      and cv["applied"] >= 1 and cv["ignored"] >= 1 and cv["pending"] == 0)
check("token list rows are unofficial", all(t["official"] is False for t in T.tokens()))
check("holder rows are unofficial", all(h["official"] is False for h in T.holders("SEAL")) and T.holders("SEAL")[0]["amount"] in ("750", "200"))
check("unknown tick balance is None", T.balance("NOPE", DEP) is None)
check("known tick, zero holder: unofficial zero", T.balance("SEAL", OTHER) == dict(tick="SEAL", addr=OTHER, amount="0", mint_count=0, official=False))

# ---- non-transfer and empty ingest ----
load(row(90, "ATP-20|m|SEAL|1000", DEP, typ="join", ts=1795185000))
check("join txs are not ingested as token ops", not any(o["txid"] == tid(90) for o in T.ops()))
check("ingest of an empty batch is a no-op", T.ingest([], "test") == 0)

# ---- module text ----
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "atp20.py"), encoding="utf-8").read()
check("no em or en dash in atp20.py", not any(d in src or d in T.OFFICIAL_NOTE or d in T.ORDERING_NOTE or d in T.BURN_NOTE for d in DASH))

print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
