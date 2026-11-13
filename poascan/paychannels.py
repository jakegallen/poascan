"""1.26.318: Answer pay and Grading pay from E76 on, only from published fields.

W-floor P1 (ballot 2625, params.payout_channels_from_epoch) caps answer pay and grading pay
separately from the E76 close. Per-address seal counts (basis.seal_load) are not public pay
amounts and are never turned into a split. Until a close record or close report publishes
explicit channel amounts, the combined rewards total stands and the split fields are null.
"""
from . import db
from . import segments as SG

# Verified live on minepoa.com/api/params on 12 Nov 2026. Used only when the cached params
# copy has not yet got the key. A later live value in params always wins.
DEFAULT_FROM_EPOCH = 76
PARAM_KEY = "payout_channels_from_epoch"

# Blocks whose short keys (answer, grading) may be read as amounts.
BLOCK_KEYS = ("payout_channels", "pay_channels", "reward_channels")
ANSWER_PAY_KEYS = ("answer_pay", "answers_pay")
GRADING_PAY_KEYS = ("grading_pay", "grades_pay")
SHORT_ANSWER = ANSWER_PAY_KEYS + ("answer",)
SHORT_GRADING = GRADING_PAY_KEYS + ("grading",)
ADDR_MAP_KEYS = ("by_addr", "by_address", "addresses", "pay_channels_by_addr")
ADDR_RX = ("poa1",)

def _params(p=None):
    if p is not None: return p or {}
    from . import analytics as A
    return A.params() or {}

def from_epoch(p=None):
    """The first epoch in the current segment at which a published split may appear, or None."""
    v = _params(p).get(PARAM_KEY)
    if v is None or v == "": return DEFAULT_FROM_EPOCH
    try: return int(v)
    except (TypeError, ValueError): return None

def active(epoch, segment=None, p=None):
    """True for a current-segment close at or after payout_channels_from_epoch."""
    fr = from_epoch(p)
    if fr is None: return False
    try: n = int(epoch)
    except (TypeError, ValueError): return False
    seg = SG.CURRENT if segment is None else int(segment)
    return seg == SG.CURRENT and n >= fr

def _num(v):
    """A published amount, or None. Booleans and non-numeric strings are not amounts."""
    if v is None or isinstance(v, bool): return None
    if isinstance(v, int): return float(v)
    if isinstance(v, float): return None if v != v else float(v)
    if isinstance(v, str) and v.strip():
        try:
            x = float(v)
        except ValueError:
            return None
        return None if x != x else x
    return None

def _is_addr(k):
    return isinstance(k, str) and k.startswith("poa1") and 20 <= len(k) <= 80

def _pick(obj, keys):
    if not isinstance(obj, dict): return None
    for k in keys:
        if k in obj:
            n = _num(obj[k])
            if n is not None: return n
    return None

def _pair(obj, short=False):
    """(answer_pay, grading_pay) from one dict. short=True allows 'answer' / 'grading'."""
    if not isinstance(obj, dict): return None, None
    ak, gk = (SHORT_ANSWER, SHORT_GRADING) if short else (ANSWER_PAY_KEYS, GRADING_PAY_KEYS)
    return _pick(obj, ak), _pick(obj, gk)

def _addr_entry(obj):
    if not isinstance(obj, dict): return None
    a, g = _pair(obj, short=True)
    if a is None and g is None: return None
    return dict(answer_pay=a, grading_pay=g)

def _addr_map(obj):
    """A {poa1: {answer_pay, grading_pay}} map, or empty."""
    if not isinstance(obj, dict) or not obj: return {}
    # wrapper: {by_addr: {...}}
    for k in ADDR_MAP_KEYS:
        if isinstance(obj.get(k), dict):
            return _addr_map(obj[k])
    out = {}
    addrs = [k for k in obj if _is_addr(k)]
    if addrs and len(addrs) == len(obj):
        # either {addr: {answer_pay, ...}} or {addr: amount} (not a split; ignore)
        for k, v in obj.items():
            row = _addr_entry(v)
            if row: out[k] = row
        return out
    return {}

def _pay_maps(obj):
    """Top-level or basis maps named exactly answer_pay / grading_pay, keyed by poa1 address."""
    if not isinstance(obj, dict): return {}
    am = obj.get("answer_pay") if isinstance(obj.get("answer_pay"), dict) else None
    gm = obj.get("grading_pay") if isinstance(obj.get("grading_pay"), dict) else None
    if not am and not gm: return {}
    keys = set()
    if am: keys.update(k for k in am if _is_addr(k))
    if gm: keys.update(k for k in gm if _is_addr(k))
    if not keys: return {}
    out = {}
    for k in keys:
        a = _num((am or {}).get(k)) if am is not None else None
        g = _num((gm or {}).get(k)) if gm is not None else None
        if a is None and g is None: continue
        out[k] = dict(answer_pay=a, grading_pay=g)
    return out

def _from_block(obj):
    """Amounts from a named channel block (totals and optional by_addr)."""
    if not isinstance(obj, dict): return None, None, {}
    a, g = _pair(obj, short=True)
    by = {}
    for k in ADDR_MAP_KEYS:
        if isinstance(obj.get(k), dict):
            by = _addr_map(obj[k])
            break
    if not by:
        # the block itself may be {poa1: {...}} with no totals
        maybe = _addr_map(obj)
        if maybe: by = maybe
    return a, g, by

def extract(src):
    """Read explicit channel amounts from one published object (a close record or close report).

    Returns {answer_pay, grading_pay, by_addr}. Missing sides stay None. Never infers a figure.
    """
    empty = dict(answer_pay=None, grading_pay=None, by_addr={})
    if not isinstance(src, dict): return empty
    a = g = None
    by = {}
    # 1. named block at the top or under basis
    for root in (src, src.get("basis") if isinstance(src.get("basis"), dict) else None):
        if not isinstance(root, dict): continue
        for k in BLOCK_KEYS:
            if isinstance(root.get(k), dict):
                ba, bg, bby = _from_block(root[k])
                if a is None: a = ba
                if g is None: g = bg
                if bby and not by: by = bby
        maps = _pay_maps(root)
        if maps and not by: by = maps
        for k in ADDR_MAP_KEYS:
            if not by and isinstance(root.get(k), dict):
                by = _addr_map(root[k])
        # totals named exactly answer_pay / grading_pay only when they are scalars, not maps
        if a is None: a = _pick(root, ANSWER_PAY_KEYS)
        if g is None: g = _pick(root, GRADING_PAY_KEYS)
    if (a is None or g is None) and by:
        if a is None:
            xs = [v["answer_pay"] for v in by.values() if v.get("answer_pay") is not None]
            if xs: a = round(sum(xs), 6)
        if g is None:
            xs = [v["grading_pay"] for v in by.values() if v.get("grading_pay") is not None]
            if xs: g = round(sum(xs), 6)
    return dict(answer_pay=a, grading_pay=g, by_addr=by)

def reports_for(epoch):
    """Stored close-report copies for this epoch, newest authority first. No network read."""
    out, n = [], int(epoch)
    cr, _ = db.get_blob("close_report_auth")
    if isinstance(cr, dict):
        try:
            if int(cr.get("close_epoch")) == n: out.append(cr)
        except (TypeError, ValueError):
            pass
    pend, _ = db.get_blob("close_reports_pending")
    if isinstance(pend, dict):
        row = pend.get(str(n)) or pend.get(n)
        if isinstance(row, dict): out.append(row)
    return out

def slim_fields(src):
    """Channel fields to keep on a closepend slim row so a later page can read them."""
    ch = extract(src)
    out = {}
    if ch["answer_pay"] is not None: out["answer_pay"] = ch["answer_pay"]
    if ch["grading_pay"] is not None: out["grading_pay"] = ch["grading_pay"]
    if ch["by_addr"]: out["pay_channels_by_addr"] = ch["by_addr"]
    return out

def for_close(epoch, rec=None, reports=None, segment=None, p=None):
    """Channel totals and per-address map for one close, or nulls when unpublished / off.

    state: off (before E76 or archived segment), pending (in range, no public amounts),
    split (at least one published channel amount).
    """
    on = active(epoch, segment, p)
    found = dict(answer_pay=None, grading_pay=None, by_addr={})
    if on:
        sources = []
        if isinstance(rec, dict): sources.append(rec)
        if reports is None: reports = reports_for(epoch)
        for r in reports or []:
            if isinstance(r, dict): sources.append(r)
        for src in sources:
            ch = extract(src)
            if found["answer_pay"] is None: found["answer_pay"] = ch["answer_pay"]
            if found["grading_pay"] is None: found["grading_pay"] = ch["grading_pay"]
            if ch["by_addr"] and not found["by_addr"]: found["by_addr"] = ch["by_addr"]
            if (found["answer_pay"] is not None or found["grading_pay"] is not None or found["by_addr"]):
                # keep scanning for a missing side, but do not overwrite a published value
                pass
    state = "off" if not on else ("split" if (found["answer_pay"] is not None or found["grading_pay"] is not None or found["by_addr"]) else "pending")
    return dict(answer_pay=found["answer_pay"], grading_pay=found["grading_pay"], by_addr=found["by_addr"], state=state)

def row_fields(epoch, rec=None, reports=None, segment=None, p=None):
    """Additive keys for an epoch list or pending-close row."""
    ch = for_close(epoch, rec=rec, reports=reports, segment=segment, p=p)
    return dict(answer_pay=ch["answer_pay"], grading_pay=ch["grading_pay"], pay_split=ch["state"])

def for_addr(epoch, addr, rec=None, reports=None, segment=None, p=None):
    """Per-Agent channel amounts. Close-level totals are not used as this Agent's split."""
    ch = for_close(epoch, rec=rec, reports=reports, segment=segment, p=p)
    row = (ch["by_addr"] or {}).get(addr) or {}
    return dict(answer_pay=row.get("answer_pay"), grading_pay=row.get("grading_pay"), state=ch["state"])
