"""Close records on disk, one row per close (1.26.235).

The close list grows by one record every close and every record repeats the whole pending list, so the parsed copy kept in
memory grew about 2.5 MB per close (57 MB at E23). Each close is now a row of close_rows: the record without
basis.pending ("slim", a few KB), its pending list as its own JSON text, where "pending" sat among the basis keys, and the
record's canonical sha256 and byte count (records.py). Only the slim records stay in memory; a close's pending list is
read from its row when a page needs it (a small LRU), and pend_ix answers "this answer's row at this close" without
parsing a whole close.

The blobs row of each segment ("epochs", "epochs:sN") is still written exactly as before, so a build from before 1.26.235
reads the same database. close_meta records which blob copy the rows came from (its ts and byte length); when they differ
(the first boot of 1.26.235, or a blob written by an older build after a rollback) the rows are rebuilt from the blob one
close at a time, read through SQLite blob I/O in chunks, so the whole list is never held as text or parsed at once."""
import codecs, collections, hashlib, json, threading
from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS close_rows(kind TEXT NOT NULL, pos INTEGER NOT NULL, epoch INTEGER, ts INTEGER, slim TEXT NOT NULL,
  pending TEXT, ppos INTEGER, sha256 TEXT NOT NULL, nbytes INTEGER NOT NULL, sig TEXT NOT NULL, PRIMARY KEY(kind, pos));
CREATE TABLE IF NOT EXISTS close_meta(kind TEXT PRIMARY KEY, src_ts INTEGER, src_len INTEGER, n INTEGER NOT NULL, ver INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS pend_ix(kind TEXT NOT NULL, tx TEXT NOT NULL, pos0 INTEGER NOT NULL, pos1 INTEGER NOT NULL, v TEXT NOT NULL,
  PRIMARY KEY(kind, tx, pos0)) WITHOUT ROWID;
"""
VER = 1
CHUNK = 4 << 20
_lock = threading.RLock()   # one writer or rebuild at a time; readers that find the rows behind the blob wait here
_ver = collections.Counter()   # kind -> bumped on every rows write (in-process; the slim copy and the LRU key on it)

def init():
    db.conn().executescript(SCHEMA); db.conn().commit()

def kinds():
    return [r["kind"] for r in db.q("SELECT kind FROM blobs WHERE kind='epochs' OR kind LIKE 'epochs:s%'")]

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

def _row(kind, pos, e):
    from . import records as RR
    full = json.dumps(e); slim, pend, ppos = split(e); cb = RR.canonical(e)
    ep = e.get("epoch") if isinstance(e, dict) else None; ts = e.get("ts") if isinstance(e, dict) else None
    return (kind, pos, int(ep) if isinstance(ep, (int, float)) else None, int(ts) if isinstance(ts, (int, float)) else None, slim, pend, ppos,
            RR.sha256(cb), len(cb), hashlib.sha1(full.encode("utf-8", "surrogatepass")).hexdigest())

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
    ok = bool(m and src and m["ver"] == VER and (m["src_ts"], m["src_len"]) == tuple(src))
    g = db.blob_gen(kind)
    if ok and _gen.setdefault(kind, g) != g: ok = False
    return ok

def iter_blob(kind):
    """Each element of a blobs row's JSON array, decoded one at a time from chunks of the stored text."""
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
INS = "INSERT OR REPLACE INTO close_rows(kind, pos, epoch, ts, slim, pending, ppos, sha256, nbytes, sig) VALUES(?,?,?,?,?,?,?,?,?,?)"

def rebuild(kind):
    """Rows of one segment from its blob, one close at a time (idempotent: a no-op when close_meta matches the blob)."""
    with _lock:
        src = blob_src(kind)
        if src is None or current(kind, src): return False
        c = db.conn(); n = 0; have = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=?", (kind,))}
        for e in iter_blob(kind):
            if have.get(n) != sig_of(e):
                with db._wlock: c.execute(INS, db._clean(_row(kind, n, e))); c.commit()
            n += 1
        _finish(kind, src, n)
        return True

def write(kind, rows):
    """After db.put_blob(kind, rows): the changed rows only (by sig), then pend_ix and close_meta."""
    with _lock:
        have = {r["pos"]: r["sig"] for r in db.q("SELECT pos, sig FROM close_rows WHERE kind=?", (kind,))}
        ch = [_row(kind, i, e) for i, e in enumerate(rows) if have.get(i) != sig_of(e)]
        if ch: db.write(INS, ch, many=True)
        _finish(kind, blob_src(kind), len(rows))

def _finish(kind, src, n):
    db.write_tx([("DELETE FROM close_rows WHERE kind=? AND pos>=?", (kind, n), False)])
    _index(kind)
    db.write("INSERT OR REPLACE INTO close_meta(kind, src_ts, src_len, n, ver) VALUES(?,?,?,?,?)", (kind, src[0] if src else None, src[1] if src else None, n, VER))
    _ver[kind] += 1; _lru.clear(); _gen[kind] = db.blob_gen(kind)

def retag(kind):
    """After db.touch_blob: the rows stand for the blob's new stored time."""
    with _lock:
        m = meta(kind); src = blob_src(kind)
        if m and src and m["src_len"] == src[1] and m["ver"] == VER: db.write("UPDATE close_meta SET src_ts=? WHERE kind=?", (src[0], kind))

def _index(kind):
    """pend_ix: for each answer, the runs of consecutive closes where its pending row is unchanged (rows grow with distinct
    rows, not with closes times answers). Rebuilt from the rows, one close's pending at a time."""
    c = db.conn(); out, run = [], {}
    for r in c.execute("SELECT pos, pending FROM close_rows WHERE kind=? ORDER BY pos", (kind,)).fetchall():
        p = json.loads(r[1]) if r[1] else {}; p = p if isinstance(p, dict) else {}; pos = r[0]; nxt = {}
        for t, v in p.items():
            vt = json.dumps(v); o = run.get(t)
            if o and o[1] == pos - 1 and o[2] == vt: o[1] = pos; nxt[t] = o
            else:
                if o: out.append((kind, t, o[0], o[1], o[2]))
                nxt[t] = [pos, pos, vt]
        for t, o in run.items():
            if t not in nxt: out.append((kind, t, o[0], o[1], o[2]))
        run = nxt
    out += [(kind, t, o[0], o[1], o[2]) for t, o in run.items()]
    db.write_tx([("DELETE FROM pend_ix WHERE kind=?", (kind,), False), ("INSERT OR REPLACE INTO pend_ix(kind, tx, pos0, pos1, v) VALUES(?,?,?,?,?)", out, True)])

def migrate():
    """Startup: every segment's rows current with its blob (streamed; nothing to do once they are)."""
    init(); done = []
    for k in kinds():
        if rebuild(k): done.append(k)
    return done

# ---------------------------------------------------------------- reads
def ver(kind): return _ver[kind]

class Close(dict):
    """A slim close record: a plain dict to every reader (same keys, values, order and JSON), plus where its row is
    (kind, pos, ppos), so pending_of and full_close find the close even after a newer copy replaced it."""
    __slots__ = ("loc",)

def slim(kind):
    """[slim record (Close)] of one segment, in stored order."""
    out = []
    for r in db.q("SELECT pos, ppos, slim FROM close_rows WHERE kind=? ORDER BY pos", (kind,)):
        v = json.loads(r["slim"])
        if isinstance(v, dict): v = Close(v); v.loc = (kind, r["pos"], r["ppos"], _ver[kind])
        out.append(v)
    return out

def ensure(kind):
    """Rows current with the blob (rebuilt from it when not: first boot of 1.26.235, or a blob an older build wrote)."""
    if not current(kind): rebuild(kind)

_lru = collections.OrderedDict(); LRU_MAX = 2   # (kind, pos, ver) -> parsed pending of one close
def pending(kind, pos, ver=None):
    """The parsed pending list of one close. ver: the rows version a slim record was read at (None: now); a record from
    before a rewrite reads the current row of its position, which a rewrite only changes when the close itself changed."""
    k = (kind, pos, _ver[kind])
    with _lock:
        hit = _lru.get(k)
        if hit is not None: _lru.move_to_end(k); return hit[0]
    r = db.q1("SELECT pending, ppos FROM close_rows WHERE kind=? AND pos=?", (kind, pos))
    v = _interned(json.loads(r["pending"])) if r and r["pending"] is not None else None
    with _lock:
        _lru[k] = (v,)
        while len(_lru) > LRU_MAX: _lru.popitem(last=False)
    return v

def _interned(p):
    """Equal pending rows share one dict (read only; about 8k distinct rows among 36k answers at E23)."""
    if not isinstance(p, dict): return p
    seen = {}
    for k, v in p.items():
        if isinstance(v, dict):
            o = seen.setdefault(json.dumps(v), v)
            if o is not v: p[k] = o
    return p

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
