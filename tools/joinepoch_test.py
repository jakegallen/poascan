"""Join epoch (1.26.168): Never established's joined segment comes from the join time (config segment boundaries), never
from the source, and a missing epoch is worked out from that segment's close records. hdr: a segment 1 join tx with no
epoch; E12 to E14: minepoa's joined_epoch for Agents who joined before the cut, labelled S1 E12 and so on, not E12.
Two segments from poascan/segments.json (cut at 1792875660), temp database, no network. Usage: python3 tools/joinepoch_test.py"""
import os, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ.pop("POASCAN_SEGMENTS", None)
os.environ.update(POASCAN_DB=os.path.join(tmp, "j.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import db
db.init()
db.put_blob("networks", {"default_chain": "poa-mainnet-1", "chains": [{"chain_id": "poa-mainnet-1", "status": "live", "default": True, "checkpoint_height": 59755}]})
from poascan import segments as SG, govv2 as GV2, analytics as A
CUT = SG.BY_N[SG.CURRENT]["start_ts"]; S1 = [s["n"] for s in SG.SEGMENTS if s["n"] != SG.CURRENT][0]
check(f"two segments from the config, current {SG.CURRENT}, cut {CUT}", SG.CURRENT == 2 and S1 == 1 and CUT == 1792875660)
H = "poa15VA8Smq8kAt8jzx9N9B4cp11zj4QZ2cQv2oMtYmey8em"; M = "poa1" + "M" * 44; N = "poa1" + "N" * 44; Q = "poa1" + "Q" * 44
# segment 1 closes every 6 h up to E14 (the last one 3 h before the cut); segment 2 E0..E7 from the cut
s1 = [{"epoch": k, "ts": CUT - 3 * 3600 - (14 - k) * 21600, "rewards": {}, "basis": {}} for k in range(15)]
s2 = [{"epoch": k, "ts": CUT + (k + 1) * 21600, "rewards": {}, "basis": {}} for k in range(8)]
db.put_blob(SG.blob_kind(S1), s1); db.put_blob(SG.blob_kind(SG.CURRENT), s2)
now = int(time.time())
hdr_join = CUT - 3 * 3600 - 3 * 21600 - 600    # 10 min before segment 1's E11 close: epoch 11
db.write("INSERT INTO txs(id,type,from_addr,epoch,ts,final,segment) VALUES(?,?,?,?,?,?,?)", ("aa" * 32, "join", H, None, hdr_join, 1, S1))
e12 = CUT - 3 * 3600 - 2 * 21600 - 100         # inside segment 1's E12
rows = [(H, 511996.651201, now - 60, 8), (M, 0.0, e12, 12), (N, 0.0, CUT + 21600 + 50, None), (Q, 0.0, CUT - 60, None)]
db.write("INSERT OR REPLACE INTO accounts(addr,balance,balance_s,api_ts,api_joined_epoch,first_seen,last_seen) VALUES(?,?,?,?,?,?,?)",
         [(a, b, str(b), t, je, t, now) for a, b, t, je in rows], many=True)

check(f"epoch_at: before segment 1's E11 close is E11 ({GV2.epoch_at(hdr_join)})", GV2.epoch_at(hdr_join) == (S1, 11))
check(f"epoch_at: after segment 1's last close and before the cut is E15 ({GV2.epoch_at(CUT - 60)})", GV2.epoch_at(CUT - 60) == (S1, 15))
check(f"epoch_at: segment 2 after its E0 close is E1 ({GV2.epoch_at(CUT + 21600 + 50)})", GV2.epoch_at(CUT + 21600 + 50) == (2, 1))
check(f"epoch_at: segment 2 before its first close is E0 ({GV2.epoch_at(CUT + 10)})", GV2.epoch_at(CUT + 10) == (2, 0))

A._cache.clear(); nv = {r["address"]: r for r in GV2.never_established()}
h = nv[H]
check(f"hdr: join tx with no epoch gets segment 1, E11 from its time ({h['joined_segment']}, {h['joined_epoch']}, {h['joined_ts']})",
      h["joined_segment"] == S1 and h["joined_epoch"] == 11 and h["joined_ts"] == hdr_join)
m = nv[M]
check(f"E12 case: minepoa's joined_epoch 12 with a join time before the cut is segment 1 ({m['joined_segment']}, {m['joined_epoch']})", m["joined_segment"] == S1 and m["joined_epoch"] == 12)
check(f"no epoch from minepoa, joined in segment 2: worked out from the time ({nv[N]['joined_segment']}, {nv[N]['joined_epoch']})", nv[N]["joined_segment"] == 2 and nv[N]["joined_epoch"] == 1)
check(f"no epoch from minepoa, joined just before the cut: S1 E15 ({nv[Q]['joined_segment']}, {nv[Q]['joined_epoch']})", nv[Q]["joined_segment"] == S1 and nv[Q]["joined_epoch"] == 15)

def href(tab, **kw): return f"/governance?tab={tab}"
html = GV2.never_tab({}, href, lambda **kw: "")
check("chart labels earlier segments S1 E11, S1 E12, S1 E15; the current segment plain E1", all(x in html for x in ("S1 E11", "S1 E12", "S1 E15", ">E1<")) or all(x in html for x in ("S1 E11", "S1 E12", "S1 E15", "E1")))
check("chart: every row is in it", sum(1 for r in nv.values() if r["joined_epoch"] is not None) == 4)
i11, i12, i1 = html.find("S1 E11"), html.find("S1 E12"), html.find("S1 E15")
check("chart bars ordered by segment then epoch", 0 <= i11 < i12 < i1)
check("no en or em dashes", "\\u2013" not in html and "\\u2014" not in html and "\u2013" not in html and "\u2014" not in html)

print(f"{len(fails)} failed" if fails else "all passed"); sys.exit(1 if fails else 0)
