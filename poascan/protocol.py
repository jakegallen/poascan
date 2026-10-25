"""Protocol timeline (1.26.141): minepoa's signed releases, the public client files and, later, params changes.

Source files: https://minepoa.com/client/poa.mjs (the reference client; its sha256 is client_sha256 and engine_sha256 in
the G0 signed release) and https://minepoa.com/poa-web.mjs (web_client_sha256). POAScan only hashes their bytes: it
never runs, imports or keeps them. Each is checked once an hour inside the hourly meta job: a conditional GET with the
stored ETag or Last-Modified (a 304 costs a few hundred bytes). Without a validator, a HEAD each hour (a changed
Content-Length triggers a GET) and a full GET at most every FULL_EVERY_S (6 h). Validators live in the database, so a
restart or deploy never adds a read.

Events (table protocol_events): release (from /api/release, keyed by txid), baseline (the first hash POAScan recorded
for a file), source_change (a file's sha256 moved; matches_release names the signed release whose hash it equals, else
it is unreleased) and params_change (/api/params keys added, removed or changed).

A check that fails keeps the last good hash; past STALE_S without a good check the state is flagged Stale."""
import gzip, hashlib, json, logging, time, urllib.error, urllib.request, zlib
from . import db

log = logging.getLogger("poascan.protocol")
BASE = "https://minepoa.com"
FILES = (("client", "/client/poa.mjs", "client_sha256"), ("web_client", "/poa-web.mjs", "web_client_sha256"))
FILE_NAMES = {"client": "poa.mjs", "web_client": "poa-web.mjs"}
FULL_EVERY_S = 6 * 3600      # full GET at most this often when the host sends no validator
STALE_S = 3 * 3600           # no good check for this long: Stale
MAX_BYTES = 4 * 1024 * 1024  # the client is about 310 KB
TIMEOUT_S = 30
META = "protocol_meta"
KINDS = ("release", "baseline", "source_change", "params_change")

# Seed (1.26.141): the signed release live when the timeline shipped and the hashes POAScan took at 12:45 PM PT, Oct 25 2026.
SEED_RELEASE = dict(version="v1.1.2-carveout2", ts=1792952074, txid="6904ab5b370a4fcdf2744af464c2329525dfd0e7e95733446a6fb042cb1657b4",
                    engine_sha256="25e1c64fbd1742331bb63d656c10cfae9102dddffb25d216a4841bbf9f2035dc",
                    server_sha256="72bcb3531bda24f81f3b6b639b2c5b33c32a05d661e2e7cbb0f5cd96009bdca8",
                    params_sha256="26234029f84a30f89d90384f29d61c53c64b8c37ba77a5d76fbbb0e3fd6f582b",
                    worker_sha256="63955cf41b8e6d4f2a4ef8d172891b5c3a223d13be9b972f60e425d5052df17b",
                    client_sha256="25e1c64fbd1742331bb63d656c10cfae9102dddffb25d216a4841bbf9f2035dc",
                    web_client_sha256="911b833b2fb1b292b17c17ff6e63c7086e9ad96a824a7aa41fbd21ecc7981f7c",
                    changelog_ref="pay-only system_pay_carveout_extra union at grader-pay carve-out")
SEED_TS = 1792957500
SEED_HASHES = {"client": ("25e1c64fbd1742331bb63d656c10cfae9102dddffb25d216a4841bbf9f2035dc", 309277),
               "web_client": ("911b833b2fb1b292b17c17ff6e63c7086e9ad96a824a7aa41fbd21ecc7981f7c", 28131)}

# ---------------------------------------------------------------- storage
_ready = [False]
def _ensure():
    if _ready[0]: return
    db.write("CREATE TABLE IF NOT EXISTS protocol_events(id INTEGER PRIMARY KEY, ukey TEXT NOT NULL UNIQUE, ts INTEGER NOT NULL, "
             "kind TEXT NOT NULL CHECK (kind IN ('release','baseline','source_change','params_change')), file TEXT, sha_old TEXT, sha_new TEXT, "
             "version TEXT, txid TEXT, matches_release TEXT, detail TEXT, first_seen INTEGER NOT NULL)")
    db.write("CREATE INDEX IF NOT EXISTS protocol_events_ts ON protocol_events(ts)")
    _ready[0] = True
    if not db.q1("SELECT 1 AS x FROM protocol_events LIMIT 1"): seed()

def _add(ukey, ts, kind, first_seen=None, **kw):
    """Insert one event once (ukey is unique). True when new."""
    _ensure()
    det = kw.pop("detail", None)
    cols = dict(ukey=ukey, ts=int(ts), kind=kind, first_seen=int(first_seen or time.time()), detail=json.dumps(det, separators=(",", ":")) if det is not None else None,
                **{k: kw.get(k) for k in ("file", "sha_old", "sha_new", "version", "txid", "matches_release")})
    if db.q1("SELECT 1 AS x FROM protocol_events WHERE ukey=?", (ukey,)): return False
    db.write(f"INSERT OR IGNORE INTO protocol_events({','.join(cols)}) VALUES({','.join('?' * len(cols))})", tuple(cols.values()))
    return True

def _rel_detail(r):
    return {k: r.get(k) for k in ("engine_sha256", "server_sha256", "params_sha256", "worker_sha256", "client_sha256", "web_client_sha256", "changelog_ref") if r.get(k)}

def seed():
    """The shipped baseline: the live signed release and both file hashes (idempotent)."""
    _ready[0] = True
    r = SEED_RELEASE
    _add("release:" + r["txid"], r["ts"], "release", SEED_TS, version=r["version"], txid=r["txid"], detail=_rel_detail(r))
    for f, (sha, n) in SEED_HASHES.items():
        _add(f"baseline:{f}", SEED_TS, "baseline", SEED_TS, file=f, sha_new=sha, matches_release=r["version"], detail=dict(bytes=n))
    m = meta()
    if not m.get("files"):
        db.put_blob(META, dict(m, files={f: dict(sha=sha, bytes=n, first_seen=SEED_TS) for f, (sha, n) in SEED_HASHES.items()}))

def meta(): return db.get_blob(META)[0] or {}

# ---------------------------------------------------------------- releases
def releases(rel=None):
    """Signed releases newest first: /api/release current plus history (deduplicated by txid), else the seed."""
    rel = rel if rel is not None else (db.get_blob("release")[0] or {})
    out, seen = [], set()
    for r in [rel.get("current") or {}] + list(reversed(rel.get("history") or [])):
        if isinstance(r, dict) and r.get("version") and r.get("txid") not in seen:
            seen.add(r.get("txid")); out.append(r)
    if not out: out = [SEED_RELEASE]
    out.sort(key=lambda r: -(r.get("ts") or 0))
    return out

def current_release(rel=None):
    rel = rel if rel is not None else (db.get_blob("release")[0] or {})
    c = rel.get("current")
    return c if isinstance(c, dict) and c.get("version") else releases(rel)[0]

def sync_releases(rel=None, now=None):
    """release events from the stored /api/release copy. Returns the number added."""
    n = 0
    for r in releases(rel):
        if r.get("txid") and _add("release:" + r["txid"], r.get("ts") or now or time.time(), "release", now, version=r["version"], txid=r["txid"], detail=_rel_detail(r)): n += 1
    return n

def release_for(sha, field, rel=None):
    """The newest signed release whose field (client_sha256 or web_client_sha256) equals sha, or None."""
    if not sha: return None
    for r in releases(rel):
        if r.get(field) == sha or (field == "client_sha256" and not r.get(field) and r.get("engine_sha256") == sha): return r
    return None

# ---------------------------------------------------------------- reads (bytes are hashed, never run or kept)
class CheckError(Exception):
    def __init__(self, msg, retry=None):
        super().__init__(msg); self.retry = retry

def _http(path, method="GET", headers=None):
    """One request to BASE+path (FILES paths only). Returns (status, headers, body bytes or b'')."""
    if path not in {p for _, p, _ in FILES}: raise ValueError("path not allowlisted")
    from . import indexer as I
    hold = I._hold[0] - time.time()
    if hold > 0: raise CheckError("paused after a 429", int(hold) + 1)
    hd = {"User-Agent": I.UA, "Accept": "*/*", "Accept-Encoding": "gzip"}
    hd.update(headers or {})
    req = urllib.request.Request(BASE + path, headers=hd, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            raw = r.read(MAX_BYTES + 1) if method == "GET" else b""
            if len(raw) > MAX_BYTES: raise CheckError("response too large")
            I.count_bytes(path, len(raw)); I.count(path, r.status); I._probe(path, True, t0, str(r.status))
            body = raw
            if method == "GET" and (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                d = zlib.decompressobj(16 + zlib.MAX_WBITS); body = d.decompress(raw, MAX_BYTES)
                if d.unconsumed_tail: raise CheckError("response too large")
            return r.status, r.headers, body
    except urllib.error.HTTPError as e:
        I.count(path, e.code)
        if e.code == 304: I._probe(path, True, t0, "304"); return 304, e.headers, b""
        I._probe(path, False, t0, str(e.code))
        retry = I.retry_after(e.headers.get("Retry-After"))
        if e.code == 429: I._hold[0] = max(I._hold[0], time.time() + min(I.RETRY_AFTER_MAX_S, retry or I.BACKOFF_BASE_S))
        raise CheckError(f"HTTP {e.code}", retry)
    except CheckError: raise
    except Exception as e:
        I.count(path, "err"); I._probe(path, False, t0, type(e).__name__); raise CheckError(type(e).__name__)

def _ok(path, now, nbytes=None):
    db.write("INSERT INTO fetch_log(endpoint,last_ok,fails,next_at,bytes,err) VALUES(?,?,0,0,?,NULL) "
             "ON CONFLICT(endpoint) DO UPDATE SET last_ok=excluded.last_ok, fails=0, next_at=0, bytes=COALESCE(excluded.bytes, fetch_log.bytes)", (path, now, nbytes))

def check_file(f, path, st, now, http=None):
    """One file's hourly check. st: its stored state (sha, bytes, etag, lastmod, full_at). Returns (new state, new sha or None).
    Conditional GET when a validator is stored; else HEAD (GET on a changed length) and a full GET every FULL_EVERY_S."""
    http = http or _http
    st = dict(st or {})
    if st.get("etag") or st.get("lastmod"):
        h = {}
        if st.get("etag"): h["If-None-Match"] = st["etag"]
        if st.get("lastmod"): h["If-Modified-Since"] = st["lastmod"]
        code, hd, body = http(path, "GET", h); how = "conditional"
    else:
        need_full = not st.get("sha") or now - (st.get("full_at") or 0) >= FULL_EVERY_S
        if not need_full:
            code, hd, _ = http(path, "HEAD", {"Accept-Encoding": "identity"})
            n = hd.get("Content-Length") if hd else None
            if code == 200 and n is not None and st.get("bytes") is not None and str(n).isdigit() and int(n) != st["bytes"]: need_full = True
            if hd and (hd.get("ETag") or hd.get("Last-Modified")): need_full = True   # validators appeared: one GET binds them to bytes we hashed
            if not need_full: st.update(checked=now, how="head"); return st, None
        code, hd, body = http(path, "GET"); how = "full"
    st["checked"] = now; st["how"] = how
    if code == 304: return st, None
    if code != 200 or not body: raise CheckError(f"HTTP {code}")
    sha = hashlib.sha256(body).hexdigest()
    st.update(etag=hd.get("ETag") if hd else None, lastmod=hd.get("Last-Modified") if hd else None, full_at=now, bytes=len(body))
    new = sha if sha != st.get("sha") else None
    st["sha"] = sha
    if new: st["first_seen"] = now
    return st, new

def check(now=None, http=None, rel=None):
    """The hourly check (called at the end of indexer.job_hourly_meta): releases from the stored copy, then both files.
    Never raises; failures are recorded in protocol_meta and the per-file fetch_log row."""
    now = int(now or time.time())
    try: _ensure(); sync_releases(rel, now)
    except Exception as e: log.warning("protocol: release sync failed (%s)", type(e).__name__)
    m = meta(); files = dict(m.get("files") or {}); errs = {}
    from . import indexer as I
    for f, path, field in FILES:
        if http is None and not I.can_fetch(path): errs[f] = "backing off"; continue
        old = (files.get(f) or {}).get("sha")
        try:
            st, new = check_file(f, path, files.get(f), now, http)
        except CheckError as e:
            errs[f] = str(e)[:80]
            try: I._fail(path, str(e)[:120], e.retry)
            except Exception: pass
            continue
        except Exception as e:
            errs[f] = type(e).__name__; log.warning("protocol: %s check failed (%s)", f, type(e).__name__); continue
        files[f] = dict(st, last_ok=now)
        try: _ok(path, now, st.get("bytes"))
        except Exception: pass
        if new:
            r = release_for(new, field, rel)
            if old: _add(f"source:{f}:{old}:{new}", now, "source_change", now, file=f, sha_old=old, sha_new=new, matches_release=r["version"] if r else None,
                         version=r["version"] if r else None, txid=r.get("txid") if r else None, detail=dict(bytes=st.get("bytes")))
            else: _add(f"baseline:{f}", now, "baseline", now, file=f, sha_new=new, matches_release=r["version"] if r else None, detail=dict(bytes=st.get("bytes")))
        if http is None: time.sleep(1)
    ok_all = not errs
    db.put_blob(META, dict(m, files=files, last_check=now, last_ok=now if ok_all else m.get("last_ok"), errors=errs or None,
                           fails=0 if ok_all else int(m.get("fails") or 0) + 1))
    return not errs

# ---------------------------------------------------------------- state for pages and the API (no upstream call)
def stale(now=None):
    t = meta().get("last_ok")
    return not t or (now or time.time()) - t > STALE_S

def state(rel=None):
    """Live file hashes against the current signed release."""
    _ensure()
    m = meta(); files = m.get("files") or {}; cur = current_release(rel)
    live = {f: (files.get(f) or {}).get("sha") for f, _, _ in FILES}
    match = {f: release_for(live[f], field, rel) for f, _, field in FILES}
    in_sync = {f: bool(live[f]) and live[f] == (cur.get(field) or (cur.get("engine_sha256") if f == "client" else None)) for f, _, field in FILES}
    known = all(live.values())
    if not known: st, badge = "unknown", "Client not checked yet"
    elif all(match.values()):
        v = match["client"]["version"]; st, badge = ("match" if all(in_sync.values()) else "older_release"), f"Client matches release {v}"
    else: st, badge = "unreleased", "Unreleased client change"
    return dict(state=st, badge=badge, release_version=cur.get("version"), release_txid=cur.get("txid"), release_ts=cur.get("ts"),
                engine_sha256=cur.get("engine_sha256"), client_sha256=cur.get("client_sha256"), web_client_sha256=cur.get("web_client_sha256"),
                live_client_sha256=live["client"], live_web_client_sha256=live["web_client"],
                client_matches_release=match["client"]["version"] if match["client"] else None,
                web_client_matches_release=match["web_client"]["version"] if match["web_client"] else None,
                client_in_sync=in_sync["client"], web_client_in_sync=in_sync["web_client"], in_sync=all(in_sync.values()))

def events(kind=None, limit=500):
    _ensure()
    sql = "SELECT * FROM protocol_events" + (" WHERE kind=?" if kind else "") + " ORDER BY ts DESC, id DESC LIMIT ?"
    out = []
    for r in db.q(sql, ((kind,) if kind else ()) + (int(limit),)):
        d = json.loads(r["detail"]) if r["detail"] else {}
        out.append(dict(id=r["id"], ts=r["ts"], first_seen=r["first_seen"], kind=r["kind"], file=FILE_NAMES.get(r["file"]) if r["file"] else None,
                        sha256_old=r["sha_old"], sha256_new=r["sha_new"], release_version=r["version"], release_txid=r["txid"],
                        matches_release=r["matches_release"], changed_keys=d.get("changed_keys"), boundaries=d.get("boundaries"),
                        changelog_ref=d.get("changelog_ref"), detail=d))
    return out

def api(kind=None, limit=500):
    """GET /api/protocol: freshness, the live state and the timeline (rows; the CSV is the rows)."""
    m = meta(); now = time.time()
    rows = events(kind, limit)
    for r in rows: r.pop("detail", None)
    return dict(source="minepoa_release_and_client_files", checked_at=m.get("last_check"), last_ok_ts=m.get("last_ok"),
                stale=stale(now), stale_after_s=STALE_S, check_errors=m.get("errors"),
                files=[dict(file=FILE_NAMES[f], url=BASE + p, sha256=(m.get("files") or {}).get(f, {}).get("sha"), bytes=(m.get("files") or {}).get(f, {}).get("bytes"),
                            first_seen=(m.get("files") or {}).get(f, {}).get("first_seen"), last_ok=(m.get("files") or {}).get(f, {}).get("last_ok")) for f, p, _ in FILES],
                current=state(), kind=kind, total=len(rows), rows=rows,
                note="Hourly: conditional GET of both client files (HEAD plus a full GET every 6 h when the host sends no validator); bytes are hashed, never run. "
                     "matches_release names the G0 signed release whose client_sha256 or web_client_sha256 equals the hash.",
                url="https://poascan.io/governance?tab=protocol")
