"""Supply basis at the genesis cut (1.26.122): closes excluded at a cut (segments.json excluded_closes, unconfirmed_closes)
are not carried, so segment 2 cum_supply, circulating plus locked, the holders total and the unlock calendar all equal the
node's supply, and reconcile Mined reads explained. Temp database, no network. Usage: python3 tools/supply_test.py"""
import os, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "s.db")
os.environ.pop("POASCAN_SEGMENTS", None)
os.environ.update(POASCAN_DB=DB, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import db, segments as SG, analytics as A, reconcile as RC, views3 as V3
db.init()
CUT = SG.BY_N[SG.CURRENT]["start_ts"]; P = 21600
def addr(c): return "poa1" + c * 40
X, Y, Z, W = addr("x"), addr("y"), addr("z"), addr("w")   # X listed, Y listed with balance 0 (only excluded rewards), Z not listed, W listed
EXC = {(int(e["segment"]), int(e["epoch"])) for e in SG.unconfirmed_list()}
check("config excludes S1 E12 and E14", {(1, 12), (1, 14)} <= EXC)
def close(n, ts, rewards=None):
    return {"epoch": n, "ts": ts, "pool": 1e9, "rewards": rewards or {}, "challenges": {}, "propagation": {},
            "basis": {"pending": {}, "settled": [], "challenge_eligible": [], "established_after": [], "established_removed": []}}
r1 = {n: {} for n in range(15)}
r1[2] = {X: "100.000000", Z: "40.000000"}; r1[12] = {Y: "50.000000", X: "5.000000", Z: "2.000000"}; r1[13] = {X: "30.000000", W: "20.000000"}; r1[14] = {Y: "8.000000"}
S1 = [close(n, CUT - (15 - n) * P - 3600, r1[n]) for n in range(15)]
S2 = [close(0, CUT + 1800), close(1, CUT + 1800 + P, {W: "10.000000"}), close(2, CUT + 1800 + 2 * P)]
db.put_blob("epochs:s1", S1); db.put_blob("epochs", S2)
carried = 100 + 40 + 30 + 20; supply = carried + 10
now = int(time.time())
db.put_blob("status", {"supply": f"{supply:.6f}", "epochs_closed": 3, "holders": 3, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))})
db.put_blob("params", {"vesting_epochs": 100, "auto_epoch_seconds": P})
ins = "INSERT INTO accounts(addr, balance, balance_s, first_seen, last_seen) VALUES(?,?,?,?,?)"
db.write(ins, (X, 130.0, "130.000000", CUT - 9 * P, now)); db.write(ins, (Y, 0.0, "0.000000", CUT - 9 * P, now))
db.write(ins, (W, 30.0, "30.000000", CUT - 9 * P, now)); db.write(ins, (addr("s"), 999.0, "999.000000", CUT - 9 * P, CUT - 60))   # last seen only before the cut
A._cache.clear()

rows = A.epoch_rows()
check("segment 2 E0 cum_supply is the carried supply", abs(rows[0]["cum_supply"] - carried) < 1e-6)
check("segment 2 latest cum_supply equals /api/status supply", abs(rows[-1]["cum_supply"] - supply) < 1e-6)
check("cum_supply stays a number (v1 type)", all(isinstance(r["cum_supply"], float) and isinstance(r["cum_supply_confirmed"], float) for r in rows))
with SG.use(1): s1 = A.epoch_rows()
check("segment 1 cum_supply as recorded, cum_supply_confirmed without excluded closes",
      abs(s1[-1]["cum_supply"] - (carried + 65)) < 1e-6 and abs(s1[-1]["cum_supply_confirmed"] - carried) < 1e-6 and s1[12]["rewards_state"] == "unconfirmed")

sp = A.supply_split()
check("circulating plus locked equals supply", abs(sp["spendable"] + sp["locked"] - supply) < 1e-6)
h = A.holders()
check("holders total equals supply", abs(h["total"] - supply) < 1e-6)
check("a listed Agent at balance 0 is not re-added from its reward sum", Y not in {r["addr"] for r in h["rows"]})
check("an address last seen before the cut is not a holder row", addr("s") not in {r["addr"] for r in h["rows"]})
check("an unlisted address falls back to confirmed rewards", any(r["addr"] == Z and abs(r["balance"] - 40) < 1e-6 for r in h["rows"]))
check("concentration total equals supply", abs(A.concentration()["total_balance"] - supply) < 1e-6)

u = V3.unlocks_api()
check("unlock calendar: first row circulating minus its unlock is today's circulating (POASwap market cap)",
      bool(u) and abs(u[0]["circulating"] - u[0]["unlocks"] - sp["spendable"]) < 1e-5)
check("unlock calendar ends at the supply, 100%", bool(u) and abs(u[-1]["circulating"] - supply) < 1e-5 and u[-1]["pct"] == 1.0)
check("unlock calendar rows keep their types", all(isinstance(r["unlocks"], float) and isinstance(r["circulating"], float) for r in u))

rr = RC.reconcile(); by = {r["key"]: r for r in rr["rows"]}
check("reconcile Mined reads explained by the excluded closes", by["mined"]["state"] == "explained" and "excluded at the genesis cut" in (by["mined"]["reason"] or ""))
check("reconcile Burned reads explained", by["burned"]["state"] == "explained")
check("reconcile Held: carried rewards against current /api/agents, explained by the unlisted address", by["held"]["state"] in ("match", "explained"))

# ---- 1.26.124: a transfer to an address not in /api/agents stays in the holders total ----
V = addr("v")
db.write("INSERT INTO txs(id, type, from_addr, to_addr, amount, epoch, ts, segment) VALUES(?,?,?,?,?,?,?,?)", ("t" * 64, "transfer", X, V, "10.000000", None, CUT + 4 * P, 2))
db.write("UPDATE accounts SET balance=120.0, balance_s='120.000000' WHERE addr=?", (X,)); A._cache.clear()
h3 = A.holders()
check("transfer to an unlisted address: holders total still equals supply", abs(h3["total"] - supply) < 1e-6 and any(r["addr"] == V and abs(r["balance"] - 10) < 1e-6 for r in h3["rows"]))
check("reconcile Held still explained with that transfer", {r["key"]: r for r in RC.reconcile()["rows"]}["held"]["state"] in ("match", "explained"))

# ---- 1.26.123: segments cut.carry_unlocked (unset: bounds; true: carried rewards spendable since the cut) ----
# ---- 1.26.135: ships true (operators: every carried balance unlocked at the genesis cut) ----
from poascan import agentapi as AG, views as V
cut = SG.BY_N[SG.CURRENT]["cut"]
check("carry_unlocked ships true", SG.carry_unlocked() is True and sp["circulating_basis"] == "carry_unlocked" and sp["locked_confirmed"] is True)
check("carried_supply and excluded_rewards are additive numbers", abs(sp["carried_supply"] - carried) < 1e-6 and abs(sp["excluded_rewards"] - 65) < 1e-6)
off = SG.offset(SG.CURRENT); vest_now = 10 * min(1.0, (A.open_gkey() - (off + 1)) / 100)
check("carry true: carried rewards spendable, new rewards vest", abs(sp["spendable"] - (carried + vest_now)) < 1e-6 and abs(sp["spendable"] + sp["locked"] - supply) < 1e-6)
check("carry true: calendar unlocks only new rewards", bool(u) and abs(u[0]["unlocks"] - 0.1) < 1e-6 and abs(u[0]["circulating"] - u[0]["unlocks"] - sp["spendable"]) < 1e-5)
sm = AG.t_summary({})
check("v1 summary keeps circulating and locked as numbers, adds the basis", isinstance(sm["circulating"], float) and isinstance(sm["locked"], float) and sm["circulating_basis"] == "carry_unlocked")
check("unlock rows carry the basis", all(r["basis"] == "carry_unlocked" for r in u))
tb = V.token_body(); hl = V.headline()
check("carry true: no bound tags on the Token tab or the home headline", not any(t in x for t in ("Lower bound", "Upper bound") for x in (tb, hl["circ"], hl["vest"])))
check("about#segments: neutral carried balances note", "Carried balances unlocked at the genesis cut, per the operators" in V.seg_about())
cut["carry_unlocked"] = None; A._cache.clear()
spn = A.supply_split(); tb = V.token_body()
check("carry unset: bounds, unconfirmed", spn["circulating_basis"] == "unconfirmed" and spn["locked_confirmed"] is False and abs(spn["spendable"] + spn["locked"] - supply) < 1e-6)
check("carry unset: Lower bound on Circulating, Upper bound on Locked, as tags (no sub-line)", "Lower bound</summary>" in tb and "Upper bound</summary>" in tb and 'class="asof"' not in tb)
check("carry unset: Lower bound tag on home Circulating supply", "Lower bound</summary>" in V.headline()["circ"])
check("carry unset: no carried balances note", "Carried balances unlocked" not in V.seg_about())
cut["carry_unlocked"] = False; A._cache.clear()
check("carry false: same figures as unset, confirmed, no tags", abs(A.supply_split()["spendable"] - spn["spendable"]) < 1e-6 and A.supply_split()["circulating_basis"] == "vesting_continues" and "Lower bound" not in V.token_body())
cut["carry_unlocked"] = True; A._cache.clear()

print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
