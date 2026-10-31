"""Settle age (Governance, Settle age): the network-wide spread of how long answers waited from their origin epoch to the
close that settled them. Age in epochs = settle close minus origin epoch, from the public close records POAScan already
archives, reusing govv2.settlement (its origin bucketing, cached, no extra tx lookups). A distribution only, never per grader
and never per Agent: no address, no verdict.

Juried answers are bucketed by age. Answers that expired with no jury (outcome.no_jury) sit in their own bucket, since they
cluster at the pending TTL and would spike the spread. Answers whose origin epoch is not on record land in the unknown
bucket, reported on their own. Settled data and timestamps only; a grading verdict is never read."""
import collections
from . import analytics as A, segments as SG, scoresort as SS, estfold as EF, netparams as NP, outcome as OC
from . import govv2 as GV2
from .ui import E, card, stat, intc, bars, qtip

METHOD = "/about#settle-age"

# Age in epochs from origin to settlement; the pending TTL default is 16, so the last band opens there (netparams.pending_ttl).
AGE_BANDS = [(0, "0"), (1, "1"), (2, "2-3"), (4, "4-7"), (8, "8-15"), (16, "16+")]

def _band_counts(ages):
    """[{band, lo, hi, answers}] over {age: count}, one entry per AGE_BANDS step."""
    out = []
    for i, (lo, lab) in enumerate(AGE_BANDS):
        hi = AGE_BANDS[i + 1][0] if i + 1 < len(AGE_BANDS) else None
        top = hi if hi is not None else float("inf")
        out.append(dict(band=lab, lo=lo, hi=hi, answers=sum(n for a, n in ages.items() if lo <= a < top)))
    return out

def _wmedian(ages):
    """Weighted median age (epochs) over {age: count}; None with no answer."""
    items = sorted(ages.items()); n = sum(v for _, v in items)
    if not n: return None
    k1, k2 = (n - 1) // 2, n // 2; need = {k1, k2}; res = {}; cum = 0
    for a, c in items:
        prev = cum; cum += c
        for k in list(need):
            if prev <= k < cum: res[k] = a; need.discard(k)
        if not need: break
    return (res[k1] + res[k2]) / 2

@A.cached("settleage", 300)
def distribution():
    """The selected segment's settle-age spread. Juried answers by age, expired (no jury) apart, unknown origin apart."""
    seg = SG.selected(); rows = GV2.settlement()
    ages = collections.Counter(); expired = unknown = settled = juried = 0
    closes = set(); first = None
    for r in rows:
        closes.add(r["close"]); first = r["close"] if first is None else min(first, r["close"])
        s = int(r["settled"]); x = int(r["expired_no_jury"]); settled += s
        if r["origin"] is None:
            unknown += s; continue
        age = int(r["close"]) - int(r["origin"])
        if age < 0:
            unknown += s; continue
        expired += x; j = s - x; juried += j
        if j: ages[age] += j
    genesis = bool(EF.imported(seg))
    return dict(segment=seg, archived=SG.archived(seg), bands=_band_counts(ages), median=_wmedian(ages),
                settled=settled, juried=juried, expired=expired, unknown=unknown, closes=len(closes),
                first_close=first, genesis_import=genesis, pending_ttl=NP.value("pending_ttl_epochs", seg))

COLS = [SS.Col("band", "Age", "low"), SS.Col("answers", "Answers", "num", "r"), SS.Col("share", "Share", "num", "r dk")]
SORTS = [(c.key, c.label) for c in COLS]
_V = {"band": lambda r: r["lo"], "answers": lambda r: r["answers"], "share": lambda r: r["answers"]}
TIP = ("Age: epochs an answer waited from its origin epoch to the close that settled it, over juried answers network-wide. "
       "Expired, no jury: settled past the pending TTL with no jury, kept apart so it does not spike the spread. Unknown: the origin epoch is not on record.")

def _rows(d):
    """Bands with Share of juried answers added."""
    tot = d["juried"] or 1
    return [dict(b, share=b["answers"] / tot) for b in d["bands"]]

def select(by="band", d="desc"):
    return SS.sort_rows(_rows(distribution()), _V.get(by, _V["band"]), SS.kind_of(COLS, by), d, tie=lambda r: r["lo"])

def _n(v): return f'<span class="num">{v:,}</span>' if v is not None else '<span class="dim">···</span>'
def _pct(v): return f'<span class="num">{v * 100:.1f}%</span>' if v is not None else '<span class="dim">···</span>'
def _med(v): return '<span class="num">···</span>' if v is None else (f'<span class="num">{int(v):,}</span>' if float(v).is_integer() else f'<span class="num">{v:.1f}</span>')

def tab(qs, href, qsx):
    d = distribution()
    if not d["closes"]: return card("Settle age", '<p class="na">No settled answer in this segment yet.</p>')
    by = SS.page_sort(qs, dict(SORTS), "band"); dd = SS.page_dir(qs)
    rs = select(by, dd)
    link = lambda k, x: href("settleage", sort=k if k != "band" else "", dir="asc" if x == "asc" else "") + "#settleage"
    s = "".join([stat("Settled", intc(d["settled"]), tip="Settled answers by origin epoch in this segment"),
                 stat("Median age", _med(d["median"]), tip="Median epochs from origin to settlement, over juried answers"),
                 stat("Expired, no jury", intc(d["expired"]), tip=f'Settled past the pending TTL ({d["pending_ttl"]}) with no jury'),
                 stat("Unknown origin", intc(d["unknown"]), tip="Settled answers whose origin epoch is not on record")])
    T = lambda: qtip(TIP, METHOD, "About Settle age", "hv")
    cols = [c._replace(tip=T()) if c.key == "band" else c for c in COLS]
    ch = bars([(b["band"], [b["answers"]]) for b in d["bands"]], height=150, colors=("gold",), fmt=lambda z: f"{z:,.0f}") if d["juried"] else '<p class="na">No juried answer in this segment yet.</p>'
    trs = "".join(f'<tr><td>{E(r["band"])}</td><td class="r">{_n(r["answers"])}</td><td class="r dk">{_pct(r["share"])}</td></tr>' for r in rs)
    tb = SS.select(cols, by, dd, link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(cols, by, dd, link)}</tr></thead><tbody>{trs}</tbody></table></div>'
    q = qsx(sort=by if by != "band" else "", dir="asc" if dd == "asc" else "")
    links = f'<a class="more" href="/api/v1/governance/settle-age.csv{q}" download>CSV →</a><a class="more" href="/api/v1/governance/settle-age{q}">API →</a>'
    note = (" The first close of a segment with a genesis import can settle answers from before the cut, so their origin reads as unknown." if d["genesis_import"] else "")
    cov = f'<p class="cov dim small">{E(TIP)} From the close records, by origin epoch.{note} <a href="{METHOD}">Method</a></p>'
    return (f'<div class="stats four">{s}</div>' + card("Answers by age", ch)
            + card(f"Settle age · {d['juried']:,}", tb + cov, links, cls="histc", id="settleage"))

BASE = "https://poascan.io"
def api(sort="band", d="desc"):
    dd = distribution(); rs = select(sort, d)
    return dict(segment=dd["segment"], archived=dd["archived"],
                source="close records (basis.settled by origin epoch; minepoa's engine settlement fold, reused from the Settlement view)",
                definitions=TIP, method=BASE + METHOD, url=BASE + "/governance?tab=settleage", sort=sort, dir=d,
                settled=dd["settled"], juried=dd["juried"], expired_no_jury=dd["expired"], unknown=dd["unknown"],
                median_age_epochs=dd["median"], closes=dd["closes"], first_close=dd["first_close"],
                genesis_import=dd["genesis_import"], pending_ttl=dd["pending_ttl"],
                note="Age in epochs = settle close minus origin epoch, over juried answers. " + OC.LABEL[OC.EXPIRED] + " and unknown origin are reported apart, never bucketed by age. A grading verdict is never read.",
                total=len(rs), rows=rs)
