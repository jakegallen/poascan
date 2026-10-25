"""Governance (1.26.96): one page with chip tabs for where every established Agent stands, who grades and how the rules read.

Tabs: Overview, At risk, Graders, Charts, Rules. Every number comes from close records POAScan already archives
(analytics.established_set, last_eligible, epoch_rows; calibration) and /api/params. No new upstream reads.
Levels use the observed L + 7 drop rule (standing.py): At risk within the next 2 closes, Watch at 3, Safe at 4 or more."""
import time, datetime as dt, collections
from . import db, analytics as A, standing as SD, segments as SG, calibration as CA, govscore as GS, scoresort as SS, grading as GR
from .ui import E, card, stat, intc, pct, short, name_link, line, table, bars, compact, qtip, lt, utc_text, iso_ts as _iso
from . import views as V

TABS = [("overview", "Overview"), ("established", "Established"), ("at-risk", "At risk"), ("payouts", "Payouts"), ("graders", "Graders"), ("directory", "Directory"), ("forum", "Forum"), ("proposals", "Proposals"), ("charts", "Charts"), ("rules", "Rules")]
LEVELS = [("risk", "At risk"), ("watch", "Watch"), ("safe", "Safe"), ("norecord", "No record"), ("system", "System")]
AGENT_COL = SS.Col("name", "Agent", "text")   # header sorting (1.26.117): Agent sorts by name A to Z, unnamed Agents last
LEVEL_ORDER = {k: i for i, (k, _) in enumerate(LEVELS)}

def _nm_tie(r): return ((r.get("name") or "~").lower(), r.get("address") or r.get("pid") or "")
LEVEL_TAG = {"risk": "warn", "watch": "est", "safe": "ok", "norecord": "", "system": ""}
RULE = {"risk": "lapse", "watch": "lapse", "safe": "lapse", "norecord": "no-record", "system": "system"}
DAY = 86400
RANGES = [("24h", "24h", DAY), ("7d", "7d", 7 * DAY), ("30d", "30d", 30 * DAY), ("all", "All", None)]
GO = '<a href="https://minepoa.com/go.md" target="_blank" rel="noopener noreferrer">go.md</a>'
SK = '<a href="https://minepoa.com/skill.md" target="_blank" rel="noopener noreferrer">skill.md</a>'

def _q(qs, k, d=""): return ((qs or {}).get(k) or [d])[0]

def href(tab, **kw):
    """/governance link that keeps an archived segment."""
    q = ([] if tab == "overview" else [("tab", tab)]) + [(k, v) for k, v in kw.items() if v and not k.startswith("_")] + ([("segment", str(SG.selected()))] if SG.archived() else [])
    return "/governance" + ("?" + "&amp;".join(f"{k}={E(v)}" for k, v in q) if q else "")

def segment_standing():
    """(established set, last challenge_eligible close per address) from the selected segment's own close records only.
    Governance shows standing fresh at a genesis cut (segment 1 standing stays under Segment 1). Same fold as
    analytics.established_set: established_after adds, established_removed drops, a grading seat within estab_ttl
    closes after the last removal counts, plus trusted and system graders."""
    eps = sorted(A.segment_closes(SG.selected()), key=lambda e: int(e.get("epoch", 0)))
    pp = A.params(); ttl = int(pp.get("estab_ttl") or 6); tr = SD._trusted()
    est, seat, removed, le = set(), {}, {}, {}
    for e in eps:
        n = int(e.get("epoch", 0)); b = e.get("basis", {}) or {}
        seated = set(b.get("graders_served", {}) or {}) | {j.get("grader") for x in (b.get("settled") or []) for j in (x.get("jury") or []) if j.get("grader")}
        for a in seated: seat[a] = n
        gone = set(b.get("established_removed", []) or [])
        for a in gone: removed[a] = n
        est = (est - gone) | set(b.get("established_after", []) or [])
        for a in b.get("challenge_eligible", []) or []: le[a] = n
    if eps:
        last = int(eps[-1].get("epoch", 0))
        est |= {a for a, n in seat.items() if n > removed.get(a, -1) and n > last - ttl}
        est |= tr & (set(seat) | est)
    return est, le

def level_of(left):
    return "risk" if left <= SD.AT_RISK_CLOSES else "watch" if left == SD.AT_RISK_CLOSES + 1 else "safe"

def standing_rows():
    """Every Agent in the established set with its last cleared close L, drop close L + ttl + 1, closes left and level.
    In an archived segment the reference is the close after its last one."""
    ep = A.epoch_rows(); ttl = int(A.params().get("estab_ttl") or 6)
    if SG.archived(): cur = (ep[-1]["epoch"] + 1) if ep else None
    else: cur = A.open_epoch().get("epoch")
    est, le = segment_standing(); tr = SD._trusted(); nm = A.forum_names(); last = ep[-1]["epoch"] if ep else None
    rows = []
    for a in est:
        L = le.get(a)
        if a in tr: lv, drop, left = "system", None, None
        elif L is None or cur is None: lv, drop, left = "norecord", None, None
        else: drop = L + ttl + 1; left = max(0, drop - cur + 1); lv = level_of(left)
        rows.append(dict(address=a, name=nm.get(a), last=L, drop=drop, left=left, level=lv,
                         missed=(last - L) if (L is not None and last is not None) else None))
    order = {k: i for i, (k, _) in enumerate(LEVELS)}
    rows.sort(key=lambda r: (order[r["level"]], r["drop"] if r["drop"] is not None else 1 << 30, (r["name"] or "~").lower(), r["address"]))
    return dict(rows=rows, open_epoch=cur, ttl=ttl, last_close=last,
                counts={k: sum(1 for r in rows if r["level"] == k) for k, _ in LEVELS})

def _agent(r, est=False):
    """Agent cell: name (LabLeak) with the short address under it. est: an established row, tagged Unconfirmed when
    minepoa's grading list does not have it (grading.established_check)."""
    a = r["address"]; al = f'<a class="mono" href="/address/{E(a)}#standing" title="{E(a)}">{E(short(a, 6, 4))}</a>'
    tg = GR.tag_html(GR.established_check(a)[2]) if est else ""
    return ((name_link(r["name"], a) + tg + f"<small>{al}</small>") if r["name"] else al + tg)

def unconfirmed_flag(addrs):
    """The Unconfirmed tag for an Established count when minepoa's grading list leaves out some of these Agents."""
    c = GR.conflict_summary(addrs)
    if not c or not c["conflict"]: return ""
    q = sum(1 for a in addrs if a not in GR.index()["established"] and (GR.index()["by_g"].get(a) or {}).get("qual"))
    lead = "minepoa's grading list shows none" if c["list_empty"] else f"{c['conflict']:,} not on minepoa's grading list"
    return GR.tag_html(lead + (f"; seals from {q:,} of these Agents still count toward quorum." if q else "; hosted /me is the authority."))

def _ep(n): return f'<a href="/epoch/{n}{SG.qs()}">E{n}</a>' if n is not None else '<span class="dim">···</span>'

def _lvl(k): return f'<span class="tag {LEVEL_TAG[k]}">{dict(LEVELS)[k]}</span>'

RISK_COLS = [AGENT_COL] + [None] + [SS.Col("level", "Level", "cat", "r"), SS.Col("left", "Closes left", "low", "r"), SS.Col("missed", "Missed", "num", "r dk"),
                                    SS.Col("last", "Last cleared", "num", "r dk"), SS.Col("drop", "Drops at", "num", "r"), SS.Col(None, "Rule", "num", "r dk")]

def risk_cols(): return [c for x in RISK_COLS for c in ([x] if x else score_cols())]

def standing_table(rows, limit=None, sort=None, d="desc", link=None):
    """Standing rows with Score and parts (scores of the selected segment). link(key, dir): sortable headers; None: plain."""
    rs = rows[:limit] if limit else rows; sc = scores()["rows"]
    trs = "".join(f'<tr><td>{_agent(r, True)}</td>{score_cells(parts_of(r["address"], sc))}<td class="r">{_lvl(r["level"])}</td><td class="r">{r["left"] if r["left"] is not None else "<span class=dim>···</span>"}</td>'
                  f'<td class="r dk">{r["missed"] if r["missed"] is not None else "<span class=dim>···</span>"}</td><td class="r dk">{_ep(r["last"])}</td><td class="r">{_ep(r["drop"])}</td>'
                  f'<td class="r dk"><a href="{href("rules")}#{RULE[r["level"]]}">Rule</a></td></tr>' for r in rs)
    return ((SS.select(risk_cols(), sort, d, link) if link else "") + f'<div class="tw"><table class="hist cal risk gov"><thead><tr>{SS.heads(risk_cols(), sort, d, link)}</tr></thead>'
            f'<tbody>{trs or "<tr><td colspan=12 class=na>No established Agents in this segment yet.</td></tr>"}</tbody></table></div>')

def seg_chips(tab):
    if not SG.has_cut(): return ""
    cur = SG.selected(); out = []
    for n in reversed(SG.NUMBERS):
        q = ([] if tab == "overview" else [f"tab={tab}"]) + ([] if n == SG.CURRENT else [f"segment={n}"])
        h = "/governance" + ("?" + "&amp;".join(q) if q else "")
        out.append(f'<a href="{h}" class="chip {"on" if n == cur else ""}"{" aria-current=\"page\"" if n == cur else ""}>{E(SG.label(n))}</a>')
    return '<nav class="chips segs" aria-label="Segment">' + "".join(out) + "</nav>"

def overview():
    d = standing_rows(); c = d["counts"]; cal = CA.calibration(); ep = A.epoch_rows()
    f2 = lambda v: pct(v) if v is not None else "···"
    s = "".join([stat("Established", intc(len(d["rows"])), flag_html=unconfirmed_flag([r["address"] for r in d["rows"]])), stat("At risk", intc(c["risk"]), tip=f"Estimated to drop within the next {SD.AT_RISK_CLOSES} closes"),
                 stat("Watch", intc(c["watch"]), tip=f"Estimated to drop in {SD.AT_RISK_CLOSES + 1} closes"), stat("Safe", intc(c["safe"])),
                 stat("Graders", intc(cal.get("graders_count"))), stat("Agreement", f2(cal.get("aligned_rate")), tip="Jury seats aligned with the panel, advisory")])
    risky = [r for r in d["rows"] if r["level"] in ("risk", "watch")]
    t = standing_table(risky, 8) if risky else '<p class="na">No established Agent is estimated to drop in the next 3 closes.</p>'
    last = [[_ep(r["epoch"]), intc(r["established"]), intc(r["established_removed"]), intc(r["challenge_eligible"]), intc(r["paid"])] for r in reversed(ep[-6:])]
    lt = table(["Close", "Added", "Removed", "Eligible", "Paid"], last) if last else '<p class="na">No closes in this segment yet.</p>'
    return (f'<div class="stats six">{s}</div><div class="grid2">'
            + card("At risk and Watch", t, f'<a class="more" href="{href("at-risk")}">All →</a>', cls="histc")
            + estimate_card() + "</div>"
            + card("Latest closes", lt, f'<a class="more" href="{href("charts")}">Charts →</a>'))

def estimate_card():
    """Overview: the next close's Est. per Agent, labelled Estimate, with its basis closes (current segment; none in an archived one)."""
    tag = '<span class="tag est">Estimate</span>'
    if SG.archived(): return card("Est. per Agent " + tag, '<p class="na">Shown for the current segment only.</p>', id="est-payout")
    pe = payout_estimate(); o, K, ans = answered_since_close(); other = pe["basis_segment"] != SG.CURRENT
    v = f'<span class="num">{compact(pe["estimate"])}</span>' if pe["estimate"] is not None else "···"
    basis = ", ".join(f'E{b["epoch"]}' for b in pe["basis"]) or "none"
    s = "".join([stat("Est. per Agent", v, tip="Estimate: " + pe["method"]), stat("Answered", intc(ans["n"]) if ans else "···", tip="Agents with a challenge answer since the last close"),
                 stat("K-attested", intc(ans["k"]) if ans else "···", tip=f"Answers with {K} or more attestations")])
    seg = f" (segment {pe['basis_segment']})" if other else ""
    foot = f'<p class="cov dim small">Next close E{o.get("epoch")} · basis {E(basis)}{seg} · until the close record lands</p>'
    return card("Est. per Agent " + tag, f'<div class="stats three">{s}</div>' + foot, f'<a class="more" href="{href("payouts")}">Payouts →</a>', id="est-payout")

RISK_SORTS = [("level", "Level")] + SS.PARTS + [("name", "Agent"), ("left", "Closes left"), ("missed", "Missed"), ("last", "Last cleared"), ("drop", "Drops at")]

def standing_select(level="", by="level", d="desc"):
    """Standing rows for a level filter, sorted by level (soonest drop first, the standing order), Score or a part, or a
    column (Agent A to Z, closes left, missed, last cleared, drops at); blanks last."""
    data = standing_rows(); rows = [r for r in data["rows"] if not level or r["level"] == level]
    if by == "level": return (list(reversed(rows)) if d == "asc" else rows), data
    if by == "name": return SS.sort_rows(rows, lambda r: SS.text_key(r["name"]), "text", d, tie=_nm_tie), data
    if by in SS.KEYS:
        sc = scores()["rows"]; return SS.sort_rows(rows, lambda r: parts_of(r["address"], sc)[by], "num", d, tie=_nm_tie), data
    return SS.sort_rows(rows, lambda r: r[by], "low" if by == "left" else "num", d, tie=_nm_tie), data

def at_risk(qs):
    """The two-close at-risk list (standing.at_risk, as on the address page), then every established Agent with its level."""
    f = _q(qs, "level"); f = f if f in dict(LEVELS) else ""
    by = SS.page_sort(qs, dict(RISK_SORTS), "level"); d = SS.page_dir(qs)
    rows, data = standing_select(f, by, d); c = data["counts"]
    keep = dict(sort=by if by != "level" else "", dir="asc" if d == "asc" else "")
    chips = f'<a href="{href("at-risk", **keep)}#standing" class="chip {"on" if not f else ""}">All</a>' + "".join(
        f'<a href="{href("at-risk", level=k, **keep)}#standing" class="chip {"on" if k == f else ""}">{t} <small>{c[k]:,}</small></a>' for k, t in LEVELS if c[k] or k == f)
    link = lambda k, dd: href("at-risk", level=f, sort=k if k != "level" else "", dir="asc" if dd == "asc" else "") + "#standing"
    foot = f'<p class="cov dim small">Reference E{data["open_epoch"]} · <a href="{href("rules")}#lapse">Rule</a></p>' if data["open_epoch"] is not None else ""
    q = qsx(level=LEVEL_KEYS.get(f, ""), sort=by if by != "level" else "", dir="asc" if d == "asc" else "")
    links = f'<a class="more" href="/api/v1/governance/at-risk.csv{q}" download>CSV →</a><a class="more" href="/api/v1/governance/at-risk{q}">API →</a>'
    # One segment (no cut): the two-close list as on the address page first. With a cut, standing starts fresh in each
    # segment, so the level chips on the one table are the at-risk view.
    top = "" if SG.has_cut() else V.at_risk_body(qs, href("at-risk"))
    return top + card(f"Standing · {len(rows):,}", f'<div class="chips">{chips}</div>' + standing_table(rows, sort=by, d=d, link=link) + foot, links, cls="histc", id="standing")

def jury_series():
    """Per close of the selected segment: jury seats aligned and not aligned (settled[].jury[]), queue and empty panels."""
    out = []
    for e in sorted(A.segment_closes(SG.selected()), key=lambda e: int(e.get("epoch", 0))):
        b = e.get("basis", {}) or {}; js = [j for x in (b.get("settled") or []) for j in (x.get("jury") or [])]
        pend = b.get("pending") or {}; pend = pend if isinstance(pend, dict) else {}
        out.append(dict(epoch=int(e.get("epoch", 0)), aligned=sum(1 for j in js if j.get("aligned")), other=sum(1 for j in js if not j.get("aligned")),
                        queue=len(pend), empty=sum(1 for v in pend.values() if not (v or {}).get("panel"))))
    return out

def seals_since_close():
    """grade-sealed txs after the selected segment's last close, per grader (archived tx stream, this segment)."""
    ep = A.epoch_rows(); t = ep[-1]["close_ts"] if ep else 0
    w, a = SG.sql()
    rows = db.q("SELECT from_addr AS g, COUNT(*) AS n FROM txs WHERE type='grade-sealed' AND from_addr IS NOT NULL AND ts > ?" + w + " GROUP BY from_addr ORDER BY n DESC", (t,) + a)
    return t, [(r["g"], r["n"]) for r in rows]

GRADER_SORTS = [("seals", "Seals")] + SS.PARTS + [("name", "Agent")]

def grader_cols(): return [AGENT_COL, SS.Col("seals", "Seals", "num", "r"), SS.Col("score", "Score", "num", "r", score_tip())]

def seals_select(by="seals", d="desc"):
    t, ss = seals_since_close(); sc = scores()["rows"]; nm = A.forum_names()
    rows = [dict(address=g, name=nm.get(g), seals=n, **parts_of(g, sc)) for g, n in ss]
    if by == "name": return t, SS.sort_rows(rows, lambda r: SS.text_key(r["name"]), "text", d, tie=lambda r: r["address"])
    return t, SS.sort_rows(rows, lambda r: r[by], "num", d, tie=lambda r: r["address"])

def graders(qs):
    js = jury_series(); nm = A.forum_names(); last = js[-1] if js else None
    by = SS.page_sort(qs, dict(GRADER_SORTS), "seals"); d = SS.page_dir(qs)
    t, rows = seals_select(by, d)
    seats = sum(x["aligned"] + x["other"] for x in js)
    cov = (1 - last["empty"] / last["queue"]) if last and last["queue"] else None
    s = "".join([stat("Graders now", intc(len(rows)), tip="Agents with a grade-sealed tx since the last close"), stat("Seals now", intc(sum(r["seals"] for r in rows)), tip="grade-sealed txs since the last close"),
                 stat("Queue", intc(last["queue"]) if last else "···", tip="Pending answers at the last close"), stat("Coverage", pct(cov) if cov is not None else "···", tip="Pending answers with a panel at the last close")])
    ch = bars([(f'E{x["epoch"]}', [x["aligned"], x["other"]]) for x in js], height=150, colors=("verd", "ember"), fmt=lambda v: f"{v:,.0f}", legend=["Aligned", "Not aligned"]) if seats else '<p class="na">No settled jury seats in this segment yet.</p>'
    def ag(g):
        a = f'<a class="mono" href="/address/{E(g)}" title="{E(g)}">{E(short(g, 6, 4))}</a>'
        return (name_link(nm[g], g) + f"<small>{a}</small>") if nm.get(g) else a
    trs = "".join(f'<tr><td>{ag(r["address"])}</td><td class="r">{intc(r["seals"])}</td><td class="r">{_score_cell(r["score"])}</td></tr>' for r in rows[:10])
    link = lambda k, dd: href("graders", sort=k if k != "seals" else "", dir="asc" if dd == "asc" else "") + "#seals"
    st = (SS.select(grader_cols(), by, d, link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(grader_cols(), by, d, link)}</tr></thead><tbody>{trs}</tbody></table></div>'
          if rows else '<p class="na">No seals since the last close.</p>')
    q = qsx(sort=by if by != "seals" else "", dir="asc" if d == "asc" else "")
    return (f'<div class="stats four">{s}</div><div class="grid2">' + card("Jury seats per close", ch)
            + card("Seals since close", st, f'<a class="more" href="/api/v1/governance/graders{q}">API →</a>', id="seals") + "</div>"
            + V.graders_body(qs, href("graders")))

def payout_estimate():
    """Est. per Agent for the next close: the median of the per-Agent median reward at the last 3 paid closes of the
    current segment, else of segment 1's last 3 (tagged). An Estimate until the close record lands."""
    def paid(n):
        with SG.use(n): return [r for r in A.epoch_rows() if r["paid"] and r["median"]][-3:]
    basis, seg = paid(SG.CURRENT), SG.CURRENT
    if not basis:
        prev = [n for n in SG.NUMBERS if n < SG.CURRENT]
        if prev: seg = prev[-1]; basis = paid(seg)
    vals = sorted(r["median"] for r in basis)
    est = vals[len(vals) // 2] if vals else None
    return dict(estimate=est, basis=[dict(epoch=r["epoch"], segment=seg, paid=r["paid"], median=r["median"], max=r["max"], pool=r["pool"], burn_pct=r["burn_pct"]) for r in basis],
                basis_segment=seg, method="median of the per-Agent median reward at the last 3 paid closes")

def answered_since_close():
    """(open epoch, K, {n, k}): Agents with a challenge answer since the last close, and those with K or more attestations.
    Current segment only; empty in an archived segment."""
    o = A.open_epoch() if not SG.archived() else {}; K = int(A.params().get("K") or 5); t0 = o.get("last_close"); w, a = SG.sql()
    ans = db.q1("SELECT COUNT(DISTINCT from_addr) AS n, COUNT(DISTINCT CASE WHEN atts >= ? THEN from_addr END) AS k FROM txs WHERE type='challenge' AND ts > ?" + w, (K, t0) + a) if t0 else None
    return o, K, ans

def payouts(qs):
    pe = payout_estimate(); o, K, ans = answered_since_close()
    tag = '<span class="tag est">Estimate</span>'
    other = pe["basis_segment"] != SG.CURRENT
    est = (f'<span class="num">{compact(pe["estimate"])}</span>' if pe["estimate"] is not None else "···")
    ec = o.get("est_close")
    nxt = (f'<time class="t" data-ts="{int(ec)}" title="{utc_text(ec)}, estimate">~{max(0, int(ec - time.time())) // 3600}h {max(0, int(ec - time.time())) % 3600 // 60}m</time>') if ec else "···"
    s = "".join([stat(f"E{o['epoch']} close" if o.get("epoch") is not None else "Next close", nxt, tip="Last close plus auto_epoch_seconds, an estimate"),
                 stat("Answered", intc(ans["n"]) if ans else "···", tip="Agents with a challenge answer since the last close"),
                 stat("K-attested", intc(ans["k"]) if ans else "···", tip=f"Of those, answers with {K} or more attestations"),
                 stat("Est. per Agent", est, tip="Estimate: " + pe["method"] + (f", segment {pe['basis_segment']}" if other else "")),
                 stat("Pool", compact(o.get("pool")) if o.get("pool") else "···", tip="E0 halved every halving_epochs")])
    pcols = [SS.Col("epoch", "Close"), SS.Col("paid", "Paid"), SS.Col("median", "Per Agent"), SS.Col("max", "Max"), SS.Col("burn_pct", "Burned")]
    pby = _q(qs, "sort", "epoch"); pby = pby if pby in [c.key for c in pcols] else "epoch"; pd_ = SS.page_dir(qs)
    basis = SS.sort_rows(list(pe["basis"]), lambda r: r.get(pby), "num", pd_, tie=lambda r: -r["epoch"])
    plink = lambda k, dd: href("payouts", sort=k if k != "epoch" else "", dir="asc" if dd == "asc" else "") + "#estimate"
    rows = [[f'<a href="/epoch/{r["epoch"]}{SG.qs(r["segment"])}">E{r["epoch"]}</a>' + (f' <span class="tag">S{r["segment"]}</span>' if other else ""), intc(r["paid"]), compact(r["median"]), compact(r["max"]),
             f'{r["burn_pct"]:.1f}%' if r["burn_pct"] is not None else "···"] for r in basis]
    bt = table([], rows, sort=(pcols, pby, pd_, plink)) if rows else '<p class="na">No paid closes yet.</p>'
    ep = A.epoch_rows()
    pc = bars([(f'E{r["epoch"]}', [r["challenge_eligible"], r["paid"]]) for r in ep], height=150, colors=("gold", "steel"), fmt=lambda v: f"{v:,.0f}", stacked=False, legend=["Eligible", "Paid"]) if ep else '<p class="na">No closes in this segment yet.</p>'
    head = "" if SG.archived() else f'<div class="stats five">{s}</div>'
    return (head + '<div class="grid2">' + card("Last paid closes " + tag, bt, cls="histc", id="estimate")
            + card("Eligible and paid per close", pc) + "</div>")

DIR_SORTS = [("rewards", "Rewards"), ("eligible", "Eligible closes"), ("seals", "Seals"), ("atts", "Attestations")] + SS.PARTS + [("name", "Agent"), ("last_paid", "Last paid")]

def dir_cols():
    return [AGENT_COL] + score_cols() + [SS.Col("rewards", "Rewards", "num", "r"), SS.Col("last_paid", "Last paid", "num", "r dk"), SS.Col("eligible", "Eligible", "num", "r"),
                                         SS.Col("seals", "Seals", "num", "r"), SS.Col("atts", "Attestations", "num", "r dk")]
DIR_FILTERS = [("", "All"), ("established", "Established"), ("graders", "Graders"), ("attesters", "Attesters")]
DIR_PAGE = 100

@A.cached("gov_directory", 300)
def directory_rows():
    """Every Agent seen in the selected segment's close records or archived txs, with this segment's rewards, last paid
    close, eligible closes, seals, attestations, grading seats and established flag."""
    eps = sorted(A.segment_closes(SG.selected()), key=lambda e: int(e.get("epoch", 0)))
    est, le = segment_standing(); nm = A.forum_names()
    rw, lp, el, at, seat = collections.Counter(), {}, collections.Counter(), collections.Counter(), collections.Counter()
    for e in eps:
        n = int(e.get("epoch", 0)); b = e.get("basis", {}) or {}
        for a, v in (e.get("rewards") or {}).items():
            try: rw[a] += float(v); lp[a] = n
            except (TypeError, ValueError): pass
        for a in b.get("challenge_eligible", []) or []: el[a] += 1
        for a, v in (b.get("attestations") or {}).items():
            try: at[a] += int(v)
            except (TypeError, ValueError): pass
        for a in (b.get("graders_served") or {}): seat[a] += 1
    w, args = SG.sql()
    seals = {r["g"]: r["n"] for r in db.q("SELECT from_addr AS g, COUNT(*) AS n FROM txs WHERE type='grade-sealed' AND from_addr IS NOT NULL" + w + " GROUP BY from_addr", args)}
    addrs = set(rw) | set(el) | set(at) | set(seat) | set(seals) | est
    sc = scores()["rows"]
    return [dict(address=a, name=nm.get(a), established=a in est, rewards=rw.get(a, 0.0), last_paid=lp.get(a), eligible=el.get(a, 0),
                 seals=seals.get(a, 0), atts=at.get(a, 0), seats=seat.get(a, 0), **parts_of(a, sc)) for a in addrs if a and a.startswith("poa1")]

def directory_select(by="rewards", f="", d="desc"):
    """Directory rows for one sort (rewards, eligible, seals, atts, Score or a part, name, last_paid; desc or asc) and filter ("", established, graders, attesters)."""
    keep = {"": lambda r: True, "established": lambda r: r["established"], "graders": lambda r: r["seats"] or r["seals"], "attesters": lambda r: r["atts"]}[f]
    rows = [r for r in directory_rows() if keep(r)]
    if by == "name": return SS.sort_rows(rows, lambda r: SS.text_key(r["name"]), "text", d, tie=_nm_tie)
    return SS.sort_rows(rows, lambda r: r[by], "num", d, tie=_nm_tie)

def directory(qs):
    rows = directory_rows(); by = SS.page_sort(qs, dict(DIR_SORTS), "rewards"); d = SS.page_dir(qs)
    f = _q(qs, "filter"); f = f if f in dict(DIR_FILTERS) else ""
    rs = directory_select(by, f, d)
    try: pg = max(1, int(_q(qs, "page", "1")))
    except ValueError: pg = 1
    pages = max(1, -(-len(rs) // DIR_PAGE)); pg = min(pg, pages); cur = rs[(pg - 1) * DIR_PAGE: pg * DIR_PAGE]
    kw = lambda **o: dict(dict(sort=by if by != "rewards" else "", dir="asc" if d == "asc" else "", filter=f), **o)
    link = lambda k, dd: href("directory", **kw(sort=k if k != "rewards" else "", dir="asc" if dd == "asc" else "", page="")) + "#directory"
    fc = "".join(f'<a href="{href("directory", **kw(filter=k))}" class="chip {"on" if k == f else ""}">{t}</a>' for k, t in DIR_FILTERS)
    tags = lambda r: (' <span class="tag ok">Established</span>' + GR.tag_html(GR.established_check(r["address"])[2]) if r["established"] else "") + (' <span class="tag">Grader</span>' if r["seats"] or r["seals"] else "")
    trs = "".join(f'<tr><td>{_agent(r)}{tags(r)}</td>{score_cells(r)}<td class="r">{compact(r["rewards"]) if r["rewards"] else "<span class=dim>0</span>"}</td><td class="r dk">{_ep(r["last_paid"])}</td>'
                  f'<td class="r">{r["eligible"]:,}</td><td class="r">{r["seals"]:,}</td><td class="r dk">{r["atts"]:,}</td></tr>' for r in cur)
    tb = (SS.select(dir_cols(), by, d, link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(dir_cols(), by, d, link)}</tr></thead>'
          f'<tbody>{trs or "<tr><td colspan=11 class=na>No Agents in this segment yet.</td></tr>"}</tbody></table></div>')
    nav = ""
    if pages > 1:
        nav = ('<div class="chips">' + (f'<a class="chip" href="{href("directory", **kw(page=str(pg - 1) if pg > 2 else ""))}">Newer</a>' if pg > 1 else "")
               + f'<span class="dim small">Page {pg} of {pages}</span>' + (f'<a class="chip" href="{href("directory", **kw(page=str(pg + 1)))}">More</a>' if pg < pages else "") + "</div>")
    s = "".join([stat("Agents", intc(len(rows))), stat("Established", intc(sum(1 for r in rows if r["established"]))),
                 stat("Graders", intc(sum(1 for r in rows if r["seats"] or r["seals"]))), stat("Attesters", intc(sum(1 for r in rows if r["atts"])))])
    q = qsx(sort=by if by != "rewards" else "", dir="asc" if d == "asc" else "", filter=f)
    links = (f'<a class="more" href="/api/v1/governance/directory.csv{q}" download>CSV →</a>'
             f'<a class="more" href="/api/v1/governance/directory{q}">API →</a>')
    return f'<div class="stats four">{s}</div>' + card(f"Directory · {len(rs):,}", f'<div class="chips">{fc}</div>' + tb + nav, links, cls="histc", id="directory")

SCORE_METHOD = "/about#score"
def score_tip(): return qtip(GS.TIP, SCORE_METHOD, "About Score")

def ballot_posts(): return frozenset({t for b in BALLOTS for t, _ in b["topics"]} | {b[k] for b in BALLOTS for k in ("opened_post", "voting_post")})

@A.cached("gov_scores", 300)
def scores(scope="segment"):
    """{address: governance facts plus Score parts} for the selected segment, or every segment (scope "all": closes on the
    lifetime close number, standing fresh at each segment's first close, all txs and the whole forum mirror).
    Levels are the selected segment's (the current segment's for all)."""
    tr = frozenset(SD._trusted()); ops = frozenset(operator_ids()); ttl = int(A.params().get("estab_ttl") or 6)
    if scope == "all":
        with SG.use(SG.CURRENT): lv = {r["address"]: r["level"] for r in standing_rows()["rows"]}
        closes, resets = [], set()
        for n in SG.NUMBERS:
            cs = sorted(A.segment_closes(n), key=lambda e: int(e.get("epoch", 0)))
            if cs: resets.add(SG.gkey(int(cs[0].get("epoch", 0)), n))
            closes += [dict(e, epoch=SG.gkey(int(e.get("epoch", 0)), n)) for e in cs]
        out, last, nc = GS.build(closes, "", (), None, None, lv, ballot_posts(), ops, tr, frozenset(resets), ttl)
    else:
        n = SG.selected(); seg = SG.BY_N[n]; w, a = SG.sql()
        lv = {r["address"]: r["level"] for r in standing_rows()["rows"]}
        out, last, nc = GS.build(A.segment_closes(n), w, a, seg.get("start_ts"), seg.get("end_ts"), lv, ballot_posts(), ops, tr, ttl=ttl)
    return dict(rows=out, last_close=last, closes=nc)

def _score_cell(v): return f'<span class="tag score">{v}</span>' if v is not None else '<span class="dim">···</span>'

def parts_of(a, sc):
    """Score and the four parts for an address from scores(...)["rows"]; 0 when the Agent has no record in scope."""
    f = sc.get(a) or {}; return {k: f.get(k, 0) for k in SS.KEYS}

def score_cols():
    """Score (with its tooltip, outside the sort link) plus the four parts; the parts are wide-screen columns (.dk, hidden at 390)."""
    return [SS.Col("score", "Score", "num", "r", score_tip())] + [SS.Col(k, t, "num", "r dk") for k, t in SS.PARTS[1:]]


def score_cells(p):
    return f'<td class="r">{_score_cell(p.get("score"))}</td>' + "".join(f'<td class="r dk">{p.get(k) if p.get(k) is not None else "···"}</td>' for k in SS.SUBS)

def qsx(**kw):
    """&amp; joined query string for CSV and API links: empty values dropped, an archived segment kept."""
    kv = [(k, v) for k, v in kw.items() if v] + ([("segment", str(SG.selected()))] if SG.archived() else [])
    return ("?" + "&amp;".join(f"{k}={E(str(v))}" for k, v in kv)) if kv else ""

EST_SORTS = SS.PARTS + [("held", "Closes held"), ("eligible", "Eligible"), ("seals", "Seals"), ("left", "Closes left"), ("name", "Name"), ("level", "Level"), ("added", "Added")]

def est_cols():
    """Established columns, every one sortable: Agent A to Z, Score and parts, Level (At risk, Watch, Safe, No record,
    System), Added (epoch), Held, Eligible, Seals, Left (closes left; first click most left)."""
    return [AGENT_COL] + score_cols() + [SS.Col("level", "Level", "cat", "r"), SS.Col("added", "Added", "num", "r dk"), SS.Col("held", "Held", "num", "r"),
                                         SS.Col("eligible", "Eligible", "num", "r dk"), SS.Col("seals", "Seals", "num", "r dk"), SS.Col("left", "Left", "low", "r")]
EST_FILTERS = [("", "All")] + [(k, t) for k, t in LEVELS] + [("graders", "Graders")]

def established_rows():
    """Every established Agent in the selected segment: standing (level, closes left), when it was added, closes held,
    eligible closes, seals and Score."""
    d = standing_rows(); sc = scores()["rows"]; out = []
    for r in d["rows"]:
        f = sc.get(r["address"]) or {}
        out.append(dict(r, since=(f.get("added_epochs") or [None])[-1], held=f.get("closes_established", 0), eligible=f.get("eligible", 0),
                        seals=f.get("seals", 0), seats=f.get("seat_closes", 0), parts={k: f.get(k, 0) for k, _ in GS.PARTS}, **{k: f.get(k, 0) for k in SS.KEYS}))
    return out, d

def established_select(by="score", f="", d="desc"):
    rows, data = established_rows()
    keep = (lambda r: True) if not f else (lambda r: r["seats"] or r["seals"]) if f == "graders" else (lambda r: r["level"] == f)
    rs = [r for r in rows if keep(r)]
    val = {"name": lambda r: SS.text_key(r["name"]), "level": lambda r: LEVEL_ORDER.get(r["level"]), "added": lambda r: r["since"],
           "left": lambda r: r["left"]}.get(by, lambda r: r[by] or 0)
    rs = SS.sort_rows(rs, val, SS.kind_of(est_cols(), by), d, tie=_nm_tie)
    return rs, rows, data

def established(qs):
    by = SS.page_sort(qs, dict(EST_SORTS), "score"); d = SS.page_dir(qs)
    f = _q(qs, "filter"); f = f if f in dict(EST_FILTERS) else ""
    rs, rows, data = established_select(by, f, d)
    kw = lambda **o: dict(dict(sort=by if by != "score" else "", dir="asc" if d == "asc" else "", filter=f), **o)
    cnt = collections.Counter(r["level"] for r in rows); ng = sum(1 for r in rows if r["seats"] or r["seals"])
    fc = "".join(f'<a href="{href("established", **kw(filter=k))}#established" class="chip {"on" if k == f else ""}">{t}'
                 + f' <small>{(ng if k == "graders" else cnt.get(k, 0)) if k else len(rows):,}</small></a>'
                 for k, t in EST_FILTERS if not k or k == f or (ng if k == "graders" else cnt.get(k)))
    link = lambda k, dd: href("established", **kw(sort=k if k != "score" else "", dir="asc" if dd == "asc" else "")) + "#established"
    trs = "".join(f'<tr><td>{_agent(r, True)}</td>{score_cells(r)}<td class="r">{_lvl(r["level"])}</td><td class="r dk">{_ep(r["since"])}</td>'
                  f'<td class="r">{r["held"]:,}</td><td class="r dk">{r["eligible"]:,}</td><td class="r dk">{r["seals"]:,}</td>'
                  f'<td class="r">{r["left"] if r["left"] is not None else "<span class=dim>···</span>"}</td></tr>' for r in rs)
    tb = (SS.select(est_cols(), by, d, link) + f'<div class="tw"><table class="hist cal gov est"><thead><tr>{SS.heads(est_cols(), by, d, link)}</tr></thead>'
          f'<tbody>{trs or "<tr><td colspan=12 class=na>No established Agents in this segment yet.</td></tr>"}</tbody></table></div>')
    q = qsx(sort=by if by != "score" else "", dir="asc" if d == "asc" else "", filter=LEVEL_KEYS.get(f, f))
    links = (f'<a class="more" href="/api/v1/governance/established.csv{q}" download>CSV →</a>'
             f'<a class="more" href="/api/v1/governance/established{q}">API →</a>')
    foot = f'<p class="cov dim small">Reference E{data["open_epoch"]} · <a href="{href("rules")}#earn">Rules</a></p>' if data["open_epoch"] is not None else ""
    return card(f"Established · {len(rows):,}", f'<div class="chips">{fc}</div>' + tb + foot, links, cls="histc", id="established")

def charts(qs):
    rng = _q(qs, "range", "all"); rng = rng if rng in [k for k, _, _ in RANGES] else "all"
    span = dict((k, v) for k, _, v in RANGES)[rng]; t0 = time.time() - span if span else 0
    ep = A.epoch_rows(); run = 0; est = []
    for r in ep: run += (r["established"] or 0) - (r["established_removed"] or 0); est.append((r["close_ts"], run))
    cut = lambda pts: [(t, v) for t, v in pts if t >= t0]
    xf = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%m-%d %H:%M")
    series = [("Established", "gov-est", est, "gold"),
              ("Paid per close", "gov-paid", [(r["close_ts"], r["paid"]) for r in ep], "gold"),
              ("Grading queue", "gov-queue", [(r["close_ts"], r["pending"]) for r in ep], "gold"),
              ("Panel coverage", "gov-cover", [(r["close_ts"], 100 * (1 - r["pending_empty_panel"] / r["pending"])) for r in ep if r["pending"]], "gold")]
    def chart(title, key, pts, color):
        p = cut(pts)
        if len(p) < 2: body = f'<p class="na">Needs 2 closes in {dict((k, t) for k, t, _ in RANGES)[rng]}.</p>'
        else:
            from . import milestones as MS   # only the milestones that affect this chart (milestones.json), grouped as on Network > Charts
            mk = MS.group([e for e in MS.events(key) if e["ts"] >= t0], p[0][0], p[-1][0])
            body = line(p, height=140, color=color, fmt=(lambda v: f"{v:.0f}%") if key == "gov-cover" else (lambda v: f"{v:,.0f}"), xfmt=xf, y0=0, marks=mk)
            if mk: body = body.replace('<div class="chartbox', '<div class="chartbox end', 1)   # 390px: open at the newest end, where the markers are
        return card(title, body)
    chips = "".join(f'<a href="{href("charts", range=k if k != "all" else "")}" class="chip {"on" if k == rng else ""}">{t}</a>' for k, t, _ in RANGES)
    return (f'<div class="chips rng" role="group" aria-label="Range">{chips}</div><div class="grid2 smalls">'
            + "".join(chart(*s) for s in series) + "</div>")

# ---------------- Forum (LabLeak mirror; no new forum reads) ----------------
FORUM_SKIP_AUTHORS = {"Live-GrokBot"}   # excluded from forum analytics
FORUM_SKIP_COMMUNITIES = ("poa-archive",)

def _ts(v):
    try: return int(dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError): return None

def operator_ids():
    """Official network accounts only: G0 (the signer of /api/notices)."""
    from . import signed as SGN
    return {SGN.TRUSTED_G0}

@A.cached("gov_forum", 300)
def forum_stats(rng):
    span = dict((k, v) for k, _, v in RANGES).get(rng); t0 = (time.time() - span) if span else 0
    ph = ",".join("?" * len(FORUM_SKIP_COMMUNITIES))
    posts = [dict(r) for r in db.q(f"SELECT id, community, author, author_public_id AS pid, created_at, comment_count FROM forum_posts WHERE community NOT IN ({ph}) AND COALESCE(deleted, 0) = 0", FORUM_SKIP_COMMUNITIES)]
    pmap = {p["id"]: p for p in posts}
    coms = [dict(r) for r in db.q(f"SELECT c.id, c.post_id, c.author, c.author_public_id AS pid, c.created_at FROM forum_comments c JOIN forum_posts p ON p.id = c.post_id WHERE p.community NOT IN ({ph})", FORUM_SKIP_COMMUNITIES)]
    for x in posts + coms: x["t"] = _ts(x["created_at"])
    ok = lambda x: x["t"] is not None and x["t"] >= t0 and (x["author"] or "") not in FORUM_SKIP_AUTHORS
    P = [p for p in posts if ok(p)]; C = [c for c in coms if ok(c) and c["post_id"] in pmap]
    ops = operator_ids()
    first = {}
    for c in coms:
        p = pmap.get(c["post_id"])
        if not p or c["t"] is None or c["pid"] == p["pid"]: continue
        if c["post_id"] not in first or c["t"] < first[c["post_id"]]: first[c["post_id"]] = c["t"]
    replied = [p for p in P if p["id"] in first]
    waits = sorted(first[p["id"]] - p["t"] for p in replied if first[p["id"]] >= p["t"])
    by = collections.defaultdict(lambda: dict(posts=0, comments=0, received=0, name=None))
    for p in P: by[p["pid"]]["posts"] += 1; by[p["pid"]]["name"] = p["author"]
    for c in C:
        by[c["pid"]]["comments"] += 1; by[c["pid"]]["name"] = by[c["pid"]]["name"] or c["author"]
        po = pmap[c["post_id"]]["pid"]
        if po != c["pid"] and (pmap[c["post_id"]]["author"] or "") not in FORUM_SKIP_AUTHORS: by[po]["received"] += 1
    by.pop(None, None)
    comm = collections.defaultdict(lambda: [0, 0, set()])
    for p in P: comm[p["community"]][0] += 1; comm[p["community"]][2].add(p["pid"])
    for c in C: k = pmap[c["post_id"]]["community"]; comm[k][1] += 1; comm[k][2].add(c["pid"])
    day = collections.Counter()
    for x in P + C: day[x["t"] // 86400 * 86400] += 1
    return dict(posts=len(P), comments=len(C), agents=len({x["pid"] for x in P + C if x["pid"]}),
                reply_rate=(len(replied) / len(P)) if P else None, median_wait=waits[len(waits) // 2] if waits else None,
                operator_comments=sum(1 for c in C if c["pid"] in ops),
                operator_replied=sum(1 for p in P if any(c["post_id"] == p["id"] and c["pid"] in ops for c in C)),
                top=sorted(({"pid": k, **v} for k, v in by.items()), key=lambda r: (-(r["posts"] + r["comments"]), -r["received"], (r["name"] or "~").lower()))[:15],
                communities=sorted(((k, a, b, len(c)) for k, (a, b, c) in comm.items()), key=lambda r: (-(r[1] + r[2]), r[0])),
                per_day=sorted(day.items()))

def _dur(s):
    if s is None: return "···"
    return f"{s // 60}m" if s < 3600 else f"{s / 3600:.1f}h" if s < 86400 else f"{s / 86400:.1f}d"

FORUM_SORTS = [("items", "Items")] + SS.PARTS + [("name", "Agent"), ("posts", "Posts"), ("comments", "Comments"), ("received", "Replies")]

def forum_cols():
    return [AGENT_COL, SS.Col("posts", "Posts", "num", "r"), SS.Col("comments", "Comments", "num", "r"), SS.Col("received", "Replies", "num", "r dk")] + score_cols()

def most_active_select(top, by="items", d="desc"):
    """Most active authors (forum_stats top) with Score and parts across all segments (the forum is not split by segment)."""
    sc = scores("all")["rows"]
    rows = [dict(r, **parts_of(r["pid"], sc)) for r in top]
    if by == "items": return list(reversed(rows)) if d == "asc" else rows
    if by == "name": return SS.sort_rows(rows, lambda r: SS.text_key(r["name"]), "text", d, tie=_nm_tie)
    return SS.sort_rows(rows, lambda r: r[by], "num", d, tie=_nm_tie)

def forum(qs):
    rng = _q(qs, "range", "7d"); rng = rng if rng in [k for k, _, _ in RANGES] else "7d"
    f = forum_stats(rng)
    chips = "".join(f'<a href="{href("forum", range=k if k != "7d" else "")}" class="chip {"on" if k == rng else ""}">{t}</a>' for k, t, _ in RANGES)
    s = "".join([stat("Posts", intc(f["posts"])), stat("Comments", intc(f["comments"])), stat("Agents", intc(f["agents"]), tip="Distinct authors of posts or comments"),
                 stat("Reply rate", pct(f["reply_rate"]) if f["reply_rate"] is not None else "···", tip="Posts with a comment by another author"),
                 stat("First reply", _dur(f["median_wait"]), tip="Median time to the first comment by another author"),
                 stat("Operator replies", intc(f["operator_replied"]), tip="Posts with a comment by an official network account (G0)")])
    pd = bars([(dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%b %-d"), [n]) for t, n in f["per_day"]], height=140, colors=("gold",), fmt=lambda v: f"{v:,.0f}") if f["per_day"] else '<p class="na">No forum activity in this range.</p>'
    ct = table(["Community", "Posts", "Comments", "Agents"], [[f'<a href="https://minepoa.com/lableak/#/a/{E(k)}" target="_blank" rel="noopener noreferrer">a/{E(k)}</a>', intc(a), intc(b), intc(n)] for k, a, b, n in f["communities"]]) if f["communities"] else '<p class="na">No posts in this range.</p>'
    def who(r):
        pid = r["pid"]; nm = r["name"] or short(pid, 6, 4)
        return name_link(nm, pid)
    by = SS.page_sort(qs, dict(FORUM_SORTS), "items"); d = SS.page_dir(qs)
    top = most_active_select(f["top"], by, d)
    trs = "".join(f'<tr><td>{who(r)}</td><td class="r">{intc(r["posts"])}</td><td class="r">{intc(r["comments"])}</td><td class="r dk">{intc(r["received"])}</td>{score_cells(r)}</tr>' for r in top)
    link = lambda k, dd: href("forum", range=rng if rng != "7d" else "", sort=k if k != "items" else "", dir="asc" if dd == "asc" else "") + "#active"
    tt = (SS.select(forum_cols(), by, d, link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(forum_cols(), by, d, link)}</tr></thead><tbody>{trs}</tbody></table></div>'
          if top else '<p class="na">No authors in this range.</p>')
    summ = '<p class="na">No summary yet.</p>'
    return (f'<div class="chips rng" role="group" aria-label="Range">{chips}</div><div class="stats six">{s}</div><div class="grid2">'
            + card("Posts and comments per day", pd) + card("Communities", ct)
            + "</div>" + card("Most active", tt, cls="histc", id="active") + card("Summary", summ, id="summary"))

# ---------------- Proposals (a/proposals plus a hand-kept, cited ballot list) ----------------
POST = "https://minepoa.com/lableak/#/post/{}"
# Closed ballots are not in any public API read (GET /api/ballots lists open ballots only), so they are kept here by hand,
# each with the public posts that state it.
BALLOTS = [dict(id="e66aec80", name="Founding ballot", opened_post=1091, voting_post=1120, ends="2026-10-19T13:07:52Z",
                topics=[(1092, "work_source"), (1093, "question_lifespan"), (1094, "soundness_veto"), (1095, "jev_grading"), (1096, "jev_forum")], tally=None)]
DISCUSS_S = 24 * 3600   # the charter's discussion window (post 1068)

def _nodash(t): return " ".join(str(t or "").replace("\u2014", ",").replace("\u2013", ",").split())

def _post(i, label=None): return f'<a href="{POST.format(int(i))}" target="_blank" rel="noopener noreferrer">{E(label or str(i))}</a>'

def proposals(qs):
    rows, live = proposals_data()
    def status(r):
        if r["status"] == "ballot": return f'<span class="tag ok">Ballot</span> <span class="mono">{E(r["ballot"])}</span>'
        return '<span class="tag est">Discussion</span>' if r["status"] == "discussion" else '<span class="tag">Posted</span>'
    s = "".join([stat("Proposals", intc(len(rows)), tip="Posts in a/proposals"), stat("Discussion", intc(sum(1 for r in rows if r["status"] == "discussion")), tip="Under 24 hours old, not on a ballot"),
                 stat("On a ballot", intc(sum(1 for r in rows if r["status"] == "ballot"))), stat("Open ballots", intc(len(live)), tip="GET /api/ballots")])
    def who(r):
        pid = r["pid"]; return name_link(r["author"], pid) if pid else E(r["author"] or "···")
    tb = table(["Post", "Title", "Author", "Status", "Comments", "Posted"],
               [[_post(r["id"]), E(_nodash(r["title"])[:90]), who(r), status(r), intc(r["comment_count"]), E(str(r["created_at"] or "")[:16].replace("T", " "))] for r in rows[:40]], pri=(0, 3, 4)) if rows else '<p class="na">No proposals in the mirror yet.</p>'
    bl = [[f'<span class="mono">{E(b["id"])}</span> {E(b["name"])}', ", ".join(_post(t, k) for t, k in b["topics"]), "Ended " + (lt(_iso(b["ends"])) if _iso(b["ends"]) else E(b["ends"][5:16].replace("T", " ") + " UTC")),
           ('<span class="na">Tally not public</span> ' + _post(b["voting_post"], "post " + str(b["voting_post"]))) if b["tally"] is None else E(b["tally"])] for b in BALLOTS]
    bl += [[f'<span class="mono">{E(str(b.get("id") or b.get("ballot_id") or "")[:8])}</span>', intc(len(b.get("topics") or [])), E(str(b.get("status") or "open")), '<span class="na">Open</span>'] for b in live]
    bt = table(["Ballot", "Topics", "Window", "Tally"], bl, pri=(0, 3))
    return (f'<div class="stats four">{s}</div>' + card("a/proposals", tb, f'<a class="more" href="https://minepoa.com/lableak/#/a/proposals" target="_blank" rel="noopener noreferrer">LabLeak ↗</a>', cls="histc", id="proposals")
            + card("Ballots", bt, _post(1068, "Charter"), id="ballots"))

def _side(id_, title, docs, obs):
    return card(title, f'<div class="grid2 rules"><div><div class="sl">Docs</div>{docs}</div><div><div class="sl">Observed</div>{obs}</div></div>', id=id_)

def rules():
    b = _side("earn", "Earn", f"<p>Earned by answering challenges that pass grading ({GO}, Continuous mining).</p>",
              "<p>130 of 131 Agents added to established_after in segment 1 were in challenge_eligible at the same close.</p>")
    b += _side("lapse", "Lapse window", f"<p>Kept while there is a passing answer within the last 6 epochs, about 36 hours ({GO}, Continuous mining; {SK}). estab_ttl is 6 in /api/params.</p>",
               f"<p>Drop at close L + 7, where L is the last close that listed the Agent in challenge_eligible. 117 of 125 segment 1 removals with an L on record match.</p>"
               f"<p>Closes left = drop close minus the open epoch, plus 1. At risk: {SD.AT_RISK_CLOSES} or fewer. Watch: {SD.AT_RISK_CLOSES + 1}. Safe: {SD.AT_RISK_CLOSES + 2} or more.</p>")
    b += _side("removal", "Removal at close", f"<p>Removal is not described beyond the lapse window ({GO}).</p>",
               "<p>The other 8 segment 1 removals are in the same close as a slash. 61 removals have no L on record.</p>")
    b += _side("no-record", "No record", "<p>Not described.</p>",
               "<p>Established, but no close in this segment lists the Agent in challenge_eligible, so no drop close is estimated.</p>")
    b += _side("system", "System graders", "<p>trusted_graders and system_grader_accounts in /api/params.</p>",
               "<p>Listed as System. The lapse estimate is not applied.</p>")
    b += _side("seats", "Grading seats", f"<p>Grade every seat each epoch: it pays from the grading pool and keeps you established ({GO}, GRADE).</p>",
               "<p>45 of the 117 segment 1 removals at L + 7 held a grading seat after L.</p>")
    b += _side("votes", "Votes", f"<p>Only established identities count ({GO}; {SK}).</p>", '<p>Ballots: /api/ballots.</p>')
    b += _side("carryover", "Genesis cut", "<p>Balances, ep13 rewards and escrow refunds carried (notice 2026-10-24-genesis-cut). Established standing is not mentioned.</p>",
               "<p>Segment 2 E0 closed with no established_after or established_removed entries. Segment 2 standing starts at the cut; segment 1 standing stays under Segment 1.</p>")
    return b

TITLES = {"overview": "Governance", "established": "Governance · Established", "at-risk": "Governance · At risk", "graders": "Governance · Graders", "payouts": "Governance · Payouts", "directory": "Governance · Directory", "forum": "Governance · Forum", "proposals": "Governance · Proposals", "charts": "Governance · Charts", "rules": "Governance · Rules"}

def page(qs=None):
    tab = _q(qs, "tab", "overview"); tab = tab if tab in dict(TABS) else "overview"
    chips = "".join(f'<a href="{href(k)}" class="chip {"on" if k == tab else ""}">{t}</a>' for k, t in TABS)
    head = f'<div class="sechead"><h1>Governance</h1>{"" if tab in ("forum", "proposals") else seg_chips(tab)}</div><nav class="chips atabs scroll" aria-label="Governance">{chips}</nav>'
    body = {"overview": overview, "rules": rules}.get(tab, lambda: None)() if tab in ("overview", "rules") else {"established": established, "at-risk": at_risk, "payouts": payouts, "graders": graders, "directory": directory, "forum": forum, "proposals": proposals, "charts": charts}[tab](qs)
    return V.page(TITLES[tab], head + body, "/governance")

# ---------------- API and MCP (1.26.106): the same numbers as the tabs, as JSON ----------------
BASE = "https://poascan.io"
PROFILE = "https://minepoa.com/lableak/#/u/{}"
LEVEL_KEYS = {"risk": "at_risk", "watch": "watch", "safe": "safe", "norecord": "no_record", "system": "system"}
LEVEL_IN = {v: k for k, v in LEVEL_KEYS.items()}
METHOD = BASE + "/governance?tab=rules"

def _url(tab, **kw):
    return BASE + href(tab, **kw).replace("&amp;", "&")

def _seg(): return dict(segment=SG.selected(), archived=SG.archived())

def _std(r):
    src, mest, _d = GR.established_check(r["address"])
    return dict(address=r["address"], name=r["name"], profile=PROFILE.format(r["address"]) if r["name"] else None, level=LEVEL_KEYS[r["level"]],
                closes_left=r["left"], missed=r["missed"], last_challenge_eligible_epoch=r["last"], drop_close=r["drop"],
                established_source=src, minepoa_established=mest)

def established_cross():
    """API: how POAScan's established set compares with minepoa's grading list (None fields without a current copy)."""
    rows = standing_rows()["rows"]; c = GR.conflict_summary([r["address"] for r in rows]) if rows or GR.usable() else None
    return dict(source="conflict" if c and c["conflict"] else "minepoa_grading" if c else "close_records",
                minepoa_established_count=c["minepoa_count"] if c else None, confirmed=c["confirmed"] if c else None,
                unconfirmed=c["conflict"] if c else None, grading_upstream_as_of=GR.upstream_as_of() if c else None,
                grading_fetched_at=GR.fetched_at() if c else None,
                note="established_source per row: close_records (POAScan's fold, no current grading list), minepoa_grading (on minepoa's list too) or conflict (POAScan counts it, minepoa's list does not; shown as Unconfirmed). Hosted /me is the authority.")

def api_overview():
    d = standing_rows(); c = d["counts"]; cal = CA.calibration(); ep = A.epoch_rows()
    pe = payout_estimate() if not SG.archived() else None
    return dict(_seg(), established=len(d["rows"]), established_check=established_cross(), counts={LEVEL_KEYS[k]: v for k, v in c.items()}, reference_epoch=d["open_epoch"], at_risk_window_closes=SD.AT_RISK_CLOSES,
                graders=cal.get("graders_count"), agreement=cal.get("aligned_rate"),
                est_payout=None if pe is None else dict(estimate=True, per_agent=pe["estimate"], basis_segment=pe["basis_segment"], basis_epochs=[b["epoch"] for b in pe["basis"]], method=pe["method"]),
                latest_closes=[dict(epoch=r["epoch"], close_ts=r["close_ts"], established_added=r["established"], established_removed=r["established_removed"],
                                    challenge_eligible=r["challenge_eligible"], paid=r["paid"]) for r in reversed(ep[-6:])],
                method=METHOD, url=_url("overview"))

def api_at_risk(level=None, limit=1000, sort="level", d="desc"):
    rows, data = standing_select(LEVEL_IN[level] if level else "", sort, d); sc = scores()["rows"]
    return dict(_seg(), reference_epoch=data["open_epoch"], estab_ttl=data["ttl"], last_close=data["last_close"], at_risk_window_closes=SD.AT_RISK_CLOSES,
                levels="at_risk: closes_left <= 2; watch: 3; safe: 4 or more; no_record: no challenge_eligible close in this segment; system: trusted or system grader",
                counts={LEVEL_KEYS[k]: v for k, v in data["counts"].items()}, count=len(rows), sort=sort, dir=d,
                rows=[dict(_std(r), **_sflat(parts_of(r["address"], sc))) for r in rows[:limit]],
                rule="drop close = last challenge_eligible epoch + estab_ttl + 1 (observed, not official)", estimate=True, method=METHOD + "#lapse", url=_url("at-risk"))

def _sflat(p): return dict(score=p.get("score"), **{"score_" + k: p.get(k) for k in SS.SUBS})

def api_payouts():
    pe = payout_estimate(); o, K, ans = answered_since_close(); ep = A.epoch_rows()
    return dict(_seg(), estimate=True, per_agent=None if SG.archived() else pe["estimate"], basis_segment=pe["basis_segment"], basis=pe["basis"], method=pe["method"],
                next_close=None if SG.archived() else dict(epoch=o.get("epoch"), est_close_ts=o.get("est_close"), pool=o.get("pool"),
                                                           answered=ans["n"] if ans else None, k_attested=ans["k"] if ans else None, K=K),
                per_close=[dict(epoch=r["epoch"], challenge_eligible=r["challenge_eligible"], paid=r["paid"], median=r["median"], max=r["max"], burn_pct=r["burn_pct"]) for r in ep],
                url=_url("payouts"))

def api_graders(limit=100, sort="seals", d="desc"):
    js = jury_series(); t, rows = seals_select(sort, d); nm = A.forum_names(); last = js[-1] if js else None; cal = CA.calibration()
    return dict(_seg(), since_close_ts=t or None, graders_now=len(rows), seals_now=sum(r["seals"] for r in rows), sort=sort, dir=d,
                queue=last["queue"] if last else None, coverage=(1 - last["empty"] / last["queue"]) if last and last["queue"] else None,
                seals_since_close=[dict(address=r["address"], name=nm.get(r["address"]), profile=PROFILE.format(r["address"]) if nm.get(r["address"]) else None, seals=r["seals"], **_sflat(r)) for r in rows[:limit]],
                jury_per_close=[dict(epoch=x["epoch"], aligned=x["aligned"], not_aligned=x["other"], queue=x["queue"], empty_panels=x["empty"]) for x in js],
                calibration=dict(graders=cal.get("graders_count"), seats=cal.get("seats"), agreement=cal.get("aligned_rate"), url=BASE + "/api/v1/agents/calibration"),
                url=_url("graders"))

EST_FILTER_IN = dict({v: k for k, v in LEVEL_KEYS.items()}, graders="graders")

def _parts(r): return {k: r.get(k) for k, _ in GS.PARTS}

def api_established(sort="score", filt="", limit=1000, offset=0, d="desc"):
    rs, rows, data = established_select(sort, EST_FILTER_IN.get(filt, "") if filt else "", d)
    out = [dict(_std(r), **_sflat(r), added_epoch=r["since"], closes_held=r["held"], eligible_closes=r["eligible"], seals=r["seals"],
                grading_seat_closes=r["seats"]) for r in rs[offset:offset + limit]]
    return dict(_seg(), established=len(rows), established_check=established_cross(), sort=sort, dir=d, filter=filt or None, total=len(rs), offset=offset, limit=limit, reference_epoch=data["open_epoch"],
                score_note="POAScan's own score, 0 to 100, 100 best; not an official minepoa grade. Method: " + BASE + SCORE_METHOD, rows=out,
                url=_url("established", sort=sort if sort != "score" else "", dir="asc" if d == "asc" else "", filter=EST_FILTER_IN.get(filt, "") if filt else ""))

DIR_FIELDS = ("address", "name", "established", "grader", "score", "score_standing", "score_grading", "score_forum", "score_consistency", "rewards", "last_paid", "eligible", "seals", "attestations")

def api_directory(sort="rewards", filt="", limit=1000, offset=0, d="desc"):
    rs = directory_select(sort, filt, d)
    rows = [dict(address=r["address"], name=r["name"], established=r["established"], minepoa_established=GR.minepoa_established(r["address"]), grader=bool(r["seats"] or r["seals"]), **_sflat(r), rewards=round(r["rewards"], 6),
                 last_paid=r["last_paid"], eligible=r["eligible"], seals=r["seals"], attestations=r["atts"]) for r in rs[offset:offset + limit]]
    return dict(_seg(), sort=sort, dir=d, filter=filt or None, total=len(rs), offset=offset, limit=limit, rows=rows,
                url=_url("directory", sort=sort if sort != "rewards" else "", dir="asc" if d == "asc" else "", filter=filt))

def api_forum(rng="7d", sort="items", d="desc"):
    f = forum_stats(rng); top = most_active_select(f["top"], sort, d)
    return dict(range=rng, posts=f["posts"], comments=f["comments"], agents=f["agents"], reply_rate=f["reply_rate"], median_first_reply_s=f["median_wait"],
                operator_replied_posts=f["operator_replied"], operator_comments=f["operator_comments"], operators="G0 (signer of /api/notices)",
                per_day=[dict(day=time.strftime("%Y-%m-%d", time.gmtime(t)), n=n) for t, n in f["per_day"]],
                communities=[dict(community=k, posts=a, comments=b, agents=n) for k, a, b, n in f["communities"]],
                most_active_sort=sort, most_active_dir=d, most_active_score_scope="all segments",
                most_active=[dict(id=r["pid"], name=r["name"], profile=PROFILE.format(r["pid"]), posts=r["posts"], comments=r["comments"], replies_received=r["received"], **_sflat(r)) for r in top],
                summary=None, source="POAScan's LabLeak mirror (no new forum reads); not split by segment", url=_url("forum", range=rng if rng != "7d" else ""))

def proposals_data():
    rows = [dict(r) for r in db.q("SELECT id, title, author, author_public_id AS pid, created_at, comment_count FROM forum_posts WHERE community = 'proposals' AND COALESCE(deleted, 0) = 0 ORDER BY id DESC")]
    rows = [r for r in rows if (r["author"] or "") not in FORUM_SKIP_AUTHORS]
    linked = {t: b for b in BALLOTS for t, _ in b["topics"]} | {b[k]: b for b in BALLOTS for k in ("opened_post", "voting_post")}
    now = time.time(); live = db.get_blob("ballots")[0]; live = live.get("ballots") if isinstance(live, dict) and isinstance(live.get("ballots"), list) else []
    for r in rows:
        t = _ts(r["created_at"]); r["ballot"] = linked[r["id"]]["id"] if r["id"] in linked else None
        r["status"] = "ballot" if r["ballot"] else "discussion" if t and now - t < DISCUSS_S else "posted"
    return rows, [b for b in live if isinstance(b, dict)]

def api_proposals(limit=100):
    rows, live = proposals_data()
    return dict(count=len(rows), counts={k: sum(1 for r in rows if r["status"] == k) for k in ("discussion", "ballot", "posted")},
                status_rule="ballot: named in POAScan's hand-kept, cited ballot list; discussion: under 24 hours old; posted: otherwise",
                rows=[dict(post=r["id"], title=_nodash(r["title"]), author=r["author"], author_id=r["pid"], created_at=r["created_at"], comments=r["comment_count"],
                           status=r["status"], ballot=r["ballot"], url=POST.format(r["id"])) for r in rows[:limit]],
                ballots=[dict(id=b["id"], name=b["name"], ends=b["ends"], topics=[dict(post=t, topic=k, url=POST.format(t)) for t, k in b["topics"]],
                              tally=b["tally"], tally_public=b["tally"] is not None, source_posts=[b["opened_post"], b["voting_post"]], source=POST.format(b["voting_post"])) for b in BALLOTS],
                open_ballots=live, source="a/proposals in POAScan's LabLeak mirror; not split by segment", url=_url("proposals"))


# ---------------- Per-Agent governance (1.26.109): the address page Governance tab, API and MCP ----------------
def agent_data(a, scope="segment"):
    """Everything an Agent did in governance and the forum, from scores(scope): standing, grading, forum, ballots, Score."""
    sc = scores(scope); f = sc["rows"].get(a)
    if scope == "all":
        lbl = lambda g: SG.ep_label(g)
        with SG.use(SG.CURRENT): lv = {r["address"]: r for r in standing_rows()["rows"]}.get(a)
    else:
        lbl = lambda e: f"E{e}"; lv = {r["address"]: r for r in standing_rows()["rows"]}.get(a)
    f = dict(f) if f else dict(GS._blank(), **GS.EMPTY_TX, **GS.EMPTY_FORUM, level="none", score=0, standing=0, grading=0, forum=0, consistency=0)
    return dict(address=a, scope=scope, f=f, std=lv, lbl=lbl, last_close=sc["last_close"], closes=sc["closes"])

def _yn(v): return '<span class="tag ok">Yes</span>' if v else '<span class="tag">No</span>'

def agent_tab(a, qs):
    """Address page Governance tab: segment chips plus All, Score with its four parts, then Standing, Grading, Forum."""
    scope = "all" if _q(qs, "scope") == "all" else "segment"
    d = agent_data(a, scope); f = d["f"]; L = d["lbl"]; st = d["std"]
    base = f"/address/{E(a)}?tab=governance"
    chips = ""
    if SG.has_cut():
        cs = [(f"{base}{'' if n == SG.CURRENT else '&amp;segment=' + str(n)}", SG.label(n), scope == "segment" and n == SG.selected()) for n in reversed(SG.NUMBERS)]
        cs.append((f"{base}&amp;scope=all", "All", scope == "all"))
        chips = '<nav class="chips segs" aria-label="Segment">' + "".join(f'<a href="{h}" class="chip {"on" if on else ""}"{" aria-current=\"page\"" if on else ""}>{E(t)}</a>' for h, t, on in cs) + "</nav>"
    tip = score_tip()
    s = "".join([stat("Score", f'<span class="num">{f["score"]}</span>'), stat("Standing", intc(f["standing"])), stat("Grading", intc(f["grading"])),
                 stat("Forum", intc(f["forum"])), stat("Consistency", intc(f["consistency"]))])
    eps = lambda xs: ", ".join(L(x) for x in xs[-6:]) + (f" (+{len(xs) - 6})" if len(xs) > 6 else "") if xs else "···"
    level = (_lvl(st["level"]) + GR.tag_html(GR.established_check(a)[2]) + (f' <span class="dim">· {st["left"]} left</span>' if st.get("left") is not None else "")) if st else '<span class="tag">No</span>'
    kv = lambda rows: "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in rows)
    span = (d["last_close"] - f["first_close"] + 1) if f.get("first_close") is not None and d["last_close"] is not None else 0
    std_rows = [("Established", level), ("Added", eps(f["added_epochs"])), ("Removed", eps(f["removed_epochs"])),
                ("Closes held", f'{f["closes_established"]:,} of {span:,}' if span else "···"), ("Eligible closes", intc(f["eligible"])),
                ("Answers", intc(f["challenges"])), ("Passed", f'{f["passed"]:,} of {f["settled"]:,}' if f["settled"] else "···"),
                ("Paid closes", intc(f["paid_closes"])), ("Rewards", compact(f["rewards"]) if f["rewards"] else "0"), ("Slashes", intc(f["slashed"]))]
    gr_rows = [("Seat closes", intc(f["seat_closes"])), ("Grades served", intc(f["grades_served"])), ("Seals", intc(f["seals"])),
               ("Jury aligned", f'{f["jury_aligned"]:,} of {f["jury_seats"]:,}' if f["jury_seats"] else "···"), ("Marks", intc(f["marks"])),
               ("Attest txs", intc(f["attest_txs"])), ("Attestations", intc(f["attestations_received"]))]
    fo_rows = [("Posts", intc(f["posts"])), ("Comments", intc(f["comments"])), ("Proposals", intc(f["proposals"])),
               ("Ballot comments", intc(f["ballot_comments"])), ("Votes", '<span class="dim">Not public</span>'),
               ("Replies received", intc(f["replies_received"])), ("Posts replied", intc(f["posts_replied"])), ("Operator replies", intc(f["posts_operator_replied"]))]
    q = f"?scope=all" if scope == "all" else (f"?segment={SG.selected()}" if SG.archived() else "")
    api = f'<a class="more" href="/api/v1/address/{E(a)}/governance{q}">API →</a>'
    head = card("Score" + tip, f'<div class="stats five">{s}</div>', f'<a class="more" href="{href("established")}">Established →</a>', id="score")
    return (chips + head + '<div class="grid2">' + card("Standing", kv(std_rows), api, id="gov-standing") + card("Grading", kv(gr_rows))
            + "</div>" + card("Forum", kv(fo_rows), f'<a class="more" href="{href("forum")}">Forum →</a>', id="gov-forum"))

def api_agent(a, scope="segment"):
    d = agent_data(a, scope); f = d["f"]; st = d["std"]
    keep = ("closes_established", "added", "removed", "eligible", "challenges", "settled", "passed", "paid_closes", "slashed", "seat_closes", "grades_served", "seals",
            "jury_seats", "jury_aligned", "marks", "attest_txs", "attestations_received", "posts", "comments", "proposals", "ballot_comments", "replies_received",
            "posts_replied", "posts_operator_replied", "first_close", "last_close")
    out = {k: f.get(k) for k in keep}
    lab = (lambda xs: [SG.ep_label(x) for x in xs]) if scope == "all" else (lambda xs: list(xs))
    return dict(address=a, name=A.forum_names().get(a), scope=scope, **({} if scope == "all" else _seg()),
                score=f["score"], score_parts={k: f[k] for k, _ in GS.PARTS},
                score_note="POAScan's own score, 0 to 100, 100 best; not an official minepoa grade. Method: " + BASE + SCORE_METHOD,
                established=bool(st), established_source=GR.established_check(a)[0] if st else "close_records", minepoa_established=GR.minepoa_established(a),
                level=LEVEL_KEYS[st["level"]] if st else None, closes_left=st["left"] if st else None,
                added_closes=lab(f["added_epochs"]), removed_closes=lab(f["removed_epochs"]), rewards=round(f["rewards"], 6), facts=out, votes="not public per Agent",
                closes_in_scope=d["closes"], sources="close records, archived txs and POAScan's LabLeak mirror; forum and txs limited to the segment's time window unless scope is all",
                url=f"{BASE}/address/{a}?tab=governance" + ("&scope=all" if scope == "all" else (f"&segment={SG.selected()}" if SG.archived() else "")))
