"""minepoa's grading list (1.26.134): GET /api/explorer/grading, public and keyless.

One server-side read feeds every page, API and CSV; a page view never calls minepoa.com. The list is large (about 4 MB,
1.8 MB gzipped) and costly to build at the origin (gen_ms near 90 s; edge cache 30 s), so the read is slow on purpose:
every READ_S (10 min), every NEAR_S (5 min) within NEAR_WINDOW_S (30 min) of a close on either side, with If-None-Match.
A failed read doubles the wait from READ_S up to BACKOFF_MAX_S (30 min); a Retry-After (header or retry_after_seconds in
the body) is a floor on top of that. The schedule lives in the database, so a restart or deploy never adds a read.

Stored: a compact current copy (blob "grading", snippets dropped), seal changes (grading_seals: one row per seal, with
when POAScan first saw it and when it left the list), and full raw copies only for the read just before a close (pre)
and the first read after one (post), gzipped, RAW_KEEP kept.

What the list says, and what it does not:
  rows[] pending answers: id, author, born, since, expires, kind, raw (seals), qual (seals that count), need, grades[].
  grades[] seals: g (grader), ts, t (trusted grader), q (counts toward quorum). No verdict or score on a pending seal.
  settled[] jury seats carry aligned, s (score 0 to 3) and r (the juror's reason).
  leaderboard[] per grader: seals, qual, avg (mean jury score s), trusted, established.
  established[] minepoa's established list. What q means is not documented; POAScan infers it from the data."""
import gzip, json, logging, random, statistics, time
from . import db

log = logging.getLogger("poascan.grading")
PATH = "/api/explorer/grading"
READ_S, NEAR_S, NEAR_WINDOW_S, BACKOFF_MAX_S, JITTER_S = 600, 300, 1800, 1800, 20
TIMEOUT_S = 150          # the origin can take about 90 s to build the list
STALE_S = 3600           # a copy older than this is shown with a Stale tag
RAW_KEEP = 24            # pre and post copies kept (about 12 closes)
SEAL_KEEP_DAYS = 45      # seals that left the list are kept this long
BLOB, META = "grading", "grading_meta"
QUORUM_DEFAULT = 4
SETTLE_CAP_DEFAULT = 2000   # only when /api/params has no settle_cap_per_close

def grade_quorum(d=None):
    """params.grade_quorum, else the list's quorum, else 4. Note (1.26.139): the engine (poa.mjs, v1.1.2-carveout2) checks
    carried rows against a literal quorum of 4 and new rows against grade_quorum; both are 4 today, so need reads grade_quorum."""
    from . import analytics as A
    try: q = int(A.params().get("grade_quorum") or 0)
    except Exception: q = 0
    return q or int((d or {}).get("quorum") or QUORUM_DEFAULT)

def settle_cap():
    """params.settle_cap_per_close: each close evaluates only the oldest this many pending rows, by (since, answer id);
    the rest carry over unevaluated."""
    from . import analytics as A
    try: return int(A.params().get("settle_cap_per_close") or 0) or SETTLE_CAP_DEFAULT
    except Exception: return SETTLE_CAP_DEFAULT

# ---------------------------------------------------------------- storage
def _ensure():
    db.write("CREATE TABLE IF NOT EXISTS grading_seals(answer TEXT NOT NULL, grader TEXT NOT NULL, ts INTEGER NOT NULL, t INTEGER NOT NULL, "
             "q INTEGER NOT NULL, first_seen INTEGER NOT NULL, gone INTEGER, q_changed INTEGER, PRIMARY KEY(answer, grader, ts)) WITHOUT ROWID")
    db.write("CREATE INDEX IF NOT EXISTS grading_seals_g ON grading_seals(grader, ts)")
    db.write("CREATE TABLE IF NOT EXISTS grading_raw(epoch INTEGER NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('pre','post')), ts INTEGER NOT NULL, "
             "as_of INTEGER, bytes INTEGER, body BLOB NOT NULL, PRIMARY KEY(epoch, kind))")

def compact(d):
    """The stored current copy: everything but the answer snippets (kept only in the raw copies)."""
    out = dict(d)
    for k in ("rows", "open"):
        out[k] = [{x: v for x, v in r.items() if x != "snippet"} for r in (d.get(k) or []) if isinstance(r, dict)]
    return out

def store_seals(d, now):
    """Seal changes: new seals in, seals no longer listed marked gone, q flips stamped. Returns (added, gone, flipped)."""
    _ensure()
    cur = {}
    for r in (d.get("rows") or []) + (d.get("open") or []):
        for g in r.get("grades") or []:
            if isinstance(g, dict) and g.get("g") and isinstance(g.get("ts"), (int, float)):
                cur[(r["id"], g["g"], int(g["ts"]))] = (1 if g.get("t") else 0, 1 if g.get("q") else 0)
    have = {(x["answer"], x["grader"], x["ts"]): x["q"] for x in db.q("SELECT answer, grader, ts, q FROM grading_seals WHERE gone IS NULL")}
    add = [(a, g, t, tq[0], tq[1], now) for (a, g, t), tq in cur.items() if (a, g, t) not in have]
    gone = [(now, a, g, t) for (a, g, t) in have if (a, g, t) not in cur]
    flip = [(cur[k][1], now, *k) for k, q in have.items() if k in cur and cur[k][1] != q]
    back = [(a, g, t) for a, g, t, *_ in add]   # listed again after leaving: no longer gone (INSERT OR IGNORE keeps the old row)
    if add: db.write("INSERT OR IGNORE INTO grading_seals(answer, grader, ts, t, q, first_seen) VALUES(?,?,?,?,?,?)", add, many=True)
    if gone: db.write("UPDATE grading_seals SET gone=? WHERE answer=? AND grader=? AND ts=?", gone, many=True)
    if flip: db.write("UPDATE grading_seals SET q=?, q_changed=? WHERE answer=? AND grader=? AND ts=?", flip, many=True)
    if back: db.write("UPDATE grading_seals SET gone=NULL WHERE answer=? AND grader=? AND ts=? AND gone IS NOT NULL", back, many=True)
    db.write("DELETE FROM grading_seals WHERE gone IS NOT NULL AND gone < ?", (now - SEAL_KEEP_DAYS * 86400,))
    return len(add), len(gone), len(flip)

def store_raw(d, kind, now):
    _ensure()
    body = gzip.compress(json.dumps(d, separators=(",", ":")).encode(), 6)
    db.write("INSERT OR REPLACE INTO grading_raw(epoch, kind, ts, as_of, bytes, body) VALUES(?,?,?,?,?,?)",
             (int(d.get("epoch") or 0), kind, int(now), d.get("as_of"), len(body), body))
    db.write("DELETE FROM grading_raw WHERE rowid NOT IN (SELECT rowid FROM grading_raw ORDER BY ts DESC LIMIT ?)", (RAW_KEEP,))

def raw_index():
    """[{epoch, kind, ts, as_of, bytes}] newest first (no bodies)."""
    try: _ensure(); return db.q("SELECT epoch, kind, ts, as_of, bytes FROM grading_raw ORDER BY ts DESC")
    except Exception: return []

def valid(d):
    return isinstance(d, dict) and isinstance(d.get("rows"), list) and isinstance(d.get("stats"), dict) and "epoch" in d

# ---------------------------------------------------------------- schedule
def next_close(d=None, now=None):
    """Estimated time of the open epoch's close: the last rollup's time plus the median gap between rollups (6 h when
    there are fewer than two), else None. Returns (ts, epoch)."""
    d = d if d is not None else current()
    if not d: return None, None
    ro = sorted([r for r in d.get("rollups") or [] if isinstance(r, dict) and r.get("ts")], key=lambda r: r["ts"])
    if not ro: return None, d.get("epoch")
    gaps = [b["ts"] - a["ts"] for a, b in zip(ro, ro[1:]) if b["ts"] > a["ts"]]
    gap = int(statistics.median(gaps)) if gaps else 21600
    return int(ro[-1]["ts"] + gap), d.get("epoch")

def cadence(now, close_ts):
    """Seconds to the next read: NEAR_S within NEAR_WINDOW_S of the close on either side, else READ_S, but never so long
    that the first read inside the window before the close is skipped."""
    if close_ts:
        to = close_ts - now
        if -NEAR_WINDOW_S <= to <= NEAR_WINDOW_S: return NEAR_S
        if NEAR_WINDOW_S < to < NEAR_WINDOW_S + READ_S: return max(60, int(to - NEAR_WINDOW_S) + 5)
    return READ_S

def backoff(fails, retry=None):
    """READ_S doubling per failure in a row, capped at BACKOFF_MAX_S; a Retry-After is a floor."""
    w = min(BACKOFF_MAX_S, READ_S * (2 ** max(0, fails - 1)))
    return int(max(w, float(retry or 0)))

def _get():
    from . import indexer as I
    d = I.fetch(PATH, timeout=TIMEOUT_S, cond=True)
    return None if d is I.NOT_MODIFIED else d

def job(now=None, get=None, force=False):
    """Indexer job (ticks every minute; the stored next_at decides). One GET at most per run."""
    now = int(now or time.time()); get = get or _get
    m = db.get_blob(META)[0] or {}
    if not force and (m.get("next_at") or 0) > now: return False
    from . import indexer as I
    try:
        d = get()
        if d is not None and not valid(d): raise I.Busy("unexpected shape")
    except I.Busy as e:
        fails = int(m.get("fails") or 0) + 1; w = backoff(fails, getattr(e, "retry", None))
        db.put_blob(META, dict(m, fails=fails, last_err=now, err=str(e)[:120], retry=getattr(e, "retry", None), next_at=now + w))
        log.warning("grading: %s, next read in %ss", e, w); return False
    prev_epoch = m.get("epoch")
    if d is None:   # 304: nothing changed
        ct, _ = next_close(None, now)
        db.put_blob(META, dict(m, fails=0, last_ok=now, err=None, retry=None, not_modified=now, next_at=now + cadence(now, ct) + random.randint(-JITTER_S, JITTER_S)))
        return True
    ct, ep = next_close(d, now)
    try: added, gone, flipped = store_seals(d, now)
    except Exception as e: log.warning("grading: seal store failed (%s)", type(e).__name__); added = gone = flipped = None
    try:
        if prev_epoch is not None and d.get("epoch") is not None and int(d["epoch"]) > int(prev_epoch): store_raw(d, "post", now)
        elif ct and 0 <= ct - now <= NEAR_WINDOW_S: store_raw(d, "pre", now)
    except Exception as e: log.warning("grading: raw copy failed (%s)", type(e).__name__)
    db.put_blob(BLOB, dict(compact(d), fetched_at=now))
    _cur.clear()
    db.put_blob(META, dict(m, fails=0, last_ok=now, err=None, retry=None, epoch=d.get("epoch"), as_of=d.get("as_of"),
                           seals_added=added, seals_gone=gone, q_flipped=flipped, next_at=now + cadence(now, ct) + random.randint(-JITTER_S, JITTER_S)))
    return True

def meta(): return db.get_blob(META)[0] or {}

# ---------------------------------------------------------------- reads (no upstream call)
_cur = {}
def current():
    """The stored current copy, parsed once per new read (memory), or None when POAScan has none yet."""
    now = time.time()
    if "v" in _cur and now - _cur.get("chk", 0) < 5: return _cur["v"]   # one cheap check per 5 s, not per table row
    r = db.q1("SELECT ts FROM blobs WHERE kind=?", (BLOB,))
    if not r: return None
    sig = (r["ts"], db.blob_gen(BLOB))   # 1.26.180: ts is whole seconds; the generation tells two writes in one second apart
    if _cur.get("ts") == sig: _cur["chk"] = now; return _cur["v"]
    v = db.get_blob(BLOB)[0]
    if not valid(v): return None
    _cur.clear(); _cur.update(ts=sig, v=v, idx=None, chk=now, queue=None, graders=None, qix=None)
    return v

def fetched_at():
    d = current(); return (d or {}).get("fetched_at")

def upstream_as_of():
    d = current(); return (d or {}).get("as_of")

def stale(now=None):
    """True when the copy is older than STALE_S (or there is none)."""
    t = fetched_at(); return not t or (now or time.time()) - t > STALE_S

def usable():
    """A copy exists and applies to what is shown: the current segment only (the list is the live network's)."""
    from . import segments as SG
    return current() is not None and not SG.archived()

def index():
    """Per address lookups over the current copy, built once per read: q and raw seals per grader on pending rows, pending
    answers per author, settled seats per grader and settled answers per author."""
    d = current()
    if not d: return None
    if _cur.get("idx") is not None: return _cur["idx"]
    by_g, by_author, seats, settled_by = {}, {}, {}, {}
    for r in (d.get("rows") or []) + (d.get("open") or []):
        by_author.setdefault(r.get("author"), []).append(r)
        for s in r.get("grades") or []:
            x = by_g.setdefault(s.get("g"), dict(seals=0, qual=0, trusted=bool(s.get("t")), last=0, rows=[]))
            x["seals"] += 1; x["qual"] += 1 if s.get("q") else 0; x["last"] = max(x["last"], int(s.get("ts") or 0))
            x["rows"].append((r["id"], int(s.get("ts") or 0), bool(s.get("q")), bool(s.get("t")), r.get("need"), r.get("author")))
    for s in d.get("settled") or []:
        settled_by.setdefault(s.get("author"), []).append(s)
        for j in s.get("jury") or []: seats.setdefault(j.get("g"), []).append((s, j))
    lb = {x.get("addr"): x for x in d.get("leaderboard") or [] if isinstance(x, dict)}
    v = dict(by_g=by_g, by_author=by_author, seats=seats, settled_by=settled_by, lb=lb,
             established=set(a for a in d.get("established") or [] if isinstance(a, str)), trusted=set(d.get("trusted") or []))
    _cur["idx"] = v
    return v

# ---------------------------------------------------------------- established, cross-checked
UNCONFIRMED = "Unconfirmed"
def established_check(a):
    """(source, minepoa_established, detail) for an Agent POAScan counts as established.
    source: close_records (no current grading copy, or an archived segment), minepoa_grading (on minepoa's list too),
    conflict (POAScan counts it, minepoa's list does not). detail is the hover text for the Unconfirmed tag, else None."""
    if not usable(): return "close_records", None, None
    ix = index(); est = ix["established"]
    if a in est: return "minepoa_grading", True, None
    q = (ix["by_g"].get(a) or {}).get("qual", 0)
    lead = "minepoa's grading list shows none" if not est else "Not on minepoa's grading list"
    tail = "; this Agent's seals still count toward quorum." if q else "; hosted /me is the authority."
    return "conflict", False, lead + tail

def minepoa_established(a):
    """True or False from minepoa's grading list, None without a usable copy."""
    if not usable(): return None
    return a in index()["established"]

def conflict_summary(ours):
    """For a set of addresses POAScan counts as established: dict(minepoa_count, confirmed, conflict, list_empty) or None."""
    if not usable(): return None
    est = index()["established"]; ours = set(ours)
    return dict(minepoa_count=len(est), confirmed=len(ours & est), conflict=len(ours - est), list_empty=not est)

def tag_html(detail):
    from .ui import flag
    return flag(UNCONFIRMED, detail) if detail else ""

# ---------------------------------------------------------------- 1.26.137: queue, graders and per-Agent views (no upstream call)
def _row_view(r, ep, nm, open_=False, q=QUORUM_DEFAULT):
    gs = r.get("grades") or []
    t = sum(1 for g in gs if g.get("t")); qt = sum(1 for g in gs if g.get("t") and g.get("q")); qu = sum(1 for g in gs if g.get("q") and not g.get("t"))
    last = max((int(g.get("ts") or 0) for g in gs), default=0) or None
    exp = r.get("expires")
    return dict(id=r.get("id"), author=r.get("author"), name=nm.get(r.get("author")), born=r.get("born"), since=r.get("since"), expires=exp,
                expires_in=(int(exp) - int(ep)) if exp is not None and ep is not None else None, kind=r.get("kind"),
                raw=int(r.get("raw") or len(gs)), qual=int(r.get("qual") or 0), need=int(r.get("need") if r.get("need") is not None else max(0, q - int(r.get("qual") or 0))),
                trusted_seals=t, untrusted_seals=len(gs) - t, counting_trusted=qt, counting_untrusted=qu, last_seal_ts=last, open=open_)

def queue_rows():
    """Every pending answer in the copy (rows, then the open epoch's answers), one dict each, or [] without a copy."""
    d = current()
    if not d: return []
    if _cur.get("queue") is not None: return _cur["queue"]
    from . import analytics as A
    nm = A.forum_names(); ep = d.get("epoch")
    q = grade_quorum(d)
    out = [_row_view(r, ep, nm, o, q) for rs, o in ((d.get("rows") or [], False), (d.get("open") or [], True)) for r in rs if isinstance(r, dict) and r.get("id")]
    # settle window: the next close evaluates only the oldest settle_cap pending rows by (since, answer id); q stays the server's flag
    cap = settle_cap(); order = sorted((r for r in out if not r["open"]), key=lambda r: (r["since"] if r["since"] is not None else 1 << 30, r["id"]))
    for i, r in enumerate(order): r["settle_rank"] = i + 1; r["in_settle_window"] = i < cap
    for r in out:
        if r["open"]: r["settle_rank"] = None; r["in_settle_window"] = False
        r["ready_next_close"] = r["need"] == 0 and r["in_settle_window"]
        r["queued_at_quorum"] = r["need"] == 0 and not r["open"] and not r["in_settle_window"]
    _cur["queue"] = out
    return out

def summary():
    """Headline numbers from the copy: pending, at quorum, trusted share, next close; None without a copy."""
    d = current()
    if not d: return None
    st = d.get("stats") or {}; ct, ep = next_close(d); qr = queue_rows()
    return dict(pending=st.get("pending"), at_quorum=st.get("at_quorum"), settle_cap=settle_cap(),
                ready_next_close=sum(1 for r in qr if r["ready_next_close"]), at_quorum_queued=sum(1 for r in qr if r["queued_at_quorum"]), trusted_share=st.get("trusted_share"), by_need=st.get("by_need") or {},
                grades_on_pending=st.get("grades_on_pending"), graders=st.get("graders_distinct"), open_answers=len(d.get("open") or []),
                quorum=grade_quorum(d), epoch=ep, next_close_ts=ct, upstream_as_of=d.get("as_of"), fetched_at=d.get("fetched_at"),
                stale=stale(), established_listed=len(d.get("established") or []))

def last_close_ts(d=None):
    d = d if d is not None else current()
    ro = [r.get("ts") for r in (d or {}).get("rollups") or [] if isinstance(r, dict) and r.get("ts")]
    return max(ro) if ro else None

def grader_rows():
    """Per grader in the copy: seals and counting seals since the last close, on every pending answer, the counting rate,
    trusted (listed by minepoa) and minepoa's avg (mean jury score)."""
    d = current()
    if not d: return []
    if _cur.get("graders") is not None: return _cur["graders"]
    ix = index(); t0 = last_close_ts(d) or 0; out = []
    for g, x in ix["by_g"].items():
        if not g: continue
        since = [s for s in x["rows"] if s[1] > t0]
        lb = ix["lb"].get(g) or {}
        out.append(dict(address=g, seals_since_close=len(since), counting_since_close=sum(1 for s in since if s[2]),
                        pending_seals=x["seals"], pending_counting=x["qual"], qual_rate=(x["qual"] / x["seals"]) if x["seals"] else None,
                        trusted=g in ix["trusted"], minepoa_avg=lb.get("avg"), last_seal_ts=x["last"] or None))
    _cur["graders"] = out
    return out

def seal_tx(grader, ts):
    """The archived grade-sealed tx for one seal (grader and timestamp match the tx exactly), or None."""
    r = db.q1("SELECT id FROM txs WHERE type='grade-sealed' AND from_addr=? AND ts=? LIMIT 1", (grader, int(ts)))
    return r["id"] if r else None

def agent_view(a, limit=50):
    """One Agent in the copy: its pending answers, its seals on pending answers (with the seal tx when archived) and its
    settled jury seats and settled answers with the jurors' reasons. None without a usable copy."""
    if not usable(): return None
    d = current(); ix = index(); ep = d.get("epoch")
    from . import analytics as A
    nm = A.forum_names()
    mine = sorted((x for x in (row_of(r.get("id")) for r in ix["by_author"].get(a, [])) if x), key=lambda r: (r["need"], -(r["born"] or 0)))
    x = ix["by_g"].get(a) or dict(seals=0, qual=0, rows=[])
    seals = sorted(x["rows"], key=lambda s: -s[1])
    ids = {}
    if seals:
        ts = [s[1] for s in seals[:limit]]
        for r in db.q(f"SELECT id, ts FROM txs WHERE type='grade-sealed' AND from_addr=? AND ts IN ({','.join('?' * len(ts))})", (a, *ts)): ids.setdefault(r["ts"], r["id"])
    sv = [dict(answer=s[0], ts=s[1], counting=s[2], trusted=s[3], need=s[4], author=s[5], author_name=nm.get(s[5]), tx=ids.get(s[1])) for s in seals[:limit]]
    seats = [dict(answer=s.get("id"), author=s.get("author"), author_name=nm.get(s.get("author")), close=s.get("close"), passed=s.get("passed"),
                  aligned=j.get("aligned"), score=j.get("s"), reason=j.get("r"), trusted=j.get("t")) for s, j in ix["seats"].get(a, [])]
    settled = [dict(answer=s.get("id"), close=s.get("close"), passed=s.get("passed"), expired=s.get("expired"),
                    jury=[dict(grader=j.get("g"), name=nm.get(j.get("g")), aligned=j.get("aligned"), score=j.get("s"), reason=j.get("r"), trusted=j.get("t")) for j in s.get("jury") or []])
               for s in ix["settled_by"].get(a, [])]
    return dict(pending=mine[:limit], pending_count=len(mine), seals=sv, seals_count=x["seals"], seals_counting=x["qual"],
                jury_seats=seats, settled=settled, quorum=grade_quorum(d), epoch=ep,
                upstream_as_of=d.get("as_of"), fetched_at=d.get("fetched_at"), stale=stale())

def row_of(answer):
    """The pending row for an answer id in the copy (a dict from queue_rows), or None."""
    if not usable(): return None
    if _cur.get("qix") is None: _cur["qix"] = {r["id"]: r for r in queue_rows()}
    return _cur["qix"].get(answer)


def seal_facts(t0=None, t1=None):
    """{grader: (seals, qualifying)} from the seal store (every seal POAScan saw in minepoa's list, kept SEAL_KEEP_DAYS),
    by seal time in [t0, t1). q is the latest value seen. Empty before the first read."""
    w, a = [], []
    if t0 is not None: w.append("ts >= ?"); a.append(int(t0))
    if t1 is not None: w.append("ts < ?"); a.append(int(t1))
    try: rs = db.q("SELECT grader AS g, COUNT(*) AS n, SUM(q) AS k FROM grading_seals" + (" WHERE " + " AND ".join(w) if w else "") + " GROUP BY grader", tuple(a))
    except Exception: return {}
    return {r["g"]: (int(r["n"] or 0), int(r["k"] or 0)) for r in rs}

def unconfirmed_set(addrs):
    """The addresses among addrs that are tagged Unconfirmed (POAScan counts them established, minepoa's list does not)."""
    if not usable(): return frozenset()
    return frozenset(a for a in addrs if established_check(a)[0] == "conflict")
