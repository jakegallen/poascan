"""Grader patterns (1.26.183, LabLeak post 1595, comments 6021 and 6028): how each grader's settled seats compare with the
outcome and with the other jurors on the same answers. Advisory and unranked.

Reads grade_history only (gradehist.py: settled jury seats from the close records, scores 0 to 3 from settled juries in
minepoa's grading list), every seat, no cap. Pending answers and pending scores are never read. One network-wide timing
chart (answer tx to seal, on answers that later settled) uses seal timestamps POAScan already keeps (grading_seals) and the
answer tx time; it is never split by grader, since it mostly measures the queue and grade delivery, not care. No upstream
request: a page view or API call reads POAScan's own tables.

Fairness defaults (Jake, 2026-10-27): rows under MIN_N scored settled seats hidden (Segment 1, which has no scores: under
MIN_N settled seats), shown with the All chip; charts are distributions with no names; the table sorts A to Z by default;
system graders (params trusted_graders and system_grader_accounts) are tagged and left out of percentiles, medians and charts;
percentiles on hover; neutral labels."""
import collections, statistics, time
from html import escape as E
from . import db, analytics as A, segments as SG, scoresort as SS
from .analytics import cached

MIN_N = 20
METHOD = "/about#grader-patterns"
DAY = 86400
RANGES = [("24h", "24h", DAY), ("7d", "7d", 7 * DAY), ("30d", "30d", 30 * DAY), ("all", "All", None)]
SORTS = [("name", "Agent"), ("seats", "Seats"), ("agreement", "Agreement"), ("peers", "Peers"), ("spread", "Spread"), ("top_share", "Top score"),
         ("distance", "Distance"), ("closes", "Closes")]
SEG1_SORTS = [s for s in SORTS if s[0] not in ("spread", "top_share", "distance")]
PCT_KEYS = ("agreement", "peers", "spread", "top_share", "distance")
TIMING_MIN = 50          # fewer matched seals than this: the timing chart is not drawn
TIMING_BANDS = [(0, "<1h"), (1, "1h+"), (6, "6h+"), (12, "12h+"), (24, "24h+"), (48, "48h+"), (96, "96h+")]

TIPS = {
    "agreement": "Settled jury seats whose vote matched the final outcome. Agreement, not accuracy",
    "peers": "Agreement of the other jurors on the same answers. Read Agreement beside it: a hard close lowers both",
    "spread": "Standard deviation of this grader's 0 to 3 scores on settled answers",
    "top_share": "Share of scored seats that got this grader's most used score",
    "distance": "Mean gap between this grader's score and the other jurors' mean score on the same answer",
    "mix": "This grader's settled scores, 0 to 3",
}

def system_set():
    p = A.params()
    return set(p.get("trusted_graders") or []) | set(p.get("system_grader_accounts") or [])

def _closes_in(rng, now=None):
    """Close numbers of the selected segment inside the range (None: every close)."""
    span = dict((k, v) for k, _, v in RANGES).get(rng)
    if not span: return None
    t0 = (now or time.time()) - span
    return {int(e["epoch"]) for e in A.epochs_raw() if int(e.get("ts") or 0) >= t0}

def has_scores(seg=None):
    """True when the segment has any scored settled seat (Segment 1 has none)."""
    from . import gradehist as GH
    GH._ensure()
    return bool(db.q1("SELECT 1 AS x FROM grade_history WHERE seg=? AND score IS NOT NULL LIMIT 1", (seg or SG.selected(),)))

def _pctile(xs, v):
    if v is None or not xs: return None
    return round(100 * sum(1 for x in xs if x <= v) / len(xs))

@cached("grader_patterns", 300)
def patterns(rng="all", min_n=MIN_N):
    from . import gradehist as GH
    GH._ensure(); seg = SG.selected(); sc_on = has_scores(seg)
    cl = _closes_in(rng)
    rs = db.q("SELECT answer, grader, close, aligned, score FROM grade_history WHERE seg=?", (seg,))
    if cl is not None: rs = [r for r in rs if r["close"] in cl]
    by_ans = collections.defaultdict(list)
    for r in rs: by_ans[r["answer"]].append(r)
    g = collections.defaultdict(lambda: dict(seats=0, aligned=0, peers=[], scores=[], dist=[], closes=set()))
    for ans, js in by_ans.items():
        for r in js:
            x = g[r["grader"]]; x["seats"] += 1; x["aligned"] += r["aligned"]; x["closes"].add(r["close"])
            oth = [o for o in js if o["grader"] != r["grader"]]
            if oth: x["peers"].append(sum(o["aligned"] for o in oth) / len(oth))
            if sc_on and r["score"] is not None:
                x["scores"].append(r["score"])
                os_ = [o["score"] for o in oth if o["score"] is not None]
                if os_: x["dist"].append(abs(r["score"] - statistics.fmean(os_)))
    sysg = system_set(); nm = A.forum_names(); out = []
    for a, x in g.items():
        s = x["scores"]; hist = [s.count(k) for k in range(4)]
        top = max(range(4), key=lambda k: (hist[k], -k)) if s else None
        n_elig = len(s) if sc_on else x["seats"]
        row = dict(address=a, name=nm.get(a) or None, system=a in sysg, seats=x["seats"], aligned=x["aligned"],
                   agreement=round(x["aligned"] / x["seats"], 4) if x["seats"] else None,
                   peers=round(statistics.fmean(x["peers"]), 4) if x["peers"] else None, peer_seats=len(x["peers"]),
                   closes=len(x["closes"]), last_close=max(x["closes"]) if x["closes"] else None)
        if sc_on:
            row.update(scored=len(s), spread=round(statistics.stdev(s), 3) if len(s) > 1 else None,
                       top_score=top, top_share=round(hist[top] / len(s), 4) if s else None,
                       distance=round(statistics.fmean(x["dist"]), 3) if x["dist"] else None, mix={str(k): hist[k] for k in range(4)})
        row["below_min"] = n_elig < min_n
        out.append(row)
    pool = [r for r in out if not r["system"] and not r["below_min"]]
    keys = PCT_KEYS if sc_on else ("agreement", "peers")
    vals = {k: sorted(r[k] for r in pool if r.get(k) is not None) for k in keys}
    for r in out:
        r["percentiles"] = None if (r["system"] or r["below_min"]) else {k: _pctile(vals[k], r.get(k)) for k in keys}
    med = lambda k: round(statistics.median(vals[k]), 4) if vals.get(k) else None
    mix = [sum(r["mix"][str(k)] for r in pool) for k in range(4)] if sc_on else None
    return dict(segment=seg, archived=SG.archived(), range=rng, min_n=min_n, scores=sc_on, graders=len(out), pool=len(pool),
                seats=sum(r["seats"] for r in out), hidden=sum(1 for r in out if r["below_min"]),
                median=dict({k: med(k) for k in keys}), score_mix=mix,
                bands=dict(agreement=_bands([r["agreement"] for r in pool if r["agreement"] is not None], AG_BANDS),
                           spread=_bands([r["spread"] for r in pool if r.get("spread") is not None], SD_BANDS) if sc_on else None),
                timing=timing(rng), rows=out)

AG_BANDS = [(0, "<60%"), (.6, "60%+"), (.7, "70%+"), (.8, "80%+"), (.85, "85%+"), (.9, "90%+"), (.95, "95%+")]
SD_BANDS = [(0, "<0.4"), (.4, "0.4+"), (.5, "0.5+"), (.6, "0.6+"), (.7, "0.7+"), (.8, "0.8+"), (1, "1.0+")]

def _bands(vals, bands):
    out = []
    for i, (lo, lab) in enumerate(bands):
        hi = bands[i + 1][0] if i + 1 < len(bands) else float("inf")
        out.append(dict(band=lab, graders=sum(1 for v in vals if lo <= v < hi)))
    return out

def timing(rng="all"):
    """Network wide: hours from the answer tx to each seal, on settled seats in range whose seal POAScan saw in minepoa's
    grading list (grading_seals: grader and time only) and whose answer tx it holds. Never per grader."""
    from . import gradehist as GH, grading as GR
    GH._ensure(); GR._ensure(); seg = SG.selected(); cl = _closes_in(rng)
    seats = db.q("SELECT answer, grader, close FROM grade_history WHERE seg=?", (seg,))
    if cl is not None: seats = [r for r in seats if r["close"] in cl]
    if not seats: return dict(seals=0, median_hours=None, bands=[])
    sealt = {(r["answer"], r["grader"]): r["t"] for r in db.q("SELECT answer, grader, MIN(ts) AS t FROM grading_seals GROUP BY answer, grader")}
    want = list({r["answer"] for r in seats if (r["answer"], r["grader"]) in sealt})
    ats = {}
    for i in range(0, len(want), 500):
        ch = want[i:i + 500]
        for r in db.q(f"SELECT id, ts FROM txs WHERE id IN ({','.join('?' * len(ch))})", tuple(ch)): ats[r["id"]] = r["ts"]
    hrs = []
    for r in seats:
        t = sealt.get((r["answer"], r["grader"])); a = ats.get(r["answer"])
        if t and a and t >= a: hrs.append((t - a) / 3600)
    if len(hrs) < TIMING_MIN: return dict(seals=len(hrs), median_hours=None, bands=[])
    out = []
    for i, (lo, lab) in enumerate(TIMING_BANDS):
        hi = TIMING_BANDS[i + 1][0] if i + 1 < len(TIMING_BANDS) else float("inf")
        out.append(dict(band=lab, seals=sum(1 for h in hrs if lo <= h < hi)))
    return dict(seals=len(hrs), median_hours=round(statistics.median(hrs), 2), bands=out)

def select(rng="all", min_n=MIN_N, by="name", d="desc", show_all=False):
    p = patterns(rng, min_n); rows = [r for r in p["rows"] if show_all or not r["below_min"]]
    if by == "name": rows = SS.sort_rows(rows, lambda r: SS.text_key(r["name"]), "text", d, tie=lambda r: r["address"])
    else: rows = SS.sort_rows(rows, lambda r: r.get(by), "num", d, tie=lambda r: ((r["name"] or "~").lower(), r["address"]))
    return p, rows

# ---------------------------------------------------------------- HTML (Governance, Graders tab)
def _q(qs, k, dflt=""): return ((qs or {}).get(k) or [dflt])[0]

def section(qs, href):
    """Stats, distribution charts and the table. Query keys prange, psort, pdir, pn (all) so the other Graders tables keep theirs."""
    from .ui import card, stat, agent, bars, qtip, intc, pct
    rng = _q(qs, "prange", "all"); rng = rng if rng in dict((k, t) for k, t, _ in RANGES) else "all"
    show_all = _q(qs, "pn") == "all"
    sc_on = has_scores()
    sorts = dict(SORTS if sc_on else SEG1_SORTS)
    by = _q(qs, "psort", "name"); by = by if by in sorts else "name"; d = _q(qs, "pdir", "desc"); d = d if d in ("desc", "asc") else "desc"
    p, rows = select(rng, MIN_N, by, d, show_all)
    kw = lambda **o: dict(dict(prange=rng if rng != "all" else "", psort=by if by != "name" else "", pdir="asc" if d == "asc" else "", pn="all" if show_all else ""), **o)
    rchips = "".join(f'<a href="{href(**kw(prange=k if k != "all" else ""))}#patterns" class="chip {"on" if k == rng else ""}">{t}</a>' for k, t, _ in RANGES)
    nchips = (f'<a href="{href(**kw(pn=""))}#patterns" class="chip {"" if show_all else "on"}">n {MIN_N}+</a>'
              f'<a href="{href(**kw(pn="all"))}#patterns" class="chip {"on" if show_all else ""}">All</a>')
    m = p["median"]; f2 = lambda v: f'<span class="num">{v:.2f}</span>' if v is not None else '<span class="na">···</span>'
    unit = "scored settled seats" if sc_on else "settled seats"
    st = [stat("Graders", intc(p["pool"]), tip=f"Graders with {MIN_N} or more {unit} in range, system graders left out"),
          stat("Agreement", pct(m.get("agreement")), tip="Median across those graders: settled seats whose vote matched the final outcome")]
    if sc_on:
        st += [stat("Spread", f2(m.get("spread")), tip="Median across those graders: standard deviation of their 0 to 3 settled scores"),
               stat("Distance", f2(m.get("distance")), tip="Median across those graders: mean gap between a grader's score and the other jurors' mean score")]
    else:
        st += [stat("Peers", pct(m.get("peers")), tip="Median across those graders: agreement of the other jurors on the same answers"),
               stat("Seats", intc(p["seats"]), tip="Settled jury seats in range, every grader")]
    num = lambda v: f"{v:,.0f}"
    def chart(key, data, vk, color, title, tip):
        body = (bars([(b["band"], [b[vk]]) for b in data], height=150, colors=(color,), fmt=num) if data and any(b[vk] for b in data)
                else '<p class="na">Not enough settled seats in range.</p>')
        return card(title, body, qtip(tip, METHOD, f"About {title}"), cls="gpc")
    charts = [chart("agreement", p["bands"]["agreement"], "graders", "verd", "Agreement · graders",
                    f"How many graders fall in each agreement band. Distribution only, no names; graders under n {MIN_N} and system graders left out.")]
    if sc_on:
        charts.append(chart("spread", p["bands"]["spread"], "graders", "gold", "Spread · graders",
                            "How many graders fall in each spread band (standard deviation of their 0 to 3 settled scores). A low spread alone is not a fault: a grader can see similar answers."))
        mx = p["score_mix"] or [0, 0, 0, 0]
        charts.append(card("Score mix", bars([(str(k), [mx[k]]) for k in range(4)], height=150, colors=("ember",), fmt=num) if sum(mx) else '<p class="na">No settled scores in range.</p>',
                           qtip("Settled scores 0 to 3 from the graders in the Agreement chart. Scores on answers still pending are never read.", METHOD, "About Score mix"), cls="gpc"))
    t = p["timing"]
    if t["bands"]:
        charts.append(card("Answer to seal · seals", bars([(b["band"], [b["seals"]]) for b in t["bands"]], height=150, colors=("gold",), fmt=num),
                           qtip(f"Network wide, never per grader: hours from the answer tx to each seal on answers that later settled ({t['seals']:,} seals, median {t['median_hours']:.1f}h). "
                                "It mostly reflects queue wait, seat assignment and grade delivery, not how carefully anyone graded.", METHOD, "About Answer to seal"), cls="gpc"))
    T = lambda k: qtip(TIPS[k], METHOD, f"About {dict(SORTS + [('mix', 'Mix')])[k]}", "hv")
    cols = [SS.Col("name", "Agent", "text", "p"), SS.Col("seats", "Seats", "num", "r p"), SS.Col("agreement", "Agreement", "num", "r", T("agreement")),
            SS.Col("peers", "Peers", "num", "r dk", T("peers"))]
    if sc_on:
        cols += [SS.Col("spread", "Spread", "num", "r", T("spread")), SS.Col("top_share", "Top score", "num", "r dk", T("top_share")),
                 SS.Col("distance", "Distance", "num", "r dk", T("distance")), SS.Col(None, "Mix", "num", "dk", T("mix"))]
    cols.append(SS.Col("closes", "Closes", "num", "r dk"))
    pool = p["pool"]
    def cell(r, k, txt):
        pc = (r.get("percentiles") or {}).get(k)
        tt = f' title="Percentile {pc} of {pool} graders"' if pc is not None else ""
        return f'<span class="num"{tt}>{txt}</span>' if r.get(k) is not None else '<span class="na">···</span>'
    def mixbar(h):
        n = sum(h.values()) or 1
        segs = "".join(f'<i class="m{k}" style="width:{48 * h[str(k)] / n:.1f}px"></i>' for k in range(4) if h[str(k)])
        return f'<span class="mixb" title="0: {h["0"]:,} · 1: {h["1"]:,} · 2: {h["2"]:,} · 3: {h["3"]:,}">{segs}</span>' if sum(h.values()) else '<span class="na">···</span>'
    trs = []
    for r in rows:
        tail = '<span class="tag">system</span>' if r["system"] else ""
        low = ' class="low"' if r["below_min"] else ""
        tds = (f'<td class="p">{agent(r["address"], r["name"] or "", tail=tail)}</td><td class="r p">{intc(r["seats"])}</td>'
               f'<td class="r">{cell(r, "agreement", f"{100 * (r["agreement"] or 0):.1f}%")}</td><td class="r dk">{cell(r, "peers", f"{100 * (r["peers"] or 0):.1f}%")}</td>')
        if sc_on:
            tds += (f'<td class="r">{cell(r, "spread", f"{r.get("spread") or 0:.2f}")}</td><td class="r dk">{cell(r, "top_share", f"{100 * (r.get("top_share") or 0):.1f}%")}</td>'
                    f'<td class="r dk">{cell(r, "distance", f"{r.get("distance") or 0:.2f}")}</td><td class="dk">{mixbar(r["mix"])}</td>')
        tds += f'<td class="r dk">{intc(r["closes"])}</td>'
        trs.append(f"<tr{low}>{tds}</tr>")
    link = lambda k, dd: href(**kw(psort=k if k != "name" else "", pdir="asc" if dd == "asc" else "")) + "#patterns"
    tb = (SS.select(cols, by, d, link) + f'<div class="tw"><table class="hist cal gov gpat"><thead><tr>{SS.heads(cols, by, d, link)}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'
          if rows else f'<p class="na">No grader with {MIN_N} or more {unit} in range.</p>')
    seg1 = "" if sc_on else " This segment has no settled scores, so only Agreement and Peers are shown."
    foot = (f'<p class="cov dim small">Advisory: agreement with the outcome is not accuracy. Settled seats only.{seg1} '
            + (f"{p['hidden']} under n {MIN_N} hidden. " if p["hidden"] and not show_all else "")
            + f'System graders tagged and left out of percentiles, medians and charts. Hover a value for its percentile. <a href="{METHOD}">Method</a></p>')
    qp = [("range", rng) if rng != "all" else None, ("sort", by) if by != "name" else None, ("dir", "asc") if d == "asc" else None,
          ("min_n", "0") if show_all else None, ("segment", str(SG.selected())) if SG.archived() else None]
    qq = "&amp;".join(f"{k}={v}" for k, v in (x for x in qp if x)); qq = "?" + qq if qq else ""
    links = f'<a class="more" href="/api/v1/governance/grader-patterns.csv{qq}">CSV</a> <a class="more" href="/api/v1/governance/grader-patterns{qq}">API →</a>'
    head = f'<div class="chips"><span class="tag warn" title="Agreement with the settled outcome, not accuracy">Advisory</span>{rchips}{nchips}</div>'
    stats = f'<div class="stats four gpst">{"".join(st)}</div>'
    tcard = card(f"Grader patterns · {len(rows):,}", head + stats + tb + foot, links, cls="histc", id="patterns")
    grid = "".join(f'<div class="grid2">{"".join(charts[i:i + 2])}</div>' for i in range(0, len(charts), 2))
    return tcard + grid

# ---------------------------------------------------------------- API
def api(rng="all", sort="name", d="desc", min_n=MIN_N, limit=1000, offset=0):
    """GET /api/v1/governance/grader-patterns."""
    if sort not in dict(SORTS): sort = "name"
    p, rows = select(rng, min_n, sort, d, show_all=True)
    keep = [r for r in rows if not r["below_min"]] if min_n else rows
    out = []
    for r in keep[offset:offset + limit]:
        x = dict(r); x["profile"] = f"https://minepoa.com/lableak/#/u/{r['address']}" if r["name"] else None; out.append(x)
    return dict(segment=p["segment"], archived=p["archived"], range=rng, min_n=min_n, scores=p["scores"],
                source="grade_history: settled jury seats from the close records, scores (0 to 3) from settled juries in minepoa's grading list; timing from POAScan's seal store and answer txs",
                note=("Advisory: agreement with the settled outcome is not accuracy. Settled seats only; pending answers and pending scores are never read. "
                      "System graders are flagged and left out of percentiles, medians and bands. Answer to seal timing is network wide only. "
                      + ("" if p["scores"] else "This segment has no settled scores: spread, top_share, distance and mix are omitted.")),
                graders=p["graders"], pool=p["pool"], hidden=p["hidden"], seats=p["seats"], median=p["median"], bands=p["bands"], score_mix=p["score_mix"],
                timing=p["timing"], sort=sort, dir=d, total=len(keep), offset=offset, limit=limit, method="https://poascan.io" + METHOD, rows=out)

CSV_FIELDS = ("address", "name", "system", "seats", "aligned", "agreement", "peers", "peer_seats", "scored", "spread", "top_score", "top_share", "distance",
              "mix_0", "mix_1", "mix_2", "mix_3", "closes", "last_close", "below_min")

def csv_rows(rows):
    out = []
    for r in rows:
        m = r.get("mix") or {}
        out.append({k: (m.get(k[-1]) if k.startswith("mix_") else r.get(k)) for k in CSV_FIELDS})
    return out
