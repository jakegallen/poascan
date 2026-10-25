"""Configurable segment boundaries (poascan/segments.json): a third segment and a moved boundary work by a config
change alone; the current segment follows /api/networks; boundary refunds, balance-shown fills and the carried supply
baseline. Temp databases and temp config files, no network. Usage: python3 tools/segconfig_test.py"""
import json, os, subprocess, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

BASE = json.load(open(os.path.join(ROOT, "poascan", "segments.json"), encoding="utf-8"))
CUT = BASE["segments"][1]["start_ts"]

def run(cfg, code):
    """Run code in a fresh interpreter with this segments config and a temp database; returns its JSON output."""
    d = tempfile.mkdtemp(); p = os.path.join(d, "segments.json"); json.dump(cfg, open(p, "w"))
    env = dict(os.environ, POASCAN_SEGMENTS_FILE=p, POASCAN_DB=os.path.join(d, "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
    env.pop("POASCAN_SEGMENTS", None)
    r = subprocess.run([sys.executable, "-c", "import json, sys\nsys.path.insert(0, %r)\n" % ROOT + code], env=env, capture_output=True, text=True, cwd=ROOT, timeout=300)
    if r.returncode: print(r.stderr[-1500:]); return None
    return json.loads(r.stdout.strip().splitlines()[-1])

# ---- 1. a third segment: one config entry, nothing else ----
S3 = CUT + 1800   # started: a configured segment counts once its start has passed
cfg3 = json.loads(json.dumps(BASE))
cfg3["segments"][1]["cut_height"] = 5000; cfg3["segments"][1]["closes"] = 40; cfg3["segments"][1]["chain_id"] = "poa-mainnet-1-segment2"
cfg3["segments"].append({"n": 3, "label": "Segment 3", "chain_id": "poa-mainnet-1", "start_ts": S3, "from_segment": 2, "from_height": 5000,
                         "cut": {"label": "Genesis cut", "notice_id": "n3", "txid": "ab" * 32}})
out = run(cfg3, f"""
from poascan import segments as S, db, milestones as M
db.init()
nw = dict(chains=[dict(chain_id="poa-mainnet-1-segment1", status="halted"), dict(chain_id="poa-mainnet-1-segment2", status="halted"),
                  dict(chain_id="poa-mainnet-1", status="live", default=True, checkpoint_height=12)])
print(json.dumps(dict(cur=S.CURRENT, nw=S.current_of(nw), of=[S.of_ts({CUT} - 5), S.of_ts({CUT} + 5), S.of_ts({S3} + 5)],
      cuts=[(c["segment"], c["ts"]) for c in S.cuts()], cut=S.cut()["segment"], off=S.offset(3), g=S.split_gkey(15 + 40 + 2),
      kind=[S.blob_kind(1), S.blob_kind(2), S.blob_kind(3)], ms=sorted(k for k in M.SOLO if k.startswith("genesis_cut")),
      arch=[S.archived(1), S.archived(2), S.archived(3)], cp=S.checkpoint_of(3, nw), cp2=S.checkpoint_of(2, nw))))
""")
check("segment 3 by config: run", out is not None)
if out:
    check("segment 3 by config: current is 3 (config and networks)", out["cur"] == 3 and out["nw"] == 3)
    check("segment 3 by config: boundaries", out["of"] == [1, 2, 3] and out["cuts"] == [[2, CUT], [3, S3]] and out["cut"] == 3)
    check("segment 3 by config: lifetime close keys", out["off"] == 55 and out["g"] == [3, 2])
    check("segment 3 by config: blobs and archive flags", out["kind"] == ["epochs:s1", "epochs:s2", "epochs"] and out["arch"] == [True, True, False])
    check("segment 3 by config: one milestone per cut", out["ms"] == ["genesis_cut", "genesis_cut_s3"])
    check("segment 3 by config: checkpoint from networks, else config", out["cp"] == 12 and out["cp2"] == 5000)

# ---- 2. moved boundary: stored rows follow the config on the next boot ----
d = tempfile.mkdtemp(); db_path = os.path.join(d, "m.db")
def boot(cfg, code):
    p = os.path.join(d, "segments.json"); json.dump(cfg, open(p, "w"))
    env = dict(os.environ, POASCAN_SEGMENTS_FILE=p, POASCAN_DB=db_path, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9"); env.pop("POASCAN_SEGMENTS", None)
    r = subprocess.run([sys.executable, "-c", "import json, sys\nsys.path.insert(0, %r)\nfrom poascan import db, segments as S\ndb.init()\n" % ROOT + code],
                       env=env, capture_output=True, text=True, cwd=ROOT, timeout=300)
    if r.returncode: print(r.stderr[-1500:]); return None
    return json.loads(r.stdout.strip().splitlines()[-1])
T = CUT + 3600
a = boot(BASE, f"""db.write("INSERT INTO txs(id, type, from_addr, ts, atts, k, final) VALUES(?,?,?,?,?,?,?)", ("t1", "transfer", "poa1x", {T}, 5, 5, 1))
db.put_blob("epochs", [dict(epoch=0, ts={T} + 60, minted=1)])
print(json.dumps(dict(seg=db.q1("SELECT segment FROM txs WHERE id='t1'")["segment"])))""")
moved = json.loads(json.dumps(BASE)); moved["segments"][1]["start_ts"] = CUT + 7200
b = boot(moved, """from poascan import analytics as A
with S.use(1): n1 = len(A.epoch_rows())
with S.use(2): n2 = len(A.epoch_rows())
print(json.dumps(dict(seg=db.q1("SELECT segment FROM txs WHERE id='t1'")["segment"], n1=n1, n2=n2)))""")
check("moved boundary: tx after the old boundary starts in segment 2", a == {"seg": 2})
check("moved boundary: same tx in segment 1 after the config edit", bool(b) and b["seg"] == 1)
check("moved boundary: close record regrouped to segment 1", bool(b) and b["n1"] == 1 and b["n2"] == 0)

# ---- 3. current segment from /api/networks; a configured segment that has not started is not current ----
out = run(BASE, f"""
from poascan import segments as S
segs = S.SEGMENTS + [dict(n=3, chain_id="poa-mainnet-1", start_ts=4102444800)]
nw = dict(default_chain="poa-mainnet-1", chains=[dict(chain_id="poa-mainnet-1-segment1", status="halted"), dict(chain_id="poa-mainnet-1", status="live", default=True)])
print(json.dumps(dict(a=S.current_of(nw), b=S.current_of(nw, segs), c=S.current_of(None), d=S.live_chain(nw),
      e=S.current_of(dict(chains=[dict(chain_id="poa-mainnet-1-segment1", status="live", default=True)])))))
""")
check("networks: live default chain picks the segment", bool(out) and out["a"] == 2 and out["d"] == "poa-mainnet-1" and out["c"] == 2)
check("networks: a configured segment whose start time has not passed is not current", bool(out) and out["b"] == 2)
check("networks: live chain names an earlier segment", bool(out) and out["e"] == 1)

# ---- 4. swap corrections, boundary refund and balance-shown fill ----
out = run(BASE, f"""
from poascan import db; db.init()
from poascan.swap import state as ST
rows = [dict(offer_id="o1", status="delisted", created_ts={CUT} - 9000, last_open_seen={CUT} - 170, fill_txid=None, cancel_txid=None),
        dict(offer_id="o2", status="expired", created_ts={CUT} - 9000, last_open_seen={CUT} - 5000, fill_txid=None, cancel_txid=None),
        dict(offer_id="o3", status="cancelled", created_ts={CUT} - 9000, last_open_seen={CUT} - 100, fill_txid=None, cancel_txid="c"),
        dict(offer_id="de1ddefba3bb90cc3b67f1ee7a79616d48e28e5a0aee797db76e155a4bdfe953", status="expired", created_ts=1792789727, last_open_seen=1792797495, fill_txid=None, cancel_txid=None, poa=4000.0, fee_bp=100)]
ST.correct(rows)
import importlib; api = importlib.import_module('poascan.swap.api')
st = [api.settle(r, False, False) for r in rows]
print(json.dumps(dict(s=[r["status"] for r in rows], rb=rows[0].get("refund_basis"), st0=st[0], l4=dict((k, rows[3].get(k)) for k in ("fill_txid", "taker", "fill_ts", "fill_basis", "fill_final_ledger")), st3=st[3])))
""")
check("swaps: run", out is not None)
if out:
    check("swaps: open at the boundary reads refunded; older and cancelled offers unchanged", out["s"] == ["refunded", "expired", "cancelled", "filled"])
    rb = out["rb"] or {}
    check("swaps: refund_basis names the notice and tx", rb.get("notice_id") == BASE["segments"][1]["cut"]["notice_id"] and rb.get("notice_txid", "").startswith("e1c4ea26") and rb.get("ts") == CUT)
    check("swaps: refunded has no refund txid and no money moved", out["st0"]["refund_txid"] is None and out["st0"]["money_moved"] is False and out["st0"]["refund_at"] == rb.get("at"))
    l4 = out["l4"]
    check("swaps: balance-shown fill reads filled with its evidence", l4["fill_txid"].startswith("b994976f") and l4["taker"].startswith("poa1BNtY") and l4["fill_basis"] == "balances" and l4["fill_final_ledger"] is False)
    check("swaps: balance-shown fill credits the taker", out["st3"]["taker_credit"] == 3960.0 and out["st3"]["money_moved"] is True)

# ---- 5. carried supply baseline: last read less excluded closes, cross checked by the checkpoint read plus carried closes ----
h = BASE["segments"][0]["cut_height"]
out = run(BASE, f"""
from poascan import db, maint; db.init()
db.put_blob("epochs:s1", [dict(epoch=12, ts={CUT} - 64000, rewards=dict(poa1a="128140586.034237")), dict(epoch=13, ts={CUT} - 42000, rewards=dict(poa1a="45352884.298012")),
                          dict(epoch=14, ts={CUT} - 20000, rewards=dict(poa1a="13194373.072968"))])
db.add_snap("status", dict(supply="1384894817.712697", checkpoint_height={h}), ts={CUT} - 70000)
db.add_snap("status", dict(supply="1571582661.117914", checkpoint_height={h}), ts={CUT} - 600)
db.add_snap("status", dict(supply="1430247702.010709", checkpoint_height=1138), ts={CUT} + 600)
from poascan import analytics as A
for k in ("epochs", "epochs:s1"): A._cache.clear() if hasattr(A, "_cache") else None
print(json.dumps(maint.cut_baseline(), default=str))
""")
check("baseline: run", out is not None)
if out:
    check("baseline: last read less S1 E12 and S1 E14", out["before"] == "1430247702.010709" and out["intact"] is True and "E12" in out["basis"] and "E14" in out["basis"])
    check("baseline: cross check from the checkpoint read plus S1 E13", bool(out["cross_check"]) and out["cross_check"]["intact"] is True and "E13" in out["cross_check"]["basis"])

# ---- 6. /ops/network: no checkpoint advance across a boundary ----
day = CUT // 86400
out = run(BASE, f"""
from poascan import db, network as NW; db.init()
import time
it = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
db.add_snap("status", dict(agents_joined=5361, holders=739, supply="1", checkpoint_height=44003), ts=({day} - 1) * 86400 + 3600)
db.add_snap("status", dict(agents_joined=4941, holders=685, supply="1", checkpoint_height=1138), ts={CUT} + 600)
db.put_blob("networks", dict(chains=[dict(chain_id="poa-mainnet-1", status="live", default=True, checkpoint_height=1138)]))
out = json.loads(NW.report(it({day} - 1), it({day})))
print(json.dumps([d["mining"] for d in out["days"]]))
""")
check("ops network: run", out is not None)
if out:
    check("ops network: checkpoint_advance null across the boundary, checkpoint_segment set",
          out[-1].get("checkpoint_advance") is None and out[-1].get("checkpoint_segment") == 2 and out[0].get("checkpoint_segment") == 1)

# ---- 7. Not carried over, balance as of checkpoint, Unconfirmed rewards, pop-out breaks ----
h = BASE["segments"][0]["cut_height"]
out = run(BASE, f"""
import time
from poascan import db, history as HI, views as V, analytics as A, chartpop as CP, segments as S; db.init()
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
db.put_blob("epochs:s1", [dict(epoch=k, ts={CUT} - 90000 + k * 100, rewards=dict(poa1x="1")) for k in range(15)])
db.write("INSERT INTO anchors(height, chain, tx, state_root, anchored_by, memo, anchored_at, segment) VALUES(?,?,?,?,?,?,?,?)", ({h}, "base-mainnet", "0x1", "r", "g", "m", iso({CUT} - 70000), 1))
for i, ts in (("a1", {CUT} - 80000), ("a2", {CUT} - 60000), ("a3", {CUT} + 600)):
    db.write("INSERT INTO txs(id, type, from_addr, to_addr, amount, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?,?)", (i, "transfer", "poa1x", "poa1y", "1", ts, 5, 5, 1))
rows, _ = HI.txs_page("poa1x")
co = {{r["id"]: [r["segment"], r["carried_over"]] for r in rows}}
html = V.hist_rows(rows)
db.write("INSERT INTO accounts(addr, balance, balance_s, first_seen, last_seen) VALUES(?,?,?,?,?)", ("poa1y", 5.0, "5.000000", 1, {CUT} + 100))
db.put_blob("networks", dict(chains=[dict(chain_id="poa-mainnet-1-segment1", status="halted", checkpoint_height={h})]))
b1 = V.address_balance("poa1x", dict(balance="9.000000"), {CUT} + 900, None)
b2 = V.address_balance("poa1y", dict(balance="9.000000"), {CUT} + 900, None)
db.write("INSERT INTO accounts(addr, balance, balance_s, first_seen, last_seen) VALUES(?,?,?,?,?)", ("poa1z", 7.0, "7.000000", 1, {CUT} - 100))
b3 = V.address_balance("poa1z", None, None, None); b3["label"] = V.bal_asof(b3); b1["label"] = V.bal_asof(b1)
with S.use(1): rs = {{r["epoch"]: r["rewards_state"] for r in A.epoch_rows()}}
print(json.dumps(dict(co=co, html=html, b1=b1, b2=b2, b3=b3, rs=[rs.get(11), rs.get(12), rs.get(13), rs.get(14)], g12=S.unconfirmed_g(12), brk=CP.BREAK_AT_CUT)))
""")
check("tags: run", out is not None)
if out:
    check("tags: segment 1 tx after the final anchored checkpoint is not carried over", out["co"]["a2"] == [1, False] and out["co"]["a1"] == [1, None] and out["co"]["a3"] == [2, None])
    check("tags: Not carried over and Segment 1 tags on the address history", out["html"].count("Not carried over") == 1 and ">Segment 1<" in out["html"])
    check("balance: explorer-only copy is stale, as of checkpoint from networks", out["b1"]["stale"] is True and out["b1"]["as_of_checkpoint"] == h and out["b1"]["segment"] == 1)
    check("balance: agent list copy (current segment) wins when present", out["b2"]["source"] == "agents" and out["b2"]["balance"] == "5.000000" and out["b2"]["stale"] is False)
    check("balance: agent row last seen before the boundary is stale, labelled with its segment", out["b3"]["stale"] is True and out["b3"]["segment"] == 1 and out["b3"]["label"] == "As of Segment 1")
    check("balance: page label As of checkpoint", out["b1"]["label"] == f"As of checkpoint {h}")
    check("rewards: S1 E12 and E14 unconfirmed, E11 and E13 recorded", out["rs"] == ["recorded", "unconfirmed", "recorded", "unconfirmed"] and out["g12"] is True)
    check("pop-out: Agents, Holders, Agents / hr and Active Agents break at a boundary", sorted(out["brk"]) == ["active", "agents", "holders", "joins"])
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("pop-out: app.js draws one subpath per run between breaks", "d.breaks" in js and "runs.push([])" in js)

print("all segment config checks passed" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
