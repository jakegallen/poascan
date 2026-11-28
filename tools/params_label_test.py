"""Every /api/params key has a Protocol label or is on purpose left raw (1.26.437). Reads the live key list from POAScan's
own mirror (POASCAN_PARAMS_URL, default https://poascan.io/api/v1/params; one small GET, never minepoa.com). A key that is
neither labeled by netfacts.params_extra (or folded into another row, netfacts.FOLDED) nor listed in
tools/params_baseline.json fails, so a new minepoa param cannot ship unlabeled. Each labeled key's label shows on the
Network facts card the Protocol tab uses. Offline: the live read is skipped with a note and the fixture checks still run.
Usage: python3 tools/params_label_test.py"""
import json, os, sys, tempfile, urllib.request
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "pl.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from poascan import db, analytics as A, netfacts as NF
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
BASE = set(json.load(open(os.path.join(HERE, "params_baseline.json")))["keys"])
URL = os.environ.get("POASCAN_PARAMS_URL", "https://poascan.io/api/v1/params")

def unlabeled(p):
    lab = {x["key"] for x in NF.params_extra(p)}
    return sorted(k for k in p if k != "meta" and k not in lab and k not in NF.FOLDED and k not in BASE)

# fixture: a new key with no label fails, a labeled or baseline key passes
check("a new unlabeled key is caught", unlabeled({"K": 5, "brand_new_from_epoch": 140}) == ["brand_new_from_epoch"])
check("baseline and labeled keys pass", unlabeled({"K": 5, "att_disk_guard_from_height": 1756020, "att_cap_skip_verifiers": []}) == [])
check("FOLDED keys point at a labeled key", all(v in {x["key"] for x in NF.params_extra({v: 1})} for v in NF.FOLDED.values()))
check("baseline holds no labeled key", not (BASE & {x["key"] for x in NF.params_extra({k: 1 for k in BASE})}))

live = None
try:
    req = urllib.request.Request(URL, headers={"User-Agent": "poascan-ci/params-label-check", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r: live = json.load(r)
except Exception as e:
    print(f"note: live params not read ({type(e).__name__}); fixture checks only")
if isinstance(live, dict) and live:
    miss = unlabeled(live)
    check(f"every live /api/params key is labeled or baselined (missing: {', '.join(miss) or 'none'})", not miss)
    db.put_blob("params", live); A._cache.clear()
    h = NF.render_card()
    rows = NF.params_extra(live)
    check(f"each label shows on the Protocol facts card ({len(rows)} rows)", all(x["label"] in h for x in rows))
    check("no em or en dash in the rows", not any(d in json.dumps(rows, ensure_ascii=False) for d in ("\u2014", "\u2013")))
print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
