"""Phase 2 (1.26.128+): the Bench, Home's hero, and the Pour card. Built from POAScan's own archive only (the txs table the
indexer already fills and analytics.open_epoch), so it adds no upstream reads.

Left: the epoch numeral, the countdown and a 72 tick bezel that fills as the epoch runs. Right: the chain in three voices over
the last 24 minutes (Answers, Attests, Seals). Marks sit in an SVG whose x unit is one second; app.js slides the mark group left
as time passes (one transform every 5 s) and refetches /fragment/score only when the live snapshot shows a new tx, so the
strip moves when the chain does and is still otherwise.

1.26.145 motion (app.js bench*): the mark groups drift with the clock on requestAnimationFrame, new marks slide in at the now
line with a short glow, the now line breathes, Answers, Graders, Pool and the lane counts roll digit by digit with a +N chip,
the bezel head glides to the current time and the last minute ticks each second, the numeral flips at a close with a one line
summary, and an activity ticker under the strip cycles the latest txs from the live snapshot. No new reads anywhere: it all
comes from the snapshot and /fragment/score the page already polls. Reduced motion keeps the static Bench."""
import math, threading, time
from . import db
from .ui import E, intc, lt, compact, dur, short, PROFILE_URL

WIN = 1440                       # 24 minutes, in seconds
TICKS = 72                       # bezel ticks
LANES = (("challenge", "Answers", "a"), ("attest-batch", "Attests", "t"), ("grade-sealed", "Seals", "s"))
_K = {t: k for t, _, k in LANES}
_lock = threading.Lock(); _cache = {"t": 0.0, "v": None}

def score_rows(now=None):
    """[[lane, ts, atts, final], ...] for the window, oldest first. Cached 10 s for everyone (one indexed range read)."""
    now = time.time() if now is None else now
    with _lock:
        if _cache["v"] is not None and now - _cache["t"] < 10: return _cache["v"]
    rows = db.q("SELECT type, ts, atts, final FROM txs WHERE ts>=? AND ts<=? AND type IN (?,?,?) ORDER BY ts LIMIT 2000",
                (int(now) - WIN - 120, int(now) + 60, *_K))
    v = [[_K[r["type"]], int(r["ts"] or 0), int(r["atts"] or 0), 1 if r["final"] else 0] for r in rows]
    with _lock: _cache.update(t=now, v=v)
    return v

def base(now=None):
    """The x origin of the mark group: the window start, on a whole minute so a page render is stable within the minute."""
    now = time.time() if now is None else now
    return int(now // 60 * 60) - WIN

def score_json():
    return dict(b=base(), win=WIN, rows=score_rows())

def _mark(k, ts, atts, final, b):
    x = ts - b
    if k == "a": return f'<line class="ma{" f" if final else ""}" x1="{x}" x2="{x}" y1="12" y2="40"/>'
    if k == "t":
        h = 6 + 30 * min(1.0, math.log(atts + 1) / math.log(51)); return f'<line class="mt" x1="{x}" x2="{x}" y1="{26 - h / 2:.1f}" y2="{26 + h / 2:.1f}"/>'
    return f'<line class="ms" x1="{x}" x2="{x}" y1="23" y2="29"/>'

# Seals arrive in bursts (dozens in one second), so the Seals lane draws clusters, not one stroke each: neighbours closer than their
# own widths plus GAP merge into one capsule at their weighted center with a count, and the newest is held inside the now line. The
# spacing is in screen pixels: app.js reruns seal_clusters at the lane's real width; the server render assumes the narrowest lane
# (NOMINAL_PX, a 390 px phone), so without JS marks are further apart than needed but never touch.
GAP, NOMINAL_PX = 4, 260
def seal_w(n):
    """A mark's width in px: a 6 px pill for one seal, a capsule that fits its count (10 px mono digits) for more."""
    return 6 if n == 1 else 12 + 6 * len(str(n))

def seal_clusters(ts, pxs, right=None):
    """[[center ts, n, first ts, last ts], ...] oldest first, for seal times `ts` at `pxs` px per second. Adjacent clusters merge
    until every pair of centers is at least (w1 + w2) / 2 + GAP px apart; `right` (a ts, the now line) pulls the newest ones back
    inside it, keeping that spacing. app.js sealCluster is the same algorithm."""
    st = []
    for t in sorted(ts):
        st.append([float(t), 1, t, t])
        while len(st) > 1 and (st[-1][0] - st[-2][0]) * pxs < (seal_w(st[-1][1]) + seal_w(st[-2][1])) / 2 + GAP:
            b, a = st.pop(), st[-1]; n = a[1] + b[1]
            st[-1] = [(a[0] * a[1] + b[0] * b[1]) / n, n, min(a[2], b[2]), max(a[3], b[3])]
    if right is not None and st:
        lim = right - (seal_w(st[-1][1]) / 2 + 1) / pxs
        for i in range(len(st) - 1, -1, -1):
            if st[i][0] <= lim: break
            st[i][0] = lim
            if i: lim -= ((seal_w(st[i][1]) + seal_w(st[i - 1][1])) / 2 + GAP) / pxs
    return st

def _hms(t):
    return time.strftime("%H:%M:%S", time.gmtime(t))

def seal_tip(c):
    """Hover text for a cluster, UTC (the no-JS fallback; app.js writes the visitor's time)."""
    n, t0, t1 = c[1], c[2], c[3]
    if n == 1: return f"Seal · {_hms(t0)} UTC"
    return f"{n} Seals · {_hms(t0)} UTC" if t0 == t1 else f"{n} Seals · {_hms(t0)} to {_hms(t1)} UTC"

def seal_layer(ts, b, lo, now):
    """The Seals lane's marks as HTML over the lane's SVG (round capsules and counts cannot sit in a stretched viewBox). data-s
    carries every seal as seconds after b (repeats as x*n) so app.js can recluster at the real width and keep the count."""
    pxs = NOMINAL_PX / WIN; out = []
    for c in seal_clusters(ts, pxs, right=now):
        if (c[0] - lo) * pxs < seal_w(c[1]) / 2: continue   # would be cut at the window's start: a mark leaves whole
        left = 100 * (c[0] - b) / WIN
        out.append(f'<i class="sm" style="left:{left:.2f}%" title="{seal_tip(c)}">{c[1] if c[1] > 1 else ""}</i>' if c[1] > 1
                   else f'<i class="sm s1" style="left:{left:.2f}%" title="{seal_tip(c)}"></i>')
    rel, runs = [t - b for t in sorted(ts)], []
    for x in rel:
        if runs and runs[-1][0] == x: runs[-1][1] += 1
        else: runs.append([x, 1])
    ds = " ".join(f"{x}*{n}" if n > 1 else str(x) for x, n in runs)
    return f'<div class="sk" data-b="{b}" data-s="{ds}" style="transform:translateX({100 * (b - lo) / WIN:.2f}%)" aria-hidden="true">{"".join(out)}</div>'

VERB = {"challenge": ("answered", "a"), "attest-batch": ("attested", "t"), "grade-sealed": ("sealed a grade", "s"), "join": ("joined", "j")}

def _ago(ts, now):
    d = max(0, int(now - ts))
    return f"{d}s ago" if d < 60 else f"{d // 60}m ago" if d < 3600 else f"{d // 3600}h ago" if d < 86400 else f"{d // 86400}d ago"

def ticker_html(items, now=None):
    """One line under the strip: the latest txs, newest first ({type, addr, name, ts}). app.js cycles them and swaps in new
    ones from each snapshot's feed; without JS the newest stays. Names link to the Agent's LabLeak profile."""
    now = time.time() if now is None else now; out = []
    for i, t in enumerate(x for x in items if x.get("type") in VERB):
        v, k = VERB[t["type"]]; a = t.get("addr") or ""
        who = E(t.get("name") or short(a, 6, 4))
        nm = (f'<a class="tkn" href="{E(PROFILE_URL.format(a))}" target="_blank" rel="noopener noreferrer" title="LabLeak profile">{who}</a>'
              if a else f'<span class="tkn">{who}</span>')
        out.append(f'<span class="tki{" on" if not i else ""}"><i class="sw {k}"></i>{nm} {v} <time class="tkt" data-ts="{int(t["ts"])}">{_ago(t["ts"], now)}</time></span>')
    body = "".join(out[:8]) or '<span class="tki on">Waiting for the next tx</span>'
    return f'<div class="btk"><span class="lbl">Latest</span><div class="btkl" id="btk" aria-live="off">{body}</div></div>'

def score_html(now=None, ticker=""):
    now = time.time() if now is None else now
    b = base(now); rows = score_rows(now); lo = now - WIN; out = []
    grid = "".join(f'<line class="gl" x1="{WIN * g // 4}" x2="{WIN * g // 4}" y1="0" y2="52"/>' for g in (1, 2, 3))
    for t, label, k in LANES:
        mine = [r for r in rows if r[0] == k]; n = sum(1 for r in mine if r[1] >= lo)
        if k == "s":   # clusters, never overlapping (seal_layer)
            out.append(f'<div class="lane" data-k="{k}"><span class="lbl">{label}</span><div class="plot"><svg viewBox="0 0 {WIN} 52" preserveAspectRatio="none" aria-hidden="true">'
                       f'{grid}<line class="now" x1="{WIN - 1}" x2="{WIN - 1}" y1="0" y2="52"/></svg>{seal_layer([r[1] for r in mine], b, lo, now)}</div>'
                       f'<b class="c num">{n}</b></div>')
            continue
        marks = "".join(_mark(*r, b) for r in mine)
        out.append(f'<div class="lane" data-k="{k}"><span class="lbl">{label}</span><svg viewBox="0 0 {WIN} 52" preserveAspectRatio="none" aria-hidden="true">'
                   f'{grid}<g class="mk" data-b="{b}" transform="translate({b - lo:.0f} 0)">{marks}</g><line class="now" x1="{WIN - 1}" x2="{WIN - 1}" y1="0" y2="52"/></svg>'
                   f'<b class="c num">{n}</b></div>')
    ax = "".join(f"<span>{s}</span>" for s in ("24m", "18m", "12m", "6m", "now"))
    return (f'<div class="score" id="score" aria-label="Answers, attests and seals over the last 24 minutes">{"".join(out)}<i class="nowg" aria-hidden="true"></i>'
            f'<div class="sax"><span></span><div>{ax}</div><span></span></div>{ticker}</div>')

def bezel(o, now=None):
    now = time.time() if now is None else now
    s, c, per = o.get("last_close"), o.get("est_close"), o.get("period") or 21600
    f = min(1.0, max(0.0, (now - s) / per)) if s else 0
    ln = "".join(f'<line class="{"on" if i / (TICKS - 1) <= f else ""}{" big" if i % 12 == 0 else ""}" x1="{i * 10 + 1}" x2="{i * 10 + 1}" y1="{0 if i % 12 == 0 else 6}" y2="22"/>'
                 for i in range(TICKS))
    ax = f'<div class="bez-ax">{lt(s, "t") if s else ""}<span></span>{lt(c, "t") if c else ""}</div>'
    return (f'<div class="bezel" data-start="{s or ""}" data-close="{c or ""}" aria-hidden="true">'
            f'<div class="bzw" style="--f:{f:.5f}"><svg viewBox="0 0 712 22" preserveAspectRatio="none">{ln}</svg><i class="bzs"></i><i class="bzh"></i></div>{ax}</div>')

def bench_html(o, graders, ask, now=None, feed=()):
    """The whole hero card body. `graders`: views.graders_tile (count, Halted or Unconfirmed tag, tooltip). `ask`: the Ask button."""
    now = time.time() if now is None else now
    left = (o["est_close"] - now) if o.get("est_close") else None
    cd = f'<b class="cd" data-close="{o["est_close"]}">{dur(max(0, left))}</b>' if left is not None else "<b>···</b>"
    pool = f'<b class="num" data-live="pool">{compact(o.get("pool"))}</b><small>POA</small>' if o.get("pool") else "<b>···</b>"
    leg = "".join(f'<span><i class="sw {k}"></i>{n}</span>' for n, k in (("Answer", "a"), ("Attest", "t"), ("Seal", "s")))
    return (f'<div class="bench">'
            f'<div class="bl"><div class="bh"><span class="lbl">Epoch</span>{ask}<a class="more tklive" href="/chain">More →</a></div>'
            f'<div class="bnum"><b class="bn num" data-live="epoch">{o["epoch"]}</b><div class="bcd"><span class="lbl">Closes in</span>{cd}</div></div>'
            f'{bezel(o, now)}'
            f'<div class="trio"><div><span class="lbl">Answers</span><b class="num" data-live="answers">{intc(o.get("answers"))}</b></div>'
            f'<div>{graders}</div><div><span class="lbl">Pool</span>{pool}</div></div></div>'
            f'<div class="br"><div class="bh"><i class="ldot" aria-hidden="true"></i><span class="lbl on">Live</span><span class="lbl">Last 24 min</span>'
            f'<span class="legend">{leg}</span></div>{score_html(now, ticker_html(feed, now))}</div></div>')

def pour_html(last):
    """The latest close's pool, split into minted (gold) and burned (slag)."""
    if not last: return '<p class="empty">No closes yet</p>'
    pool = float(last.get("pool") or 0); m = float(last.get("minted") or 0); b = float(last.get("burned") or 0)
    mp = 100 * m / pool if pool else 0; bp = last.get("burn_pct") if last.get("burn_pct") is not None else (100 - mp)
    return (f'<div class="pour" id="pour" data-ep="{last.get("epoch")}"><div class="prow"><span class="lbl">Pool</span><b class="fig" title="{pool:,.2f} POA">{compact(pool)}</b></div>'
            f'<div class="pourbar" role="img" aria-label="Minted {mp:.1f}%, burned {bp:.1f}%"><i class="pm" style="width:{mp:.2f}%"></i><i class="pb"></i></div>'
            f'<div class="pleg"><span><i class="sw m"></i>Minted <b class="num">{compact(m)}</b></span><span><i class="sw b"></i>Burned <b class="num">{compact(b)}</b></span>'
            f'<span class="pp"><b class="num">{bp:.1f}%</b> burned</span></div></div>')
