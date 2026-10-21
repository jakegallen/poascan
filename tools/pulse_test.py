"""Parse test for poascan/pulse.py against a sanitized probe result (tools/pulse_fixture.json: endpoints, codes and a
generic halt notice only). Usage: python3 tools/pulse_test.py (temp database, no network)."""
import os, sys, json, time, copy, tempfile
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, pulse as P, halts as H, maint as M

FIX = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_fixture.json")))
fails = []
def check(name, cond): print(("ok   " if cond else "FAIL ") + name); cond or fails.append(name)

def main():
    db.init()
    g, seen = P.parse(FIX)
    check("halted 503 on hosted/challenge or hosted/me: hosted mining paused", g.get("Hosted mining") == "paused")
    check("challenges, agent profile, assignments paused", all(g.get(k) == "paused" for k in ("Challenges", "Agent profile", "Assignments")))
    check("502 without the halt notice leaves path actions to the doc", "Path actions" not in g)
    check("status and other endpoints never become groups", set(g) <= set(H.GROUPS))
    back = copy.deepcopy(FIX)
    for r in back["results"]: r.update(code=200, body={})
    g2, _ = P.parse(back, seen)
    check("200 after halted reads back", g2.get("Hosted mining") == "back" and g2.get("Assignments") == "back")
    g3, _ = P.parse(back, ())
    check("200 never halted says nothing (doc decides)", g3 == {})
    half = copy.deepcopy(FIX); half["results"][1].update(code=200, body={})
    check("one hosted endpoint still halted keeps hosted mining paused", P.parse(half)[0]["Hosted mining"] == "paused")
    for bad, why in ((dict(FIX, age_s=901), "stale"), ({"age_s": 1}, "no results"), ([], "not a dict")):
        try: P.parse(bad); ok = False
        except ValueError: ok = True
        check(f"{why} probe raises (doc fallback)", ok)
    # merge: probe primary over the doc, doc fills the rest; stored blob carries derived states only
    db.put_blob(H.BLOB, dict(groups={"Hosted mining": "planned", "Answers": "planned", "Joining": "planned"}, stays_live=["Explorer"], ts=int(time.time())))
    db.put_blob(P.BLOB, dict(groups=g, seen=seen, ok=True, ts=int(time.time())))
    c = H.current()
    check("merged: probe wins for hosted mining", c["groups"]["Hosted mining"] == "paused" and c["source"] == "probe+tracker")
    check("merged: doc fills joining", c["groups"]["Joining"] == "planned")
    check("strip and og say paused, not pauses soon", M.strip_text()[0].startswith("Hosted mining paused") and "pauses soon" not in M.og_desc())
    check("meta hosted_mining paused", M.hosted_state() == "paused" and H.summary()["surfaces_source"] == "probe+tracker")
    blob = json.dumps(db.get_blob(P.BLOB)[0])
    check("blob holds no codes, bodies or timings", not any(k in blob for k in ("code", "body", "ms", "halted -", "age_s")))
    db.put_blob(P.BLOB, dict(groups=g, seen=seen, ok=False, ts=int(time.time())))
    check("unusable probe falls back to the doc", M.hosted_state() == "planned" and H.current()["source"] == "tracker")
    db.put_blob(P.BLOB, dict(groups=g, seen=seen, ok=True, ts=int(time.time()) - P.MAX_AGE - 1))
    check("old probe state falls back to the doc", H.current()["source"] == "tracker")
    print(f"\n{len(fails)} failure(s)"); sys.exit(1 if fails else 0)

main()
