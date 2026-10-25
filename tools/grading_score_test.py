"""Score v2 inputs from minepoa's grading list and the reconciliation rows (1.26.138): seal_facts from the seal store,
qualifying seals and rate in governance scores and the agent API, Unconfirmed caps the standing level, archived segments
and a missing copy fall back, and Queue, Seals since close and Established rows on Reconciliation.
Usage: python3 tools/grading_score_test.py (temp database, no network)."""
import os, sys, tempfile, time, re
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
from poascan import db, grading as GR, analytics as A, governance as GV, reconcile as RE, segments as SG, views2 as V2
import fixture

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

NOW = int(time.time())
T1, G2 = "poa1" + "T" * 40, "poa1" + "H" * 40

def doc(est=()):
    A1 = fixture.A1
    tl = (A.epoch_rows() or [{}])[-1].get("close_ts") or NOW - 3600
    g = [dict(g=T1, ts=tl + 10, t=True, q=True), dict(g=A1, ts=tl + 20, t=False, q=True), dict(g=A1, ts=tl + 25, t=False, q=True), dict(g=G2, ts=tl + 30, t=False, q=False)]
    rows = [dict(id="d" * 64, author=fixture.A2, born=2, since=2, expires=18, kind="short", raw=4, qual=3, need=1, snippet="s", grades=g[:2] + g[3:]),
            dict(id="e" * 64, author=fixture.A2, born=2, since=2, expires=18, kind="short", raw=1, qual=1, need=3, snippet="s", grades=[g[2]])]
    ro = [dict(epoch=i, ts=tl - (3 - i) * 21600) for i in range(4)]
    return dict(as_of=NOW - 40, epoch=4, chain="poa-mainnet-1", quorum=4, ttl_epochs=16, trusted=[T1], established=list(est),
                stats=dict(pending=22, at_quorum=0, by_need={"1": 1, "3": 1}, trusted_share=0.25), rollups=ro, rows=rows, open=[], leaderboard=[], settled=[], gen_ms=1)

def main():
    fixture.seed()
    check("no copy: no grading reconciliation rows", not [r for r in RE.reconcile()["rows"] if r["key"].startswith("grading_")])
    sc0 = GV.scores()["rows"]
    check("no copy: archived seals, nobody Unconfirmed", all(f.get("seals_source") == "archived_txs" and not f.get("unconfirmed") for f in sc0.values()))
    GR.job(now=NOW, get=lambda: doc(), force=True); A._cache.clear(); RE.reconcile.__dict__.get("cache_clear", lambda: None)()
    sf = GR.seal_facts()
    check(f"seal_facts: seals and qualifying per grader {sf.get(fixture.A1)} {sf.get(G2)}", sf.get(fixture.A1) == (2, 2) and sf.get(G2) == (1, 0))
    check("seal_facts: window by seal time", GR.seal_facts(NOW + 10 ** 6) == {})
    sc = GV.scores()["rows"]; f = sc[fixture.A1]
    check("scores: listed seals and rate", f["seals_listed"] == 2 and f["qual_rate"] == 1.0 and f["seals_source"] == "minepoa_grading" and f["seals_qual"] >= 2)
    check("scores: established Agents missing from an empty list are Unconfirmed", f["unconfirmed"] is True)
    si = GV.api_agent(fixture.A1)["score_inputs"]
    check("agent API: score_inputs", si["seals_qualifying"] >= 2 and si["qual_rate"] == 1.0 and si["unconfirmed"] and si["level_value_cap"] == 0.5)
    check("agent API: score_version 2", GV.api_agent(fixture.A1)["score_version"] == 2)
    # confirmed by the list: no cap
    GR.job(now=NOW + 1, get=lambda: doc(est=[fixture.A1]), force=True); A._cache.clear()
    f2 = GV.scores()["rows"][fixture.A1]
    check(f"confirmed by the list: not Unconfirmed, standing not lower {f['standing']} -> {f2['standing']}", not f2["unconfirmed"] and f2["standing"] >= f["standing"])
    # archived segment: no live inputs
    with SG.use(1):
        A._cache.clear(); sa = GV.scores()["rows"]
        check("archived segment: no listing, nobody Unconfirmed", all(not x.get("unconfirmed") and x.get("seals_source") == "archived_txs" for x in sa.values()))
    A._cache.clear()
    rows = {r["key"]: r for r in RE.reconcile()["rows"]}
    check("reconcile: Queue row against stats.pending", rows["grading_pending"]["node"] == 22 and rows["grading_pending"]["node_source"].startswith("minepoa /api/explorer/grading"))
    check("reconcile: Seals since close counts list seals after the close", rows["grading_seals"]["node"] == 4)
    est = rows["grading_established"]
    check("reconcile: Established ours vs the list", est["node"] == 1 and est["poascan"] >= 1 and est["upstream" if "upstream" in est else "node_as_of"] == NOW - 40)
    h = V2.recon_card()
    check("Health card labels the list side", "minepoa list" in h and "\u2014" not in h and "\u2013" not in h)
    print(f"\n{len(fails)} failed" if fails else "\nall passed")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
