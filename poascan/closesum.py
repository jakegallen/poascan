"""Per close summary rows (1.26.337).

Four close memos (epoch rows, backlog, jury series, settlement opens) walked every close's pending list after a boot or a
new close: about 80 pending lists of 3 to 6 MB JSON each, parsed once per memo. The pending list of a stored close never
changes, so what those memos need from it (counts, origin tallies, the previous close's carry and drops, the settled
answers' origins) is computed once per close, when a close first needs it (at ingest: indexer warm() after finalize),
and kept in close_sum. Readers fold the small rows; no pending list is parsed again unless the close itself changes.

A row is valid while its close and the previous close keep their stored sig, the params pending_merge_from_epoch it
used is unchanged, and none of the answers it filled from the first close they sat in (no since, no archived tx) has
since been archived (then since_fill would give the tx epoch, so the row is rebuilt). Read only; never served raw."""
import collections, json, threading
from . import db, closestore as CS

SUMV = 2
SCHEMA = """CREATE TABLE IF NOT EXISTS close_sum(kind TEXT NOT NULL, pos INTEGER NOT NULL, sig TEXT NOT NULL, psig TEXT NOT NULL,
  mf INTEGER, v INTEGER NOT NULL, unres TEXT NOT NULL, j TEXT NOT NULL, PRIMARY KEY(kind, pos))"""
_init = [False]; _lock = threading.RLock()
_mem = {}   # kind -> (key, rows): the folded rows of the last get(), so a memo read after a hit costs one sig query
stats = collections.Counter()

def init():
    if not _init[0]:
        db.conn().execute(SCHEMA); db.conn().commit(); _init[0] = True

def _mf(p):
    v = (p or {}).get("pending_merge_from_epoch")
    return int(v) if v is not None else None

class _Since:
    """since_of for one close's rows without since_fill(): a row's own since, else the archived tx epoch, else the first
    close (epoch) where that answer sat without since (pend_ix). The last kind is recorded in unres."""
    def __init__(self, kind, epoch_at):
        self.kind, self.epoch_at, self.memo, self.unres = kind, epoch_at, {}, set()
    def fill(self, tids):
        need = [t for t in dict.fromkeys(tids) if t not in self.memo]
        if not need: return
        for i in range(0, len(need), 500):
            ch = need[i:i + 500]
            for r in db.q(f"SELECT id, epoch FROM txs WHERE id IN ({','.join('?' * len(ch))})", tuple(ch)):
                if r["epoch"] is not None: self.memo[r["id"]] = int(r["epoch"])
        left = [t for t in need if t not in self.memo]
        for i in range(0, len(left), 500):
            ch = left[i:i + 500]
            for r in db.q(f"SELECT tx, MIN(pos0) AS p FROM pend_ix WHERE kind=? AND tx IN ({','.join('?' * len(ch))}) AND json_extract(v, '$.since') IS NULL GROUP BY tx", (self.kind, *ch)):
                ep = self.epoch_at.get(r["p"])
                if ep is not None: self.memo[r["tx"]] = int(ep); self.unres.add(r["tx"])
        for t in need:
            if t not in self.memo: self.memo[t] = 0; self.unres.add(t)   # since_fill().get(t, 0)
    def of(self, t, v):
        s = v.get("since") if isinstance(v, dict) else None
        if s is not None: return int(s)
        return self.memo[t]

def _pairs(c): return [[k, v] for k, v in c.items()]

def build_one(e, pend, prev_e, pp, sv, mf):
    """The summary of one close (e: its slim or full record, pend its pending list, prev_e/pp the previous close or None)."""
    from . import analytics as A
    pend = pend if isinstance(pend, dict) else (pend or {})
    b = e.get("basis") or {}; n = int(e["epoch"]); t = int(e["ts"])
    need = [x for x, v in pend.items() if not (isinstance(v, dict) and v.get("since") is not None)]
    if isinstance(pp, dict): need += [x for x, v in pp.items() if not (isinstance(v, dict) and v.get("since") is not None)]
    sv.fill(need)
    out = {}
    def part(name, fn):
        """One memo's part. A record the walk would choke on (it raised) leaves the part out: that memo then walks the
        pending lists as before and raises there, and the other memos are not affected."""
        try: out.update(fn())
        except Exception: out[name] = MISSING
    part("ep", lambda: _ep(e, pend, prev_e, pp, sv, b, n))
    part("bl", lambda: _bl(e, pend, prev_e, pp, sv, b, n, mf))
    part("jy", lambda: dict(jy=dict(queue=len(pend), empty=sum(1 for v in pend.values() if not (v or {}).get("panel")))))
    part("pin", lambda: _gov(pend, pp, sv, b))
    return out

MISSING = "missing"

def _ep(e, pend, prev_e, pp, sv, b, n):
    from . import analytics as A
    kinds = collections.Counter(v.get("kind") for v in pend.values())
    by_origin = collections.Counter(sv.of(x, v) for x, v in pend.items())
    sids = {s.get("answer") for s in (b.get("settled", []) or []) if s.get("answer")}
    dropped = None if pp is None else sum(1 for x in pp if x not in pend and x not in sids)
    gc = A.grade_counts(dict(e, basis=dict(b, pending=pend)) if "pending" not in b else e, int(prev_e["ts"]) if prev_e is not None else None)
    return dict(ep=dict(pending=len(pend), pending_short=kinds.get("short", 0), pending_appeal=kinds.get("appeal", 0),
                        pending_empty_panel=sum(1 for v in pend.values() if not v.get("panel")), pending_by_origin=sorted(by_origin.items()),
                        dropped=dropped, graders=len(gc), grades=sum(gc.values())))

def _bl(e, pend, prev_e, pp, sv, b, n, mf):
    """backlog_pend (analytics._backlog_pend): the per close part after the first, and this close's seal histogram."""
    from . import analytics as A
    bl = None
    if pp is not None:
        pn = int(prev_e["epoch"]); st = [x.get("answer") for x in b.get("settled") or [] if x.get("answer")]
        sset = set(st); grew = collections.Counter(); drop = collections.Counter(); unk = 0
        org_k = collections.Counter(); org_m = []
        for x in st:
            if x in pp: org_k[sv.of(x, pp[x])] += 1
            else: org_m.append(x)
        for x, v in pend.items():
            if x not in pp: continue
            a, _ = A._seals(pp[x], pn, mf); c, _ = A._seals(v, n, mf)
            if a is None or c is None: unk += 1
            elif c > a: grew[sv.of(x, v)] += 1
        for x, v in pp.items():
            if x not in pend and x not in sset: drop[sv.of(x, v)] += 1
        bl = dict(close=n, settled=len(st), org_k=_pairs(org_k), org_m=org_m, carried=sum(1 for x in pend if x in pp), grew=sum(grew.values()), grew_unknown=unk,
                  dropped=sum(drop.values()), grew_by_epoch=_pairs(grew), dropped_by_epoch=_pairs(drop))
    hist = {}; ex = []
    for x, v in pend.items():
        c, xx = A._seals(v, n, mf); o = sv.of(x, v); h = hist.setdefault(o, {k: 0 for k in A.SEAL_KEYS})
        h["unknown" if c is None else "4+" if c >= 4 else str(c)] += 1
        if c is not None: ex.append(xx)
    return dict(bl=bl, hist=_pairs(hist), exact=(all(ex) if ex else None))

def _gov(pend, pp, sv, b):
    """govv2 _settle_pend: the origin of each settled answer in the previous close's list, and the open rows by origin."""
    prev = pp if isinstance(pp, dict) else {}
    pin = [[s.get("answer"), sv.of(s.get("answer"), prev[s.get("answer")])] for s in b.get("settled") or [] if s.get("answer") in prev]
    opens = {}
    for aid, v in pend.items():
        if not isinstance(v, dict): continue
        o = opens.setdefault(sv.of(aid, v), [0, 0]); o[0] += 1; o[1] += 1 if v.get("panel") else 0
    return dict(pin=pin, opens=_pairs(opens))

def has(sm, key):
    """True when every close's row holds this memo's part (see build_one)."""
    return sm is not None and all(x.get(key, MISSING) != MISSING for x in sm)

def _decode(j):
    return json.loads(j)

def get(kind, raw, p):
    """[summary per close] of raw (epochs_raw of kind, in stored order), built for any close whose row is missing or stale.
    None when raw is not the stored rows in order (a reader then walks the pending lists as before)."""
    init(); mf = _mf(p)
    locs = [A_loc(e) for e in raw]
    if any(x is None or x[0] != kind or x[1] != i for i, x in enumerate(locs)): stats["fallback"] += 1; return None
    eps = [int(e.get("epoch", 0)) for e in raw]
    if any(b <= a for a, b in zip(eps, eps[1:])): stats["fallback"] += 1; return None   # pieces chain each close to the one before it
    sigs = [r["sig"] for r in db.q("SELECT sig FROM close_rows WHERE kind=? ORDER BY pos", (kind,))]
    if len(sigs) != len(raw): stats["fallback"] += 1; return None
    key = (tuple(sigs), mf, SUMV)
    hit = _mem.get(kind)
    if hit and hit[0] == key and not _unres_changed(hit[2]): stats["mem"] += 1; return hit[1]
    with _lock:
        have = {r["pos"]: r for r in db.q("SELECT pos, sig, psig, mf, v, unres, j FROM close_sum WHERE kind=?", (kind,))}
        out = [None] * len(raw); bad = []
        unres_all = {}
        for i, s in enumerate(sigs):
            r = have.get(i); ps = sigs[i - 1] if i else ""
            if r and r["sig"] == s and r["psig"] == ps and r["mf"] == mf and r["v"] == SUMV:
                u = json.loads(r["unres"])
                if u: unres_all[i] = u
                out[i] = r
            else: bad.append(i)
        if unres_all:
            arch = _archived([t for u in unres_all.values() for t in u])
            for i, u in unres_all.items():
                if any(t in arch for t in u): bad.append(i); out[i] = None
        bad = sorted(set(bad))
        if bad:
            epoch_at = {r["pos"]: r["epoch"] for r in db.q("SELECT pos, epoch FROM close_rows WHERE kind=?", (kind,))}
            rows = []; cache = {}
            for i in bad:
                sv = _Since(kind, epoch_at)
                pend = cache.pop(i, None) or (CS.pending(kind, i) or {})
                pp = None
                if i:
                    pp = cache.pop(i - 1, None)
                    if pp is None: pp = CS.pending(kind, i - 1) or {}
                try: v = build_one(raw[i], pend, raw[i - 1] if i else None, pp, sv, mf)
                except Exception: stats["fallback"] += 1; return None   # a record the walks would read differently: they run as before
                cache.clear(); cache[i] = pend   # the next close's previous list (sequential rebuild parses each list once)
                j = json.dumps(v); u = json.dumps(sorted(sv.unres))
                rows.append((kind, i, sigs[i], sigs[i - 1] if i else "", mf, SUMV, u, j))
                out[i] = dict(j=j, unres=u)
                if sv.unres: unres_all[i] = sorted(sv.unres)
                stats["built"] += 1
            cache.clear()
            db.write("INSERT OR REPLACE INTO close_sum(kind, pos, sig, psig, mf, v, unres, j) VALUES(?,?,?,?,?,?,?,?)", rows, many=True)
        db.write("DELETE FROM close_sum WHERE kind=? AND pos>=?", (kind, len(raw)))
        res = [_decode(r["j"]) for r in out]
        _mem[kind] = (key, res, sorted({t for u in unres_all.values() for t in u}))
        stats["read"] += 1
        return res

def A_loc(e): return getattr(e, "loc", None)

def _archived(tids):
    out = set(); tids = list(dict.fromkeys(tids))
    for i in range(0, len(tids), 500):
        ch = tids[i:i + 500]
        for r in db.q(f"SELECT id FROM txs WHERE id IN ({','.join('?' * len(ch))}) AND epoch IS NOT NULL", tuple(ch)): out.add(r["id"])
    return out

def _unres_changed(tids):
    return bool(tids) and bool(_archived(tids))

def warm(kind):
    """At ingest, after a close is stored: build the new close's row and fold it onto the stored states, through the
    memos themselves (so pages get their values without parsing a pending list). One memo at a time (close_memo gate)."""
    import logging
    from . import analytics as A, segments as S, receipts as R, cohorts as C, calibration as CB, governance as G, govv2 as G2
    done = 0
    for n in S.NUMBERS:
        if S.blob_kind(n) != kind: continue
        with S.use(n):
            for f in (A._epoch_pend, A._backlog_pend, G.jury_series, G2._settle_pend, R._close_index, C._cohorts, CB._close_part):
                try: f(); done += 1
                except Exception as e: logging.getLogger("closesum").warning("warm %s: %s", getattr(f, "__name__", f), e)
    return done

# ---------------------------------------------------------------- folded memos (receipts, cohorts, calibration)
# Memos that keep per answer state across closes (first and last close, cohort tracks, seal times) are a fold over the
# closes in order. The fold state after the last stored close is kept in close_fold, keyed by the sigs of the closes it
# folded, the params content and the since fill. A new close folds one pending list onto it; a boot unpickles it.
FOLDV = 1
FSCHEMA = """CREATE TABLE IF NOT EXISTS close_fold(name TEXT NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL, sigs TEXT NOT NULL,
  extra TEXT NOT NULL, v INTEGER NOT NULL, state BLOB NOT NULL, lite BLOB, PRIMARY KEY(name, kind))"""
_finit = [False]
_live = {}   # (name, kind) -> (n, sigs digest, extra, state): the last state this process folded (reuse= folds only)

def _fdig(sigs):
    import hashlib
    return hashlib.sha1("\n".join(sigs).encode()).hexdigest()

def fold(name, kind, raw, extra, start, step, finish, lite=None, reuse=None):
    """finish(state) of step(state, e, pend) over raw (epochs_raw of kind, stored order), from the stored state when it
    folded a prefix of these closes under the same extra (extra(n): the key for a fold of the first n closes). None when raw is not the stored rows in epoch order.
    lite(state): the smaller value finish also accepts; when no close is left to fold only it is unpickled (a boot then
    never materializes the full per answer state, which would stay as RSS after it is dropped).
    reuse(state): a copy step may mutate without touching state (step must copy what it changes). With it, a new close
    in a warm process folds onto reuse() of the state it already holds instead of unpickling a second full copy."""
    import pickle
    if not _finit[0]:
        c = db.conn(); c.execute(FSCHEMA)
        if "lite" not in {r[1] for r in c.execute("PRAGMA table_info(close_fold)")}: c.execute("ALTER TABLE close_fold ADD COLUMN lite BLOB")
        c.commit(); _finit[0] = True
    locs = [A_loc(e) for e in raw]
    if any(x is None or x[0] != kind or x[1] != i for i, x in enumerate(locs)): stats["fold_fallback"] += 1; return None
    eps = [int(e.get("epoch", 0)) for e in raw]
    if any(b <= a for a, b in zip(eps, eps[1:])): stats["fold_fallback"] += 1; return None
    sigs = [r["sig"] for r in db.q("SELECT sig FROM close_rows WHERE kind=? ORDER BY pos", (kind,))]
    if len(sigs) != len(raw): stats["fold_fallback"] += 1; return None
    exf = lambda n: json.dumps([extra(n) if callable(extra) else extra, FOLDV], sort_keys=True, default=str)
    ex = exf(len(raw))
    with _lock:
        r = db.q1("SELECT n, sigs, extra, v FROM close_fold WHERE name=? AND kind=?", (name, kind))
        st, n0 = None, 0
        ok = bool(r and r["n"] <= len(sigs) and r["extra"] == (ex if r["n"] == len(raw) else exf(r["n"])) and r["v"] == FOLDV and r["n"] <= len(sigs) and r["sigs"] == _fdig(sigs[:r["n"]]))
        if ok and lite is not None and int(r["n"]) == len(raw):
            try: v = _load(name, kind, "lite"); stats["fold_lite"] += 1; return finish(v)
            except Exception: pass
        lv0 = _live.get((name, kind)) if reuse is not None else None
        if st is None and lv0 is not None and lv0[0] <= len(sigs) and lv0[1] == _fdig(sigs[:lv0[0]]) and lv0[2] == (ex if lv0[0] == len(raw) else exf(lv0[0])):
            if lv0[0] == len(raw) and r is not None and int(r["n"]) == len(raw): stats["fold_live"] += 1; return finish(lv0[3])
            st = reuse(lv0[3]); n0 = lv0[0]; stats["fold_live"] += 1; ok = False
        if ok and st is None:
            try: st = _load(name, kind, "state"); n0 = int(r["n"]); stats["fold_hit"] += 1
            except Exception: st = None
        if st is None: st = start(); n0 = 0
        for i in range(n0, len(raw)):
            step(st, raw[i], CS.pending(kind, i)); stats["fold_step"] += 1
        if n0 != len(raw) or r is None:
            lv = lite(st) if lite is not None else None
            _save(name, kind, len(raw), _fdig(sigs), ex, st, lv)
            if lite is not None: st = None; return finish(lv)
        if reuse is not None: _live[(name, kind)] = (len(raw), _fdig(sigs), ex, st)
        return finish(st)

class _BlobFile:
    """A readonly sqlite3.Blob as the file pickle.load reads, so a stored state is unpickled without a bytes copy of it."""
    def __init__(self, b): self.b = b
    def read(self, n=-1): return self.b.read(n) if n is not None and n >= 0 else self.b.read()
    def readinto(self, m):
        d = self.b.read(len(m)); m[:len(d)] = d; return len(d)
    def readline(self):
        out = bytearray()
        while True:
            c = self.b.read(1)
            if not c: return bytes(out)
            out += c
            if c == b"\n": return bytes(out)

def _load(name, kind, col):
    import pickle
    c = db.conn(); r = c.execute("SELECT rowid, " + col + " IS NULL FROM close_fold WHERE name=? AND kind=?", (name, kind)).fetchone()
    if not r or r[1]: raise KeyError(col)
    with c.blobopen("close_fold", col, r[0], readonly=True) as b:
        return pickle.load(_BlobFile(b))

def _save(name, kind, n, sig, ex, st, lv):
    """The state (and its lite value) pickled to a temp file, then copied into zeroblobs in chunks: no bytes copy of a
    30 to 45 MB state is held, and the statement binds only sizes (db._big_conn, closed right after)."""
    import pickle, tempfile
    fs = []
    try:
        for i, v in enumerate((st, lv)):
            f = tempfile.TemporaryFile(); fs.append(f)
            if i == 0 or lv is not None: pickle.dump(v, f, protocol=pickle.HIGHEST_PROTOCOL)
        sizes = [f.tell() for f in fs]
        with db._wlock:
            db.GEN[0] += 1; c = db._big_conn()
            try:
                c.execute("BEGIN IMMEDIATE")
                c.execute("INSERT OR REPLACE INTO close_fold(name, kind, n, sigs, extra, v, state, lite) VALUES(?,?,?,?,?,?,zeroblob(?),?)",
                          (name, kind, n, sig, ex, FOLDV, sizes[0], None))
                rid = c.execute("SELECT rowid FROM close_fold WHERE name=? AND kind=?", (name, kind)).fetchone()[0]
                if lv is not None: c.execute("UPDATE close_fold SET lite=zeroblob(?) WHERE rowid=?", (sizes[1], rid))
                for col, f in (("state", fs[0]), ("lite", fs[1])):
                    if col == "lite" and lv is None: continue
                    f.seek(0)
                    with c.blobopen("close_fold", col, rid) as b:
                        while True:
                            ch = f.read(1 << 20)
                            if not ch: break
                            b.write(ch)
                c.commit()
            except Exception:
                c.rollback(); raise
            finally:
                c.close()
    finally:
        for f in fs: f.close()

def since_digest(n):
    """sha1 of since_fill() for the answers first seen without since in the first n closes: what since_of gave a fold of
    those closes. An answer that first lacks since at a later close does not change an earlier fold."""
    import hashlib
    from . import analytics as A
    sf = A.since_fill(); fp = A.since_first_pos()
    return hashlib.sha1(json.dumps(sorted((t, v) for t, v in sf.items() if fp.get(t, -1) < n)).encode()).hexdigest()
