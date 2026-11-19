"""The epoch story (top of /epoch/N): one card that reads a closed epoch in order. Answers and grades per hour (archived
txs: challenge txs tagged with the epoch, grade and grade-sealed txs inside its window), then the close: settled answers,
paid Agents and Established changes from the close row. POAScan's own archive only, no upstream read. A step without data
is left out. Built once per closed epoch and kept for STORY_TTL seconds (late archived txs land on the next build)."""
import re, threading, time
from . import db, segments as SG
from .ui import bars, card, intc, lt, E

STORY_TTL = 900
GRADE_TYPES = ("grade", "grade-sealed")
_cache = {}; _lock = threading.Lock()

def data(n, r, open_ts):
    """Answers and grades per hour since the open for closed epoch n (r: its epoch row, open_ts: the close before it, or None)."""
    seg = SG.selected(); key = (seg, n); now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < STORY_TTL: return hit[1]
    close_ts = int(r["close_ts"])
    start = int(open_ts) if open_ts else None
    # answers are read in a bounded time range around the epoch (an index range, not every answer of the segment)
    lo, hi = (start or close_ts - 86400) - 3600, close_ts + 7200
    if not start:   # the first close of a segment: from its first answer
        x = db.q1("SELECT MIN(ts) AS m FROM txs WHERE segment=? AND type='challenge' AND ts >= ? AND ts <= ? AND epoch=?", (seg, lo, hi, n)); start = x and x["m"]
    tot = db.q1("SELECT COUNT(*) AS c FROM txs WHERE segment=? AND type='challenge' AND ts >= ? AND ts <= ? AND epoch=?", (seg, lo, hi, n))["c"]
    hrs, a, g = [], {}, {}
    if start and close_ts > start:
        # hourly bins from the open (not clock hours); a last bin under 30 minutes joins the one before it
        span = close_ts - start; nb = max(1, span // 3600 + (1 if span % 3600 >= 1800 else 0)); nb = min(nb, 24)
        bin_of = lambda b: min(int(b), nb - 1)
        for x in db.q("SELECT (ts - ?) / 3600 AS b, COUNT(*) AS c FROM txs WHERE segment=? AND type='challenge' AND epoch=? AND ts >= ? AND ts <= ? GROUP BY b",
                      (start, seg, n, start, close_ts)):
            a[bin_of(x["b"])] = a.get(bin_of(x["b"]), 0) + int(x["c"])
        ph = ",".join("?" * len(GRADE_TYPES))
        for x in db.q(f"SELECT (ts - ?) / 3600 AS b, COUNT(*) AS c FROM txs WHERE segment=? AND type IN ({ph}) AND ts >= ? AND ts <= ? GROUP BY b",
                      (start, seg, *GRADE_TYPES, start, close_ts)):
            g[bin_of(x["b"])] = g.get(bin_of(x["b"]), 0) + int(x["c"])
        if a or g: hrs = [(start + k * 3600, a.get(k, 0), g.get(k, 0)) for k in range(nb)]
    d = dict(open_ts=int(open_ts) if open_ts else None, close_ts=close_ts, hours=hrs, answers=int(tot or 0), grades=sum(g.values()))
    with _lock:
        _cache[key] = (now, d)
        if len(_cache) > 256: _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
    return d

def _step(label, value, tip="", cls=""):
    t = (f' class="{cls}"' if cls else "") + (f' title="{E(tip)}"' if tip else "")
    return f'<li{t}><span class="esl">{label}</span><b>{value}</b></li>'

def _chart(d):
    hrs = d["hours"]
    ch = (bars([(time.strftime("%H:%M UTC", time.gmtime(t)), [x, y], t) for t, x, y in hrs], legend=["Answers", "Grades"],
               colors=("gold", "ember"), xk="t", stacked=False, head=False) if len(hrs) >= 2 else "")
    if ch:   # every other hour label hides on a phone (style.css), so the times never run together
        k = iter(range(10 ** 6)); ch = re.sub(r'class="xl ', lambda m: 'class="xl xo ' if next(k) % 2 else m.group(0), ch)
    return ch

def chart_html(n, r, open_ts):
    """Answers and grades per hour as a bare chart (the epoch hero's right side), empty when the archive has nothing for the epoch."""
    try: return _chart(data(n, r, open_ts))
    except Exception: return ""

def card_html(n, r, open_ts):
    try: d = data(n, r, open_ts)
    except Exception: return ""   # the story is extra: a failed read never breaks the epoch page
    steps = []
    if d["open_ts"]: steps.append(_step("Opened", lt(d["open_ts"], "dt"), cls="et"))
    if d["answers"]: steps.append(_step("Answers", intc(d["answers"])))
    if d["grades"]: steps.append(_step("Grades", intc(d["grades"])))
    steps.append(_step("Closed", lt(d["close_ts"], "dt"), cls="et"))
    sp, sf, se = r.get("settled_passed"), r.get("settled_failed"), r.get("settled_expired_no_jury")
    if r.get("settled"): steps.append(_step("Settled", intc(r["settled"]), tip=f"Passed {sp or 0:,} · failed {sf or 0:,} · expired {se or 0:,}"))
    if r.get("paid") is not None: steps.append(_step("Paid", f'{intc(r["paid"])} Agents'))
    if r.get("established"): steps.append(_step("Established", f'+{intc(r["established"])}'))
    if r.get("established_removed"): steps.append(_step("Removed", intc(r["established_removed"]), tip="Agents whose Established status ended at this close"))
    ch = _chart(d)
    return card("Story", ch + f'<ol class="estory">{"".join(steps)}</ol>', id="story")
