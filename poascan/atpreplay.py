"""Combined unofficial ATP-20 and ATP-721 replay in one (ts, id) order.

ATP-721 mint fees debit the minter's unofficial ATP-20 balance (LabLeak 3218). A full
combined replay is cheap at the current size. Both atp20.replay and atp721.replay call
this so a later ATP-20-only rebuild cannot wipe the fee burns.
"""
import threading, time
from . import db
from . import atp20 as T20
from . import atp721 as T721

LOCK = threading.Lock()
FEE_DEBIT = "minter"
FEE_NOTE = ("On a valid ATP-721 mint, the fee in fee_tick is debited from the minter's unofficial "
            "ATP-20 balance, burn_pct is burned, and the rest is credited to the collection deployer. "
            "A mint whose minter lacks the fee is ignored (insufficient_fee_balance). ATP-20 and "
            "ATP-721 ops share one (ts, id) order.")


def ensure():
    """Replay once after a code change to the fee rule, or when either side has never replayed."""
    T20._ensure()
    T721._ensure()
    st20, st721 = T20._get_state(), T721._get_state()
    if (st20.get("fee_debit") != FEE_DEBIT) or (st721.get("fee_debit") != FEE_DEBIT):
        replay()


def replay():
    """Rebuild ATP-20 and ATP-721 tables from both op lists in one (ts, id) order."""
    T20._ensure()
    T721._ensure()
    with LOCK:
        return _replay()


def _replay():
    ops20 = [dict(r, _fam="20") for r in db.q("SELECT * FROM atp20_ops")]
    ops721 = [dict(r, _fam="721") for r in db.q("SELECT * FROM atp721_ops")]
    ops = ops20 + ops721
    ops.sort(key=lambda o: (int(o.get("ts") or 0), o.get("txid") or "", 0 if o.get("_fam") == "20" else 1))

    tokens, bals, mints = {}, {}, {}
    cols, units, held = {}, {}, {}
    results20, results721 = [], []

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

    def apply20(op):
        txid = op.get("txid")
        if not int(op.get("final") or 0):
            results20.append((txid, None, "pending")); return
        if T20._slot_superseded(txid, op.get("from_addr"), op.get("nonce")):
            results20.append((txid, 0, "superseded")); return
        parsed, reason = T20.parse_memo(op.get("memo"))
        if reason or not parsed:
            results20.append((txid, 0, reason or "malformed")); return
        kind, tick = parsed["op"], parsed["tick"]
        fr, to = op.get("from_addr"), op.get("to_addr")
        tok = tokens.get(tick)
        if kind == "d":
            if tok:
                results20.append((txid, 0, "tick_already_deployed")); return
            if not T20._self(fr, to):
                results20.append((txid, 0, "not_self_transfer")); return
            tokens[tick] = dict(tick=tick, deployer=fr, max_supply=parsed["max_supply"],
                                decimals=parsed["decimals"], meta_cid=parsed.get("meta_cid"),
                                mint_auth=parsed.get("mint_auth") or "deployer",
                                deploy_txid=txid, deploy_ts=int(op.get("ts") or 0), minted=0, burned=0)
            results20.append((txid, 1, None)); return
        if not tok:
            results20.append((txid, 0, "unknown_tick")); return
        if kind in ("m", "b") and not T20._self(fr, to):
            results20.append((txid, 0, "not_self_transfer")); return
        if kind == "t" and T20._self(fr, to):
            results20.append((txid, 0, "self_transfer")); return
        amt = int(parsed["amt"])
        if kind == "m":
            auth = T20.parse_auth(tok.get("mint_auth"))
            if auth is None:
                results20.append((txid, 0, "bad_mint_auth")); return
            if auth[0] == "deployer" and fr != tok["deployer"]:
                results20.append((txid, 0, "mint_not_authorized")); return
            if auth[0] == "open" and len(auth) == 3:
                per, cap = auth[1], auth[2]
                if amt != per:
                    results20.append((txid, 0, "mint_amount")); return
                if mints.get((tick, fr), 0) >= cap:
                    results20.append((txid, 0, "mint_cap")); return
            if tok["minted"] + amt > int(tok["max_supply"]):
                results20.append((txid, 0, "mint_overflow")); return
            add(tick, fr, amt)
            tok["minted"] += amt
            mints[(tick, fr)] = mints.get((tick, fr), 0) + 1
            results20.append((txid, 1, None)); return
        if kind == "t":
            if bal(tick, fr) < amt:
                results20.append((txid, 0, "insufficient_balance")); return
            add(tick, fr, -amt)
            add(tick, to, amt)
            results20.append((txid, 1, None)); return
        if kind == "b":
            acct = T20.burn_account(op, tok)
            if not acct:
                results20.append((txid, 0, "burn_no_account")); return
            if bal(tick, acct) < amt:
                results20.append((txid, 0, "insufficient_balance")); return
            add(tick, acct, -amt)
            tok["burned"] += amt
            results20.append((txid, 1, None)); return
        results20.append((txid, 0, "unknown_op"))

    def apply721(op):
        txid = op.get("txid")
        if not int(op.get("final") or 0):
            results721.append((txid, None, "pending")); return
        parsed, reason = T721.parse_memo(op.get("memo"))
        if reason or not parsed:
            results721.append((txid, 0, reason or "malformed")); return
        kind, col = parsed["op"], parsed["col"]
        fr, to = op.get("from_addr"), op.get("to_addr")
        rec = cols.get(col)
        if kind == "d":
            if rec:
                results721.append((txid, 0, "collection_already_deployed")); return
            if not T721._self(fr, to):
                results721.append((txid, 0, "not_self_transfer")); return
            burn = T721.burn_amount(parsed["fee"], parsed["burn_pct"])
            cols[col] = dict(col=col, deployer=fr, file_sha=parsed["file_sha"], mime=parsed["mime"],
                             total=parsed["total"], fee=parsed["fee"], fee_tick=parsed["fee_tick"],
                             burn_pct=parsed["burn_pct"], burn_fee=str(burn) if burn is not None else None,
                             max_per_addr=parsed["max_per_addr"], title=parsed.get("title"),
                             deploy_txid=txid, deploy_ts=int(op.get("ts") or 0), minted=0,
                             fee_burned=0, deployer_fees=0)
            held[col] = {}
            results721.append((txid, 1, None)); return
        if not rec:
            results721.append((txid, 0, "unknown_collection")); return
        unit = parsed["unit"]
        if unit < 1 or unit > int(rec["total"]):
            results721.append((txid, 0, "unit_range")); return
        key = (col, unit)
        if kind == "m":
            if not T721._self(fr, to):
                results721.append((txid, 0, "not_self_transfer")); return
            if key in units:
                results721.append((txid, 0, "duplicate_unit")); return
            got = held[col].get(fr, 0)
            if got >= int(rec["max_per_addr"]):
                results721.append((txid, 0, "over_addr_cap")); return
            fee = int(rec["fee"] or 0)
            tick = rec.get("fee_tick")
            if fee > 0:
                if bal(tick, fr) < fee:
                    results721.append((txid, 0, "insufficient_fee_balance")); return
                burn = int(rec["burn_fee"] or 0) if rec.get("burn_fee") is not None else (T721.burn_amount(fee, rec["burn_pct"]) or 0)
                rest = fee - burn
                add(tick, fr, -fee)
                tok = tokens.get(tick)
                if tok:
                    tok["burned"] += burn
                rec["fee_burned"] = rec.get("fee_burned", 0) + burn
                if rest:
                    add(tick, rec["deployer"], rest)
                    rec["deployer_fees"] = rec.get("deployer_fees", 0) + rest
            ts = int(op.get("ts") or 0)
            units[key] = dict(col=col, unit=unit, addr=fr, mint_txid=txid, mint_ts=ts,
                              last_txid=txid, last_ts=ts)
            held[col][fr] = got + 1
            rec["minted"] += 1
            results721.append((txid, 1, None)); return
        if kind == "t":
            if T721._self(fr, to):
                results721.append((txid, 0, "self_transfer")); return
            cur = units.get(key)
            if not cur or cur["addr"] != fr:
                results721.append((txid, 0, "not_owner")); return
            got = held[col].get(to, 0)
            if got >= int(rec["max_per_addr"]):
                results721.append((txid, 0, "over_addr_cap")); return
            held[col][fr] = held[col].get(fr, 1) - 1
            if held[col][fr] <= 0:
                held[col].pop(fr, None)
            held[col][to] = got + 1
            ts = int(op.get("ts") or 0)
            cur["addr"] = to
            cur["last_txid"] = txid
            cur["last_ts"] = ts
            results721.append((txid, 1, None)); return
        results721.append((txid, 0, "unknown_op"))

    for op in ops:
        if op.get("_fam") == "20":
            apply20(op)
        else:
            apply721(op)

    db.write("DELETE FROM atp20_tokens")
    db.write("DELETE FROM atp20_balances")
    if tokens:
        holders20 = {}
        for (tick, addr), n in bals.items():
            holders20[tick] = holders20.get(tick, 0) + 1
        db.write("""INSERT INTO atp20_tokens(tick,deployer,max_supply,decimals,meta_cid,mint_auth,deploy_txid,deploy_ts,minted,burned,holder_count)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                 [(t["tick"], t["deployer"], t["max_supply"], t["decimals"], t.get("meta_cid"), t.get("mint_auth"),
                   t["deploy_txid"], t["deploy_ts"], str(t["minted"]), str(t["burned"]), holders20.get(t["tick"], 0))
                  for t in tokens.values()], many=True)
    if bals:
        db.write("INSERT INTO atp20_balances(tick,addr,amount,mint_count) VALUES(?,?,?,?)",
                 [(tick, addr, str(n), int(mints.get((tick, addr), 0))) for (tick, addr), n in bals.items()], many=True)
    if results20:
        db.write("UPDATE atp20_ops SET valid=?, reason=? WHERE txid=?",
                 [(v, r, tid) for tid, v, r in results20], many=True)
    applied20 = sum(1 for _, v, _ in results20 if v == 1)
    ignored20 = sum(1 for _, v, _ in results20 if v == 0)
    pending20 = sum(1 for _, v, _ in results20 if v is None)
    ts20 = [int(o.get("ts") or 0) for o in ops20 if int(o.get("final") or 0) and o.get("ts")]
    T20._put_state({
        "ordering": T20.ORDERING,
        "burn": T20.BURN_DEBIT,
        "fee_debit": FEE_DEBIT,
        "applied": str(applied20),
        "ignored": str(ignored20),
        "pending": str(pending20),
        "tokens": str(len(tokens)),
        "first_ts": str(min(ts20) if ts20 else 0),
        "last_ts": str(max(ts20) if ts20 else 0),
        "replayed_at": str(int(time.time())),
        "ops": str(len(ops20)),
    })

    db.write("DELETE FROM atp721_collections")
    db.write("DELETE FROM atp721_units")
    if cols:
        holders721 = {}
        for (c, _u), u in units.items():
            holders721.setdefault(c, set()).add(u["addr"])
        db.write("""INSERT INTO atp721_collections(col,deployer,file_sha,mime,total,fee,fee_tick,burn_pct,burn_fee,max_per_addr,title,deploy_txid,deploy_ts,minted,holder_count,deployer_fees,fee_burned)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 [(t["col"], t["deployer"], t["file_sha"], t["mime"], t["total"], t["fee"], t["fee_tick"],
                   t["burn_pct"], t.get("burn_fee"), t["max_per_addr"], t.get("title"), t["deploy_txid"],
                   t["deploy_ts"], t["minted"], len(holders721.get(t["col"]) or ()),
                   str(t.get("deployer_fees") or 0), str(t.get("fee_burned") or 0))
                  for t in cols.values()], many=True)
    if units:
        db.write("""INSERT INTO atp721_units(col,unit,addr,mint_txid,mint_ts,last_txid,last_ts)
          VALUES(?,?,?,?,?,?,?)""",
                 [(u["col"], u["unit"], u["addr"], u["mint_txid"], u["mint_ts"], u["last_txid"], u["last_ts"])
                  for u in units.values()], many=True)
    if results721:
        db.write("UPDATE atp721_ops SET valid=?, reason=? WHERE txid=?",
                 [(v, r, tid) for tid, v, r in results721], many=True)
    applied721 = sum(1 for _, v, _ in results721 if v == 1)
    ignored721 = sum(1 for _, v, _ in results721 if v == 0)
    pending721 = sum(1 for _, v, _ in results721 if v is None)
    ts721 = [int(o.get("ts") or 0) for o in ops721 if int(o.get("final") or 0) and o.get("ts")]
    T721._put_state({
        "ordering": T721.ORDERING,
        "fee_debit": FEE_DEBIT,
        "applied": str(applied721),
        "ignored": str(ignored721),
        "pending": str(pending721),
        "collections": str(len(cols)),
        "units": str(len(units)),
        "first_ts": str(min(ts721) if ts721 else 0),
        "last_ts": str(max(ts721) if ts721 else 0),
        "replayed_at": str(int(time.time())),
        "ops": str(len(ops721)),
    })
    return dict(applied=applied20 + applied721, ignored=ignored20 + ignored721,
                pending=pending20 + pending721, tokens=len(tokens), collections=len(cols),
                applied_20=applied20, applied_721=applied721)
