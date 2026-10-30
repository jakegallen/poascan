"""Protocol timeline (1.26.141): minepoa's signed releases, the public client files and /api/params changes.

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
import hashlib, json, logging, re, time, urllib.error, urllib.request, zlib
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

# ---------------------------------------------------------------- release notes (1.26.226)
# POAScan's one-line read of a signed release, beside its changelog_ref. Only what the live endpoints confirm.
# SHORT fits the timeline's Note cell; the full note is on hover and in the API.
SHORT = {"v0.67-joindiff": "Adjustable join difficulty (bits 21, was 20).", "v0.68-surge": "Joins briefly halted under load."}
NOTES = {
    "v0.67-joindiff": "Join difficulty is adjustable. /api/join-pow adds kind (pow) and sets bits per challenge (21, was 20). "
                      "A short proof gets a 403 with required_bits.",
    "v0.68-surge": "Joins briefly halted under load, then served again.",
}

# ---------------------------------------------------------------- release nudge (1.26.226)
# v0.68-surge (6:44 PM PT Oct 29) reached the timeline only at the next hourly /api/release read (7:12 PM PT). The signed
# release tx is on the ledger and in POAScan's tx index within minutes, so a G0 release tx whose txid the stored
# /api/release copy does not list triggers one early conditional read. No new polling: nothing is read unless such a
# tx is indexed, and at most once per NUDGE_GAP_S.
NUDGE_GAP_S = 600
NUDGE_LOOKBACK_S = 2 * 86400

def unknown_release_txs(rel=None, now=None):
    """Indexed G0 release txids (last NUDGE_LOOKBACK_S) that the stored /api/release copy does not list."""
    from . import signed as SGN
    now = int(now or time.time())
    rel = rel if rel is not None else (db.get_blob("release")[0] or {})
    known = {r.get("txid") for r in [rel.get("current") or {}] + list(rel.get("history") or []) if isinstance(r, dict)}
    rows = db.q("SELECT id FROM txs WHERE type='release' AND from_addr=? AND ts>=?", (SGN.TRUSTED_G0, now - NUDGE_LOOKBACK_S))
    return [r["id"] for r in rows if r["id"] not in known]

def release_nudge(now=None, fetch=None):
    """One early /api/release read when an indexed G0 release tx is missing from the stored copy. Returns True on a read."""
    from . import indexer as I
    now = int(now or time.time()); path = "/api/release"
    if not unknown_release_txs(None, now): return False
    r = db.q1("SELECT MAX(COALESCE(last_ok, 0), COALESCE(last_err, 0)) AS t FROM fetch_log WHERE endpoint=?", (path,))
    if r and r["t"] and now - r["t"] < NUDGE_GAP_S: return False
    if fetch is None and not I.can_fetch(path): I.skip_backoff(path); return False
    d = (fetch or (lambda: I.fetch(path, cond=True)))()
    if d is not I.NOT_MODIFIED and isinstance(d, dict): db.put_blob("release", d)
    _ensure(); sync_releases(None, now)
    return True

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
    try: params_check(None, now)
    except Exception as e: log.warning("protocol: params diff failed (%s)", type(e).__name__)
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

# ---------------------------------------------------------------- params changes
BOUNDARY_RX = re.compile(r"_(from|until)_(ts|epoch)$")
SAMPLE = 10   # list items shown per side in a change

def _canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def _summ(v):
    """A short, JSON safe view of a params value for the timeline (lists and maps can be long)."""
    if isinstance(v, list): return dict(n=len(v)) if len(v) > SAMPLE else v
    if isinstance(v, dict): return dict(keys=len(v)) if len(_canon(v)) > 300 else v
    return v

def _change(k, a, b):
    c = dict(key=k, old=_summ(a), new=_summ(b))
    if isinstance(a, list) and isinstance(b, list):
        sa, sb = [_canon(x) for x in a], [_canon(x) for x in b]
        c.update(added=[json.loads(x) for x in sb if x not in sa][:SAMPLE], removed=[json.loads(x) for x in sa if x not in sb][:SAMPLE])
    return c

def diff_params(old, new):
    """(changed_keys, boundaries, changes) between two /api/params copies. boundaries: keys named *_from_ts, *_from_epoch,
    *_until_ts or *_until_epoch that were added or changed, with their new value."""
    keys = sorted(set(old) | set(new)); ch, bd, out = [], {}, []
    for k in keys:
        if k in old and k in new and _canon(old[k]) == _canon(new[k]): continue
        ch.append(k); out.append(_change(k, old.get(k), new.get(k)) if k in old and k in new else dict(key=k, old=_summ(old.get(k)) if k in old else None,
                                                                                                  new=_summ(new.get(k)) if k in new else None, added=k not in old, removed=k not in new))
        if k in new and BOUNDARY_RX.search(k): bd[k] = new[k]
    return ch, bd, out

def params_check(p=None, now=None):
    """Compare the stored /api/params copy with the last one seen. The first copy is the baseline (no event).
    Returns the params_change event's key list, or None."""
    now = int(now or time.time())
    p = p if p is not None else db.get_blob("params")[0]
    if isinstance(p, dict) and isinstance(p.get("params"), dict): p = p["params"]
    if not isinstance(p, dict) or not p: return None
    h = hashlib.sha256(_canon(p).encode()).hexdigest()
    m = meta(); pm = m.get("params") or {}
    if pm.get("hash") == h: return None
    old = pm.get("snapshot")
    db.put_blob(META, dict(m, params=dict(hash=h, snapshot=p, since=now)))
    if not isinstance(old, dict): return None
    ch, bd, out = diff_params(old, p)
    if not ch: return None
    _add(f"params:{pm.get('hash')}:{h}", now, "params_change", now, sha_old=pm.get("hash"), sha_new=h,
         detail=dict(changed_keys=ch, boundaries=bd or None, changes=out[:40]))
    return ch

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
                        changelog_ref=d.get("changelog_ref"), note=NOTES.get(r["version"]) if r["kind"] == "release" else None, changes=d.get("changes"), detail=d))
    return out

# ---------------------------------------------------------------- server-only releases
PUBLIC_FIELDS = ("client_sha256", "web_client_sha256")   # the only release hashes with a public file POAScan can hash
UNVERIFIABLE_TIP = "Server-only release. No public artifact to verify."

def _pub(d):
    d = d or {}
    return (d.get("client_sha256") or d.get("engine_sha256"), d.get("web_client_sha256"))

def server_only_txids():
    """txids of signed releases that change no public file: both client hashes equal the previous signed release's (by ts),
    or the release names no client hash at all. What changed is server_sha256, worker_sha256 or params_sha256, which name
    no public artifact, so the hourly file check cannot verify them. The first release POAScan holds is never flagged."""
    _ensure()
    rows = db.q("SELECT txid, ts, id, detail FROM protocol_events WHERE kind='release' ORDER BY ts ASC, id ASC")
    out, prev = set(), None
    for r in rows:
        cur = _pub(json.loads(r["detail"]) if r["detail"] else {})
        if r["txid"] and (not any(cur) or (prev is not None and cur == prev)): out.add(r["txid"])
        if any(cur): prev = cur
    return out

def api(kind=None, limit=500):
    """GET /api/protocol: freshness, the live state and the timeline (rows; the CSV is the rows)."""
    m = meta(); now = time.time()
    rows = events(kind, limit); so = server_only_txids()
    for r in rows:
        r.pop("detail", None)
        r["server_only"] = r["kind"] == "release" and r.get("release_txid") in so
        r["verifiable"] = None if r["kind"] != "release" else not r["server_only"]
    return dict(source="minepoa_release_and_client_files", checked_at=m.get("last_check"), last_ok_ts=m.get("last_ok"),
                stale=stale(now), stale_after_s=STALE_S, check_errors=m.get("errors"),
                files=[dict(file=FILE_NAMES[f], url=BASE + p, sha256=(m.get("files") or {}).get(f, {}).get("sha"), bytes=(m.get("files") or {}).get(f, {}).get("bytes"),
                            first_seen=(m.get("files") or {}).get(f, {}).get("first_seen"), last_ok=(m.get("files") or {}).get(f, {}).get("last_ok")) for f, p, _ in FILES],
                current=state(), kind=kind, total=len(rows), rows=rows,
                note="Releases: /api/release hourly, and early when a G0 release tx is indexed that the stored copy lacks. note: POAScan's one-line read of a release. "
                     "Hourly: conditional GET of both client files (HEAD plus a full GET every 6 h when the host sends no validator); bytes are hashed, never run. "
                     "matches_release names the G0 signed release whose client_sha256 or web_client_sha256 equals the hash. "
                     "server_only (release rows): its client_sha256 and web_client_sha256 equal the previous signed release's, so only server, worker or params hashes moved; "
                     "none of those names a public file, so verifiable is false.",
                url="https://poascan.io/governance?tab=protocol")
