"""Per-close record mirror: each close record from the ingested /api/epochs blob, served in canonical form.

Canonical form is RFC 8785 (JCS): object keys sorted by UTF-16 code units, no whitespace, strings escaped as
JSON.stringify does (non-ASCII left as UTF-8), numbers in ECMAScript shortest form, UTF-8 bytes. For these records it equals
json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() in Python. sha256 is over those bytes."""
import collections, decimal, gzip, hashlib, json, threading
from . import db, analytics as A, segments as S

def _num(f):
    if f != f or f in (float("inf"), float("-inf")): raise ValueError("non-finite number")
    if f == 0: return "0"
    if f.is_integer() and abs(f) < 1e21: return str(int(f))
    t = decimal.Decimal(repr(f)).as_tuple(); ds = "".join(map(str, t.digits)).rstrip("0") or "0"
    k = len(ds); n = len(t.digits) + t.exponent; sg = "-" if t.sign else ""
    if k <= n <= 21: return sg + ds + "0" * (n - k)
    if 0 < n <= 21: return sg + ds[:n] + "." + ds[n:]
    if -6 < n <= 0: return sg + "0." + "0" * (-n) + ds
    e = n - 1; es = ("+" if e >= 0 else "-") + str(abs(e))
    return sg + ds[0] + ("." + ds[1:] if k > 1 else "") + "e" + es

def _enc(x, out):
    if x is None: out.append("null")
    elif x is True: out.append("true")
    elif x is False: out.append("false")
    elif isinstance(x, int): out.append(str(x))
    elif isinstance(x, float): out.append(_num(x))
    elif isinstance(x, str): out.append(json.dumps(x, ensure_ascii=False))
    elif isinstance(x, dict):
        out.append("{"); first = True
        for k in sorted(x, key=lambda s: s.encode("utf-16-be")):
            if not first: out.append(",")
            first = False; out.append(json.dumps(str(k), ensure_ascii=False)); out.append(":"); _enc(x[k], out)
        out.append("}")
    elif isinstance(x, (list, tuple)):
        out.append("[")
        for i, v in enumerate(x):
            if i: out.append(",")
            _enc(v, out)
        out.append("]")
    else: raise TypeError(type(x).__name__)

def canonical(x):
    out = []; _enc(x, out); return "".join(out).encode("utf-8")

def sha256(b): return hashlib.sha256(b).hexdigest()

# Per segment (segments.py): epoch numbers restart at a genesis cut, so the index and the LRU key on the segment too.
_lock = threading.Lock(); _ixs = {}; _lru = collections.OrderedDict(); LRU_MAX = 3

def _blob_ts(): return A.epochs_ts()

def _raw():
    return {int(e.get("epoch", 0)): e for e in A.epochs_raw()}

def index():
    """[{epoch, close_ts, sha256, bytes}] for every published close, recomputed only when the ingested blob changes."""
    ts = _blob_ts(); sg = S.selected()
    with _lock:
        ix = _ixs.get(sg)
        if ix and ix["ts"] == ts and ix["rows"]: return ix["rows"]
    rows = []
    for n, e in sorted(_raw().items()):
        b = canonical(e); rows.append(dict(epoch=n, close_ts=e.get("ts"), sha256=sha256(b), bytes=len(b), segment=sg))
    with _lock:
        _ixs[sg] = dict(ts=ts, rows=rows)
        for k in [k for k in _lru if k[0] == sg]: _lru.pop(k, None)
    return rows

def record(n):
    """(canonical bytes, sha256) of close n, or None when epoch n has no published close record."""
    row = next((r for r in index() if r["epoch"] == n), None)
    if not row: return None
    k = (S.selected(), n)
    with _lock:
        hit = _lru.get(k)
        if hit and hit[1] == row["sha256"]: _lru.move_to_end(k); return hit
    e = _raw().get(n)
    if e is None: return None
    b = canonical(e); h = sha256(b)
    with _lock:
        _lru[k] = (b, h)
        while len(_lru) > LRU_MAX: _lru.popitem(last=False)
    return b, h

def summary(n):
    """Hash and headline counts for one close record (no blob): for agents that pin or diff closes."""
    row = next((r for r in index() if r["epoch"] == n), None)
    if not row: return None
    e = _raw()[n]; b = e.get("basis") or {}
    return dict(row, keys=sorted(e), basis_keys=sorted(b), pending=len(b.get("pending") or {}), settled=len(b.get("settled") or []),
                rewards=len(e.get("rewards") or {}), graders_served=len(b.get("graders_served") or {}))

FROM_MAX = 3   # records per ?from= page: the newest closes run about 2 MB each
IMMUTABLE = "public, max-age=31536000, immutable"
CANON = "RFC 8785 JCS; sha256 of the UTF-8 body"

def page(fr, lim=FROM_MAX):
    """Canonical {"from", "next_from", "records": [{bytes, epoch, record, sha256}]} for closes fr..fr+lim-1, built from
    the per-record canonical bytes so the whole body is itself canonical. next_from is null when no later close exists."""
    ns = [r["epoch"] for r in index() if r["epoch"] >= fr]; take = ns[:lim]; nxt = ns[lim] if len(ns) > lim else None
    items = []
    for n in take:
        b, h = record(n)
        items.append(b'{"bytes":' + str(len(b)).encode() + b',"epoch":' + str(n).encode() + b',"record":' + b + b',"sha256":"' + h.encode() + b'"}')
    body = b'{"from":' + str(fr).encode() + b',"next_from":' + (b"null" if nxt is None else str(nxt).encode()) + b',"records":[' + b",".join(items) + b"]}"
    return body, nxt
