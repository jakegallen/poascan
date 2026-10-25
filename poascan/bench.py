"""Phase 2 (1.26.128+): the Bench, Home's hero, and the Pour card. Built from POAScan's own archive only (the txs table the
indexer already fills and analytics.open_epoch), so it adds no upstream reads.

Left: the epoch numeral, the countdown and a 72 tick bezel that fills as the epoch runs. Right: the chain in three voices over
the last 24 minutes (Answers, Attests, Seals). Marks sit in an SVG whose x unit is one second; app.js slides the mark group left
as time passes (one transform every 5 s) and refetches /fragment/score only when the live snapshot shows a new tx, so the
strip moves when the chain does and is still otherwise."""
import math, threading, time
from . import db
from .ui import E, intc, lt, compact, dur

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

def score_html(now=None):
    now = time.time() if now is None else now
    b = base(now); rows = score_rows(now); lo = now - WIN; out = []
    grid = "".join(f'<line class="gl" x1="{WIN * g // 4}" x2="{WIN * g // 4}" y1="0" y2="52"/>' for g in (1, 2, 3))
    for t, label, k in LANES:
        mine = [r for r in rows if r[0] == k]; n = sum(1 for r in mine if r[1] >= lo)
        marks = "".join(_mark(*r, b) for r in mine)
        out.append(f'<div class="lane" data-k="{k}"><span class="lbl">{label}</span><svg viewBox="0 0 {WIN} 52" preserveAspectRatio="none" aria-hidden="true">'
                   f'{grid}<g class="mk" data-b="{b}" transform="translate({b - lo:.0f} 0)">{marks}</g><line class="now" x1="{WIN - 1}" x2="{WIN - 1}" y1="0" y2="52"/></svg>'
                   f'<b class="c num">{n}</b></div>')
    ax = "".join(f"<span>{s}</span>" for s in ("24m", "18m", "12m", "6m", "now"))
    return f'<div class="score" id="score" aria-label="Answers, attests and seals over the last 24 minutes">{"".join(out)}<div class="sax"><span></span><div>{ax}</div><span></span></div></div>'

def bezel(o, now=None):
    now = time.time() if now is None else now
    s, c, per = o.get("last_close"), o.get("est_close"), o.get("period") or 21600
    f = min(1.0, max(0.0, (now - s) / per)) if s else 0
    ln = "".join(f'<line class="{"on" if i / (TICKS - 1) <= f else ""}{" big" if i % 12 == 0 else ""}" x1="{i * 10 + 1}" x2="{i * 10 + 1}" y1="{0 if i % 12 == 0 else 6}" y2="22"/>'
                 for i in range(TICKS))
    ax = f'<div class="bez-ax">{lt(s, "t") if s else ""}<span></span>{lt(c, "t") if c else ""}</div>'
    return (f'<div class="bezel" data-start="{s or ""}" data-close="{c or ""}" aria-hidden="true">'
            f'<svg viewBox="0 0 712 22" preserveAspectRatio="none">{ln}</svg>{ax}</div>')

def bench_html(o, graders, ask, now=None):
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
            f'<span class="legend">{leg}</span></div>{score_html(now)}</div></div>')

def pour_html(last):
    """The latest close's pool, split into minted (gold) and burned (slag)."""
    if not last: return '<p class="empty">No closes yet</p>'
    pool = float(last.get("pool") or 0); m = float(last.get("minted") or 0); b = float(last.get("burned") or 0)
    mp = 100 * m / pool if pool else 0; bp = last.get("burn_pct") if last.get("burn_pct") is not None else (100 - mp)
    return (f'<div class="pour" id="pour"><div class="prow"><span class="lbl">Pool</span><b class="fig" title="{pool:,.2f} POA">{compact(pool)}</b></div>'
            f'<div class="pourbar" role="img" aria-label="Minted {mp:.1f}%, burned {bp:.1f}%"><i class="pm" style="width:{mp:.2f}%"></i><i class="pb"></i></div>'
            f'<div class="pleg"><span><i class="sw m"></i>Minted <b class="num">{compact(m)}</b></span><span><i class="sw b"></i>Burned <b class="num">{compact(b)}</b></span>'
            f'<span class="pp"><b class="num">{bp:.1f}%</b> burned</span></div></div>')
