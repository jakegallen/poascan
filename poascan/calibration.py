"""Grader calibration: agreement with settled panels, score mean and spread, seals per close. Advisory, never ranked.

1.26.183: scores are settled only, from grade_history (gradehist.py: the 0 to 3 scores settled juries carry in minepoa's
grading list). Before, they came from the grades on rows still pending at each close (basis.pending[].grades[].score);
those are no longer read. Pending grades are read for their grader and timestamp only (seal counts)."""
import bisect, collections, statistics
from . import db, analytics as A
from .analytics import cached

MIN_N = 20   # below this, a rate or mean is shown greyed

def _sd(v): return statistics.stdev(v) if len(v) > 1 else None

def settled_scores(seg=None):
    """{grader: [score, ...]} for the selected segment: settled jury seats with a score (grade_history, 0 to 3)."""
    from . import gradehist as GH, segments as SG
    GH._ensure(); out = collections.defaultdict(list)
    for r in db.q("SELECT grader, score FROM grade_history WHERE seg=? AND score IS NOT NULL", (seg or SG.selected(),)): out[r["grader"]].append(int(r["score"]))
    return out

@A.close_memo("calibration_closes")
def _close_part():
    """The close record part of calibration (1.26.235: read once per close; the archive part stays live)."""
    E = sorted(A.epochs_raw(), key=lambda e: int(e["epoch"]))
    p = A.params(); merge = int(p.get("pending_merge_from_epoch") or 0)
    seat = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))   # g -> close -> [seats, aligned]
    split = collections.defaultdict(lambda: [0, 0, 0, 0])                              # g -> [seats on passed, aligned, seats on failed, aligned]
    seal_ts = {}                                                                        # (answer, grader) -> seal ts (pending grades: ts only)
    for e in E:
        n = int(e["epoch"]); b = e.get("basis", {}) or {}
        for s in b.get("settled", []) or []:
            ok = bool(s.get("passed"))
            for j in s.get("jury", []) or []:
                g = j.get("grader"); al = int(bool(j.get("aligned")))
                if not g: continue
                c = seat[g][n]; c[0] += 1; c[1] += al
                x = split[g]; i = 0 if ok else 2; x[i] += 1; x[i + 1] += al
        if n >= merge:   # seal times only: a pending grade's score is never read
            pend = A.pending_of(e) or {}
            for ans, row in (pend.items() if isinstance(pend, dict) else ()):
                for gr in (row or {}).get("grades") or []:
                    if isinstance(gr, dict) and gr.get("grader") and isinstance(gr.get("ts"), (int, float)) and gr["ts"]: seal_ts[(ans, gr["grader"])] = int(gr["ts"])
    return seat, split, seal_ts

@cached("calibration", 300)
def calibration():
    E = sorted(A.epochs_raw(), key=lambda e: int(e["epoch"]))
    if not E: return dict(as_of_close=None, min_n=MIN_N, graders=[])
    p = A.params(); merge = int(p.get("pending_merge_from_epoch") or 0)
    closes = [int(e["epoch"]) for e in E]; cts = [int(e["ts"]) for e in E]; last_ts = cts[-1]
    trusted = set(p.get("trusted_graders", [])) | set(p.get("system_grader_accounts", []))
    seat, split, seal_ts = _close_part()
    # Seals: record grades plus archived grade-sealed txs, one per (grader, ts); a grade's ts equals its seal tx ts.
    seals = {(g, t) for (_, g), t in seal_ts.items()}
    for r in db.q("SELECT from_addr AS g, ts FROM txs WHERE type='grade-sealed' AND from_addr IS NOT NULL"): seals.add((r["g"], int(r["ts"])))
    per = collections.defaultdict(collections.Counter); since = collections.Counter()
    for g, t in seals:
        if t > last_ts: since[g] += 1; continue
        per[g][closes[bisect.bisect_left(cts, t)]] += 1
    sc = settled_scores()
    nm = A.forum_names(); out = []
    for g in set(seat) | set(sc) | set(per) | set(since):
        bc = seat.get(g, {}); n = sum(v[0] for v in bc.values()); al = sum(v[1] for v in bc.values()); x = split.get(g, [0, 0, 0, 0])
        v = sc.get(g, []); pc = per.get(g, collections.Counter())
        first = min(pc) if pc else None; span = closes[-1] - first + 1 if first is not None else 0
        out.append(dict(grader=g, name=nm.get(g) or None, trusted=g in trusted,
                        seats=n, aligned=al, aligned_rate=round(al / n, 4) if n else None,
                        seats_passed=x[0], aligned_passed=x[1], seats_failed=x[2], aligned_failed=x[3],
                        scored=len(v), score_mean=round(statistics.fmean(v), 3) if v else None, score_sd=round(_sd(v), 3) if _sd(v) is not None else None,
                        score_hist={str(k): v.count(k) for k in (0, 1, 2, 3)} if v else {},
                        seals=sum(pc.values()), closes=span, seals_per_close=round(sum(pc.values()) / span, 1) if span else None,
                        seals_by_close={str(k): pc[k] for k in sorted(pc)}, seals_since_close=since.get(g, 0),
                        seats_by_close={str(k): {"seats": c[0], "aligned": c[1]} for k, c in sorted(bc.items())},
                        low_n=n < MIN_N and len(v) < MIN_N))
    out.sort(key=lambda r: ((r["name"] or "~").lower(), r["grader"]))
    tot = sum(r["seats"] for r in out); tal = sum(r["aligned"] for r in out); allv = [s for v in sc.values() for s in v]
    return dict(as_of_close=closes[-1], min_n=MIN_N, graders_count=len(out), seats=tot, aligned=tal, aligned_rate=round(tal / tot, 4) if tot else None,
                scored=len(allv), score_mean=round(statistics.fmean(allv), 3) if allv else None, score_sd=round(_sd(allv), 3) if _sd(allv) is not None else None,
                seals=len(seals), archive_start_ts=(db.q1("SELECT MIN(ts) AS t FROM txs") or {}).get("t"), graders=out)

def sorted_rows(by="name"):
    c = calibration(); rows = list(c["graders"])
    if by == "n": rows.sort(key=lambda r: (-r["seats"], -r["scored"], r["grader"]))
    return c, rows

def one(g): return next((r for r in calibration()["graders"] if r["grader"] == g), None)
