"""POAScan's Score (1.26.108): weights load from govscore.json and sum to 1, scores are deterministic integers 0 to 100,
the fold matches governance.segment_standing, better inputs never score lower, and a changed config changes the result.
Usage: python3 tools/govscore_test.py"""
import copy, json, os, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_DB", os.path.join(tempfile.mkdtemp(), "s.db"))
from poascan import govscore as GS
FAILS = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or FAILS.append(name)

A, B, C, T = "poa1" + "A" * 40, "poa1" + "B" * 40, "poa1" + "C" * 40, "poa1" + "T" * 40
def rec(n, **b): return {"epoch": n, "basis": b, "rewards": b.pop("rewards", {})}
CLOSES = [rec(0, challenge_eligible=[A, B], settled=[{"from": A, "passed": True, "jury": [{"grader": C, "aligned": True}]}, {"from": B, "passed": False, "jury": [{"grader": C, "aligned": False}]}]),
          rec(1, established_after=[A], challenge_eligible=[A], graders_served={C: 3}, rewards={A: "10"}),
          rec(2, challenge_eligible=[A], graders_served={C: 2, T: 1}, marks={C: 1}),
          rec(3, established_removed=[A], graders_served={C: 1}),
          rec(4, established_after=[A], challenge_eligible=[A, B], audit={"slashed": [B]})]

def main():
    c = GS.load_cfg()
    check("govscore.json: weights and part weights sum to 1", abs(sum(c["weights"].values()) - 1) < 1e-9 and [k for k, _ in GS.PARTS] == list(c["weights"]))
    bad = copy.deepcopy(c); bad["weights"]["forum"] += 0.1; p = os.path.join(tempfile.mkdtemp(), "bad.json"); json.dump(bad, open(p, "w"))
    try: GS.load_cfg(p); check("weights that do not sum to 1 are refused", False)
    except AssertionError: check("weights that do not sum to 1 are refused", True)
    cf, last, n = GS.close_facts(CLOSES, frozenset({T}), ttl=6)
    check(f"fold: closes held (A added E1, removed E3, back E4; C held by seats and jury seats; T trusted once seen) {cf[A]['closes_established']} {cf[C]['closes_established']} {cf[T]['closes_established']}",
          cf[A]["closes_established"] == 3 and cf[C]["closes_established"] == 5 and cf[T]["closes_established"] == 3)
    check("facts: removals, slashes, marks, jury, settled, paid", cf[A]["removed"] == 1 and cf[B]["slashed"] == 1 and cf[C]["marks"] == 1 and (cf[C]["jury_seats"], cf[C]["jury_aligned"]) == (2, 1)
          and (cf[A]["settled"], cf[A]["passed"], cf[B]["passed"]) == (1, 1, 0) and cf[A]["paid_closes"] == 1 and cf[A]["rewards"] == 10)
    check("a removal alone is not activity", 3 not in cf[A]["active_closes"] and cf[A]["active_closes"] == [0, 1, 2, 4])
    cr, _, _ = GS.close_facts(CLOSES[:3] + [dict(CLOSES[3], epoch=3)] + [dict(CLOSES[4])], resets=frozenset({4}))
    check("reset: standing starts fresh at a segment's first close", cr[C]["closes_established"] == 4)
    def full(a, **o):
        f = dict(GS._blank()); f.update(cf.get(a) or {}); f.update(GS.EMPTY_TX); f.update(GS.EMPTY_FORUM); f.update(o); return f
    s1 = GS.score(full(A), "safe", last, n); s2 = GS.score(full(A), "safe", last, n)
    check(f"deterministic integers 0 to 100 {s1}", s1 == s2 and all(isinstance(v, int) and 0 <= v <= 100 for v in s1.values()) and set(s1) == {"score", "standing", "grading", "forum", "consistency"})
    more = GS.score(full(A, posts=5, comments=20, posts_replied=3), "safe", last, n)
    check(f"forum activity raises Forum and never lowers the Score {s1['forum']} -> {more['forum']}", more["forum"] > s1["forum"] and more["score"] >= s1["score"])
    check("At risk scores below Safe on the same facts", GS.score(full(A), "risk", last, n)["standing"] < s1["standing"])
    sl = GS.score(full(B), "none", last, n); ns = GS.score(full(B, slashed=0), "none", last, n)
    check("a slash lowers Standing", sl["standing"] < ns["standing"] or ns["standing"] == 0)
    gr = GS.score(full(C, seals=300), "safe", last, n); g0 = GS.score(full(C), "safe", last, n)
    check(f"seals raise Grading {g0['grading']} -> {gr['grading']}", gr["grading"] > g0["grading"])
    check("no grading at all scores 0 on Grading", GS.score(full(B), "none", last, n)["grading"] == 0)
    empty = GS.score(GS._blank() | GS.EMPTY_TX | GS.EMPTY_FORUM, "none", last, n)
    check(f"no activity scores 0 {empty}", empty == {"score": 0, "standing": 0, "grading": 0, "forum": 0, "consistency": 0})
    alt = copy.deepcopy(c); alt["weights"] = {"standing": 0.0, "grading": 0.0, "forum": 1.0, "consistency": 0.0}
    check("config driven: forum-only weights give Score == Forum", GS.score(full(A, posts=5, comments=20), "safe", last, n, alt)["score"] == GS.score(full(A, posts=5, comments=20), "safe", last, n, alt)["forum"])
    check("consistency: one close is not a record", GS.consistency([4], 4, 4, 7) < 0.2 and GS.consistency(list(range(7)), 0, 6, 7) == 1.0)
    from poascan import views as V
    m = V.score_method()
    check("/about#score: own score, not official, every weight from the config, no dashes", 'id="score"' in m and "Not an official ranking" in m and "\u2014" not in m and "\u2013" not in m
          and all(f"({round(v * 100)}%)" in m for v in c["weights"].values()))
    check("tooltip copy", GS.TIP == "Built by POAScan from public network data. Not an official ranking. Meant to help explain how Agents become established.")

if __name__ == "__main__":
    main(); print(f"{len(FAILS)} failed" if FAILS else "all passed"); sys.exit(1 if FAILS else 0)
