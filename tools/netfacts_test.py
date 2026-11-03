"""Authoritative network facts and the drift cross check (poascan/netfacts.py).

Covers the pure parsing (economics params, system accounts v1 to v5 liveness, trusted graders, the engine and params
hashes) and the cross check verdict: match when POAScan's derived engine and params hashes equal the authoritative
ones, drift when any differs, unknown when the facts are unavailable or a hash is missing. Also the fail soft render
(no facts keeps the derived values with an "authoritative source unavailable" note, never raises), the allowlist entry
and the job cadence. Temp database, no network. Usage: python3 tools/netfacts_test.py"""
import os, sys, tempfile, time
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, netfacts as NF, indexer as I, protocol as P

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

def addr(c): return "poa1" + c * 40

def main():
    db.init()
    der = NF.derived_hashes()
    check("derived engine and params hashes come from the signed release", bool(der["engine"]) and bool(der["params"]) and bool(der["version"]))

    # ---- no facts: fail soft, unknown verdict, derived values kept ----
    cc = NF.crosscheck()
    check("no facts read: available False, verdict unknown", cc["available"] is False and cc["verdict"] == "unknown")
    check("no facts read: every hash row is unknown, derived still shown", all(r["state"] == "unknown" for r in cc["rows"]) and all(r["derived"] for r in cc["rows"]))
    html = NF.render_card()
    check("render fails soft with the unavailable note", "Authoritative source unavailable" in html and "authoritative" in html)
    check("no em or en dash on the facts card", "\u2014" not in html and "\u2013" not in html)
    check("economics(None) lists every key with a None value", [e["value"] for e in NF.economics(None)] == [None] * len(NF.ECON))
    check("system_accounts(None) and trusted_graders(None) are empty, never raise", NF.system_accounts(None) == [] and NF.trusted_graders(None) == [])

    # ---- authoritative facts that agree with the derived hashes: match ----
    facts = {"economics": {"estab_intake_floor": 5, "estab_intake_rate": 0.1, "estab_ttl": 6, "grade_quorum": 3,
                           "panel_size": 5, "pending_ttl_epochs": 16, "auto_epoch_seconds": 21600, "K": 5},
             "system_accounts": {"v1": {"address": addr("1"), "live": True}, "v2": {"address": addr("2"), "status": "down"},
                                 "v3": {"address": addr("3")}, "v4": {"address": addr("4"), "live": True}, "v5": {"address": addr("5"), "live": True}},
             "trusted_graders": [addr("t"), addr("u")],
             "engine_sha256": der["engine"], "params_sha256": der["params"]}
    db.put_blob(NF.BLOB, facts)
    cc = NF.crosscheck()
    check("facts agree: available True, verdict match", cc["available"] is True and cc["verdict"] == "match")
    check("both hash rows read match", [r["state"] for r in cc["rows"]] == ["match", "match"])

    econ = {e["key"]: e["value"] for e in NF.economics()}
    check("economics parsed from the facts block (floor, rate, ttl, quorum, panel, pending, auto epoch, K)",
          econ == {"estab_intake_floor": 5, "estab_intake_rate": 0.1, "estab_ttl": 6, "grade_quorum": 3, "panel_size": 5,
                   "pending_ttl_epochs": 16, "auto_epoch_seconds": 21600, "K": 5})
    acc = {a["id"]: a["live"] for a in NF.system_accounts()}
    check("system accounts v1 to v5 with liveness (bool from live, string status, None when absent)",
          acc == {"v1": True, "v2": False, "v3": None, "v4": True, "v5": True})
    addrs = {a["id"]: a["address"] for a in NF.system_accounts()}
    check("each system account carries its address", addrs["v1"] == addr("1") and addrs["v5"] == addr("5"))
    check("trusted graders parsed", NF.trusted_graders() == [addr("t"), addr("u")])
    check("facts_hashes reads engine and params", NF.facts_hashes() == {"engine": der["engine"], "params": der["params"]})
    html = NF.render_card()
    check("match card shows Matches consensus and the economics and system account rows", "Matches consensus" in html and "Intake floor" in html and "v1" in html)
    check("no em or en dash on the match card", "\u2014" not in html and "\u2013" not in html)

    # ---- a drift in one hash is a real signal ----
    db.put_blob(NF.BLOB, dict(facts, engine_sha256="ff" * 32))
    cc = NF.crosscheck()
    check("one hash differs: verdict drift", cc["verdict"] == "drift")
    check("the engine row reads drift, the params row still matches", {r["name"]: r["state"] for r in cc["rows"]} == {"engine": "drift", "params": "match"})
    check("drift card shows Drift", "Drift" in NF.render_card())

    # ---- a nested hashes block and a list of system accounts both parse ----
    db.put_blob(NF.BLOB, {"hashes": {"engine": der["engine"], "params": der["params"]},
                          "accounts": [{"id": "v1", "address": addr("1"), "state": "live"}, {"name": "v2", "addr": addr("2"), "alive": False}]})
    cc = NF.crosscheck()
    check("a nested hashes block still cross checks to match", cc["verdict"] == "match")
    check("a list of system accounts parses with liveness", [(a["id"], a["live"]) for a in NF.system_accounts()] == [("v1", True), ("v2", False)])

    # ---- a missing authoritative hash leaves that pair unknown, never a false drift ----
    db.put_blob(NF.BLOB, {"params_sha256": der["params"]})
    cc = NF.crosscheck()
    check("facts present but engine hash absent: engine unknown, params match, verdict match on the one pair",
          {r["name"]: r["state"] for r in cc["rows"]} == {"engine": "unknown", "params": "match"} and cc["verdict"] == "match")
    db.put_blob(NF.BLOB, {"economics": {"K": 5}})
    cc = NF.crosscheck()
    check("facts present but no hash at all: verdict unknown, not drift", cc["verdict"] == "unknown")

    # ---- allowlist: the new endpoints are reachable, traversal is not ----
    check("allowlist admits /api/network-facts", bool(I.ALLOWED.match("/api/network-facts")))
    check("allowlist admits /api/established and the per-address form", bool(I.ALLOWED.match("/api/established")) and bool(I.ALLOWED.match("/api/established/" + addr("a"))))
    check("allowlist admits close-report, settled and expiry-schedule", all(I.ALLOWED.match("/api/" + p) for p in ("close-report", "settled", "expiry-schedule")))
    check("allowlist refuses a traversal under established", not I.ALLOWED.match("/api/established/../params"))

    # ---- the job is scheduled hourly, conditional, gated on its own endpoint ----
    jobs = {j[0]: (j[2], j[3]) for j in I.JOBS}
    check("netfacts job every hour, gated on /api/network-facts", jobs.get("netfacts") == (3600, "/api/network-facts"))
    check("EVERY carries the facts cadence (hourly)", I.EVERY.get("/api/network-facts") == 3600)

    # a conditional read stores a 200 and keeps the stored copy on a 304
    seen = []
    def fake(path, timeout=60, endpoint=None, cond=False, soft=False, gate=None):
        seen.append((path, cond)); return {"engine_sha256": der["engine"], "params_sha256": der["params"]}
    I.fetch = fake
    db.put_blob(NF.BLOB, None); NF.fetch_facts()
    check("fetch_facts reads /api/network-facts conditionally and stores the blob", seen == [("/api/network-facts", True)] and NF.available())
    def fake304(path, **k): seen.append(path); return I.NOT_MODIFIED
    I.fetch = fake304; before = NF.cached()[0]
    r = NF.fetch_facts()
    check("a 304 keeps the stored facts (returns None, blob unchanged)", r is None and NF.cached()[0] == before)
    # a backing off endpoint is skipped, never fetched
    db.write("INSERT INTO fetch_log(endpoint,last_err,fails,next_at,err) VALUES('/api/network-facts',?,3,?,'HTTP 503')", (int(time.time()), int(time.time()) + 600))
    calls = []
    I.fetch = lambda *a, **k: calls.append(a) or {}
    NF.job()
    check("job skips the fetch while the endpoint is backing off", calls == [])

    # ---- established set cross check (/api/established) ----
    from poascan import analytics as A, estfold as EF, segments as S
    db.put_blob(NF.EST_BLOB, None)
    check("no established copy: reconcile fails soft (available False, agree None, derived size reported)",
          (r := NF.established_reconcile())["available"] is False and r["agree"] is None and isinstance(r["derived_size"], int))
    check("addr_established and addr_row fail soft to None with no copy", NF.addr_established(addr("a")) is None and NF.addr_row(addr("a"), True) is None)

    # a known derived set: segment genesis import of A1 and A2, no close changes
    A1, A2, A3 = addr("1"), addr("2"), addr("3")
    seg = S.selected()
    EF.CFG["imports"] = {str(seg): {"established": [A1, A2], "established_count": 2, "url": "x", "sha256": "x", "final_checkpoint_height": 1, "agents": 2}}
    db.put_blob("params", {"estab_ttl": 6}); db.put_blob(S.blob_kind(), [])
    A._cache.clear()
    check("derived established set is A1 and A2", set(A.established_set()) == {A1, A2})

    # authoritative set: A1 (agrees) and A3 (only authoritative); A2 is only in the derivation
    db.put_blob(NF.EST_BLOB, [{"address": A1, "established_since": 3, "expires_after": 10}, {"address": A3, "since": 5}])
    aset, detail = NF.authoritative_established()
    check("authoritative set parsed from a list of rows", aset == {A1, A3} and detail[A1]["since"] == 3 and detail[A1]["expires"] == 10)
    rec = NF.established_reconcile()
    check("reconcile: not agree, A2 only in derivation, A3 only authoritative",
          rec["available"] and rec["agree"] is False and rec["only_derived"] == [A2] and rec["only_authoritative"] == [A3]
          and rec["derived_size"] == 2 and rec["authoritative_size"] == 2)
    row = NF.addr_row(A1, True)
    check("A1 chip: authoritative YES, since and expires shown, no drift (agrees with derivation)",
          row[0] == "Established (authoritative)" and "since E3" in row[1] and "expires after E10" in row[1] and "Drift" not in row[1] and ">YES<" in row[1])
    check("A3 chip: authoritative YES but derived False is a Drift", "Drift" in NF.addr_row(A3, False)[1])
    check("A2 chip: authoritative NO but derived True is a Drift", "Drift" in NF.addr_row(A2, True)[1] and ">NO<" in NF.addr_row(A2, True)[1])
    html = NF.render_card()
    check("facts card carries the Established set reconciliation (Differs)", "Established set" in html and "Differs" in html)
    check("no em or en dash on the reconciliation card", "\u2014" not in html and "\u2013" not in html)

    # agreement reads Matches derivation; a plain list of addresses parses too
    db.put_blob(NF.EST_BLOB, [A1, A2])
    rec = NF.established_reconcile()
    check("identical sets agree (Matches derivation), a plain address list parses", rec["agree"] is True and rec["only_derived"] == [] and rec["only_authoritative"] == [])
    check("render shows Matches derivation when the sets agree", "Matches derivation" in NF.render_card())
    # a dict wrapper around the list
    db.put_blob(NF.EST_BLOB, {"established": [A1, A2], "count": 2})
    check("a dict wrapping the established list parses", NF.authoritative_established()[0] == {A1, A2})

    # the established job: conditional read, 304 keeps the copy, backoff skips
    check("established_auth job every hour, gated on /api/established", jobs.get("established_auth") == (3600, "/api/established"))
    check("EVERY carries the established cadence (hourly)", I.EVERY.get("/api/established") == 3600)
    seen2 = []
    I.fetch = lambda path, timeout=60, endpoint=None, cond=False, soft=False, gate=None: seen2.append((path, cond)) or [A1, A2, A3]
    db.put_blob(NF.EST_BLOB, None); NF.fetch_established()
    check("fetch_established reads /api/established conditionally and stores the blob", seen2 == [("/api/established", True)] and NF.established_available())
    I.fetch = lambda *a, **k: I.NOT_MODIFIED; before2 = db.get_blob(NF.EST_BLOB)[0]
    check("a 304 keeps the stored established copy", NF.fetch_established() is None and db.get_blob(NF.EST_BLOB)[0] == before2)
    db.write("INSERT INTO fetch_log(endpoint,last_err,fails,next_at,err) VALUES('/api/established',?,3,?,'HTTP 503')", (int(time.time()), int(time.time()) + 600))
    calls2 = []; I.fetch = lambda *a, **k: calls2.append(a) or []
    NF.established_job()
    check("established_job skips the fetch while the endpoint is backing off", calls2 == [])

    print(f"\n{len(fails)} failed" if fails else "\nall ok")
    sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
