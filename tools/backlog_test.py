"""Answered vs Backlog paid (post 3113): an epoch counts as answered only when the Agent submitted an answer in it (a challenge
tx). A close that paid an earlier answer is Backlog paid. Checks the profile, established_history (API fields added, old ones
kept), the epoch list tags and the reward tracker steps. Usage: python3 tools/backlog_test.py (temp database, no network)."""
import os, re, sys, tempfile, time
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, agents as G, profile as PF, views as V, segments as SG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

ME, OTHER = "poa1" + "M" * 40, "poa1" + "O" * 40
T0 = 1_790_000_000
db.init()
db.put_blob("params", {"trusted_graders": []})
def rec(n, mine_share=None, settled=(), rewards=None):
    return {"epoch": n, "ts": T0 + n * 21600, "challenges": ({ME: mine_share} if mine_share else {}), "rewards": ({ME: rewards} if rewards else {}),
            "basis": {"settled": [dict(answer=a, **{"from": ME}, passed=ok, jury=[]) for a, ok in settled], "pending": {}}}
# E1: answered in E1 (tx). E2: close pays an earlier (E1) answer, nothing submitted in E2 (backlog). E3: answered in E3 and E1 settles failed there.
# E4: submitted, nothing credited. E5: close pays an earlier answer that passed (settled row only, not in challenges): backlog.
db.put_blob("epochs", [rec(1, "10", [], "10"), rec(2, "20", [("a1", True)], "20"), rec(3, "30", [("a1b", False)], "30"), rec(4), rec(5, None, [("a3", True)], "50")])
tx = lambda i, ep: (f"{i:064x}", "challenge", ME, None, None, None, None, ep, T0 + ep * 21600 - 100, 0, 0, 1, 0, 0, "t")
db.write("INSERT INTO txs(id,type,from_addr,to_addr,amount,memo,invited_by,epoch,ts,atts,k,final,first_seen,last_seen,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         [tx(1, 1), tx(3, 3), tx(4, 4)], many=True)
db.write("UPDATE txs SET segment=?", (SG.selected(),))   # the selected segment's archive
A._cache.clear()

sub = G.submitted_epochs(ME)
check("submitted = epochs with a challenge tx from the address", sub == [1, 3, 4])
check("other address has none", G.submitted_epochs(OTHER) == [])
p = G.profile(ME)
check("profile keeps answered (credited or submitted) for old callers", set(p["answered"]) >= {1, 2, 3})
check("profile.submitted is the tx epochs only", p["submitted"] == [1, 3, 4])
check("profile.backlog = credited closes with no submission (E2 challenges key, E5 passed settled row)", p["backlog"] == [2, 5])
check("submitted and backlog never overlap and cover the credited set", not set(p["submitted"]) & set(p["backlog"]) and set(p["submitted"]) | set(p["backlog"]) >= set(p["answered"]))
check("backlog_epochs(): failed or expired settled rows alone are not backlog paid",
      G.backlog_epochs([], [], [(7, "x", False, "failed"), (8, "y", True, "expired_no_jury")]) == [] and G.backlog_epochs([], [1], [(7, "x", True, "passed")]) == [7])

h = G.established_history(ME)
check("API: old fields kept with the same meaning", h["epochs_answered"] == len(p["answered"]) and "first_answer_epoch" in h and "last_answer_epoch" in h and "answered" in h["window"])
check("API: new fields added", h["epochs_submitted"] == 3 and h["submitted_epochs"] == [1, 3, 4] and h["epochs_backlog_paid"] == 2 and h["backlog_paid_epochs"] == [2, 5]
      and h["first_submitted_epoch"] == 1 and h["last_submitted_epoch"] == 4 and "submitted" in h["window"] and "backlog_paid" in h["window"])
check("totals add up: submitted + backlog paid >= answered, and the sum equals the union", h["epochs_submitted"] + h["epochs_backlog_paid"] == len(set(h["submitted_epochs"]) | set(h["backlog_paid_epochs"])))

rows = {x["g"]: x for x in PF.epoch_rows(p, {})}
cell = {g: PF._answers(x) for g, x in rows.items()}
check("epoch list: an answered epoch with nothing settled reads Answered, never Backlog paid", "Answered" in cell[SG.gkey(4)] and "Backlog" not in cell[SG.gkey(4)])
check("epoch list: answered epochs with settled outcomes show the outcomes, no backlog tag", all("Backlog" not in cell[SG.gkey(e)] for e in (1, 3, 4)) and "Failed" in cell[SG.gkey(3)])
check("epoch list: backlog epochs carry Backlog paid and never Answered", all("Backlog paid" in cell[SG.gkey(e)] and "Answered" not in cell[SG.gkey(e)] for e in (2, 5)))
check("epoch list: outcomes still shown under the Backlog paid tag", "Passed" in cell[SG.gkey(2)] and "Passed" in cell[SG.gkey(5)])
check("epoch list: no em or en dash", all("\u2014" not in c and "\u2013" not in c for c in cell.values()))

el = V._elist(list(range(1, 31)))
check("stat list: count, newest 20 shown, rest folded", ">30<" in el and "E30" in el and "E11" in el and "E10," not in el and "+10 earlier" in el)
check("stat list: empty is the placeholder", V._elist([]) == "···")
src = open(os.path.join(ROOT, "poascan", "views.py")).read()
check("address page shows Answered and Backlog paid, not the old Epochs answered row", '("Answered", _elist(p["submitted"]))' in src and '("Backlog paid", _elist(p["backlog"]))' in src and "Epochs answered" not in src)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
