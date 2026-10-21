"""Seed a test database with 12 closed epochs, Agents (one with a malformed inviter), a fill and status blobs.
Used by smoke_test.py to render every page against realistic data. Usage: POASCAN_DB=path python3 tools/fixture.py"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db

A1, A2, A3 = ("poa1" + c * 40 for c in "ABC")
BAD = "poa132rYmMupMdxEk7RWNDC4atRy7pVY92LwWfiAdsbC46P8-"

def seed(n=12):
    db.init(); now = int(time.time()); t0 = now - n * 21600
    eps = []
    for e in range(n):
        pend = {f"a{e}-{i}": {"kind": "short" if i % 3 else "appeal", "since": max(0, e - i % 9), "panel": [A1] if i % 2 else []} for i in range(20)}
        eps.append({"epoch": e, "ts": t0 + (e + 1) * 21600, "pool": 1e9, "rewards": {A1: 1e8, A2: 5e7, A3: 2e7},
                    "challenges": {A1: 1, A2: 1}, "propagation": {},
                    "basis": {"pending": pend, "settled": [{"passed": True}, {"passed": False}], "attestations": {A1: 3},
                              "graders_served": {A1: 4}, "slashed": [A3] if e % 4 == 0 else [], "established_after": [A1],
                              "challenge_eligible": [A1, A2], "audit": {"sampled": 2, "slashed": []}}})
    db.put_blob("epochs", eps)
    db.put_blob("status", {"supply": "980933293.9", "txs": 100, "final": 90, "agents_joined": 3, "epochs_closed": n, "holders": 3,
                           "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "checkpoint_height": 100, "stale": False, "stale_age_s": 5})
    db.put_blob("params", {"K": 5, "auto_epoch_seconds": 21600, "panel_size": 5, "grade_quorum": 3, "pending_ttl_epochs": 6,
                           "slash_pardons": {"0": [A3]}, "swap_fee_bp": 100, "E0": 1e9, "halving_epochs": 720})
    db.put_blob("networks", {"chains": [{"chain_id": "poa-mainnet-1", "height": 200, "checkpoint_height": 100}]})
    db.put_blob("fx", {"SOL": 100.0, "ETH": 3000.0, "src": "CoinGecko"})
    db.write("INSERT OR REPLACE INTO accounts(addr, invited_by, balance, balance_s, first_seen, last_seen) VALUES(?,?,?,?,?,?)",
             [(A1, None, 1.5e8, "150000000", t0, now), (A2, A1, 5e7, "50000000", t0, now), (A3, BAD, 2e7, "20000000", t0, now)], many=True)

if __name__ == "__main__":
    seed()
