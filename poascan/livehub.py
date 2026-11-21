"""Live hub: one page for chain activity, network health and the API explorer.

Reached from the header status pill (no Live nav item). Option A: both 24-minute boards and the
network routes board sit in the hero; REST, MCP, Spec and Feeds are the module underneath.
Humans get the visualized numbers first; the explorer is for agents and developers.

Home and Agents keep their own chain strip. Charts, Anchors and Token stay under Network.
JSON /api/v1/* and MCP are unchanged. /api/reference stays standalone."""
import time, urllib.parse
from html import escape as E
from . import kit as KIT, apihub as AH, bench as B, govhub as GH, analytics as A, db
from .ui import *

PATH = "/live"
LANES = AH.LANES

def _asset_head():
    from . import nethub as NH
    api = AH.HEAD.format(AH._asset_v("api.css"), AH._asset_v("api.js"))
    return api + NH.head()

def _q(qs, k, d=""):
    return AH._q(qs, k, d)

def _feed(now):
    from . import views as V
    return [dict(type=r["type"], addr=r["from_addr"], name=V.names().get(r["from_addr"]), ts=int(r["ts"] or 0))
            for r in db.q("SELECT type, from_addr, ts FROM txs WHERE type IN ('challenge','attest-batch','grade-sealed','join') ORDER BY ts DESC LIMIT 8")]

def _calls_panel():
    cd = AH.calls_data(); pm = (cd or {}).get("per_minute") or {}
    empty = not pm
    lanes = '<ul class="alanes">' + "".join(AH._lane(k, n, (pm or {}).get(k) or [0] * 24) for k, n in LANES) + "</ul>"
    axis = '<div class="aaxis"><span>24m</span><span>12m</span><span>now</span></div>'
    note = AH.na("No counts in this window.") if empty else ""
    return lanes + axis + note

def _chain_panel(now, feed):
    return B.score_html(now, B.ticker_html(feed, now))

def _activity_pair(now, feed):
    leg_c = "".join(f'<span><i class="sw {k}"></i>{n}</span>' for n, k in (("Answer", "a"), ("Attest", "t"), ("Seal", "s")))
    leg_a = "".join(f'<span><i class="sw {k}"></i>{n}</span>' for k, n in LANES)
    return (
        f'<div class="lpair">'
        f'<div class="lpk"><div class="bh"><span class="legend">{leg_c}</span></div>{_chain_panel(now, feed)}</div>'
        f'<div class="lpk lcalls"><div class="bh"><span class="legend">{leg_a}</span></div>{_calls_panel()}</div>'
        f'</div>'
    )

def _routes_panel(now):
    """Network routes and the last-hour strip, without the word Live (the header pill already says it)."""
    from . import nethub as NH
    eta = A.anchor_eta()
    nxt = eta.get("next_anchor_eta"); cad = eta.get("cadence_s")
    nx = ("due" if nxt <= now else NH.short_age(nxt - now)) if nxt else "···"
    figs = ('<div class="trio">'
            f'<div><span class="lbl">Next</span><b class="num" data-anext="{int(nxt or 0)}">{nx}</b></div>'
            f'<div><span class="lbl">Cadence</span><b class="num">{NH.short_age(cad) if cad else "···"}</b></div>'
            f'<div><span class="lbl">Anchored</span><b class="num">{intc(eta.get("anchors_in_window"))}</b></div></div>')
    halted, rl = NH.routes_strip(now)
    leg = "".join(f'<span><i class="sw {k}"></i>{n}</span>' for n, k in (("Open", "o"), ("Halted", "h"), ("Down", "d")))
    return (f'<div class="bench nbench lnet"><div class="bl">{NH.anchor_ring(eta, now)}{figs}</div>'
            f'<div class="br"><div class="bh"><i class="ldot" aria-hidden="true"></i><span class="lbl">Routes · 24h</span>'
            f'<span class="legend">{leg}</span></div>{rl}{NH.minute_strip(now)}</div></div>')

def _kpis(groups, tools, now):
    from . import views2 as V2
    try: sd = V2.status_data()
    except Exception: sd = dict(eps=[], inc=[], lag=[], lat=[], anchors=[])
    cd = AH.calls_data(); pm = (cd or {}).get("per_minute") or {}
    o = A.open_epoch() or {}
    submitted = o.get("answers")
    if submitted is None: submitted = o.get("answers_so_far")
    nw = A.networks()
    h = nw.get("height"); fin = nw.get("checkpoint_height")
    from . import nethub as NH
    cp = NH.checkpoint_lag(nw, A.status())
    lag = cp["lag"] if cp.get("lag") is not None else ((h - fin) if (h and fin) else None)
    behind = flag("Behind", f"{cp['lag']:,} blocks ahead of the checkpoint") if cp.get("behind") else ""
    p50 = (cd or {}).get("p50_ms")
    tot = [sum(x) for x in zip(*[pm.get(k) or [0] * 24 for k, _ in LANES])] if pm else None
    calls = (cd or {}).get("calls_3h")
    fmtc = lambda v: compact(v) if v is not None else "···"
    return "".join([
        KIT.kpi("Height", f'<span class="num">{fmtc(h)}</span>', NH.height_series(now)),
        KIT.kpi("Finalized", f'<span class="num">{fmtc(fin)}</span>' + V2.cp_flag()),
        KIT.spark_in(stat("Lag", f'<span class="num">{intc(lag)}</span>' if lag is not None else "···",
                          tip="Blocks between the chain height and the finalized height", flag_html=behind),
                     [(t, v) for t, v in (sd.get("lag") or []) if t > now - 86400]),
        KIT.kpi("Submitted", f'<span class="num">{intc(submitted)}</span>' if submitted is not None else "···"),
        KIT.kpi("Serving", f'<span class="num">{int(p50):,} ms</span>' if p50 is not None else "···"),
        KIT.kpi("Calls", f'<span class="num">{compact(calls)}</span>' if calls is not None else "···",
                [(i, v) for i, v in enumerate(tot)] if tot else None),
    ])

def _connect():
    from . import agentapi as AG, oneclick as OC
    from .join import label
    l = OC.links("poascan", AG.MCP_URL); fb = OC.fallback("poascan", AG.MCP_URL)
    chips = "".join(
        f'<a class="chip app" href="{E(l[k])}" data-mcp="{k.replace("_", "-")}"'
        + (' target="_blank" rel="noopener noreferrer"' if k in OC.WEB else "")
        + f' data-mcpcopy="{E(fb[k])}" data-app="{E(n)}">{label(n)}</a>'
        for k, n in OC.BUTTONS[:4])
    chips += f'<a class="chip" href="{PATH}?tab=spec" data-kit-tab="spec">Other</a>'
    url = lambda u: f'<div class="aurl"><code>{E(u.split("://", 1)[1])}</code>{copy(u)}</div>'
    return (f'<div class="lconnect"><span class="lbl">Connect</span>'
            f'{url(AG.MCP_URL)}{url(AG.BASE + AG.API_PREFIX)}<div class="achips">{chips}</div></div>')

def _hero(now, feed, groups, tools):
    head = '<div class="bh"><i class="ldot" aria-hidden="true"></i><span class="lbl">Last 24 min</span></div>'
    board = f'<div class="lboard">{head}{_activity_pair(now, feed)}</div>'
    routes = _routes_panel(now)
    strip = f'<section class="stats four kpis six" role="group" aria-label="Headline numbers">{_kpis(groups, tools, now)}</section>'
    return (f'<section id="tracker" class="card benchc hpulse lhero nethero" aria-label="Activity">'
            f'{board}{routes}{strip}{_connect()}</section>')

def _feeds_body(qs):
    from . import nethub as NH
    view = _q(qs, "view")
    view = view if view == "details" else ""
    body = NH.health_body(view)
    body = body.replace("/network?view=details", PATH + "?tab=feeds&amp;view=details").replace('href="/network"', f'href="{PATH}?tab=feeds"')
    return body

def _feeds_tools(qs):
    view = _q(qs, "view")
    on_d = view == "details"
    return (f'<a href="{PATH}?tab=feeds" class="chip {"" if on_d else "on"}" data-kit-sub="feeds">Overview</a>'
            f'<a href="{PATH}?tab=feeds&amp;view=details" class="chip {"on" if on_d else ""}" data-kit-sub="details">Details</a>')

def tabs(cur="rest"):
    return [("rest", PATH, "REST"), ("mcp", PATH + "?tab=mcp", "MCP"),
            ("spec", PATH + "?tab=spec", "Spec"), ("feeds", PATH + "?tab=feeds", "Feeds")]

def page(qs, page_fn):
    from . import agentapi as AG
    from . import nethub as NH
    qs = qs or {}
    now = time.time()
    AH.BASE = PATH
    try:
        AH._pager = lambda total, off, mk: GH.pager(total, off, mk)
        tab = _q(qs, "tab")
        tab = tab if tab in ("rest", "mcp", "spec", "feeds") else "rest"
        groups = AG.api_groups(); tools = AG.TOOLS
        feed = _feed(now)
        NH._tl.s = NH.Seen(*[t for _, _, t in tabs()], "Last 24 min", "Since", "Next", "Cadence",
                           "Anchored", "Routes", "Probes", "Open", "Halted", "Down", "Overview", "Details",
                           "Height", "Finalized", "Submitted", "Lag", "Serving", "Calls", "Connect", "Answer", "Attest",
                           "Seal", "HTTP", "Tools", "CSV")
        if tab == "mcp":
            body, tool = AH.mcp_body(qs, tools), ""
        elif tab == "spec":
            body, tool = AH.spec_body(), ""
        elif tab == "feeds":
            body, tool = _feeds_body(qs), _feeds_tools(qs)
        else:
            body, tool = AH.rest_body(qs, groups), ""
        from . import views as V, views2 as V2
        hero = _hero(now, feed, groups, tools)
        mod = KIT.tabmod([(k, h, t, None) for k, h, t in tabs()], tab, body, tool, id="livemod", label="Reference")
        html = f'<div class="sechead"><h1 class="sr-only">Live</h1></div>{V2.upgrade_line()}{V.cut_note()}{hero}{mod}'
        return page_fn("Live", html, PATH, head=_asset_head())
    finally:
        AH.BASE = "/api"
