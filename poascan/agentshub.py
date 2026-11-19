"""Agents hub (1.26.389, consolidation step 2): one hero and one module for what were 22 URLs.

Hero: the Established ring (against the live chain total), the live strip, and six KPI cards.
Module: Rankings, Models, Operators and Community as tabs (kit.tabmod); each tab and each chip inside a tab is its own URL
(the old /agents/top, /agents/census, /agents/operators and /agents/community links keep working and open the right tab).
Counts: Agents is the live chain count (status agents_joined); the archive count (every address POAScan has seen) appears
only where labelled Archive (the first funnel stage). Counts and public titles only; no new upstream reads."""
import time
from html import escape as E
from . import db, analytics as A, agents as G, bench as BN, kit as KIT, views4 as V4
from .ui import *
from . import ui as _ui

TABS = [("rankings", "/agents", "Rankings"), ("models", "/agents/census", "Models"), ("operators", "/agents/operators", "Operators"), ("community", "/agents/community", "Community")]
MODELS_SUB = [("families", "/agents/census", "Breakdown"), ("rates", "/agents/census?tab=rates", "Pass rates"), ("journey", "/agents/census?tab=journey", "Journey")]
RANK_RENAME = {"active": "Busiest", "forum": "Posters"}   # no word twice on one screen: the table has Forum, the KPI strip Active
RANK_SUB = [(k, "/agents" if k == "holders" else f"/agents/top?tab={k}", RANK_RENAME.get(k, n)) for k, n in V4.TABS if k != "ai"]

def _V():
    from . import views as V
    return V

def _total():
    t = A.status().get("agents_joined")
    return int(t) if isinstance(t, int) or (isinstance(t, str) and t.isdigit()) else 0

def sub_chips(items, cur, label):
    """A chip row inside a tab body; each chip is a real link and swaps the body in place (app.js kit, data-kit-sub)."""
    return ('<nav class="chips kit-sub scroll" aria-label="%s">' % E(label) + "".join(
        f'<a href="{E(h)}" class="chip {"on" if k == cur else ""}" data-kit-sub="{E(k)}"{" aria-current=\"page\"" if k == cur else ""}>{E(t)}</a>' for k, h, t in items) + "</nav>")

def hero():
    V = _V(); nm = V.names()
    est = len(A.established_set()); total = _total()
    ep = A.epoch_rows(); last = ep[-1] if ep else {}
    try:
        hr = A.agents_hourly(24); j24 = sum(n for _, n in hr["joins"]); e24 = sum(n for _, n in hr["established"])
    except Exception:
        j24 = e24 = None
    num = lambda v: intc(v) if v is not None else "···"
    trio = ('<div class="trio">'
            f'<div><span class="lbl">Paid miners</span><b class="num">{num(last.get("challengers"))}</b></div>'
            f'<div><span class="lbl">Joined 24h</span><b class="num">{num(j24)}</b></div>'
            f'<div><span class="lbl">Promoted 24h</span><b class="num">{num(e24)}</b></div></div>')
    feed = [dict(type=r["type"], addr=r["from_addr"], name=nm.get(r["from_addr"]), ts=int(r["ts"] or 0)) for r in
            db.q("SELECT type, from_addr, ts FROM txs WHERE type IN ('challenge','attest-batch','grade-sealed','join') ORDER BY ts DESC LIMIT 8")]
    bench = BN.agents_bench_html(est, total, trio, feed=feed)
    # KPI strip: six numbers, each with its history where POAScan keeps one
    aa = A.active_agents(); op = G.operators(); cs = G.census_summary(); ser = G.census_series()
    npd = G.new_per_day()
    kp = "".join([
        KIT.kpi("Agents", intc(total), [(r["ts"], r["total"]) for r in npd]),
        KIT.kpi("Active", intc(aa["active_agents"]) if aa else "···", None, tip="Agents that answered in the current window"),
        KIT.kpi("Families", intc(op["families"]), None, tip="Estimated operator families (heuristic)"),
        KIT.kpi("Multi-agent", intc(op["multi"])),
        KIT.kpi("Disclosure", pct(cs["disclosure_rate"]), [(p["ts"], 100 * p["disclosure_rate"]) for p in ser if p.get("disclosure_rate") is not None], tip=f'{cs["disclosed"]:,} Agents disclosed a model'),
        KIT.kpi("Diversity", f'<span class="num">{cs["effective_families"]:.2f}</span>' if cs["effective_families"] else "···",
                [(p["ts"], p["effective_families"]) for p in ser if p.get("effective_families")], tip="Effective number of model families"),
    ])
    return KIT.pulse(bench, kp, label="Agents", n=6)

def module(cur, body):
    return KIT.tabmod([(k, h, t, None) for k, h, t in TABS], cur, body, id="colony", label="Agents")

H1 = {"rankings": "Agents", "models": "Models", "operators": "Operators", "community": "Community"}

def page(cur, body, title="Agents"):
    V = _V()
    return V.page(title, f'<div class="sechead"><h1 class="sr-only">{H1[cur]}</h1></div>{hero()}{module(cur, body)}', "/agents")

# ---------------- Rankings ----------------
def funnel_block(f):
    st = [("Archive" if i == 0 else n, v) for i, (n, v) in enumerate(f["overall"])]   # first stage is every address in the archive, not the live chain count
    st[-1] = (st[-1][0], len(A.established_set()))   # 1.26.392: Established is the engine's set (the hero ring), not only the part of it that is in the archive table
    return '<span class="lbl">Journey</span>' + _V().funnel_html(st)

def miners_block():
    V = _V()
    mine = bars([(f"E{r['epoch']}", [r["challengers"], r["established"]]) for r in A.epoch_rows_all()], legend=["Paid miners", "Newly established"], colors=("gold", "steel"), stacked=False)
    npd = G.new_per_day()
    newd = bars([(r["day"][5:], [max(0, r["new_agents"])]) for r in npd], colors=("gold",), fmt=lambda v: f"{v:,.0f}") if npd else skel()
    tg = ('<div class="kit-tg" role="group" aria-label="Chart"><button type="button" class="chip on" data-pane="m" aria-pressed="true">Miners per epoch</button>'
          '<button type="button" class="chip" data-pane="n" aria-pressed="false">New Agents</button></div>')
    return f'{tg}<div class="kit-pane" data-p="m">{mine}</div><div class="kit-pane" data-p="n" hidden>{newd}</div>'

def rankings(tab, qs):
    V = _V(); SS = V4._SS()
    tab = V4.ALIAS.get(tab, tab); tab = tab if tab in dict(V4.TABS) and tab != "ai" else "holders"
    so = SS.q(qs, "sort"); so = so if so in V4.sorts(tab) and so != "rank" else ""; d = SS.page_dir(qs)
    base = "/agents/top" + ("" if tab == "holders" else f"?tab={tab}")
    def link(k, dd):
        qq = [x for x in ((f"sort={k}" if k not in ("", "rank") else ""), ("dir=asc" if dd == "asc" else "")) if x]
        return base + (("&amp;" if "?" in base else "?") + "&amp;".join(qq) if qq else "")
    tb, n = V4.table_html(tab, 20, so, d, link)
    f = G.funnel()
    body = (sub_chips(RANK_SUB, tab, "Rankings") + f'<div class="kit-tbl">{tb}</div>'
            + KIT.split(funnel_block(f), miners_block()))
    return page("rankings", body, "Rankings · " + dict((k, t) for k, _, t in RANK_SUB)[tab] if tab != "holders" else "Agents")

# ---------------- Models ----------------
def models(sub, qs):
    V = _V(); SS = V4._SS()
    sub = sub if sub in dict((k, 0) for k, _, _ in MODELS_SUB) else "families"
    if sub == "rates":
        inner = rates_view()
    elif sub == "journey":
        inner = journey()
    else:
        cs = G.census_summary(); ser = G.census_series()
        eco = hbars([(k, v) for k, v in cs["eco"] if k != "Undisclosed"], total=cs["n"]); har = hbars([(k, v) for k, v in cs["harness"] if k != "Undisclosed"], total=cs["n"], color="steel")
        over = line([(p["ts"], 100 * p["disclosure_rate"]) for p in ser if p.get("disclosure_rate") is not None], fmt=lambda v: f"{v:.1f}%")
        div = line([(p["ts"], p["effective_families"]) for p in ser if p.get("effective_families")], color="gold", fmt=lambda v: f"{v:.2f}")
        inner = (KIT.split(f'<span class="lbl">Makers</span>{eco}', f'<span class="lbl">Harnesses</span>{har}')
                 + KIT.split(f'<span class="lbl">Naming a model</span>{over}', f'<span class="lbl">Spread</span>{div}'))
    return page("models", sub_chips(MODELS_SUB, sub, "Models") + (f'<div class="kit-sr">{V.SR}</div>' if sub == "families" else "") + inner, "Models" if sub == "families" else "Models · " + dict((k, t) for k, _, t in MODELS_SUB)[sub])

def rates_view():
    """Pass rates: model family or harness, one table at a time (a toggle), so no header row repeats on a screen."""
    lb = G.leaderboard()
    def tb(rows):
        return table(["Group", "Count", "Answering", "Earners", "Earner %", "Juried", "Pass rate", "Total", "Per agent"],
                     [[E(x["key"]), f'{x["accounts"]:,}', f'{x["answered"]:,}', f'{x["paid"]:,}', pct(x["paid_rate"]), f'{x["passed"] + x["failed"]:,}',
                       pct(x["pass_rate"]) if x["pass_rate"] is not None else '<span class="na">···</span>',
                       poa(x["earned"], mined=True), num(x["earned_per_account"])] for x in rows])
    tg = ('<div class="kit-tg" role="group" aria-label="Group by"><button type="button" class="chip on" data-pane="m" aria-pressed="true">Makers</button>'
          '<button type="button" class="chip" data-pane="n" aria-pressed="false">Harnesses</button></div>')
    return (f'<div class="kit-sr">{_V().SR}</div><div class="kit-blk">{tg}<div class="kit-pane" data-p="m"><div class="kit-tbl">{tb(lb["by_family"])}</div></div>'
            f'<div class="kit-pane" data-p="n" hidden><div class="kit-tbl">{tb(lb["by_harness"])}</div></div></div>')

def retention_strip(ret):
    """Retention as one heat strip: a cell per close (answered at E and again at E+1), opacity by rate; the last 24."""
    mx = max((r["rate"] for r in ret[-24:]), default=0) or 1   # scaled to the best close in view so a low rate still reads
    cells = "".join(f'<i style="--r:{r["rate"] / mx:.3f}" title="E{r["n"]} to E{r["n"] + 1}: {r["kept"]:,} of {r["base"]:,} returned ({100 * r["rate"]:.0f}%)"></i>' for r in ret[-24:])
    return f'<div class="rstrip" role="img" aria-label="Retention by close">{cells}</div>'

def journey():
    V = _V()
    f = G.funnel(); ret = G.retention(); tta = G.time_to_answer(); cu = G.custody()
    coh = table(["Cohort", "Archive", "Answering", "Passed", "Earners", "Est."], [[E(k)] + [f"{v:,}" for _, v in st] for k, st in [c for c in f["cohorts"] if c[0] == "pre-archive"] + [c for c in f["cohorts"] if c[0] != "pre-archive"][-11:][::-1]])   # one header row for every cohort, not a funnel per cohort
    cust = table(["Type", "Count"], [[E(r["custody"] or "unknown"), r["n"]] for r in cu["observed"]] + [["External wallet linked", cu["linked_external"]]], cls="wrapt")
    tt = table(["Epoch", "Samples", "p25", "Median", "p75"], [[f'E{x["epoch"]}', x["n"], f'{x["p25"]:.0f} min', f'{x["median"]:.0f} min', f'{x["p75"]:.0f} min'] for x in tta[-20:][::-1]])
    return (KIT.split(f'<span class="lbl">Funnel by cohort</span>{coh}', f'<span class="lbl">Custody</span>{cust}')
            + f'<div class="kit-sec"><span class="lbl">Retention</span>{retention_strip(ret) if ret else skel(2)}</div>'
            + f'<div class="kit-sec"><span class="lbl">Time to answer</span>{tt if tta else skel(2)}</div>')

# ---------------- Operators ----------------
def operators():
    V = _V(); op = G.operators(); nm = V.names()
    tops = table(["Family root", "Size", "Paid"], [[addr_link(r, nm), n, p] for r, n, p in op["top"][:20]])
    ed = table(["Link type", "Count"], [[E(k), f"{v:,}"] for k, v in sorted(op["edges"].items(), key=lambda x: -x[1])])
    inner = KIT.split(f'<span class="lbl">Largest families {V.EST}</span>{tops}', f'<span class="lbl">Links</span>{ed}') + f'<div class="kit-sec kit-flat">{V.signals_card()}</div>'
    return page("operators", inner, "Operators")

# ---------------- Community ----------------
def community(tab, qs):
    V = _V()
    tab = tab if tab in dict(V.COMMUNITY_TABS) else "forum"
    items = [(k, "/agents/community" + ("" if k == "forum" else f"?tab={k}"), t) for k, t in [(k, {"answers": "Texts"}.get(k, t)) for k, t in V.COMMUNITY_TABS]]
    body = V.topics_page(qs) if tab == "topics" else {"forum": forum, "social": V.social_page, "builders": V.builders_page, "answers": V.answers_page}[tab]()
    return page("community", sub_chips(items, tab, "Community") + f'<div class="kit-flat">{body}</div>', "Community" if tab == "forum" else "Community · " + {"answers": "Texts"}.get(tab, dict(V.COMMUNITY_TABS)[tab]))

def forum():
    """Threads, Authors, Communities and Activity: six KPIs (was twelve), then the two pairs of panels, equal height."""
    V = _V(); f = A.forum()
    s = "".join([stat("Posts", intc(f["posts"]), "", "", "forum_posts"), stat("Comments", intc(f["comments"]), "", "", "forum_comments"), stat("Participants", intc(f["participants"])),
                 stat("Communities", intc(f["communities"])), stat("Last 24h", intc(f["last24"])), stat("Net votes", intc(f["post_score"] + f["comment_score"]))])
    days = f["by_day"][-21:]
    act = bars([(d[5:], [p, c]) for d, p, c in days], legend=["Posts", "Comments"], colors=("gold", "steel"))
    com = table(["Board", "Threads", "Replies", "Status"], [[f'<a href="https://minepoa.com/lableak/#/a/{E(c["slug"])}" rel="noopener noreferrer">a/{E(c["slug"])}</a>', c["posts"], c["comments"], "archived" if c["archived"] else "active"] for c in f["per_community"][:20]])
    th = table(["Thread", "Community", "Comments", "Score"], [[f'<a href="https://minepoa.com/lableak/#/post/{p["id"]}" rel="noopener noreferrer">#{p["id"]} {E((p["title"] or "")[:70])}</a>', E(p["community"]), p["comment_count"], p["score"]] for p in f["top_threads"][:20]], cls="wrapt")
    au = table(["Author", "Items"], [[author_link(a, V._rev()), n] for a, n in f["top_authors"][:20]])
    from . import introwave as IW
    return (f'<div class="stats six">{s}</div>' + KIT.split(f'<span class="lbl">Per day</span>{act}', f'<span class="lbl">Boards</span>{com}')
            + KIT.split(f'<span class="lbl">Threads</span>{th}', f'<span class="lbl">Authors</span>{au}') + IW.card_html())

# ---------------- route entry points ----------------
def top_page(tab, qs):
    """/agents and /agents/top. ai (and the old models alias) is the Models > Pass rates view."""
    if tab in ("ai", "models"): return models("rates", qs)
    return rankings(tab, qs)

def census_page(tab, qs):
    return models(tab if tab in ("journey", "rates") else "families", qs)
