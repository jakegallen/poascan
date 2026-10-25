"""Network upgrade milestones (minepoa.com hardening, LabLeak post 1357, the genesis cut) for every time chart.
Each event names the charts whose data it affects (milestones.json "charts"); events(chart=...) returns only those, so a
marker never lands on an unrelated chart. The Milestones table on Network > Charts lists every event.

Two sources, both public or POAScan's own:
* SEED: events already past, each verified once against POAScan's own database and mirrors (forum mirror, /api/notices
  mirror, status and networks snapshots, the hosted route check, the mining_back record). Exact times, fixed.
* Live: later events are detected from live state by the indexer job (no upstream request) and stored with the time
  POAScan first saw them, in the blob upgrade_milestones, so they survive restarts. A state flag (notice cleared,
  grading reopened, upgrade ended) is kept only once a second look at least CONFIRM_S later still shows it, so one
  odd read never adds a marker; the stored time is still the first sighting."""
import json, os, time
from . import db

BLOB = "upgrade_milestones"
CONFIRM_S = 600
POST_ID = 1357
POST = f"https://minepoa.com/lableak/#/post/{POST_ID}"
def _tx(txid): return f"/tx/{txid}"
DONE_TX = "a241efae5b315b9f4dfdd4030990321d3d794cf800acdb76932029c6be267000"   # notice 2026-10-23-grading-resumed

# The verified events, their plain labels and the charts each one belongs on live in milestones.json (config, not code).
CONFIG_PATH = os.environ.get("POASCAN_MILESTONES_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "milestones.json")
with open(CONFIG_PATH, encoding="utf-8") as _f: CFG = json.load(_f)
CHART_IDS = tuple(CFG["chart_ids"])
GROUPS = {k: tuple(v) for k, v in CFG["groups"].items()}

def _url(u):
    if not u: return None
    if u.startswith("post:"): return f"https://minepoa.com/lableak/#/post/{int(u[5:])}"
    if u.startswith("tx:"): return _tx(u[3:])
    return u

def expand(charts):
    """Chart ids for a relevance list of chart ids and group names (unknown names raise: the config test catches them)."""
    out = []
    for c in charts or ():
        for x in (GROUPS[c] if c in GROUPS else (c,)):
            if x not in CHART_IDS: raise ValueError(f"milestones.json: unknown chart {x}")
            if x not in out: out.append(x)
    return tuple(out)

# key, ts (UTC), label, url, source
SEED = [(e["key"], int(e["ts"]), e["label"], _url(e.get("url")), e["source"]) for e in CFG["events"]]
RELEVANT = {e["key"]: expand(e.get("charts")) for e in CFG["events"]}
CHART_LABELS = {e["key"]: dict(e["chart_labels"]) for e in CFG["events"] if e.get("chart_labels")}
# Segment boundaries (segments.json): one milestone per cut, linked to its notice tx when the config names one.
from . import segments as _SG
for _c in _SG.cuts():
    _k = "genesis_cut" if _c["segment"] == 2 else f"genesis_cut_s{_c['segment']}"
    SEED.append((_k, _c["ts"], _c["label"], _tx(_c["txid"]) if _c.get("txid") else None,
                 f"segments.json: {_c['label']} at the start of segment {_c['segment']}" + (f" (notice {_c['notice_id']})" if _c.get("notice_id") else "")))
    RELEVANT[_k] = expand(CFG.get("cut_charts") or ["chain"])
SEEDED = {k for k, *_ in SEED}
# Keys that always get their own marker (never folded into a nearby group), so each real event stays labelled.
SOLO = {"begins", "allclear", "grading_reopened", "ended", "genesis_cut", "s2_mining_reopened", "s2_first_join"} | {k for k, *_ in SEED if k.startswith("genesis_cut")}

def charts_of(key):
    """The chart ids a milestone is drawn on (seeded: milestones.json; live: live_charts, route_charts; else none)."""
    if key in RELEVANT: return RELEVANT[key]
    if key in (CFG.get("live_charts") or {}): return expand(CFG["live_charts"][key])
    if key.startswith("route:"): return expand(CFG.get("route_charts") or [])
    return ()

# Routes the route check covers: (route id, label). A route seen open gets "<label> responding" at its first open read.
ROUTE_LABEL = {"mining": "Mining", "grading": "Grading", "send": "Send", "swap_offer": "Swap offers", "vote": "Voting", "export": "Export"}
# Chart priority when markers are grouped: the group shows its most telling label (no count suffix).
PRIORITY = ["genesis_cut", "s2_mining_reopened", "s2_first_join", "ended", "grading_reopened", "allclear", "mining_reopened", "notice_cleared", "checkpoint", "begins", "route:mining", "grading_halted"]

def _route_since():
    """{route: since} for routes whose newest route-check read is open (POAScan's own hosted_routes record)."""
    d = (db.get_blob("hosted_routes")[0] or {}).get("routes") or {}
    return {k: v.get("since") for k, v in d.items() if isinstance(v, dict) and v.get("state") == "open" and v.get("since")}

def _grading_notice_active():
    d = db.get_blob("notices")[0]
    if not isinstance(d, dict): return None
    return any("grading" in str(x.get("id", "")).lower() for x in d.get("active") or [] if isinstance(x, dict))

def _flags():
    """(key, label, url, exact ts or None) for upgrade state flags that hold right now."""
    from . import maint as M
    out = []
    n = M.notice()
    # a hardening notice superseded by the completion notice is not 'cleared': 'Upgrade complete' already marks that
    if n is not None and not n["active"] and not n.get("superseded_by"): out.append(("notice_cleared", "Notice cleared", None, None))
    rs = _route_since(); gn = _grading_notice_active()
    if "grading" in rs and (M.official()["routes"] or gn is False): out.append(("grading_reopened", "Grading reopened", None, None))
    try: why = M._cleared()
    except Exception: why = None
    if why:
        c = M.complete() if why == "upgrade_complete" else None
        t = c["at"] if c else (M.back_since() or 0) + M.BACK_GRACE_S if why == "mining_back" and M.back_since() else None
        out.append(("ended", "Upgrade complete", _tx(c["txid"]) if c and c.get("txid") else None, t))
    return out

def observe(now=None):
    """Add newly seen upgrade events to the stored list. Called by the indexer job; reads only POAScan's own data."""
    now = int(now or time.time())
    st = db.get_blob(BLOB)[0] or {}; ev = dict(st.get("events") or {}); pend = dict(st.get("pending") or {}); changed = False
    for rid, since in _route_since().items():   # a route answering again: its first open read (never moved later)
        k = "route:" + rid
        if k in SEEDED or k in ev or rid not in ROUTE_LABEL: continue
        ev[k] = dict(ts=int(since), label=ROUTE_LABEL[rid] + " responding", url=POST, src="hosted route check"); changed = True
    try:
        from . import maint as M
        b = M.back_since()
        if b and "mining_reopened" not in SEEDED | set(ev):
            ev["mining_reopened"] = dict(ts=int(b), label="Mining reopened", url=POST, src="official signal (mining_back_at)"); changed = True
        holding = {k for k, *_ in _flags()}
        for k, lab, url, exact in _flags():
            if k in ev or k in SEEDED: continue
            p = pend.get(k)
            if not p: pend[k] = dict(ts=exact or now, seen=now, label=lab, url=url); changed = True
            elif now - p["seen"] >= CONFIRM_S:
                ev[k] = dict(ts=int(p["ts"]), label=lab, url=url, src="live state, first seen by POAScan"); pend.pop(k, None); changed = True
        for k in [k for k in pend if k not in holding]: pend.pop(k, None); changed = True
    except Exception:
        pass
    if changed: db.put_blob(BLOB, dict(events=ev, pending=pend))
    return ev

def events(chart=None):
    """Every upgrade milestone, oldest first: [{key, ts, label, url, source, charts}]. chart: only those drawn on that chart
    (milestones.json relevance), for chart markers; without it, every event (the Milestones table, signed badges)."""
    out = [dict(key=k, ts=t, label=l, url=u, source=s, charts=charts_of(k)) for k, t, l, u, s in SEED]
    for k, v in ((db.get_blob(BLOB)[0] or {}).get("events") or {}).items():
        if k not in SEEDED: out.append(dict(key=k, ts=v["ts"], label=v["label"], url=v.get("url"), source=v.get("src"), charts=charts_of(k)))
    if chart is not None: out = [dict(e, label=CHART_LABELS.get(e["key"], {}).get(chart, e["label"])) for e in out if chart in e["charts"]]
    return sorted(out, key=lambda e: (e["ts"], e["key"]))

def group(evs, t0, t1, width=576, gap=64):
    """Chart markers for evs inside [t0, t1]: events closer than `gap` viewBox units (on a `width`-unit plot) become one
    marker at the first event's time, labelled with the group's most telling label only ("Mining reopened").
    Returns [(ts, label, url, title)], title listing every member for the hover tip."""
    span = max(1, t1 - t0); px = lambda t: width * (t - t0) / span
    evs = [e for e in evs if t0 <= e["ts"] <= t1]; groups = []
    for e in evs:
        if groups and e["key"] not in SOLO and px(e["ts"]) - px(groups[-1][0]["ts"]) < gap: groups[-1].append(e)
        else: groups.append([e])
    rank = lambda e: PRIORITY.index(e["key"]) if e["key"] in PRIORITY else len(PRIORITY)
    out = []
    for g in groups:
        top = min(g, key=rank); lab = top["label"]   # the main event name only; the title lists the group
        title = "; ".join(time.strftime("%m-%d %H:%M", time.gmtime(e["ts"])) + " " + e["label"] for e in g)
        out.append((g[0]["ts"], lab, top["url"] or next((e["url"] for e in g if e["url"]), None), title + " (UTC)"))
    return out

def job(): observe()
