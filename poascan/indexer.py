"""Polite poller for public minepoa.com endpoints. Read-only GETs only; never uses keys."""
import collections, json, os, random, re, threading, time, urllib.request, urllib.error, glob, logging, zlib
from . import db, strain as _ST

BASE = os.environ.get("POA_BASE", "https://minepoa.com")
UA = "POAScan-indexer/1.0 (+https://poascan.io; read-only)"
log = logging.getLogger("indexer")

def _env_num(name, default, lo=None, hi=None, cast=float):
    """Numeric env knob with a clamp; a bad value falls back to the default."""
    try: v = cast(os.environ.get(name, "") or default)
    except ValueError: v = cast(default)
    if lo is not None: v = max(lo, v)
    if hi is not None: v = min(hi, v)
    return v
_ei = lambda n, d, lo=None, hi=None: _env_num(n, d, lo, hi, int)

# ---- polling cadence (env-tunable; floors keep a bad value from hammering minepoa.com) ----
# Healthy cadence, and the slower one used while upstream is degraded: any 429, 5xx or timeout on the shared feed
# endpoints in the last DEGRADED_FOR_S seconds. Back to healthy once that window passes clean.
LIVE_S = _ei("POASCAN_LIVE_S", 60, 30)                         # /api/explorer/txs, healthy
LIVE_DEGRADED_S = _ei("POASCAN_LIVE_DEGRADED_S", 120, 30)      # /api/explorer/txs, degraded (never faster than 30 s)
STATUS_S = _ei("POASCAN_STATUS_S", 60, 60)                     # /api/status, one shared read for every feature
STATUS_DEGRADED_S = _ei("POASCAN_STATUS_DEGRADED_S", 120, 60)
NETWORKS_S = _ei("POASCAN_NETWORKS_S", 120, 60)                # /api/networks (height, checkpoint)
SWAPS_S = _ei("POASCAN_SWAPS_S", 60, 30, 120)                  # /api/swaps (swap mirrors read our cached copy, never minepoa.com)
FORUM_S = _ei("POASCAN_FORUM_S", 3600, 900)                    # communities plus one posts list per community
META_S = _ei("POASCAN_META_S", 300, 120)                       # anchors, notices, ballots
DEGRADED_FOR_S = _ei("POASCAN_DEGRADED_FOR_S", 900, 60)
LIVE_LIMIT = _ei("POASCAN_LIVE_LIMIT", 200, 20, 500)           # rows per /api/explorer/txs page
LIVE_MAX_PAGES = _ei("POASCAN_LIVE_MAX_PAGES", 3, 1, 10)       # gap fill after a pause: older pages until a seen txid
BACKOFF_BASE_S = _ei("POASCAN_BACKOFF_BASE_S", 30, 5)          # first retry delay; doubles per failure
BACKOFF_MAX_S = _ei("POASCAN_BACKOFF_MAX_S", 900, 60)
RETRY_AFTER_MAX_S = 6 * 3600                                   # a Retry-After beyond this is treated as this
FEED_EPS = ("/api/explorer/txs", "/api/status", "/api/networks", "/api/swaps")
# Hard allowlist: the indexer can only ever call these read-only paths.
ALLOWED = re.compile(r"^/(api/(status|networks|txs|explorer/txs|explorer/tx/[0-9a-f]{64}|explorer/address/poa1[1-9A-HJ-NP-Za-km-z]+|"
                     r"epochs|agents|anchors|params|release|notices|ballots|chains|swaps)|lableak/api/(communities|posts|posts/\d+))(\?[\w=&.\-]*)?$")

class Busy(Exception):
    def __init__(self, msg, retry=None):
        super().__init__(msg); self.retry = retry
class Missing(Busy):
    """The node does not know this id (HTTP 404, or a detail answer without an id). Never an endpoint failure."""
class Limited(Busy):
    """An on-demand read was refused by the upstream budget (per client or global); retry is in seconds."""
class Notice(Busy):
    """minepoa answered with a notice in place of data (strain.py). Nothing from it is stored; callers keep their last real copy."""
NOTICE_RETRY_S = _ei("POASCAN_NOTICE_RETRY_S", 300, 60)   # back-off floor after a notice response (polite to a strained endpoint)

NOT_MODIFIED = object()            # fetch(..., cond=True) result when the node answered 304 to our If-None-Match
MAX_BODY = 96 * 1024 * 1024        # decoded size cap (the epochs list is about 11 MB)
_etags = {}                        # path -> ETag of the last 200, in memory only (a restart sends one plain GET)

def _decode(raw, enc):
    """gzip bodies are inflated with a size cap; anything other than gzip or identity is refused."""
    enc = (enc or "").strip().lower()
    if enc in ("", "identity"): return raw
    if enc != "gzip": raise Busy("unexpected content-encoding " + enc[:20])
    d = zlib.decompressobj(16 + zlib.MAX_WBITS); out = d.decompress(raw, MAX_BODY)
    if d.unconsumed_tail: raise Busy("response too large")
    return out

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None   # surface the 3xx as an HTTPError
_NOREDIR = urllib.request.build_opener(_NoRedirect)
MISSING_CODES = (404, 301, 302, 303, 307, 308)   # minepoa answers an unknown tx id with a 307 to its HTML app

def fetch(path, timeout=60, endpoint=None, cond=False, soft=False):
    """GET BASE+path, return parsed JSON. Records health in fetch_log. Raises on failure.
    Always asks for gzip (SC-009). cond=True sends If-None-Match with the ETag of the last 200 for this exact path and
    returns NOT_MODIFIED on a 304, so the caller keeps what it stored. soft=True (single-id detail reads): redirects are
    not followed, and a 404 or a redirect (minepoa's answer for an unknown id) raises Missing without counting as an
    endpoint failure."""
    if not ALLOWED.match(path):
        raise ValueError("path not allowlisted")
    from . import keysafe as _KS   # POAScan holds no PoA key and never sends one
    if _KS.has_key(path) or _KS.has_cred_param(path.partition("?")[2]):
        raise ValueError("refused: credential-shaped value in an outbound path")
    ep = endpoint or path.split("?")[0]
    hold = _hold[0] - time.time()
    if hold > 0: deny(ep, "pause_429"); raise Limited("minepoa.com asked us to wait (429)", int(hold) + 1)
    hd = {"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip"}
    if cond and _etags.get(path): hd["If-None-Match"] = _etags[path]
    req = urllib.request.Request(BASE + path, headers=hd)
    now = int(time.time()); t0 = time.time()
    try:
        with (_NOREDIR.open(req, timeout=timeout) if soft else urllib.request.urlopen(req, timeout=timeout)) as r:
            wire = r.read(); raw = _decode(wire, r.headers.get("Content-Encoding")); et = r.headers.get("ETag")
        if raw[:1] not in (b"{", b"["):
            _probe(ep, True, t0, "200"); count(ep, 200)
            raise Busy("non-JSON response (load page?)")
        data = json.loads(raw)
        hit = _ST.detect(path, data, r.headers)   # strain notice guard: a stand-in is never stored, cached or shown as data
        if hit:
            _ST.record(path, hit); _probe(ep, False, t0, "notice"); count(ep, "notice")
            raise Notice("upstream notice instead of data: " + ";".join(hit["signals"])[:120], NOTICE_RETRY_S)
        _probe(ep, True, t0, "200"); count(ep, 200); _ST.clear(path)
        if cond:
            if et: _etags[path] = et
            else: _etags.pop(path, None)
        db.write("INSERT INTO fetch_log(endpoint,last_ok,fails,next_at,bytes,err) VALUES(?,?,0,0,?,NULL) "
                 "ON CONFLICT(endpoint) DO UPDATE SET last_ok=excluded.last_ok, fails=0, next_at=0, bytes=excluded.bytes",
                 (ep, now, len(raw)))
        return data
    except urllib.error.HTTPError as e:
        count(ep, e.code)
        if e.code == 304 and cond:
            _probe(ep, True, t0, "304")
            db.write("INSERT INTO fetch_log(endpoint,last_ok,fails,next_at,err) VALUES(?,?,0,0,NULL) "
                     "ON CONFLICT(endpoint) DO UPDATE SET last_ok=excluded.last_ok, fails=0, next_at=0", (ep, now))
            return NOT_MODIFIED
        retry = retry_after(e.headers.get("Retry-After"))
        body = None
        try:
            body = json.loads(_decode(e.read() or b"{}", e.headers.get("Content-Encoding")) or b"{}")
            retry = max(retry or 0, float(body.get("retry_after_seconds") or 0)) or None
        except Exception:
            pass
        try:
            if isinstance(body, dict):
                hit = _ST.detect(path, body, e.headers)
                if _ST.strong(hit): _ST.record(path, hit)   # an error that names a notice: show its text; the read already failed
        except Exception:
            pass
        if soft and e.code in MISSING_CODES:
            _probe(ep, True, t0, str(e.code)); raise Missing("not found")
        _probe(ep, False, t0, str(e.code))
        if e.code == 429: _hold[0] = max(_hold[0], time.time() + min(RETRY_AFTER_MAX_S, retry or BACKOFF_BASE_S))
        _fail(ep, f"HTTP {e.code}", retry)
        raise Busy(f"HTTP {e.code}", retry)
    except Busy as e:
        _fail(ep, str(e), e.retry); raise
    except Exception as e:
        count(ep, "err"); _probe(ep, False, t0, type(e).__name__); _fail(ep, type(e).__name__ + ": " + str(e)[:120], None)
        raise Busy(str(e))

def _probe(ep, ok, t0, code):
    try: db.write("INSERT INTO probes VALUES(?,?,?,?,?)", (int(time.time()), uptime_name(ep), 1 if ok else 0, int((time.time() - t0) * 1000), code))
    except Exception: pass

# Status probes: only the two public pages, every 10 min, first 1 KB. The JSON endpoints we already
# poll (status, swaps, communities) count toward uptime from those regular fetches instead.
PROBES = ["/", "/go.md"]
DERIVED = ("/api/status", "/api/swaps", "/lableak/api/communities")
def uptime_name(ep): return "probe " + ep if ep in DERIVED else ep
def job_probe():
    if _hold[0] > time.time():
        for path in PROBES: deny(path + " (probe)", "pause_429")
        return
    for path in PROBES:
        t0 = time.time()
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Range": "bytes=0-1023"})
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read(1024); _probe("probe " + path, 200 <= r.status < 400, t0, str(r.status)); count(path + " (probe)", r.status)
        except urllib.error.HTTPError as e: _probe("probe " + path, False, t0, str(e.code)); count(path + " (probe)", e.code)
        except Exception as e: _probe("probe " + path, False, t0, type(e).__name__); count(path + " (probe)", "err")
        time.sleep(0.5)
    db.write("DELETE FROM probes WHERE ts < ?", (int(time.time()) - 14 * 86400,))
    rollup_uptime()

def rollup_uptime(now=None):
    """Fold the last two UTC days of probe and fetch outcomes into one small row per day and endpoint; keep a year."""
    now = int(now or time.time()); d0 = (now // 86400 - 1) * 86400
    db.write("""INSERT OR REPLACE INTO uptime_daily(day, endpoint, n, ok, ms)
      SELECT (ts/86400)*86400, CASE WHEN endpoint IN (?,?,?) THEN 'probe ' || endpoint ELSE endpoint END, COUNT(*), SUM(ok), CAST(AVG(CASE WHEN ok=1 THEN ms END) AS INTEGER)
      FROM probes WHERE ts >= ? GROUP BY 1, 2""", DERIVED + (d0,))
    db.write("DELETE FROM uptime_daily WHERE day >= ? AND endpoint IN (?,?,?)", (d0,) + DERIVED)
    db.write("DELETE FROM uptime_daily WHERE day < ?", (now - 365 * 86400,))

_hold = [0.0]   # host-wide pause after a 429: every read waits it out (minepoa rate limits per client, not per path)

def retry_after(v, now=None):
    """Retry-After header in seconds: delta-seconds or an HTTP date. None when absent or unreadable."""
    v = (v or "").strip()
    if not v: return None
    if v.isdigit(): return float(v)
    try:
        import email.utils
        return max(0.0, email.utils.parsedate_to_datetime(v).timestamp() - (now or time.time()))
    except Exception: return None

def backoff_s(fails, retry=None, rnd=random.random):
    """Delay before the next try after `fails` failures in a row: exponential (BACKOFF_BASE_S doubling, capped at
    BACKOFF_MAX_S) with equal jitter (half fixed, half random), so retries spread out instead of lining up. A
    Retry-After (header or body) is a floor, plus up to 10 % jitter; it is honoured even beyond BACKOFF_MAX_S (to 6 h)."""
    cap = min(BACKOFF_MAX_S, BACKOFF_BASE_S * (2 ** min(max(fails, 1) - 1, 16)))
    d = cap / 2 + rnd() * cap / 2
    if retry:
        r = min(RETRY_AFTER_MAX_S, float(retry)); d = max(d, r + rnd() * r * 0.1)
    return d

def _fail(ep, err, retry):
    row = db.q1("SELECT fails FROM fetch_log WHERE endpoint=?", (ep,))
    fails = (row["fails"] if row else 0) + 1
    now = int(time.time())
    db.write("INSERT INTO fetch_log(endpoint,last_err,err,fails,next_at) VALUES(?,?,?,?,?) "
             "ON CONFLICT(endpoint) DO UPDATE SET last_err=excluded.last_err, err=excluded.err, fails=excluded.fails, next_at=excluded.next_at",
             (ep, now, err, fails, now + int(backoff_s(fails, retry))))

def degraded(now=None):
    """Upstream is degraded: a failed read (429, 5xx, timeout) on a shared feed endpoint in the last DEGRADED_FOR_S,
    or POASCAN_UPSTREAM_DEGRADED=1. Feed polls slow down to their *_DEGRADED_S cadence while this holds."""
    if os.environ.get("POASCAN_UPSTREAM_DEGRADED") == "1": return True
    now = now or time.time()
    if _hold[0] > now: return True
    r = db.q1(f"SELECT MAX(last_err) AS t FROM fetch_log WHERE endpoint IN ({','.join('?' * len(FEED_EPS))})", FEED_EPS)
    return bool(r and r["t"] and now - r["t"] < DEGRADED_FOR_S)

def live_every(): return LIVE_DEGRADED_S if degraded() else LIVE_S

def _last_try(ep):
    """Last read of ep (ok or not), from fetch_log, so a restart or deploy never adds an early read."""
    r = db.q1("SELECT last_ok, last_err FROM fetch_log WHERE endpoint=?", (ep,))
    return max((r["last_ok"] or 0), (r["last_err"] or 0)) if r else 0

# ---------------- upstream request counter ----------------
# Every request that leaves for minepoa.com (scheduled, on demand, probes, the hosted route check) is counted here by
# endpoint key (path template, plus the caller in brackets where one template has several) and status class, in
# minute buckets: in memory, flushed to upstream_counts about once a minute, kept UPSTREAM_KEEP_DAYS. Private:
# reported only in /ops/visits (token). Counts only; no ids, addresses or query strings.
UPSTREAM_KEEP_DAYS = 8
_ctr = collections.Counter(); _ctr_lock = threading.Lock(); _ctr_flushed = [0.0]
def _code_class(code):
    if code in (200, 304, 404, 429, "notice"): return str(code)
    if isinstance(code, int): return f"{code // 100}xx"
    return "err"
def count(ep, code, now=None):
    m = int((now or time.time()) // 60) * 60
    with _ctr_lock: _ctr[(m, ep, _code_class(code))] += 1
def _ensure_counts():
    db.write("CREATE TABLE IF NOT EXISTS upstream_counts(minute INTEGER, endpoint TEXT, code TEXT, n INTEGER, PRIMARY KEY(minute, endpoint, code))")
def flush_counts(force=False):
    if not force and time.time() - _ctr_flushed[0] < 60: return
    _ctr_flushed[0] = time.time()
    with _ctr_lock: items = list(_ctr.items()); _ctr.clear()
    _ensure_counts()
    if items:
        db.write("INSERT INTO upstream_counts VALUES(?,?,?,?) ON CONFLICT(minute, endpoint, code) DO UPDATE SET n = n + excluded.n",
                 [(m, ep, c, n) for (m, ep, c), n in items], many=True)
    db.write("DELETE FROM upstream_counts WHERE minute < ?", (int(time.time()) - UPSTREAM_KEEP_DAYS * 86400,))
    try: flush_denials()
    except Exception as e: log.warning("upstream denials flush: %s", type(e).__name__)
def template(ep): return ep.split(" (")[0]

# Upstream budget denials (1.26.26, private /ops/internal): a read POAScan chose not to send, per UTC day, endpoint key and
# reason. Counts only, in memory, flushed with the request counter to upstream_denials (kept DENY_KEEP_DAYS).
# pause_429: the host-wide pause after a 429. backoff: the endpoint key is backing off (scheduled reads count once per
# backoff window, a visitor read every time). visitor_cap:<cap>: a visitor-triggered read refused by the polite caps.
DENY_REASONS = ("pause_429", "backoff", "visitor_cap:recent", "visitor_cap:client", "visitor_cap:endpoint", "visitor_cap:global", "visitor_cap:inflight")
DENY_KEEP_DAYS = 400
_deny = collections.Counter(); _deny_seen = {}
def _utc_day(t): return time.strftime("%Y-%m-%d", time.gmtime(t))
def deny(ep, reason, now=None):
    if reason not in DENY_REASONS: return
    with _ctr_lock: _deny[(_utc_day(now or time.time()), ep, reason)] += 1
def skip_backoff(ep):
    """A scheduled read skipped because ep is backing off: counted once per backoff window (its next_at)."""
    try:
        r = db.q1("SELECT next_at FROM fetch_log WHERE endpoint=?", (ep,)); w = (r or {}).get("next_at") or 0
        with _ctr_lock:
            if _deny_seen.get(ep) == w: return
            _deny_seen[ep] = w
            if len(_deny_seen) > 500: _deny_seen.clear()
        deny(ep, "backoff")
    except Exception: pass
def _ensure_denials():
    db.write("CREATE TABLE IF NOT EXISTS upstream_denials(day TEXT NOT NULL, endpoint TEXT NOT NULL CHECK (length(endpoint) <= 80), "
             "reason TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, endpoint, reason)) WITHOUT ROWID")
def flush_denials():
    with _ctr_lock: items = list(_deny.items()); _deny.clear()
    _ensure_denials()
    if items:
        db.write("INSERT INTO upstream_denials VALUES(?,?,?,?) ON CONFLICT(day, endpoint, reason) DO UPDATE SET n = n + excluded.n",
                 [(d, ep[:80], r, n) for (d, ep, r), n in items], many=True)
    db.write("DELETE FROM upstream_denials WHERE day < ?", (_utc_day(time.time() - DENY_KEEP_DAYS * 86400),))
def upstream_report(now=None):
    """Requests to minepoa.com per endpoint: counts and per-hour rates over the last 15 min, 60 min and 24 h (full
    minutes only, so a partial minute never inflates a rate), per-hour buckets for the last 24 h, and status classes."""
    flush_counts(force=True); now = int(now or time.time()); cur = now // 60 * 60
    first = (db.q1("SELECT MIN(minute) AS m FROM upstream_counts") or {}).get("m")
    def win(mins):
        lo = cur - mins * 60; span = (cur - max(lo, first or cur)) / 3600
        rows = db.q("SELECT endpoint, SUM(n) AS n FROM upstream_counts WHERE minute >= ? AND minute < ? GROUP BY endpoint", (lo, cur))
        by = {r["endpoint"]: r["n"] for r in rows}; tp = {}
        for k, v in by.items(): tp[template(k)] = tp.get(template(k), 0) + v
        ph = lambda x: {k: round(v / span, 1) for k, v in sorted(x.items(), key=lambda kv: -kv[1])} if span > 0 else {}
        return dict(minutes=round(span * 60), total=sum(by.values()), per_hour_total=round(sum(by.values()) / span, 1) if span > 0 else None,
                    per_hour=ph(tp), per_hour_by_caller=ph(by), counts=dict(sorted(by.items(), key=lambda kv: -kv[1])))
    hours = {}
    for r in db.q("SELECT (minute/3600)*3600 AS h, endpoint, SUM(n) AS n FROM upstream_counts WHERE minute >= ? GROUP BY 1, 2", (cur - 86400,)):
        hours.setdefault(r["h"], {})[template(r["endpoint"])] = hours.get(r["h"], {}).get(template(r["endpoint"]), 0) + r["n"]
    codes = {}
    for r in db.q("SELECT endpoint, code, SUM(n) AS n FROM upstream_counts WHERE minute >= ? GROUP BY 1, 2", (cur - 3600,)):
        codes.setdefault(r["endpoint"], {})[r["code"]] = r["n"]
    return dict(counting_since=first, now=now, degraded=degraded(now), last_15m=win(15), last_60m=win(60), last_24h=win(1440),
                hourly=[dict(hour=h, **{"endpoints": hours[h]}) for h in sorted(hours)], codes_60m=codes,
                cadence=dict(live_s=LIVE_S, live_degraded_s=LIVE_DEGRADED_S, status_s=STATUS_S, status_degraded_s=STATUS_DEGRADED_S,
                             networks_s=NETWORKS_S, swaps_s=SWAPS_S, forum_s=FORUM_S, meta_s=META_S, live_limit=LIVE_LIMIT, live_max_pages=LIVE_MAX_PAGES))
def upstream_daily(frm, to):
    """{YYYY-MM-DD: {endpoint template: requests}} for /ops/visits days (UTC)."""
    import datetime as _dt
    flush_counts(force=True); out = {}
    lo = int(_dt.datetime.fromisoformat(frm + "T00:00:00+00:00").timestamp()); hi = int(_dt.datetime.fromisoformat(to + "T00:00:00+00:00").timestamp()) + 86400
    for r in db.q("SELECT minute/86400 AS d, endpoint, SUM(n) AS n FROM upstream_counts WHERE minute >= ? AND minute < ? GROUP BY 1, 2", (lo, hi)):
        day = _dt.datetime.fromtimestamp(r["d"] * 86400, _dt.timezone.utc).date().isoformat(); t = template(r["endpoint"])
        out.setdefault(day, {})[t] = out.get(day, {}).get(t, 0) + r["n"]
    return out

def can_fetch(ep):
    row = db.q1("SELECT next_at FROM fetch_log WHERE endpoint=?", (ep,))
    return not row or not row["next_at"] or row["next_at"] <= time.time()

# ---------------- ingest helpers ----------------
def upsert_txs(rows, source):
    now = int(time.time()); out = []
    for t in rows:
        tid = t.get("id")
        if not tid: continue
        fr = t.get("from_addr", t.get("from")) or None
        to = t.get("to_addr", t.get("to")) or None
        amt = t.get("amount") or None
        fin = t.get("final"); fin = 1 if fin in (1, True, "1") else 0
        out.append((tid, t.get("type"), fr, to, amt, t.get("memo") or None, t.get("invited_by"), t.get("epoch"),
                    int(t.get("ts") or 0), int(t.get("atts") or 0), t.get("K"), fin, now, now, source))
    db.write("""INSERT INTO txs(id,type,from_addr,to_addr,amount,memo,invited_by,epoch,ts,atts,k,final,first_seen,last_seen,source)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET atts=MAX(txs.atts, excluded.atts), final=MAX(txs.final, excluded.final),
        last_seen=excluded.last_seen, memo=COALESCE(txs.memo, excluded.memo), invited_by=COALESCE(txs.invited_by, excluded.invited_by),
        epoch=COALESCE(txs.epoch, excluded.epoch), k=COALESCE(txs.k, excluded.k)""", out, many=True)
    labs = []
    for t in rows:
        if t.get("type") == "join":
            memo = t.get("memo") or ""
            fr = t.get("from_addr", t.get("from"))
            hosted = memo.lower().startswith("hosted join")
            labs.append((fr, re.sub(r"^hosted join:?\s*", "", memo).strip(), "hosted" if hosted else "non-hosted join (likely self-custody)", "join memo", int(t.get("ts") or 0)))
    if labs:
        # A later copy of the same join without its memo (some reads omit it) must not blank a known name or custody.
        db.write("""INSERT INTO labels(addr,label,custody,source,ts) VALUES(?,?,?,?,?)
          ON CONFLICT(addr) DO UPDATE SET
            custody=CASE WHEN excluded.label != '' OR COALESCE(labels.label, '') = '' THEN excluded.custody ELSE labels.custody END,
            source=CASE WHEN excluded.label != '' OR COALESCE(labels.label, '') = '' THEN excluded.source ELSE labels.source END,
            ts=CASE WHEN excluded.label != '' OR COALESCE(labels.label, '') = '' THEN excluded.ts ELSE labels.ts END,
            label=CASE WHEN excluded.label != '' OR COALESCE(labels.label, '') = '' THEN excluded.label ELSE labels.label END""", labs, many=True)
    return len(out)

def _known(ids):
    ids = [i for i in ids if i]
    if not ids: return set()
    return {r["id"] for r in db.q(f"SELECT id FROM txs WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))}

def live_txs(get=None):
    """The newest LIVE_LIMIT txs (attestation counts and final flags of recent txs refresh from this page). minepoa's
    explorer has no since or cursor parameter going forward (since= is ignored) and sends no ETag, so incremental means:
    one page per cycle, and only when the page holds no txid we have already seen (a gap after a pause or an outage)
    older pages are read with before=<oldest ts>, stopping at the first page that reaches a seen txid, at a short page,
    or after LIVE_MAX_PAGES. Returns the number of pages read."""
    get = get or (lambda path, first: fetch(path, cond=first, endpoint="/api/explorer/txs"))
    batch = get(f"/api/explorer/txs?limit={LIVE_LIMIT}", True); pages = 1; run = set()
    while isinstance(batch, list):
        fresh = [t for t in batch if isinstance(t, dict) and t.get("id") and t["id"] not in run]
        seen = _known([t["id"] for t in fresh])
        upsert_txs(fresh, "explorer/txs"); run |= {t["id"] for t in fresh}
        if seen or not fresh or len(batch) < LIVE_LIMIT or pages >= LIVE_MAX_PAGES: break
        oldest = min((int(t.get("ts") or 0) for t in fresh), default=0)
        if not oldest: break
        time.sleep(1)
        batch = get(f"/api/explorer/txs?limit={LIVE_LIMIT}&before={oldest + 1}", False); pages += 1   # +1: same-second txs past the cut
    return pages

def job_live():
    # Each read stands alone: a slow /api/networks must not hold back the tx feed that drives the Live pill.
    # /api/status is read here once per STATUS_S (STATUS_DEGRADED_S while degraded) and shared: every feature reads
    # the stored copy (db blob "status"), never minepoa.com.
    live_txs()
    now = time.time(); slow = degraded(now)
    for path, fn, every in (("/api/status", _live_status, STATUS_DEGRADED_S if slow else STATUS_S), ("/api/networks", _live_networks, NETWORKS_S)):
        if not can_fetch(path): skip_backoff(path); continue
        if now - _last_try(path) < every - 5: continue   # 5 s slack: the job itself drifts
        try:
            d = fetch(path, timeout=20, cond=True)
            if d is not NOT_MODIFIED: fn(d)
        except Busy as e: log.warning("%s: %s", path, e)

def _live_status(st): db.add_snap("status", st); db.put_blob("status", st)

def _live_networks(nw):
    db.put_blob("networks", nw)
    for c in nw.get("chains", []):
        if c.get("chain_id") == "poa-mainnet-1":
            db.add_snap("height", {"height": c.get("height"), "checkpoint_height": c.get("checkpoint_height")})

def job_window():
    d = fetch("/api/txs", timeout=90, cond=True)
    if d is NOT_MODIFIED: return
    upsert_txs(d.get("valid", []), "txs-window")
    now = int(time.time())
    db.write("INSERT OR IGNORE INTO invalid_txs(txid,error,first_seen) VALUES(?,?,?)",
             [(x.get("txid"), x.get("error"), now) for x in d.get("invalid", []) if x.get("txid")], many=True)

def job_meta():
    for kind, path in (("anchors", "/api/anchors"), ("notices", "/api/notices"), ("ballots", "/api/ballots")):
        if not can_fetch(path): skip_backoff(path); continue
        try:
            d = fetch(path, cond=True)
            if d is NOT_MODIFIED: continue
            db.put_blob(kind, d)
            if kind == "anchors":
                db.write("INSERT OR IGNORE INTO anchors VALUES(?,?,?,?,?,?,?)",
                         [(a["height"], a["chain"], a.get("tx_hash") or a.get("tx_signature"), a.get("state_root"),
                           a.get("anchored_by"), a.get("memo"), a.get("anchored_at")) for a in d], many=True)
        except Busy as e:
            log.warning("%s: %s", path, e)
        time.sleep(1)

def job_hourly_meta():
    for kind, path in (("params", "/api/params"), ("release", "/api/release"), ("chains", "/api/chains")):
        if not can_fetch(path): skip_backoff(path); continue
        try:
            d = fetch(path, cond=True)
            if d is not NOT_MODIFIED: db.put_blob(kind, d)
        except Busy as e: log.warning("%s: %s", path, e)
        time.sleep(1)

def job_epochs(force=False):
    from . import analytics as A   # shared parsed copy; re-parsing the ~11 MB blob here every 5 min cost ~50 MB each run
    st, _ = db.get_blob("status"); have = A.epochs_count(); ep = have
    need = (st or {}).get("epochs_closed", 0)
    if not force and ep and have >= need: return False
    d = fetch("/api/epochs", timeout=180, cond=True)
    if isinstance(d, list) and d:
        db.put_blob("epochs", d); return True
    return False

def job_agents():
    d = fetch("/api/agents", timeout=120)
    now = int(time.time())
    rows = [(a["addr"], a.get("invited_by"), float(a.get("balance") or 0), a.get("balance"), a.get("ts"), a.get("joined_epoch"), now, now) for a in d]
    db.write("""INSERT INTO accounts(addr,invited_by,balance,balance_s,api_ts,api_joined_epoch,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?)
      ON CONFLICT(addr) DO UPDATE SET balance=excluded.balance, balance_s=excluded.balance_s, api_ts=excluded.api_ts,
        api_joined_epoch=excluded.api_joined_epoch, last_seen=excluded.last_seen,
        invited_by=COALESCE(accounts.invited_by, excluded.invited_by)""", rows, many=True)
    db.add_snap("accounts", {"total": len(d), "with_balance": sum(1 for a in d if float(a.get("balance") or 0) > 0)})

def job_forum():
    B = "/lableak/api"
    comms = fetch(B + "/communities", cond=True)
    if comms is NOT_MODIFIED: comms = db.get_blob("communities")[0] or []
    else: db.put_blob("communities", comms)
    known = {r["id"]: (r["comment_count"], r["edited_at"]) for r in db.q("SELECT id, comment_count, edited_at FROM forum_posts")}
    changed = []
    for c in comms:
        time.sleep(1)
        ps = fetch(f"{B}/posts?sort=new&community={c['slug']}&limit=1000", endpoint=B + "/posts", cond=True)
        if ps is NOT_MODIFIED: continue   # same list as last time: nothing new in this community
        for p in ps:
            pid = int(p["id"]); cc = int(p.get("comment_count") or 0); ed = p.get("edited_at") or None
            # The list carries body (and edited_at once a post is edited): edited bodies refresh here at no extra request.
            db.write("""INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body,edited_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT fetched FROM forum_posts WHERE id=?),0),?,?)
              ON CONFLICT(id) DO UPDATE SET score=excluded.score, title=excluded.title, deleted=excluded.deleted, pinned=excluded.pinned,
              body=COALESCE(excluded.body, forum_posts.body), edited_at=COALESCE(excluded.edited_at, forum_posts.edited_at)""",
                     (pid, p.get("community"), p.get("title"), p.get("author"), p.get("author_public_id"), p.get("created_at"),
                      int(p.get("score") or 0), known.get(pid, (-1, None))[0], int(p.get("deleted") or 0), int(p.get("pinned") or 0), pid,
                      p.get("body"), ed))
            k = known.get(pid)
            if not k or k[0] != cc or (ed and ed != k[1]): changed.append(pid)   # new comments, or an edit (its comments may have changed too)
    broke = False
    for pid in changed[:120]:   # cap detail calls per run; the rest catch up next run
        time.sleep(0.8)
        try: ingest_post(fetch(f"{B}/posts/{pid}", endpoint=B + "/posts/:id"))
        except Busy as e: log.warning("forum post %s: %s", pid, e); broke = True; break
    if broke or len(changed) > 120:   # a backlog is only visible in the full lists: next run reads them without If-None-Match
        for k in [k for k in list(_etags) if k.startswith(B + "/posts?")]: _etags.pop(k, None)

def ingest_post(p):
    pid = int(p["id"]); cs = p.get("comments", [])
    db.write("""INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body,edited_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET comment_count=excluded.comment_count, score=excluded.score,
      fetched=excluded.fetched, body=excluded.body, title=excluded.title, edited_at=COALESCE(excluded.edited_at, forum_posts.edited_at)""",
             (pid, p.get("community"), p.get("title"), p.get("author"), p.get("author_public_id"), p.get("created_at"),
              int(p.get("score") or 0), len(cs), int(p.get("deleted") or 0), int(p.get("pinned") or 0), int(time.time()), p.get("body"), p.get("edited_at") or None))
    db.write("INSERT OR REPLACE INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body,edited_at) VALUES(?,?,?,?,?,?,?,?,?)",
             [(int(c["id"]), pid, (int(c["parent_id"]) if c.get("parent_id") not in (None, "None", "") else None), c.get("author"),
               c.get("author_public_id"), c.get("created_at"), int(c.get("score") or 0), c.get("body"), c.get("edited_at") or None) for c in cs], many=True)
    from . import kin as _KN
    if _KN.KIN_POST_ID is not None and pid == _KN.KIN_POST_ID: _KN.sync()   # kin claims: rebuilt from this post's archived comments, no extra read

# ---------------- swaps (on-ledger escrow offers, fills, cancels) ----------------
# Swap offers, swap tx details and the SOL/ETH USD reference: poascan/swap/indexer.py (its JOBS are spliced in below).

# ---------------- answer-text sampling (Sybil signals) ----------------
SLOT = re.compile(r"\b(the words|words)\s+[a-z]+,\s*[a-z]+,?\s+(and\s+)?[a-z]+\b|\bwith\s+[a-z]+,\s*[a-z]+\s+and\s+[a-z]+\b|"
                  r"\b(of|evaluate|think of)\s+[a-z]+,\s*[a-z]+\s+and\s+[a-z]+\b|\band\s+[a-z]+,\s*[a-z]+,\s*[a-z]+\s+(remind|mark|capture)", re.I)
ECHO = re.compile(r"120-600 chars|plain prose|^need (original|write)", re.I)

def classify(text):
    t = text or ""
    words = re.findall(r"[a-z]+", t.lower())
    return dict(lang=lang(t), len=len(t), slot_template=1 if (len(t) < 300 and SLOT.search(t)) else 0,
                prompt_echo=1 if ECHO.search(t) else 0, prefix4=" ".join(words[:4]))

STOP = {"en": "the and of to is a in that for each with", "es": "el la de que y los las una por para", "fr": "le la les de et des une est pour que",
        "de": "der die und das ist nicht ein eine zu mit", "pt": "o a de que e os uma para com não", "it": "il la di che e per una con non sono"}
STOP = {k: set(v.split()) for k, v in STOP.items()}
def lang(t):
    if re.search(r"[\u3040-\u30ff]", t): return "ja"
    if re.search(r"[\uac00-\ud7af]", t): return "ko"
    if re.search(r"[\u4e00-\u9fff]", t): return "zh"
    if re.search(r"[\u0400-\u04ff]", t): return "ru"
    if re.search(r"[\u0600-\u06ff]", t): return "ar"
    w = re.findall(r"[a-zà-ÿ]+", t.lower())
    if not w: return "unknown"
    sc = {k: sum(1 for x in w if x in v) for k, v in STOP.items()}
    best = max(sc, key=sc.get)
    return best if sc[best] >= 2 else "unknown"

# On-demand upstream reads made while serving a visitor (tx detail, address balance) on the HTML pages, the API and MCP.
# They must never pile up behind a slow or down upstream, and visitors must never be able to turn POAScan into a steady
# minepoa.com caller (SC-003). In order, a visitor read is refused before any request when:
#   * the id does not match the valid format (64 hex for a tx, a base58 poa1 address),
#   * the id failed recently (negative cache: NEG_TTL s for a 404 or an answer without an id, NEG_ERR_TTL s for other
#     errors; bounded to NEG_MAX ids, oldest dropped first),
#   * the on-demand endpoint key is backing off (its own key: a visitor miss never pauses scheduled ingest),
#   * the client's budget is spent (CLIENT_RATE per s, burst CLIENT_BURST, per Fly-Client-IP, in memory only),
#   * the global budget is spent (GLOBAL_RATE per s, burst GLOBAL_BURST, all visitors together),
#   * ONDEMAND_MAX reads are already in flight.
# Scheduled jobs (swap fills, wallet links, answer sample) read tx details through their own endpoint keys with their own
# backoff and never spend the visitor budget. Mirror reads of /api/v1/swaps*, /agents/<a>/addresses and /epochs are
# answered from the local archive and never reach this path; /address/<a> balance reads are cached 60 s per address
# and fall back to the stored balance when the budget is spent.
ONDEMAND_MAX = int(os.environ.get("POASCAN_ONDEMAND_MAX", "3"))
ONDEMAND_TIMEOUT = float(os.environ.get("POASCAN_ONDEMAND_TIMEOUT", "8"))
GLOBAL_RATE = float(os.environ.get("POASCAN_UPSTREAM_RATE", "0.25")); GLOBAL_BURST = int(os.environ.get("POASCAN_UPSTREAM_BURST", "20"))
CLIENT_RATE = float(os.environ.get("POASCAN_UPSTREAM_CLIENT_RATE", "0.2")); CLIENT_BURST = int(os.environ.get("POASCAN_UPSTREAM_CLIENT_BURST", "20"))
NEG_TTL = _ei("POASCAN_NEG_TTL", 600, 60); NEG_ERR_TTL = _ei("POASCAN_NEG_ERR_TTL", 300, 30); NEG_MAX = 5000
NEG_BG_TTL = _ei("POASCAN_NEG_BG_TTL", 6 * 3600, 600)   # a scheduled job's unknown tx id (e.g. rolled back by the upgrade)
# Per-endpoint on-demand budgets inside the global one, and the shortest gap between two reads of the same address
# (the page serves its cached copy meanwhile). With these the visitor-driven ceiling is GLOBAL_RATE*3600 per hour.
ADDR_RATE = _env_num("POASCAN_UPSTREAM_ADDR_RATE", 0.05, 0.001); ADDR_BURST = _ei("POASCAN_UPSTREAM_ADDR_BURST", 10, 1)
TXOD_RATE = _env_num("POASCAN_UPSTREAM_TX_RATE", 0.1, 0.001); TXOD_BURST = _ei("POASCAN_UPSTREAM_TX_BURST", 20, 1)
ADDR_MIN_S = _ei("POASCAN_ADDR_MIN_S", 300, 30)
TX_REFRESH_S = _ei("POASCAN_TX_REFRESH_S", 120, 30)   # a stored non-final tx is read again at most this often
TX_EP, ADDR_EP = "/api/explorer/tx/:id (on demand)", "/api/explorer/address/:addr"   # visitor keys
BG_TX_EP = "/api/explorer/tx/:id"            # scheduled answer sample and wallet links (JOBS)
SWAP_TX_EP = "/api/explorer/tx/:id (swaps)"  # swap fill ingest, never paused by a visitor or by the sample
TX_ID = re.compile(r"^[0-9a-f]{64}$")
ADDR_ID = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")
_ondemand = threading.BoundedSemaphore(ONDEMAND_MAX)
_tx_lock = threading.Lock(); _tx_inflight = {}
CLIENT = threading.local()   # server.py sets CLIENT.ip (Fly-Client-IP, else the peer) per request; jobs have none

class Bucket:
    """Token bucket; keyed buckets idle for 10 min are dropped (memory stays bounded)."""
    def __init__(self, rate, burst):
        self.rate, self.burst, self.b, self.lock = rate, burst, {}, threading.Lock()
    def take(self, key=""):
        now = time.monotonic()
        with self.lock:
            if len(self.b) > 5000: self.b = {k: v for k, v in self.b.items() if now - v[1] < 600}
            tok, last = self.b.get(key, (self.burst, now)); tok = min(self.burst, tok + (now - last) * self.rate)
            if tok < 1: self.b[key] = (tok, now); return False, int((1 - tok) / self.rate) + 1
            self.b[key] = (tok - 1, now); return True, 0
GLOBAL_BUDGET = Bucket(GLOBAL_RATE, GLOBAL_BURST)
CLIENT_BUDGET = Bucket(CLIENT_RATE, CLIENT_BURST)
EP_BUDGET = {ADDR_EP: Bucket(ADDR_RATE, ADDR_BURST), TX_EP: Bucket(TXOD_RATE, TXOD_BURST)}
_recent = collections.OrderedDict(); _recent_lock = threading.Lock()   # endpoint+key -> last on-demand read (bounded)
def _recent_hit(k, gap):
    now = time.time()
    with _recent_lock:
        t = _recent.get(k)
        if t and now - t < gap: return int(gap - (now - t)) + 1
        _recent[k] = now; _recent.move_to_end(k)
        while len(_recent) > 5000: _recent.popitem(last=False)
    return 0

_neg = collections.OrderedDict(); _neg_lock = threading.Lock()   # id -> (until, Missing or Busy)
def neg_get(key):
    with _neg_lock:
        hit = _neg.get(key)
        if hit and hit[0] > time.time(): return hit[1]
        if hit: _neg.pop(key, None)
    return None
def neg_put(key, missing, ttl=None):
    with _neg_lock:
        _neg[key] = (time.time() + (ttl or (NEG_TTL if missing else NEG_ERR_TTL)), Missing if missing else Busy); _neg.move_to_end(key)
        while len(_neg) > NEG_MAX: _neg.popitem(last=False)
def neg_size(): return len(_neg)

def fetch_ondemand(path, endpoint, key):
    """One visitor-triggered read (see the block comment above). key is the tx id or address."""
    if not (TX_ID.match(key) if endpoint == TX_EP else ADDR_ID.match(key)): raise Missing("not a valid id")
    k = neg_get(endpoint + key)
    if k: raise k("not found (cached)" if k is Missing else "upstream failed recently (cached)")
    if not can_fetch(endpoint): deny(endpoint, "backoff"); raise Busy("upstream backing off")
    if endpoint == ADDR_EP:
        w = _recent_hit(endpoint + key, ADDR_MIN_S)
        if w: deny(endpoint, "visitor_cap:recent"); raise Limited("read recently; the cached copy is current enough", w)
    ip = getattr(CLIENT, "ip", None)
    if ip:
        ok, wait = CLIENT_BUDGET.take(ip)
        if not ok: deny(endpoint, "visitor_cap:client"); raise Limited("too many lookups of new ids; slow down", wait)
    if endpoint in EP_BUDGET:
        ok, wait = EP_BUDGET[endpoint].take()
        if not ok: deny(endpoint, "visitor_cap:endpoint"); raise Limited("upstream budget for this lookup spent; try again shortly", wait)
    ok, wait = GLOBAL_BUDGET.take()
    if not ok: deny(endpoint, "visitor_cap:global"); raise Limited("upstream budget spent; try again shortly", wait)
    if not _ondemand.acquire(timeout=0.5): deny(endpoint, "visitor_cap:inflight"); raise Busy("upstream busy")
    try:
        d = fetch(path, timeout=ONDEMAND_TIMEOUT, endpoint=endpoint, soft=True)
        if endpoint == TX_EP and not (isinstance(d, dict) and d.get("id")): raise Missing("not found")
        return d
    except Missing: neg_put(endpoint + key, True); raise
    except Limited: raise
    except Busy: neg_put(endpoint + key, False); raise
    finally: _ondemand.release()

def _bg_fetch_tx(tid, endpoint):
    """A scheduled job's tx detail read: its own endpoint key and backoff, no visitor budget; unknown ids are negative cached."""
    if not TX_ID.match(tid): raise Missing("not a valid id")
    if neg_get(endpoint + tid): raise Missing("not found (cached)")
    if not can_fetch(endpoint): skip_backoff(endpoint); raise Busy("backing off")
    try:
        d = fetch(f"/api/explorer/tx/{tid}", timeout=20, endpoint=endpoint, soft=True)
        if not (isinstance(d, dict) and d.get("id")): raise Missing("not found")
    except Missing: neg_put(endpoint + tid, True, NEG_BG_TTL); raise
    return d

def get_tx_detail(tid, allow_fetch=True, bg=None):
    """Stored detail when final (or read in the last 120 s), else one read. bg=None is a visitor read (fetch_ondemand);
    bg=<endpoint key> is a scheduled job's read (BG_TX_EP or SWAP_TX_EP). Raises Missing, Limited or Busy when nothing is stored."""
    r = db.q1("SELECT json, fetched, final FROM tx_detail WHERE id=?", (tid,))
    if r and (r["final"] or time.time() - r["fetched"] < TX_REFRESH_S):
        return json.loads(r["json"])
    if not allow_fetch:
        return json.loads(r["json"]) if r else None
    with _tx_lock:
        ev = _tx_inflight.get(tid); mine = ev is None
        if mine: ev = _tx_inflight[tid] = threading.Event()
    if not mine:                        # another request is fetching this tx: wait briefly, then use what is stored
        ev.wait(ONDEMAND_TIMEOUT + 2)
        return get_tx_detail(tid, allow_fetch=False)
    try:
        d = _bg_fetch_tx(tid, bg) if bg else fetch_ondemand(f"/api/explorer/tx/{tid}", TX_EP, tid)
    except Busy:
        if r: return json.loads(r["json"])
        raise
    finally:
        with _tx_lock: _tx_inflight.pop(tid, None)
        ev.set()
    db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,?)", (tid, json.dumps(d), int(time.time()), 1 if d.get("final") else 0))
    upsert_txs([d], "explorer/tx")
    return d

def job_sample(n=20):
    rows = db.q("""SELECT id, from_addr, ts, epoch FROM txs WHERE type='challenge' AND id NOT IN (SELECT id FROM answers)
                   ORDER BY ts DESC LIMIT 400""")
    random.shuffle(rows)
    for r in rows[:n]:
        time.sleep(1.0)
        try: d = get_tx_detail(r["id"], bg=BG_TX_EP)
        except Missing: continue
        except Busy: break
        body = (d or {}).get("body") or {}
        c = classify(body.get("answer", ""))
        db.write("INSERT OR REPLACE INTO answers VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (r["id"], r["from_addr"], body.get("epoch", r["epoch"]), r["ts"], c["len"], c["slot_template"], c["prompt_echo"], c["prefix4"],
                  int(time.time()), body.get("answer", ""), c["lang"]))

def job_links(n=10):
    """Each chains-update tx's body (the linked chain addresses), read once through the same rate-limited tx read the
    explorer uses, so verified_at can come from the ledger. Already-stored final txs are never read again."""
    rows = db.q("""SELECT t.id FROM txs t LEFT JOIN tx_detail d ON d.id = t.id WHERE t.type = 'chains-update'
                   AND (d.id IS NULL OR (d.final = 0 AND t.final = 1)) ORDER BY t.ts DESC LIMIT ?""", (n,))
    for r in rows:
        try: get_tx_detail(r["id"], bg=BG_TX_EP)
        except Missing: pass
        except Busy: break
        time.sleep(1.0)

# ---------------- seeding from earlier public snapshots (optional) ----------------
def seed(seed_dir):
    """Import previously captured public snapshots (same endpoints) so a fresh box has history."""
    if not seed_dir or not os.path.isdir(seed_dir): return
    if db.q1("SELECT 1 AS x FROM blobs WHERE kind='seeded'"): return
    log.info("seeding from %s", seed_dir)
    def J(p):
        try: return json.load(open(p))
        except Exception: return None
    raw = os.path.join(seed_dir, "dashboard", "raw")
    e = J(os.path.join(raw, "epochs.json"))
    if isinstance(e, list) and e: db.put_blob("epochs", e)
    for kind in ("params", "release", "notices", "ballots", "chains", "networks"):
        d = J(os.path.join(raw, kind + ".json"))
        if d is not None: db.put_blob(kind, d)
    a = J(os.path.join(raw, "anchors.json"))
    if a:
        db.put_blob("anchors", a)
        db.write("INSERT OR IGNORE INTO anchors VALUES(?,?,?,?,?,?,?)",
                 [(x["height"], x["chain"], x.get("tx_hash") or x.get("tx_signature"), x.get("state_root"), x.get("anchored_by"), x.get("memo"), x.get("anchored_at")) for x in a], many=True)
    # status history points (mainnet only; all captured from unprefixed /api/status after launch)
    for p in ["st.json", "status_m2.json", "status_now.json", "dashboard/raw/status.json", "dashboard/raw/status_1141.json"]:
        d = J(os.path.join(seed_dir, p))
        if d and d.get("as_of"):
            import datetime as dt
            ts = int(dt.datetime.fromisoformat(d["as_of"].replace("Z", "+00:00")).timestamp())
            db.add_snap("status", dict(d, seeded=True), ts)
    t = J(os.path.join(raw, "txs.json"))
    if t: upsert_txs(t.get("valid", []), "seed")
    # mainnet address histories captured Oct 19 evening (explorer/address responses)
    for p in ["research/explorer.json", "research/explorer2.json"]:
        d = J(os.path.join(seed_dir, p)) or {}
        for v in d.values():
            if isinstance(v, dict): upsert_txs(v.get("txs", []), "seed")
    ag = J(os.path.join(raw, "agents.json"))
    if ag:
        now = int(time.time())
        db.write("INSERT OR IGNORE INTO accounts VALUES(?,?,?,?,?,?,?,?)",
                 [(x["addr"], x.get("invited_by"), float(x.get("balance") or 0), x.get("balance"), x.get("ts"), x.get("joined_epoch"), now, now) for x in ag], many=True)
    comms = J(os.path.join(raw, "forum", "communities.json"))
    if comms: db.put_blob("communities", comms)
    for f in glob.glob(os.path.join(raw, "forum", "posts", "*.json")):
        d = J(f)
        if d: ingest_post(d)
    s = J(os.path.join(raw, "chall", "sample80.json")) or {}
    for tid, d in s.items():
        if "body" in d:
            db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,?)", (tid, json.dumps(d), int(time.time()), 1 if d.get("final") else 0))
            c = classify(d["body"].get("answer", ""))
            db.write("INSERT OR REPLACE INTO answers VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (tid, d.get("from_addr"), d["body"].get("epoch"), d.get("ts"), c["len"], c["slot_template"], c["prompt_echo"], c["prefix4"],
                      int(time.time()), d["body"].get("answer", ""), c["lang"]))
    import csv
    cp = os.path.join(os.path.dirname(__file__), "..", "data", "census.csv")
    if os.path.exists(cp):
        rows = [r for r in csv.DictReader(open(cp)) if r["addr"].startswith("poa1") and r["label"]]
        db.write("INSERT OR IGNORE INTO labels VALUES(?,?,?,?,?)", [(r["addr"], r["label"], None, "census.csv registration label (Oct 19)", 0) for r in rows], many=True)
    db.put_blob("seeded", {"from": seed_dir})

# ---------------- scheduler ----------------
# How often each upstream source is read when healthy (for the /status freshness table).
EVERY = {"/api/explorer/txs": LIVE_S, "/api/status": STATUS_S, "/api/networks": NETWORKS_S, "/api/swaps": SWAPS_S, "/api/txs": 600,
         "/api/anchors": META_S, "/api/notices": META_S, "/api/ballots": META_S, "/api/epochs": 300, "/api/agents": 900, "/api/params": 3600,
         "/api/release": 3600, "/api/chains": 3600, "/lableak/api/communities": FORUM_S, "/lableak/api/posts": FORUM_S}

_SWAP_JOBS = __import__("poascan.swap.indexer", fromlist=["x"]).JOBS   # the swap module's jobs, at their old slots
JOBS = [  # name, fn, interval seconds, endpoint key used for backoff
    ("live", job_live, live_every, "/api/explorer/txs"),   # LIVE_S, or LIVE_DEGRADED_S while upstream is degraded
    _SWAP_JOBS[0][:2] + (SWAPS_S,) + _SWAP_JOBS[0][3:],   # swaps: open-offer book, SWAPS_S (60 s)
    ("probe", job_probe, 600, None),
    _SWAP_JOBS[1],   # fx: SOL/ETH USD reference, 15 min
    ("window", job_window, 600, "/api/txs"),
    ("meta", job_meta, META_S, None),
    ("epochs", job_epochs, 300, "/api/epochs"),
    ("agents", job_agents, 900, "/api/agents"),
    ("hourly", job_hourly_meta, 3600, None),
    ("forum", job_forum, FORUM_S, "/lableak/api/communities"),
    ("sample", job_sample, 1800, "/api/explorer/tx/:id"),
    ("links", job_links, 600, "/api/explorer/tx/:id"),   # chains-update tx bodies, once each
    ("signed", lambda: __import__("poascan.signed", fromlist=["x"]).job(), 600, "/api/explorer/tx/:id"),   # G0 notice and release txs, each read once (at most 2 per run), verified offline
    ("census", lambda: __import__("poascan.agents", fromlist=["x"]).census_job(), 86400, None),
    ("pulse", lambda: __import__("poascan.pulse", fromlist=["x"]).job(), 300, None),   # private live prober, off the node; no-op without POASCAN_PULSE_SRC
    ("halts", lambda: __import__("poascan.halts", fromlist=["x"]).job(), 600, None),   # private tracker, off the node; no-op without POASCAN_HALT_SRC
    ("hosted", lambda: __import__("poascan.hosted", fromlist=["x"]).job(), 900, None),
    ("milestones", lambda: __import__("poascan.milestones", fromlist=["x"]).job(), 300, None),   # upgrade milestones from live state; no upstream call   # one keyless GET per hosted route, only while maintenance is on
]

# Jobs that drive the Live pill and swap freshness run in their own thread, so a slow forum, epochs or /api/txs read
# never holds them back (SC-025). The swap read keeps a fixed phase SWAP_PHASE_S after the live read plus a little
# jitter each run, so the two 60 s reads (and 60 s mirror polls of the cached swap API) do not line up (SC-004).
FAST = ("live", "swaps")
SWAP_PHASE_S, SWAP_JITTER_S = 30, 5

def _phase(name, every, now):
    """Initial last-run time: the swap read starts SWAP_PHASE_S after the live read."""
    return now - every + SWAP_PHASE_S if name == "swaps" else 0

def _ran(name):
    """When a job last ran (its job: blob), so a restart or deploy resumes the schedule instead of re-reading everything."""
    try: return int((db.get_blob("job:" + name)[0] or {}).get("ran") or 0)
    except Exception: return 0

JOB_RETRY_S = _ei("POASCAN_JOB_RETRY_S", 300, 30)   # 1.26.82: failed hourly reads waited an hour (chains, params, release 2 h old)

def run_forever(stop=None, jobs=None):
    jobs = JOBS if jobs is None else jobs
    t0 = time.time()
    last = {name: max(_phase(name, every() if callable(every) else every, t0), min(_ran(name), t0)) for name, fn, every, ep in jobs}
    while not (stop and stop.is_set()):
        now = time.time()
        try: flush_counts()
        except Exception as e: log.warning("upstream counter flush: %s", type(e).__name__)
        for name, fn, every, ep in jobs:
            if callable(every):
                try: every = every()
                except Exception: every = 60
            if now - last.get(name, 0) < every: continue
            if ep and not can_fetch(ep): skip_backoff(ep); continue
            last[name] = now + (random.uniform(-SWAP_JITTER_S, SWAP_JITTER_S) if name == "swaps" else 0)
            ok = False
            try:
                fn(); ok = True
            except Busy as e:
                log.warning("job %s busy: %s", name, e)
            except Exception as e:
                _etags.clear()   # the job may not have stored what it read: the next reads are plain GETs
                log.exception("job %s failed: %s", name, e)
            if ok: db.put_blob("job:" + name, {"ran": int(time.time())})
            elif every > JOB_RETRY_S: last[name] = now - every + JOB_RETRY_S   # a failed run retries soon (endpoint backoff still applies), not a full interval later
            time.sleep(2)  # spacing between jobs
        time.sleep(5 if len(jobs) > 2 else 1)

def _purge_keys():
    from . import keysafe as _KS
    try:
        n = _KS.purge_db(db)
        log.info("key scrub: %d stored rows redacted", n)
    except Exception as e:
        log.warning("key scrub failed: %s", type(e).__name__)

def repair_join_labels():
    """Idempotent, local data only: refill join labels that a memo-less copy of the join blanked before 1.26.77,
    from the archived join tx memo (txs.memo keeps the first memo seen). Rows with a name are left alone. No upstream read."""
    rows = db.q("""SELECT t.from_addr AS addr, t.memo, t.ts FROM txs t LEFT JOIN labels l ON l.addr = t.from_addr
                   WHERE t.type='join' AND t.from_addr IS NOT NULL AND COALESCE(t.memo, '') != '' AND COALESCE(l.label, '') = ''
                   ORDER BY t.ts""")
    fix = {}
    for r in rows:   # newest join memo per address wins
        memo = r["memo"]; hosted = memo.lower().startswith("hosted join")
        nm = re.sub(r"^hosted join:?\s*", "", memo, flags=re.I).strip()
        if nm: fix[r["addr"]] = (r["addr"], nm, "hosted" if hosted else "non-hosted join (likely self-custody)", "join memo", int(r["ts"] or 0))
    if fix: db.write("INSERT OR REPLACE INTO labels VALUES(?,?,?,?,?)", list(fix.values()), many=True)
    return len(fix)

def start(seed_dir=None):
    db.init()
    try: __import__("poascan.kin", fromlist=["x"]).sync()   # kin claims from the archive (clears them when no claim post is set)
    except Exception as e: log.warning("kin sync: %s", type(e).__name__)
    try: log.info("join labels repaired: %d", repair_join_labels())
    except Exception as e: log.warning("join label repair: %s", type(e).__name__)
    threading.Thread(target=_purge_keys, daemon=True, name="keyscrub").start()
    try: seed(seed_dir)
    except Exception as e: log.exception("seed failed: %s", e)
    fast = [j for j in JOBS if j[0] in FAST]; slow = [j for j in JOBS if j[0] not in FAST]
    from . import swapflag as _SF; _SF.start()   # the shared swap flag, read only, its own thread (never on the minepoa budget)
    threading.Thread(target=run_forever, kwargs=dict(jobs=fast), daemon=True, name="indexer-fast").start()
    th = threading.Thread(target=run_forever, kwargs=dict(jobs=slow), daemon=True, name="indexer"); th.start()
    return th
