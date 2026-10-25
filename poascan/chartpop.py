"""Chart pop-out data (app.js opens it from any stat or chart card that has a chart; ?chart=<key>&range=<range> opens it on load).

GET /fragment/chart?c=<key>&r=<range>&w=<plot px>: JSON for one chart over one range, built from POAScan's own archive only
(the same series the home sparklines and Network > Charts draw; no upstream request). Every chart offers all four time ranges
(24h, 7d, 30d, All) plus Epoch where the data is per epoch. When the history is shorter than a range, that range shows all of it
(no error, no empty state, no padding: a window never starts before the first real point). Upgrade milestones (milestones.py) are
grouped with milestones.group at the reader's plot width, so the big chart uses the same grouping as Network > Charts."""
import time
from . import analytics as A, db

DAY = 86400
TIME_RANGES = ("24h", "7d", "30d", "all")
RANGES = TIME_RANGES + ("epoch",)
SPAN = {"24h": DAY, "7d": 7 * DAY, "30d": 30 * DAY, "all": None}
MAX_PTS = 720
W_MIN, W_MAX = 200, 2400

# key: title, kind (line on a time axis; bars per epoch), unit, value format (int | c), color, y from zero, has an Epoch view, marks
CHARTS = {
    "mined":   dict(title="Total mined", unit="POA", fmt="c", color="#FFB000", y0=True, epoch=False, marks=True),
    "supply":  dict(title="Supply", unit="POA", fmt="c", color="#FFB000", y0=True, epoch=False, marks=True),
    "circ":    dict(title="Circulating supply", unit="POA", fmt="c", color="#FFB000", y0=True, epoch=True, marks=True),
    "agents":  dict(title="Agents", unit="", fmt="int", color="#FFB000", y0=False, epoch=False, marks=True),
    "joins":   dict(title="Agents / hr", unit="", fmt="int", color="#FFB000", y0=True, epoch=False, marks=True),
    "holders": dict(title="Holders (node)", unit="", fmt="int", color="#FFB000", y0=False, epoch=False, marks=True),
    "txs":     dict(title="Txs / hour", unit="", fmt="int", color="#FFB000", y0=True, epoch=False, marks=True),
    "answers": dict(title="Answers / epoch", unit="", fmt="int", color="#FFB000", y0=True, epoch=True, marks=False),
}
PARAMS = {"c", "r", "w"}

def parse(qs):
    """(key, range or '', plot width) from the query, or ValueError. Strict: known keys only, one value each, nothing else."""
    if set(qs) - PARAMS: raise ValueError("unknown parameter")
    one = lambda k: (qs.get(k) or [""]) if len(qs.get(k) or [""]) == 1 else None
    c, r, w = one("c"), one("r"), one("w")
    if c is None or r is None or w is None: raise ValueError("one value per parameter")
    c, r, w = c[0], r[0], w[0]
    if c not in CHARTS: raise ValueError("unknown chart")
    if r and r not in RANGES: raise ValueError("unknown range")
    if w and not (w.isdigit() and len(w) <= 4): raise ValueError("w is a width in px")
    w = min(W_MAX, max(W_MIN, int(w))) if w else 800
    return c, r, w // 40 * 40   # width buckets keep the cache small

def _growth():
    from . import views3 as V3
    return V3.growth_data()

def _epoch_closes():
    """(lifetime close number, close_ts) over every segment, oldest first: epoch numbers restart at a genesis cut (segments.py)."""
    from . import segments as SG
    out = []
    for n in SG.NUMBERS:
        with SG.use(n): out += [(SG.gkey(r["epoch"], n), r["close_ts"]) for r in A.epoch_rows()]
    return out

def _hourly(pts):
    """Agents / hr from the Agents series: joins in each whole hour with a reading in the hour before it, in the same segment
    (analytics.joins_series: no bucket across a genesis cut, join tx times in the current segment, the filling hour left out)."""
    now = int(time.time()); fl = A.S.CUT_TS if A.S.has_cut() and now >= A.S.CUT_TS else None
    return A.joins_series(pts, now, fl, A.seg_join_times() if fl else None)

def _daily(g, rng):
    """Txs per day for 30d and All once there are at least 3 days to draw; per hour before that."""
    return rng in ("30d", "all") and len(g["day"]) >= 3

def series(key, rng=""):
    """Time points [(ts, v)] for a line chart, or epoch bars [(epoch, close_ts, [values])] for the Epoch view and Answers."""
    g = _growth()
    if key in ("mined", "supply"): return g["supply"]
    if key == "agents": return g["agents"]
    if key == "holders": return g["holders"]
    if key == "joins": return _hourly(g["agents"])
    if key == "txs":
        if _daily(g, rng): return [(r["d"], r["n"]) for r in g["day"]]
        return [(r["h"], r["n"]) for r in g["hour"][:-1]]   # the current hour is still filling
    if key == "circ":
        from . import views3 as V3
        u = V3.unlock_data(); closes = _epoch_closes()
        if rng == "epoch": return [(e, t, [v]) for (e, t), (_, v) in zip(closes, u["past"])]
        return u["past"] + [(time.time(), u["now"])]
    if key == "answers":
        cl = dict(_epoch_closes())
        return [(k, cl.get(k) or time.time(), [a, max(0, p)]) for k, a, p in g["per_ep"]]
    raise KeyError(key)

def ranges(key, now=None):
    """Ranges this chart offers, in button order: always 24h, 7d, 30d and All once there is data, plus Epoch for per epoch data
    other than Answers (its bars are already per epoch, so All is the Epoch view). A range wider than the history shows all of it."""
    pts = series(key)
    if not pts: return []
    return list(TIME_RANGES) + (["epoch"] if CHARTS[key]["epoch"] and key != "answers" else [])

def pick(want, have):
    """The range to show: the one asked for if offered (Epoch on Answers is All), else the default 7d."""
    if want == "epoch" and "epoch" not in have and "all" in have: return "all"
    if want in have: return want
    for r in ("7d", "24h", "30d", "all", "epoch"):
        if r in have: return r
    return ""

def window(rows, t0, ts=lambda x: x[0]):
    """Rows at or after t0. If that leaves fewer than 2 (a quiet or stale series), the last real rows before t0 fill in,
    so a short range still draws a line or a bar, never an empty state. Never padded with made-up points."""
    inside = [x for x in rows if ts(x) >= t0]
    if len(inside) >= 2: return inside
    before = [x for x in rows if ts(x) < t0]
    return before[-(2 - len(inside)):] + inside if before else inside

def _thin(pts, n=MAX_PTS):
    if len(pts) <= n: return pts
    step = len(pts) / n
    return [pts[int(i * step)] for i in range(n)] + [pts[-1]]

BREAK_AT_CUT = ("agents", "holders", "joins")

@A.cached("chartpop", 60)
def payload(key, rng, w):
    cfg = CHARTS[key]; now = time.time(); have = ranges(key, now); r = pick(rng, have)
    out = dict(c=key, title=cfg["title"], unit=cfg["unit"], fmt=cfg["fmt"], color=cfg["color"], ranges=have, range=r, kind="line",
               y0=cfg["y0"], pts=[], bars=[], legend=[], colors=[], marks=[], breaks=[])
    if not r: return out
    if key == "txs" and _daily(_growth(), r): out["title"] = "Txs / day"
    if key == "answers" or r == "epoch":
        rows = series(key, "epoch")
        if SPAN.get(r): rows = window(rows, now - SPAN[r], lambda x: x[1])
        from . import segments as SG
        out.update(kind="bars", bars=[[SG.ep_label(e), int(t), [round(v, 6) for v in vals]] for e, t, vals in rows])
        if key == "answers": out.update(legend=["Answered", "Paid"], colors=["#FFB000", "#8FA3B8"])
        else: out.update(legend=[], colors=[cfg["color"]])
        return out
    pts = [(int(t), v) for t, v in series(key, r) if v is not None]
    if SPAN[r]: pts = window(pts, now - SPAN[r])
    pts = _thin(pts)
    out["pts"] = [[t, round(float(v), 6)] for t, v in pts]
    if key in BREAK_AT_CUT and len(pts) > 1:   # counters that restart at a segment boundary: no line across it (as the inline charts)
        from . import segments as SG
        out["breaks"] = [c["ts"] for c in SG.cuts() if pts[0][0] < c["ts"] <= pts[-1][0]]
    if cfg["marks"] and len(pts) > 1:
        from . import milestones as MS
        x0, x1 = pts[0][0], pts[-1][0]
        out["marks"] = [[t, l, ti] for t, l, _u, ti in MS.group(MS.events(key), x0, x1, width=max(120, w - 64))]   # only milestones that affect this chart
    return out
