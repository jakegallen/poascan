"""Paused closes (1.26.192, LabLeak comment 6258): forward-compatible reading of a halt flag on close records.

Tessellate asked minepoa's operators for maintenance windows, or an overlapped_halt flag, on /api/epochs close records.
Neither exists yet (checked on the E10 and E11 records, Oct 27 2026). When a close record POAScan already ingests carries
one, the close is tagged Paused on its epoch page, the /chain close history and the Governance close views, and the API
rows carry it. No new request: this reads only the stored close records. Absent fields change nothing (paused false,
pause null).

Read, in this order, at the record's top level and in its basis:
- overlapped_halt: true, a nonzero number, a non-empty string, or an object or list. An object may carry a window
  (start and end keys, below) or a windows list; a list is read as windows. false, 0, "" or null means not paused,
  even when windows are also listed (they are still exposed).
- maintenance_windows, maintenance_window, halt_windows, halt_window, maintenance, halts: one window object or a list.
  With no overlapped_halt, any readable window marks the close paused.
A window has a start under start, start_ts, from, since, started_at or begin, and an end under end, end_ts, to, until,
ended_at or finish: Unix seconds, milliseconds (scaled), or an ISO 8601 UTC string. A missing end stays null (open)."""
import calendar, re, time

FLAG = "overlapped_halt"
WINDOW_KEYS = ("maintenance_windows", "maintenance_window", "halt_windows", "halt_window", "maintenance", "halts")
START = ("start", "start_ts", "from", "since", "started_at", "begin")
END = ("end", "end_ts", "to", "until", "ended_at", "finish")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")

def ts_of(v):
    """Unix seconds from seconds, milliseconds or an ISO 8601 string; None when unreadable."""
    if isinstance(v, bool) or v is None: return None
    if isinstance(v, (int, float)):
        if v != v or v <= 0: return None
        return int(v / 1000) if v > 1e11 else int(v)
    if isinstance(v, str):
        s = v.strip()
        if re.fullmatch(r"\d{9,13}(\.\d+)?", s): return ts_of(float(s))
        m = _ISO.match(s)
        if not m: return None
        y, mo, d, h, mi, se, z = m.groups()
        t = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(se or 0), 0, 0, 0))
        if z and z != "Z":
            sg = 1 if z[0] == "+" else -1; zz = z[1:].replace(":", "")
            t -= sg * (int(zz[:2]) * 3600 + int(zz[2:]) * 60)
        return t
    return None

def _first(d, keys):
    for k in keys:
        if k in d: return d[k]
    return None

def window(w):
    """{start_ts, end_ts} from one window object, or None without a readable start."""
    if not isinstance(w, dict): return None
    a = ts_of(_first(w, START)); b = ts_of(_first(w, END))
    if a is None: return None
    if b is not None and b < a: a, b = b, a
    return dict(start_ts=a, end_ts=b)

def windows(v):
    """Windows from one object, a list of them, or an object with a windows list; sorted, duplicates dropped."""
    if isinstance(v, dict) and isinstance(v.get("windows"), list): v = v["windows"]
    xs = v if isinstance(v, list) else [v]
    out = []
    for x in xs:
        w = window(x)
        if w and w not in out: out.append(w)
    return sorted(out, key=lambda w: w["start_ts"])

def _truthy(v):
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)): return v != 0
    if isinstance(v, str): return v.strip().lower() not in ("", "false", "0", "no", "none", "null")
    if isinstance(v, (dict, list)): return bool(v)
    return False

def of_record(e):
    """None when the close record carries none of the fields; else dict(paused, overlapped_halt, windows, fields)."""
    if not isinstance(e, dict): return None
    places = [("", e)] + ([("basis.", e["basis"])] if isinstance(e.get("basis"), dict) else [])
    flag = None; ws = []; fields = []
    for pre, d in places:
        if FLAG in d and d[FLAG] is not None:
            fields.append(pre + FLAG)
            if flag is None: flag = _truthy(d[FLAG])
            else: flag = flag or _truthy(d[FLAG])
            if isinstance(d[FLAG], (dict, list)): ws += windows(d[FLAG])
        for k in WINDOW_KEYS:
            if k in d and d[k] is not None:
                got = windows(d[k])
                if got or isinstance(d[k], (dict, list)): fields.append(pre + k)
                ws += got
    if not fields: return None
    uniq = []
    for w in sorted(ws, key=lambda w: w["start_ts"]):
        if w not in uniq: uniq.append(w)
    paused = flag if flag is not None else bool(uniq)
    return dict(paused=bool(paused), overlapped_halt=flag, windows=uniq, fields=fields)

def fields_for(e):
    """The two API fields every close row carries: paused (bool) and pause (the of_record dict, or null)."""
    p = of_record(e)
    return dict(paused=bool(p and p["paused"]), pause=p)

def by_epoch():
    """{epoch: of_record} for the selected segment's paused closes only (from the stored records; no request)."""
    from . import analytics as A, db, segments as SG
    kind = SG.blob_kind()   # the stored copy: ts is whole seconds, so the write generation is in the key too (as analytics.epochs_raw)
    return _by_epoch((kind, A.epochs_ts(), db.blob_gen(kind)), SG.selected())

_cache = {}
def _by_epoch(ts, seg):
    k = (ts, seg)
    if k in _cache: return _cache[k]
    from . import analytics as A
    out = {}
    for e in A.epochs_raw():
        p = of_record(e)
        if p and p["paused"]:
            try: out[int(e.get("epoch"))] = p
            except (TypeError, ValueError): pass
    _cache.clear(); _cache[k] = out
    return out

def _utc(t): return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))

def tip_text(p):
    """Plain hover text in UTC (the no-script fallback)."""
    ws = (p or {}).get("windows") or []
    if not ws: return "Paused: this close record flags overlapped_halt (no window times in the record)"
    parts = [f"{_utc(w['start_ts'])} to {_utc(w['end_ts']) if w['end_ts'] else 'not ended'}" for w in ws]
    return "Paused: the close record lists a halt or maintenance window, " + "; ".join(parts)

def tip_ltt(p):
    """The same hover as an app.js local-time template ({t:ts})."""
    ws = (p or {}).get("windows") or []
    if not ws: return "Paused: this close record flags overlapped_halt (no window times in the record)"
    parts = ["{t:%d} to %s" % (w["start_ts"], "{t:%d}" % w["end_ts"] if w["end_ts"] else "not ended") for w in ws]
    return "Paused: the close record lists a halt or maintenance window, " + "; ".join(parts)

def tag(p):
    """The Paused tag (empty string when p is None or not paused). The title reads local in the browser (data-ltt)."""
    if not p or not p.get("paused"): return ""
    from html import escape as E
    return f' <span class="tag warn ptag" title="{E(tip_text(p))}" data-ltt="{E(tip_ltt(p))}">Paused</span>'

def tag_for(n):
    """The Paused tag for close n of the selected segment, or ""."""
    try: return tag(by_epoch().get(int(n)))
    except Exception: return ""
