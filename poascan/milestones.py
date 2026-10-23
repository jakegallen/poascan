"""Network upgrade milestones (minepoa.com hardening, LabLeak post 1357) for Network > Charts.

Two sources, both public or POAScan's own:
* SEED: events already past, each verified once against POAScan's own database and mirrors (forum mirror, /api/notices
  mirror, status and networks snapshots, the hosted route check, the mining_back record). Exact times, fixed.
* Live: later events are detected from live state by the indexer job (no upstream request) and stored with the time
  POAScan first saw them, in the blob upgrade_milestones, so they survive restarts. A state flag (notice cleared,
  grading reopened, upgrade ended) is kept only once a second look at least CONFIRM_S later still shows it, so one
  odd read never adds a marker; the stored time is still the first sighting."""
import time
from . import db

BLOB = "upgrade_milestones"
CONFIRM_S = 600
POST_ID = 1357
POST = f"https://minepoa.com/lableak/#/post/{POST_ID}"
def _tx(txid): return f"/tx/{txid}"

# key, ts (UTC), label, url, source. Verified 2026-10-22 against the production database:
SEED = [
    ("begins", 1792609251, "Upgrade begins", POST, "LabLeak post 1357 created_at 2026-10-21 19:00:51 (forum mirror)"),
    ("paused", 1792609251, "Mining, grading paused", POST, "post 1357: mining and grading paths paused (forum mirror)"),
    ("notice", 1792614261, "Hardening notice", _tx("23bc1a34c81f4591046a62c29ae8f20a3f64b834df89ff8cf83861eef9c5eddb"),
     "notice 2026-10-21-hardening issued_ts (/api/notices mirror, on-ledger tx 23bc1a34)"),
    ("checkpoint", 1792704843, "Checkpoint 33,463", None, "first snapshot with checkpoint_height 33463 (/api/networks, height snaps)"),
    ("route:mining", 1792708521, "Mining responding", POST, "hosted route check: mining first open"),
    ("route:send", 1792710996, "Send responding", POST, "hosted route check: send first open"),
    ("route:swap_offer", 1792710996, "Swap offers responding", POST, "hosted route check: swap-offer first open"),
    ("route:vote", 1792710996, "Voting responding", POST, "hosted route check: vote first open"),
    ("route:export", 1792710996, "Export responding", POST, "hosted route check: export first open"),
    ("allclear", 1792711015, "All-clear", POST, "post 1357 comment 3121 by the post author, 2026-10-22 23:16:55 (forum mirror)"),
    ("grading_halted", 1792711349, "Grading still halted", POST, "post 1357 comment 3123 by the post author, 2026-10-22 23:22:29 (forum mirror)"),
    ("mining_reopened", 1792712749, "Mining reopened", POST, "official signal recorded by POAScan (mining_back_at)"),
]
SEEDED = {k for k, *_ in SEED}

# Routes the route check covers: (route id, label). A route seen open gets "<label> responding" at its first open read.
ROUTE_LABEL = {"mining": "Mining", "grading": "Grading", "send": "Send", "swap_offer": "Swap offers", "vote": "Voting", "export": "Export"}
# Chart priority when markers are grouped: the group shows its most telling label (no count suffix).
PRIORITY = ["ended", "mining_reopened", "grading_reopened", "notice_cleared", "allclear", "checkpoint", "begins", "route:mining", "grading_halted"]

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
    if n is not None and not n["active"]: out.append(("notice_cleared", "Notice cleared", None, None))
    rs = _route_since(); gn = _grading_notice_active()
    if "grading" in rs and (M.official()["routes"] or gn is False): out.append(("grading_reopened", "Grading reopened", None, None))
    try: why = M._cleared()
    except Exception: why = None
    if why:
        t = (M.back_since() or 0) + M.BACK_GRACE_S if why == "mining_back" and M.back_since() else None
        out.append(("ended", "Upgrade ends", None, t))
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

def events():
    """Every upgrade milestone, oldest first: [{key, ts, label, url, source}]."""
    out = [dict(key=k, ts=t, label=l, url=u, source=s) for k, t, l, u, s in SEED]
    for k, v in ((db.get_blob(BLOB)[0] or {}).get("events") or {}).items():
        if k not in SEEDED: out.append(dict(key=k, ts=v["ts"], label=v["label"], url=v.get("url"), source=v.get("src")))
    return sorted(out, key=lambda e: (e["ts"], e["key"]))

def group(evs, t0, t1, width=576, gap=64):
    """Chart markers for evs inside [t0, t1]: events closer than `gap` viewBox units (on a `width`-unit plot) become one
    marker at the first event's time, labelled with the group's most telling label only ("Mining reopened").
    Returns [(ts, label, url, title)], title listing every member for the hover tip."""
    span = max(1, t1 - t0); px = lambda t: width * (t - t0) / span
    evs = [e for e in evs if t0 <= e["ts"] <= t1]; groups = []
    for e in evs:
        if groups and px(e["ts"]) - px(groups[-1][0]["ts"]) < gap: groups[-1].append(e)
        else: groups.append([e])
    rank = lambda e: PRIORITY.index(e["key"]) if e["key"] in PRIORITY else len(PRIORITY)
    out = []
    for g in groups:
        top = min(g, key=rank); lab = top["label"]   # the main event name only; the title lists the group
        title = "; ".join(time.strftime("%m-%d %H:%M", time.gmtime(e["ts"])) + " " + e["label"] for e in g)
        out.append((g[0]["ts"], lab, top["url"] or next((e["url"] for e in g if e["url"]), None), title + " (UTC)"))
    return out

def job(): observe()
