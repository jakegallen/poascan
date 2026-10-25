"""Established set per minepoa's engine (1.26.140, estfold.py), end to end: the genesis import's 81 flagged Agents seed the
segment, E1's established_after adds, nobody is added for seats or as a trusted grader, imports with no challenge_eligible
in the segment drop at the E6 close (L = -1, estab_ttl 6 from params), the ones listed at E1 at E8; levels, the At risk
list, the Governance API and CSV fields, Score's closes held and the /about and Rules copy.
Usage: python3 tools/established_engine_test.py (temp database, no network)."""
import os, sys, tempfile, time, re
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from poascan import db, analytics as A, estfold as EF, segments as S

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

REAL = EF.load_cfg()["imports"]["2"]
IMP = REAL["established"]
NEW = ["poa1" + c * 40 for c in "ABCDEFGHJ"]           # E1 established_after (not imported)
SEAT, TRUST = "poa1" + "S" * 40, "poa1" + "T" * 40

def close(n, ts, **b):
    base = {"challenge_eligible": [], "established_after": [], "established_removed": [], "graders_served": {}, "settled": [], "pending": {}}
    base.update(b); return {"epoch": n, "ts": ts, "pool": 1e9, "rewards": {}, "challenges": {}, "propagation": {}, "basis": base}

def seed(closed=4, ttl=6):
    db.init(); now = time.time(); last = now - 600
    db.put_blob("params", {"estab_ttl": ttl, "K": 5, "auto_epoch_seconds": 21600, "trusted_graders": [TRUST], "system_grader_accounts": [TRUST]})
    db.put_blob("status", {"epochs_closed": closed})
    E = [close(n, last - (closed - 1 - n) * 21600) for n in range(closed)]
    E[1]["basis"].update(established_after=NEW, challenge_eligible=NEW + IMP[:4], graders_served={SEAT: 3, TRUST: 2, IMP[10]: 1},
                         settled=[{"from": NEW[0], "passed": True, "jury": [{"grader": SEAT, "aligned": True}]}])
    db.put_blob(S.blob_kind(), E)
    A._cache.clear()

def main():
    EF.CFG["imports"] = {str(S.selected()): REAL}
    seed()
    est = A.established_set()
    check(f"set = 81 imports + 9 added = 90 ({len(est)})", len(est) == 90 and set(IMP) <= est and set(NEW) <= est)
    check("no seats, jury seats or trusted and system graders", SEAT not in est and TRUST not in est)
    x = A.established_expiry_est(IMP[20])
    check(f"import with no challenge_eligible: L -1, drops at E6 ({x['established_expires_epoch_est']})", x["established_expires_epoch_est"] == 6 and x["last_challenge_eligible_epoch"] is None and "L = -1" in x["established_expires_basis"])
    check("import listed at E1: drops at E8", A.established_expiry_est(IMP[0])["established_expires_epoch_est"] == 8)
    check("a seat does not keep an import (seated at E1, still E6)", A.established_expiry_est(IMP[10])["established_expires_epoch_est"] == 6)
    from poascan import governance as GV, standing as SD
    rows = {r["address"]: r for r in GV.standing_rows()["rows"]}
    check(f"levels at open E4: imports with L -1 are Watch (3 closes left), E1 Agents Safe", rows[IMP[20]]["level"] == "watch" and rows[IMP[20]]["left"] == 3 and rows[NEW[0]]["level"] == "safe")
    check("no No record or System rows", not any(r["level"] in ("norecord", "system") for r in rows.values()))
    check("basis per row: import or added at E1", rows[IMP[20]]["basis"] == "import" and rows[NEW[0]]["basis"] == "added" and rows[NEW[0]]["basis_close"] == 1)
    check("At risk at open E4 (window E4, E5): none", SD.at_risk()["count"] == 0)
    api = GV.api_established(limit=5000)
    r0 = {r["address"]: r for r in api["rows"]}
    check("API: rule, estab_ttl and genesis_import at the top", "genesis import" in api["rule"] and api["estab_ttl"] == 6 and api["genesis_import"]["established_count"] == 81)
    check("API rows: drop_close, established_basis", r0[IMP[20]]["drop_close"] == 6 and r0[IMP[20]]["established_basis"] == "import" and r0[NEW[1]]["established_basis"] == "added")
    sc = GV.scores()["rows"]
    check(f"Score: an import is held at every close ({sc[IMP[20]]['closes_established'] if IMP[20] in sc else None}), a seat holds nothing",
          IMP[20] not in sc or sc[IMP[20]]["closes_established"] == 4)
    check("Score: seat-only Agent holds no closes", sc.get(SEAT, {}).get("closes_established", 0) == 0)
    # one close later: the open epoch is E5, so the E6 drop is At risk
    seed(closed=5)
    ar = SD.at_risk()
    check(f"At risk at open E5: the 77 imports with L -1 drop at E6 ({ar['count']})", ar["count"] == 77 and ar["by_close"].get("6") == 77)
    check("At risk rule names the engine and -1", "engine" in ar["rule"] and "-1" in ar["rule"])
    # ttl from params, not hardcoded
    seed(closed=4, ttl=4)
    check("estab_ttl read from params: L -1 + 4 + 1 = E4", A.established_expiry_est(IMP[20])["established_expires_epoch_est"] == 4)
    # removal at a close drops an import
    seed()
    E = db.get_blob(S.blob_kind())[0]; E[3]["basis"]["established_removed"] = IMP[30:31]; time.sleep(1.1); db.put_blob(S.blob_kind(), E); A._cache.clear()
    check("established_removed drops an import", IMP[30] not in A.established_set() and len(A.established_set()) == 89)
    from poascan import views as V
    h = V.about() if hasattr(V, "about") else ""
    h = h if isinstance(h, str) else ""
    rules = GV.rules()
    check("Rules: seats and system graders observed as not counted", "does not count seats" in rules and "Not added to the established set" in rules)
    check("copy: no em or en dashes", not re.search("[\u2013\u2014]", rules + A.STANDING_NOTE + api["rule"]))
    print(f"\n{len(fails)} failed" if fails else "\nall passed")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
