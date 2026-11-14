"""Frozen answer cohorts: every answer born in an epoch, tracked at each later close. Counts always sum to the denominator."""
from . import analytics as A, outcome as O
from .analytics import cached

STATES = ("unsealed", "sealed", "passed", "failed", "expired_no_jury", "vanished")   # expired_no_jury: settled with no jury (1.26.224)

def _sealed(row, merged):
    """Seal state of a pending row: True, False, or 'lb' when an empty pre-merge panel may have missed seals."""
    if row.get("kind") == "appeal": return True                    # an appeal re-grades an answer that was already graded
    if "grades" in row or merged: return bool({g.get("grader") for g in row.get("grades") or [] if g.get("grader")})
    return True if row.get("panel") else "lb"

@cached("cohorts", 300)
def cohorts(): return _cohorts()

@A.close_memo("cohorts")
def _cohorts():
    """1.26.235: two passes over the closes, one pending list at a time. 1.26.337: one fold over the closes (both passes
    per close: an answer is born at its close, and a cohort's tracks start there), kept in close_fold (closesum.py), so a
    new close folds its own pending list only. Same counts, same order."""
    from . import closesum as SUM
    raw = A.epochs_raw(); merge = int(A.params().get("pending_merge_from_epoch") or 0)
    v = SUM.fold("cohorts", A.S.blob_kind(), raw, lambda n: [merge, SUM.since_digest(n)], _co_start, lambda st, e, p: _co_step(st, e, p, merge), lambda st: _co_finish(st, merge),
                 lite=lambda st: dict(members={c: len(v) for c, v in st["members"].items()}, gate=st["gate"], tracks=st["tracks"], last=st["last"], late_n=len(st["late"] - set(st["born"]))))
    if v is not None: return v
    st = _co_start()
    for e in sorted(raw, key=lambda e: int(e["epoch"])): _co_step(st, e, A.pending_of(e), merge)
    return _co_finish(st, merge)

def _co_start():
    return dict(born={}, gate=[], late=set(), members={}, tracks={}, settled={}, last=None)

def _co_step(st, e, p, merge):
    born, gate, late, members, tracks, settled = st["born"], st["gate"], st["late"], st["members"], st["tracks"], st["settled"]
    p = p or {}; p = p if isinstance(p, dict) else {}
    n = int(e["epoch"]); b = e.get("basis", {}) or {}
    new = [k for k, v in p.items() if k not in born and A.since_of(k, v or {}) == n]   # 1.26.89: since filled when minepoa omits it (E14 on)
    late |= {k for k, v in p.items() if k not in born and A.since_of(k, v or {}) != n}   # first seen after its birth close: no frozen cohort
    for k in new: born[k] = n
    el = len(b.get("challenge_eligible") or [])
    gate.append(dict(close=n, eligible=el, answers=len(new), rate=round(el / len(new), 4) if new else None))
    for k in new: members.setdefault(n, []).append(k)
    if new: tracks.setdefault(n, [])
    for s in b.get("settled", []) or []:
        if s.get("answer"): settled[s["answer"]] = (n, O.of(s))
    st["last"] = n
    cs = [c for c in sorted(members) if n >= c]
    if not cs: return
    st_ = settled
    for c in cs:
        ids = members[c]; ct = dict.fromkeys(STATES, 0); lb = False
        for k in ids:
            if k in p:
                s = _sealed(p[k] or {}, n >= merge)
                if s == "lb": lb = True; ct["unsealed"] += 1
                else: ct["sealed" if s else "unsealed"] += 1
            elif k in st_: ct[st_[k][1]] += 1
            else: ct["vanished"] += 1
        assert sum(ct.values()) == len(ids)
        tracks[c].append(dict(close=n, age=n - c, **ct, sealed_is_lower_bound=lb))

def _co_finish(st, merge):
    gate, members, tracks = st["gate"], st["members"], st["tracks"]
    late_n = st["late_n"] if "late_n" in st else len(st["late"] - set(st["born"]))
    out = []
    for c in sorted(members):
        g = next(x for x in gate if x["close"] == c)
        out.append(dict(birth=c, answers=members[c] if isinstance(members[c], int) else len(members[c]), gate_a=dict(eligible=g["eligible"], rate=g["rate"]), closes=[dict(t) for t in tracks[c]]))
    _dac = st["last"]
    return dict(as_of_close=_dac, data_as_of_close=_dac, stale_reason=A.close_lag(_dac), merge_from=merge, k=A.params().get("K"), cohorts=out, gate_a=[dict(x) for x in gate], first_seen_late=late_n)

def rows():
    """Flat rows for CSV: one per cohort and close."""
    return [dict(birth=c["birth"], answers=c["answers"], gate_a_eligible=c["gate_a"]["eligible"], gate_a_rate=c["gate_a"]["rate"], **t) for c in cohorts()["cohorts"] for t in c["closes"]]

def one(n): return next((c for c in cohorts()["cohorts"] if c["birth"] == n), None)
