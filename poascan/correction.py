"""Ballot 2464 carry correction (1.26.257). A won 75 to 9 (LabLeak post 2464): the carried portion of E37 and E38 pay comes
off 92 Agents' locked balances at the segment 2 E44 close, 940,522,943.64 POA in total, burned. G0 notice
2026-11-04-carry-correction-E44 (on chain, txid below) announced it with the per-Agent table on IPFS; POAScan bundles that
table, pinned by sha256, to show what is scheduled. Executed only once the E44 close record carries a correction field
(analytics.correction_of); balances and supply move from the chain data, never from this table."""
import hashlib, json, os, time
from . import analytics as A, segments as SG

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

def status():
    """scheduled (E44 not closed), executed (the E44 record carries a correction), or closed_no_record."""
    e = _close()
    if e is None: return dict(state="scheduled", close=CLOSE, close_ts=None, recorded=None)
    rec = A.correction_of(e)
    return dict(state="executed" if rec > 0 else "closed_no_record", close=CLOSE, close_ts=int(e.get("ts") or 0) or None, recorded=rec or None)

def expected_ts():
    """When the E44 close is due: the latest close plus one epoch per close to go."""
    cs = A.segment_closes(SEG)
    if not cs: return None
    last = max(cs, key=lambda e: int(e.get("epoch", 0))); n = int(last.get("epoch", 0))
    per = int(A.params().get("auto_epoch_seconds") or 21600)
    return int(last.get("ts") or 0) + per * (CLOSE - n) if n < CLOSE else int(last.get("ts") or 0)

def for_address(a):
    v = table().get(a)
    if not v: return None
    st = status()
    return dict(amount=v, state=st["state"], close=CLOSE, segment=SEG, ts=st["close_ts"] or expected_ts(), post=POST, notice=NOTICE["id"])

def effect_text():
    st = status()["state"]
    word = {"scheduled": "Scheduled", "executed": "Executed", "closed_no_record": "E44 closed, not in the record"}[st]
    return f"Burns {total() / 1e6:,.2f}M POA from {len(table())} Agents' locked at the E{CLOSE} close", word

def api():
    st = status()
    return dict(ballot=POST, tally=TALLY, close=CLOSE, segment=SEG, lifetime_epoch=SG.gkey(CLOSE, SEG), agents=len(table()), total=round(total(), 6),
                status=st, expected_close_ts=expected_ts() if st["state"] == "scheduled" else None,
                table=dict(sha256=SHA256, ipfs=CID, rows=len(table())), notice=NOTICE, source=URL,
                note="Scheduled amounts come from the G0 notice's table. Balances and supply change only from the close record.")


def locked_after(a, locked):
    """locked_est less this Agent's correction once the E44 record carries it (taken from its last unlocks)."""
    v = table().get(a)
    if not v or locked is None or status()["state"] != "executed": return locked
    return max(0.0, locked - v)
