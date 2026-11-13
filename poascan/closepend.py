"""1.26.307: closes minepoa.com has made whose full record POAScan cannot read yet.

minepoa.com's /api/epochs (the full close records: pool, rewards, burned, basis) has answered 503 'halted' since
Nov 8, 2026, while /api/status keeps counting closes (epochs_closed). Home and /chain therefore stopped at E57.
Each close's report is still published at /api/close-report?epoch=N (archived, never changes once written), so
POAScan reads that once per missing close, at most PER_RUN per run, and shows the close with what is known:
its number, close time, settled split and intake. Paid, minted and burned stay blank until the record is read.
The node's supply step across the close (from POAScan's own archived /api/status reads, no extra request) is
carried as supply_step. A close leaves this list as soon as /api/epochs lists its record."""
import json, time, logging
from . import db, analytics as A
from . import segments as SG

log = logging.getLogger("poascan.closepend")
PATH = "/api/close-report"
EP = "/api/close-report?epoch"   # its own fetch_log row, so the hourly latest read keeps its health
BLOB = "close_reports_pending"
PER_RUN = 2        # light on minepoa.com: two small archived reads per run, a run every 10 minutes
GAP_S = 3
MAX_BACK = 40      # never walk further back than this many closes

def _record_last():
    with SG.use(SG.CURRENT):
        ep = A.epoch_rows()
    return int(ep[-1]["epoch"]) if ep else None

def _closed_last():
    st, _ = db.get_blob("status")
    n = (st or {}).get("epochs_closed")
    try: n = int(n)
    except (TypeError, ValueError): return None
    return n - 1 if n > 0 else None   # epochs_closed counts E0 too: 67 means E0 to E66

def _slim(d, n):
    if not isinstance(d, dict): return None
    try:
        if int(d.get("close_epoch")) != int(n) or not d.get("close_ts"): return None
    except (TypeError, ValueError): return None
    ss = d.get("settled_split") or {}; es = d.get("establishment") or {}
    from . import paychannels as _PCH
    return dict(epoch=int(n), close_ts=int(d["close_ts"]), settled_count=d.get("settled_count"),
                settled_passed=ss.get("passed"), settled_failed=ss.get("failed"),
                settled_expired_no_jury=(ss.get("expired_empty_jury") or 0) + (ss.get("expired_with_seals") or 0) if ss else None,
                admitted=es.get("admitted"), eligible=es.get("eligible"), fetched_at=int(time.time()),
                **_PCH.slim_fields(d))

def missing():
    """Close numbers past the last record, up to the last close /api/status counts."""
    a, b = _record_last(), _closed_last()
    if a is None or b is None or b <= a: return []
    return list(range(max(a + 1, b - MAX_BACK + 1), b + 1))

def job(fetch=None, sleep=time.sleep):
    """Read the report of each missing close once. Returns how many were stored."""
    from . import indexer as I
    fetch = fetch or (lambda p: I.fetch(p, timeout=30, endpoint=EP))
    have, _ = db.get_blob(BLOB); have = {int(k): v for k, v in (have or {}).items()}
    miss = missing(); keep = {n: v for n, v in have.items() if n in miss}
    changed = len(keep) != len(have)
    lr, _ = db.get_blob("close_report_auth")   # the hourly latest read already holds the newest close: no extra request
    if isinstance(lr, dict):
        try: n = int(lr.get("close_epoch"))
        except (TypeError, ValueError): n = None
        if n in miss and n not in keep and (s := _slim(lr, n)): keep[n] = s; changed = True
    todo = [n for n in reversed(miss) if n not in keep][:PER_RUN]   # newest first, so Home fills from the top
    for i, n in enumerate(todo):
        if i: sleep(GAP_S)
        try: d = fetch(f"{PATH}?epoch={n}")
        except Exception as e:
            log.warning("close report E%s: %s", n, type(e).__name__); break
        s = _slim(d, n)
        if s: keep[n] = s; changed = True
    if changed:
        db.put_blob(BLOB, {str(k): v for k, v in sorted(keep.items())})
        try:
            from . import htmlcache as _HC; _HC.note_close()
        except Exception: pass
    return len(todo)

def _supply_step(t):
    """The node's supply after the close minus before it, from archived /api/status reads within 2 h (as reconcile does)."""
    b = a = None
    for x in db.q("SELECT ts, json FROM snaps WHERE kind='status' AND ts BETWEEN ? AND ? ORDER BY ts", (t - 7200, t + 7200)):
        try: j = json.loads(x["json"]); sp = float(j.get("supply"))
        except Exception: continue
        at = x["ts"]
        try:
            from .reconcile import _iso_ts; at = _iso_ts(j.get("as_of")) or at
        except Exception: pass
        if at <= t: b = sp
        elif a is None: a = sp
    return round(a - b, 6) if a is not None and b is not None else None

def rows():
    """Closes with a report but no record yet, oldest first. Empty for an archived segment or when none is missing."""
    if SG.archived(): return []
    have, _ = db.get_blob(BLOB)
    if not have: return []
    miss = set(missing()); out = []
    for k, v in sorted(((int(k), v) for k, v in have.items())):
        if k not in miss: continue
        from . import paychannels as _PCH
        out.append(dict(v, segment=SG.CURRENT, lifetime=SG.gkey(k, SG.CURRENT), record="pending", rewards_state="record_pending",
                        supply_step=_supply_step(v["close_ts"]), pool=None, minted=None, burned=None, paid=None, burn_pct=None, median=None,
                        **_PCH.row_fields(k, rec=v, reports=[v], segment=SG.CURRENT)))
    return out

def span():
    """'E58 to E66' for the closes counted with no record, or None."""
    m = missing()
    if not m: return None
    return f"E{m[0]}" if len(m) == 1 else f"E{m[0]} to E{m[-1]}"

def run():
    """The indexer job: gated and backed off like every other minepoa read."""
    from . import indexer as I
    if not missing(): return 0
    if not I.can_fetch(EP): I.skip_backoff(EP); return 0
    try: return job()
    except I.Busy as e: log.warning("%s: %s", EP, e); return 0
