"""Private ops stats for POASwap's dashboard (GET /ops/internal, Bearer POASCAN_STATS_TOKEN, else the normal 404).
Read only from POAScan's own database and memory: nothing here calls minepoa.com. Counts, times and short classes only:
no IP, user agent, hash, address, tx id, tx body or upstream response body leaves this module.

Sections (UTC days, newest first; times are unix seconds):
  fetch_log        current state per upstream endpoint key (the fetch_log table; a snapshot, not range filtered)
  invalid_txs      refused txs seen in the /api/txs window, by error class, per day POAScan first saw them
  probes           the hosted route check per route and day: reads, clear reads, p50/p95 latency, status codes
  upstream_budget  upstream reads POAScan chose not to send, per endpoint key and day, by reason
Fields that start with this release carry since_ts (when collection began); days before it are absent, never filled in."""
import datetime as dt, re, time
from . import db

MAX_DAYS, DEFAULT_DAYS = 31, 7
SINCE_BLOB = "ops_internal_since"
DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ERR_CAP = 40   # error classes listed per day; the rest fold into 'other'

def start(now=None):
    """Record when collection of the new counters began (once; kept across restarts)."""
    have = db.get_blob(SINCE_BLOB)[0] or {}
    if not {"probes", "upstream_budget"} <= set(have):
        t = int(now or time.time()); db.put_blob(SINCE_BLOB, dict({"probes": t, "upstream_budget": t}, **have))

def _since(k): return (db.get_blob(SINCE_BLOB)[0] or {}).get(k)

def parse_range(qs, now=None):
    """(from, to) as YYYY-MM-DD; default the last DEFAULT_DAYS days ending today (UTC); at most MAX_DAYS. ValueError on bad input."""
    def one(k, default):
        v = qs.get(k)
        if v is None: return default
        if len(v) != 1 or not DATE_RX.match(v[0]): raise ValueError(f"{k} must be YYYY-MM-DD")
        try: return dt.date.fromisoformat(v[0])
        except ValueError: raise ValueError(f"{k} is not a valid date")
    today = dt.datetime.fromtimestamp(now or time.time(), dt.timezone.utc).date()
    to = one("to", today); fr = one("from", to - dt.timedelta(days=DEFAULT_DAYS - 1))
    if fr > to: raise ValueError("from is after to")
    if (to - fr).days + 1 > MAX_DAYS: raise ValueError(f"at most {MAX_DAYS} days per call")
    return fr.isoformat(), to.isoformat()

def _bounds(fr, to):
    lo = int(dt.datetime.fromisoformat(fr + "T00:00:00+00:00").timestamp())
    return lo, int(dt.datetime.fromisoformat(to + "T00:00:00+00:00").timestamp()) + 86400

def _day(t): return time.strftime("%Y-%m-%d", time.gmtime(t))

_ID = (re.compile(r"[0-9a-fA-F]{16,}"), re.compile(r"poa1[1-9A-HJ-NP-Za-km-z]{6,}"), re.compile(r"/\d+(?=/|$)"))
def endpoint_key(ep):
    """An endpoint key with any id-shaped part replaced (keys are templates already; this is a safety net)."""
    ep = str(ep or "")[:80]
    ep = _ID[0].sub(":id", ep); ep = _ID[1].sub(":addr", ep); return _ID[2].sub("/:n", ep)

def err_class(e):
    """fetch_log.err as a short class: 'HTTP 503' -> http_503, 'URLError: ...' -> URLError, known messages by name, else other."""
    e = (e or "").strip()
    if not e: return None
    m = re.match(r"^HTTP (\d{3})\b", e)
    if m: return "http_" + m.group(1)
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]{1,40}(?:Error|Exception|Timeout|timeout))\b", e)
    if m: return m.group(1)
    lo = e.lower()
    for k, c in (("non-json", "non_json"), ("too large", "too_large"), ("content-encoding", "bad_encoding"), ("timed out", "timeout"),
                 ("429", "pause_429"), ("backing off", "backoff"), ("busy", "busy")):
        if k in lo: return c
    return "other"

_EV = (re.compile(r"[0-9a-fA-F]{16,}"), re.compile(r"poa1[1-9A-HJ-NP-Za-km-z]{6,}"), re.compile(r"\d+(\.\d+)?"), re.compile(r"[^a-z0-9 _:.\-]"))
def invalid_class(e):
    """A refused tx's error text as a class: lower case, ids, addresses and numbers removed, the part before the first ':'."""
    s = (e or "").strip().lower()
    if not s: return "unknown"
    s = _EV[0].sub("", s); s = _EV[1].sub("", s); s = _EV[2].sub("n", s); s = _EV[3].sub(" ", s)
    s = re.sub(r"\s+", " ", s.split(":")[0]).strip(" .-_")[:48].strip()
    return s or "unknown"

def fetch_log():
    out = {}
    for r in db.q("SELECT endpoint, last_ok, last_err, err, fails, next_at, bytes FROM fetch_log ORDER BY endpoint"):
        k = endpoint_key(r["endpoint"]); prev = out.get(k)
        row = dict(last_ok_ts=r["last_ok"] or None, last_error_ts=r["last_err"] or None, last_error=err_class(r["err"]) if r["last_err"] else None,
                   fails=int(r["fails"] or 0), next_try_ts=r["next_at"] or None, bytes=r["bytes"])
        if prev:   # two raw keys that template to one: keep the newest of each time, the larger fail run
            for f in ("last_ok_ts", "last_error_ts", "next_try_ts"): row[f] = max([x for x in (prev[f], row[f]) if x] or [None])
            row["fails"] = max(prev["fails"], row["fails"]); row["bytes"] = row["bytes"] if row["bytes"] is not None else prev["bytes"]
        out[k] = row
    return dict(scope="current", endpoints=out)

def _fold(m):
    top = dict(sorted(m.items(), key=lambda kv: (-kv[1], kv[0]))[:ERR_CAP]); rest = sum(v for k, v in m.items() if k not in top)
    if rest: top["other"] = top.get("other", 0) + rest
    return top

def invalid_txs(fr, to):
    lo, hi = _bounds(fr, to); days, tot = {}, {}
    for r in db.q("SELECT first_seen, error FROM invalid_txs WHERE first_seen >= ? AND first_seen < ?", (lo, hi)):
        c = invalid_class(r["error"]); d = days.setdefault(_day(r["first_seen"]), {})
        d[c] = d.get(c, 0) + 1; tot[c] = tot.get(c, 0) + 1
    first = (db.q1("SELECT MIN(first_seen) AS t FROM invalid_txs WHERE first_seen > 0") or {}).get("t")
    return dict(since_ts=first, total=sum(tot.values()), by_error=_fold(tot),
                days=[dict(day=k, total=sum(v.values()), by_error=_fold(v)) for k, v in sorted(days.items(), reverse=True)])

def _pct(xs, p):
    if not xs: return None
    xs = sorted(xs); return xs[min(len(xs) - 1, max(0, int(round(p / 100 * (len(xs) - 1)))))]

def probes(fr, to):
    lo, hi = _bounds(fr, to); days = {}
    for r in db.q("SELECT ts, route, code, ms, ok FROM route_checks WHERE ts >= ? AND ts < ? ORDER BY ts", (lo, hi)):
        e = days.setdefault(_day(r["ts"]), {}).setdefault(endpoint_key(r["route"]), dict(count=0, ok=0, _ms=[], status_codes={}))
        e["count"] += 1; e["ok"] += int(r["ok"] or 0); e["status_codes"][r["code"]] = e["status_codes"].get(r["code"], 0) + 1
        if r["code"].isdigit() and r["ms"] is not None: e["_ms"].append(int(r["ms"]))
    out = []
    for d in sorted(days, reverse=True):
        eps = {}
        for k, e in sorted(days[d].items()):
            ms = e.pop("_ms"); eps[k] = dict(e, p50_ms=_pct(ms, 50), p95_ms=_pct(ms, 95), status_codes=dict(sorted(e["status_codes"].items())))
        out.append(dict(day=d, endpoints=eps))
    return dict(since_ts=_since("probes"), days=out)

REASONS = ("visitor_cap", "pause_429", "backoff")
def upstream_budget(fr, to):
    days = {}
    for r in db.q("SELECT day, endpoint, reason, n FROM upstream_denials WHERE day BETWEEN ? AND ?", (fr, to)):
        e = days.setdefault(r["day"], {}).setdefault(endpoint_key(r["endpoint"]), dict({k: 0 for k in REASONS}, total=0, visitor_cap_by={}))
        top, _, sub = r["reason"].partition(":")
        if top not in REASONS: continue
        e[top] += r["n"]; e["total"] += r["n"]
        if sub: e["visitor_cap_by"][sub] = e["visitor_cap_by"].get(sub, 0) + r["n"]
    return dict(since_ts=_since("upstream_budget"), days=[dict(day=d, endpoints=dict(sorted(days[d].items()))) for d in sorted(days, reverse=True)])

def report(fr, to, version, now=None):
    from . import indexer as I
    try: I.flush_counts(force=True)   # this process's in-memory denials reach the table first (a local write, no request)
    except Exception: pass
    return {"from": fr, "to": to, "generated_ts": int(now or time.time()), "version": version,
            "fetch_log": fetch_log(), "invalid_txs": invalid_txs(fr, to), "probes": probes(fr, to), "upstream_budget": upstream_budget(fr, to)}
