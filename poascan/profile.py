"""Phase 3: the Agent page as a maker's mark profile. The header carries the Agent's rosette (marks.py), the name in the display serif
linking to its LabLeak profile, the address with copy, and census tags. The Overview opens with the Score (a dial and its four
parts, with jury and standing facts), rewards per epoch, and an hour by day activity map (UTC from the server, the visitor's zone once app.js runs). All from
POAScan's archive: Score and facts from governance.scores (cached 300 s), rewards from the close records, activity from the txs table (one indexed read per page)."""
import time
from . import db, marks as MK
from .ui import E, card, copy, name_link, intc, short, bars

LEVEL = {"safe": ("Safe", "ok"), "watch": ("Watch", "warn"), "atrisk": ("At risk", "bad"), "system": ("System", ""), "norecord": None}

def tags(est, level, cen):
    t = ['<span class="tag ok">Established</span>' if est else ""]
    lv = LEVEL.get(level or "norecord")
    if lv: t.append(f'<span class="tag {lv[1]}">{lv[0]}</span>')
    if cen:
        t.append(f'<span class="tag">{E(cen.get("eco") or "")}</span>' if cen.get("eco") else "")
        t.append(f'<span class="tag">{E(cen.get("detail") or "")}</span>' if cen.get("detail") else "")
        t += [f'<span class="tag">{E(h)}</span>' for h in (cen.get("harness") or [])[:3]]
    t = [x for x in t if x]
    return f'<div class="ptags">{"".join(t)}</div>' if t else ""

def head(a, name, meta, tagrow, usd=""):
    """The profile header card. Name links to LabLeak (name_link); no name: the address is the title."""
    nm = (f'<h1 class="pname">{name_link(name, a, cls="")}</h1><div class="amono"><span class="mono">{E(a)}</span>{copy(a)}</div>' if name
          else f'<h1 class="pname mono pa">{E(short(a, 10, 8))}</h1><div class="amono"><span class="mono">{E(a)}</span>{copy(a)}</div>')
    return (f'<section class="card prof addrhead">{MK.mark_img(a, 104, "mmark pm")}<div class="ahid"><span class="lbl">Agent</span>{nm}{meta}{tagrow}</div>'
            f'<div class="px">{usd}</div></section>')

def dial(score):
    s = max(0, min(100, int(score or 0)))
    return (f'<div class="dial" role="img" aria-label="Score {s} of 100"><svg viewBox="0 0 120 120" aria-hidden="true">'
            f'<circle class="dt" cx="60" cy="60" r="52" pathLength="100"/><circle class="dv" cx="60" cy="60" r="52" pathLength="100" stroke-dasharray="{s} 100"/></svg>'
            f'<b class="fig">{s}</b><span>of 100</span></div>')

def score_card(row, tip=""):
    """Score dial, the four parts as bars, then six facts. row: governance.scores()["rows"][a] or None."""
    if not row: return card("Score", '<p class="empty">No Score in this segment yet</p>', tip, cls="pscore")
    parts = "".join(f'<div class="ppart"><span class="lbl">{n}</span><span class="pbar2"><i style="width:{max(0, min(100, int(row.get(k) or 0)))}%"></i></span><b class="num">{int(row.get(k) or 0)}</b></div>'
                    for k, n in (("standing", "Standing"), ("grading", "Grading"), ("forum", "Forum"), ("consistency", "Consistency")))
    f = lambda lbl, v, of=None: f'<div class="pf"><span class="lbl">{lbl}</span><b class="fig">{v}{f"<small>/ {of}</small>" if of is not None else ""}</b></div>'
    facts = (f("Jury aligned", intc(row.get("jury_aligned")), intc(row.get("jury_seats"))) + f("Attests in", intc(row.get("attestations_received")))
             + f("Closes held", intc(row.get("closes_established"))) + f("Passed", intc(row.get("passed")), intc(row.get("settled")))
             + f("Paid closes", intc(row.get("paid_closes"))) + f("Seals", intc(row.get("seals"))))
    return card("Score", f'<div class="psc">{dial(row.get("score"))}<div class="pparts">{parts}</div></div><div class="pfacts">{facts}</div>', tip, cls="pscore")

def activity(a, days=7, now=None):
    """Txs sent by hour over the last 7 days: day rows, 24 hour columns, five quiet steps of gold. The server draws UTC days and
    hours (the no-JS view, labelled UTC). data-q carries the counts in 15 minute UTC slots from one day before the first row, so
    app.js (pheat) can rebuild the grid in the visitor's zone, half and quarter hour offsets included, and relabel it."""
    now = int(time.time() if now is None else now); d0 = now // 86400 * 86400 - (days - 1) * 86400; q0 = d0 - 86400
    rows = db.q("SELECT CAST((ts - ?) / 900 AS INTEGER) AS q, COUNT(*) AS n FROM txs WHERE from_addr=? AND ts>=? AND ts<=? GROUP BY q",
                (q0, a, q0, now))
    qs = {int(r["q"]): int(r["n"]) for r in rows}
    g = {}
    for q, n in qs.items():
        t = q0 + q * 900
        if t >= d0: g[((t - d0) // 86400, t % 86400 // 3600)] = g.get(((t - d0) // 86400, t % 86400 // 3600), 0) + n
    if not g: return '<p class="empty">No txs in the last 7 days</p>'
    out = []; mx = max(g.values())
    for d in range(days):
        day = time.strftime("%b %-d", time.gmtime(d0 + d * 86400))
        cells = "".join(f'<i class="l{step(g.get((d, h), 0), mx)}" title="{day}, {h:02d}:00 UTC: {txs(g.get((d, h), 0))}"></i>' for h in range(24))
        out.append(f'<div class="phr"><span>{day}</span>{cells}</div>')
    ax = '<div class="phax"><span></span><span>00</span><span>06</span><span>12</span><span>18</span></div>'
    dq = " ".join(f"{q}:{n}" for q, n in sorted(qs.items()))
    return (f'<div class="pheat" role="img" aria-label="Txs by hour, last 7 days, UTC" data-q0="{q0}" data-days="{days}" data-q="{dq}">'
            f'{"".join(out)}{ax}</div>')

def step(n, mx):
    """A cell's shade, 0 (none) to 4 (the busiest hour). app.js pheat uses the same steps."""
    return 0 if not n else (1 + min(3, int(4 * (n - 1) / mx)) if mx > 1 else 4)

def txs(n):
    return f'{n} tx{"" if n == 1 else "s"}'

def overview(a, row, rew_items, tip=""):
    """The Overview's signature row: Score beside rewards per epoch and the activity map."""
    rb = bars(rew_items, colors=("gold",)) if rew_items else '<p class="empty">No rewards yet</p>'
    side = card("Rewards", rb, '<span class="lbl">Per epoch</span>', cls="prew") + card("Activity", activity(a), '<span class="lbl">Txs by hour · <span class="phz">UTC</span></span>', cls="pact")
    return f'<div class="grid2 pgrid">{score_card(row, tip)}<div class="side">{side}</div></div>'
