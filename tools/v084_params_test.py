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
cse = {x["key"]: x for x in NF.params_extra({"close_summary_from_epoch": 28})}
check("close_summary_from_epoch: terse E28 row", cse.get("close_summary_from_epoch", {}).get("value") == 28 and cse["close_summary_from_epoch"]["text"] == "E28" and cse["close_summary_from_epoch"]["label"] == "Close summary from")
check("close_summary_from_epoch absent: no row", not any(x["key"] == "close_summary_from_epoch" for x in NF.params_extra({"K": 5})))
al = {x["key"]: x for x in NF.params_extra({"att_log_from_epoch": 117})}
check("att_log_from_epoch: terse E117 row", al.get("att_log_from_epoch", {}).get("value") == 117 and al["att_log_from_epoch"]["text"] == "E117" and al["att_log_from_epoch"]["label"] == "Attestation log from")
check("att_log_from_epoch absent: no row", not any(x["key"] == "att_log_from_epoch" for x in NF.params_extra({"K": 5})))
v133 = {x["key"]: x for x in NF.params_extra({"chall_epoch_gate": True, "att_log_seal_from_epoch": 123, "settled_grade_from_epoch": 123, "settled_window_epochs": 17, "att_packs_from_epoch": 124})}
check("v0.133 keys: five terse rows", [(k, v["label"], v["text"]) for k, v in v133.items()] == [("chall_epoch_gate", "Challenge gate", "On"), ("att_log_seal_from_epoch", "Seals", "E123"),
      ("settled_grade_from_epoch", "Settled grades", "E123"), ("att_packs_from_epoch", "Packs", "E124"), ("settled_window_epochs", "Window", "17")])
pl = {x["key"]: x for x in NF.params_extra({"slot_prelatch_from_height": 1727006})}
check("v0.134 slot_prelatch_from_height: terse height row", pl["slot_prelatch_from_height"]["label"] == "Prelatch" and pl["slot_prelatch_from_height"]["text"] == "H1,727,006" and pl["slot_prelatch_from_height"]["value"] == 1727006)
check("v0.134 prelatch absent: no row", not any(x["key"] == "slot_prelatch_from_height" for x in NF.params_extra({"K": 5})))
sb = {x["key"]: x for x in NF.params_extra({"settled_bound_from_epoch": 127})}
check("v0.134.1 settled_bound_from_epoch: terse E127 row", sb["settled_bound_from_epoch"]["label"] == "Bound" and sb["settled_bound_from_epoch"]["text"] == "E127" and sb["settled_bound_from_epoch"]["value"] == 127)
check("v0.134.1 bound absent: no row", not any(x["key"] == "settled_bound_from_epoch" for x in NF.params_extra({"K": 5})))
dg = {x["key"]: x for x in NF.params_extra({"att_disk_guard_from_height": 1756020})}
check("v0.135 att_disk_guard_from_height: terse height row", dg["att_disk_guard_from_height"]["label"] == "Disk guard" and dg["att_disk_guard_from_height"]["text"] == "H1,756,020" and dg["att_disk_guard_from_height"]["value"] == 1756020)
check("v0.135 disk guard absent: no row", not any(x["key"] == "att_disk_guard_from_height" for x in NF.params_extra({"K": 5})))
_all_labels = [x["label"] for x in NF.params_extra({"chall_epoch_gate": True, "att_log_seal_from_epoch": 123, "settled_grade_from_epoch": 123, "settled_window_epochs": 17, "att_packs_from_epoch": 124, "slot_prelatch_from_height": 1727006, "settled_bound_from_epoch": 127, "att_disk_guard_from_height": 1756020})]
_words = [w.lower() for lab in _all_labels for w in lab.split()]
check("v0.133 through v0.135 labels repeat no word", len(_words) == len(set(_words)))
check("v0.133 values keep their type", v133["chall_epoch_gate"]["value"] is True and v133["att_packs_from_epoch"]["value"] == 124 and v133["settled_window_epochs"]["value"] == 17)
check("v0.133 null or absent key: no row", not any(x["key"] == "att_packs_from_epoch" for x in NF.params_extra({"att_packs_from_epoch": None, "K": 5})))
check("v0.133 gate off reads Off", {x["key"]: x for x in NF.params_extra({"chall_epoch_gate": False})}["chall_epoch_gate"]["text"] == "Off")
_words = [w.lower() for x in v133.values() for w in x["label"].split()]
check("v0.133 labels repeat no word", len(_words) == len(set(_words)))
V5 = ["poa15UH76CjkKBhirEVsYhiSPgutqQHNx8Lfy6pk2W5dhdNw", "poa1CemBVYnHu5z8yXQP7ScL6cT92HCGoqBmtE1GV51EiFXc", "poa12mhdE2egFdxrqSoRfUPwiqR4WCEHv8EurMTsZJBHKSUS",
      "poa1F6rGu8pjTGeA7SyqpAVdCwcmD4tW2t27Juxzn7nUxMzH", "poa1Gw8appS7VLqzk6RBBX6fFJiwTGwjyQEsUh9feAUdcCpB"]
v138 = {x["key"]: x for x in NF.params_extra({"att_log_recover_from_epoch": 135, "att_cap_skip_from_epoch": 136, "att_cap_skip_verifiers": V5, "batch_unpark_from_epoch": 136})}
check("v0.137 att_log_recover_from_epoch: terse E135 row", (v138["att_log_recover_from_epoch"]["label"], v138["att_log_recover_from_epoch"]["text"]) == ("Recovery", "E135"))
check("v0.138 cap skip: one row, E136 and 5 verifiers", (v138["att_cap_skip_from_epoch"]["label"], v138["att_cap_skip_from_epoch"]["text"]) == ("Cap skip", "E136 · 5 verifiers")
      and v138["att_cap_skip_from_epoch"]["value"] == dict(from_epoch=136, verifiers=V5) and "att_cap_skip_verifiers" not in v138)
check("v0.138 batch_unpark_from_epoch: terse E136 row", (v138["batch_unpark_from_epoch"]["label"], v138["batch_unpark_from_epoch"]["text"]) == ("Unpark", "E136"))
check("v0.138 cap skip with no list: epoch only", {x["key"]: x for x in NF.params_extra({"att_cap_skip_from_epoch": 136})}["att_cap_skip_from_epoch"]["text"] == "E136")
check("v0.138 keys absent: no rows", not any(x["key"] in v138 for x in NF.params_extra({"K": 5})))
_all = [x["label"] for x in NF.params_extra({"chall_epoch_gate": True, "att_log_seal_from_epoch": 123, "settled_grade_from_epoch": 123, "settled_window_epochs": 17, "att_packs_from_epoch": 124, "slot_prelatch_from_height": 1727006, "settled_bound_from_epoch": 127, "att_disk_guard_from_height": 1756020, "att_log_recover_from_epoch": 135, "att_cap_skip_from_epoch": 136, "att_cap_skip_verifiers": V5, "batch_unpark_from_epoch": 136})]
_words = [w.lower() for lab in _all for w in lab.split()]
check("v0.133 through v0.138 labels repeat no word", len(_words) == len(set(_words)))
check("v0.138 rows: no em or en dash", not any(d in json.dumps(v138, ensure_ascii=False) for d in DASH))
check("no em or en dash", not any(d in h + json.dumps(api) + json.dumps(NF.params_extra()) for d in DASH))
print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
