"""Publisher signature check for minepoa's G0 notices and releases (1.26.65).

minepoa publishes every system notice and release manifest as an on-ledger tx signed by the genesis identity (G0)
(go.md, SYSTEM NOTICES: "Every notice is a G0-signed ON-LEDGER tx, verify any notice by its txid"). POAScan checks
each one offline, once per txid, and serves the result as a badge and as /api/v1/notices/verified.

Scheme (official client /client/poa.mjs, whose sha256 is the client_sha256 of the G0-signed release in /api/release):
* a poa1 address is "poa1" + base58(raw 32-byte Ed25519 public key) (addrOf, pubOfAddr)
* the signed bytes are canonical(body without sig): JSON, object keys sorted, no whitespace, strings as JSON.stringify
  writes them, UTF-8 (canonical, signBody, verifyBody); sig is base58 of the 64-byte Ed25519 signature
* the txid is sha256 hex of those same bytes (txidOf), so a stored body can never drift from its id
* the G0 declaration (genesis-identity) is self-signed and countersigned by every params.g0_countersigners address over
  "poa-g0-v1|<chain_id>|<g0>|<powers joined by ,>|<charter_ref>|<ts>" (g0DeclMsg, applyG0Tx)

Approach (verify the G0 key, then each notice and release tx, then check the listed fields against the signed body)
adapted from POA Observatory 0.3.0 poa_harness/release_review.py, MIT, Copyright (c) 2026 POA Observatory contributors.
Reimplemented here in standard-library Python (no Node, no new dependency), including Ed25519 verification (RFC 8032).

Load on minepoa.com: no new polling. The notice and release lists are already mirrored (/api/notices every 5 min,
/api/release hourly). Each signed tx is read once, ever, through the indexer's scheduled tx read (BG_TX_EP: allowlist,
gzip, no redirects, backoff with Retry-After, unknown ids negative cached 6 h), at most FETCH_PER_RUN per 10 min run,
and kept in tx_detail. A result is recomputed only when its stored body or its listing changes; nothing is re-read."""
import datetime as dt, hashlib, json, re, threading, time
from . import db

# ---------------------------------------------------------------- trust root
# G0, the publisher key. Traced 2026-10-23 to: GET /api/notices "g0"; GET /api/release g0.addr; the on-ledger
# genesis-identity tx G0_DECL_TX (/api/release g0.txid), whose body.g0 is this address, self-signed and countersigned
# 5/5 by params.g0_countersigners (/api/params). A different live G0 is reported (g0_live) and never trusted silently.
TRUSTED_G0 = "poa14YNP29qps22US1em7rT8cYp69z53EyDFGbrwa4HmbRzu"
G0_DECL_TX = "3a248d5135917bd2a4292fc1144095efafbe250aed68f793d0c2ccccc1852601"
BLOB = "signed_checks"
FETCH_PER_RUN = 2          # new signed txs read per job run (the job runs every 10 min)
MAX_RECORDS = 60           # notices plus releases kept in the feed
MAX_RELEASES = 12          # newest releases checked (the release history is long; older rows show no badge)
SOURCE = "https://minepoa.com/api/explorer/tx/"
G0_TYPES = ("genesis-identity", "notice", "release")
STATUSES = ("verified", "invalid", "unsigned", "pending")

# ---------------------------------------------------------------- Ed25519 verify (RFC 8032, section 5.1.7)
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)

def _padd(a, b):
    x1, y1, z1, t1 = a; x2, y2, z2, t2 = b
    A = (y1 - x1) * (y2 - x2) % _P; B = (y1 + x1) * (y2 + x2) % _P
    C = 2 * t1 * t2 * _D % _P; Z = 2 * z1 * z2 % _P
    E, F, G, H = B - A, Z - C, Z + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)

def _pmul(s, pt):
    q = (0, 1, 1, 0)
    while s:
        if s & 1: q = _padd(q, pt)
        pt = _padd(pt, pt); s >>= 1
    return q

def _peq(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0

def _pdec(s):
    """A 32-byte point encoding, or None when it is not a valid curve point."""
    if len(s) != 32: return None
    y = int.from_bytes(s, "little"); sign = y >> 255; y &= (1 << 255) - 1
    if y >= _P: return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        if sign: return None
        x = 0
    else:
        x = pow(x2, (_P + 3) // 8, _P)
        if (x * x - x2) % _P: x = x * _I % _P
        if (x * x - x2) % _P: return None
        if (x & 1) != sign: x = _P - x
    return (x, y, 1, x * y % _P)

_B = _pdec((4 * pow(5, _P - 2, _P) % _P).to_bytes(32, "little"))

def ed25519_verify(pub, msg, sig):
    """True when sig (64 bytes) is a valid Ed25519 signature of msg by the 32-byte public key pub."""
    if not (isinstance(pub, bytes) and isinstance(sig, bytes) and len(pub) == 32 and len(sig) == 64): return False
    A = _pdec(pub); R = _pdec(sig[:32]); S = int.from_bytes(sig[32:], "little")
    if A is None or R is None or S >= _L: return False
    k = int.from_bytes(hashlib.sha512(sig[:32] + pub + msg).digest(), "little") % _L
    return _peq(_pmul(S, _B), _padd(R, _pmul(k, A)))

# ---------------------------------------------------------------- encoding (poa.mjs b58dec, pubOfAddr, canonical)
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def b58dec(s):
    if not isinstance(s, str) or not s or len(s) > 120: raise ValueError("bad base58")
    n = 0
    for c in s:
        i = _B58.find(c)
        if i < 0: raise ValueError("bad base58")
        n = n * 58 + i
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw

def pub_of(addr):
    """The raw Ed25519 key inside a poa1 address."""
    if not isinstance(addr, str) or not addr.startswith("poa1"): raise ValueError("bad address")
    raw = b58dec(addr[4:])
    if len(raw) != 32: raise ValueError("bad address length")
    return raw

def fingerprint(addr):
    """SHA256:<first 16 hex> of the raw public key, the short form shown in tooltips."""
    try: return "SHA256:" + hashlib.sha256(pub_of(addr)).hexdigest()[:16]
    except ValueError: return None

def _num(v):
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, int): return str(v)
    if v != v or v in (float("inf"), float("-inf")): return "null"   # JSON.stringify(NaN) is null
    if v.is_integer() and abs(v) < 1e21: return str(int(v))
    return repr(v)

def canonical(v):
    """poa.mjs canonical(): sorted keys (UTF-16 order, as Array.prototype.sort), no whitespace, JSON.stringify scalars."""
    if isinstance(v, (list, tuple)): return "[" + ",".join(canonical(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + canonical(v[k]) for k in sorted(v, key=lambda k: k.encode("utf-16-be"))) + "}"
    if v is None: return "null"
    if isinstance(v, (bool, int, float)): return _num(v)
    return json.dumps(v, ensure_ascii=False)

def signed_bytes(body):
    return canonical({k: v for k, v in body.items() if k != "sig"}).encode("utf-8")

def g0_decl_msg(b, chain_id):
    return f'poa-g0-v1|{chain_id or ""}|{b.get("g0")}|{",".join(b.get("powers") or [])}|{b.get("charter_ref") or ""}|{b.get("ts")}'.encode("utf-8")

# ---------------------------------------------------------------- checks
def check_tx(detail, signer=TRUSTED_G0, txid=None):
    """(status, reason) for one tx detail ({id, body}): verified, invalid or unsigned. txid: the id it was listed under."""
    if not isinstance(detail, dict): return "pending", "signed tx not read yet"
    b = detail.get("body")
    if not isinstance(b, dict) or not b: return "pending", "signed tx body not available yet"
    if not b.get("sig"): return "unsigned", "no signature in the tx body: informational only"
    want = (txid or detail.get("id") or "").lower()
    try:
        msg = signed_bytes(b); sig = b58dec(b["sig"])
    except (ValueError, TypeError, UnicodeEncodeError):
        return "invalid", "signature or body cannot be decoded"
    if hashlib.sha256(msg).hexdigest() != want: return "invalid", "txid does not match the signed body"
    if b.get("from") != signer: return "invalid", "signed by a key other than G0"
    try: ok = ed25519_verify(pub_of(signer), msg, sig)
    except ValueError: ok = False
    return ("verified", None) if ok else ("invalid", "Ed25519 signature does not verify")

def check_g0(detail, params):
    """(status, reason, countersigned 'n/m') for the G0 declaration: self-signed by G0 and countersigned by every
    params.g0_countersigners address."""
    st, why = check_tx(detail, TRUSTED_G0, G0_DECL_TX)
    if st != "verified": return st, why, None
    b = detail["body"]
    if b.get("type") != "genesis-identity" or b.get("g0") != TRUSTED_G0: return "invalid", "declaration does not name this G0", None
    cs = (params or {}).get("g0_countersigners") or []
    if not cs: return "pending", "countersigner list (params.g0_countersigners) not read yet", None
    msg = g0_decl_msg(b, (params or {}).get("chain_id")); n = 0
    for a in cs:
        s = (b.get("countersigs") or {}).get(a)
        try: n += 1 if isinstance(s, str) and ed25519_verify(pub_of(a), msg, b58dec(s)) else 0
        except ValueError: pass
    if n != len(cs): return "invalid", f"countersigned by {n} of {len(cs)} pinned countersigners", f"{n}/{len(cs)}"
    return "verified", None, f"{n}/{len(cs)}"

NOTICE_FIELDS = (("notice_id", "id"), ("msg", "msg"), ("severity", "severity"), ("ts", "issued_ts"), ("expires_ts", "expires_ts"))
RELEASE_FIELDS = ("version", "engine_sha256", "server_sha256", "params_sha256", "worker_sha256", "client_sha256", "web_client_sha256", "ts")

def listing_diff(kind, listing, body):
    """Names of listed fields that differ from the signed body (empty when they agree, or with no listing)."""
    if not isinstance(listing, dict) or not isinstance(body, dict): return []
    if kind == "notice":
        return [src for f, src in NOTICE_FIELDS if src in listing and listing.get(src) != body.get(f)] + (["type"] if body.get("type") != "notice" else [])
    if kind == "release":
        return [f for f in RELEASE_FIELDS if f in listing and listing.get(f) != body.get(f)] + (["type"] if body.get("type") != "release" else [])
    return []

def verify_record(kind, txid, listing, detail):
    """(status, reason) for one listed notice or release: the tx check plus the listed fields against the signed body."""
    if isinstance(listing, dict) and str(listing.get("source") or "").lower() == "server-override":
        return "unsigned", "server override, not on the ledger: informational only"
    if not txid: return "unsigned", "no on-ledger txid: informational only"
    st, why = check_tx(detail, TRUSTED_G0, txid)
    if st != "verified": return st, why
    diff = listing_diff(kind, listing, detail["body"])
    if diff: return "invalid", "listed " + ", ".join(diff) + " differs from the signed tx"
    return "verified", None

# ---------------------------------------------------------------- time
def _pt(ts):
    """Pacific time without tzdata (DST second Sunday of March to first Sunday of November, 2am local): (datetime, label)."""
    u = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc); y = u.year
    def sun(m, k): d = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc); return d + dt.timedelta(days=(6 - d.weekday()) % 7 + 7 * (k - 1))
    on = sun(3, 2).replace(hour=10); off = sun(11, 1).replace(hour=9)
    h = -7 if on <= u < off else -8
    return u.astimezone(dt.timezone(dt.timedelta(hours=h))), "PDT" if h == -7 else "PST"

def times(ts):
    """{utc, pt} ISO strings for a unix time, or both None."""
    if not isinstance(ts, (int, float)) or ts <= 0: return dict(utc=None, pt=None)
    p, _ = _pt(ts)
    return dict(utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts))), pt=p.strftime("%Y-%m-%dT%H:%M:%S%z")[:-2] + ":" + p.strftime("%z")[-2:])

def human(ts):
    """'Oct 23, 2026 2:50 PM PDT (21:50 UTC)' for tooltips."""
    if not ts: return "not yet"
    p, lab = _pt(ts)
    return p.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ") + f" {lab} ({time.strftime('%H:%M', time.gmtime(int(ts)))} UTC)"

# ---------------------------------------------------------------- what POAScan shows
def _clean(s):
    s = re.sub(r"\s*\u2014\s*", ", ", str(s or "")).replace("\u2013", "-")
    return s if len(s) <= 160 else s[:157].rstrip() + "..."

def wanted():
    """[(kind, txid, listing)] for every signed record POAScan shows: the G0 declaration, the notices in the /api/notices
    mirror (plus notices POAScan links from milestones and the upgrade record), and the releases in the /api/release mirror.
    Local data only."""
    out, seen = [], set()
    def add(kind, txid, listing):
        t = (txid or "").lower()
        if t and (t in seen or not re.fullmatch(r"[0-9a-f]{64}", t)): return
        if t: seen.add(t)
        out.append((kind, t or None, listing))
    rel = db.get_blob("release")[0] or {}
    add("g0", G0_DECL_TX, None)   # pinned; a different live g0.txid shows in g0_live
    nb = db.get_blob("notices")[0] or {}
    for x in nb.get("active") or []:
        if isinstance(x, dict):
            ov = str(x.get("source") or "").lower() == "server-override"
            add("notice", None if ov else x.get("txid"), x)   # a server override is never checked as signed, even with a txid
    try:
        from . import maint as M
        c = M.complete()
        if c and c.get("txid"): add("notice", c["txid"], None)
    except Exception: pass
    try:
        from . import milestones as MS
        for e in MS.events():
            m = re.fullmatch(r"/tx/([0-9a-f]{64})", e.get("url") or "")
            if m: add("notice", m.group(1), None)
    except Exception: pass
    for r in ([rel.get("current")] + list(reversed(rel.get("history") or [])))[:MAX_RELEASES]:   # the newest releases only
        if isinstance(r, dict) and r.get("txid"): add("release", r["txid"], r)
    return out

_mem = {"ts": None, "d": None}; _lock = threading.Lock()

def state():
    """The stored results {txid: record}, cached in memory until the blob changes."""
    d, ts = db.get_blob(BLOB)
    with _lock:
        if ts != _mem["ts"]: _mem["ts"], _mem["d"] = ts, d if isinstance(d, dict) else {}
        return _mem["d"] or {}

def _key(listing, detail):
    raw = json.dumps([listing, (detail or {}).get("id"), (detail or {}).get("body")], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()[:24]

def _title(kind, listing, body):
    if kind == "g0": return "G0 declaration (genesis identity)"
    if kind == "release": return "Release " + str((listing or {}).get("version") or body.get("version") or "")
    return _clean((listing or {}).get("msg") or body.get("msg") or "")

SEVERITIES = ("info", "action", "critical")
def _sev(kind, listing, body):
    """A notice's severity (info, action or critical): the signed body's when read, else the listing's. None for releases."""
    if kind != "notice": return None
    v = str((body or {}).get("severity") or (listing or {}).get("severity") or "").lower()
    return v if v in SEVERITIES else None

def _rid(kind, txid, listing, body):
    if kind == "notice": return (listing or {}).get("id") or body.get("notice_id") or txid
    if kind == "release": return (listing or {}).get("version") or body.get("version") or txid
    return "g0"

BUSY_WAIT_S, BUSY_WAIT_MAX_S = 1200, 6 * 3600   # a tx whose read failed (5xx, timeout): 20 min, doubling to 6 h

def _no_request(e):
    """The indexer refused the read without asking minepoa (endpoint backing off, or an id it negative cached)."""
    m = str(e)
    return "backing off" in m or "(cached)" in m

def pending_summary(recs=None):
    """{pending, waiting, next_try_utc} over the stored records (for the feed): how many are still unread and when the next retry is due."""
    recs = (state().get("records") or {}) if recs is None else recs
    p = [r for r in recs.values() if r.get("kind") != "g0" and r.get("status") == "pending" and r.get("txid")]
    nt = min((r.get("next_try") or 0 for r in p), default=None)
    return dict(pending=len(p), retrying=sum(1 for r in p if (r.get("tries") or 0) + (r.get("fails") or 0) > 0),
                next_try_utc=times(nt)["utc"] if nt else None, per_run=FETCH_PER_RUN, run_every_s=600)

def refresh(fetch=True, now=None, fetch_tx=None):
    """Verify new or changed records; read at most FETCH_PER_RUN unread signed txs. Returns how many were read."""
    from . import indexer as I
    fetch_tx = fetch_tx or (lambda t: I.get_tx_detail(t, bg=I.BG_TX_EP))
    now = int(now or time.time()); old = dict(db.get_blob(BLOB)[0] or {}); recs = dict(old.get("records") or {}); reads = 0
    params = db.get_blob("params")[0] or {}
    # never-tried txs first, then retries whose wait is over: a missing tx (404) waits 1 h, doubling to 24 h; a tx whose
    # read failed (5xx, timeout) waits BUSY_WAIT_S, doubling to 6 h, so one failing tx never holds the queue's head and
    # the others still get their turn. Same budget: at most FETCH_PER_RUN real reads per run, and a failed read still
    # ends the run (the shared endpoint backoff). A read skipped without a request (endpoint backing off, or an id
    # negative cached by the indexer) costs no slot and no try.
    want = sorted(wanted(), key=lambda w: ((recs.get(w[1]) or {}).get("tries", 0) + (recs.get(w[1]) or {}).get("fails", 0),
                                           (recs.get(w[1]) or {}).get("next_try", 0)))
    for kind, txid, listing in want:
        if not txid:   # unsigned listing (no txid, or a server override): kept as Unverified, keyed by its notice id
            if kind != "notice" or not isinstance(listing, dict) or not listing.get("id"): continue
            key = "u:" + hashlib.sha256(str(listing.get("id")).encode("utf-8", "replace")).hexdigest()[:16]
            st, why = verify_record(kind, None, listing, None); prev = recs.get(key) or {}; k = _key(listing, None)
            if prev.get("key") != k:
                recs[key] = dict(kind=kind, id=str(listing.get("id"))[:80], title=_title(kind, listing, {}), ts=listing.get("issued_ts") or listing.get("issued_at"),
                                 txid=None, severity=_sev(kind, listing, {}), signer=None, status=st, reason=why, countersigned=None, key=k,
                                 checked_at=now, listing=listing, first_seen=prev.get("first_seen", now), tries=0, next_try=0, source=listing.get("source"))
            continue
        prev = recs.get(txid) or {}; tries, nxt, fails = prev.get("tries", 0), prev.get("next_try", 0), prev.get("fails", 0)
        detail = I.get_tx_detail(txid, allow_fetch=False)
        if not (detail and detail.get("body")) and fetch and reads < FETCH_PER_RUN and nxt <= now:
            reads += 1
            try: detail = fetch_tx(txid); fails = 0
            except I.Missing as e:
                detail = None
                if _no_request(e): reads -= 1; nxt = now + 3600   # negative cached by the indexer: no request made, look again in 1 h
                else: tries += 1; nxt = now + min(86400, 3600 * 2 ** (tries - 1))   # unknown or redirected (307)
            except I.Busy as e:   # 429, 5xx or backoff: no more reads this run (the endpoint backs off)
                fetch = False; detail = None
                if _no_request(e): reads -= 1
                else: fails += 1; nxt = now + min(BUSY_WAIT_MAX_S, BUSY_WAIT_S * 2 ** (fails - 1))
            if fetch: time.sleep(1.0)
        listing = listing if listing is not None else prev.get("listing")
        k = _key(listing, detail)
        if prev.get("key") == k:   # unchanged: checked once, kept
            if (tries, nxt, fails) != (prev.get("tries", 0), prev.get("next_try", 0), prev.get("fails", 0)): recs[txid] = dict(prev, tries=tries, next_try=nxt, fails=fails)
            continue
        body = (detail or {}).get("body") or {}
        if kind == "g0": st, why, cs = check_g0(detail, params)
        else: (st, why), cs = verify_record(kind, txid, listing, detail), None
        ts = (listing or {}).get("issued_ts") or (listing or {}).get("ts") or body.get("ts") or (detail or {}).get("ts")
        recs[txid] = dict(kind=kind, id=_rid(kind, txid, listing, body), title=_title(kind, listing, body), ts=ts, txid=txid,
                          severity=_sev(kind, listing, body), signer=body.get("from"), status=st, reason=why, countersigned=cs, key=k,
                          checked_at=now,
                          listing=listing if kind != "g0" else None, first_seen=prev.get("first_seen", now), tries=tries, next_try=nxt, fails=fails)
    # a listing that left the mirror keeps its last result (expired notices stay on POAScan); oldest dropped past the cap
    if len(recs) > MAX_RECORDS:
        keep = sorted(recs.values(), key=lambda r: (r["kind"] == "g0", r.get("ts") or 0), reverse=True)[:MAX_RECORDS]
        recs = {(r["txid"] or "u:" + hashlib.sha256(str(r.get("id")).encode()).hexdigest()[:16]): r for r in keep}
    nb = db.get_blob("notices")[0] or {}; rel = db.get_blob("release")[0] or {}
    live = dict(notices=nb.get("g0"), release=(rel.get("g0") or {}).get("addr"), declaration_txid=(rel.get("g0") or {}).get("txid"))
    if recs != old.get("records") or live != old.get("g0_live") or reads or not old:
        db.put_blob(BLOB, dict(records=recs, g0_live=live, ran_at=now, reads=reads))
        with _lock: _mem["ts"] = None   # same-second writes keep the blob ts: drop the parsed copy
    return reads

def job(): refresh()

# ---------------------------------------------------------------- reads for pages, the API and MCP
def lookup(txid=None, notice_id=None):
    recs = (state().get("records") or {})
    if txid: return recs.get((txid or "").lower())
    if notice_id: return next((r for r in recs.values() if r.get("kind") == "notice" and r.get("id") == notice_id), None)
    return None

_tx_cache = {}
def for_detail(d):
    """The result for a G0-type tx detail on its /tx page: the stored check, else a local check (memory cached by txid)."""
    if not isinstance(d, dict) or d.get("type") not in G0_TYPES and ((d.get("body") or {}).get("type") not in G0_TYPES): return None
    tid = (d.get("id") or "").lower(); r = lookup(tid)
    if r: return r
    if tid in _tx_cache: return _tx_cache[tid]
    st, why = check_tx(d, TRUSTED_G0, tid)
    if len(_tx_cache) > 500: _tx_cache.clear()
    r = _tx_cache[tid] = dict(txid=tid, status=st, reason=why, signer=(d.get("body") or {}).get("from") or TRUSTED_G0, checked_at=int(time.time()))
    return r

def badge(r):
    """Terse badge: Signed (check), Unverified or Invalid; the tooltip names the signer key and the check time."""
    if r is None: return ""
    st = r.get("status"); sev = r.get("severity")
    from .ui import E as _E
    sv = f'<span class="sigsev {_E(sev)}" title="Notice severity: {_E(sev)}">{_E(sev)}</span>' if sev in SEVERITIES else ""
    return sv + _badge(r, st)

def _badge(r, st):
    who = r.get("signer") or TRUSTED_G0; fp = fingerprint(who) or "?"
    from .ui import E
    if st == "verified":
        tip = f"Signed by minepoa G0 {who[:8]}...{who[-4:]}, key {fp}. Ed25519 signature checked {human(r.get('checked_at'))}."
        return (f'<span class="sigb ok" tabindex="0" title="{E(tip)}" data-sig="{E(tip)}"><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.3l2.3 2.3 4.7-5"/></svg>Signed</span>')
    if st == "invalid":
        tip = f"Invalid: {r.get('reason') or 'signature check failed'}. Expected G0 key {fingerprint(TRUSTED_G0)}. Checked {human(r.get('checked_at'))}."
        return f'<span class="sigb bad" tabindex="0" title="{E(tip)}" data-sig="{E(tip)}">Invalid</span>'
    tip = (f"Unverified, informational only: {r.get('reason') or 'not checked yet'}. G0 key {fingerprint(TRUSTED_G0)}."
           + (f" Checked {human(r.get('checked_at'))}." if r.get("checked_at") else ""))
    return f'<span class="sigb un" tabindex="0" title="{E(tip)}" data-sig="{E(tip)}">Unverified</span>'

def badge_tx(txid): return badge(lookup(txid=txid)) if txid else ""

def feed():
    """/api/v1/notices/verified and the MCP tool get_verified_notices."""
    from . import agentapi as AG
    s = state(); recs = list((s.get("records") or {}).values())
    g0r = next((r for r in recs if r.get("kind") == "g0"), None)
    rows = []
    body = [r for r in recs if r.get("kind") != "g0"]
    same = {}   # (kind, id) -> how many distinct signed txs carry it (minepoa re-published some releases under one version name)
    for r in body: same[(r["kind"], r.get("id"))] = same.get((r["kind"], r.get("id")), 0) + 1
    for r in sorted(body, key=lambda r: (r.get("ts") or 0, r.get("txid") or ""), reverse=True):
        t, c = times(r.get("ts")), times(r.get("checked_at")); tx = r.get("txid"); n = same[(r["kind"], r.get("id"))]
        rows.append(dict(kind=r["kind"], id=r.get("id"), title=r.get("title"), severity=r.get("severity"), txid=tx, txid_short=tx[:8] if tx else None,
                         same_id_count=n, label=f'{r.get("id")} · {tx[:8]}' if n > 1 and tx else r.get("id"), time_utc=t["utc"], time_pt=t["pt"],
                         signer=r.get("signer"), signer_fingerprint=fingerprint(r.get("signer") or ""), status=r.get("status"), reason=r.get("reason"),
                         informational_only=r.get("status") != "verified", notice_source=r.get("source"),
                         checked_at_utc=c["utc"], checked_at_pt=c["pt"], source_url=SOURCE + tx if tx else "https://minepoa.com/api/notices",
                         url=AG.BASE + "/tx/" + tx if tx else None))
    live = s.get("g0_live") or {}
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in STATUSES}
    gc = times((g0r or {}).get("checked_at"))
    return dict(
        signer=dict(address=TRUSTED_G0, fingerprint=fingerprint(TRUSTED_G0), public_key_hex=pub_of(TRUSTED_G0).hex(),
                    declaration=dict(txid=G0_DECL_TX, status=(g0r or {}).get("status", "pending"), reason=(g0r or {}).get("reason"),
                                     countersigned=(g0r or {}).get("countersigned"), checked_at_utc=gc["utc"], source_url=SOURCE + G0_DECL_TX),
                    key_source="The G0 address named by https://minepoa.com/api/notices (g0) and /api/release (g0.addr), declared on-ledger by the genesis-identity tx above "
                               "(self-signed, countersigned by every /api/params g0_countersigners address). The public key is the address: poa1 + base58 of the raw 32-byte Ed25519 key.",
                    g0_live=dict(notices=live.get("notices"), release=live.get("release"), declaration_txid=live.get("declaration_txid")),
                    g0_live_matches=bool(live.get("notices") in (None, TRUSTED_G0) and live.get("release") in (None, TRUSTED_G0)
                                         and live.get("declaration_txid") in (None, G0_DECL_TX))),
        scheme="Ed25519 over canonical JSON of the tx body without sig (keys sorted, no whitespace, UTF-8); txid = sha256 of the same bytes; "
               "listed notice and release fields must equal the signed body. As in minepoa's client /client/poa.mjs.",
        statuses=dict(verified="signature, txid and listed fields all check out", invalid="a check failed (see reason)",
                      unsigned="no on-ledger txid (for example a server-override notice) or no signature: Unverified, informational only, never Signed",
                      pending="the signed tx is not read yet; POAScan reads each one once. Treat as Unverified until then"),
        severities=dict(info="informational", action="asks Agents to change what they do", critical="stop and check; repeats until it expires"),
        counts=counts, backfill=pending_summary(s.get("records") or {}), records=rows, updated_utc=times(s.get("ran_at"))["utc"], method=AG.BASE + "/about#signed")
