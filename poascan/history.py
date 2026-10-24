"""Full address history from the archive (keyset paging) and grading assignments per grader from the close records."""
import base64, collections, json, threading, time
from . import db, analytics as A
from . import segments as S

LIMIT_MAX = 200

def enc(*k): return base64.urlsafe_b64encode(json.dumps(list(k), separators=(",", ":")).encode()).decode().rstrip("=")

def dec(c, n):
    """Opaque cursor -> its n key parts, or ValueError."""
    try:
        v = json.loads(base64.urlsafe_b64decode(c + "=" * (-len(c) % 4)).decode())
        if isinstance(v, list) and len(v) == n: return v
    except Exception: pass
    raise ValueError("bad cursor")

def txs_page(a, cursor=None, limit=50, typ=None):
    """Newest first by (ts, id). The cursor is the last row's key, so new txs never shift a page."""
    limit = max(1, min(LIMIT_MAX, int(limit))); w = ""; args = []
    if cursor:
        ts, tid = dec(cursor, 2); w = " AND (ts < ? OR (ts = ? AND id < ?))"; args = [int(ts), int(ts), str(tid)]
    if typ: w += " AND type = ?"; args.append(typ)
    sub = "SELECT * FROM txs INDEXED BY {ix} WHERE {col} = ?" + w + " ORDER BY ts DESC, id DESC LIMIT ?"
    sql = (f"SELECT * FROM ({sub.format(ix='txs_from_k', col='from_addr')}) UNION SELECT * FROM ({sub.format(ix='txs_to_k', col='to_addr')}) "
           "ORDER BY ts DESC, id DESC LIMIT ?")
    rows = db.q(sql, tuple([a] + args + [limit + 1] + [a] + args + [limit + 1, limit + 1]))
    nxt = enc(rows[limit - 1]["ts"], rows[limit - 1]["id"]) if len(rows) > limit else None
    return rows[:limit], nxt

def type_counts(a):
    r = db.q("SELECT type, COUNT(*) AS n FROM (SELECT id, type FROM txs WHERE from_addr = ? UNION SELECT id, type FROM txs WHERE to_addr = ?) GROUP BY type ORDER BY n DESC", (a, a))
    return {x["type"]: x["n"] for x in r}

def coverage(a):
    """What the archive holds for this address, and the evidence that it may hold less than the network."""
    g = db.q1("SELECT MIN(ts) AS t FROM txs") or {}
    s = db.q1("SELECT COUNT(*) AS n, MIN(ts) AS lo, MAX(ts) AS hi FROM txs WHERE from_addr = ?", (a,)) or {}
    t = db.q1("SELECT COUNT(*) AS n FROM txs WHERE to_addr = ? AND (from_addr IS NULL OR from_addr != ?)", (a, a)) or {}
    sent = s.get("n") or 0
    # 1.26.91: nonces restart at a genesis cut, so the nonce and its gap are per segment (never segment 1's 395 against
    # every tx sent in both). The top level keeps its fields for the current segment; by_segment has each one.
    by = {r["segment"]: r for r in db.q("SELECT segment, COUNT(*) AS n, MIN(ts) AS lo, MAX(ts) AS hi FROM txs WHERE from_addr = ? GROUP BY segment", (a,))}
    nz = {r["segment"]: r["m"] for r in db.q("SELECT t.segment AS segment, MAX(CAST(json_extract(d.json, '$.body.nonce') AS INTEGER)) AS m FROM txs t "
                                             "JOIN tx_detail d ON d.id = t.id WHERE t.from_addr = ? GROUP BY t.segment", (a,))}
    def one(n):
        r = by.get(n) or {}; k = r.get("n") or 0; m = nz.get(n)
        return dict(segment=n, label=S.label(n), archived=n != S.CURRENT, indexed_sent=k, first_ts=r.get("lo"), last_ts=r.get("hi"), highest_nonce=m,
                    nonce_gap=(m - k) if m is not None and m > k else 0 if m is not None else None, complete=False if m is not None and m > k else None)
    segs = [one(n) for n in reversed(S.NUMBERS) if n == S.CURRENT or n in by]
    cur = segs[0]
    return dict(archive_start_ts=g.get("t"), indexed=sent + (t.get("n") or 0), indexed_sent=sent, first_ts=s.get("lo"), last_ts=s.get("hi"),
                segment=S.CURRENT, highest_nonce=cur["highest_nonce"], nonce_gap=cur["nonce_gap"],
                complete=cur["complete"],    # never true: the newest bodies may not be archived, so the nonce is a lower bound
                by_segment=segs,
                note="Archive of the network's tx feed (newest 200, read every minute), its tx window and address reads; the network lists only an address's newest 100. "
                     "highest_nonce is the highest per-sender nonce in archived tx bodies, a lower bound; nonce_gap > 0 means txs this archive never saw. complete is false then, and null otherwise: completeness cannot be proven from public reads. "
                     "Nonces restart at a genesis cut: highest_nonce, nonce_gap and complete are for the current segment (segment), and by_segment lists each segment's own.")

# ---------------- grading assignments ----------------
_lock = threading.Lock(); _gx = {"key": None, "v": None}

def grading_index():
    """Per answer: latest pending record (close, kind, since, panel, grades or None) and settlement (close, passed, jury).
    Per grader: the answers they sit on (panel), sealed (grades) or judged (jury)."""
    raw = A.epochs_raw()
    # keyed on the parsed blob's identity and its stored ts; compared with == (an `is` on two int ids is never true,
    # which made every address page rebuild this index from the whole epochs blob)
    key = (S.selected(), id(raw), A.epochs_ts())
    with _lock:
        if _gx["key"] == key and _gx["v"]: return _gx["v"]
    rec, by = {}, {}
    for e in sorted(raw, key=lambda e: int(e.get("epoch", 0))):
        n = int(e.get("epoch", 0)); b = e.get("basis") or {}
        for t, p in (b.get("pending") or {}).items():
            gr = {x.get("grader"): x.get("ts") for x in p.get("grades") or []} if "grades" in p else None
            r = rec.setdefault(t, {}); r["p"] = (n, p.get("kind"), A.since_of(t, p), frozenset(p.get("panel") or []), gr)
            for g in list(p.get("panel") or []) + list(gr or {}): by.setdefault(g, set()).add(t)
        for s in b.get("settled") or []:
            t = s.get("answer")
            if not t: continue
            jy = frozenset(j.get("grader") for j in s.get("jury") or [])
            rec.setdefault(t, {})["s"] = (n, bool(s.get("passed")), jy)
            for g in jy: by.setdefault(g, set()).add(t)
    v = dict(rec=rec, by=by, last=max((int(e.get("epoch", 0)) for e in raw), default=None), last_ts=max((int(e.get("ts") or 0) for e in raw), default=None),
             merge=A.params().get("pending_merge_from_epoch"))
    with _lock: _gx.update(key=key, v=v)
    return v

def _one(g, t, r, ix, seal_ts, seal_as):
    p, s = r.get("p"), r.get("s"); last = ix["last"]
    close = s[0] if s else p[0] if p else None
    status = ("passed" if s[1] else "failed") if s else ("vanished" if p and p[0] < last else "pending") if p else "unrecorded"
    on = (g in p[3]) if p else None
    sealed, ev, ts = None, None, None
    if s and g in s[2]: sealed, ev = True, "jury"
    if p and p[4] is not None and g in p[4]: sealed, ev, ts = True, ev or "grades", p[4][g]
    if sealed is None and p and p[4] is None and p[1] == "short" and on: sealed, ev = True, "panel"   # before the merge a short row's panel listed its counted seals
    tx = None; sa = seal_as.get(t)
    if ts is not None: tx = (seal_ts.get(ts) or [None])[0] if len(seal_ts.get(ts) or []) == 1 else (sa or (None,))[0]
    elif sa: tx = sa[0]
    in_rec = sealed is True
    if sealed is not True and sa:
        sealed, ev, ts = True, "tx", sa[1]
        if ix.get("last_ts") and sa[1] > ix["last_ts"]: in_rec = None        # cast after the latest close: the next record decides
    if sealed is None and on and p and (p[4] is not None or s): sealed = False        # drawn seat, the record lists no seal from this grader
    return dict(answer=t, since=p[2] if p else None, status=status, close=close, seat=("panel" if on else "off_panel") if p else None,
                sealed=sealed, evidence=ev, in_record=in_rec if sealed else None, seal_tx=tx, seal_ts=ts)

# Per grader: the full sorted assignment list and its summary. An address page asks for it on every view (the Grading
# tab count), so it is cached, keyed on what it is built from: the grading index (epochs blob id and ts) and this
# grader's seal rows (count and highest rowid in txs and tx_detail; a late detail is an INSERT OR REPLACE, a new rowid).
# ASSIGN_TTL bounds the one input outside the key: an answer tx archived later can turn 'unrecorded' into a known epoch.
ASSIGN_TTL = 300
ASSIGN_MAX = 256
_alock = threading.Lock(); _acache = collections.OrderedDict()   # g -> (key, computed_at, out, summary, last)

def _seal_mark(g):
    r = db.q1("SELECT COUNT(*) AS n, MAX(t.rowid) AS r, MAX(d.rowid) AS dr FROM txs t LEFT JOIN tx_detail d ON d.id = t.id "
              "WHERE t.from_addr = ? AND t.type = 'grade-sealed'", (g,)) or {}
    return (r.get("n"), r.get("r"), r.get("dr"))

def _assign_all(g):
    ix = grading_index(); key = (_gx["key"], _seal_mark(g))
    with _alock:
        hit = _acache.get(g)
        if hit and hit[0] == key and time.time() - hit[1] < ASSIGN_TTL:
            _acache.move_to_end(g); return hit[2], hit[3], hit[4]
    rows = db.q("SELECT t.id, t.ts, json_extract(d.json, '$.body.assignment') AS a FROM txs t LEFT JOIN tx_detail d ON d.id = t.id "
                "WHERE t.from_addr = ? AND t.type = 'grade-sealed'", (g,))
    seal_ts, seal_as = {}, {}
    for x in rows:
        seal_ts.setdefault(x["ts"], []).append(x["id"])
        if x["a"]: seal_as[x["a"]] = (x["id"], x["ts"])
    ts_used = set()
    out = []
    for t in (ix["by"].get(g) or set()) | set(seal_as):
        o = _one(g, t, ix["rec"].get(t, {}), ix, seal_ts, seal_as)
        if o["since"] is None and o["status"] == "unrecorded":
            e = db.q1("SELECT epoch FROM txs WHERE id = ?", (t,)); o["since"] = e["epoch"] if e else None
            if o["since"] is not None and ix["last"] is not None and o["since"] > ix["last"]: o["status"] = "awaiting_close"; o["in_record"] = None
        if o["seal_tx"]: ts_used.add(o["seal_tx"])
        out.append(o)
    out.sort(key=lambda o: (o["since"] if o["since"] is not None else -1, o["answer"]), reverse=True)
    summary = dict(assignments=len(out), sealed=sum(1 for o in out if o["sealed"] is True), not_sealed=sum(1 for o in out if o["sealed"] is False),
                   unknown=sum(1 for o in out if o["sealed"] is None), seal_txs_indexed=len(rows),
                   seal_txs_linked=len(ts_used), not_in_record=sum(1 for o in out if o["evidence"] == "tx" and o["in_record"] is False and o["status"] != "awaiting_close"),
                   after_close=sum(1 for o in out if o["evidence"] == "tx" and (o["in_record"] is None or o["status"] == "awaiting_close")))
    with _alock:
        _acache[g] = (key, time.time(), out, summary, ix["last"]); _acache.move_to_end(g)
        while len(_acache) > ASSIGN_MAX: _acache.popitem(last=False)
    return out, summary, ix["last"]

def assignments(g, cursor=None, limit=50):
    """Grading assignments of one grader, newest origin first, keyset on (since, answer)."""
    limit = max(1, min(LIMIT_MAX, int(limit)))
    out, summary, last = _assign_all(g)
    if cursor:
        sv, ans = dec(cursor, 2); k = (int(sv), str(ans))
        out = [o for o in out if (o["since"] if o["since"] is not None else -1, o["answer"]) < k]
    page = [dict(o) for o in out[:limit]]   # copies: the cached rows are shared between requests
    nxt = enc(page[-1]["since"] if page[-1]["since"] is not None else -1, page[-1]["answer"]) if len(out) > limit else None
    return dict(summary, rows=page, next_cursor=nxt, as_of_close=last)
