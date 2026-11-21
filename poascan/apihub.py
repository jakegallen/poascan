"""API hub (consolidation step 5): one hero and one explorer module for what was a 5,800 px index of 155 endpoints.

Hero: Connect (MCP and REST URLs with copy, client chips) beside the live call lanes (24 minutes, one lane per surface), plus five KPIs.
Module: REST, MCP and Spec as tabs (kit.tabmod). REST and MCP are an explorer: a search box (as you type), group chips with counts, a list of 20
rows with paging, and a pane with the stored sample, Copy curl and Run. Run never calls a live endpoint: it replays the stored sample (6b).
Every state is a URL: /api?tab=rest&group=agents&q=epoch&sel=/api/epochs&offset=20. The list is built from openapi() and TOOLS as before.

Data: Build's 6a ring (apitel.py) feeds the live lanes, Latency p50, Success 1h, Calls 3h and the Top chip; Build's 6b samples (apisamples.py, the
same data as /api/v1/reference/samples) feed the pane. Both read in process; the lanes and the pane show an empty state until there is data."""
import os, json, time, urllib.parse
from html import escape as E
from . import kit as KIT
from .ui import *
from . import ui as _ui

PAGE = 20
BASE = "/api"
def tab_rows(base=None):
    b = base or BASE
    return [("rest", b, "REST"), ("mcp", f"{b}?tab=mcp", "MCP"), ("spec", f"{b}?tab=spec", "Spec")]
TABS = tab_rows()
HEAD = '<link rel="stylesheet" href="/static/api.css?v={}"><script src="/static/api.js?v={}" defer></script>'
LANES = [("rest", "HTTP"), ("mcp", "Tools"), ("csv", "CSV")]
FIX = os.path.join(os.path.dirname(__file__), "..", "tools", "fixtures")

def _asset_v(name):
    import hashlib
    try: return hashlib.sha256(open(os.path.join(os.path.dirname(__file__), "..", "static", name), "rb").read()).hexdigest()[:10]
    except OSError: return "0"

def _q(qs, k, d=""): return ((qs or {}).get(k) or [d])[0]

def calls_data():
    """Build's 6a ring (apitel.py, in process): per minute counts by surface for the last 24 minutes, p50, success over the last hour, calls over the
    ring's 3 h window and the top routes. None until the ring has a request (it resets on restart)."""
    try:
        from . import apitel as T
        snap = T.snapshot(60)
        if not snap.get("requests"): return None
        now_m = (int(time.time()) // 60) * 60; lanes = {k: [] for k, _ in LANES}
        with T._lock: mins = dict(T._mins)
        for m in range(now_m - 23 * 60, now_m + 60, 60):
            b = mins.get(m) or {}
            for k in lanes: lanes[k].append((b.get("surf") or {}).get(k, 0))
        return dict(per_minute=lanes, p50_ms=snap.get("p50_ms"), success_1h=snap.get("success_rate"), calls_3h=T.snapshot(T.KEEP_MIN).get("requests"),
                    top=[dict(route=t["endpoint"], count=t["count"]) for t in snap.get("top_endpoints") or []])
    except Exception:
        return None

def samples():
    """Build's 6b stored samples (apisamples.py): {path: {status, ms, body}}; a sample too large to store carries its top level keys."""
    try:
        from . import apisamples as SM
        out = {}
        for r in SM.samples().get("samples") or []:
            p = (r.get("endpoint") or "").split("?")[0]
            if r.get("status") == 200 and "sample" in r: out[p] = dict(status=200, ms=None, body=r["sample"])
            elif r.get("status") == 200: out[p] = dict(status=200, ms=None, body={"top_level_keys": r.get("top_level_keys")})
        return out
    except Exception:
        return {}

# ---------------- hero ----------------
def _lane(key, label, series):
    mx = max(series or [0]) or 1; tot = sum(series or [])
    cells = "".join(f'<i style="--h:{max(8, round(100 * v / mx))}%" class="{"on" if v else ""}" title="{v}"></i>' for v in (series or [0] * 24))
    return f'<li class="al {key}"><span class="an num">{intc(tot)}</span><span class="astrip" role="img" aria-label="{E(label)} calls per minute">{cells}</span></li>'

def hero(groups, tools):
    from . import agentapi as AG, oneclick as OC
    from .join import label
    nrest = sum(len(r) for _, _, r in groups)
    cd = calls_data(); pm = (cd or {}).get("per_minute") or {}
    l = OC.links("poascan", AG.MCP_URL); fb = OC.fallback("poascan", AG.MCP_URL)
    chips = "".join(f'<a class="chip app" href="{E(l[k])}" data-mcp="{k.replace("_", "-")}"' + (' target="_blank" rel="noopener noreferrer"' if k in OC.WEB else "")
                    + f' data-mcpcopy="{E(fb[k])}" data-app="{E(n)}">{label(n)}</a>' for k, n in OC.BUTTONS[:4])
    chips += f'<a class="chip" href="{BASE}?tab=spec" data-kit-tab="spec">Other</a>'
    url = lambda u: f'<div class="aurl"><code>{E(u.split("://", 1)[1])}</code>{copy(u)}</div>'
    conn = f'<div class="bl aconn"><span class="lbl">Connect</span>{url(AG.MCP_URL)}{url(AG.BASE + AG.API_PREFIX)}<div class="achips">{chips}</div></div>'
    leg = "".join(f'<span><i class="sw {k}"></i>{n}</span>' for k, n in LANES)
    if pm:
        lanes = '<ul class="alanes">' + "".join(_lane(k, n, pm.get(k) or []) for k, n in LANES) + "</ul>"
        axis = '<div class="aaxis"><span>24m</span><span>12m</span><span>now</span></div>'
        live = '<i class="ldot" aria-hidden="true"></i><span class="lbl on">Live</span><span class="lbl">Last 24 min</span>'
    else:
        lanes = na("No call counts yet."); axis = ""; live = '<span class="lbl">Last 24 min</span>'
    right = f'<div class="br"><div class="bh">{live}<span class="legend">{leg if pm else ""}</span></div>{lanes}{axis}</div>'
    c24 = (cd or {}).get("calls_3h"); p50 = (cd or {}).get("p50_ms"); ok = (cd or {}).get("success_1h")
    tot = [sum(x) for x in zip(*[pm.get(k) or [0] * 24 for k, _ in LANES])] if pm else None
    cards = [KIT.kpi("Endpoints", intc(nrest)), KIT.kpi("MCP tools", intc(len(tools))),
             KIT.kpi("Latency p50", f'<span class="num">{int(p50):,} ms</span>' if p50 is not None else "···"),
             KIT.kpi("Success 1h", f'<span class="num">{100 * float(ok):.1f}%</span>' if ok is not None else "···"),
             KIT.kpi("Calls 3h", f'<span class="num">{compact(c24)}</span>' if c24 is not None else "···", [(i, v) for i, v in enumerate(tot)] if tot else None)]
    strip = f'<section class="stats four kpis five" role="group" aria-label="Headline numbers">{"".join(cards)}</section>'
    return f'<section id="tracker" class="card benchc hpulse apihero" aria-label="API"><div class="bench abench">{conn}{right}</div>{strip}</section>'

# ---------------- explorer ----------------
def _grouped(groups):
    out = {}; order = []
    for a, t, rows in groups:
        if t not in out: out[t] = []; order.append(t)
        out[t] += rows
    return order, out

def _u(**o):
    keep = [(k, v) for k, v in o.items() if v not in ("", None, 0)]
    return BASE + ("?" + "&amp;".join(f"{k}={urllib.parse.quote(str(v), safe='/{}')}" for k, v in keep) if keep else "")

def _pager(total, off, mk):
    if total <= PAGE: return ""
    prev = f'<a class="chip" href="{mk(max(0, off - PAGE))}" data-aj>Prev</a>' if off > 0 else ""
    nxt = f'<a class="chip" href="{mk(off + PAGE)}" data-aj>Next</a>' if off + PAGE < total else ""
    return f'<div class="chips gpager">{prev}<span class="dim small num">{off + 1:,} to {min(total, off + PAGE):,} of {total:,}</span>{nxt}</div>'

def _json_text(body, lines=22):
    t = json.dumps(body, indent=1, ensure_ascii=False) if not isinstance(body, str) else body
    ls = t.splitlines()
    return "\n".join(ls[:lines]) + ("\n..." if len(ls) > lines else "")

def _pane(kind, name, method, curl, sample, run, call=None, args=None, ran=False):
    head = (f'<div class="aph"><span class="tag">{E(method)}</span><span class="aphs"></span>'
            f'<button class="chip acurl" type="button" data-copy="{E(curl)}">Copy curl</button></div>')
    if sample is not None:
        st = sample.get("status", 200) if isinstance(sample, dict) else 200; ms = sample.get("ms") if isinstance(sample, dict) else None
        body = sample.get("body") if isinstance(sample, dict) and "body" in sample else sample
        pre = f'<pre class="apip" tabindex="0" data-sample>{E(_json_text(body))}</pre>'
        chip = f'<span class="chip astat{" on" if ran else ""}" data-status><i class="sd ok"></i>{int(st)}{f" · {int(ms)} ms" if ms is not None else ""}</span>'
        foot = f'<div class="apf"><a class="chip arun" href="{E(run)}" data-run>Run</a>{chip}</div>'
    else:
        pre = na("No stored sample yet."); foot = ""
    if call is not None:
        pre = f'<pre class="apip" tabindex="0">{E(call)}</pre>'
        foot = (f'<div class="apf"><span class="dim small">{E(args)}</span></div>' if args else "")
    return f'<div class="apane" data-apane>{head}{pre}{foot}</div>'

def rest_body(qs, groups):
    from . import agentapi as AG
    order, g = _grouped(groups); smp = samples(); cd = calls_data()
    q = _q(qs, "q").strip()[:60].lower(); grp = _q(qs, "group"); top = [t["route"] for t in ((cd or {}).get("top") or [])][:5]
    tr = [r for _, _, rs in groups for r in rs if r[1] in top] if top else []
    if tr: order = order + ["Top"]; g["Top"] = tr
    grp = grp if grp in order else order[0]
    pool = [r for t in order if t != "Top" for r in g[t]] if q else g[grp]
    rows = [r for r in pool if not q or q in r[1].lower() or q in (r[2] or "").lower()]
    try: off = max(0, int(_q(qs, "offset", "0")))
    except ValueError: off = 0
    sel = _q(qs, "sel"); cur = next((r for r in rows if r[1] == sel), None) or (rows[off] if rows[off:] else None)
    mk = lambda **o: _u(**dict(dict(group=grp if grp != order[0] else "", q=q, sel="", offset=""), **o))
    chips = "".join(f'<a class="chip {"on" if t == grp and not q else ""}" href="{mk(group=t if t != order[0] else "", q="")}" data-aj>{E(t)} <span class="dim">{len(g[t]):,}</span></a>' for t in order)
    lst = "".join(f'<li><a class="arow {"on" if cur and r[1] == cur[1] else ""}" href="{mk(sel=r[1], offset=off or "")}" data-aj data-asel>'
                  + (f'<span class="tag">{E(r[0])}</span>' if r[0] != "GET" else "") + f'<code>{E(r[1])}</code></a></li>' for r in rows[off:off + PAGE])
    if not rows: lst_html = na("Nothing matches.")
    else: lst_html = f'<ul class="alist">{lst}</ul>' + _pager(len(rows), off, lambda o: mk(offset=o or ""))
    if cur:
        url = AG.BASE + (cur[3] or cur[1]); run = _u(group=grp if grp != order[0] else "", q=q, sel=cur[1], offset=off or "", run="1")
        pane = _pane("rest", cur[1], cur[0], f"curl -s '{url}'", smp.get(cur[1]), run, None, ran=_q(qs, "run") == "1") if cur[0] == "GET" else _pane("rest", cur[1], cur[0], f"curl -s -X {cur[0]} '{url}'", None, "")
    else: pane = '<div class="apane" data-apane></div>'
    form = (f'<form class="aq" role="search" method="get" action="{BASE}"><input type="hidden" name="tab" value="rest">'
            f'<input type="search" name="q" value="{E(q)}" placeholder="Find an endpoint" aria-label="Find an endpoint" autocomplete="off" data-aq></form>')
    return form + f'<div class="ares" data-ares><nav class="chips kit-sub scroll" aria-label="Group">{chips}</nav>' + KIT.split(lst_html, pane) + "</div>"

def mcp_body(qs, tools):
    from . import agentapi as AG
    q = _q(qs, "q").strip()[:60].lower()
    rows = [t for t in tools if not q or q in t[0].lower() or q in (t[1] or "").lower() or q in (t[2] or "").lower()]
    try: off = max(0, int(_q(qs, "offset", "0")))
    except ValueError: off = 0
    sel = _q(qs, "sel"); cur = next((t for t in rows if t[0] == sel), None) or (rows[off] if rows[off:] else None)
    mk = lambda **o: _u(**dict(dict(tab="mcp", q=q, sel="", offset=""), **o))
    lst = "".join(f'<li><a class="arow {"on" if cur and t[0] == cur[0] else ""}" href="{mk(sel=t[0], offset=off or "")}" data-aj data-asel><code>{E(t[0])}</code></a></li>' for t in rows[off:off + PAGE])
    lst_html = (f'<ul class="alist">{lst}</ul>' + _pager(len(rows), off, lambda o: mk(offset=o or ""))) if rows else na("Nothing matches.")
    if cur:
        name, _, _, schema, _ = cur
        call = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {}}}, indent=2)
        props = sorted((schema or {}).get("properties") or {}); req = (schema or {}).get("required") or []
        args = ("Arguments: " + ", ".join(props) + (f". Required: {', '.join(req)}" if req else "")) if props else ""
        pane = _pane("mcp", name, "tools/call", f"curl -s {AG.MCP_URL} -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d '{json.dumps(json.loads(call))}'", None, "", call, args)
    else: pane = '<div class="apane" data-apane></div>'
    form = (f'<form class="aq" role="search" method="get" action="{BASE}"><input type="hidden" name="tab" value="mcp">'
            f'<input type="search" name="q" value="{E(q)}" placeholder="Find a tool" aria-label="Find a tool" autocomplete="off" data-aq></form>')
    return form + '<div class="ares" data-ares>' + KIT.split(lst_html, pane) + "</div>"

def spec_body():
    from . import agentapi as AG, oneclick as OC
    l = OC.links("poascan", AG.MCP_URL); fb = OC.fallback("poascan", AG.MCP_URL)
    docs = [("openapi.json", "/openapi.json"), ("llms.txt", "/llms.txt"), ("mcp.json", "/.well-known/mcp.json"), ("Interactive reference", "/api/reference")]
    dl = "".join(f'<li><a href="{h}">{E(t)}</a><code>{E(AG.BASE + h)}</code>{copy(AG.BASE + h)}</li>' for t, h in docs)
    snip = json.dumps({"mcpServers": {"poascan": {"url": AG.MCP_URL}}}, indent=2)
    from .join import label
    cl = "".join(f'<li><span>{label(n)}</span><code>{E(l[k])[:60]}</code>{copy(l[k])}</li>' for k, n in OC.COPY)
    lim = '<p class="dim small">Read-only, no keys. Cache and poll at most once a minute. More than 20 requests in 10 s returns 429.</p>'
    return (KIT.split('<span class="lbl">Config</span>' + f'<pre class="apip" tabindex="0">{E(snip)}</pre>' + copy(snip) + lim,
                      '<span class="lbl">Docs</span>' + f'<ul class="aspec">{dl}</ul>')
            + '<span class="lbl">Clients</span>' + f'<ul class="aspec clients">{cl}</ul>')

def page(qs, page_fn):
    from . import agentapi as AG
    qs = qs or {}; tab = _q(qs, "tab"); tab = tab if tab in ("rest", "mcp", "spec") else "rest"
    groups = AG.api_groups(); tools = AG.TOOLS
    body = (tab == "mcp" and mcp_body(qs, tools)) or (tab == "spec" and spec_body()) or rest_body(qs, groups)
    mod = KIT.tabmod([(k, h, t, None) for k, h, t in tab_rows()], tab, body, "", id="apimod", label="Reference")
    return page_fn("API", f'<div class="sechead"><h1 class="sr-only">API</h1></div>{hero(groups, tools)}{mod}', BASE, head=HEAD.format(_asset_v("api.css"), _asset_v("api.js")))
