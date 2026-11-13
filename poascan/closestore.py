"""Close records on disk, one row per close (1.26.235).

The close list grows by one record every close and every record repeats the whole pending list, so the parsed copy kept in
memory grew about 2.5 MB per close (57 MB at E23). Each close is now a row of close_rows: the record without
basis.pending ("slim", a few KB), its pending list as its own JSON text, where "pending" sat among the basis keys, and the
record's canonical sha256 and byte count (records.py). Only the slim records stay in memory; a close's pending list is
read from its row when a page needs it (a small LRU), and pend_ix answers "this answer's row at this close" without
parsing a whole close.

The close_rows table is the store (1.26.325). The raw ~15 MB minepoa close body is checked against the index sha256
and byte count at fetch, then dropped; only the parsed fields stay (slim record, pending list, rewards, totals, and
Answer pay and Grading pay when published), plus that raw sha256 and byte count for verification. The blobs row is a
small stub so readers still have a ts and generation. A leftover full-list blob from an older build is pruned once the
rows are current, or used to rebuild the rows if they are behind. close_meta records which blob copy the rows came from
(its ts and byte length)."""
import codecs, collections, hashlib, json, threading
from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS close_rows(kind TEXT NOT NULL, pos INTEGER NOT NULL, epoch INTEGER, ts INTEGER, slim TEXT NOT NULL,
  pending TEXT, ppos INTEGER, sha256 TEXT NOT NULL, nbytes INTEGER NOT NULL, sig TEXT NOT NULL, raw_sha256 TEXT, raw_bytes INTEGER, PRIMARY KEY(kind, pos));
CREATE TABLE IF NOT EXISTS close_meta(kind TEXT PRIMARY KEY, src_ts INTEGER, src_len INTEGER, n INTEGER NOT NULL, ver INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS pend_ix(kind TEXT NOT NULL, tx TEXT NOT NULL, pos0 INTEGER NOT NULL, pos1 INTEGER NOT NULL, v TEXT NOT NULL,
  PRIMARY KEY(kind, tx, pos0)) WITHOUT ROWID;
"""
VER = 1
STUB_V = 2   # 1.26.325: close_rows are canonical; the blobs row is a stub, not the close list
STUB_MAX = 1024
CHUNK = 4 << 20
_lock = threading.RLock()   # one writer or rebuild at a time; readers that find the rows behind the blob wait here
_ver = collections.Counter()   # kind -> bumped on every rows write (in-process; the slim copy and the LRU key on it)

def init():
    db.conn().executescript(SCHEMA); db.conn().commit()
    cols = {r["name"] for r in db.q("PRAGMA table_info(close_rows)")}
    if "raw_sha256" not in cols:
        c = db.conn(); c.execute("ALTER TABLE close_rows ADD COLUMN raw_sha256 TEXT"); c.execute("ALTER TABLE close_rows ADD COLUMN raw_bytes INTEGER"); c.commit()

def kinds():
    ks = [r["kind"] for r in db.q("SELECT kind FROM blobs WHERE kind='epochs' OR kind LIKE 'epochs:s%'")]
    for r in db.q("SELECT DISTINCT kind FROM close_rows"):
        if r["kind"] not in ks: ks.append(r["kind"])
    return ks

def stub_obj(n):
    return {"v": STUB_V, "rows": "close_rows", "n": int(n)}

def is_stub(obj):
    return isinstance(obj, dict) and obj.get("v") == STUB_V and obj.get("rows") == "close_rows"

def rows_canonical(kind):
    """True when close_rows are the store and the blobs row is (or should be) a stub."""
    m = meta(kind)
    return bool(m and int(m["ver"]) >= STUB_V)

def count(kind):
    m = meta(kind)
    if m: return int(m["n"])
    r = db.q1("SELECT COUNT(*) AS n FROM close_rows WHERE kind=?", (kind,))
    return int(r["n"]) if r else 0

# ---------------------------------------------------------------- split and join
def split(e):
    """(slim text, pending text or None, ppos or None) of one close record. The slim record keeps every other key in order."""
    b = e.get("basis") if isinstance(e, dict) else None
    if not isinstance(b, dict) or "pending" not in b: return json.dumps(e), None, None
    keys = list(b); ppos = keys.index("pending")
    sb = {k: v for k, v in b.items() if k != "pending"}
    slim = {k: (sb if k == "basis" else v) for k, v in e.items()}
    return json.dumps(slim), json.dumps(b["pending"]), ppos

def join(slim, pending, ppos):
    """The full record from a slim record (not changed) and its pending value, keys in the stored order."""
    if ppos is None: return slim
    b = slim.get("basis") or {}; items = list(b.items()); items.insert(ppos, ("pending", pending))
    return {k: (dict(items) if k == "basis" else v) for k, v in slim.items()}

def _row(kind, pos, e, raw_sha256=None, raw_bytes=None):
    from . import records as RR
    if isinstance(e, dict) and "_raw" in e:
        e = dict(e); raw = e.pop("_raw")
        if raw and isinstance(raw, (tuple, list)) and len(raw) >= 2:
            raw_sha256 = raw_sha256 or raw[0]; raw_bytes = raw_bytes if raw_bytes is not None else raw[1]
    full = json.dumps(e); slim, pend, ppos = split(e); cb = RR.canonical(e)
    ep = e.get("epoch") if isinstance(e, dict) else None; ts = e.get("ts") if isinstance(e, dict) else None
    return (kind, pos, int(ep) if isinstance(ep, (int, float)) else None, int(ts) if isinstance(ts, (int, float)) else None, slim, pend, ppos,
            RR.sha256(cb), len(cb), hashlib.sha1(full.encode("utf-8", "surrogatepass")).hexdigest(),
            (str(raw_sha256).lower() if raw_sha256 else None), (int(raw_bytes) if raw_bytes is not None else None))

def sig_of(e): return hashlib.sha1(json.dumps(e).encode("utf-8", "surrogatepass")).hexdigest()

# ---------------------------------------------------------------- the blob copy rows are built from
def blob_src(kind):
    """(ts, byte length) of a blobs row, read without loading its text, or None."""
    c = db.conn(); r = c.execute("SELECT rowid, ts FROM blobs WHERE kind=?", (kind,)).fetchone()
    if not r: return None
    try:
        with c.blobopen("blobs", "json", r[0], readonly=True) as b: n = len(b)
    except Exception:
        n = (c.execute("SELECT length(CAST(json AS BLOB)) FROM blobs WHERE kind=?", (kind,)).fetchone() or [0])[0] or 0
    return (r[1], n)

def meta(kind):
    return db.q1("SELECT src_ts, src_len, n, ver FROM close_meta WHERE kind=?", (kind,))

_gen = {}   # kind -> db.blob_gen when the rows were last matched to the blob in this process (two writes in one second)
def current(kind, src=None):
    m = meta(kind); src = src or blob_src(kind)
    ok = bool(m and src and int(m["ver"]) in (VER, STUB_V) and (m["src_ts"], m["src_len"]) == tuple(src))
    if ok and int(m["ver"]) >= STUB_V and src[1] > STUB_MAX:
        ok = False   # a full-list blob an older build wrote after the stub; rebuild from it
    g = db.blob_gen(kind)
    if ok and _gen.setdefault(kind, g) != g: ok = False
    return ok

def iter_blob(kind, strict=False):
    """Each element of a blobs row's JSON array, decoded one at a time from chunks of the stored text. strict: a stored
    value that is neither an array nor null raises ValueError instead of being iterated."""
    c = db.conn(); r = c.execute("SELECT rowid FROM blobs WHERE kind=?", (kind,)).fetchone()
    if not r: return
    dec = json.JSONDecoder(); ud = codecs.getincrementaldecoder("utf-8")("surrogatepass")
    with c.blobopen("blobs", "json", r[0], readonly=True) as b:
        buf, i, eof, started = "", 0, False, False
        def more():
            nonlocal buf, i, eof
            ch = b.read(CHUNK); eof = not ch
            buf = buf[i:] + ud.decode(ch, final=eof); i = 0
        def skip_ws():
            nonlocal i
            while True:
                while i < len(buf) and buf[i] in " \t\n\r": i += 1
                if i < len(buf) or eof: return
                more()
        more(); skip_ws()
        if buf[i:i + 1] != "[":
            v = json.loads(buf[i:] + (b.read() or b"").decode("utf-8", "surrogatepass") or "null")
            if is_stub(v):
                return
            if strict and v and not isinstance(v, list): raise ValueError("close records: not a list")
            yield from (v or []); return
        i += 1; skip_ws()
        if buf[i:i + 1] == "]": return
        while True:
            while True:
                try: v, j = dec.raw_decode(buf, i); break
                except json.JSONDecodeError:
                    if eof: raise
                    more()
            i = j; yield v; skip_ws()
            ch = buf[i:i + 1]
            if ch == "]": return
            if ch != ",": raise ValueError("close records: expected , or ]")
            i += 1; skip_ws()

# ---------------------------------------------------------------- writes
INS = "INSERT OR REPLACE INTO close_rows(kind, pos, epoch, ts, slim, pending, ppos, sha256, nbytes, sig, raw_sha256, raw_bytes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"

def rebuild(kind):
    """Rows of one segment from its blob, one close at a time (idempotent: a no-op when close_meta matches the blob).
    1.26.325: a stub blob must never wipe close_rows."""
    with _lock:
        src = blob_src(kind)
        if src is None or current(kind, src): return False
        if src and src[1] <= STUB_MAX:
            obj, _ = db.get_blob(kind)
            if is_stub(obj):
                n = count(kind)
                _finish(kind, src, n, ver=STUB_V)
                return False
        c = db.conn(); n = 0; have = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=?", (kind,))}
        for e in iter_blob(kind):
            if have.get(n) != sig_of(e):
                with db._wlock: c.execute(INS, db._clean(_row(kind, n, e))); c.commit()
            n += 1
        _finish(kind, src, n)
        return True

def write(kind, rows):
    """Write the changed close_rows only (by sig), publish a stub blob, then pend_ix and close_meta. 1.26.325:
    the full list is not stored in blobs."""
    with _lock:
        have = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=?", (kind,))}
        ch = [_row(kind, i, e) for i, e in enumerate(rows) if have.get(i) != sig_of(e)]
        if ch: db.write(INS, ch, many=True)
        put_stub(kind, len(rows))
        _finish(kind, blob_src(kind), len(rows), ver=STUB_V)

def _finish(kind, src, n, ver=None):
    db.write_tx([("DELETE FROM close_rows WHERE kind=? AND pos>=?", (kind, n), False)])
    _index(kind)
    ver = VER if ver is None else ver
    db.write("INSERT OR REPLACE INTO close_meta(kind, src_ts, src_len, n, ver) VALUES(?,?,?,?,?)", (kind, src[0] if src else None, src[1] if src else None, n, ver))
    _ver[kind] += 1; _lru.clear(); _gen[kind] = db.blob_gen(kind)

def retag(kind):
    """After db.touch_blob: the rows stand for the blob's new stored time."""
    with _lock:
        m = meta(kind); src = blob_src(kind)
        if m and src and m["src_len"] == src[1] and int(m["ver"]) in (VER, STUB_V): db.write("UPDATE close_meta SET src_ts=? WHERE kind=?", (src[0], kind))

def _write_row(row):
    """One close_rows insert on its own connection, so it can run while iter_blob still holds the read blob.
    A changed close is written and dropped before the next one is parsed."""
    c = db._big_conn()
    try:
        with db._wlock:
            db.GEN[0] += 1
            try:
                c.execute("BEGIN IMMEDIATE"); c.execute(INS, db._clean(row)); c.commit()
            except Exception:
                c.rollback(); raise
    finally:
        c.close()

def apply_sigs(kind, sigs):
    """After the blob is stored: rewrite only the closes whose sha1 changed, then pend_ix and close_meta.
    sigs is sha1(json.dumps(record)) per position, the same text sig_of stores. One close is parsed at a time."""
    with _lock:
        have = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=? ORDER BY pos", (kind,))}
        n = 0
        for e in iter_blob(kind):
            if have.get(n) != (sigs[n] if n < len(sigs) else None): _write_row(_row(kind, n, e))
            n += 1
        _finish(kind, blob_src(kind), n)

def _index(kind):
    """pend_ix: for each answer, the runs of consecutive closes where its pending row is unchanged (rows grow with distinct
    rows, not with closes times answers). Rebuilt from the rows, one close's pending at a time.
    1.26.271: completed runs spill to a temp file and insert in batches, so the JSON of every historical pending row
    is not one Python list on top of the close just parsed."""
    import os, tempfile
    c = db.conn(); run = {}
    fd, path = tempfile.mkstemp(prefix="poa-pend-", suffix=".jsonl"); os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            def emit(t, o): f.write(json.dumps([kind, t, o[0], o[1], o[2]], separators=(",", ":")) + "\n")
            for r in c.execute("SELECT pos, pending FROM close_rows WHERE kind=? ORDER BY pos", (kind,)):   # 1.26.236: one row at a time (fetchall held every close's pending text at once)
                p = json.loads(r[1]) if r[1] else {}; p = p if isinstance(p, dict) else {}; pos = r[0]; nxt = {}
                for t, v in p.items():
                    vt = json.dumps(v); o = run.get(t)
                    if o and o[1] == pos - 1 and o[2] == vt: o[1] = pos; nxt[t] = o
                    else:
                        if o: emit(t, o)
                        nxt[t] = [pos, pos, vt]
                for t, o in run.items():
                    if t not in nxt: emit(t, o)
                run = nxt
            for t, o in run.items(): emit(t, o)
        w = db._big_conn()
        try:
            with db._wlock:
                db.GEN[0] += 1
                try:
                    w.execute("BEGIN IMMEDIATE")
                    w.execute("DELETE FROM pend_ix WHERE kind=?", (kind,))
                    buf = []
                    with open(path, encoding="utf-8") as f:
                        for line in f:
                            buf.append(db._clean(tuple(json.loads(line))))
                            if len(buf) >= 300:
                                w.executemany("INSERT OR REPLACE INTO pend_ix(kind, tx, pos0, pos1, v) VALUES(?,?,?,?,?)", buf); buf.clear()
                    if buf: w.executemany("INSERT OR REPLACE INTO pend_ix(kind, tx, pos0, pos1, v) VALUES(?,?,?,?,?)", buf)
                    w.commit()
                except Exception:
                    w.rollback(); raise
        finally:
            w.close()
    finally:
        try: os.unlink(path)
        except OSError: pass


def put_stub(kind, n):
    """Replace the blobs row with a small pointer at close_rows. Never writes the close list."""
    db.put_blob(kind, stub_obj(n))

def touch(kind):
    """Move the stub (or leftover blob) stored time without rewriting close_rows."""
    db.touch_blob(kind)

def append_records(kind, recs, raw_map=None, reindex=True):
    """Append parsed close records that are not already stored for this kind, oldest first. raw_map is
    {epoch: (raw_sha256, raw_bytes)} from the minepoa index (the fetched body's hash, not the canonical hash).
    reindex False: caller will finalize() once after a batch."""
    recs = [e for e in recs if isinstance(e, dict) and e.get("epoch") is not None]
    if not recs and not reindex: return 0
    with _lock:
        have_ep = {int(r["epoch"]) for r in db.q("SELECT epoch FROM close_rows WHERE kind=?", (kind,)) if r["epoch"] is not None}
        have = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=? ORDER BY pos", (kind,))}
        pos = (max(have) + 1) if have else 0
        added = 0
        for e in sorted(recs, key=lambda e: int(e["epoch"])):
            ep = int(e["epoch"]); raw = (raw_map or {}).get(ep)
            if ep in have_ep:
                if raw:
                    db.write("UPDATE close_rows SET raw_sha256=COALESCE(raw_sha256, ?), raw_bytes=COALESCE(raw_bytes, ?) WHERE kind=? AND epoch=?",
                             (str(raw[0]).lower(), int(raw[1]), kind, ep))
                continue
            raw_sha, raw_b = (raw[0], raw[1]) if raw else (None, None)
            _write_row(_row(kind, pos, e, raw_sha256=raw_sha, raw_bytes=raw_b))
            have_ep.add(ep); pos += 1; added += 1
        if reindex:
            n = db.q1("SELECT COUNT(*) AS n FROM close_rows WHERE kind=?", (kind,))["n"]
            put_stub(kind, n)
            _finish(kind, blob_src(kind), n, ver=STUB_V)
        return added

def finalize(kind):
    """Rebuild pend_ix and publish the stub after a batch of append_records(..., reindex=False)."""
    with _lock:
        n = db.q1("SELECT COUNT(*) AS n FROM close_rows WHERE kind=?", (kind,))["n"]
        put_stub(kind, n)
        _finish(kind, blob_src(kind), n, ver=STUB_V)

def apply_spill(kind, path, sigs):
    """Read a spilled JSON array of close records one object at a time, write changed close_rows, publish a stub.
    1.26.325: the spill file is not copied into blobs."""
    recs = []
    with open(path, "rb") as f:
        raw = f.read()
    recs = json.loads(raw.decode("utf-8", "surrogatepass"))
    if not isinstance(recs, list):
        raise ValueError("close records: not a list")
    write(kind, recs)

def prune_raw_blobs():
    """Replace any leftover full close-list blobs with stubs once close_rows hold the same closes. Idempotent.
    Never deletes close_rows, txs, or other served tables."""
    init(); changed = []
    for k in kinds():
        src = blob_src(k)
        n = db.q1("SELECT COUNT(*) AS n FROM close_rows WHERE kind=?", (k,))
        n = int(n["n"]) if n else 0
        if n == 0 and not (src and src[1] and src[1] > STUB_MAX):
            continue
        if src and src[1] <= STUB_MAX:
            obj, _ = db.get_blob(k)
            if is_stub(obj):
                m = meta(k)
                if not (m and int(m["ver"]) >= STUB_V):
                    _finish(k, src, n if n else int(obj.get("n") or 0), ver=STUB_V)
                    changed.append(k)
                continue
        if n == 0:
            continue   # do not drop a large blob that has no rows behind it
        put_stub(k, n)
        _finish(k, blob_src(k), n, ver=STUB_V)
        changed.append(k)
    return changed

def migrate():
    """Startup: every segment's rows current with its blob (streamed; nothing to do once they are).
    1.26.325: after the rows are current, leftover full-list blobs are replaced with stubs."""
    init(); done = []
    for k in kinds():
        if rebuild(k): done.append(k)
    done.extend(prune_raw_blobs())
    return done

# ---------------------------------------------------------------- reads
def ver(kind): return _ver[kind]

class Basis(dict):
    """basis of a cached slim close without its settled list in memory (1.26.328). "settled" still reads as a key:
    b.get("settled"), b["settled"], "settled" in b, items(), keys(), iteration, dict(b) and json.dumps(b) load it from
    the close row through the 2-close settled LRU. Any other key is a plain dict read, so walking every close for
    graders_served, challenge_eligible, marks and the like never parses a stored slim (1.26.327 re-parsed the whole
    slim of every close on each e.get("basis"), about 112 MB of JSON per walk)."""
    __slots__ = ("src",)   # (kind, pos, index of settled among the stored basis keys)

    def _st(self): return settled(self.src[0], self.src[1])
    def __contains__(self, k): return k == "settled" or dict.__contains__(self, k)
    def __getitem__(self, k): return self._st() if k == "settled" else dict.__getitem__(self, k)
    def get(self, k, default=None): return self._st() if k == "settled" else dict.get(self, k, default)
    def __len__(self): return dict.__len__(self) + 1
    def keys(self):
        ks = list(dict.keys(self)); ks.insert(min(self.src[2], len(ks)), "settled"); return ks
    def __iter__(self): return iter(self.keys())
    def items(self):
        it = list(dict.items(self)); it.insert(min(self.src[2], len(it)), ("settled", self._st())); return it
    def values(self): return [v for _, v in self.items()]
    def copy(self): return dict(self.items())
    def __eq__(self, o): return dict(self.items()) == (dict(o.items()) if isinstance(o, dict) else o)
    __hash__ = None
    def __repr__(self): return "Basis(%r)" % (dict(dict.items(self)),)
    def __reduce__(self): return (dict, (self.items(),))

class Close(dict):
    """A slim close record plus where its row is (kind, pos, ppos), so pending_of and full_close find the close even
    after a newer copy replaced it. 1.26.328: basis is a Basis, which keeps settled on disk until a reader asks for it."""
    __slots__ = ("loc",)

def slim(kind):
    """[slim record (Close)] of one segment, in stored order. basis.settled stays on disk (Basis) until read."""
    out = []
    for r in db.q("SELECT pos, ppos, slim FROM close_rows WHERE kind=? ORDER BY pos", (kind,)):
        v = json.loads(r["slim"])
        if isinstance(v, dict):
            b = v.get("basis")
            if isinstance(b, dict) and "settled" in b:
                keys = list(b); nb = Basis((k, val) for k, val in b.items() if k != "settled")
                nb.src = (kind, r["pos"], keys.index("settled")); v["basis"] = nb
            v = Close(v); v.loc = (kind, r["pos"], r["ppos"], _ver[kind])
        out.append(v)
    return out

def slim_at(kind, pos):
    """The full stored slim of one close (includes basis.settled; still no pending)."""
    r = db.q1("SELECT pos, ppos, slim FROM close_rows WHERE kind=? AND pos=?", (kind, pos))
    if not r or r["slim"] is None:
        return None
    v = json.loads(r["slim"])
    if isinstance(v, dict):
        v = Close(v); v.loc = (kind, r["pos"], r["ppos"], _ver[kind])
    return v

def ensure(kind):
    """Rows current with the blob (rebuilt from it when not: first boot of 1.26.235, or a blob an older build wrote)."""
    if not current(kind): rebuild(kind)

_lru = collections.OrderedDict(); LRU_MAX = 2   # (kind, pos, ver) -> parsed pending of one close
_settled_lru = collections.OrderedDict(); SETTLED_LRU_MAX = 2   # (kind, pos, ver) -> basis.settled of one close
def pending(kind, pos, ver=None):
    """The parsed pending list of one close. ver: the rows version a slim record was read at (None: now); a record from
    before a rewrite reads the current row of its position, which a rewrite only changes when the close itself changed."""
    k = (kind, pos, _ver[kind])
    with _lock:
        hit = _lru.get(k)
        if hit is not None: _lru.move_to_end(k); return hit[0]
    r = db.q1("SELECT pending, ppos FROM close_rows WHERE kind=? AND pos=?", (kind, pos))
    # 1.26.327: do not intern via json.dumps of every row; that doubled the peak while walking E58 to E78.
    v = json.loads(r["pending"]) if r and r["pending"] is not None else None
    with _lock:
        _lru[k] = (v,)
        while len(_lru) > LRU_MAX: _lru.popitem(last=False)
    return v

def settled(kind, pos, ver=None):
    """basis.settled of one close, from its stored slim. Only two parsed lists are kept."""
    k = (kind, pos, _ver[kind])
    with _lock:
        hit = _settled_lru.get(k)
        if hit is not None: _settled_lru.move_to_end(k); return hit[0]
    r = db.q1("SELECT slim FROM close_rows WHERE kind=? AND pos=?", (kind, pos))
    v = None
    if r and r["slim"] is not None:
        sl = json.loads(r["slim"])
        if isinstance(sl, dict):
            b = sl.get("basis")
            if isinstance(b, dict):
                v = b.get("settled")
    with _lock:
        _settled_lru[k] = (v,)
        while len(_settled_lru) > SETTLED_LRU_MAX: _settled_lru.popitem(last=False)
    return v

def release():
    """Drop parsed pending and settled lists so a walk of every close does not keep the last two."""
    with _lock:
        _lru.clear()
        _settled_lru.clear()

def pending_get(kind, pos, txs):
    """{tx: row} of the given answers in one close's pending list (pend_ix; no close parsed)."""
    txs = [t for t in dict.fromkeys(txs) if t]; out = {}
    for i in range(0, len(txs), 500):
        ch = txs[i:i + 500]
        for r in db.q(f"SELECT tx, v FROM pend_ix WHERE kind=? AND pos0<=? AND pos1>=? AND tx IN ({','.join('?' * len(ch))})", (kind, pos, pos, *ch)):
            out[r["tx"]] = json.loads(r["v"])
    return out

def canon(kind):
    """[(pos, sha256, nbytes)] of one segment (records.index without a parse)."""
    return [(r["pos"], r["sha256"], r["nbytes"]) for r in db.q("SELECT pos, sha256, nbytes FROM close_rows WHERE kind=? ORDER BY pos", (kind,))]
