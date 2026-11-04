"""minepoa v0.84-slotlatch-cc44 params (1.26.262): the live /api/params with carry_correction and slot_latch_overrides is
data, not a notice; the params change records the two keys and no boundary; the signed release's engine and params hashes
(d30ea55b, 6de5b2fc) match the network facts; the release listing agrees with its own fields; both keys are listed with
terse labels on the Network facts card and in /api/v1/governance/econ; no em or en dash. Fixture: live reads saved in
tools/v084_params_fixture.json. Usage: python3 tools/v084_params_test.py (temp database, no network)."""
import json, os, sys, tempfile
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "v.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from poascan import db, analytics as A, strain as ST, protocol as PT, netfacts as NF, signed as SI, econ as EC, correction as CC

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
DASH = ("\u2014", "\u2013")
FX = json.load(open(os.path.join(HERE, "v084_params_fixture.json")))
P, REL, FACTS = FX["params"], FX["release"], FX["facts"]
db.init()

check("live params with both keys are data, not a notice", ST.detect("/api/params", P) is None)
check("live release is data, not a notice", ST.detect("/api/release", REL) is None)
check("slot latch reason text is not read as a strain notice", ST.detect("/api/params", {"slot_latch_overrides": P["slot_latch_overrides"]}) is None)

old = {k: v for k, v in P.items() if k not in ("carry_correction", "slot_latch_overrides")}
check("first params copy is the baseline", PT.params_check(old, now=1793830000) is None)
ch = PT.params_check(P, now=1793833372)
check(f"params change names the two keys ({ch})", ch == ["carry_correction", "slot_latch_overrides"])
ev = [e for e in PT.events("params_change")]
check("params change: no boundary keys, both added", ev and not ev[0]["boundaries"] and all(c.get("added") for c in ev[0]["changes"]))
check("same copy again: no new event", PT.params_check(P, now=1793833999) is None and len(PT.events("params_change")) == 1)

db.put_blob("release", REL)
cur = PT.current_release()
check("current signed release v0.84, params 6de5b2fc, engine d30ea55b", cur["version"] == "v0.84-slotlatch-cc44" and cur["params_sha256"].startswith("6de5b2fc") and cur["engine_sha256"].startswith("d30ea55b"))
prev = next(h for h in REL["history"] if h["version"] == "v0.83-carrycorr-inert")
check("server, worker and web client unchanged from v0.83", all(prev[k] == cur[k] for k in ("server_sha256", "worker_sha256", "web_client_sha256")))
cc = NF.crosscheck(FACTS, REL)
check(f"network facts cross check: match ({cc['verdict']})", cc["verdict"] == "match" and all(r["state"] == "match" for r in cc["rows"]))
body = dict({k: cur[k] for k in SI.RELEASE_FIELDS}, type="release")
check("release listing agrees with a signed body of the same fields", SI.listing_diff("release", cur, body) == [])
check("bundled table equals params carry_correction entries", dict(CC.table()) == {a: float(v) for a, v in P["carry_correction"]["entries"].items()})

db.put_blob("params", P); A._cache.clear()
px = {x["key"]: x for x in NF.params_extra()}
c = px["carry_correction"]["value"]
check("carry_correction: E44, 92 Agents, 940,522,943.638388, pinned table", (c["from_epoch"], c["agents"], c["total"], c["pinned_table"]) == (44, 92, 940522943.638388, True))
check("carry_correction label", px["carry_correction"]["label"] == "Carry correction" and px["carry_correction"]["text"] == "E44 · 92 Agents · 940.52M")
s = px["slot_latch_overrides"]
check("slot latch: 4 pinned slots, nonces 461 to 463 and 526", s["label"] == "Slot latch pins" and s["text"] == "4"
      and sorted(x["nonce"] for x in s["value"]["slots"]) == [461, 462, 463, 526])
db.put_blob(NF.BLOB, FACTS)
h = NF.render_card()
check("Network facts card lists both keys", "Carry correction" in h and "E44 · 92 Agents · 940.52M" in h and "Slot latch pins" in h)
db.put_blob(NF.BLOB, None)
h2 = NF.render_card()
check("card still lists them without a facts read", "Carry correction" in h2 and "Slot latch pins" in h2)
api = EC.api_block()
check("/api/v1/governance/econ params block", api["params"]["carry_correction"]["agents"] == 92 and api["params"]["slot_latch_overrides"]["count"] == 4)
check("no params keys: no rows", NF.params_extra({"K": 5}) == [])
check("no em or en dash", not any(d in h + json.dumps(api) + json.dumps(NF.params_extra()) for d in DASH))
print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
