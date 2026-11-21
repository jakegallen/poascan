"""Network hub (consolidation step 3): one hero and one module for what were six tabs on /network.

Hero: the last anchor ring (age against the usual gap between anchors, from the same numbers as /api/v1/network/anchors-eta),
the live routes strip (24 h per route, plus the last 60 minutes in one-minute cells from /api/v1/network/route-buckets) and
six KPI cards with their history.
Module: Health, Charts, Anchors and Token as tabs (kit.tabmod). Each tab is its own URL; the old Overview, Records and
Unlocks links open the right tab. POA only: no price, volume, market cap or last fill (swap derived figures stay off POAScan;
the public /api/price, /api/swaps/* and MCP price fields are untouched).
Data: POAScan's own archive and the blobs it already mirrors. No new upstream read, nothing per visitor."""
import time, datetime as dt
from html import escape as E
from . import db, analytics as A, kit as KIT, segments as SG
from .ui import *
from . import ui as _ui

TABS = [("charts", "/network", "Charts"), ("anchors", "/network?tab=anchors", "Anchors"), ("token", "/network?tab=token", "Token")]
ALIAS = {"overview": "charts", "records": "anchors", "": "charts"}
METRICS = [("joins", "Joins"), ("agents", "Agents"), ("holders", "Holders"), ("supply", "Supply"), ("txs", "Txs"), ("answers", "Answers"), ("forum", "Forum")]
RANGES = [("24h", "24h", 86400), ("7d", "7d", 7 * 86400), ("30d", "30d", 30 * 86400), ("all", "All", None)]
EV_TYPES = [("", "All"), ("anchor", "Anchor"), ("release", "Release"), ("notice", "Notice"), ("record", "Record")]
HEAD = '<link rel="stylesheet" href="/static/net.css?v={}"><script src="/static/net.js?v={}" defer></script>'

class Seen:
    """Jake's standing order: the same word or reference is never shown twice on one screen. Everything that prints a label
    (hero routes, feed names, chips) asks here first; the tab names are taken before anything else."""
    def __init__(self, *taken): self.s = {self.k(t) for t in taken}
    @staticmethod
    def k(t): return " ".join(str(t).lower().split())
    def new(self, t):
        k = self.k(t)
        if k in self.s: return False
        self.s.add(k); return True

import threading
_tl = threading.local()
def seen():
    if not hasattr(_tl, "s"): _tl.s = Seen()
    return _tl.s

def _V():
    from . import views as V
    return V

def _asset_v(name):
    import hashlib, os
    try: return hashlib.sha256(open(os.path.join(os.path.dirname(__file__), "..", "static", name), "rb").read()).hexdigest()[:10]
    except OSError: return "0"

def head():
    return HEAD.format(_asset_v("net.css"), _asset_v("net.js"))

def short_age(s):
    """22m, 1h 05m, 45s: the age on the ring."""
    if s is None: return "···"
    s = max(0, int(s))
    return f"{s}s" if s < 60 else f"{s // 60}m" if s < 3600 else f"{s // 3600}h {s % 3600 // 60:02d}m" if s < 86400 else f"{s // 86400}d {s % 86400 // 3600}h"

# ---------------- hero ----------------
def anchor_ring(eta, now):
    """The Heartbeat ring as an age gauge: it fills as the last anchor ages against the usual gap and starts over on the next one.
    app.js (net.js) ticks the numeral each second and polls /api/v1/network/anchors-eta once a minute while the tab is visible."""
    last = eta.get("last_anchor_ts"); cad = eta.get("cadence_s") or 0
    age = (now - last) if last else None
    f = min(1.0, max(0.0, age / cad)) if (age is not None and cad) else 0
    rel_ = (db.get_blob("release")[0] or {}).get("current") or {}
    ver = rel_.get("version") or ""
    tk = ('<circle class="mk2" cx="120" cy="120" r="111" pathLength="96" stroke-dasharray=".25 1.75"/>'
          '<circle class="hk" cx="120" cy="120" r="112.5" pathLength="96" stroke-dasharray=".5 15.5" stroke-dashoffset=".25"/>')
    late = " late" if (age is not None and cad and age > 1.5 * cad) else ""
    return (f'<div class="ring hring ering aring{late}" style="--f:{f:.4f}" data-aring data-now="{int(now)}" data-last="{int(last or 0)}" data-cad="{int(cad)}">'
            f'<svg viewBox="0 0 240 240" aria-hidden="true"><circle class="rt" cx="120" cy="120" r="104"/>'
            f'<circle class="rp" cx="120" cy="120" r="104" pathLength="100" stroke-dasharray="{f * 100:.2f} 100"/>{tk}</svg>'
            f'<i class="rhd" aria-hidden="true"><i></i></i><i class="rpl" aria-hidden="true"></i><i class="rpl r2" aria-hidden="true"></i>'
            f'<div class="rc"><span class="lbl">Since</span><b class="bn num{" long" if age is not None and len(short_age(age)) > 5 else ""}" data-aage>{short_age(age)}</b>'
            f'</div></div>')

def _iso_ts(s):
    try: return int(dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError): return None

DOT = {"open": "ok", "halted": "bad", "down": "bad", "unknown": "nd"}

def routes_strip(now):
    """Right side of the hero: each watched route as a state dot, its name and its last 24 h (routewatch.history, one cell per 15 min).
    The state word is the legend in the header, so no row repeats Open, Halted or Down."""
    from . import routewatch as RW, views2 as V2
    d = RW.state(now); rows = []
    for r in d["routes"]:
        st = r["state"]; seen().new(r["label"])
        why = f'{r["label"]}: {RW.WORD.get(st, st)}' + (f' since {time.strftime("%b %-d %H:%MZ", time.gmtime(r["since_ts"]))}' if st in ("halted", "down") and r.get("since_ts") else "")
        rows.append(f'<li data-route="{E(r["id"])}" data-st="{st}"><span class="rn"><i class="sd {DOT.get(st, "nd")}" title="{E(why)}" role="img" aria-label="{E(why)}"></i>{E(r["label"])}</span>{V2.flag("Stale", r.get("stale_reason") or "Last read over 2 h ago") if r.get("stale") else ""}'
                    f'{V2._route_strip(r["id"], r["label"], now)}</li>')
    halted = len([r for r in d["routes"] if r["state"] in ("halted", "down")])
    return halted, f'<ul class="nrt" aria-label="Routes">{"".join(rows)}</ul>'

def minute_strip(now, minutes=60):
    """The last hour of route probes in one-minute cells (/api/v1/network/route-buckets): green clear reads, red halted or failed."""
    b = A.route_buckets(None, minutes)
    by = {m: (o, h, d) for m, o, h, d in b["buckets"]}; t0 = int(now) // 60 * 60 - (minutes - 1) * 60; cells = []
    for i in range(minutes):
        m = t0 + i * 60; v = by.get(m)
        if not v: cells.append('<i class="nd" title="No probe"></i>'); continue
        o, h, d = v; cls = "bad" if (h or d) and not o else "warn" if (h or d) else "ok"
        cells.append(f'<i class="{cls}" title="{E(time.strftime("%H:%MZ", time.gmtime(m)))} open {o}, halted {h}, down {d}"></i>')
    seen = bool(by)
    return (f'<div class="nmin" data-minutes="{minutes}"><span class="lbl">Probes</span>'
            + (f'<span class="nstrip" role="img" aria-label="Route probes">{"".join(cells)}</span>' if seen else '<span class="na">None yet.</span>') + '</div>')

def height_series(now, hours=24, n=48):
    """Chain height over the last day from the snapshots POAScan already stores (one number per snapshot), thinned to about n points."""
    rows = db.q("SELECT ts, json_extract(json, '$.height') AS h FROM snaps WHERE kind IN ('height','status') AND ts > ? ORDER BY ts", (int(now) - hours * 3600,))
    pts = [(r["ts"], r["h"]) for r in rows if r["h"]]
    if len(pts) > n: pts = pts[::-(-len(pts) // n)] + [pts[-1]]
    return pts if len(pts) > 1 else None


# 1.26.409: flag when the live chain height is this many blocks ahead of /api/status checkpoint_height.
# /api/status has no head height; the live height is the default chain on /api/networks (already mirrored).
CP_LAG_BLOCKS = 2000

def checkpoint_lag(nw=None, st=None):
    """{height, checkpoint, lag, behind} from the stored networks and status copies. behind when lag >= CP_LAG_BLOCKS."""
    if nw is None: nw = A.networks() or {}
    if st is None: st = A.status() or {}
    h = nw.get("height")
    fin = st.get("checkpoint_height")
    if fin is None: fin = nw.get("checkpoint_height")
    try:
        h, fin = int(h), int(fin)
    except (TypeError, ValueError):
        return dict(height=h, checkpoint=fin, lag=None, behind=False)
    lag = h - fin
    return dict(height=h, checkpoint=fin, lag=lag, behind=lag >= CP_LAG_BLOCKS)

def kpis(sd, now):
    """Five KPI cards. History only where POAScan keeps a series (height from the snapshots, lag and latency from status_data)."""
    nw = A.networks()
    h = nw.get("height"); fin = nw.get("checkpoint_height"); lag = (h - fin) if (h and fin) else None
    core = [e for e in sd["eps"] if e["ep"].startswith("probe")] or sd["eps"]
    s1 = [e["s1"] for e in core if e["s1"] is not None]; p50s = [e["p50"] for e in core if e["p50"]]
    p50 = sorted(p50s)[len(p50s) // 2] if p50s else None
    lagser = [(t, v) for t, v in sd["lag"] if t > now - 86400]
    fmtc = lambda v: compact(v) if v is not None else "···"
    cp = checkpoint_lag(nw, A.status())
    lag = cp["lag"] if cp["lag"] is not None else lag
    behind = flag("Behind", f"{cp['lag']:,} blocks ahead of the checkpoint") if cp["behind"] else ""
    return "".join([KIT.kpi("Height", f'<span class="num">{fmtc(h)}</span>', height_series(now)),
                    KIT.kpi("Finalized", f'<span class="num">{fmtc(fin)}</span>' + _V2().cp_flag()),   # Parked or Stalled stays on the finalized height
                    KIT.spark_in(stat("Lag", f'<span class="num">{intc(lag)}</span>', tip="Blocks between the chain height and the finalized height", flag_html=behind), lagser),
                    KIT.kpi("Success 1h", f'<span class="num">{pct(sum(s1) / len(s1))}</span>' if s1 else '<span class="num">···</span>'),
                    KIT.kpi("Latency p50", f'<span class="num">{p50:,} ms</span>' if p50 else '<span class="num">···</span>', [(h_, v) for h_, v in sd["lat"]] if sd["lat"] else None)])

def hero():
    now = time.time()
    from . import views2 as V2
    try: sd = V2.status_data()
    except Exception: sd = dict(eps=[], inc=[], lag=[], lat=[], anchors=[])
    eta = A.anchor_eta()
    nxt = eta.get("next_anchor_eta"); cad = eta.get("cadence_s")
    nx = ("due" if nxt <= now else short_age(nxt - now)) if nxt else "···"
    figs = ('<div class="trio">'
            f'<div><span class="lbl">Next</span><b class="num" data-anext="{int(nxt or 0)}">{nx}</b></div>'
            f'<div><span class="lbl">Cadence</span><b class="num">{short_age(cad) if cad else "···"}</b></div>'
            f'<div><span class="lbl">Anchored</span><b class="num">{intc(eta.get("anchors_in_window"))}</b></div></div>')
    halted, rl = routes_strip(now)
    leg = "".join(f'<span><i class="sw {k}"></i>{n}</span>' for n, k in (("Open", "o"), ("Halted", "h"), ("Down", "d")))
    bench = (f'<div class="bench nbench"><div class="bl">{anchor_ring(eta, now)}{figs}</div>'
             f'<div class="br"><div class="bh"><i class="ldot" aria-hidden="true"></i><span class="lbl on">Live</span><span class="lbl">Routes · 24h</span>'
             f'<span class="legend">{leg}</span></div>{rl}{minute_strip(now)}</div></div>')
    strip = f'<section class="stats four kpis" role="group" aria-label="Headline numbers">{kpis(sd, now)}</section>'
    return f'<section id="tracker" class="card benchc hpulse nethero" aria-label="Network">{bench}{strip}</section>'

# ---------------- tab bodies ----------------
GROUP = [("down", "Failing", "bad"), ("degraded", "Degraded", "warn"), ("ok", "OK", "ok"), ("other", "Idle", "")]

def _feed_rows():
    """Feeds and route health in one list, grouped by state so no row repeats a state word. A name already shown in the hero (a route) or
    on a tab is left out here; the age of the last good read is in each name's tooltip."""
    from . import views2 as V2
    fd = A.feeds(); g = {k: [] for k, _, _ in GROUP}
    def put(label, state, tip):
        st = {"OK": "ok", "Down": "down", "Stale": "down"}.get(state, "degraded" if state in ("Degraded", "Partial", "degraded") else state if state in g else "other")
        if seen().new(label): g[st].append(f'<li><span title="{E(tip)}">{E(label)}</span></li>')
    for r in fd.get("routes") or []: put(r["label"], r["state"].capitalize() if r["state"] != "unknown" else "other", f'{r["label"]}: {r["detail"]}')
    for f in fd["feeds"]:
        put(f["label"], f["state"], f'{f["label"]}: ' + (f'last good read {time.strftime("%b %-d %H:%MZ", time.gmtime(f["last_ok"]))}' if f.get("last_ok") else "no read yet"))
    out = []
    for k, word, cls in GROUP:
        if g[k]: out.append(f'<div class="ngrp"><div class="ngh"><span class="tag {cls}">{word}</span><b class="num">{len(g[k])}</b></div><ul class="nchips">{"".join(g[k])}</ul></div>')
    return "".join(out) or na("No feeds yet.")

def _incidents(sd, now, n=20):
    """14 days of incidents, one row per endpoint: how many, the latest start, the total time down. No endpoint is listed twice."""
    if not sd["inc"]: return na("No incidents in 14 days.")
    by = {}
    for a, b, w, f in sd["inc"]:
        r = by.setdefault(w.replace("probe ", ""), dict(n=0, last=0, secs=0, on=False))
        r["n"] += 1; r["last"] = max(r["last"], a); r["secs"] += ((b or now) - a); r["on"] = r["on"] or b is None or now - b < 600
    rows = sorted(by.items(), key=lambda kv: -kv[1]["last"])[:n]
    return table(["Incident", "Count", "Latest", "Total"], [[f'<code>{E(w)}</code>' + (' <i class="sd bad" title="Ongoing" role="img" aria-label="Ongoing"></i>' if r["on"] else ""),
                 r["n"], utc(r["last"], "%m-%d %H:%M"), dur(r["secs"])] for w, r in rows], cls="wrapt")

def _V2():
    from . import views2
    return views2

def health_body(view=""):
    from . import views2 as V2
    sd = V2.status_data(); now = time.time()
    if view == "details":
        d = [f'<div class="kit-sec"><span class="lbl">Freshness</span>{V2.freshness_html()}</div>']
        try: d.append(f'<div class="kit-sec"><span class="lbl">Reconciliation</span>{V2.recon_card()}</div>')
        except Exception: pass
        ep = sd["eps"][:20]
        tb = table(["Endpoint", "1h", "24h", "p50", "p95", "Last error"], [[f'<code>{E(e["ep"].replace("probe ", ""))}</code>', V2._okpct(e["s1"]), V2._okpct(e["s24"]),
               f'{e["p50"]:,} ms' if e["p50"] else "···", f'{e["p95"]:,} ms' if e["p95"] else "···", rel(e["last_err"]) if e["last_err"] else "···"] for e in ep], cls="wrapt")
        lagc = line([(t, v) for t, v in sd["lag"] if t > now - 86400], color="gold", fmt=lambda v: f"{v:,.0f}", y0=0)
        latc = bars([(dt.datetime.fromtimestamp(h, dt.timezone.utc).strftime("%H:00"), [v], h) for h, v in sd["lat"]], colors=("gold",), fmt=lambda v: f"{v:,.0f}ms")
        d.append(f'<div class="kit-sec"><span class="lbl">Endpoints</span>{tb}</div>')
        d.append(KIT.split('<span class="lbl">Finality lag · 24h</span>' + lagc, '<span class="lbl">Latency p50 · hourly</span>' + latc))
        d.append(KIT.split('<span class="lbl">Uptime · daily UTC</span>' + V2.uptime_chart_html(), '<span class="lbl">Last 7d</span>' + V2.uptime_table_html()))   # the uptime history stays on Health
        return "".join(d)
    return KIT.split(_feed_rows(), _incidents(sd, now))

def _joins(rng):
    """Joins per hour (24h, 7d) or per day (30d, All) from the join memos in the archive: the same series as /api/v1/agents/hourly."""
    span = dict((k, v) for k, _, v in RANGES)[rng]; now = int(time.time())
    if rng in ("24h", "7d"):
        h = A.agents_hourly(24 if rng == "24h" else 168)["joins"]; m = {t: n for t, n in h}
        t0 = (now - span) // 3600 * 3600 + 3600
        return [(t, m.get(t, 0)) for t in range(t0, now // 3600 * 3600, 3600)]
    cut = (now - span) if span else 0
    m = {int(r["d"]): r["n"] for r in db.q("SELECT (ts/86400)*86400 AS d, COUNT(*) AS n FROM labels WHERE source='join memo' AND ts > ? GROUP BY d ORDER BY d", (cut,))}
    if not m: return []
    t0 = min(m); today = now // 86400 * 86400
    return [(t, m.get(t, 0)) for t in range(t0, today, 86400)]   # today's partial day left out

def _forum(rng, t_lo, t_hi):
    from . import topics as TOP
    tmid = int(time.time() // 86400) * 86400
    return [(ts + 43200, p + c) for ts, p, c in TOP.posts_daily() if t_lo - 86400 <= ts < tmid and ts <= t_hi]

def overlay(chart_html, fpts, x0, x1, color="steel"):
    """Forum activity on the joins chart: a second line with its own right axis (ui.line is one series; the overlay svg shares the plot box
    and the same x scale). Labels the axis ends in the forum colour."""
    if len(fpts) < 2 or x1 <= x0: return chart_html
    lo = 0; hi = max(v for _, v in fpts) or 1; hi = hi * 1.1
    X = lambda x: _ui.VW * (x - x0) / (x1 - x0); Y = lambda y: _ui.VH * (1 - (y - lo) / (hi - lo))
    P = [(X(min(max(x, x0), x1)), Y(y)) for x, y in fpts]
    d = _ui._smooth(P)
    svg = (f'<svg class="chart fov" viewBox="0 0 {_ui.VW} {_ui.VH}" preserveAspectRatio="none" aria-hidden="true">'
           f'<path d="{d}" class="ln s-steel"/></svg>')
    last = fpts[-1][1]
    ax = (f'<span class="fax top" title="Forum posts and comments per day">{compact(hi / 1.1)}</span><span class="fax bot">0</span>'
          f'<span class="flv" style="top:{100 * Y(last) / _ui.VH:.2f}%"><b>{compact(last)}</b></span>')
    i = chart_html.find('class="cvp"')
    if i < 0: return chart_html
    j = chart_html.find("</div></div>", i)
    return chart_html[:j] + svg + ax + chart_html[j:]

def _series(metric, rng):
    from . import views3 as V3
    span = dict((k, v) for k, _, v in RANGES)[rng]; now = time.time(); t0 = now - span if span else 0
    g = V3.growth_data(); cut = lambda pts: [(t, v) for t, v in pts if t >= t0]
    xf = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%m-%d %H:%M")
    fn = lambda v: f"{v:,.0f}"
    if metric == "joins": return ("line", _joins(rng), dict(fmt=fn, xfmt=xf, y0=0))
    if metric in ("agents", "holders"): return ("line", cut(g[metric]), dict(fmt=fn, xfmt=xf))
    if metric == "supply": return ("line", cut(g["supply"]), dict(fmt=compact, xfmt=xf, y0=0))
    if metric == "txs":
        if rng == "all": return ("bars", [(dt.datetime.fromtimestamp(r["d"], dt.timezone.utc).strftime("%b %-d"), [r["n"]]) for r in g["day"]], dict(fmt=fn))
        return ("line", [(r["h"], r["n"]) for r in g["hour"][:-1] if r["h"] >= t0], dict(fmt=fn, xfmt=xf, y0=0))
    if metric == "answers":
        pe = g["per_ep"]
        return ("bars", [(SG.ep_label(k), [a, max(0, p)]) for k, a, p in pe[-60:]] if rng != "all" else [(SG.ep_label(k), [a, max(0, p)]) for k, a, p in pe], dict(fmt=fn, legend=["Answered", "Paid"], colors=("gold", "steel"), stacked=False))
    # forum: posts plus comments per day (today's partial day left out)
    from . import topics as TOP
    tmid = int(now // 86400) * 86400
    return ("line", [(ts, p + c) for ts, p, c in TOP.posts_daily() if t0 <= ts < tmid], dict(fmt=fn, xfmt=xf, y0=0))

DEFAULT_METRIC = "answers"   # 1.26.399: Joins reads a flat zero while joining is halted; Answers always has data

def charts_body(qs):
    metric = (qs.get("metric") or [DEFAULT_METRIC])[0]; metric = metric if metric in dict(METRICS) else DEFAULT_METRIC
    rng = (qs.get("range") or ["7d"])[0]; rng = rng if rng in [k for k, _, _ in RANGES] else "7d"
    ov = (qs.get("ov") or ["1"])[0] != "0" and metric == "joins" and rng != "24h"
    kind, pts, kw = _series(metric, rng)
    def url(**o):
        p = dict(metric=metric, range=rng, ov=None); p.update(o)
        q = [f"{k}={v}" for k, v in p.items() if v is not None and not (k == "metric" and v == DEFAULT_METRIC) and not (k == "range" and v == "7d")]
        return "/network?tab=charts" + "".join("&amp;" + x for x in q)
    mchips = "".join(f'<a href="{url(metric=k)}" class="chip {"on" if k == metric else ""}" data-kit-sub="m{k}">{t}</a>' for k, t in METRICS)
    rchips = "".join(f'<a href="{url(range=k)}" class="chip {"on" if k == rng else ""}" data-kit-sub="r{k}">{t}</a>' for k, t, _ in RANGES)
    tg = ""
    if metric == "joins" and rng != "24h":
        tg = f'<a href="{url(ov="0") if ov else url()}" class="chip ovt {"on" if ov else ""}" role="switch" aria-checked="{"true" if ov else "false"}" data-kit-sub="ov">{"<i class=\'ev f\' aria-hidden=\'true\'></i>" if ov else ""}Overlay</a>'
    if kind == "line":
        ch = line(pts, height=300, color="gold", **kw) if len(pts) > 1 else na("No data in this range.")
        if ov and len(pts) > 1: ch = overlay(ch, _forum(rng, pts[0][0], pts[-1][0]), pts[0][0], pts[-1][0])
    else:
        ch = bars(pts, height=300, colors=kw.pop("colors", ("gold",)), **kw) if pts else na("No data in this range.")
    legend = ""
    tools = f'<nav class="chips kit-sub scroll ncc" aria-label="Metric">{mchips}</nav>'
    rr = f'<nav class="chips kit-sub ncr" aria-label="Range">{rchips}{tg}</nav>'
    return f'{tools}<div class="ncbar">{rr}{legend}</div><div class="ncw" data-metric="{metric}" data-range="{rng}">{ch}</div>'

EV_DOT = {"anchor": "a", "release": "r", "notice": "n", "record": "k"}

def events_body(qs):
    """One feed of the four event kinds (/api/v1/network/events), newest first, 20 rows. The kind is a coloured dot that matches the dot on its
    filter chip; the two anchors of one checkpoint height (Base and Solana) are one row; each day is named once."""
    ty = (qs.get("type") or [""])[0]; ty = ty if ty in [k for k, _ in EV_TYPES if k] else ""
    d = A.network_events(ty or None, 20)
    chips = "".join(f'<a href="/network?tab=anchors{"&amp;type=" + k if k else ""}" class="chip {"on" if k == ty else ""}" data-kit-sub="e{k or "all"}">'
                    + (f'<i class="ev {EV_DOT[k]}" aria-hidden="true"></i>' if k else "") + f'{t}</a>' for k, t in EV_TYPES)
    rows = []; seen_h = {}
    for e in d["events"][:20]:
        lab = e["label"]; u = e.get("url")
        if e["type"] == "anchor":
            import re
            m = re.match(r"Checkpoint (\d+) anchored to (\w+)", lab); h = m.group(1) if m else lab; ch = (m.group(2) if m else "").lower()
            ico = "net-solana" if "sol" in ch else "net-base" if "base" in ch else None
            link = (f'<a class="chn" href="{E(u)}" target="_blank" rel="noopener noreferrer" title="{E(m.group(2) if m else "")}"><img src="/static/{ico}.svg" width="16" height="16" alt="{E(m.group(2) if m else "")}"></a>' if u and ico else "")
            if h in seen_h: seen_h[h][1].append(link); continue
            seen_h[h] = [e, [link], f'<span class="mono">{intc(int(h)) if h.isdigit() else E(h)}</span>']
            rows.append(h); continue
        if e["type"] == "release": lab = lab.replace("Release ", "", 1)
        txt = E(lab)
        if u: txt = f'<a href="{E(u)}"' + (' target="_blank" rel="noopener noreferrer"' if u.startswith("http") else "") + f'>{txt}</a>'
        rows.append((e, txt))
    out = []; last_day = None; last_tm = None
    for r in rows:
        if isinstance(r, str): e, links, txt = seen_h[r]; txt = txt + " " + "".join(links)
        else: e, txt = r
        day = time.strftime("%b %-d", time.gmtime(e["ts"])) if e.get("ts") else ""
        if day != last_day:
            out.append(f'<li class="nday" aria-hidden="true">{day}</li>'); last_day = day
        tt = time.strftime("%H:%MZ", time.gmtime(e["ts"])) if e.get("ts") else ""
        tm = f'<time class="t" data-ts="{int(e["ts"])}">{tt}</time>' if tt and tt != last_tm else ""; last_tm = tt
        out.append(f'<li data-type="{e["type"]}"><i class="ev {EV_DOT[e["type"]]}" role="img" aria-label="{e["type"]}" title="{e["type"]}"></i><span class="el">{txt}</span><span class="fdt">{tm}</span></li>')
    body = f'<ul class="nev" aria-label="Events">{"".join(out)}</ul>' if out else na("No events yet.")
    return f'<nav class="chips kit-sub scroll" aria-label="Event type">{chips}</nav>{body}'

def _n(v, dec=2):
    """A POA amount as a bare number: the unit is named once, in the module header."""
    return compact(v, dec) if v is not None else "···"

def token_body():
    from . import views3 as V3
    st = A.status(); ep = A.epoch_rows(); sp = A.supply_split(); h = A.holders(); c = A.concentration()
    sup = float(st.get("supply") or 0); er = [r for r in A.epoch_rows_all() if not SG.unconfirmed(r["epoch"], r["segment"])]
    fg = KIT.figs([("Supply", f'<span class="num">{_n(sup)}</span>'), ("Circulating", f'<span class="num">{_n(sp["spendable"])}</span>'), ("Locked", f'<span class="num">{_n(sp["locked"])}</span>'),
                   ("Holders", intc(st.get("holders"))), ("Median", f'<span class="num">{_n(h["median"])}</span>'), ("Gini", f'<span class="num">{c["gini"]:.3f}</span>' if c["gini"] is not None else "···")])
    mb = bars([(f"E{r['epoch']}", [r["minted"], r["burned"]]) for r in ep], legend=["Minted", "Burned"], colors=("gold", "ember"))
    u = V3.unlock_data(); tot = u["total"] or 1
    cal = table(["At close", f"Time ({TZ})", "Unlocked", "Share"], [[f"E{j}", utc(t, "%m-%d %H:%M"), _n(c_), pct(c_ / tot)] for j, t, c_, d_ in u["fut"][:12]])
    conc = ('<div class="minis conc">' + "".join(f'<div><span class="lbl">Top {n}</span>{pct(c[f"top{n}_share"], 2)}</div>' for n in (1, 5, 10, 20)) + "</div>")
    return (fg + KIT.split(f'<span class="lbl" title="Close records only.{E(_V()._pend_tip())}">Per epoch</span>' + mb, '<span class="lbl">Vesting</span>' + V3.unlock_chart())
            + KIT.split('<span class="lbl">Calendar</span>' + cal, '<span class="lbl">Concentration</span>' + conc))

# ---------------- page ----------------
def module(tab, qs):
    if tab == "charts": body = charts_body(qs); tools = ""
    elif tab == "anchors":
        from . import protocolview as PV
        body = events_body(qs); tools = PV.badge()   # the client-versus-release badge stays with the releases it describes
    elif tab == "token": body = token_body(); tools = '<span class="kit-n" title="Amounts are in POA">POA</span>'
    else:
        view = (qs.get("view") or [""])[0]; view = view if view == "details" else ""
        from . import views2 as _V2
        body = _V2.upgrade_line() + _V().cut_note() + health_body(view)   # the recovery line and the segment cut note stay on Health
        tools = (f'<a href="/network" class="chip {"" if view else "on"}" data-kit-sub="feeds">Feeds</a>'
                 f'<a href="/network?view=details" class="chip {"on" if view else ""}" data-kit-sub="details">Details</a>')
    tabs = [(k, h, t, None) for k, h, t in TABS]
    return KIT.tabmod(tabs, tab, body, tools, id="netmod", label="Network")

def page(tab, qs):
    """Charts, Anchors and Token only. The live hero and Health now live on /live (the header pill)."""
    _tl.s = Seen(*[t for _, _, t in TABS], "Last anchor", "Next", "Cadence", "Anchored", "Routes", "Last hour", "Open", "Halted", "Down")
    V = _V(); tab = ALIAS.get(tab, tab); tab = tab if tab in dict((k, 0) for k, _, _ in TABS) else "charts"
    title = {"charts": "Network charts", "anchors": "Network events", "token": "POA token"}[tab]
    h1 = {"charts": "Charts", "anchors": "Events", "token": "Token"}[tab]
    body = f'<div class="sechead"><h1 class="sr-only">{h1}</h1></div>{module(tab, qs)}'
    return V.page(title, body, "/network", head=head())
