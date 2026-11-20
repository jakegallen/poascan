"""Unofficial ATP-20 token state, replayed from memos on archived transfer txs.

ATP-20 is a memo convention (LabLeak posts 3201 and 3202), not a protocol rule. This module never
calls minepoa.com. It reads transfer rows already stored by the indexer and rebuilds token state.

Assumptions (easy to change: ORDERING, BURN_DEBIT, sort_key, burn_account):
- Order is (ts, id). The convention text names (anchor_height, account_nonce), but those keys are
  not on the public transfer list or in the txs table. The published devkit uses (ts, id) for the
  same reason. Set ORDERING to "anchor_nonce_txid" when those fields are stored.
- A burn debits from_addr (the signer). The v1.0 text also mentions the deployer; BURN_DEBIT can
  be set to "deployer" if that reading is confirmed.
- A 6-field deploy whose last field is not a mint_auth value treats that field as meta_cid (SEAL).
- Pending deploys do not reserve a tick. The first final valid deploy wins.
- Balances and holder figures are unofficial and may differ from other indexers.
"""
import re, threading, time
from . import db

ORDERING = "ts_id"          # "ts_id" or "anchor_nonce_txid"
BURN_DEBIT = "from_addr"    # "from_addr" or "deployer"
MEMO_PREFIX = "ATP-20|"
MEMO_MAX = 140
TICK_RE = re.compile(r"^[A-Z0-9]{3,12}$")
UINT_RE = re.compile(r"^[0-9]+$")
UINT64_MAX = (1 << 64) - 1
OPS = ("d", "m", "t", "b")

OFFICIAL = False
OFFICIAL_NOTE = ("Unofficial replay of the ATP-20 memo convention. Balances and holder figures "
                 "are not a protocol view and may differ from other indexers.")
ORDERING_NOTE = ("Replay sorts by (ts, id). The convention text names (anchor_height, account_nonce); "
                 "those keys are not in the public transfer list or in this archive, so this follows "
                 "the published devkit's practical order.")
BURN_NOTE = ("A burn debits the signer (from_addr). The v1.0 text also mentions the deployer; "
             "this choice is documented and can be changed.")

SCHEMA = """
CREATE TABLE IF NOT EXISTS atp20_ops(
  txid TEXT PRIMARY KEY, tick TEXT, op TEXT, from_addr TEXT, to_addr TEXT, amt TEXT,
  max_supply TEXT, decimals INTEGER, meta_cid TEXT, mint_auth TEXT, memo TEXT,
  ts INTEGER, nonce INTEGER, anchor_height INTEGER, final INTEGER, source TEXT,
  valid INTEGER, reason TEXT);
CREATE INDEX IF NOT EXISTS atp20_ops_order ON atp20_ops(ts, txid);
CREATE INDEX IF NOT EXISTS atp20_ops_tick ON atp20_ops(tick, ts, txid);
CREATE TABLE IF NOT EXISTS atp20_tokens(
  tick TEXT PRIMARY KEY, deployer TEXT, max_supply TEXT, decimals INTEGER, meta_cid TEXT,
  mint_auth TEXT, deploy_txid TEXT, deploy_ts INTEGER, minted TEXT, burned TEXT, holder_count INTEGER);
CREATE TABLE IF NOT EXISTS atp20_balances(
  tick TEXT NOT NULL, addr TEXT NOT NULL, amount TEXT NOT NULL, mint_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(tick, addr));
CREATE INDEX IF NOT EXISTS atp20_bal_tick ON atp20_balances(tick, amount DESC, addr);
CREATE TABLE IF NOT EXISTS atp20_state(k TEXT PRIMARY KEY, v TEXT);
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


def parse_auth(s):
    """('deployer',) | ('open',) | ('open', per_mint, max_mints) | None if malformed."""
    if s in (None, "", "deployer"):
        return ("deployer",)
    if s == "open":
        return ("open",)
    m = re.fullmatch(r"open:([0-9]+):([0-9]+)", s or "")
    if m:
        per, cap = int(m.group(1)), int(m.group(2))
        if per <= UINT64_MAX and cap <= UINT64_MAX:
            return ("open", per, cap)
    return None


def _uint(s, min_v=0):
    if not isinstance(s, str) or not UINT_RE.fullmatch(s):
        return None
    n = int(s)
    if n < min_v or n > UINT64_MAX:
        return None
    return n


def sort_key(op):
    """Sort key for replay. Swap ORDERING to change the rule without touching apply()."""
    if ORDERING == "anchor_nonce_txid":
        ah = op.get("anchor_height")
        nz = op.get("nonce")
        return (ah if ah is not None else UINT64_MAX, nz if nz is not None else UINT64_MAX, op.get("txid") or "")
    return (int(op.get("ts") or 0), op.get("txid") or "")


def burn_account(op, token):
    """Whose balance a burn debits. Swap BURN_DEBIT to change the rule."""
    if BURN_DEBIT == "deployer":
        return token.get("deployer")
    return op.get("from_addr")


def _nonce_of(t):
    if t.get("nonce") is not None and t.get("nonce") != "":
        try:
            return int(t["nonce"])
        except (TypeError, ValueError):
            pass
    body = t.get("body")
    if isinstance(body, dict) and body.get("nonce") is not None and body.get("nonce") != "":
        try:
            return int(body["nonce"])
        except (TypeError, ValueError):
            pass
    return None


def _anchor_of(t):
    for k in ("anchor_height", "anchorHeight"):
        if t.get(k) is not None and t.get(k) != "":
            try:
                return int(t[k])
            except (TypeError, ValueError):
                pass
    body = t.get("body")
    if isinstance(body, dict):
        for k in ("anchor_height", "anchorHeight"):
            if body.get(k) is not None and body.get(k) != "":
                try:
                    return int(body[k])
                except (TypeError, ValueError):
                    pass
    return None


def _final_of(t):
    v = t.get("final")
    return 1 if v in (1, True, "1") else 0


def parse_memo(memo):
    """Parse an ATP-20 memo. Returns (fields, None) or (None, reason). fields is a dict; amt may be None on deploy."""
    if memo is None or not memo.startswith(MEMO_PREFIX):
        return None, "malformed"
    if len(memo) > MEMO_MAX:
        return None, "memo_too_long"
    f = memo.split("|")
    if len(f) < 3 or f[0] != "ATP-20":
        return None, "malformed"
    op, tick = f[1], f[2]
    if op not in OPS:
        return None, "unknown_op"
    if not TICK_RE.fullmatch(tick):
        return None, "bad_tick"
    out = dict(op=op, tick=tick, amt=None, max_supply=None, decimals=None, meta_cid=None, mint_auth="deployer")
    if op == "d":
        if len(f) not in (5, 6, 7):
            return None, "bad_field_count"
        mx, dec = _uint(f[3]), _uint(f[4])
        if mx is None or dec is None or dec > 18:
            return None, "bad_types"
        out["max_supply"], out["decimals"] = str(mx), dec
        if len(f) == 6:
            auth = parse_auth(f[5])
            if auth is not None and f[5] not in (None, ""):
                out["mint_auth"] = f[5]
            else:
                out["meta_cid"] = f[5] or None
        elif len(f) == 7:
            out["meta_cid"] = f[5] or None
            if parse_auth(f[6]) is None:
                return None, "bad_mint_auth"
            out["mint_auth"] = f[6] or "deployer"
        return out, None
    if len(f) != 4:
        return None, "bad_field_count"
    amt = _uint(f[3], min_v=1)
    if amt is None:
        return None, "bad_types"
    out["amt"] = str(amt)
    return out, None


def _self(fr, to):
    return bool(fr) and fr == to


def _slot_superseded(txid, author, nonce):
    try:
        from . import slotlatch as SL
        st = SL.state_of(txid, author, nonce) if nonce is not None else SL.of(txid)
    except Exception:
        return False
    return bool(st) and st.get("state") == "superseded"


def ingest(rows, source=""):
    """Take transfer rows (from upsert_txs or a local backfill) and refresh unofficial token state. No upstream reads."""
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
            f"SELECT * FROM atp20_ops WHERE txid IN ({','.join('?' * len(ids))})", tuple(ids))}
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
        anchor = _anchor_of(t)
        if anchor is None:
            anchor = (prev or {}).get("anchor_height")
        parsed, reason = parse_memo(memo)
        rec = dict(txid=tid, tick=(parsed or {}).get("tick") or (prev or {}).get("tick"),
                   op=(parsed or {}).get("op") or (prev or {}).get("op"),
                   from_addr=fr, to_addr=to, amt=(parsed or {}).get("amt"),
                   max_supply=(parsed or {}).get("max_supply"), decimals=(parsed or {}).get("decimals"),
                   meta_cid=(parsed or {}).get("meta_cid"), mint_auth=(parsed or {}).get("mint_auth"),
                   memo=memo, ts=ts, nonce=nonce, anchor_height=anchor, final=fin,
                   source=source or t.get("source") or st.get("source") or (prev or {}).get("source"),
                   valid=None, reason=reason)
        writes.append(rec)
        if not prev or any(prev.get(k) != rec.get(k) for k in ("memo", "final", "ts", "nonce", "anchor_height", "from_addr", "to_addr", "amt")):
            changed = True
    if not writes:
        return 0
    db.write("""INSERT INTO atp20_ops(txid,tick,op,from_addr,to_addr,amt,max_supply,decimals,meta_cid,mint_auth,memo,ts,nonce,anchor_height,final,source,valid,reason)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(txid) DO UPDATE SET
        tick=COALESCE(excluded.tick, atp20_ops.tick),
        op=COALESCE(excluded.op, atp20_ops.op),
        from_addr=COALESCE(excluded.from_addr, atp20_ops.from_addr),
        to_addr=COALESCE(excluded.to_addr, atp20_ops.to_addr),
        amt=COALESCE(excluded.amt, atp20_ops.amt),
        max_supply=COALESCE(excluded.max_supply, atp20_ops.max_supply),
        decimals=COALESCE(excluded.decimals, atp20_ops.decimals),
        meta_cid=COALESCE(excluded.meta_cid, atp20_ops.meta_cid),
        mint_auth=COALESCE(excluded.mint_auth, atp20_ops.mint_auth),
        memo=COALESCE(excluded.memo, atp20_ops.memo),
        ts=CASE WHEN excluded.ts IS NOT NULL AND excluded.ts != 0 THEN excluded.ts ELSE atp20_ops.ts END,
        nonce=COALESCE(excluded.nonce, atp20_ops.nonce),
        anchor_height=COALESCE(excluded.anchor_height, atp20_ops.anchor_height),
        final=MAX(atp20_ops.final, excluded.final),
        source=COALESCE(excluded.source, atp20_ops.source)""",
             [(w["txid"], w["tick"], w["op"], w["from_addr"], w["to_addr"], w["amt"], w["max_supply"], w["decimals"],
               w["meta_cid"], w["mint_auth"], w["memo"], w["ts"], w["nonce"], w["anchor_height"], w["final"],
               w["source"], w["valid"], w["reason"]) for w in writes], many=True)
    if changed or any(not known.get(w["txid"]) for w in writes):
        replay()
    return len(writes)


def backfill():
    """Replay every archived transfer whose stored memo starts with ATP-20|. Local database only."""
    _ensure()
    rows = db.q("""SELECT t.id, t.type, t.from_addr, t.to_addr, t.amount, t.memo, t.ts, t.final, t.source,
                          CAST(json_extract(d.json, '$.body.nonce') AS INTEGER) AS nonce
                   FROM txs t LEFT JOIN tx_detail d ON d.id = t.id
                   WHERE t.type='transfer' AND t.memo LIKE 'ATP-20|%'""")
    return ingest([dict(r) for r in rows], "backfill")


def replay():
    """Rebuild token and balance tables from atp20_ops in sort_key order. Always a full replay (cheap at current size)."""
    _ensure()
    with _lock:
        ops = [dict(r) for r in db.q("SELECT * FROM atp20_ops")]
        ops.sort(key=sort_key)
        tokens, bals, mints = {}, {}, {}
        results = []  # (txid, valid, reason)

        def bal(tick, addr):
            return bals.get((tick, addr), 0)

        def add(tick, addr, delta):
            k = (tick, addr)
            n = bals.get(k, 0) + delta
            if n < 0:
                return False
            if n == 0:
                bals.pop(k, None)
            else:
                bals[k] = n
            return True

        for op in ops:
            txid = op.get("txid")
            if not int(op.get("final") or 0):
                results.append((txid, None, "pending"))
                continue
            if _slot_superseded(txid, op.get("from_addr"), op.get("nonce")):
                results.append((txid, 0, "superseded")); continue
            parsed, reason = parse_memo(op.get("memo"))
            if reason or not parsed:
                results.append((txid, 0, reason or "malformed")); continue
            kind, tick = parsed["op"], parsed["tick"]
            fr, to = op.get("from_addr"), op.get("to_addr")
            tok = tokens.get(tick)
            if kind == "d":
                if tok:
                    results.append((txid, 0, "tick_already_deployed")); continue
                if not _self(fr, to):
                    results.append((txid, 0, "not_self_transfer")); continue
                tokens[tick] = dict(tick=tick, deployer=fr, max_supply=parsed["max_supply"],
                                    decimals=parsed["decimals"], meta_cid=parsed.get("meta_cid"),
                                    mint_auth=parsed.get("mint_auth") or "deployer",
                                    deploy_txid=txid, deploy_ts=int(op.get("ts") or 0), minted=0, burned=0)
                results.append((txid, 1, None)); continue
            if not tok:
                results.append((txid, 0, "unknown_tick")); continue
            if kind in ("m", "b") and not _self(fr, to):
                results.append((txid, 0, "not_self_transfer")); continue
            if kind == "t" and _self(fr, to):
                results.append((txid, 0, "self_transfer")); continue
            amt = int(parsed["amt"])
            if kind == "m":
                auth = parse_auth(tok.get("mint_auth"))
                if auth is None:
                    results.append((txid, 0, "bad_mint_auth")); continue
                if auth[0] == "deployer" and fr != tok["deployer"]:
                    results.append((txid, 0, "mint_not_authorized")); continue
                if auth[0] == "open" and len(auth) == 3:
                    per, cap = auth[1], auth[2]
                    if amt != per:
                        results.append((txid, 0, "mint_amount")); continue
                    if mints.get((tick, fr), 0) >= cap:
                        results.append((txid, 0, "mint_cap")); continue
                if tok["minted"] + amt > int(tok["max_supply"]):
                    results.append((txid, 0, "mint_overflow")); continue
                add(tick, fr, amt)
                tok["minted"] += amt
                mints[(tick, fr)] = mints.get((tick, fr), 0) + 1
                results.append((txid, 1, None)); continue
            if kind == "t":
                if bal(tick, fr) < amt:
                    results.append((txid, 0, "insufficient_balance")); continue
                add(tick, fr, -amt)
                add(tick, to, amt)
                results.append((txid, 1, None)); continue
            if kind == "b":
                acct = burn_account(op, tok)
                if not acct:
                    results.append((txid, 0, "burn_no_account")); continue
                if bal(tick, acct) < amt:
                    results.append((txid, 0, "insufficient_balance")); continue
                add(tick, acct, -amt)
                tok["burned"] += amt
                results.append((txid, 1, None)); continue
            results.append((txid, 0, "unknown_op"))

        db.write("DELETE FROM atp20_tokens")
        db.write("DELETE FROM atp20_balances")
        if tokens:
            holders = {}
            for (tick, addr), n in bals.items():
                holders[tick] = holders.get(tick, 0) + 1
            db.write("""INSERT INTO atp20_tokens(tick,deployer,max_supply,decimals,meta_cid,mint_auth,deploy_txid,deploy_ts,minted,burned,holder_count)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                     [(t["tick"], t["deployer"], t["max_supply"], t["decimals"], t.get("meta_cid"), t.get("mint_auth"),
                       t["deploy_txid"], t["deploy_ts"], str(t["minted"]), str(t["burned"]), holders.get(t["tick"], 0))
                      for t in tokens.values()], many=True)
        if bals:
            db.write("INSERT INTO atp20_balances(tick,addr,amount,mint_count) VALUES(?,?,?,?)",
                     [(tick, addr, str(n), int(mints.get((tick, addr), 0))) for (tick, addr), n in bals.items()], many=True)
        if results:
            db.write("UPDATE atp20_ops SET valid=?, reason=? WHERE txid=?",
                     [(v, r, tid) for tid, v, r in results], many=True)
        applied = sum(1 for _, v, _ in results if v == 1)
        ignored = sum(1 for _, v, _ in results if v == 0)
        pending = sum(1 for _, v, _ in results if v is None)
        ts_vals = [int(o.get("ts") or 0) for o in ops if int(o.get("final") or 0) and o.get("ts")]
        _put_state({
            "ordering": ORDERING,
            "burn": BURN_DEBIT,
            "applied": str(applied),
            "ignored": str(ignored),
            "pending": str(pending),
            "tokens": str(len(tokens)),
            "first_ts": str(min(ts_vals) if ts_vals else 0),
            "last_ts": str(max(ts_vals) if ts_vals else 0),
            "replayed_at": str(int(time.time())),
            "ops": str(len(ops)),
        })
        return dict(applied=applied, ignored=ignored, pending=pending, tokens=len(tokens))


def _put_state(d):
    db.write("INSERT INTO atp20_state(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
             list(d.items()), many=True)


def _get_state():
    _ensure()
    return {r["k"]: r["v"] for r in db.q("SELECT k, v FROM atp20_state")}


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
        burn=st.get("burn") or BURN_DEBIT,
        burn_note=BURN_NOTE,
        applied=_i("applied"),
        ignored=_i("ignored"),
        pending=_i("pending"),
        tokens=_i("tokens"),
        ops=_i("ops"),
        first_ts=_i("first_ts") or None,
        last_ts=_i("last_ts") or None,
        replayed_at=_i("replayed_at") or None,
    )


def _token_row(r):
    if not r:
        return None
    d = dict(r)
    d["official"] = OFFICIAL
    d["minted"] = str(d.get("minted") or "0")
    d["burned"] = str(d.get("burned") or "0")
    d["holder_count"] = int(d.get("holder_count") or 0)
    return d


def tokens():
    _ensure()
    return [_token_row(r) for r in db.q("SELECT * FROM atp20_tokens ORDER BY deploy_ts ASC, tick ASC")]


def token(tick):
    _ensure()
    if not tick or not TICK_RE.fullmatch(tick):
        return None
    r = db.q1("SELECT * FROM atp20_tokens WHERE tick=?", (tick,))
    return _token_row(r)


def _bal_row(r):
    if not r:
        return None
    return dict(tick=r["tick"], addr=r["addr"], amount=str(r["amount"] or "0"),
                mint_count=int(r["mint_count"] or 0), official=OFFICIAL)


def holders(tick):
    _ensure()
    if not tick or not TICK_RE.fullmatch(tick):
        return []
    return [_bal_row(r) for r in db.q(
        "SELECT tick, addr, amount, mint_count FROM atp20_balances WHERE tick=? AND CAST(amount AS INTEGER) > 0 "
        "ORDER BY CAST(amount AS INTEGER) DESC, addr ASC", (tick,))]


def balance(tick, addr):
    _ensure()
    if not tick or not TICK_RE.fullmatch(tick) or not addr:
        return None
    r = db.q1("SELECT tick, addr, amount, mint_count FROM atp20_balances WHERE tick=? AND addr=?", (tick, addr))
    if r:
        return _bal_row(r)
    if token(tick) is None:
        return None
    return dict(tick=tick, addr=addr, amount="0", mint_count=0, official=OFFICIAL)


def ops(tick=None, final=None, valid=None):
    _ensure()
    w, a = [], []
    if tick:
        if not TICK_RE.fullmatch(tick):
            return []
        w.append("tick=?"); a.append(tick)
    if final is not None:
        w.append("final=?"); a.append(1 if final else 0)
    if valid is not None:
        if valid is True or valid == 1:
            w.append("valid=1")
        elif valid == 0:
            w.append("valid=0")
        elif valid == "pending":
            w.append("valid IS NULL")
    sql = "SELECT * FROM atp20_ops" + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY ts ASC, txid ASC"
    return [dict(r) for r in db.q(sql, tuple(a))]


def pending(tick=None):
    return ops(tick=tick, valid="pending")
