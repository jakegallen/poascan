"""Ballot 2464 carry correction (1.26.257). A won 75 to 9 (LabLeak post 2464): the carried portion of E37 and E38 pay comes
off 92 Agents' locked balances at the segment 2 E44 close, 940,522,943.64 POA in total, burned. G0 notice
2026-11-04-carry-correction-E44 (on chain, txid below) announced it with the per-Agent table on IPFS; POAScan bundles that
table, pinned by sha256, to show what is scheduled. Applied once the E44 close record carries a correction field
(analytics.correction_of), or, from 1.26.261, once the E44 record is in while /api/params carry_correction (v0.84) names
E44 and this table's sha256; the per Agent amounts are then the record's rows, else this table (shortfall 0, LabLeak
comment 15202)."""
import hashlib, json, os, time
from . import db, analytics as A, segments as SG

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "carry_correction_E44.json")
SHA256 = "be455270e74571f92eac275d18ee4d9cc77ed4ef34994abc142a202966fb40f7"
CID = "bafkreif6ivjhbz2foh4s5lbhlumo4tm4y57nj3zutfflyfbkeauwn62a64"
NOTICE = dict(id="2026-11-04-carry-correction-E44", txid="ecfcdbece0e10a24147831ad277b8aa8c0b40a102336ce7e823ebe9d4b1cf7cf", issued_ts=1793788302)
POST, CLOSE, SEG = 2464, 44, 2
TALLY = "A 75 · LEAVE 9"
URL = "https://minepoa.com/lableak/#/post/2464"
_t = None

def table():
    """{address: amount} from the bundled table; empty if its sha256 does not match the pin."""
    global _t
    if _t is None:
        raw = open(PATH, "rb").read()
        _t = {a: float(v) for a, v in json.loads(raw)} if hashlib.sha256(raw).hexdigest() == SHA256 else {}
    return _t

def total(): return sum(table().values())

def _close():
    return next((e for e in A.segment_closes(SEG) if int(e.get("epoch", -1)) == CLOSE), None)

MEMO = "carry_correction_e44"   # 1.26.261: kept once params and the E44 record agree, so a later params change cannot undo it

def _params_ok():
    """/api/params carry_correction names this close and the pinned table (minepoa v0.84-slotlatch-cc44 on)."""
    cc = A.params().get("carry_correction")
    if not isinstance(cc, dict): return False
    try: fe = int(cc.get("from_epoch"))
    except (TypeError, ValueError): return False
    return fe == CLOSE and str(cc.get("table_sha256") or "").lower() == SHA256

@A.cached("cc_status", 30, light=True)
def status():
    """scheduled (E44 not closed); executed (the E44 record carries a correction); applied (the E44 record is in and
    /api/params carry_correction names E44 and the pinned table, so the engine ran it; amounts from that table); or
    closed_no_record (neither). recorded: the record's own total, else None."""
    e = _close()
    if e is None: return dict(state="scheduled", close=CLOSE, close_ts=None, recorded=None, via=None)
    ts = int(e.get("ts") or 0) or None
    rec = A.correction_of(e)
    if rec > 0: return dict(state="executed", close=CLOSE, close_ts=ts, recorded=rec, via="close record")
    memo, _ = db.get_blob(MEMO)
    if not memo and _params_ok():
        memo = dict(close_ts=ts, seen=int(time.time())); db.put_blob(MEMO, memo)
    if memo: return dict(state="applied", close=CLOSE, close_ts=ts, recorded=None, via="params and close record")
    return dict(state="closed_no_record", close=CLOSE, close_ts=ts, recorded=None, via=None)

def done(st=None): return (st or status())["state"] in ("executed", "applied")

@A.cached("cc_rows", 30, light=True)
def rows():
    """{address: amount} that applied: the E44 record's own rows when it lists them, else the pinned table once done."""
    st = status()
    if not done(st): return {}
    e = _close(); rr = A.correction_rows(e) if e is not None else {}
    return rr or dict(table())

def applied_total():
    st = status()
    if not done(st): return 0.0
    return st["recorded"] if st["recorded"] else sum(rows().values())

def applied(a): return rows().get(a, 0.0)

def implied(e, seg):
    """The pinned table total for the segment 2 E44 record when it carries no correction field but the correction ran
    (state applied), else 0. Lets supply and reconcile read the burn without inventing a number."""
    try:
        if int(seg) != SEG or int(e.get("epoch", -1)) != CLOSE or A.correction_of(e) > 0: return 0.0
    except (TypeError, ValueError): return 0.0
    return total() if status()["state"] == "applied" else 0.0

def expected_ts():
    """When the E44 close is due: the latest close plus one epoch per close to go."""
    cs = A.segment_closes(SEG)
    if not cs: return None
    last = max(cs, key=lambda e: int(e.get("epoch", 0))); n = int(last.get("epoch", 0))
    per = int(A.params().get("auto_epoch_seconds") or 21600)
    return int(last.get("ts") or 0) + per * (CLOSE - n) if n < CLOSE else int(last.get("ts") or 0)

def for_address(a):
    v = table().get(a); st = status(); got = applied(a) if done(st) else 0.0
    if not v and not got: return None
    return dict(amount=got or v, scheduled=v or None, applied=got or None, state=st["state"], close=CLOSE, segment=SEG,
                ts=st["close_ts"] or expected_ts(), post=POST, notice=NOTICE["id"], via=st["via"])

WORD = {"scheduled": "Scheduled", "executed": "Applied", "applied": "Applied", "closed_no_record": "E44 closed, not in the record"}

def effect_text():
    st = status(); s = st["state"]
    if done(st):
        return f"Burned {applied_total() / 1e6:,.2f}M POA from {len(rows())} Agents' locked at the E{CLOSE} close", WORD[s]
    return f"Burns {total() / 1e6:,.2f}M POA from {len(table())} Agents' locked at the E{CLOSE} close", WORD[s]

def api():
    st = status(); d = done(st); rr = rows() if d else {}
    return dict(ballot=POST, tally=TALLY, close=CLOSE, segment=SEG, lifetime_epoch=SG.gkey(CLOSE, SEG), agents=len(table()), total=round(total(), 6),
                status=st, applied=d, applied_total=round(applied_total(), 6) if d else None, applied_agents=len(rr) if d else None,
                matches_table=(len(rr) == len(table()) and abs(applied_total() - total()) <= 0.01) if d else None,
                expected_close_ts=expected_ts() if st["state"] == "scheduled" else None, params_match=_params_ok(),
                table=dict(sha256=SHA256, ipfs=CID, rows=len(table())), notice=NOTICE, source=URL,
                note="Scheduled amounts come from the G0 notice's table. Applied: the E44 record carries the correction, or it is in "
                     "and /api/params carry_correction names E44 and this table. Spendable balances do not change; locked does.")


def locked_after(a, locked):
    """locked_est less this Agent's correction once it applied at E44 (taken from its last unlocks)."""
    if locked is None: return locked
    v = applied(a)
    return max(0.0, locked - v) if v else locked
