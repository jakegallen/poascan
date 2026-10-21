"""Frozen answer cohorts: every answer born in an epoch, tracked at each later close. Counts always sum to the denominator."""
from . import analytics as A
from .analytics import cached

STATES = ("unsealed", "sealed", "passed", "failed", "vanished")

def _sealed(row, merged):
    """Seal state of a pending row: True, False, or 'lb' when an empty pre-merge panel may have missed seals."""
    if row.get("kind") == "appeal": return True                    # an appeal re-grades an answer that was already graded
    if "grades" in row or merged: return bool({g.get("grader") for g in row.get("grades") or [] if g.get("grader")})
    return True if row.get("panel") else "lb"

@cached("cohorts", 300)
def cohorts():
    E = sorted(A.epochs_raw(), key=lambda e: int(e["epoch"]))
    merge = int(A.params().get("pending_merge_from_epoch") or 0)
    born, settled, out, gate, late = {}, {}, [], [], set()
    snaps = []
    for e in E:
        n = int(e["epoch"]); b = e.get("basis", {}) or {}; p = b.get("pending") or {}
        if not isinstance(p, dict): p = {}
        for s in b.get("settled", []) or []:
            if s.get("answer"): settled[s["answer"]] = (n, bool(s.get("passed")))
        new = [k for k, v in p.items() if k not in born and (v or {}).get("since") == n]
        late |= {k for k, v in p.items() if k not in born and (v or {}).get("since") != n}   # first seen after its birth close: no frozen cohort
        for k in new: born[k] = n
        snaps.append((n, p, dict(settled)))
        el = len(b.get("challenge_eligible") or [])
        gate.append(dict(close=n, eligible=el, answers=len(new), rate=round(el / len(new), 4) if new else None))
    members = {}
    for k, c in born.items(): members.setdefault(c, []).append(k)
    for c in sorted(members):
        ids = members[c]; track = []
        for n, p, st in snaps:
            if n < c: continue
            ct = dict.fromkeys(STATES, 0); lb = False
            for k in ids:
                if k in p:
                    s = _sealed(p[k] or {}, n >= merge)
                    if s == "lb": lb = True; ct["unsealed"] += 1
                    else: ct["sealed" if s else "unsealed"] += 1
                elif k in st: ct["passed" if st[k][1] else "failed"] += 1
                else: ct["vanished"] += 1
            assert sum(ct.values()) == len(ids)
            track.append(dict(close=n, age=n - c, **ct, sealed_is_lower_bound=lb))
        g = next(x for x in gate if x["close"] == c)
        out.append(dict(birth=c, answers=len(ids), gate_a=dict(eligible=g["eligible"], rate=g["rate"]), closes=track))
    return dict(as_of_close=int(E[-1]["epoch"]) if E else None, merge_from=merge, k=A.params().get("K"), cohorts=out, gate_a=gate, first_seen_late=len(late - set(born)))

def rows():
    """Flat rows for CSV: one per cohort and close."""
    return [dict(birth=c["birth"], answers=c["answers"], gate_a_eligible=c["gate_a"]["eligible"], gate_a_rate=c["gate_a"]["rate"], **t) for c in cohorts()["cohorts"] for t in c["closes"]]

def one(n): return next((c for c in cohorts()["cohorts"] if c["birth"] == n), None)
