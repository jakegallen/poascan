"""Grading queue board (1.26.206): Governance, Queue. Counts only, from data POAScan already holds: the latest close record's
basis.pending (panel coverage by birth band, answers nearing expiry), minepoa's grading list copy read every 10 minutes
(answers at 3 qualified seals of the quorum of 4) and POAScan's tx archive (answer and seal tx times per close window).
No upstream read, no pending seal blob, no pending score: a row's grades list is used only for its length.

Neutral closes: POAScan's replay of a proposed rule, until a close record carries the two fields itself (then they are shown
as recorded). A close is neutral_answer when the longest gap between consecutive final answer txs in its window (edges
included) is over 3 hours, or it has under 20 answer txs; neutral_grading when its seal txs are under 25% of the median of
the last three closes that were neither. A close window runs from the previous close's time to its own."""
import statistics
from . import db, analytics as A, segments as SG, netparams as NP, grading as GR
from .ui import E, card, stat, intc, qtip, lt

METHOD = "/about#board"
BANDS = [(0, 2, "0 to 2"), (3, 5, "3 to 5"), (6, 9, "6 to 9"), (10, 13, "10 to 13"), (14, 10 ** 6, "14 or more")]
GAP_S, MIN_ANSWERS, SEAL_FRAC, BASE_N = 3 * 3600, 20, 0.25, 3
CLOSES_SHOWN = 12

def _times(seg, typ):
    try: return [r["ts"] for r in db.q("SELECT ts FROM txs WHERE type=? AND segment=? AND final=1 AND ts IS NOT NULL ORDER BY ts", (typ, seg))]
    except Exception: return []

def _count_in(ts, lo, hi):
    import bisect
    return bisect.bisect_right(ts, hi) - bisect.bisect_right(ts, lo)

def _gap(ts, lo, hi):
    import bisect
    i, j = bisect.bisect_right(ts, lo), bisect.bisect_right(ts, hi)
    pts = [lo] + ts[i:j] + [hi]
    return max(b - a for a, b in zip(pts, pts[1:]))

def neutral(eps, answers, seals):
    """One row per close with a known window: answers, longest_gap_s, seals, baseline, neutral_answer, neutral_grading, source."""
    out, normal = [], []
    for prev, e in zip(eps, eps[1:]):
        n = int(e.get("epoch", 0)); lo, hi = int(prev.get("ts") or 0), int(e.get("ts") or 0)
        if not lo or not hi or hi <= lo: continue
        na_, gap, ns = _count_in(answers, lo, hi), _gap(answers, lo, hi), _count_in(seals, lo, hi)
        base = statistics.median(normal[-BASE_N:]) if len(normal) >= BASE_N else None
        rec = (e.get("basis") or {}); ra, rg = rec.get("neutral_answer", e.get("neutral_answer")), rec.get("neutral_grading", e.get("neutral_grading"))
        nA = bool(ra) if ra is not None else (gap > GAP_S or na_ < MIN_ANSWERS)
        nG = bool(rg) if rg is not None else (base is not None and ns < SEAL_FRAC * base)
        out.append(dict(close=n, close_ts=hi, opened_ts=lo, answers=na_, longest_gap_s=gap, seals=ns, baseline=base, neutral_answer=nA, neutral_grading=nG,
                        grading_known=rg is not None or base is not None, source="close record" if (ra is not None or rg is not None) else "POAScan replay"))
        if not nA and not nG: normal.append(ns)
    return out

@A.cached("grading_board", 300)
def data():
    seg = SG.selected(); eps = sorted(A.epochs_raw(), key=lambda e: int(e.get("epoch", 0)))
    last = eps[-1] if eps else None; lc = int(last["epoch"]) if last else None
    ttl = NP.pending_ttl(seg)["value"]
    bands = [dict(band=l, lo=lo, hi=hi, pending=0, birth_panel=0, any_seal=0) for lo, hi, l in BANDS]
    near = {1: 0, 2: 0, 3: 0}; total = 0; three_rec = 0
    for tid, v in (((last or {}).get("basis") or {}).get("pending") or {}).items():
        if not isinstance(v, dict): continue
        total += 1; age = lc - A.since_of(tid, v)
        b = next(x for x in bands if x["lo"] <= age <= x["hi"])
        b["pending"] += 1; b["birth_panel"] += 1 if v.get("panel") else 0; b["any_seal"] += 1 if v.get("grades") else 0
        g = len({(x.get("grader") if isinstance(x, dict) else x) for x in v.get("grades") or []})
        three_rec += 1 if g == 3 else 0
        left = A.since_of(tid, v) + ttl - lc   # closes until it expires
        for k in near:
            if left <= k: near[k] += 1
    for b in bands: b["coverage"] = round(b["birth_panel"] / b["pending"], 4) if b["pending"] else None
    gl = None
    if GR.usable():
        qr = [r for r in GR.queue_rows() if not r.get("open")]
        gl = dict(at_three=sum(1 for r in qr if r.get("need") == 1), at_quorum=sum(1 for r in qr if r.get("need") == 0), pending=len(qr),
                  as_of=(GR.summary() or {}).get("upstream_as_of"))
    nt = neutral(eps, _times(seg, "challenge"), _times(seg, "grade-sealed"))
    return dict(segment=seg, last_close=lc, last_close_ts=int(last.get("ts") or 0) if last else None, pending=total, pending_ttl=ttl,
                birth_panel=sum(b["birth_panel"] for b in bands), bands=bands, at_three_record=three_rec, grading_list=gl,
                expiring=dict(next_close=near[1], within_2=near[2], within_3=near[3]), closes=nt,
                rule=dict(gap_s=GAP_S, min_answers=MIN_ANSWERS, seal_frac=SEAL_FRAC, baseline_closes=BASE_N))

def _pct(v): return f"{v * 100:.0f}%" if v is not None else '<span class="dim">···</span>'
def _yn(v, known=True):
    if not known: return '<span class="dim">···</span>'
    return '<span class="tag warn">Yes</span>' if v else '<span class="dim">No</span>'
def _h(s): return f"{s / 3600:.1f} h"

TIP = ("Birth panel: the answer has a panel listed in the close record (set when it is born). Any seal: its grades list is not empty. "
       "Counts only; no seal blob or score is read.")
NTIP = ("POAScan's replay of a proposed rule, until a close record carries neutral_answer and neutral_grading itself. "
        "Answer: longest gap between answer txs over 3 h, or under 20 answer txs. Grading: seal txs under 25% of the median of the last 3 closes that were neither.")

def card_html():
    d = data()
    if d["last_close"] is None: return ""
    gl = d["grading_list"]; cov = d["birth_panel"]
    if gl and (gl.get("as_of") or 0) < (d.get("last_close_ts") or 0): gl = None   # the grading list predates the newest close: use the record / d["pending"] if d["pending"] else None
    s = "".join([stat("Pending", intc(d["pending"]), tip=f'In basis.pending at the E{d["last_close"]} close'),
                 stat("Birth panel", _pct(cov), tip="Pending answers with a panel in the close record"),
                 stat("At 3 of 4", intc(gl["at_three"]) if gl else intc(d["at_three_record"]),
                      tip="Answers one qualified seal short of quorum, from minepoa's grading list (checked every 10 minutes)" if gl else f'Pending answers with 3 graders at the E{d["last_close"]} close'),
                 stat("Expire in 2 closes", intc(d["expiring"]["within_2"]), tip=f'Pending answers whose entry epoch plus the pending TTL ({d["pending_ttl"]}) falls within the next 2 closes')])
    bt = "".join(f'<tr><td>{E(b["band"])}</td><td class="r">{b["pending"]:,}</td><td class="r">{b["birth_panel"]:,}</td><td class="r">{_pct(b["coverage"])}</td><td class="r dk">{b["any_seal"]:,}</td></tr>' for b in d["bands"])
    btab = (f'<div class="tw"><table class="hist cal gov"><thead><tr><th>Closes waited</th><th class="r">Pending</th><th class="r">Birth panel</th><th class="r">Coverage {qtip(TIP, METHOD, "About coverage", "hv")}</th>'
            f'<th class="r dk">Any seal</th></tr></thead><tbody>{bt}</tbody></table></div>')
    cs = d["closes"][-CLOSES_SHOWN:][::-1]
    ct = "".join(f'<tr><td><a href="/epoch/{c["close"]}">E{c["close"]}</a></td><td class="r">{c["answers"]:,}</td><td class="r dk">{_h(c["longest_gap_s"])}</td>'
                 f'<td class="r">{c["seals"]:,}</td><td class="r dk">{intc(round(c["baseline"])) if c["baseline"] is not None else "<span class=dim>···</span>"}</td>'
                 f'<td class="r">{_yn(c["neutral_answer"])}</td><td class="r">{_yn(c["neutral_grading"], c["grading_known"])}</td></tr>' for c in cs)
    ctab = (f'<div class="tw"><table class="hist cal gov"><thead><tr><th>Close</th><th class="r">Answers</th><th class="r dk">Longest gap</th><th class="r">Seals</th>'
            f'<th class="r dk">Baseline</th><th class="r">neutral_answer {qtip(NTIP, METHOD, "About neutral closes", "hv")}</th><th class="r">neutral_grading</th></tr></thead><tbody>{ct}</tbody></table></div>') if cs else ""
    foot = (f'<p class="cov dim small">Close record E{d["last_close"]} ({lt(d["last_close_ts"], "dt")}) and POAScan\'s tx archive'
            + (f' · grading list as of {lt(gl["as_of"], "dt")}' if gl and gl.get("as_of") else "") + f' · Counts only · <a href="{METHOD}">Method</a></p>')
    links = '<a class="more" href="/api/v1/governance/board">API →</a>'
    return (card("Queue board", f'<div class="stats four">{s}</div><h3 class="rech">Birth panel by closes waited</h3>' + btab
            + ('<h3 class="rech">Neutral closes</h3>' + ctab if ctab else "") + foot, links, cls="histc", id="board"))

def api():
    d = data()
    return dict(d, method="https://poascan.io" + METHOD, url="https://poascan.io/governance?tab=queue#board",
                note="Counts only. No pending seal blob or score is read. neutral_* are POAScan's replay of a proposed rule unless source says close record.")
