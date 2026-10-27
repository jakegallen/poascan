"""Views over minepoa's grading list (1.26.137): the settle queue, the Overview and queue stats, exact grader counts and
the per-Agent pending answers, seals and jury reasons. Reads grading.py's stored copy only; no upstream call."""
import time
from . import grading as GR, scoresort as SS, segments as SG
from .ui import qtip, E, card, stat, intc, pct, short, name_link, lt, rel, dur, flag, agent

def _ago(s):
    s = max(0, int(s)); return f"{s // 60}m" if s < 3600 else f"{s // 3600}h {s % 3600 // 60}m"

def stale_flag():
    """Stale tag when the copy is older than grading.STALE_S (hover: when it was read)."""
    t = GR.checked_at(); why = GR.stale_reason() if t else None
    if why == "check": return flag("Stale", f"Grading list checked {_ago(time.time() - t)} ago")
    if why == "upstream": return flag("Stale", f"minepoa's grading list is from {_ago(time.time() - int(GR.upstream_as_of()))} ago; checked {_ago(time.time() - t)} ago")
    return ""

def countdown(ts):
    """A ticking countdown to ts (app.js .cd[data-close])."""
    if not ts: return "···"
    left = int(ts - time.time())
    return f'<span class="cd num" data-close="{int(ts)}">{dur(max(0, left))}</span>'

def stats_row():
    """At quorum, Pending, Trusted share, Next close: four stat cards, no sub-lines; empty without a usable copy."""
    s = GR.summary() if GR.usable() else None
    if not s: return ""
    f = stale_flag()
    nc = f'E{s["epoch"]} close' if s.get("epoch") is not None else "Next close"
    return ('<div class="stats four">' + "".join([
        stat("At quorum", intc(s["ready_next_close"]), tip=(f"At quorum and inside the oldest {s['settle_cap']:,} pending rows the next close evaluates"
             + (f"; {s['at_quorum_queued']:,} more at quorum wait beyond that cap" if s["at_quorum_queued"] else "")),
             flag_html=f or (flag(f"+{s['at_quorum_queued']:,} queued", f"{s['at_quorum_queued']:,} more answers are at quorum but outside the {s['settle_cap']:,} oldest rows a close evaluates. They carry over.", "warn") if s["at_quorum_queued"] else "")),
        stat("Pending", intc(s["pending"]), tip="Answers waiting on graders in minepoa's grading list", flag_html=f),
        stat("Trusted share", pct(s["trusted_share"]) if s.get("trusted_share") is not None else "···", tip="Share of seals on pending answers from trusted graders", flag_html=f),
        stat(nc, countdown(s["next_close_ts"]), tip="Estimate: the last close plus the median time between closes")]) + "</div>")

def qprog(r, q=4):
    """Quorum progress: q steps, gold for a trusted seal that counts, steel for an untrusted one that counts."""
    steps = ["t"] * min(q, r["counting_trusted"]) + ["u"] * max(0, min(q - r["counting_trusted"], r["counting_untrusted"]))
    steps += [""] * (q - len(steps))
    lab = f'{r["qual"]} of {q} seals count at the next close: {r["counting_trusted"]} trusted, {r["counting_untrusted"]} untrusted'
    pips = "".join(f'<i class="{c}"></i>' if c else "<i></i>" for c in steps)
    return f'<span class="qp" role="img" aria-label="{E(lab)}" title="{E(lab)}">{pips}</span><span class="num qn">{r["qual"]}/{q}</span>'

def agent_cell(a, name):
    return agent(a, name or "")   # the shared Agent cell (1.26.152)

def _ts_cell(t):
    """Date over time in the visitor's zone (app.js; the hover has both and the zone), muted ··· when blank."""
    return f'{lt(t, "d")}<small>{lt(t, "t")}</small>' if t else '<span class="dim">···</span>'

def ans_link(i): return f'<a class="mono" href="/tx/{E(i)}" title="{E(i)}">{E(short(i, 6, 4))}</a>'

PANEL_TIP = "Panel size at the last close, from its close record. Blank when the answer was not pending then."
QUEUE_COLS = [SS.Col(None, "Answer", "text"), SS.Col("name", "Agent", "text", "dk"), SS.Col("qual", "Quorum", "num"),
              SS.Col("trusted", "Trusted", "num", "r dk"), SS.Col("untrusted", "Untrusted", "num", "r dk"), SS.Col("need", "Need", "low", "r"),
              SS.Col("panel", "Panel", "num", "r", qtip(PANEL_TIP, "/about#gov-v2", "About Panel")), SS.Col("age", "Age", "num", "r dk"), SS.Col("born", "Born", "low", "r dk"), SS.Col("expires", "Expires", "low", "r"), SS.Col("last", "Last seal", "num", "r dk"),
              SS.Col("sealed", "Sealed", "num", "r"), SS.Col("graded", "Graded", "num", "r")]
QUEUE_SORTS = [(c.key, c.label) for c in QUEUE_COLS if c.key]
QUEUE_FILTERS = [("", "Pending"), ("ready", "Ready"), ("queued", "At quorum, queued"), ("1", "Need 1"), ("2", "Need 2"), ("3", "Need 3"), ("4", "Need 4"), ("open", "Open epoch")]
QUEUE_PAGE = 100
_VAL = {"name": lambda r: SS.text_key(r["name"]), "qual": lambda r: r["qual"], "trusted": lambda r: r["trusted_seals"], "untrusted": lambda r: r["untrusted_seals"],
        "need": lambda r: r["need"], "panel": lambda r: r.get("panel"), "age": lambda r: r.get("age"), "born": lambda r: r["born"], "expires": lambda r: r["expires"], "last": lambda r: r["last_seal_ts"],
        "sealed": lambda r: r.get("sealed_ts"), "graded": lambda r: r.get("graded_ts")}

def queue_select(f="", by="need", d="desc"):
    from . import govv2 as GV2   # gov-v2: panel size at the last close and age in epochs, public counts only
    rows = GV2.add_panel_age(GR.queue_rows(), (GR.current() or {}).get("epoch"))
    if f == "open": rows = [r for r in rows if r["open"]]
    else: rows = [r for r in rows if not r["open"]]
    if f == "ready": rows = [r for r in rows if r["ready_next_close"]]
    elif f == "queued": rows = [r for r in rows if r["queued_at_quorum"]]
    elif f in ("1", "2", "3", "4"): rows = [r for r in rows if r["need"] == int(f)]
    kind = SS.kind_of(QUEUE_COLS, by)
    tie = lambda r: (r["need"], r["born"] if r["born"] is not None else 1 << 30, -(r["last_seal_ts"] or 0), r["id"])
    return SS.sort_rows(rows, _VAL.get(by, _VAL["need"]), kind, d, tie=tie)

def _last_close():
    from . import govv2 as GV2
    return GV2.panels()[1]

def queue_tab(qs, href, qsx):
    """Governance, Queue: every pending answer with quorum progress, trusted and untrusted seals, need and expiry."""
    q1 = lambda k, dflt="": ((qs or {}).get(k) or [dflt])[0]
    from . import horizon as HZ   # 1.26.186: expiry horizon per pending cohort, from close records (every segment)
    hz = HZ.card_html(qs, href)
    if SG.archived(): return hz + card("Settle queue", '<p class="na">The grading list is the live network\'s: shown for the current segment only.</p>')
    if not GR.usable(): return hz + card("Settle queue", '<p class="na">minepoa\'s grading list has not been read yet. It is checked every 10 minutes.</p>')
    by = SS.page_sort(qs, dict(QUEUE_SORTS), "need"); d = SS.page_dir(qs)
    f = q1("need"); f = f if f in dict(QUEUE_FILTERS) else ""
    rs = queue_select(f, by, d); allr = GR.queue_rows(); s = GR.summary(); qn = s["quorum"]
    try: pg = max(1, int(q1("page", "1")))
    except ValueError: pg = 1
    pages = max(1, -(-len(rs) // QUEUE_PAGE)); pg = min(pg, pages); cur = rs[(pg - 1) * QUEUE_PAGE: pg * QUEUE_PAGE]
    keep = lambda **o: dict(dict(sort=by if by != "need" else "", dir="asc" if d == "asc" else "", need=f), **o)
    link = lambda k, dd: href("queue", **keep(sort=k if k != "need" else "", dir="asc" if dd == "asc" else "", page="")) + "#queue"
    pend = [r for r in allr if not r["open"]]
    cnt = {"": len(pend), "ready": sum(1 for r in pend if r["ready_next_close"]), "queued": sum(1 for r in pend if r["queued_at_quorum"]), **{str(n): sum(1 for r in pend if r["need"] == n) for n in (1, 2, 3, 4)}, "open": len(allr) - len(pend)}
    chips = "".join(f'<a href="{href("queue", **keep(need=k, page=""))}#queue" class="chip {"on" if k == f else ""}">{t} <small>{cnt[k]:,}</small></a>'
                    for k, t in QUEUE_FILTERS if cnt[k] or k == f)
    def need_cell(r): return (READY if r["ready_next_close"] else QUEUED) if r["need"] == 0 else f'<span class="num">{r["need"]}</span>'
    def exp_cell(r):
        if r["expires"] is None: return '<span class="dim">···</span>'
        return f'E{r["expires"]}' + (f' <small class="dim">in {r["expires_in"]}</small>' if r["expires_in"] is not None else "")
    trs = "".join(f'<tr{" class=rdy" if r["ready_next_close"] else ""}><td>{ans_link(r["id"])}</td><td class="dk">{agent_cell(r["author"], r["name"]) if r["author"] else "···"}</td>'
                  f'<td class="qpc">{qprog(r, qn)}</td><td class="r dk">{r["trusted_seals"]:,}</td><td class="r dk">{r["untrusted_seals"]:,}</td><td class="r">{need_cell(r)}</td>'
                  f'<td class="r">{r["panel"] if r.get("panel") is not None else "<span class=dim>···</span>"}</td><td class="r dk">{str(r["age"]) if r.get("age") is not None else "<span class=dim>···</span>"}</td>'
                  f'<td class="r dk">{"E" + str(r["born"]) if r["born"] is not None else "···"}</td><td class="r">{exp_cell(r)}</td>'
                  f'<td class="r dk">{rel(r["last_seal_ts"]) if r["last_seal_ts"] else "<span class=dim>···</span>"}</td>'
                  f'<td class="r">{_ts_cell(r.get("sealed_ts"))}</td><td class="r">{_ts_cell(r.get("graded_ts"))}</td></tr>' for r in cur)
    tb = (SS.select(QUEUE_COLS, by, d, link) + f'<div class="tw"><table class="hist cal gov queue"><thead><tr>{SS.heads(QUEUE_COLS, by, d, link)}</tr></thead>'
          f'<tbody>{trs or "<tr><td colspan=13 class=na>No answers in this view.</td></tr>"}</tbody></table></div>')
    nav = ""
    if pages > 1:
        nav = ('<div class="chips">' + (f'<a class="chip" href="{href("queue", **keep(page=str(pg - 1) if pg > 2 else ""))}#queue">Previous</a>' if pg > 1 else "")
               + f'<span class="dim small">Page {pg} of {pages}</span>' + (f'<a class="chip" href="{href("queue", **keep(page=str(pg + 1)))}#queue">More</a>' if pg < pages else "") + "</div>")
    ct = s["next_close_ts"]; cl = _last_close()
    foot = (f'<p class="cov dim small">E{s["epoch"]} closes about {lt(ct, "t")}, in {countdown(ct)}, an estimate · '
            f'It evaluates the oldest {s["settle_cap"]:,} pending rows: {s["ready_next_close"]:,} at quorum there' + (f', {s["at_quorum_queued"]:,} more at quorum carry over' if s["at_quorum_queued"] else "") + ' · '
            f'Checked {lt(s["checked_at"] or s["fetched_at"], "t")}, minepoa as of {lt(s["upstream_as_of"], "t")} · '
            f'Sealed and Graded: first and latest seal in the {"E" + str(cl) + " " if cl is not None else ""}close record · <a href="/about#grading-list">Method</a></p>') if ct else ""
    q = qsx(sort=by if by != "need" else "", dir="asc" if d == "asc" else "", need=f)
    links = (f'<a class="more" href="/api/v1/governance/queue.csv{q}" download>CSV →</a><a class="more" href="/api/v1/governance/queue{q}">API →</a>')
    return stats_row() + hz + card(f"Settle queue · {len(rs):,}", f'<div class="chips">{chips}</div>' + tb + nav + foot, links, cls="histc", id="queue")

# ---------------------------------------------------------------- Graders: exact counts from the list
GR_COLS = [SS.Col(None, "Agent", "text"), SS.Col("seals", "Seals", "num", "r"), SS.Col("counting", "Count", "num", "r"),
           SS.Col("rate", "Rate", "num", "r dk"), SS.Col("pending", "On queue", "num", "r dk"), SS.Col("avg", "Jury avg", "num", "r dk")]

def grader_badge(r): return ' <span class="tag est">trusted</span>' if r.get("trusted") else ""

# ---------------------------------------------------------------- per-Agent
READY = '<span class="tag ok">Ready</span>'
QUEUED = '<span class="tag warn" title="At quorum, but outside the oldest rows the next close evaluates (params.settle_cap_per_close). It carries over.">Queued</span>'
def _res(passed): return '<span class="tag ok">Passed</span>' if passed else '<span class="tag bad">Failed</span>'
def _yesno(v, yes="Counts", no="Does not count"):
    """The server's q flag as published, never recomputed."""
    return (f'<span class="tag ok" title="Counts at the next close (minepoa\'s q flag)">{yes}</span>' if v
            else f'<span class="tag" title="Does not count at the next close (minepoa\'s q flag)">{no}</span>')
def _need(r): return (READY if r.get("ready_next_close") else QUEUED) if r["need"] == 0 else str(r["need"])
def _txl(t): return f'<a class="mono" href="/tx/{E(t)}">Seal tx</a>' if t else '<span class="dim">Not archived</span>'
def _vote(al): return "Aligned" if al else '<span class="dim">Not aligned</span>'
def _na_al(al): return "" if al else ' <span class="dim">(not aligned)</span>'


def agent_cards(a):
    """Address Governance tab: pending answers, seals on pending answers (seal tx linked) and settled jury seats with reasons."""
    v = GR.agent_view(a)
    if not v: return ""
    f = stale_flag(); qn = v["quorum"]; out = []
    asof = f'<p class="cov dim small">minepoa\'s grading list, read {lt(v["fetched_at"], "t")} · pending seals carry no verdict · <a href="/about#grading-list">Method</a></p>'
    if v["pending"]:
        trs = "".join(f'<tr><td>{ans_link(r["id"])}</td><td class="qpc">{qprog(r, qn)}</td><td class="r dk">{r["trusted_seals"]}</td><td class="r dk">{r["untrusted_seals"]}</td>'
                      f'<td class="r">{_need(r)}</td><td class="r dk">E{r["born"]}</td><td class="r">E{r["expires"]}</td></tr>' for r in v["pending"])
        out.append(card(f"Pending answers · {v['pending_count']:,}" + f, '<div class="tw"><table class="hist cal gov queue"><thead><tr><th>Answer</th><th>Quorum</th><th class="r dk">Trusted</th><th class="r dk">Untrusted</th>'
                        f'<th class="r">Need</th><th class="r dk">Born</th><th class="r">Expires</th></tr></thead><tbody>{trs}</tbody></table></div>' + asof,
                        f'<a class="more" href="/governance?tab=queue">Queue →</a>', id="gov-pending"))
    if v["seals"]:
        trs = "".join(f'<tr><td>{ans_link(s["answer"])}</td><td class="dk">{agent_cell(s["author"], s["author_name"]) if s["author"] else "···"}</td>'
                      f'<td class="r">{lt(s["ts"], "dt")}</td><td class="r">{_yesno(s["counting"])}</td>'
                      f'<td class="r">{_txl(s["tx"])}</td></tr>' for s in v["seals"])
        more = f' <span class="dim small">· newest {len(v["seals"])}</span>' if v["seals_count"] > len(v["seals"]) else ""
        out.append(card(f"Seals on pending answers · {v['seals_count']:,}" + more + f,
                        '<div class="tw"><table class="hist cal gov"><thead><tr><th>Answer</th><th class="dk">Agent</th><th class="r">Sealed</th><th class="r">Quorum</th><th class="r">Tx</th></tr></thead>'
                        f'<tbody>{trs}</tbody></table></div>' + f'<p class="cov dim small">{v["seals_counting"]:,} of {v["seals_count"]:,} count toward quorum. The seal tx is matched by grader and time.</p>', id="gov-seals"))
    if v["jury_seats"] or v["settled"]:
        rows = ""
        for s in v["jury_seats"]:
            rows += (f'<tr><td>{ans_link(s["answer"])}</td><td class="r dk">E{s["close"]}</td><td class="r">{_res(s["passed"])}</td>'
                     f'<td class="r dk">{_vote(s["aligned"])}</td><td class="r num">{s["score"] if s["score"] is not None else "···"}</td>'
                     f'<td class="why dk">{E(s["reason"] or "")}</td></tr>'
                     f'<tr class="whym"><td colspan="6" class="why">{E(s["reason"] or "")}{_na_al(s["aligned"])}</td></tr>')   # phones: the reason under its row
        seats = ('<div class="tw"><table class="hist cal gov why"><thead><tr><th>Answer</th><th class="r dk">Close</th><th class="r">Result</th><th class="r dk">Vote</th><th class="r">Score</th><th class="dk">Reason</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table></div>') if rows else ""
        own = ""
        for s in v["settled"]:
            js = "".join(f'<li><span class="num">{j["score"] if j["score"] is not None else "···"}</span> {agent_cell(j["grader"], j["name"])}'
                         f'{_na_al(j["aligned"])}: {E(j["reason"] or "")}</li>' for j in s["jury"])
            own += (f'<div class="kv"><span>{ans_link(s["answer"])} <small class="dim">E{s["close"]}</small></span><div>'
                    f'{_res(s["passed"])}<ul class="jury">{js}</ul></div></div>')
        body = (("<h3 class=\"sub\">As juror</h3>" + seats) if seats else "") + (("<h3 class=\"sub\">Own answers</h3>" + own) if own else "")
        out.append(card("Jury reasons", body + '<p class="cov dim small">Scores 0 to 3 and reasons from settled juries in minepoa\'s grading list.</p>', id="gov-jury"))
    return "".join(out)
