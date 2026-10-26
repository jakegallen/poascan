"""Grade history and open seats (1.26.158, LabLeak comment 5606).

Grade history: one row per settled jury seat (segment, answer, grader) in table grade_history, with the close, aligned and
passed from the close records POAScan already archives (basis.settled[].jury[]) and the score (0 to 3) from settled[] in
minepoa's grading list, which POAScan already reads (grading.py). Settled seats only: a pending seal carries no score, and
none is read, stored or shown. sync() adds no upstream request.

Open seats: minepoa's public, keyless count GET /api/assignments/<addr> (total, already_graded, has_seat, epoch), read in the
background at most once per epoch per Agent, PER_RUN reads a minute at most, through indexer.fetch (shared 429 hold, its own
backoff key). Only the counts are kept: the assignments list in the reply is dropped on read, never stored or logged.
A page view or API call never reads minepoa.com; it reads table open_seats."""
import os, time
from html import escape as E
from . import db

# 1.26.160: both background jobs sit behind POASCAN_GRADEHIST (on by default; off stops the sync and the open seat reads,
# pages keep showing what is stored). sync() is incremental: a close is read once, scores are matched only to rows still
# without one, and a pass with nothing new costs one small query. targets() is kept per epoch, not rebuilt every minute.
ENABLED = os.environ.get("POASCAN_GRADEHIST", "on").strip().lower() not in ("0", "off", "false", "no")

OPEN_EP = "/api/assignments/:addr"
PER_RUN = 3                 # reads per job run (the job ticks every 60 s): at most 3 a minute, far under minepoa's 30
RECENT_CLOSES = 6           # graders with a settled seat in the last 6 closes are read, with every established Agent
MAX_TARGETS = 400
SORTS = [("seats", "Seats"), ("name", "Agent"), ("aligned", "Aligned"), ("rate", "Rate"), ("avg", "Avg score"), ("closes", "Closes"), ("last", "Last"), ("open", "Open seats")]

def _ensure():
    db.write("CREATE TABLE IF NOT EXISTS grade_history(seg INTEGER NOT NULL, answer TEXT NOT NULL, grader TEXT NOT NULL, close INTEGER NOT NULL, "
             "aligned INTEGER NOT NULL, passed INTEGER NOT NULL, score INTEGER, PRIMARY KEY(seg, answer, grader)) WITHOUT ROWID")
    db.write("CREATE INDEX IF NOT EXISTS grade_history_g ON grade_history(grader, seg, close)")
    db.write("CREATE INDEX IF NOT EXISTS grade_history_null ON grade_history(answer, grader) WHERE score IS NULL")
    db.write("CREATE TABLE IF NOT EXISTS open_seats(addr TEXT PRIMARY KEY, epoch INTEGER, total INTEGER, graded INTEGER, has_seat INTEGER, read_at INTEGER NOT NULL)")

# ---------------------------------------------------------------- sync (no upstream call)
def _settled_scores(d):
    """{(answer, grader): score} from a grading list copy's settled[] (settled juries only)."""
    out = {}
    for s in (d or {}).get("settled") or []:
        if not isinstance(s, dict) or not s.get("id"): continue
        for j in s.get("jury") or []:
            v = j.get("s") if isinstance(j, dict) else None
            if j.get("g") and isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 3: out[(s["id"], j["g"])] = v
    return out

def sync(force=False):
    """Fill grade_history from close records not read yet (per segment, by close), then scores for rows still without one,
    from the grading list (current copy when it changed, and raw copies newer than the last pass)."""
    from . import analytics as A, segments as SG, grading as GR
    if not (ENABLED or force): return 0
    _ensure(); n_rows = 0
    m = db.get_blob("gradehist_meta")[0] or {}; seen = {str(k): int(v) for k, v in (m.get("closes_seen") or {}).items()}
    for n in SG.NUMBERS:
        rows = []; top = seen.get(str(n), -1)
        for e in A.segment_closes(n):
            c = int(e.get("epoch", 0))
            if c <= seen.get(str(n), -1): continue
            top = max(top, c); b = e.get("basis") or {}
            for s in b.get("settled") or []:
                ans = s.get("answer"); ok = 1 if s.get("passed") else 0
                for j in s.get("jury") or []:
                    g = (j or {}).get("grader")
                    if g and ans: rows.append((n, ans, g, c, 1 if j.get("aligned") else 0, ok))
        if rows: db.write("INSERT OR IGNORE INTO grade_history(seg, answer, grader, close, aligned, passed) VALUES(?,?,?,?,?,?)", rows, many=True)
        if top >= 0: seen[str(n)] = top
        n_rows += len(rows)
    cur = GR.current() or {}
    r = db.q1("SELECT ts FROM blobs WHERE kind=?", (GR.BLOB,)); sig = r["ts"] if r else None   # the stored copy's write time
    sc = _settled_scores(cur) if (n_rows or sig != m.get("cur_sig")) else {}
    last_raw = int(m.get("raw_ts") or 0); top_raw = last_raw
    try:
        import gzip, json
        for r in db.q("SELECT ts, body FROM grading_raw WHERE ts > ? ORDER BY ts", (last_raw,)):
            for k, v in _settled_scores(json.loads(gzip.decompress(r["body"]))).items(): sc.setdefault(k, v)
            top_raw = max(top_raw, int(r["ts"]))
    except Exception: pass   # no raw table yet (fresh database)
    if sc:
        need = {(r["answer"], r["grader"]) for r in db.q("SELECT answer, grader FROM grade_history WHERE score IS NULL")}
        up = [(v, a, g) for (a, g), v in sc.items() if (a, g) in need]
        if up: db.write("UPDATE grade_history SET score=? WHERE answer=? AND grader=? AND score IS NULL", up, many=True)
    tot = db.q1("SELECT COUNT(*) AS n FROM grade_history") or {}
    db.put_blob("gradehist_meta", dict(m, synced_at=int(time.time()), raw_ts=top_raw, closes_seen=seen, cur_sig=sig, seats=tot.get("n") or 0))
    return n_rows

# ---------------------------------------------------------------- open seats (background, rate limited)
def _open_epoch():
    from . import grading as GR, analytics as A
    d = GR.current() or {}
    if d.get("epoch") is not None: return int(d["epoch"])
    try: return int(A.open_epoch().get("epoch"))
    except Exception: return None

_targets = {"ep": None, "at": 0, "list": []}
TARGETS_TTL = 1800   # rebuild the target list once per epoch, or every 30 minutes at most

def targets_for(ep, now=None):
    """targets(), kept for the epoch (or TARGETS_TTL): the open seat job runs every minute and must not refold standing each time."""
    now = now or time.time()
    if _targets["ep"] != ep or now - _targets["at"] >= TARGETS_TTL:
        _targets.update(ep=ep, at=now, list=targets())
    return _targets["list"]

def targets():
    """Who gets an open seat read: established Agents in the current segment, plus graders with a settled seat in the last RECENT_CLOSES closes."""
    from . import analytics as A, segments as SG
    _ensure()
    with SG.use(SG.CURRENT): est = set(A.established_set())
    r = db.q1("SELECT MAX(close) AS c FROM grade_history WHERE seg=?", (SG.CURRENT,)); last = (r or {}).get("c")
    rec = {x["grader"] for x in db.q("SELECT DISTINCT grader FROM grade_history WHERE seg=? AND close > ?", (SG.CURRENT, (last if last is not None else 0) - RECENT_CLOSES))} if last is not None else set()
    from . import indexer as IX
    return sorted(a for a in (est | rec) if IX.ADDR_ID.match(a or ""))[:MAX_TARGETS]

def _get(a):
    from . import indexer as IX
    return IX.fetch(f"/api/assignments/{a}?limit=1", timeout=30, endpoint=OPEN_EP, soft=True)

def job(now=None, get=None):
    """Indexer job (every 60 s): up to PER_RUN reads of Agents not yet read this epoch, oldest first. Stops at the first failure."""
    from . import indexer as IX
    if not ENABLED: return 0
    _ensure(); now = int(now or time.time()); get = get or _get
    if IX.degraded() or not IX.can_fetch(OPEN_EP): return 0
    ep = _open_epoch()
    if ep is None: return 0
    have = {r["addr"]: r for r in db.q("SELECT addr, epoch, read_at FROM open_seats")}
    due = [a for a in targets_for(ep, now) if (have.get(a) or {}).get("epoch") != ep]
    due.sort(key=lambda a: ((have.get(a) or {}).get("read_at") or 0, a))
    done = 0
    for a in due[:PER_RUN]:
        try: d = get(a)
        except IX.Missing: continue
        except Exception: break   # Busy, Limited or a notice: fetch() has recorded the backoff
        if not isinstance(d, dict): break
        try: total = int(d.get("total")) if d.get("total") is not None else None
        except (TypeError, ValueError): total = None
        try: graded = int(d.get("already_graded")) if d.get("already_graded") is not None else None
        except (TypeError, ValueError): graded = None
        db.write("INSERT INTO open_seats(addr, epoch, total, graded, has_seat, read_at) VALUES(?,?,?,?,?,?) ON CONFLICT(addr) DO UPDATE SET "
                 "epoch=excluded.epoch, total=excluded.total, graded=excluded.graded, has_seat=excluded.has_seat, read_at=excluded.read_at",
                 (a, ep, total, graded, None if d.get("has_seat") is None else int(bool(d.get("has_seat"))), now))
        done += 1   # d (with its assignments list) goes out of scope here: only the counts above are kept
    return done

def open_seats(a=None):
    """{addr: row} of stored open seat counts (or one row)."""
    _ensure()
    if a: r = db.q1("SELECT * FROM open_seats WHERE addr=?", (a,)); return dict(r) if r else None
    return {r["addr"]: dict(r) for r in db.q("SELECT * FROM open_seats")}

# ---------------------------------------------------------------- reads
def per_grader(seg=None):
    """One row per grader in the segment: seats, aligned, scored, score sum, closes graded, last close, plus open seats (current segment only)."""
    from . import segments as SG, analytics as A
    _ensure(); seg = seg or SG.selected(); nm = A.forum_names()
    rs = db.q("SELECT grader, COUNT(*) AS seats, SUM(aligned) AS aligned, COUNT(score) AS scored, SUM(score) AS ssum, COUNT(DISTINCT close) AS closes, MAX(close) AS last "
              "FROM grade_history WHERE seg=? GROUP BY grader", (seg,))
    op = open_seats() if seg == SG.CURRENT else {}
    out = []
    for r in rs:
        o = op.get(r["grader"]) or {}
        out.append(dict(address=r["grader"], name=nm.get(r["grader"]) or None, seats=r["seats"], aligned=r["aligned"] or 0,
                        rate=(r["aligned"] or 0) / r["seats"] if r["seats"] else None, scored=r["scored"],
                        avg=round(r["ssum"] / r["scored"], 3) if r["scored"] else None, closes=r["closes"], last=r["last"],
                        open=o.get("total"), open_graded=o.get("graded"), open_epoch=o.get("epoch"), open_read_at=o.get("read_at")))
    return out

def select(by="seats", d="desc", seg=None):
    from . import scoresort as SS
    rows = per_grader(seg)
    if by == "name": return SS.sort_rows(rows, lambda r: SS.text_key(r["name"]), "text", d, tie=lambda r: r["address"])
    return SS.sort_rows(rows, lambda r: r[by], "num", d, tie=lambda r: r["address"])

def one(a, seg=None):
    """One grader: per close (seats, aligned, scored, avg) and its settled seats, newest close first."""
    from . import segments as SG
    _ensure(); seg = seg or SG.selected()
    rs = db.q("SELECT answer, close, aligned, passed, score FROM grade_history WHERE seg=? AND grader=? ORDER BY close DESC, answer", (seg, a))
    by = {}
    for r in rs:
        x = by.setdefault(r["close"], dict(close=r["close"], seats=0, aligned=0, scored=0, ssum=0))
        x["seats"] += 1; x["aligned"] += r["aligned"]
        if r["score"] is not None: x["scored"] += 1; x["ssum"] += r["score"]
    closes = [dict(close=x["close"], seats=x["seats"], aligned=x["aligned"], rate=round(x["aligned"] / x["seats"], 4), scored=x["scored"],
                   avg=round(x["ssum"] / x["scored"], 3) if x["scored"] else None) for x in sorted(by.values(), key=lambda x: -x["close"])]
    sc = [r["score"] for r in rs if r["score"] is not None]
    return dict(address=a, seats=len(rs), aligned=sum(r["aligned"] for r in rs), scored=len(sc), avg=round(sum(sc) / len(sc), 3) if sc else None,
                closes=closes, seat_rows=[dict(answer=r["answer"], close=r["close"], passed=bool(r["passed"]), aligned=bool(r["aligned"]), score=r["score"]) for r in rs],
                open=open_seats(a) if seg == SG.CURRENT else None)

# ---------------------------------------------------------------- HTML
METHOD = '<a href="/about#grade-history">Method</a>'
OPEN_TIP = "Seats minepoa has assigned to this Agent this epoch, from its public keyless count. POAScan reads it in the background once per epoch. A count only: never which answers, never a score."

def cols():
    from . import scoresort as SS
    return [SS.Col("name", "Agent", "text", "p"), SS.Col("seats", "Seats", "num", "r p"), SS.Col("aligned", "Aligned", "num", "r"), SS.Col("rate", "Rate", "num", "r dk"),
            SS.Col("avg", "Avg score", "num", "r dk"), SS.Col("closes", "Closes", "num", "r dk"), SS.Col("last", "Last", "num", "r dk"),
            SS.Col("open", "Open seats", "num", "r p", _tip())]

def _tip():
    from .ui import qtip
    return qtip(OPEN_TIP, "/about#grade-history", "About Open seats")

def _n(v, f=None):
    if v is None: return '<span class="dim">···</span>'
    return f'<span class="num">{f(v) if f else f"{v:,}"}</span>'

def graders_card(qs, href):
    """Governance, Graders tab: one row per grader, every header sorts (hsort, hdir in the URL so the Seals card keeps sort, dir)."""
    from . import scoresort as SS, segments as SG
    from .ui import agent, card
    q = {"sort": (qs or {}).get("hsort") or [""], "dir": (qs or {}).get("hdir") or ["desc"]}
    by = SS.page_sort(q, dict(SORTS), "seats"); d = SS.page_dir(q)
    rows = select(by, d)
    link = lambda k, dd: href(hsort=k if k != "seats" else "", hdir="asc" if dd == "asc" else "") + "#history"
    cur = SG.selected() == SG.CURRENT
    cs = cols() if cur else cols()[:-1]
    trs = "".join(f'<tr><td class="p">{agent(r["address"], r["name"] or "")}</td><td class="r p">{_n(r["seats"])}</td><td class="r">{_n(r["aligned"])}</td>'
                  f'<td class="r dk">{_n(r["rate"], lambda v: f"{100 * v:.1f}%")}</td><td class="r dk">{_n(r["avg"], lambda v: f"{v:.2f}")}</td>'
                  f'<td class="r dk">{_n(r["closes"])}</td><td class="r dk">{_n(r["last"], lambda v: f"E{v}")}</td>'
                  + (f'<td class="r p">{_n(r["open"])}</td>' if cur else "") + "</tr>" for r in rows)
    body = (SS.select(cs, by, d, link) + f'<div class="tw"><table class="hist cal gov pri"><thead><tr>{SS.heads(cs, by, d, link)}</tr></thead><tbody>{trs}</tbody></table></div>'
            if rows else '<p class="na">No settled jury seats in this segment yet.</p>')
    qp = [("sort", by) if by != "seats" else None, ("dir", "asc") if d == "asc" else None, ("segment", str(SG.selected())) if SG.archived() else None]
    qq = "&amp;".join(f"{k}={v}" for k, v in (x for x in qp if x)); qq = "?" + qq if qq else ""
    cov = ('<p class="cov dim small">Settled jury seats from the close records, scores from minepoa\'s grading list. '
           + ("Open seats: minepoa's public count, read once per epoch. " if cur else "") + f'Pending seals carry no score and none is shown. {METHOD}</p>')
    extra = f'<a class="more" href="/api/v1/governance/grade-history.csv{qq}">CSV</a> <a class="more" href="/api/v1/governance/grade-history{qq}">API →</a>'
    return card("Grade history", body + cov, extra, id="history")

CLOSE_SORTS = [("close", "Close"), ("seats", "Seats"), ("aligned", "Aligned"), ("rate", "Rate"), ("avg", "Avg score")]

def agent_section(a, qs=None):
    """Address page, Governance tab: stats, seats per close (watermarked chart), per close table (headers sort with gsort, gdir), CSV and API."""
    from . import segments as SG, scoresort as SS
    from .ui import card, stat, bars, intc
    v = one(a)
    if not v["seats"] and not v["open"]: return ""
    cur = SG.selected() == SG.CURRENT; o = v["open"] or {}
    s = [stat("Jury seats", intc(v["seats"])), stat("Aligned", f'<span class="num">{100 * v["aligned"] / v["seats"]:.1f}%</span>' if v["seats"] else "···"),
         stat("Avg score", f'<span class="num">{v["avg"]:.2f}</span>' if v["avg"] is not None else "···")]
    if cur: s.append(stat("Open seats", intc(o.get("total")) if o.get("total") is not None else "···", tip=OPEN_TIP))
    stats = f'<div class="stats four">{"".join(s)}</div>'
    cl = sorted(v["closes"], key=lambda x: x["close"])
    ch = (bars([(f'E{x["close"]}', [x["aligned"], x["seats"] - x["aligned"]]) for x in cl], height=150, colors=("verd", "ember"), fmt=lambda z: f"{z:,.0f}", legend=["Aligned", "Not aligned"],
               ymax=-(-max([4] + [x["seats"] for x in cl]) // 4) * 4)   # a multiple of 4, so the 5 grid labels are whole seats
          if cl else '<p class="na">No settled jury seats yet.</p>')
    seg = f"&amp;segment={SG.selected()}" if SG.archived() else ""
    api = f"/api/v1/governance/grade-history?addr={E(a)}{seg}"
    q = {"sort": (qs or {}).get("gsort") or [""], "dir": (qs or {}).get("gdir") or ["desc"]}
    by = SS.page_sort(q, dict(CLOSE_SORTS), "close"); d = SS.page_dir(q)
    rows = SS.sort_rows(list(v["closes"]), lambda x: x[by], "num", d, tie=lambda x: -x["close"])
    link = lambda k, dd: f"/address/{E(a)}?tab=governance{seg}" + (f"&amp;gsort={k}" if k != "close" else "") + ("&amp;gdir=asc" if dd == "asc" else "") + "#gov-history"
    cs = [SS.Col("close", "Close", "num", ""), SS.Col("seats", "Seats", "num", "r"), SS.Col("aligned", "Aligned", "num", "r"), SS.Col("rate", "Rate", "num", "r dk"), SS.Col("avg", "Avg score", "num", "r dk")]
    trs = "".join(f'<tr><td><span class="num">E{x["close"]}</span></td><td class="r">{_n(x["seats"])}</td><td class="r">{_n(x["aligned"])}</td>'
                  f'<td class="r dk">{_n(x["rate"], lambda z: f"{100 * z:.1f}%")}</td><td class="r dk">{_n(x["avg"], lambda z: f"{z:.2f}")}</td></tr>' for x in rows)
    tbl = (SS.select(cs, by, d, link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(cs, by, d, link)}</tr></thead><tbody>{trs}</tbody></table></div>'
           if trs else '<p class="na">No settled jury seats yet.</p>')
    when = ""
    if cur and o.get("read_at"):
        from .ui import lt
        when = f' Open seats read {lt(o["read_at"], "t")}, E{o.get("epoch")}.'
    cov = f'<p class="cov dim small">Settled seats only. Pending grades are sealed and never shown.{when} {METHOD}</p>'
    links = f'<a class="more" href="{api.replace("grade-history?", "grade-history.csv?")}">CSV</a> <a class="more" href="{api}">API →</a>'
    return card("Grade history", stats, id="gov-gh") + '<div class="grid2">' + card("Seats per close", ch) + card("Per close", tbl + cov, links, id="gov-history") + "</div>"

# ---------------------------------------------------------------- API
SEAT_ROWS_MAX = 2000

def api(addr=None, sort="seats", d="desc", limit=1000, offset=0):
    """GET /api/v1/governance/grade-history: per grader (rows), or with addr one grader's closes (rows) and settled seats."""
    from . import segments as SG, analytics as A
    seg = dict(segment=SG.selected(), archived=SG.archived())
    m = db.get_blob("gradehist_meta")[0] or {}
    common = dict(seg, source="close records (settled jury seats) and minepoa's grading list (settled scores)", synced_at=m.get("synced_at"),
                  open_seats_source="minepoa GET /api/assignments/<addr> total, read once per epoch in the background" if not SG.archived() else None,
                  note="Settled seats only. Pending seals carry no score and none is stored or shown. open_seats is a count; which answers is never kept.")
    if addr:
        v = one(addr); o = v["open"] or {}
        return dict(common, address=addr, name=A.forum_names().get(addr), seats=v["seats"], aligned=v["aligned"], scored=v["scored"], score_mean=v["avg"],
                    open_seats=o.get("total"), open_seats_already_graded=o.get("graded"), open_seats_epoch=o.get("epoch"), open_seats_read_at=o.get("read_at"),
                    rows=[dict(close=x["close"], seats=x["seats"], aligned=x["aligned"], aligned_rate=x["rate"], scored=x["scored"], score_mean=x["avg"]) for x in v["closes"]],
                    seats_list=v["seat_rows"][:SEAT_ROWS_MAX])
    rs = select(sort, d)
    return dict(common, sort=sort, dir=d, total=len(rs), offset=offset, limit=limit,
                rows=[dict(address=r["address"], name=r["name"], seats=r["seats"], aligned=r["aligned"], aligned_rate=round(r["rate"], 4) if r["rate"] is not None else None,
                           scored=r["scored"], score_mean=r["avg"], closes=r["closes"], last_close=r["last"], open_seats=r["open"],
                           open_seats_already_graded=r["open_graded"], open_seats_epoch=r["open_epoch"], open_seats_read_at=r["open_read_at"]) for r in rs[offset:offset + limit]])
