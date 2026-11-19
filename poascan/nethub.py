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

TABS = [("health", "/network", "Health"), ("charts", "/network?tab=charts", "Charts"), ("anchors", "/network?tab=anchors", "Anchors"), ("token", "/network?tab=token", "Token")]
ALIAS = {"overview": "health", "records": "anchors", "": "health"}
METRICS = [("joins", "Joins"), ("agents", "Agents"), ("holders", "Holders"), ("supply", "Supply"), ("txs", "Txs"), ("answers", "Answers"), ("forum", "Forum")]
RANGES = [("24h", "24h", 86400), ("7d", "7d", 7 * 86400), ("30d", "30d", 30 * 86400), ("all", "All", None)]
EV_TYPES = [("", "All"), ("anchor", "Anchor"), ("release", "Release"), ("notice", "Notice"), ("record", "Record")]
HEAD = '<link rel="stylesheet" href="/static/net.css?v={}"><script src="/static/net.js?v={}" defer></script>'

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
            f'<div class="rc"><span class="lbl">Last anchor</span><b class="bn num{" long" if age is not None and len(short_age(age)) > 5 else ""}" data-aage>{short_age(age)}</b>'
            f'<div class="bcd"><span class="lbl">Version</span><b class="cd num mono">{E(ver) if ver else "···"}</b></div></div></div>')

def _chain_age(now):
    out = {}
    for r in db.q("SELECT chain, MAX(anchored_at) AS t FROM anchors WHERE segment=? GROUP BY chain", (SG.CURRENT,)):
        ts = _iso_ts(r["t"])
        if ts: out[(r["chain"] or "").lower()] = ts
    return out

def _iso_ts(s):
    try: return int(dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError): return None

def _age_of(ages, key, now):
    t = next((v for k, v in ages.items() if key in k), None)
    return short_age(now - t) if t else '<span class="na">···</span>'

STATE_TAG = {"open": ("ok", "OPEN"), "halted": ("bad", "HALTED"), "down": ("bad", "DOWN"), "unknown": ("", "NO READ")}

def routes_strip(now):
    """Right side of the hero: each watched route with its state and last 24 h (routewatch.history, one cell per 15 min)."""
    from . import routewatch as RW, views2 as V2
    d = RW.state(now); rows = []
    for r in d["routes"]:
        st = r["state"]; cls, word = STATE_TAG.get(st, ("", st.upper()))
        if r.get("covered_by") and st in ("halted", "down"): cls, word = "warn", "DEGRADED"
        since = f'<span class="dim small">since {lt(r["since_ts"])}</span>' if st in ("halted", "down") and r.get("since_ts") else ""
        rows.append(f'<li data-route="{E(r["id"])}" data-st="{st}"><span class="rn">{E(r["label"])}</span><span class="rg">{since}<span class="tag {cls}">{word}</span></span>'
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
    return (f'<div class="nmin" data-minutes="{minutes}"><span class="lbl">Probes · 60m</span>'
            + (f'<span class="nstrip" role="img" aria-label="Route probes, last hour">{"".join(cells)}</span>' if seen else '<span class="na">No probes this hour</span>') + '</div>')

def height_series(now, hours=24, n=48):
    """Chain height over the last day from the snapshots POAScan already stores (one number per snapshot), thinned to about n points."""
    rows = db.q("SELECT ts, json_extract(json, '$.height') AS h FROM snaps WHERE kind IN ('height','status') AND ts > ? ORDER BY ts", (int(now) - hours * 3600,))
    pts = [(r["ts"], r["h"]) for r in rows if r["h"]]
    if len(pts) > n: pts = pts[::-(-len(pts) // n)] + [pts[-1]]
    return pts if len(pts) > 1 else None

def kpis(sd, now):
    """Six KPI cards. History only where POAScan keeps a series (finality lag and latency from status_data)."""
    V = _V(); nw = A.networks(); fd = A.feeds()
    h = nw.get("height"); fin = nw.get("checkpoint_height"); lag = (h - fin) if (h and fin) else None
    core = [e for e in sd["eps"] if e["ep"].startswith("probe")] or sd["eps"]
    s1 = [e["s1"] for e in core if e["s1"] is not None]; p50s = [e["p50"] for e in core if e["p50"]]
    p50 = sorted(p50s)[len(p50s) // 2] if p50s else None
    lagser = [(t, v) for t, v in sd["lag"] if t > now - 86400]
    hser = height_series(now)
    ac = _chain_age(now); last = max(ac.values()) if ac else None
    fmtc = lambda v: compact(v) if v is not None else "···"
    cards = [KIT.kpi("Height", f'<span class="num">{fmtc(h)}</span>', hser),
             KIT.kpi("Finalized", f'<span class="num">{fmtc(fin)}</span>'),
             KIT.kpi("Lag", f'<span class="num">{intc(lag)}</span>', lagser, tip="Blocks between the chain height and the finalized height"),
             KIT.kpi("Last anchor", f'<span class="num">{short_age(now - last) + " ago" if last else "···"}</span>'),
             KIT.kpi("Success 1h", f'<span class="num">{pct(sum(s1) / len(s1))}</span>' if s1 else '<span class="num">···</span>'),
             KIT.kpi("Latency p50", f'<span class="num">{p50:,} ms</span>' if p50 else '<span class="num">···</span>', [(h_, v) for h_, v in sd["lat"]] if sd["lat"] else None)]
    return "".join(cards)

def hero():
    now = time.time(); V = _V()
    from . import views2 as V2
    try: sd = V2.status_data()
    except Exception: sd = dict(eps=[], inc=[], lag=[], lat=[], anchors=[])
    eta = A.anchor_eta(); ages = _chain_age(now); fd = A.feeds()
    up = fd["state"]; upc = {"OK": "ok", "Partial": "warn", "Degraded": "warn", "Down": "bad"}.get(up, "")
    figs = ('<div class="trio">'
            f'<div><span class="lbl">Base</span><b class="num">{_age_of(ages, "base", now)}</b></div>'
            f'<div><span class="lbl">Solana</span><b class="num">{_age_of(ages, "sol", now)}</b></div>'
            f'<div><span class="lbl">Upstream</span><b class="num"><span class="tag {upc}">{E(up)}</span></b></div></div>')
    halted, rl = routes_strip(now)
    leg = "".join(f'<span><i class="sw {k}"></i>{n}</span>' for n, k in (("Open", "o"), ("Halted", "h"), ("Down", "d")))
    bench = (f'<div class="bench nbench"><div class="bl">{anchor_ring(eta, now)}{figs}</div>'
             f'<div class="br"><div class="bh"><i class="ldot" aria-hidden="true"></i><span class="lbl on">Live</span><span class="lbl">Routes · 24h</span>'
             f'<span class="lbl">Halted</span><span class="tag {"bad" if halted else "ok"}" data-halted="{halted}">{halted}</span>'
             f'<span class="legend">{leg}</span></div>{rl}{minute_strip(now)}</div></div>')
    strip = f'<section class="stats four kpis six" role="group" aria-label="Headline numbers">{kpis(sd, now)}</section>'
    return f'<section id="tracker" class="card benchc hpulse nethero" aria-label="Network">{bench}{strip}</section>'

# ---------------- tab bodies ----------------
def _feed_rows():
    from . import views2 as V2
    fd = A.feeds(); TAG = V2.FEED_TAG
    li = "".join(f'<li data-feed="{E(f["label"])}"><b>{E(f["label"])}</b><span class="tag {TAG[f["state"]]}">{f["state"]}</span>'
                 + (f'<span class="tag warn" title="No good read in {dur(f["stale_s"])}">Stale</span>' if f.get("stale") else "")
                 + f'<span class="fdt">{rel(f["last_ok"]) if f["last_ok"] else "never"}</span></li>' for f in fd["feeds"])
    RT = {"ok": ("ok", "OK"), "degraded": ("warn", "Degraded"), "down": ("bad", "Down"), "unknown": ("", "No read")}
    rli = "".join(f'<li data-rh="{E(r["id"])}"><b>{E(r["label"])}</b><span class="tag {RT[r["state"]][0]}" title="{E(r["detail"])}">{RT[r["state"]][1]}</span>'
                  + ('<span class="tag" title="Decides OK vs Partial">Core</span>' if r["core"] else "<span></span>") + f'<span class="fdt">{E(r["detail"])}</span></li>' for r in fd.get("routes") or [])
    head_ = (f'<div class="fdh"><span class="lbl">Health</span><span class="tag {TAG[fd["state"]]}" data-health="{fd["state"]}">{fd["state"]}</span>'
             f'<span class="lbl">Chain</span><span class="tag {TAG[fd["chain"]]}">{fd["chain"]}</span></div>')
    return head_ + (f'<ul class="feeds nf rhl" aria-label="Route health">{rli}</ul>' if rli else "") + f'<ul class="feeds nf" aria-label="Feeds">{li}</ul>'

def _incidents(sd, now, n=20):
    if not sd["inc"]: return '<span class="lbl">Incidents · 14d</span>' + na("No incidents in 14 days.")
    rows = [[utc(a, "%m-%d %H:%M"), ('<span class="tag bad">ONGOING</span>' if b is None or now - b < 600 else dur(b - a)), E(w.replace("probe ", ""))] for a, b, w, f in sd["inc"][:n]]
    return '<span class="lbl">Incidents · 14d</span>' + table([f"Start ({TZ})", "Duration", "What"], rows, cls="wrapt")

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

def charts_body(qs):
    metric = (qs.get("metric") or ["joins"])[0]; metric = metric if metric in dict(METRICS) else "joins"
    rng = (qs.get("range") or ["7d"])[0]; rng = rng if rng in [k for k, _, _ in RANGES] else "7d"
    ov = (qs.get("ov") or ["1"])[0] != "0" and metric == "joins" and rng != "24h"
    kind, pts, kw = _series(metric, rng)
    def url(**o):
        p = dict(metric=metric, range=rng, ov=None); p.update(o)
        q = [f"{k}={v}" for k, v in p.items() if v is not None and not (k == "metric" and v == "joins") and not (k == "range" and v == "7d")]
        return "/network?tab=charts" + "".join("&amp;" + x for x in q)
    mchips = "".join(f'<a href="{url(metric=k)}" class="chip {"on" if k == metric else ""}" data-kit-sub="m{k}">{t}</a>' for k, t in METRICS)
    rchips = "".join(f'<a href="{url(range=k)}" class="chip {"on" if k == rng else ""}" data-kit-sub="r{k}">{t}</a>' for k, t, _ in RANGES)
    tg = ""
    if metric == "joins" and rng != "24h":
        tg = f'<a href="{url(ov="0") if ov else url()}" class="chip ovt {"on" if ov else ""}" role="switch" aria-checked="{"true" if ov else "false"}" data-kit-sub="ov">Forum</a>'
    if kind == "line":
        ch = line(pts, height=300, color="gold", **kw) if len(pts) > 1 else na("No data in this range.")
        if ov and len(pts) > 1: ch = overlay(ch, _forum(rng, pts[0][0], pts[-1][0]), pts[0][0], pts[-1][0])
    else:
        ch = bars(pts, height=300, colors=kw.pop("colors", ("gold",)), **kw) if pts else na("No data in this range.")
    legend = '<span class="legend ovl"><span><i class="sw a"></i>Joins</span><span><i class="sw f"></i>Forum</span></span>' if ov else ""
    tools = f'<nav class="chips kit-sub scroll ncc" aria-label="Metric">{mchips}</nav>'
    rr = f'<nav class="chips kit-sub ncr" aria-label="Range">{rchips}{tg}</nav>'
    return f'{tools}<div class="ncbar">{rr}{legend}</div><div class="ncw" data-metric="{metric}" data-range="{rng}">{ch}</div>'

def events_body(qs):
    ty = (qs.get("type") or [""])[0]; ty = ty if ty in [k for k, _ in EV_TYPES if k] else ""
    d = A.network_events(ty or None, 20); now = time.time()
    chips = "".join(f'<a href="/network?tab=anchors{"&amp;type=" + k if k else ""}" class="chip {"on" if k == ty else ""}" data-kit-sub="e{k or "all"}">{t}</a>' for k, t in EV_TYPES)
    def row(e):
        u = e.get("url")
        lab = E(e["label"])
        if u: lab = f'<a href="{E(u)}"' + (' target="_blank" rel="noopener noreferrer"' if u.startswith("http") else "") + f'>{lab}</a>'
        return (f'<li data-type="{e["type"]}"><span class="tag {"" if e["type"] != "notice" else "warn"}">{e["type"].upper()}</span><span class="el">{lab}</span>'
                f'<span class="fdt">{rel(e["ts"]) if e.get("ts") else "···"}</span></li>')
    rows = "".join(row(e) for e in d["events"][:20]) or ""
    body = f'<ul class="nev" aria-label="Events">{rows}</ul>' if rows else na("No events yet.")
    return f'<nav class="chips kit-sub scroll" aria-label="Event type">{chips}</nav>{body}'

def token_body():
    from . import views3 as V3, econ as X
    V = _V(); st = A.status(); ep = A.epoch_rows(); sp = A.supply_split(); p = A.params(); h = A.holders(); c = A.concentration()
    sup = float(st.get("supply") or 0); er = [r for r in A.epoch_rows_all() if not SG.unconfirmed(r["epoch"], r["segment"])]
    mint_t = sum(float(r.get("minted") or 0) for r in er); burn_t = sum(float(r.get("burned") or 0) for r in er)
    g = V3.growth_data()
    fg = KIT.figs([("Supply", poa(sup, mined=True)), ("Circulating", poa(sp["spendable"])), ("Locked", poa(sp["locked"])), ("Holders", intc(st.get("holders"))),
                   ("Minted", poa(mint_t, mined=True)), ("Burned", poa(burn_t))])
    mb = bars([(f"E{r['epoch']}", [r["minted"], r["burned"]]) for r in ep], legend=["Minted", "Burned"], colors=("gold", "ember"))
    gi = f'<span class="num">{c["gini"]:.3f}</span>' if c["gini"] is not None else "···"
    conc = ('<div class="minis conc">' + "".join(f'<div><span class="lbl">Top {n}</span>{pct(c[f"top{n}_share"], 2)}</div>' for n in (1, 5, 10, 20))
            + f'<div><span class="lbl">Gini</span>{gi}</div><div><span class="lbl">Median</span><span class="num">{num(h["median"])}</span></div></div>')
    unl = V3.unlock_chart(); cal = V3.unlock_calendar(nrows=12)
    return (fg + KIT.split('<span class="lbl">Minted vs burned</span>' + mb, '<span class="lbl">Circulating</span>' + unl)
            + KIT.split('<span class="lbl">Unlock calendar</span>' + cal, '<span class="lbl">Concentration</span>' + conc))

# ---------------- page ----------------
def module(tab, qs):
    if tab == "charts": body = charts_body(qs); tools = ""
    elif tab == "anchors": body = events_body(qs); tools = ""
    elif tab == "token": body = token_body(); tools = ""
    else:
        view = (qs.get("view") or [""])[0]; view = view if view == "details" else ""
        body = health_body(view)
        tools = (f'<a href="/network" class="chip {"" if view else "on"}" data-kit-sub="feeds">Feeds</a>'
                 f'<a href="/network?view=details" class="chip {"on" if view else ""}" data-kit-sub="details">Details</a>')
    tabs = [(k, h, t, None) for k, h, t in TABS]
    return KIT.tabmod(tabs, tab, body, tools, id="netmod", label="Network")

def page(tab, qs):
    V = _V(); tab = ALIAS.get(tab, tab); tab = tab if tab in dict((k, 0) for k, _, _ in TABS) else "health"
    title = {"health": "Network", "charts": "Network charts", "anchors": "Network events", "token": "POA token"}[tab]
    body = f'<div class="sechead"><h1 class="sr-only">Network</h1></div>{hero()}{module(tab, qs)}'
    return V.page(title, body, "/network", head=head())
