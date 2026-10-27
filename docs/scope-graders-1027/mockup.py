"""Static mockup for a Graders tab "Grader patterns" card (scope only, not wired into the app).
Data: preview_data.json, derived offline from POAScan's own public API (grade-history, settled seats only, Segment 2,
closes through E10). Run from the repo root: POASCAN_DB=/tmp/x.db python3 docs/scope-graders-1027/mockup.py > out.html"""
import json, os, statistics as st, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from poascan import ui, scoresort as SS
from poascan.ui import card, stat, agent, bars, qtip, intc, pct

HERE = os.path.dirname(__file__)
rows = json.load(open(os.path.join(HERE, "preview_data.json")))
cal = json.load(open(os.path.join(HERE, "calibration_trusted.json")))
SYS = set(cal)
MIN_N = 20
M = "/about#grader-patterns"
for r in rows:
    r["system"] = r["address"] in SYS
    r["low"] = (r["scored"] or 0) < MIN_N
pool = [r for r in rows if not r["system"] and not r["low"]]

def pctile(k, v):
    xs = sorted(r[k] for r in pool if r[k] is not None)
    if v is None or not xs: return None
    return round(100 * sum(1 for x in xs if x <= v) / len(xs))

med = lambda k: st.median([r[k] for r in pool if r[k] is not None])
f2 = lambda v: f"{v:.2f}" if v is not None else "···"

def band(vals, edges, lab):
    out = []
    for i, lo in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else 9
        out.append((lab(lo), [sum(1 for v in vals if lo <= v < hi)]))
    return out

ag = band([r["aligned_rate"] for r in pool], [0, .6, .7, .8, .85, .9, .95], lambda x: f"{round(x * 100)}%+" if x else "<60%")
sd = band([r["sd"] for r in pool], [0, .4, .5, .6, .7, .8], lambda x: f"{x:.1f}+" if x else "<0.4")
mix = [0, 0, 0, 0]
for r in pool:
    for i in range(4): mix[i] += r["hist"][i]

EX = '<span class="tag warn" title="Preview: computed offline from POAScan public grade-history, Segment 2, settled seats through E10. Not live.">Preview data</span>'
rng = "".join(f'<a href="#" class="chip {"on" if k == "all" else ""}">{t}</a>' for k, t in (("24h", "24h"), ("7d", "7d"), ("30d", "30d"), ("all", "All")))
seg = '<a href="#" class="chip on">Segment 2</a><a href="#" class="chip">Segment 1</a>'
filt = '<a href="#" class="chip on">n 20+</a><a href="#" class="chip">All</a>'

stats = "".join([
    stat("Graders", intc(len(pool)), tip=f"Non system graders with {MIN_N} or more scored settled seats in range"),
    stat("Agreement", pct(med("aligned_rate")), tip="Median across graders: settled jury seats that matched the final outcome"),
    stat("Spread", f2(med("sd")), tip="Median across graders: standard deviation of their 0 to 3 scores on settled answers"),
    stat("Distance", f2(med("dist")), tip="Median across graders: mean gap between a grader's score and the other jurors' mean score on the same answer"),
])
c1 = card("Agreement · graders", f'<div class="chips">{rng}</div>' + bars(ag, height=150, colors=("verd",), fmt=lambda v: f"{v:,.0f}") ,
          qtip("How many graders fall in each agreement band. Distribution only, no names. System graders and n under 20 left out.", M, "About this chart"))
c2 = card("Spread · graders", f'<div class="chips">{rng}</div>' + bars(sd, height=150, colors=("gold",), fmt=lambda v: f"{v:,.0f}"),
          qtip("How many graders fall in each score spread band (standard deviation of 0 to 3 scores). A low spread alone is not a fault: some panels see similar answers.", M, "About this chart"))
c3 = card("Score mix", bars([(str(i), [mix[i]]) for i in range(4)], height=150, colors=("ember",), fmt=lambda v: f"{v:,.0f}"),
          qtip("Settled scores 0 to 3 across the graders above. Settled answers only; pending scores are never read.", M, "About this chart"))

T = lambda t: qtip(t, M, "What this column means", "hv")
cols = [SS.Col("name", "Agent", "text", "p"), SS.Col("seats", "Seats", "num", "r p"),
        SS.Col("agree", "Agreement", "num", "r", T("Settled jury seats that matched the final outcome")),
        SS.Col("peers", "Peers", "num", "r dk", T("Agreement of the other jurors on the same answers. Agreement well above Peers means this grader matched outcomes more often than the people beside them")),
        SS.Col("spread", "Spread", "num", "r", T("Standard deviation of this grader's 0 to 3 scores on settled answers")),
        SS.Col("same", "Top score", "num", "r dk", T("Share of scored seats that got this grader's most used score")),
        SS.Col("dist", "Distance", "num", "r dk", T("Mean gap between this grader's score and the other jurors' mean score on the same answer")),
        SS.Col("mix", "Mix", None, "dk"), SS.Col("closes", "Closes", "num", "r dk")]
cols[7] = SS.Col(None, "Mix", "num", "dk")

def cell(v, txt, k):
    p = pctile(k, v)
    t = f' title="Percentile {p} of {len(pool)} graders"' if p is not None else ""
    return f'<span class="num"{t}>{txt}</span>'

def mixbar(h):
    n = sum(h) or 1; cs = ("#7a4b3a", "#b98a4a", "#c9b26a", "#6f9a6a")
    seg = "".join(f'<i style="display:inline-block;height:8px;width:{60 * x / n:.1f}px;background:{cs[i]}"></i>' for i, x in enumerate(h) if x)
    return f'<span title="0: {h[0]} · 1: {h[1]} · 2: {h[2]} · 3: {h[3]}" style="display:inline-flex;vertical-align:middle;border-radius:2px;overflow:hidden">{seg}</span>'

shown = sorted([r for r in rows if not r["low"]], key=lambda r: ((r["name"] or "~").lower(), r["address"]))
trs = ""
for r in shown:
    tail = '<span class="tag">system</span>' if r["system"] else ""
    trs += (f'<tr><td>{agent(r["address"], r["name"] or "", tail=tail)}</td><td class="r">{intc(r["seats"])}</td>'
            f'<td class="r">{cell(r["aligned_rate"], pct(r["aligned_rate"]), "aligned_rate")}</td>'
            f'<td class="r dk">{cell(r["peer_rate"], pct(r["peer_rate"]), "peer_rate")}</td>'
            f'<td class="r">{cell(r["sd"], f2(r["sd"]), "sd")}</td>'
            f'<td class="r dk">{cell(r["modal"], pct(r["modal"]), "modal")}</td>'
            f'<td class="r dk">{cell(r["dist"], f2(r["dist"]), "dist")}</td>'
            f'<td class="dk">{mixbar(r["hist"])}</td><td class="r dk">{intc(r["closes"])}</td></tr>')
link = lambda k, d: "#patterns"
tb = (SS.select(cols, "name", "desc", link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(cols, "name", "desc", link)}</tr></thead><tbody>{trs}</tbody></table></div>')
low = sum(1 for r in rows if r["low"])
foot = (f'<p class="cov dim small">Settled seats only. Agents under n {MIN_N} hidden ({low}); system graders tagged and left out of percentiles and charts. '
        f'Hover a value for its percentile. Advisory: agreement with the outcome is not accuracy. <a href="{M}">Method</a></p>')
tcard = card(f"Grader patterns · {len(shown)}", f'<div class="chips">{EX}{rng}{filt}</div>' + tb + foot,
             '<a class="more" href="#">CSV</a> <a class="more" href="#">API →</a>', cls="histc", id="patterns")

tabs = "".join(f'<a href="#" class="chip {"on" if k == "graders" else ""}">{t}</a>' for k, t in [("overview", "Overview"), ("established", "Established"), ("at-risk", "At risk"), ("queue", "Queue"), ("settlement", "Settlement"), ("changes", "Changes"), ("never", "Never established"), ("payouts", "Payouts"), ("graders", "Graders"), ("directory", "Directory"), ("forum", "Forum"), ("proposals", "Proposals"), ("protocol", "Protocol"), ("charts", "Charts"), ("rules", "Rules")])
head = f'<div class="sechead"><h1>Governance</h1><div class="chips">{seg}</div></div><nav class="chips atabs scroll" aria-label="Governance">{tabs}</nav>'
banner = f'<p class="cov small" style="margin:.5rem 0">{EX} Scope mockup for Grader patterns, a new card under Graders. Values are real settled data pulled from POAScan\'s public API for this preview, not a live render.</p>'
body = head + banner + f'<div class="stats four">{stats}</div><div class="grid2">{c1}{c2}</div>' + tcard + f'<div class="grid2">{c3}</div>'
html = ui.layout("Governance", body, active="/governance", live={"state": "ok", "label": "Live", "pop": "Preview"})
assert "\u2013" not in html and "\u2014" not in html, "dash found"
sys.stdout.write(html)
