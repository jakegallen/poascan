"""Shared page kit (1.26.383, consolidation phase 0): the Heartbeat pieces as reusable parts.

pulse()   the hero card: a bench (gauge on the left, live strip on the right) over a KPI strip of sparkline cards.
kpi()     one KPI card: terse label, value, sparkline (watermark and count-up come from the existing stat CSS and app.js).
tabmod()  one tabbed module: tab chips in the header, one body. Tabs are real links (every tab renders server side, so a
          crawler or a visitor with no script gets the same page); app.js (poaKit) swaps the body in place with a short
          crossfade, keeps the URL, and falls back to a normal load on any error. Reduced motion swaps with no animation.
No new endpoints, no new upstream reads: a tab swap fetches the target page, which the page cache already serves."""
from html import escape as E
from . import ui as _ui
from .ui import stat, spark_in

def kpi(label, value, series=None, icon="", tip=None):
    """One hero KPI card. value is the inner HTML of the number (usually a span.num); series: [(ts, value)] for the sparkline."""
    s = stat(label, value, icon=icon, tip=tip)
    return spark_in(s, series) if series else s

def pulse(bench, kpis="", label="Open epoch", attrs=""):
    """The hero card. bench: bench.bench_html() or any .bench markup; kpis: joined kpi() cards (the strip is left out when empty)."""
    strip = f'<section class="stats four kpis" role="group" aria-label="Headline numbers"{attrs}>{kpis}</section>' if kpis else ""
    return f'<section id="tracker" class="card benchc hpulse" aria-label="{E(label)}">{bench}{strip}</section>'

def tabmod(tabs, cur, body, toolbar="", id="ledger", label="Tabs"):
    """tabs: [(key, href, label, count or None)]. The active tab is a link too (aria-current), so the chip row never changes shape."""
    chips = "".join(
        f'<a href="{E(h)}" class="chip {"on" if k == cur else ""}" data-kit-tab="{E(k)}"{" aria-current=\"page\"" if k == cur else ""}>{E(t)}'
        + (f' <span class="dim">{c:,}</span>' if c is not None else "") + "</a>" for k, h, t, c in tabs)
    return (f'<section class="card kit-mod" id="{E(id)}" data-kit="tabs"><div class="ch kit-ch"><nav class="chips kit-tabs" aria-label="{E(label)}">{chips}</nav>'
            f'<div class="cx kit-tools">{toolbar}</div></div><div class="cb kit-body" aria-live="polite">{body}</div></section>')

def split(*blocks):
    """Equal-height blocks side by side inside a module (stacked under 900 px). Plain blocks, not nested cards."""
    return '<div class="kit-split">' + "".join(f'<div class="kit-blk">{b}</div>' for b in blocks) + "</div>"

def figs(items):
    """A compact row of label and number pairs inside a module (no sub-lines): [(label, value_html)]."""
    return '<div class="kit-figs">' + "".join(f'<div><span class="lbl">{E(l)}</span><b class="num">{v}</b></div>' for l, v in items) + "</div>"
