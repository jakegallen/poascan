"""Paused closes (1.26.192, LabLeak comment 6258): a close record that carries overlapped_halt or maintenance window fields
is tagged Paused (hover with the window times, local in the browser) on its epoch page, the /chain close history and the
Governance Settlement, Changes and Intake close views, and its API rows carry paused and pause. Absent fields (every close
record today) change nothing. No request is added. Usage: python3 tools/closepause_test.py (temp database, no network)."""
import json, os, re, sys, tempfile, time
os.environ["POASCAN_SEGMENTS"] = "1"
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "c.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, closepause as CP, governance as GV, agentapi as AG, server as SV, views as V, govv2 as GV2, intake as IK, indexer as I

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

# ---- parsing (no database)
check("absent: a record like today's E10 and E11 (no halt fields) gives None", CP.of_record({"epoch": 10, "ts": 1793095764, "basis": {"pending": {}, "settled": []}, "note": "v2.2"}) is None)
check("absent: fields_for gives paused false and pause null", CP.fields_for({"epoch": 1, "basis": {}}) == {"paused": False, "pause": None})
p = CP.of_record({"overlapped_halt": True})
check("overlapped_halt true: paused, no windows", p == {"paused": True, "overlapped_halt": True, "windows": [], "fields": ["overlapped_halt"]})
p = CP.of_record({"basis": {"overlapped_halt": {"start": 1793084400, "end": 1793091600}}})
check("basis.overlapped_halt object with a window: paused, window read", p["paused"] and p["windows"] == [{"start_ts": 1793084400, "end_ts": 1793091600}] and p["fields"] == ["basis.overlapped_halt"])
p = CP.of_record({"maintenance_windows": [{"from": "2026-10-27T07:00:00Z", "to": 1793091600000}, {"start_ts": "2026-10-27T01:00:00-07:00"}]})
check(f"maintenance_windows alone: paused; ISO (Z and offset), milliseconds, open end ({p['windows']})", p["paused"] and p["overlapped_halt"] is None
      and p["windows"] == [{"start_ts": 1793084400, "end_ts": 1793091600}, {"start_ts": 1793088000, "end_ts": None}])
check("ISO with offset reads as UTC", CP.ts_of("2026-10-27T01:00:00-07:00") == CP.ts_of("2026-10-27T08:00:00Z") == 1793088000)
check("milliseconds and numeric strings scale to seconds", CP.ts_of(1793088000000) == 1793088000 and CP.ts_of("1793088000") == 1793088000)
check("unreadable times are None", CP.ts_of("soon") is None and CP.ts_of(True) is None and CP.ts_of(-5) is None and CP.ts_of(None) is None)
p = CP.of_record({"overlapped_halt": False, "maintenance_window": {"start": 1793084400, "end": 1793091600}})
check("overlapped_halt false wins over a listed window: not paused, window still exposed", p["paused"] is False and len(p["windows"]) == 1)
check("overlapped_halt \"false\" and 0 are not paused", CP.of_record({"overlapped_halt": "false"})["paused"] is False and CP.of_record({"overlapped_halt": 0})["paused"] is False)
check("overlapped_halt null is ignored (absent)", CP.of_record({"overlapped_halt": None}) is None)
check("an empty window list is a field but not a pause", CP.of_record({"halt_windows": []}) == {"paused": False, "overlapped_halt": None, "windows": [], "fields": ["halt_windows"]})
check("a window with an end before its start is put in order", CP.window({"start": 20_0000_0000, "end": 1_900_000_000}) == {"start_ts": 1_900_000_000, "end_ts": 2_000_000_000})
check("tag is empty when absent or not paused", CP.tag(None) == "" and CP.tag(CP.of_record({"overlapped_halt": False})) == "")
t = CP.tag(CP.of_record({"overlapped_halt": {"start": 1793084400, "end": 1793091600}}))
check("tag: Paused, UTC title fallback, local-time template for app.js", ">Paused</span>" in t and "2026-10-27 07:00 UTC to 2026-10-27 09:00 UTC" in t
      and 'data-ltt="Paused: the close record lists a halt or maintenance window, {t:1793084400} to {t:1793091600}"' in t)
t = CP.tag(CP.of_record({"overlapped_halt": True}))
check("tag without windows says the record has no window times", "no window times in the record" in t)
src = open(os.path.join(ROOT, "poascan", "closepause.py")).read()
check("closepause makes no request (no urllib, no indexer fetch)", "urllib" not in src and "fetch(" not in src and "http" not in src.replace("https://", ""))
check("house style: no em or en dashes", all(chr(c) not in src for c in (0x2014, 0x2013)) and all(chr(c) not in open(__file__).read() for c in (0x2014, 0x2013)))

# ---- fixture: four closes; E2 overlapped a halt (basis.overlapped_halt plus a top-level maintenance window), E3 a flag only
NOW = int(time.time()); W0, W1 = NOW - 2 * 21600 - 5000, NOW - 2 * 21600 - 1000
ad = lambda i: "poa1" + format(i, "040d").replace("0", "Q")
def rec(n, extra=None, basis_extra=None):
    b = {"challenge_eligible": [ad(n + 1)], "established_after": [ad(n + 1)], "established_removed": [], "slashed": [], "attestations": {ad(1): 2},
         "pending": {f"p{n}": {"since": n, "kind": "short", "panel": []}}, "settled": [{"answer": f"s{n}", "from": ad(1), "passed": True, "jury": []}]}
    b.update(basis_extra or {})
    e = {"epoch": n, "ts": NOW - (4 - n) * 21600, "pool": 1e9, "rewards": {ad(1): 1e6}, "challenges": {ad(1): 1}, "propagation": {}, "basis": b}
    e.update(extra or {}); return e
eps = [rec(0), rec(1), rec(2, {"maintenance_windows": [{"start": W0, "end": W1}]}, {"overlapped_halt": True}), rec(3, {"overlapped_halt": True})]
db.init(); db.put_blob("epochs", eps)
db.put_blob("params", {"auto_epoch_seconds": 21600, "estab_ttl": 6, "pending_ttl_epochs": 16})
db.put_blob("status", {"epochs_closed": 4, "checkpoint_height": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW))})
A._cache.clear()
before = json.dumps(I.stats() if hasattr(I, "stats") else None, default=str)

rows = {r["epoch"]: r for r in A.epoch_rows()}
check("epoch rows: paused only on E2 and E3", [rows[n]["paused"] for n in range(4)] == [False, False, True, True])
check("epoch rows: pause null when absent", rows[0]["pause"] is None and rows[1]["pause"] is None)
check("E2 pause: both fields, the window, overlapped_halt true", rows[2]["pause"]["fields"] == ["maintenance_windows", "basis.overlapped_halt"]
      and rows[2]["pause"]["windows"] == [{"start_ts": W0, "end_ts": W1}] and rows[2]["pause"]["overlapped_halt"] is True)
d, _ = SV.api("/api/epochs", {})
check("API /api/v1/epochs carries paused and pause", [r["paused"] for r in d] == [False, False, True, True] and "pause" in d[0])
d2, _ = SV.api("/api/epoch/2", {})
check("API /api/v1/epoch/2 carries the window", d2["paused"] is True and d2["pause"]["windows"][0]["start_ts"] == W0)
cs = SV.to_csv(d)
check("CSV /api/epochs.csv has paused and pause columns", "paused" in cs.splitlines()[0] and "pause" in cs.splitlines()[0])
m = AG.TOOL_FN["get_epoch"]({"epoch": 2})
mj = json.dumps(m, default=str)
check("MCP get_epoch carries paused", '"paused": true' in mj)

def ptags(h): return len(re.findall(r'class="tag warn ptag"', h))
h2 = V.epoch(2); h2 = h2[1] if isinstance(h2, tuple) else h2
h1 = V.epoch(1); h1 = h1[1] if isinstance(h1, tuple) else h1
check("epoch page E2: Paused tag in the header with the local-time window", ptags(h2) == 1 and f"{{t:{W0}}} to {{t:{W1}}}" in h2)
check("epoch page E1: no Paused tag", ptags(h1) == 0)
hc = V.epochs_page({}); hc = hc[1] if isinstance(hc, tuple) else hc
check(f"/chain close history: Paused on E2 and E3 only ({ptags(hc)})", ptags(hc) == 2)
hs = GV.page({"tab": ["settlement"]}).split('id="settlement"')[1]
trs = re.findall(r"<tr><td><a href=\"/epoch/(\d+)[^\"]*\">E\d+</a>(.*?)</td>", hs)
check(f"Governance Settlement: Paused on every E2 and E3 close cell, never on E0 or E1 ({trs})", trs and all(("ptag" in t) == (int(n) >= 2) for n, t in trs) and {int(n) for n, _ in trs} == {0, 1, 2, 3})
hg = GV.page({"tab": ["changes"]})
check(f"Governance Changes: Paused on E2 and E3 ({ptags(hg)})", ptags(hg) == 2)
hi = GV.page({"tab": ["intake"]})
check(f"Governance Intake: Paused on E2 and E3 ({ptags(hi)})", ptags(hi) == 2)
sa = SV.governance_api("/api/governance/settlement", {})
check("API settlement closes carry paused", [c["paused"] for c in sa["closes"]] == [False, False, True, True])
ca = SV.governance_api("/api/governance/standing-changes", {})
check("API standing changes rows carry paused", sorted((r["close"], r["paused"]) for r in ca["rows"]) == [(0, False), (1, False), (2, True), (3, True)])
ia = SV.governance_api("/api/governance/intake", {})
check("API intake rows carry paused", sorted((r["close"], r["paused"]) for r in ia["rows"]) == [(0, False), (1, False), (2, True), (3, True)])
ov = SV.governance_api("/api/governance", {})
check("API governance overview latest_closes carry paused", {r["epoch"]: r["paused"] for r in ov.get("latest_closes", [])}.get(2) is True)
after = json.dumps(I.stats() if hasattr(I, "stats") else None, default=str)
check("no request added (indexer counters unchanged)", before == after)

# ---- absent everywhere: the same closes without the fields render no tag
db.put_blob("epochs", [rec(n) for n in range(4)]); A._cache.clear()
check("absent: every row paused false, pause null", all(r["paused"] is False and r["pause"] is None for r in A.epoch_rows()))
hx = V.epoch(2); hx = hx[1] if isinstance(hx, tuple) else hx
hc = V.epochs_page({}); hc = hc[1] if isinstance(hc, tuple) else hc
check("absent: no Paused tag on the epoch page, /chain or Governance", ptags(hx) == 0 and ptags(hc) == 0
      and sum(ptags(GV.page({"tab": [t]})) for t in ("settlement", "changes", "intake")) == 0)

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
