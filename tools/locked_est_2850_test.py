#!/usr/bin/env python3
"""Bug 2850: POAScan locked_est too low while rewards_behind is true.

rewards_by_addr() carries only the close records POAScan has read, and vest_split vests them against open_gkey() (the
network's open epoch from /api/status epochs_closed). When the network lists newer closes than POAScan holds the open
epoch advances past the held records, so the held rewards are vested against a later open epoch than they stand at:
more unlocks, and locked_est reads low. The fix caps the vesting reference at the open epoch just after the newest held
close. Spendable and locked still sum to the held rewards (no invented split for the missing close); only the split
boundary is corrected, so locked_est no longer reads low while rewards_behind is true.

Run: python3 tools/locked_est_2850_test.py (in-process, no network; a temp db for the module import)."""
import os, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, segments as SG, server as S, agentapi as AG
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NOW = int(time.time()); P = 21600; seg = SG.CURRENT
a = "poa15VA8Smq8kAt8jzx9N9B4cp11zj4QZ2cQv2oMtYmey8em"
REWARD = 1_000_000.0; K = 10   # one reward, earned at the E10 close

# POAScan holds E0..E15 (16 closes); the reward sits at E10.
closes = [dict(epoch=k, ts=NOW - (15 - k) * P, rewards={}, basis={}) for k in range(16)]
closes[K]["rewards"] = {a: f"{REWARD:.6f}"}
db.put_blob(SG.blob_kind(seg), closes)
db.put_blob("params", {"auto_epoch_seconds": P, "vesting_epochs": 100})
# The network reports one more close than POAScan holds: the open epoch is E17, the held records stand at E16's open.
db.put_blob("status", {"epochs_closed": 17, "supply": "1", "txs": 1})
# A balance ahead of the held rewards, so the reward figures are flagged behind.
db.write("INSERT INTO accounts(addr, balance, balance_s, last_seen, first_seen) VALUES(?,?,?,?,?)",
         (a, REWARD + 200000.0, f"{REWARD + 200000.0:.6f}", NOW - 60, NOW - 18 * P))
A._cache.clear()

gk = SG.gkey(K, seg); rb = A.rewards_by_addr().get(a, {})
check("the held reward is read under its lifetime close number", abs(float(rb.get(gk, 0)) - REWARD) < 1e-6)

# open_gkey has advanced to E17 while the newest held close is E15: the raw (uncapped) split over-unlocks.
over_sp, over_lk = A.vesting_split({gk: REWARD}, A.open_gkey(), 100)
check("uncapped split (the bug) unlocks against E17: 7 percent spendable, locked 930,000",
      abs(over_sp - 70000.0) < 1e-6 and abs(over_lk - 930000.0) < 1e-6)

# vest_split caps the reference at the open epoch after the newest held close (E16): 6 percent spendable.
sp, lk = A.vest_split(rb, A.open_gkey())
check("vest_split caps at E16: 6 percent spendable, locked 940,000 (10,000 higher, no longer low)",
      abs(sp - 60000.0) < 1e-6 and abs(lk - 940000.0) < 1e-6)
check("spendable + locked still equal the held rewards (no invented split for the missing close)",
      abs(sp + lk - REWARD) < 1e-6)
check("the fix raises locked_est, it never lowers it", lk > over_lk)

# Not behind (status equals the held closes): the cap is a no-op, the split is unchanged.
db.put_blob("status", {"epochs_closed": 16, "supply": "1", "txs": 1}); A._cache.clear()
sp2, lk2 = A.vest_split(rb, A.open_gkey())
check("when POAScan is current the split is unchanged (cap is a no-op, open epoch already E16)",
      abs(sp2 - 60000.0) < 1e-6 and abs(lk2 - 940000.0) < 1e-6)

# Back to behind: the HTTP and MCP address views carry the corrected locked_est with rewards_behind true.
db.put_blob("status", {"epochs_closed": 17, "supply": "1", "txs": 1}); A._cache.clear()
r = S.api("/api/address/" + a, {})[0]
check("API: rewards_behind true and locked_est is the capped 940,000, not the low 930,000",
      r["rewards_behind"] is True and abs(r["locked_est"] - 940000.0) < 1e-3)
check("API: spendable_est + locked_est = rewards_total (invariant holds while behind)",
      abs(r["spendable_est"] + r["locked_est"] - r["rewards_total"]) < 1e-3)
m = AG.t_address({"address": a, "tx_limit": 0})
check("MCP get_address: locked_est is the capped 940,000 while rewards_behind is true",
      m["rewards_behind"] is True and abs(m["locked_est"] - 940000.0) < 1e-3)

check("no em or en dash in the new code", not any(c in (A.vest_split.__doc__ or "") for c in "\u2014\u2013"))

print(("\nFAILED: " + ", ".join(fails)) if fails else "\nall passed")
sys.exit(1 if fails else 0)
