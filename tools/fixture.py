"""Seed a test database with 12 closed epochs, Agents (one with a malformed inviter), a fill and status blobs.
Used by smoke_test.py to render every page against realistic data. Usage: POASCAN_DB=path python3 tools/fixture.py"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db

A1, A2, A3 = ("poa1" + c * 40 for c in "ABC")
TX = "ab" * 32
RP, RN, RV, RW = ("c1" * 32, "c2" * 32, "c3" * 32, "c4" * 32)
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
    # answer receipts: passed, pending, vanished, awaiting close (all by A1)
    eps[n - 2]["basis"]["settled"].append({"answer": RP, "from": A1, "passed": True, "jury": [{"grader": g, "aligned": True} for g in (A2, A3, A2 + "x", A3 + "x")]})
    for k in (n - 2, n - 1): eps[k]["basis"]["pending"][RN] = {"kind": "short", "panel": [A2], "originalPassed": False, "since": n - 2}
    eps[n - 4]["basis"]["pending"][RV] = {"kind": "short", "panel": [], "originalPassed": False, "since": n - 4}
    # backlog: the latest close is the first with grades (pending_merge_from_epoch = n - 1); it carries close n-2's rows
    prev = {k: v for k, v in eps[n - 2]["basis"]["pending"].items() if k.startswith("a")}
    cur = {}
    for k, v in prev.items():
        i = int(k.split("-")[1]); g = list(v["panel"]) + ([A2] if i % 4 == 0 else [])
        cur[k] = dict(v, grades=[{"grader": x, "score": 2, "ts": t0 + n * 21600 - 60} for x in g])
    settled = f"a{n - 2}-1"; cur.pop(settled)                       # since n-3, settles at the latest close
    eps[n - 1]["basis"]["settled"].append({"answer": settled, "from": A2, "passed": True, "jury": [{"grader": A1, "aligned": True}]})
    eps[n - 2]["basis"]["pending"]["bd" * 32] = {"kind": "short", "panel": [], "originalPassed": False, "since": n - 4}   # dropped
    cur["bu" * 32] = {"kind": "appeal", "panel": [A1] * 12, "originalPassed": True, "since": n - 1}                   # no grades: unknown
    cur[RN] = dict(eps[n - 1]["basis"]["pending"][RN], grades=[{"grader": A2, "score": 2, "ts": t0}])
    cur["be" * 32] = {"kind": "short", "panel": [A2], "originalPassed": False, "since": n - 1, "grades": []}               # A2 drawn, no seal
    eps[n - 1]["basis"]["pending"] = cur
    # cohorts: six answers born at close 7, then pending, settled or gone at closes 8 and 9
    CB = [f"cb{i:062x}" for i in range(6)]
    for i, k in enumerate(CB): eps[7]["basis"]["pending"][k] = {"kind": "short", "panel": [A2] if i >= 3 else [], "since": 7}
    for i in (0, 1): eps[8]["basis"]["pending"][CB[i]] = {"kind": "short", "panel": [], "since": 7}
    eps[8]["basis"]["pending"][CB[4]] = {"kind": "short", "panel": [A2], "since": 7}
    eps[9]["basis"]["pending"][CB[0]] = {"kind": "short", "panel": [], "since": 7}
    eps[8]["basis"]["settled"] += [{"answer": CB[2], "from": A1, "passed": True, "jury": []}, {"answer": CB[3], "from": A1, "passed": False, "jury": []}]
    eps[9]["basis"]["settled"].append({"answer": CB[1], "from": A1, "passed": True, "jury": []})
    # calibration: A3 sits on 24 more juries at close 3 (18 aligned; every third outcome failed)
    eps[3]["basis"]["settled"] += [{"answer": f"ca{i:062x}", "from": A1, "passed": i % 3 != 0, "jury": [{"grader": A3, "aligned": i % 4 != 0}]} for i in range(24)]
    db.put_blob("epochs", eps)
    db.put_blob("status", {"supply": "980933293.9", "txs": 100, "final": 90, "agents_joined": 3, "epochs_closed": n, "holders": 3,
                           "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "checkpoint_height": 100, "stale": False, "stale_age_s": 5})
    db.put_blob("params", {"K": 5, "auto_epoch_seconds": 21600, "panel_size": 5, "grade_quorum": 3, "pending_ttl_epochs": 6, "pending_merge_from_epoch": n - 1,
                           "slash_pardons": {"0": [A3]}, "swap_fee_bp": 100, "E0": 1e9, "halving_epochs": 720})
    db.put_blob("networks", {"chains": [{"chain_id": "poa-mainnet-1", "height": 200, "checkpoint_height": 100}]})
    db.put_blob("release", {"current": {"version": "1.8.0"}, "history": [{"version": "1.8.0", "ts": now - 86400}]})
    db.put_blob("fx", {"SOL": 100.0, "ETH": 3000.0, "src": "CoinGecko"})
    db.write("INSERT OR REPLACE INTO accounts(addr, invited_by, balance, balance_s, first_seen, last_seen) VALUES(?,?,?,?,?,?)",
             [(A1, None, 1.5e8, "150000000", t0, now), (A2, A1, 5e7, "50000000", t0, now), (A3, BAD, 2e7, "20000000", t0, now)], many=True)
    db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, to_addr, amount, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?,?,?)",
             (TX, "transfer", A1, A2, "1250", n - 1, now - 600, 5, 5, 1))
    for tid, e in ((RP, n - 3), (RN, n - 2), (RV, n - 4), (RW, n)):
        db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)", (tid, "challenge", A1, e, t0 + e * 21600 + 600, 5, 5, 1))
    db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,1)", (RP, json.dumps({"id": RP, "type": "challenge", "from_addr": A1, "epoch": n - 3, "final": True,
             "ts": t0 + (n - 3) * 21600 + 600, "body": {"type": "challenge", "seed": "61ada059", "epoch": n - 3}}), now))
    for tid, e in ((RN, n - 2), (RV, n - 4)):
        db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,1)", (tid, json.dumps({"id": tid, "type": "challenge", "from_addr": A1, "epoch": e, "final": True,
                 "ts": t0 + e * 21600 + 600, "body": {"type": "challenge", "epoch": e}}), now))
    db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,1)", (TX, json.dumps({"id": TX, "type": "transfer", "from_addr": A1, "to_addr": A2, "amount": "1250",
             "epoch": n - 1, "ts": now - 600, "final": True, "atts": 5, "body": {"type": "transfer", "epoch": n - 1}}), now))
    # grader history for A2: 60 grade-sealed txs, pairs share a timestamp (keyset ties break on id)
    g = [(f"{i:02x}" * 32, "grade-sealed", A2, None, t0 + 1000 + (i // 2) * 10, 5, 5, 1) for i in range(16, 74)]
    g += [("4a" * 32, "grade-sealed", A2, None, t0 + 5000, 5, 5, 1), ("4b" * 32, "grade-sealed", A2, None, t0, 5, 5, 1)]
    db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)", g, many=True)
    for tid, ts, asg, nonce in (("4a" * 32, t0 + 5000, RV, 90), ("4b" * 32, t0, RN, 12)):   # 4a: on the ledger, not in any close record
        db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,1)", (tid, json.dumps({"id": tid, "type": "grade-sealed", "from_addr": A2, "ts": ts, "final": True,
                 "body": {"type": "grade-sealed", "assignment": asg, "from": A2, "nonce": nonce, "ts": ts}}), now))
    # uptime history from before the probe cut: old dedicated probes and bare fetch rows, then derived rows
    rows = [(now - 7200 + i * 60, ep, 1, 100, "200") for i in range(10) for ep in ("probe /api/status", "/api/status", "probe /explorer", "probe /", "probe /go.md")]
    rows += [(now - 600 + i * 60, "probe /api/status", 1, 90, "200") for i in range(5)]
    db.write("INSERT INTO probes VALUES(?,?,?,?,?)", rows, many=True)
    # our reads are current; the checkpoint last moved 8h ago, so the pill reads Lagging
    db.write("INSERT INTO fetch_log(endpoint,last_ok,fails,next_at,bytes) VALUES(?,?,0,0,100)", [("/api/explorer/txs", now), ("/api/status", now), ("/api/params", now - 3 * 3600)], many=True)
    for i, t in enumerate(range(now - 10 * 3600, now, 600)):
        db.add_snap("status", {"checkpoint_height": 90 if t < now - 8 * 3600 else 100}, t)

if __name__ == "__main__":
    seed()
