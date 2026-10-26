"""Balance lag (1.26.166): the address balance is the fresher of minepoa.com's address read and the agent list row by
the checkpoint each reflects, not by read time; an address read of 0 never overrides a nonzero agent list row under
30 min old (hdr, LabLeak 5527: explorer 0 while /api/agents had 511,996.651201 for about 2.5 h); an address read past
the explorer config segment's final checkpoint is the current segment's state; the Balance stat says "As of checkpoint N".
Temp database, no network. Usage: python3 tools/balance_lag_test.py"""
import os, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ.pop("POASCAN_SEGMENTS", None)
os.environ.update(POASCAN_DB=os.path.join(tmp, "b.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import db
db.init()
db.put_blob("networks", {"default_chain": "poa-mainnet-1", "chains": [{"chain_id": "poa-mainnet-1", "status": "live", "default": True, "checkpoint_height": 59755, "height": 61000}]})
from poascan import views as V, segments as SG, indexer as I, analytics as A
now = int(time.time()); H = "poa15VA8Smq8kAt8jzx9N9B4cp11zj4QZ2cQv2oMtYmey8em"
acc = lambda bal, seen: {"balance_s": bal, "balance": float(bal), "last_seen": seen}
xread = lambda bal, cp=None: dict(balance=bal, **({"balance_as_of": {"checkpoint_height": cp}} if cp is not None else {}))
def roster_at(cp, ts): db.put_blob("agents_cp", {"ts": ts, "checkpoint": cp})

# 1) hdr: the address read says 0 at the current checkpoint, the agent list row (5 min old) has the balance
roster_at(None, now - 300)
bb = V.address_balance(H, xread("0.000000", 59755), now, acc("511996.651201", now - 300))
check(f"address read 0 never overrides a nonzero agent list row under 30 min old ({bb['balance']}, {bb['source']})", bb["balance"] == "511996.651201" and bb["source"] == "agents" and not bb["stale"])
bb = V.address_balance(H, xread("0.000000"), now, acc("511996.651201", now - 300))
check("same without a checkpoint on the read", bb["balance"] == "511996.651201")
bb = V.address_balance(H, xread("0.000000", 59755), now, acc("511996.651201", now - 3600))
check(f"a row over 30 min old no longer guards a 0 (read time decides, no checkpoints) ({bb['source']})", bb["source"] == "explorer/address")

I.upsert_txs([{"id": "f1" * 32, "type": "transfer", "from_addr": "poa1" + "W" * 44, "to_addr": H, "amount": "5", "ts": now - 60, "final": 1}], "test")
bb = V.address_balance("poa1" + "W" * 44, xread("0.000000", 59755), now, acc("5.000000", now - 300))
check(f"a real sweep (outgoing tx archived since the row) lets the 0 through ({bb['balance']}, {bb['source']})", bb["balance"] == "0.000000" and bb["source"] == "explorer/address")

# 2) checkpoints decide, not read time
roster_at(59760, now - 600)
bb = V.address_balance(H, xread("500000.000000", 59755), now, acc("511996.651201", now - 600))
check(f"the agent list row stands at a later checkpoint: it wins though the address read is newer ({bb['source']})", bb["source"] == "agents" and bb["balance"] == "511996.651201")
roster_at(59700, now - 600)
bb = V.address_balance(H, xread("512100.000000", 59755), now - 900, acc("511996.651201", now - 600))
check(f"the address read stands at a later checkpoint: it wins though it was read earlier ({bb['source']}, cp {bb['as_of_checkpoint']})",
      bb["source"] == "explorer/address" and bb["balance"] == "512100.000000" and bb["as_of_checkpoint"] == 59755 and not bb["stale"])
roster_at(59700, now - 2000)
bb = V.address_balance(H, xread("1.000000", 59755), now, acc("511996.651201", now - 600))
check("a roster checkpoint from another agents run is not used (read time decides)", bb["source"] == "explorer/address")

# 3) the explorer config segment (1) is past: a read past segment 1's final checkpoint is current state, not "As of checkpoint 44003"
check("config still says the explorer serves segment 1", SG.source_segment("explorer") != SG.CURRENT)
bb = V.address_balance("poa1" + "Z" * 44, xread("42.000000", 59755), now, None)
check(f"a recruit missing from the agent list: current, not stale, checkpoint 59755 ({bb})", bb["source"] == "explorer/address" and not bb["stale"] and bb["segment"] == SG.CURRENT and bb["as_of_checkpoint"] == 59755)
bb = V.address_balance("poa1" + "Z" * 44, xread("42.000000"), now, None)
check(f"a read naming no checkpoint keeps the old rule: stale, as of segment 1's final checkpoint ({bb['as_of_checkpoint']})", bb["stale"] and bb["as_of_checkpoint"] == 44003)
st0 = SG.BY_N[SG.CURRENT]["start_ts"]
bb = V.address_balance("poa1" + "Y" * 44, None, None, acc("9.000000", st0 - 100))
check(f"a row last seen before the cut and no read: stale, its own segment ({bb['stale']}, {bb['segment']})", bb["stale"] and bb["segment"] != SG.CURRENT)

# 4) Balance stat tag: Stale "As of checkpoint N" when the read is behind the current checkpoint, tooltip when at it
check(f"read behind the current checkpoint: Stale flag text ({V.balance_tag(dict(source='explorer/address', as_of_checkpoint=59700, stale=False, segment=SG.CURRENT))})",
      V.balance_tag(dict(source="explorer/address", as_of_checkpoint=59700, stale=False, segment=SG.CURRENT)) == ("As of checkpoint 59700", None))
check("read at the current checkpoint: label tooltip only", V.balance_tag(dict(source="explorer/address", as_of_checkpoint=59755, stale=False, segment=SG.CURRENT)) == (None, "As of checkpoint 59755"))
check("agent list balance: no tag", V.balance_tag(dict(source="agents", as_of_checkpoint=None, stale=False, segment=SG.CURRENT)) == (None, None))
from poascan import ui as U
h = U.stat("Balance", "1", asof_text="As of checkpoint 59700")
check("the stat shows the Stale flag with the checkpoint, no sub-line", "As of checkpoint 59700" in h and "Stale" in h and "class=\"sub\"" not in h)
check("no en or em dashes in the copy", not any(ch in V.balance_tag(dict(source="explorer/address", as_of_checkpoint=1, stale=False, segment=SG.CURRENT))[0] for ch in "\u2013\u2014"))

# 5) the agents job records the checkpoint its roster stands at
I.fetch = lambda *a, **k: [{"addr": H, "balance": "511996.651201", "ts": now, "joined_epoch": 8}]
I.job_agents()
b, _ = db.get_blob("agents_cp"); row = db.q1("SELECT last_seen FROM accounts WHERE addr=?", (H,))
check(f"agents job writes agents_cp at the current checkpoint, same time as last_seen ({b})", b["checkpoint"] == 59755 and abs(b["ts"] - row["last_seen"]) <= 1 and V.roster_cp(row["last_seen"]) == 59755)

print(f"{len(fails)} failed" if fails else "all passed"); sys.exit(1 if fails else 0)
