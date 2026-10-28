"""Fast index: a public, read-only indexed cache of poa-mainnet-1, read in front of minepoa.com, never in place of it.

Off unless FAST_INDEX_URL is set (a Fly secret in production, an env var or untracked config locally). The URL is never
logged, rendered, returned by an API or written to the database. Nothing is ever sent to it but plain GETs with no key,
token or cookie. Every read is server side (no browser calls), counted, and held to a sliding per minute cap.

What it feeds, each with the existing minepoa.com path as the fallback:
  * sync(): the cursor paged tx list into POAScan's own txs table (1000 rows a page, a few pages a run while backfilling,
    one page a run after), plus the overview (freshness), anchors and external address links on a slower clock.
  * tx_detail(): a single tx with its signed body for /tx and the tx API. Only a final row is used as is; a pending one is a
    fallback for when minepoa.com fails. A final body is stored in tx_detail, so it is never read again from anywhere.
  * bodies(): grade seal bodies, newest first, for the seal to answer link (body.assignment). Only the link is stored,
    never the sealed blob. Seal counts per answer come from these links.
  * address() and resolve(): address fallback and external wallet to poa1 resolution for search.
Segment logic is config driven (segments.json): rows are kept only for the segment whose chain_id the index reports."""
import collections, gzip, json, logging, os, re, threading, time, urllib.error, urllib.parse, urllib.request
from . import db, segments as _SG

log = logging.getLogger("fastindex")

def _env_i(k, d, lo, hi):
    try: v = int(os.environ.get(k, d))
    except (TypeError, ValueError): v = d
    return max(lo, min(hi, v))

def _url():
    u = (os.environ.get("FAST_INDEX_URL") or "").strip().rstrip("/")
    if not u:   # local development: an untracked file outside the repo
        p = os.environ.get("FAST_INDEX_URL_FILE") or ""
        if p and os.path.isfile(p):
            try: u = open(p, encoding="utf-8").read().strip().rstrip("/")
            except OSError: u = ""
    return u if u.startswith(("https://", "http://127.0.0.1", "http://localhost")) else ""

URL = _url()
UA = "POAScan/1.0 (+https://poascan.io; read-only)"
SYNC_S = _env_i("FAST_INDEX_SYNC_S", 300, 120, 3600)          # tx list, overview
PAGES = _env_i("FAST_INDEX_PAGES", 3, 1, 10)                   # tx pages a run while backfilling (one page a run once caught up)
LIMIT = _env_i("FAST_INDEX_LIMIT", 1000, 50, 1000)
PAGE_GAP_S = _env_i("FAST_INDEX_PAGE_GAP_S", 4, 1, 60)
META_S = _env_i("FAST_INDEX_META_S", 1800, 600, 86400)        # anchors and external links
BODIES_PER_MIN = _env_i("FAST_INDEX_BODIES_PER_MIN", 10, 0, 30)   # seal bodies a minute (0 turns them off)
VISITOR_PER_MIN = _env_i("FAST_INDEX_VISITOR_PER_MIN", 20, 0, 40)  # page and API lookups a minute, all visitors together
PER_MIN = _env_i("FAST_INDEX_PER_MIN", 30, 5, 60)              # hard cap on every read a minute (the index allows 120 per IP)
TIMEOUT = _env_i("FAST_INDEX_TIMEOUT_S", 6, 2, 20)
LAG_DEGRADED_S = _env_i("FAST_INDEX_LAG_DEGRADED_S", 1800, 600, 86400)   # behind by more than this: Degraded (Partial dot)
DOWN_S = _env_i("FAST_INDEX_DOWN_S", 1800, 600, 86400)       # no good read for this long, or lag above 4x this: Down
NEG_S = 180                                                    # an id the index does not have yet is not asked again for this long
BACKOFF_MAX_S = 900
MAX_BODY = 8 * 1024 * 1024
TXID = re.compile(r"^[0-9a-f]{64}$")
ADDR = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")
EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
HEXONLY = re.compile(r"^[0-9a-fA-F]+$")   # a tx id prefix, never a wallet
SOURCE = "fast-index"
PUBLIC_NAME = "fast index"

class Unavailable(Exception):
    """Off, over budget, backing off or failed: the caller takes the minepoa.com path."""

def enabled(): return bool(URL) and os.environ.get("FAST_INDEX_OFF", "") not in ("1", "true")

def is_external(q):
    """An EVM (0x + 40 hex) or Solana style (base58, 32 to 44 chars) address that is not a poa1 address."""
    q = (q or "").strip()
    return bool(EVM.match(q) or (B58.match(q) and not q.startswith("poa1") and not HEXONLY.match(q)))

# ---------------- requests: budget, backoff, counts ----------------
_lock = threading.Lock()
_sent = collections.deque(maxlen=20000)      # (ts, kind) of every request sent
_win = collections.deque(maxlen=200)         # send times within the last minute, all kinds
_vwin = collections.deque(maxlen=200)        # visitor lookups within the last minute
_hold = [0.0]; _fails = [0]; _last = dict(ok=None, err=None, err_kind=None, ms=None)
_neg = collections.OrderedDict()

def _take(kind, visitor, now=None):
    now = now or time.time()
    with _lock:
        if _hold[0] > now: return False
        while _win and now - _win[0] >= 60: _win.popleft()
        while _vwin and now - _vwin[0] >= 60: _vwin.popleft()
        if len(_win) >= PER_MIN: return False
        if visitor and len(_vwin) >= VISITOR_PER_MIN: return False
        _win.append(now); _sent.append((now, kind))
        if visitor: _vwin.append(now)
    return True

def _fail(kind, retry=None):
    with _lock:
        _fails[0] += 1; _last["err"] = int(time.time()); _last["err_kind"] = kind
        wait = min(BACKOFF_MAX_S, 30 * (2 ** min(_fails[0] - 1, 6)))
        if retry: wait = max(wait, min(6 * 3600, retry))
        _hold[0] = max(_hold[0], time.time() + wait) if (_fails[0] >= 3 or retry) else _hold[0]

def _ok(ms):
    with _lock: _fails[0] = 0; _last["ok"] = int(time.time()); _last["ms"] = ms

def _get(path, kind, visitor=False, timeout=None):
    """GET <index>/api/<path>, parsed JSON. Raises Unavailable on anything short of a good answer."""
    if not enabled(): raise Unavailable("off")
    if not _take(kind, visitor): raise Unavailable("budget")
    req = urllib.request.Request(URL + "/api/" + path, headers={"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as r:
            raw = r.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY: raise ValueError("too large")
            if (r.headers.get("Content-Encoding") or "").lower() == "gzip": raw = gzip.decompress(raw)
            d = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        ra = e.headers.get("Retry-After") if e.headers else None
        retry = int(ra) if ra and str(ra).isdigit() else (60 if e.code == 429 else None)
        _fail(f"http_{e.code}", retry if e.code in (429, 503) else None)
        log.warning("fast index %s: HTTP %s", kind, e.code); raise Unavailable(f"HTTP {e.code}")
    except Exception as e:
        _fail(type(e).__name__); log.warning("fast index %s: %s", kind, type(e).__name__); raise Unavailable(type(e).__name__)
    if not isinstance(d, dict) or d.get("ok") is False or not isinstance(d.get("rows", []), list):
        _fail("shape"); raise Unavailable("unexpected answer")
    _ok(int((time.time() - t0) * 1000))
    return d

def requests_report(now=None):
    """Reads sent to the index per kind: counts over the last 15 and 60 minutes and the per minute rate."""
    now = now or time.time(); out = {}
    with _lock: rows = list(_sent)
    for mins in (15, 60):
        c = collections.Counter(k for t, k in rows if now - t < mins * 60)
        out[f"last_{mins}m"] = dict(total=sum(c.values()), per_min=round(sum(c.values()) / mins, 2), by_kind=dict(sorted(c.items())))
    out["caps_per_min"] = dict(all=PER_MIN, visitor=VISITOR_PER_MIN, seal_bodies=BODIES_PER_MIN)
    return out

def _neg_hit(k):
    with _lock:
        t = _neg.get(k)
        if t and t > time.time(): return True
        if t: _neg.pop(k, None)
    return False

def _neg_put(k):
    with _lock:
        _neg[k] = time.time() + NEG_S; _neg.move_to_end(k)
        while len(_neg) > 5000: _neg.popitem(last=False)

# ---------------- storage ----------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS fx_anchors(height INTEGER NOT NULL, chain TEXT NOT NULL, tx TEXT, state_root TEXT, ts INTEGER, segment INTEGER NOT NULL,
  PRIMARY KEY(segment, height, chain));
CREATE TABLE IF NOT EXISTS fx_ext(address TEXT PRIMARY KEY, network TEXT, poa TEXT, verified INTEGER, seen INTEGER);
CREATE INDEX IF NOT EXISTS fx_ext_poa ON fx_ext(poa);
CREATE TABLE IF NOT EXISTS seal_links(seal TEXT PRIMARY KEY, answer TEXT NOT NULL, ts INTEGER, segment INTEGER);
CREATE INDEX IF NOT EXISTS seal_links_answer ON seal_links(answer);
"""
_inited = [False]
def init():
    if _inited[0]: return
    with db._wlock: db.conn().executescript(SCHEMA); db.conn().commit()
    _inited[0] = True

def segment_for(chain):
    """The configured segment whose chain_id the index reports (the newest such), or None."""
    m = [s["n"] for s in _SG.SEGMENTS if s.get("chain_id") == chain]
    return max(m) if m else None

def _seg_bounds(n):
    s = _SG.BY_N.get(n) or {}
    return s.get("start_ts"), s.get("end_ts")

def _state():
    return db.get_blob("fx:state")[0] or {}

def _put_state(st): db.put_blob("fx:state", st)

def link_seal(d):
    """A grade seal body names the answer it grades (body.assignment): store that link, never the sealed blob."""
    if not isinstance(d, dict) or d.get("type") != "grade-sealed": return False
    b = d.get("body") or {}; a = b.get("assignment"); sid = d.get("id")
    if not (isinstance(a, str) and TXID.match(a) and isinstance(sid, str) and TXID.match(sid)): return False
    init(); ts = int(d.get("ts") or b.get("ts") or 0)
    db.write("INSERT OR IGNORE INTO seal_links(seal, answer, ts, segment) VALUES(?,?,?,?)", (sid, a, ts, _SG.of_ts(ts)))
    return True

def backfill_links_from_details():
    """Once: seal links from grade seal bodies POAScan already stored (tx_detail). Local only, no read."""
    init()
    if (db.get_blob("fx:links_seeded")[0] or {}).get("done"): return 0
    rows = db.q("""SELECT d.id, json_extract(d.json, '$.body.assignment') AS a, COALESCE(t.ts, json_extract(d.json, '$.ts')) AS ts
                   FROM tx_detail d LEFT JOIN txs t ON t.id = d.id
                   WHERE json_extract(d.json, '$.type') = 'grade-sealed' AND json_extract(d.json, '$.body.assignment') IS NOT NULL""")
    ok = [(r["id"], r["a"], int(r["ts"] or 0), _SG.of_ts(r["ts"])) for r in rows if TXID.match(str(r["a"] or "")) and TXID.match(str(r["id"] or ""))]
    if ok: db.write("INSERT OR IGNORE INTO seal_links(seal, answer, ts, segment) VALUES(?,?,?,?)", ok, many=True)
    db.put_blob("fx:links_seeded", {"done": True, "n": len(ok)})
    return len(ok)

# ---------------- sync: tx list, overview, anchors, external links ----------------
def _store_rows(rows, seg):
    """Index rows of this segment into POAScan's txs table (the same upsert the minepoa feeds use). A tx minepoa.com
    refused (invalid_txs) is never stored. Returns (stored, new_by_type)."""
    from . import indexer as I
    lo, hi = _seg_bounds(seg)
    keep = [r for r in rows if isinstance(r, dict) and TXID.match(str(r.get("id") or "")) and _SG.of_ts(r.get("ts")) == seg
            and (lo is None or int(r.get("ts") or 0) >= lo) and (hi is None or int(r.get("ts") or 0) < hi)]
    if not keep: return 0, {}
    ids = [r["id"] for r in keep]
    bad = {x["txid"] for x in db.q(f"SELECT txid FROM invalid_txs WHERE txid IN ({','.join('?' * len(ids))})", tuple(ids))}
    keep = [r for r in keep if r["id"] not in bad]
    known = set()
    for i in range(0, len(keep), 500): known |= I._known([r["id"] for r in keep[i:i + 500]])
    new = collections.Counter(r.get("type") or "?" for r in keep if r["id"] not in known)
    norm = [dict(r, to_addr=r.get("to_addr") or None, amount=r.get("amount") or None, memo=r.get("memo") or None) for r in keep]
    I.upsert_txs(norm, SOURCE)
    return len(keep), dict(new)

def sync(now=None, sleep=time.sleep):
    """One run: overview, then the tx cursor (PAGES pages while behind, else one), then anchors and external links when due.
    Every failure keeps what is stored; the next run resumes from the stored cursor."""
    if not enabled(): return False
    init(); now = now or time.time(); st = _state()
    try: ov = (_get("overview", "overview").get("rows") or [{}])[0]
    except Unavailable:
        st["checked_at"] = int(now); _put_state(st); return False
    seg = segment_for(ov.get("chain"))
    st.update(checked_at=int(now), ok_at=int(now), chain=ov.get("chain"), segment=seg, index_txs=_int(ov.get("txs")), index_identities=_int(ov.get("identities")),
              newest_tx_ts=_int(ov.get("newest_tx_ts")), synced_at=_int(ov.get("synced_at")), anchors=_int(ov.get("anchors")))
    if seg is None:   # the index serves a chain the segments config does not know: store nothing until the config does
        st["state_note"] = "unknown chain"; _put_state(st); return False
    st.pop("state_note", None)
    ck = f"fx:cursor:s{seg}"; cur = (db.get_blob(ck)[0] or {})
    cursor = cur.get("cursor"); stored = int(cur.get("stored") or 0); diag = cur.get("new_by_type") or {}
    pages = PAGES if not cur.get("caught_up") else 1; caught = bool(cur.get("caught_up"))
    for i in range(pages):
        q = f"txs?limit={LIMIT}" + (f"&cursor={urllib.parse.quote(cursor, safe=':')}" if cursor else "")
        try: d = _get(q, "txs")
        except Unavailable: break
        rows = d.get("rows") or []
        n, new = _store_rows(rows, seg); stored += n
        for k, v in new.items(): diag[k] = diag.get(k, 0) + v
        if rows and d.get("next_cursor"): cursor = str(d["next_cursor"])
        if len(rows) < LIMIT: caught = True; break
        caught = False
        if i + 1 < pages: sleep(PAGE_GAP_S)
    cts = _int((cursor or "").split(":")[0]) if cursor else None
    db.put_blob(ck, dict(cursor=cursor, stored=stored, caught_up=caught, cursor_ts=cts, new_by_type=diag, at=int(now)))
    st.update(cursor_ts=cts, caught_up=caught, stored=stored, new_to_archive=sum(diag.values()), new_by_type=diag)
    if now - int(st.get("meta_at") or 0) >= META_S:
        if _meta(seg, sleep): st["meta_at"] = int(now)
    _put_state(st)
    return True

def _int(v):
    try: return int(v)
    except (TypeError, ValueError): return None

def _meta(seg, sleep=time.sleep):
    ok = True
    try:
        rows = _get("anchors", "anchors").get("rows") or []
        out = []
        for a in rows:
            if not isinstance(a, dict) or a.get("height") is None or not a.get("chain"): continue
            t = _iso(a.get("ts")); s = _SG.of_anchor(dict(state_root=a.get("state_root"), anchored_at=a.get("ts")))
            if s != seg: continue
            out.append((int(a["height"]), str(a["chain"])[:40], str(a.get("tx") or "")[:200] or None, str(a.get("state_root") or "")[:128] or None, t, seg))
        if out: db.write("INSERT OR REPLACE INTO fx_anchors(height, chain, tx, state_root, ts, segment) VALUES(?,?,?,?,?,?)", out, many=True)
    except Unavailable: ok = False
    sleep(PAGE_GAP_S)
    try:
        rows = _get("ext-addresses", "ext").get("rows") or []
        now = int(time.time())
        out = [(str(r["address"])[:100], str(r.get("network") or "")[:24], r["poa_address"], 1 if r.get("verified") in (1, True, "1") else 0, now)
               for r in rows if isinstance(r, dict) and r.get("address") and ADDR.match(str(r.get("poa_address") or ""))]
        if out: db.write("INSERT OR REPLACE INTO fx_ext(address, network, poa, verified, seen) VALUES(?,?,?,?,?)", out, many=True)
    except Unavailable: ok = False
    return ok

def _iso(s):
    from .ui import iso_ts
    return iso_ts(s)

# ---------------- seal bodies ----------------
def bodies(n=None, sleep=time.sleep):
    """Up to n grade seal bodies (BODIES_PER_MIN a run, one run a minute), newest first, only seals the index should
    already hold (at or before its newest tx). Each is read once; only the seal to answer link is kept."""
    if not enabled(): return 0
    n = BODIES_PER_MIN if n is None else n
    if n <= 0: return 0
    init(); st = _state(); tip = st.get("newest_tx_ts"); seg = st.get("segment")
    if not tip or not seg: return 0
    rows = db.q("""SELECT t.id FROM txs t LEFT JOIN seal_links s ON s.seal = t.id LEFT JOIN tx_detail d ON d.id = t.id
                   WHERE t.type = 'grade-sealed' AND t.segment = ? AND t.ts <= ? AND s.seal IS NULL AND d.id IS NULL
                   ORDER BY t.ts DESC LIMIT ?""", (seg, int(tip), n * 3))
    got = 0
    for r in rows:
        if got >= n: break
        if _neg_hit("b" + r["id"]): continue
        try: d = tx(r["id"], kind="seal_body")
        except Unavailable: break
        got += 1
        if not d or not link_seal(d): _neg_put("b" + r["id"])
        sleep(0.5)
    return got

def seals_for(answer):
    """Seal count for one answer from the stored links, and whether every seal that could name it has been read."""
    init()
    n = db.q1("SELECT COUNT(*) AS n FROM seal_links WHERE answer=?", (answer,))["n"]
    row = db.q1("SELECT ts, segment FROM txs WHERE id=?", (answer,))
    cov = coverage()
    complete = bool(row and row["ts"] and cov["complete_after_ts"] is not None and row["ts"] > cov["complete_after_ts"] and cov["through_ts"])
    return dict(answer=answer, seals=n, complete=complete, counted_through_ts=cov["through_ts"], complete_after_ts=cov["complete_after_ts"])

_cov = {"t": 0, "v": None}
def coverage(now=None):
    """through_ts: seals are counted up to the index's newest tx. complete_after_ts: every seal newer than this (up to
    through_ts) has its link stored, so an answer born after it has a complete count. Cached 60 s."""
    now = now or time.time()
    if _cov["v"] and now - _cov["t"] < 60: return _cov["v"]
    init(); st = _state(); tip = st.get("newest_tx_ts"); seg = st.get("segment") or _SG.CURRENT
    linked = db.q1("SELECT COUNT(*) AS n FROM seal_links WHERE segment=?", (seg,))["n"]
    total = db.q1("SELECT COUNT(*) AS n FROM txs WHERE type='grade-sealed' AND segment=?", (seg,))["n"]
    gap = db.q1("""SELECT MAX(t.ts) AS m FROM txs t WHERE t.type='grade-sealed' AND t.segment=? AND t.ts <= ?
                   AND NOT EXISTS (SELECT 1 FROM seal_links s WHERE s.seal = t.id)""", (seg, int(tip or 0)))["m"] if tip else None
    start = (_SG.BY_N.get(seg) or {}).get("start_ts") or 0
    v = dict(linked=linked, seals=total, through_ts=tip, complete_after_ts=(gap if gap is not None else (start - 1 if tip else None)))
    _cov.update(t=now, v=v); return v

# ---------------- lookups (page and API views) ----------------
def tx(tid, kind="tx", visitor=False):
    """One tx row with its signed body, or None when the index does not have it. Raises Unavailable."""
    tid = (tid or "").lower()
    if not TXID.match(tid): return None
    rows = _get("tx?q=" + tid, kind, visitor=visitor).get("rows") or []
    r = next((x for x in rows if isinstance(x, dict) and x.get("id") == tid), None)
    return r

def tx_detail(tid, visitor=True):
    """A tx detail shaped like minepoa's (id, type, from_addr, to_addr, amount, epoch, ts, atts, final, memo, body), or None.
    Never raises: off, over budget, failing or not indexed yet all read None and the caller goes to minepoa.com."""
    if not enabled() or not TXID.match(tid or "") or _neg_hit("t" + tid): return None
    try: r = tx(tid, visitor=visitor)
    except Unavailable: return None
    if not r or not isinstance(r.get("body"), dict): _neg_put("t" + tid); return None
    d = {k: r.get(k) for k in ("id", "type", "from_addr", "to_addr", "amount", "epoch", "ts", "atts", "final", "memo")}
    for k in ("to_addr", "amount", "memo"):
        if d.get(k) == "": d[k] = None
    d["final"] = bool(r.get("final") in (1, True, "1")); d["body"] = r["body"]; d["detail_source"] = "indexed cache"
    link_seal(d)
    return d

_addr_cache = collections.OrderedDict()
def address(a, visitor=True):
    """The index's address view (balance, external links, the last 100 txs), cached 60 s; None when unavailable."""
    if not enabled() or not ADDR.match(a or ""): return None
    hit = _addr_cache.get(a)
    if hit and time.time() - hit[0] < 60: return hit[1]
    try: d = _get("address?q=" + a, "address", visitor=visitor)
    except Unavailable: return None
    row = (d.get("rows") or [None])[0]
    out = dict(balance=(row or {}).get("balance"), tx_count=_int((row or {}).get("tx_count")), history=[h for h in d.get("history") or [] if isinstance(h, dict)],
               as_of=_state().get("newest_tx_ts")) if row else None
    _addr_cache[a] = (time.time(), out)
    while len(_addr_cache) > 500: _addr_cache.popitem(last=False)
    if out and out["history"]:
        st = _state(); seg = st.get("segment") or segment_for(st.get("chain"))
        if seg: _store_rows(out["history"], seg)
    return out

def resolve_external(q, allow_fetch=True):
    """An external wallet address to its poa1 Agent: POAScan's copies first (minepoa's /api/chains map, the stored index
    links), then one budgeted index read. Returns [{poa, network, address, verified, source}] (empty when unknown)."""
    q = (q or "").strip()
    if not is_external(q): return []
    norm = q.lower() if q[:2].lower() == "0x" else q
    out, seen = [], set()
    for agent, links in (db.get_blob("chains")[0] or {}).items():
        if not isinstance(links, dict) or not ADDR.match(str(agent)): continue
        for chain, v in links.items():
            ad = str((v or {}).get("addr") or "") if isinstance(v, dict) else ""
            if ad and (ad.lower() if ad[:2].lower() == "0x" else ad) == norm and agent not in seen:
                seen.add(agent); out.append(dict(poa=agent, network=chain, address=ad, verified=(v or {}).get("verified") is True, source="minepoa"))
    try:
        init()
        for r in db.q("SELECT address, network, poa, verified FROM fx_ext WHERE address = ? OR lower(address) = ?", (q, norm)):
            if r["poa"] not in seen: seen.add(r["poa"]); out.append(dict(poa=r["poa"], network=r["network"], address=r["address"], verified=bool(r["verified"]), source=PUBLIC_NAME))
    except Exception: pass
    if out or not allow_fetch or not enabled() or _neg_hit("r" + norm): return out
    try: rows = _get("resolve?q=" + urllib.parse.quote(q), "resolve", visitor=True).get("rows") or []
    except Unavailable: return out
    for r in rows:
        p = (r or {}).get("poa"); k = str((r or {}).get("kind") or "")
        if ADDR.match(str(p or "")) and k.startswith("external") and p not in seen:
            seen.add(p); out.append(dict(poa=p, network=k.split(":", 1)[1] if ":" in k else None, address=q, verified=None, source=PUBLIC_NAME))
    if not out: _neg_put("r" + norm)
    return out

# ---------------- state for Health, the status dot and /api/health ----------------
def feed(now=None):
    """The Fast index feed row: OK, Degraded (behind by more than LAG_DEGRADED_S, or failing with a recent good read) or
    Down (no good read for DOWN_S, or far behind). None when the index is off or not read yet."""
    if not enabled(): return None
    now = now or time.time(); st = _state()
    lo = max(_last["ok"] or 0, st.get("ok_at") or 0) or None; lag = lag_s(now, st)
    if not lo:
        if not st.get("checked_at"): return None
        state = "Down"
    elif now - lo > DOWN_S or (lag is not None and lag > 4 * DOWN_S): state = "Down"
    elif (lag is not None and lag > LAG_DEGRADED_S) or _fails[0] >= 3: state = "Degraded"
    else: state = "OK"
    return dict(label="Fast index", state=state, last_ok=lo, lag_s=lag)

STARTED = time.time()

def lag_s(now=None, st=None):
    """How far the index trails real time: now minus its newest indexed tx."""
    st = st if st is not None else _state(); t = st.get("newest_tx_ts")
    return int((now or time.time()) - t) if t else None

def public_state(now=None):
    """/api/health fast_index: state, lag and request counts. Never the URL."""
    if not enabled(): return dict(enabled=False)
    now = now or time.time(); st = _state(); f = feed(now) or {}
    cov = coverage(now)
    return dict(enabled=True, state=f.get("state"), lag_s=f.get("lag_s"), newest_tx_ts=st.get("newest_tx_ts"), synced_at=st.get("synced_at"),
                checked_at=st.get("checked_at"), chain=st.get("chain"), segment=st.get("segment"), index_txs=st.get("index_txs"),
                backfill=dict(caught_up=bool(st.get("caught_up")), cursor_ts=st.get("cursor_ts"), rows_read=st.get("stored"), new_to_archive=st.get("new_to_archive"),
                              new_by_type=st.get("new_by_type") or {}),
                seals=dict(linked=cov["linked"], seal_txs=cov["seals"], counted_through_ts=cov["through_ts"], complete_after_ts=cov["complete_after_ts"]),
                requests=requests_report(now), sync_every_s=SYNC_S)

def pill_line(now=None):
    """(text, html) for the status dot note, or None: how current the indexed cache is."""
    if not enabled(): return None
    f = feed(now)
    if not f: return None
    lag = f.get("lag_s")
    if f["state"] == "Down": return ("Fast index unavailable. Reading minepoa.com.", "Fast index unavailable. Reading minepoa.com.")
    if lag is None: return None
    m = max(1, lag // 60)
    t = f"Fast index {m} min behind." + (" Reading minepoa.com where newer." if f["state"] != "OK" else "")
    return (t, t)

# ---------------- jobs (own thread: never delays a minepoa.com read) ----------------
def jobs():
    return [("fx_sync", sync, SYNC_S, None), ("fx_bodies", bodies, 60, None)]

def start():
    if not enabled(): return None
    try: init()
    except Exception as e: log.warning("fast index init: %s", type(e).__name__); return None
    def seed_links():
        try: log.info("seal links from stored bodies: %d", backfill_links_from_details())
        except Exception as e: log.warning("seal link seed: %s", type(e).__name__)
    threading.Thread(target=seed_links, daemon=True, name="fx-links").start()
    from . import indexer as I
    th = threading.Thread(target=I.run_forever, kwargs=dict(jobs=jobs()), daemon=True, name="fastindex"); th.start()
    return th
