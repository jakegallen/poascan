"""1.26.216: the basis the reward figures stand at, against the balance.

Balance comes from the agent list (or an address read), which minepoa.com updates as soon as a close pays out. Total
rewards, Spendable and Locked come from the close records POAScan holds. For the time between a close and POAScan reading
its record, the balance is ahead of the three reward figures. They are then tagged Stale with the close they stand at,
never re-split or estimated, and the header status note says why. Local data only: no upstream read."""
import time
from . import analytics as A, segments as SG

GRACE_S = 900   # a close is taken as due this long after the newest held close plus one epoch length

def held():
    """The newest close record POAScan holds in the current segment: dict(segment, epoch, gkey, close_ts, count), or None."""
    ep = A.segment_closes(SG.CURRENT)
    if not ep: return None
    e = max(ep, key=lambda r: int(r.get("epoch", 0)))
    k = int(e.get("epoch", 0))
    return dict(segment=SG.CURRENT, epoch=k, gkey=SG.gkey(k, SG.CURRENT), close_ts=int(e.get("ts") or 0) or None, count=len(ep))

def lag(at=None):
    """None while the held close records look current, else dict(kind, missing, due_ts, reason).
    missing: minepoa's status lists more closes than POAScan holds. due: a newer read (at) is past the next close's due time."""
    h = held()
    if not h: return None
    try: up = int(A.status().get("epochs_closed") or 0)
    except (TypeError, ValueError): up = 0
    if up > h["count"]:
        n = up - h["count"]
        return dict(kind="missing", missing=n, due_ts=None,
                    reason=f"minepoa.com lists {n} newer close{'s' if n > 1 else ''} than POAScan has read")
    period = int(A.params().get("auto_epoch_seconds") or 21600)
    due = (h["close_ts"] or 0) + period
    at = int(at or time.time())
    try:
        from . import maint as M
        paused = bool(M.state()["active"])   # closes stop during maintenance: an overdue close is not a missed record then
    except Exception: paused = False
    if h["close_ts"] and at > due + GRACE_S and not paused:
        return dict(kind="due", missing=None, due_ts=due, reason=f"the E{h['epoch'] + 1} close was due and POAScan has not read its record yet")
    return None

def _unfolded(a, rb, h):
    """1.26.218: the newest held close pays a, but the reward figures (rb, cached apart from the close records) do not
    have it yet: the minute or so after POAScan reads a close record."""
    if not a or rb is None or not h: return False
    e = max(A.segment_closes(SG.CURRENT), key=lambda r: int(r.get("epoch", 0)))
    try: v = float((e.get("rewards") or {}).get(a) or 0)
    except (TypeError, ValueError): v = 0
    return v > 0 and h["gkey"] not in rb

def basis(bal, rsum, bal_at=None, a=None, rb=None):
    """The reward figures' basis for one address: dict(as_of (segment, epoch, close_ts), behind, reason, balance_ahead_by).
    behind when the balance and the reward sum disagree while a newer close is due or listed upstream, or (1.26.218, with
    a and rb) while the newest held close pays a but its reward is not in rb yet; as_of is then the close before it."""
    h = held(); lg = lag(bal_at)
    diff = None if bal is None else round(float(bal) - float(rsum or 0), 6)
    if _unfolded(a, rb, h):
        lg = dict(kind="unfolded", reason=f"POAScan read the E{h['epoch']} close record a moment ago and is adding it")
        prev = [r for r in A.segment_closes(SG.CURRENT) if int(r.get("epoch", 0)) == h["epoch"] - 1]
        h = dict(h, epoch=h["epoch"] - 1, close_ts=int(prev[0].get("ts") or 0) or None if prev else None)
        behind = True
    else: behind = bool(lg and diff is not None and abs(diff) > 0.01)
    return dict(as_of=dict(segment=h["segment"], epoch=h["epoch"], close_ts=h["close_ts"]) if h else None,
                behind=behind, reason=lg["reason"] if behind else None, balance_ahead_by=diff if behind else None)

def tag_text(b):
    """The Stale tag detail for Total rewards, Spendable and Locked when behind, else None."""
    if not b or not b["behind"] or not b["as_of"]: return None
    ep = b["as_of"]["epoch"]; ep = f"E{ep}" if b["as_of"]["segment"] == SG.CURRENT else f"S{b['as_of']['segment']} E{ep}"
    return f"As of the {ep} close. The balance already includes a newer close ({b['reason']}), so this is behind it until that record is read."

def pill_reason():
    """One line for the header status note while the close records are behind, else ''."""
    try:
        lg = lag(); h = held()
    except Exception: return ""
    if not lg or not h: return ""
    return f"Rewards, spendable and locked as of the E{h['epoch']} close: {lg['reason']}."
