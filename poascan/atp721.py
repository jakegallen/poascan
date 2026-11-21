"""Unofficial ATP-721 collection state, replayed from memos on archived transfer txs.

ATP-721 is a memo convention (LabLeak posts 3218-3220), not a protocol rule. This module
never calls minepoa.com. It reads transfer rows already stored by the indexer and rebuilds
collection and unit ownership.

Assumptions (easy to change: ORDERING):
- Order is (ts, id). The convention text names nonce at inclusion; those keys are not on
  the public transfer list. The same practical order as unofficial ATP-20 is used here.
- Deploy and mint must be self-transfers. The first valid deploy of a collection name wins.
- A mint picks a unit number in 1..total. The first valid mint of that unit wins.
- An address may hold at most max_per_addr units of a collection.
- Fee debit in fee_tick (an ATP-20 tick) is not applied in this replay; coverage says so.
- LIST / UNLIST / BUY and any other op are recorded and ignored.
- Pending deploys do not reserve a name. Ownership is the last valid mint or transfer.
- Figures are unofficial and may differ from other indexers.
"""
import re, threading, time
from . import db

ORDERING = "ts_id"
MEMO_PREFIX = "ATP-721|"
MEMO_MAX = 200
COL_RE = re.compile(r"^[A-Z0-9](?:[A-Z0-9-]{0,30}[A-Z0-9])$")
TICK_RE = re.compile(r"^[A-Z0-9]{3,12}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MIME_OK = {"image/png", "image/gif", "image/webp", "image/jpeg"}
UINT_RE = re.compile(r"^[0-9]+$")
UINT64_MAX = (1 << 64) - 1
OPS = ("d", "m", "t")
LIMIT_DEFAULT, LIMIT_MAX = 20, 200

OFFICIAL = False
OFFICIAL_NOTE = ("Unofficial replay of the ATP-721 memo convention. Ownership and mint counts "
                 "are not a protocol view and may differ from other indexers.")
ORDERING_NOTE = ("Replay sorts by (ts, id). The convention text names nonce at inclusion; "
                 "those keys are not in the public transfer list or in this archive, so this "
                 "follows the same practical order as unofficial ATP-20.")
FEE_NOTE = ("Mint fee in fee_tick is not debited here. A mint that lacked the fee may still "
            "count as valid in this replay.")

SCHEMA = """
CREATE TABLE IF NOT EXISTS atp721_ops(
  txid TEXT PRIMARY KEY, col TEXT, op TEXT, unit INTEGER, from_addr TEXT, to_addr TEXT,
  file_sha TEXT, mime TEXT, total INTEGER, fee TEXT, fee_tick TEXT, burn_pct INTEGER,
  max_per_addr INTEGER, title TEXT, memo TEXT, ts INTEGER, nonce INTEGER, final INTEGER,
  source TEXT, valid INTEGER, reason TEXT);
CREATE INDEX IF NOT EXISTS atp721_ops_order ON atp721_ops(ts, txid);
CREATE INDEX IF NOT EXISTS atp721_ops_col ON atp721_ops(col, ts, txid);
CREATE TABLE IF NOT EXISTS atp721_collections(
  col TEXT PRIMARY KEY, deployer TEXT, file_sha TEXT, mime TEXT, total INTEGER, fee TEXT,
  fee_tick TEXT, burn_pct INTEGER, burn_fee TEXT, max_per_addr INTEGER, title TEXT,
  deploy_txid TEXT, deploy_ts INTEGER, minted INTEGER, holder_count INTEGER);
CREATE TABLE IF NOT EXISTS atp721_units(
  col TEXT NOT NULL, unit INTEGER NOT NULL, addr TEXT NOT NULL, mint_txid TEXT, mint_ts INTEGER,
  last_txid TEXT, last_ts INTEGER, PRIMARY KEY(col, unit));
CREATE INDEX IF NOT EXISTS atp721_units_addr ON atp721_units(col, addr, unit);
CREATE TABLE IF NOT EXISTS atp721_state(k TEXT PRIMARY KEY, v TEXT);
"""

_lock = threading.Lock()
_inited = [False]


def init(conn=None):
    """Create tables. Called from db.init inside the write lock, or lazily."""
    c = conn or db.conn()
    c.executescript(SCHEMA)
    _inited[0] = True


def _ensure():
    if not _inited[0]:
        init()


def _uint(s, min_v=0, max_v=UINT64_MAX):
    if s is None or not UINT_RE.fullmatch(str(s)):
        return None
    n = int(s)
    if n < min_v or n > max_v:
        return None
    return n


def sort_key(op):
    return (int(op.get("ts") or 0), op.get("txid") or "")


def _nonce_of(t):
    for k in ("nonce", "body_nonce"):
        if t.get(k) is not None:
            try:
                return int(t[k])
            except (TypeError, ValueError):
                pass
    body = t.get("body")
    if isinstance(body, dict) and body.get("nonce") is not None:
        try:
            return int(body["nonce"])
        except (TypeError, ValueError):
            pass
    return None


def _final_of(t):
    v = t.get("final")
    return 1 if v in (1, True, "1") else 0


def parse_memo(memo):
    """Parse an ATP-721 memo. Returns (fields, None) or (None, reason)."""
    if memo is None or not memo.startswith(MEMO_PREFIX):
        return None, "malformed"
    if len(memo) > MEMO_MAX:
        return None, "memo_too_long"
    f = memo.split("|")
    if len(f) < 3 or f[0] != "ATP-721":
        return None, "malformed"
    op, col = f[1], f[2]
    if op not in OPS:
        return None, "unknown_op"
    if not COL_RE.fullmatch(col):
        return None, "bad_collection"
    out = dict(op=op, col=col, unit=None, file_sha=None, mime=None, total=None, fee=None,
               fee_tick=None, burn_pct=None, max_per_addr=None, title=None)
    if op == "d":
        if len(f) < 11:
            return None, "bad_field_count"
        sha, mime = (f[3] or "").lower(), f[4]
        total, fee = _uint(f[5], min_v=1), _uint(f[6], min_v=0)
        tick, pct = f[7], _uint(f[8], min_v=1, max_v=100)
        cap = _uint(f[9], min_v=1)
        title = "|".join(f[10:]).strip() or None
        if not SHA_RE.fullmatch(sha) or mime not in MIME_OK:
            return None, "bad_types"
        if None in (total, fee, pct, cap) or not TICK_RE.fullmatch(tick or ""):
            return None, "bad_types"
        out.update(file_sha=sha, mime=mime, total=total, fee=str(fee), fee_tick=tick,
                   burn_pct=pct, max_per_addr=cap, title=title)
        return out, None
    if len(f) != 4:
        return None, "bad_field_count"
    unit = _uint(f[3], min_v=1)
    if unit is None:
        return None, "bad_types"
    out["unit"] = unit
    return out, None


def burn_amount(fee, pct):
    """Protocol burn: ceil(fee * pct / 100)."""
    try:
        fee_n, pct_n = int(fee), int(pct)
    except (TypeError, ValueError):
        return None
    if fee_n < 0 or pct_n < 1:
        return None
    return (fee_n * pct_n + 99) // 100


def _self(fr, to):
    return bool(fr) and fr == to


def ingest(rows, source=""):
    """Take transfer rows (from upsert_txs or a local backfill) and refresh unofficial state. No upstream reads."""
    _ensure()
    if not rows:
        return 0
    incoming = {}
    for t in rows:
        if not isinstance(t, dict) and not hasattr(t, "keys"):
            continue
        t = dict(t)
        tid = t.get("id")
        if not tid:
            continue
        incoming[tid] = t
    if not incoming:
        return 0
    ids = list(incoming)
    stored = {}
    try:
        stored = {r["id"]: dict(r) for r in db.q(
            f"SELECT id,type,from_addr,to_addr,amount,memo,ts,final,source FROM txs WHERE id IN ({','.join('?' * len(ids))})",
            tuple(ids))}
    except Exception:
        stored = {}
    known = {}
    try:
        known = {r["txid"]: dict(r) for r in db.q(
            f"SELECT * FROM atp721_ops WHERE txid IN ({','.join('?' * len(ids))})", tuple(ids))}
    except Exception:
        known = {}
    writes, changed = [], False
    for tid, t in incoming.items():
        st = stored.get(tid) or {}
        typ = t.get("type") or st.get("type")
        if typ and typ != "transfer":
            continue
        memo = t.get("memo") or st.get("memo") or (known.get(tid) or {}).get("memo")
        prev = known.get(tid)
        if not (memo or "").startswith(MEMO_PREFIX):
            if not prev:
                continue
            memo = prev.get("memo")
        fin = max(_final_of(t), _final_of(st), int((prev or {}).get("final") or 0))
        ts = int(t.get("ts") or st.get("ts") or (prev or {}).get("ts") or 0)
        fr = t.get("from_addr") or t.get("from") or st.get("from_addr") or (prev or {}).get("from_addr")
        to = t.get("to_addr") or t.get("to") or st.get("to_addr") or (prev or {}).get("to_addr")
        nonce = _nonce_of(t)
        if nonce is None:
            nonce = (prev or {}).get("nonce")
        parsed, reason = parse_memo(memo)
        rec = dict(txid=tid, col=(parsed or {}).get("col") or (prev or {}).get("col"),
                   op=(parsed or {}).get("op") or (prev or {}).get("op"),
                   unit=(parsed or {}).get("unit") if parsed and parsed.get("unit") is not None else (prev or {}).get("unit"),
                   from_addr=fr, to_addr=to,
                   file_sha=(parsed or {}).get("file_sha") or (prev or {}).get("file_sha"),
                   mime=(parsed or {}).get("mime") or (prev or {}).get("mime"),
                   total=(parsed or {}).get("total") if parsed and parsed.get("total") is not None else (prev or {}).get("total"),
                   fee=(parsed or {}).get("fee") or (prev or {}).get("fee"),
                   fee_tick=(parsed or {}).get("fee_tick") or (prev or {}).get("fee_tick"),
                   burn_pct=(parsed or {}).get("burn_pct") if parsed and parsed.get("burn_pct") is not None else (prev or {}).get("burn_pct"),
                   max_per_addr=(parsed or {}).get("max_per_addr") if parsed and parsed.get("max_per_addr") is not None else (prev or {}).get("max_per_addr"),
                   title=(parsed or {}).get("title") or (prev or {}).get("title"),
                   memo=memo, ts=ts, nonce=nonce, final=fin,
                   source=source or t.get("source") or st.get("source") or (prev or {}).get("source"),
                   valid=None, reason=reason)
        writes.append(rec)
        if not prev or any(prev.get(k) != rec.get(k) for k in ("memo", "final", "ts", "nonce", "from_addr", "to_addr", "unit")):
            changed = True
    if not writes:
        return 0
    db.write("""INSERT INTO atp721_ops(txid,col,op,unit,from_addr,to_addr,file_sha,mime,total,fee,fee_tick,burn_pct,max_per_addr,title,memo,ts,nonce,final,source,valid,reason)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(txid) DO UPDATE SET
        col=COALESCE(excluded.col, atp721_ops.col),
        op=COALESCE(excluded.op, atp721_ops.op),
        unit=COALESCE(excluded.unit, atp721_ops.unit),
        from_addr=COALESCE(excluded.from_addr, atp721_ops.from_addr),
        to_addr=COALESCE(excluded.to_addr, atp721_ops.to_addr),
        file_sha=COALESCE(excluded.file_sha, atp721_ops.file_sha),
        mime=COALESCE(excluded.mime, atp721_ops.mime),
        total=COALESCE(excluded.total, atp721_ops.total),
        fee=COALESCE(excluded.fee, atp721_ops.fee),
        fee_tick=COALESCE(excluded.fee_tick, atp721_ops.fee_tick),
        burn_pct=COALESCE(excluded.burn_pct, atp721_ops.burn_pct),
        max_per_addr=COALESCE(excluded.max_per_addr, atp721_ops.max_per_addr),
        title=COALESCE(excluded.title, atp721_ops.title),
        memo=COALESCE(excluded.memo, atp721_ops.memo),
        ts=CASE WHEN excluded.ts IS NOT NULL AND excluded.ts != 0 THEN excluded.ts ELSE atp721_ops.ts END,
        nonce=COALESCE(excluded.nonce, atp721_ops.nonce),
        final=MAX(atp721_ops.final, excluded.final),
        source=COALESCE(excluded.source, atp721_ops.source)""",
             [(w["txid"], w["col"], w["op"], w["unit"], w["from_addr"], w["to_addr"], w["file_sha"], w["mime"],
               w["total"], w["fee"], w["fee_tick"], w["burn_pct"], w["max_per_addr"], w["title"], w["memo"],
               w["ts"], w["nonce"], w["final"], w["source"], w["valid"], w["reason"]) for w in writes], many=True)
    if changed or any(not known.get(w["txid"]) for w in writes):
        replay()
    return len(writes)


def backfill():
    """Replay every archived transfer whose stored memo starts with ATP-721|. Local database only."""
    _ensure()
    rows = db.q("""SELECT t.id, t.type, t.from_addr, t.to_addr, t.amount, t.memo, t.ts, t.final, t.source,
                          CAST(json_extract(d.json, '$.body.nonce') AS INTEGER) AS nonce
                   FROM txs t LEFT JOIN tx_detail d ON d.id = t.id
                   WHERE t.type='transfer' AND t.memo LIKE 'ATP-721|%'""")
    return ingest([dict(r) for r in rows], "backfill")


def replay():
    """Rebuild collection and unit tables from atp721_ops in (ts, id) order. Always a full replay."""
    _ensure()
    with _lock:
        ops = [dict(r) for r in db.q("SELECT * FROM atp721_ops")]
        ops.sort(key=sort_key)
        cols, units, held = {}, {}, {}
        results = []

        for op in ops:
            txid = op.get("txid")
            if not int(op.get("final") or 0):
                results.append((txid, None, "pending"))
                continue
            parsed, reason = parse_memo(op.get("memo"))
            if reason or not parsed:
                results.append((txid, 0, reason or "malformed"))
                continue
            kind, col = parsed["op"], parsed["col"]
            fr, to = op.get("from_addr"), op.get("to_addr")
            rec = cols.get(col)
            if kind == "d":
                if rec:
                    results.append((txid, 0, "collection_already_deployed"))
                    continue
                if not _self(fr, to):
                    results.append((txid, 0, "not_self_transfer"))
                    continue
                burn = burn_amount(parsed["fee"], parsed["burn_pct"])
                cols[col] = dict(col=col, deployer=fr, file_sha=parsed["file_sha"], mime=parsed["mime"],
                                 total=parsed["total"], fee=parsed["fee"], fee_tick=parsed["fee_tick"],
                                 burn_pct=parsed["burn_pct"], burn_fee=str(burn) if burn is not None else None,
                                 max_per_addr=parsed["max_per_addr"], title=parsed.get("title"),
                                 deploy_txid=txid, deploy_ts=int(op.get("ts") or 0), minted=0)
                held[col] = {}
                results.append((txid, 1, None))
                continue
            if not rec:
                results.append((txid, 0, "unknown_collection"))
                continue
            unit = parsed["unit"]
            if unit < 1 or unit > int(rec["total"]):
                results.append((txid, 0, "unit_range"))
                continue
            key = (col, unit)
            if kind == "m":
                if not _self(fr, to):
                    results.append((txid, 0, "not_self_transfer"))
                    continue
                if key in units:
                    results.append((txid, 0, "duplicate_unit"))
                    continue
                got = held[col].get(fr, 0)
                if got >= int(rec["max_per_addr"]):
                    results.append((txid, 0, "over_addr_cap"))
                    continue
                ts = int(op.get("ts") or 0)
                units[key] = dict(col=col, unit=unit, addr=fr, mint_txid=txid, mint_ts=ts,
                                  last_txid=txid, last_ts=ts)
                held[col][fr] = got + 1
                rec["minted"] += 1
                results.append((txid, 1, None))
                continue
            if kind == "t":
                if _self(fr, to):
                    results.append((txid, 0, "self_transfer"))
                    continue
                cur = units.get(key)
                if not cur or cur["addr"] != fr:
                    results.append((txid, 0, "not_owner"))
                    continue
                got = held[col].get(to, 0)
                if got >= int(rec["max_per_addr"]):
                    results.append((txid, 0, "over_addr_cap"))
                    continue
                held[col][fr] = held[col].get(fr, 1) - 1
                if held[col][fr] <= 0:
                    held[col].pop(fr, None)
                held[col][to] = got + 1
                ts = int(op.get("ts") or 0)
                cur["addr"] = to
                cur["last_txid"] = txid
                cur["last_ts"] = ts
                results.append((txid, 1, None))
                continue
            results.append((txid, 0, "unknown_op"))

        db.write("DELETE FROM atp721_collections")
        db.write("DELETE FROM atp721_units")
        if cols:
            holders = {}
            for (c, _u), u in units.items():
                holders.setdefault(c, set()).add(u["addr"])
            db.write("""INSERT INTO atp721_collections(col,deployer,file_sha,mime,total,fee,fee_tick,burn_pct,burn_fee,max_per_addr,title,deploy_txid,deploy_ts,minted,holder_count)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     [(t["col"], t["deployer"], t["file_sha"], t["mime"], t["total"], t["fee"], t["fee_tick"],
                       t["burn_pct"], t.get("burn_fee"), t["max_per_addr"], t.get("title"), t["deploy_txid"],
                       t["deploy_ts"], t["minted"], len(holders.get(t["col"]) or ()))
                      for t in cols.values()], many=True)
        if units:
            db.write("""INSERT INTO atp721_units(col,unit,addr,mint_txid,mint_ts,last_txid,last_ts)
              VALUES(?,?,?,?,?,?,?)""",
                     [(u["col"], u["unit"], u["addr"], u["mint_txid"], u["mint_ts"], u["last_txid"], u["last_ts"])
                      for u in units.values()], many=True)
        if results:
            db.write("UPDATE atp721_ops SET valid=?, reason=? WHERE txid=?",
                     [(v, r, tid) for tid, v, r in results], many=True)
        applied = sum(1 for _, v, _ in results if v == 1)
        ignored = sum(1 for _, v, _ in results if v == 0)
        pending = sum(1 for _, v, _ in results if v is None)
        ts_vals = [int(o.get("ts") or 0) for o in ops if int(o.get("final") or 0) and o.get("ts")]
        _put_state({
            "ordering": ORDERING,
            "fee_debit": "unchecked",
            "applied": str(applied),
            "ignored": str(ignored),
            "pending": str(pending),
            "collections": str(len(cols)),
            "units": str(len(units)),
            "first_ts": str(min(ts_vals) if ts_vals else 0),
            "last_ts": str(max(ts_vals) if ts_vals else 0),
            "replayed_at": str(int(time.time())),
            "ops": str(len(ops)),
        })
        return dict(applied=applied, ignored=ignored, pending=pending, collections=len(cols))


def _put_state(d):
    db.write("INSERT INTO atp721_state(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
             list(d.items()), many=True)


def _get_state():
    _ensure()
    return {r["k"]: r["v"] for r in db.q("SELECT k, v FROM atp721_state")}


def coverage():
    """Coverage and unofficial labels for API responses."""
    st = _get_state()
    def _i(k):
        try:
            return int(st.get(k) or 0)
        except ValueError:
            return 0
    return dict(
        official=OFFICIAL,
        official_note=OFFICIAL_NOTE,
        ordering=st.get("ordering") or ORDERING,
        ordering_note=ORDERING_NOTE,
        fee_debit=st.get("fee_debit") or "unchecked",
        fee_note=FEE_NOTE,
        applied=_i("applied"),
        ignored=_i("ignored"),
        pending=_i("pending"),
        collections=_i("collections"),
        units=_i("units"),
        ops=_i("ops"),
        first_ts=_i("first_ts") or None,
        last_ts=_i("last_ts") or None,
        replayed_at=_i("replayed_at") or None,
    )


def _col_row(r):
    if not r:
        return None
    d = dict(r)
    d["official"] = OFFICIAL
    return d


def collections():
    ensure_fresh()
    return [_col_row(r) for r in db.q("SELECT * FROM atp721_collections ORDER BY deploy_ts, col")]


def collection(col):
    ensure_fresh()
    rows = db.q("SELECT * FROM atp721_collections WHERE col=?", (col,))
    return _col_row(rows[0]) if rows else None


def units_offset(col, offset=0, limit=LIMIT_DEFAULT):
    ensure_fresh()
    limit = max(1, min(LIMIT_MAX, int(limit)))
    offset = max(0, int(offset or 0))
    rows = db.q("SELECT * FROM atp721_units WHERE col=? ORDER BY unit LIMIT ? OFFSET ?",
                (col, limit, offset))
    return [dict(r, official=OFFICIAL) for r in rows]


def units_count(col):
    ensure_fresh()
    rows = db.q("SELECT COUNT(*) AS n FROM atp721_units WHERE col=?", (col,))
    return int((rows[0]["n"] if rows else 0) or 0)


def holders_offset(col, offset=0, limit=LIMIT_DEFAULT):
    ensure_fresh()
    limit = max(1, min(LIMIT_MAX, int(limit)))
    offset = max(0, int(offset or 0))
    rows = db.q("""SELECT addr, COUNT(*) AS units FROM atp721_units WHERE col=?
                   GROUP BY addr ORDER BY units DESC, addr LIMIT ? OFFSET ?""",
                (col, limit, offset))
    return [dict(addr=r["addr"], units=int(r["units"]), official=OFFICIAL) for r in rows]


def holders_count(col):
    ensure_fresh()
    rows = db.q("SELECT COUNT(DISTINCT addr) AS n FROM atp721_units WHERE col=?", (col,))
    return int((rows[0]["n"] if rows else 0) or 0)


def ops(col=None, final=None, valid=None):
    ensure_fresh()
    w, a = [], []
    if col:
        w.append("col=?"); a.append(col)
    if final is not None:
        w.append("final=?"); a.append(int(final))
    if valid is not None:
        w.append("valid=?"); a.append(int(valid) if valid is not None else valid)
    sql = "SELECT * FROM atp721_ops" + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY ts, txid"
    return [dict(r) for r in db.q(sql, tuple(a))]


def collections_count():
    ensure_fresh()
    rows = db.q("SELECT COUNT(*) AS n FROM atp721_collections")
    return int((rows[0]["n"] if rows else 0) or 0)


def collections_offset(offset=0, limit=LIMIT_DEFAULT):
    ensure_fresh()
    limit = max(1, min(LIMIT_MAX, int(limit)))
    offset = max(0, int(offset or 0))
    rows = db.q("SELECT * FROM atp721_collections ORDER BY deploy_ts, col LIMIT ? OFFSET ?",
                (limit, offset))
    return [_col_row(r) for r in rows]


def _limit(qs):
    try:
        n = int((qs or {}).get("limit", [LIMIT_DEFAULT])[0])
    except (TypeError, ValueError):
        n = LIMIT_DEFAULT
    return max(1, min(LIMIT_MAX, n))


def _cursor(qs, n):
    raw = ((qs or {}).get("cursor") or [""])[0]
    if not raw:
        return None
    parts = raw.split("|")
    if len(parts) != n:
        raise ValueError("bad cursor")
    return parts


def _params(qs, allowed):
    for k in (qs or {}):
        if k not in allowed:
            raise ValueError("unknown parameter")


_QS_NONE = frozenset()
_QS_PAGE = frozenset(("limit", "cursor"))


def _envelope(**extra):
    ensure_fresh()
    cv = coverage()
    out = dict(official=OFFICIAL, official_note=OFFICIAL_NOTE, coverage=cv)
    out.update(extra)
    return out


def ensure_fresh():
    """Create tables and backfill once if this process has never replayed. Local database only."""
    _ensure()
    if not _get_state().get("replayed_at"):
        backfill()


def _page_rows(rows, nxt):
    return rows, nxt


def collections_page(cursor=None, limit=LIMIT_DEFAULT):
    ensure_fresh()
    limit = max(1, min(LIMIT_MAX, int(limit)))
    if cursor:
        ts, col = cursor
        try:
            ts = int(ts)
        except ValueError:
            raise ValueError("bad cursor")
        rows = db.q("SELECT * FROM atp721_collections WHERE deploy_ts > ? OR (deploy_ts=? AND col>?) ORDER BY deploy_ts, col LIMIT ?",
                    (ts, ts, col, limit + 1))
    else:
        rows = db.q("SELECT * FROM atp721_collections ORDER BY deploy_ts, col LIMIT ?", (limit + 1,))
    rows = [_col_row(r) for r in rows]
    nxt = None
    if len(rows) > limit:
        last = rows[limit - 1]
        nxt = f"{last['deploy_ts']}|{last['col']}"
        rows = rows[:limit]
    return rows, nxt


def units_page(col, cursor=None, limit=LIMIT_DEFAULT):
    ensure_fresh()
    limit = max(1, min(LIMIT_MAX, int(limit)))
    if cursor:
        try:
            unit = int(cursor[0])
        except (TypeError, ValueError, IndexError):
            raise ValueError("bad cursor")
        rows = db.q("SELECT * FROM atp721_units WHERE col=? AND unit>? ORDER BY unit LIMIT ?",
                    (col, unit, limit + 1))
    else:
        rows = db.q("SELECT * FROM atp721_units WHERE col=? ORDER BY unit LIMIT ?", (col, limit + 1))
    rows = [dict(r, official=OFFICIAL) for r in rows]
    nxt = None
    if len(rows) > limit:
        nxt = str(rows[limit - 1]["unit"])
        rows = rows[:limit]
    return rows, nxt


def holders_page(col, cursor=None, limit=LIMIT_DEFAULT):
    ensure_fresh()
    limit = max(1, min(LIMIT_MAX, int(limit)))
    # keyset on (units DESC, addr)
    if cursor:
        try:
            n, addr = int(cursor[0]), cursor[1]
        except (TypeError, ValueError, IndexError):
            raise ValueError("bad cursor")
        rows = db.q("""SELECT addr, COUNT(*) AS units FROM atp721_units WHERE col=?
                       GROUP BY addr
                       HAVING units < ? OR (units=? AND addr>?)
                       ORDER BY units DESC, addr LIMIT ?""",
                    (col, n, n, addr, limit + 1))
    else:
        rows = db.q("""SELECT addr, COUNT(*) AS units FROM atp721_units WHERE col=?
                       GROUP BY addr ORDER BY units DESC, addr LIMIT ?""",
                    (col, limit + 1))
    rows = [dict(addr=r["addr"], units=int(r["units"]), official=OFFICIAL) for r in rows]
    nxt = None
    if len(rows) > limit:
        last = rows[limit - 1]
        nxt = f"{last['units']}|{last['addr']}"
        rows = rows[:limit]
    return rows, nxt


def txs_page(col, cursor=None, limit=LIMIT_DEFAULT):
    """Final ops only, newest first, includes ignored."""
    ensure_fresh()
    limit = max(1, min(LIMIT_MAX, int(limit)))
    if cursor:
        try:
            ts, txid = int(cursor[0]), cursor[1]
        except (TypeError, ValueError, IndexError):
            raise ValueError("bad cursor")
        rows = db.q("""SELECT * FROM atp721_ops WHERE col=? AND final=1
                       AND (ts < ? OR (ts=? AND txid < ?))
                       ORDER BY ts DESC, txid DESC LIMIT ?""",
                    (col, ts, ts, txid, limit + 1))
    else:
        rows = db.q("""SELECT * FROM atp721_ops WHERE col=? AND final=1
                       ORDER BY ts DESC, txid DESC LIMIT ?""",
                    (col, limit + 1))
    rows = [dict(r, official=OFFICIAL) for r in rows]
    nxt = None
    if len(rows) > limit:
        last = rows[limit - 1]
        nxt = f"{last['ts']}|{last['txid']}"
        rows = rows[:limit]
    return rows, nxt


_COL_PATH = r"([A-Z0-9](?:[A-Z0-9-]{0,30}[A-Z0-9]))"


def http(path, qs):
    """Unofficial ATP-721 read API. Raises ValueError or LookupError for the server to map."""
    ensure_fresh()
    if path == "/api/atp721/collections":
        _params(qs, _QS_PAGE)
        rows, nxt = collections_page(_cursor(qs, 2), _limit(qs))
        return _envelope(collections=rows, next_cursor=nxt)
    m = re.match(r"^/api/atp721/collection/" + _COL_PATH + r"$", path)
    if m:
        _params(qs, _QS_NONE)
        col = m.group(1)
        tok = collection(col)
        if tok is None:
            raise LookupError("unknown collection")
        return _envelope(collection=tok)
    m = re.match(r"^/api/atp721/collection/" + _COL_PATH + r"/units$", path)
    if m:
        _params(qs, _QS_PAGE)
        col = m.group(1)
        if collection(col) is None:
            raise LookupError("unknown collection")
        rows, nxt = units_page(col, _cursor(qs, 1), _limit(qs))
        return _envelope(collection=col, units=rows, next_cursor=nxt)
    m = re.match(r"^/api/atp721/collection/" + _COL_PATH + r"/holders$", path)
    if m:
        _params(qs, _QS_PAGE)
        col = m.group(1)
        if collection(col) is None:
            raise LookupError("unknown collection")
        rows, nxt = holders_page(col, _cursor(qs, 2), _limit(qs))
        return _envelope(collection=col, holders=rows, next_cursor=nxt)
    m = re.match(r"^/api/atp721/collection/" + _COL_PATH + r"/txs$", path)
    if m:
        _params(qs, _QS_PAGE)
        col = m.group(1)
        if collection(col) is None:
            raise LookupError("unknown collection")
        rows, nxt = txs_page(col, _cursor(qs, 2), _limit(qs))
        return _envelope(collection=col, txs=rows, next_cursor=nxt)
    if path.startswith("/api/atp721/"):
        raise LookupError("unknown endpoint")
    raise LookupError("unknown endpoint")
