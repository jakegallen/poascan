"""Network data asks (4b events feed, 4c route buckets) and the 1b /api/summary completion. 4c reads the route_checks table
POAScan already fills; 4b merges anchor/release/notice/record from the archive and the blobs POAScan mirrors (sources stubbed
here); 1b exposes closing_in and the open-epoch answers/graders on the homepage snapshot. Additive /api/v1, labels and links
only, counts only. Usage: python3 tools/network_data_test.py (temp database, no network)."""
import os, sys, tempfile, time
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, protocol as PR, maint as M, highlights as HL, views as V

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

db.init()
srv = open(os.path.join(ROOT, "poascan", "server.py")).read()

# ---- 4c: per-minute open / halted / down from route_checks ----
now = int(time.time()); m0 = (now // 60) * 60
seed = [
    (now, "hosted_mining", "200", 10, 1),       # current minute: open
    (now - 1, "hosted_mining", "503", 11, 0),   # current minute: halted (503 with halt text)
    (now - 2, "hosted_mining", "500", 12, 0),   # current minute: down (other failure)
    (m0 - 30, "hosted_mining", "200", 9, 1),    # previous minute: open
    (now, "grading", "200", 8, 1),              # a second route, filtered out below
]
db.write("INSERT INTO route_checks(ts,route,code,ms,ok) VALUES(?,?,?,?,?)", seed, many=True)
rb = A.route_buckets("hosted_mining", 60)
bm = {b[0]: b[1:] for b in rb["buckets"]}
check("4c current minute splits open/halted/down", bm.get(m0) == [1, 1, 1])
check("4c previous minute counts a clear read as open", bm.get(m0 - 60) == [1, 0, 0])
check("4c route filter counts only that route (grading read in the same minute is excluded)", bm.get(m0) == [1, 1, 1])
check("4c lists every route seen in the window as a pick-list", rb["routes"] == ["grading", "hosted_mining"])
check("4c minutes clamp to 180", A.route_buckets(None, 99999)["minutes"] == 180)
check("4c minutes floor at 1 on junk", A.route_buckets(None, "x")["minutes"] == 60)
check("server routes /api/network/route-buckets", '"/api/network/route-buckets"' in srv and "A.route_buckets(" in srv)

# ---- 4b: merged anchor | release | notice | record feed ----
A.anchors_latest = lambda n=20: [
    dict(height=44010, chain="base", tx="0xabc", anchored_at="2026-11-18T20:00:00+00:00"),
    dict(height=44011, chain="solana", tx="sig123", anchored_at="2026-11-18T20:05:00Z")]
PR.releases = lambda rel=None: [dict(version="v1.9", ts=1795000000, txid="reltx")]
M._active_notices = lambda: [dict(id="n1", msg="Grading paused for hardening", issued_ts=1795000500)]
HL.data = lambda now=None: dict(firsts=[dict(label="First answer in this segment", ts=1795000900, tx="ftx", found=True),
                                         dict(label="First seal", found=False)])
ev = A.network_events(None, 20)["events"]
by = {}
for e in ev: by.setdefault(e["type"], []).append(e)
check("4b carries all four kinds", set(by) == {"anchor", "release", "notice", "record"})
check("4b anchor labels the chain and links the explorer", any(e["label"] == "Checkpoint 44010 anchored to Base" and e["url"] == "https://basescan.org/tx/0xabc" for e in by["anchor"]))
check("4b anchor handles the Z suffix and Solana explorer", any(e["url"] == "https://solscan.io/tx/sig123" for e in by["anchor"]))
check("4b release labels the version and links the POA tx", by["release"][0] == dict(ts=1795000000, type="release", label="Release v1.9", url="/tx/reltx"))
check("4b notice shows its short text, no url", by["notice"][0]["label"] == "Grading paused for hardening" and by["notice"][0]["url"] is None)
check("4b record keeps only found firsts and links the tx", len(by["record"]) == 1 and by["record"][0]["url"] == "/tx/ftx")
check("4b is newest first", [e["ts"] for e in ev] == sorted((e["ts"] for e in ev), reverse=True))
check("4b type filter keeps one kind", {e["type"] for e in A.network_events("release", 20)["events"]} == {"release"})
check("4b unknown type falls back to all", A.network_events("bogus", 20)["type"] is None)
check("4b limit is capped at 20", A.network_events(None, 999)["events"] == ev)
M._active_notices = lambda: [dict(id="n2", msg="x" * 200, issued_ts=1795000600)]
check("4b long notice text is trimmed to a label", A.network_events("notice", 20)["events"][0]["label"].endswith("…"))
check("server routes /api/network/events", '"/api/network/events"' in srv and "A.network_events(" in srv)

# ---- 1b: the homepage snapshot (/api/summary) carries closing_in + the open-epoch answers/graders ----
A.open_epoch = lambda: dict(epoch=99, last_close=1795000000, est_close=1795021600, period=21600, pool=1e9,
                            answers_so_far=359, graders_so_far=262, closing_in=1234)
snap = V.live_snapshot()
ep = snap.get("epoch") or {}
check("1b snapshot top-level closing_in", snap.get("closing_in") == 1234)
check("1b snapshot open-epoch answers_so_far", ep.get("answers_so_far") == 359)
check("1b snapshot open-epoch graders_so_far", ep.get("graders_so_far") == 262)
check("1b snapshot open-epoch closing_in", ep.get("closing_in") == 1234)

print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
