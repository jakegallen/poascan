"""Strain notice guard (build only, not released). Every minepoa.com read passes through check() before anything is stored.

From Oct 23, 2026 minepoa.com can answer a strained endpoint at once with a stand-in response that carries a network
style notice instead of data. POAScan must never store, cache or show that as real: indexer.fetch() raises Notice
(a Busy), so every caller keeps its last real copy exactly as it does for a 5xx, and the endpoint backs off. The
notice text, sanitized, shows in the site notice strip (ui.layout) and as upstream_notice in the API meta.

The exact wire format of the stand-in is NOT published (go.md, skill.md and /api/release read Oct 23, 2026) and was
not observed in live probes. Detection therefore combines:
  confirmed  system_notice: the documented notice object that may ride any API response (go.md, SYSTEM NOTICES):
             {id, severity: info|action|critical, msg, issued_at, expires_ts, seen_at, show, txid}. On its own it
             does NOT mark data fake (real responses may carry it); it marks a stand-in when the data fields are
             missing, or when its text matches STRAIN_TEXT.
  confirmed  REQUIRED: the field set each endpoint returned in live reads (Oct 23, 2026) and in POAScan's archive.
  heuristic  NOTICE_KEYS, STRAIN_KEYS, STRAIN_TEXT, STRAIN_HEADERS, NONEMPTY: guesses at the stand-in's shape.
Update the patterns here, in this block only; drop an exact sample in tools/strain_notice_test.py (SAMPLES)."""
import html, re, threading, time, unicodedata

# ---- patterns: the one place to edit -------------------------------------------------------------------------------
# Keys that carry a notice object or text. system_notice is documented; the rest are guesses.
NOTICE_KEYS = ("system_notice", "notice", "notice_override", "upstream_notice", "message", "msg", "error", "detail", "status")
# Keys whose presence (truthy) means "this is a stand-in", whatever else the body holds. Guesses.
STRAIN_KEYS = ("strain", "strained", "under_strain", "load_shed", "shed", "fake", "placeholder", "synthetic", "instant_response")
# Notice text that names strain or a stand-in. Deliberately narrow: real notices say "return instantly with status".
STRAIN_TEXT = re.compile(r"\bstrain(?:ed)?\b|\boverload(?:ed)?\b|\bload[\s_-]?shed(?:ding)?\b|\bhigh load\b|\bplaceholder\b|"
                         r"\bnot (?:real|live) data\b|\bstand[\s-]?in\b|\bfake (?:response|data)\b|\binstant (?:fake|placeholder|stand[\s-]?in) response\b", re.I)
# 1.26.89 (confirmed Oct 24, 2026): minepoa's API hardening halt answers a read with HTTP 503, Retry-After 3600 and
# {"error": "endpoint temporarily halted, API hardening in progress", "notice": {...}, "system_notice": {...}} on
# /api/explorer/tx/<id> (and /api/tx/<id>), /api/notices and /api/chains. A halt is not strain: the data is not faked, the
# lookup is off. It is kept apart (halted(), never the site strip or meta.upstream_notice) and shown per lookup.
HALT_TEXT = re.compile(r"\b(?:endpoint|lookup|route|surface)s? (?:is |are )?(?:temporarily )?(?:halted|paused|disabled)\b|\btemporarily halted\b", re.I)
HALT_KEYS = ("error", "message", "msg", "detail", "status")
HALT_NOTE = "minepoa.com paused this lookup. Showing indexed data."
HALT_NONE = "Not available while minepoa.com has this lookup paused."
# Response headers: (name, value pattern). Live reads carry x-poa-edge: read-node-primary; any other value is a guess.
STRAIN_HEADERS = (("x-poa-strain", re.compile(r".+")), ("x-poa-notice", re.compile(r".+")),
                  ("x-poa-edge", re.compile(r"strain|notice|shed|fallback|instant", re.I)))
# Endpoint template -> (container, required keys; for a list, keys each item needs). Confirmed from live reads and the archive.
REQUIRED = {
    "/api/status": ("dict", ("as_of", "supply", "txs", "epochs_closed", "checkpoint_height")),
    "/api/networks": ("dict", ("chains",)),
    "/api/explorer/txs": ("list", ("id",)),   # the feed needs only id (live_txs skips rows without one)
    "/api/explorer/tx/:id": ("dict", ("id",)),
    "/api/explorer/address/:addr": ("dict", ("address", "balance", "txs")),
    "/api/txs": ("dict", ("valid",)),
    "/api/epochs": ("list", ("epoch",)),
    "/api/agents": ("list", ("addr",)),
    "/api/anchors": ("list", ("height", "chain")),
    "/api/notices": ("dict", ("active",)),
    "/api/ballots": ("dict", ("ballots",)),
    "/api/params": ("dictany", ()),     # params gain and lose keys between releases: any non-notice key counts as data
    "/api/release": ("dict", ("current",)),
    "/api/chains": ("addrmap", ()),
    "/api/swaps": ("list", ("offer_id",)),
    "/api/explorer/grading": ("dict", ("rows", "stats", "epoch")),
    "/lableak/api/communities": ("list", ("slug",)),
    "/lableak/api/posts": ("list", ("id",)),
    "/lableak/api/posts/:id": ("dict", ("id",)),
}
# Lists that are never empty on a live network: an empty one reads as a stand-in. Heuristic.
NONEMPTY = ("/api/agents", "/api/epochs", "/lableak/api/communities")
# Detail reads where the node's own answer for an unknown id is a body without the id (often just an error or message):
# indexer turns that into Missing. Here a missing id fires only with a notice key (NOTICE_OBJ_KEYS), not a bare error.
SOFT_MISSING = ("/api/explorer/tx/:id", "/lableak/api/posts/:id")
NOTICE_OBJ_KEYS = ("system_notice", "notice", "notice_override", "upstream_notice")
NOTICE_TTL_S = 900      # a notice stays shown this long after its last sighting, unless a real read of that endpoint clears it
MAX_TEXT = 220
GENERIC = "minepoa.com sent a notice instead of data."
# ---------------------------------------------------------------------------------------------------------------------

_TPL = ((re.compile(r"^/api/explorer/tx/[0-9a-f]{64}$"), "/api/explorer/tx/:id"), (re.compile(r"^/chain/[a-z0-9\-]+/api/tx/[0-9a-f]{64}$"), "/api/explorer/tx/:id"),
        (re.compile(r"^/api/tx/[0-9a-f]{64}$"), "/api/explorer/tx/:id"), (re.compile(r"^/api/explorer/address/poa1\w+$"), "/api/explorer/address/:addr"),
        (re.compile(r"^/lableak/api/posts/\d+$"), "/lableak/api/posts/:id"))
ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")
SECRET_RX = re.compile(r"api[_\s-]?key|private key|seed phrase|mnemonic|password|send (?:poa|funds)|\bpk_|\bsk_", re.I)

def template(path):
    p = (path or "").split("?")[0]
    for rx, t in _TPL:
        if rx.match(p): return t
    return p

def _text_of(v):
    if isinstance(v, dict): return str(v.get("msg") or v.get("message") or v.get("text") or v.get("notice") or "")
    return v if isinstance(v, str) else ""

def _schema_gap(tpl, data):
    """None when data has the shape tpl needs, else a short reason."""
    spec = REQUIRED.get(tpl)
    if not spec: return None
    kind, keys = spec
    if kind == "list":
        if not isinstance(data, list): return "expected a list"
        if not data: return "empty list" if tpl in NONEMPTY else None
        bad = [x for x in data[:50] if not isinstance(x, dict) or any(k not in x for k in keys)]
        return "list items missing " + ",".join(keys) if bad else None
    if not isinstance(data, dict): return "expected an object"
    if kind == "dictany":
        return None if any(k not in NOTICE_KEYS and k not in STRAIN_KEYS for k in data) else "no data keys"
    if kind == "addrmap":
        odd = [k for k in data if not ADDR_RX.match(str(k))]
        return "non-address keys" if odd else None
    miss = [k for k in keys if k not in data]
    return "missing " + ",".join(miss) if miss else None

def detect(path, data, headers=None):
    """None for real data, else dict(signals=[...], text=raw notice text or ''). Pure: no state, no I/O."""
    tpl = template(path); sig = []; text = ""
    hd = {str(k).lower(): str(v) for k, v in (dict(headers or {})).items()}
    for name, rx in STRAIN_HEADERS:
        if name in hd and rx.search(hd[name]): sig.append("header:" + name)
    gap = _schema_gap(tpl, data)
    if isinstance(data, dict):
        for k in STRAIN_KEYS:
            if data.get(k) not in (None, False, 0, "", [], {}): sig.append("key:" + k)
        carriers = [k for k in NOTICE_KEYS if data.get(k) not in (None, "", [], {}) and k not in (REQUIRED.get(tpl, ("", ()))[1])]
        for k in carriers:
            t = _text_of(data[k])
            if t and not text: text = t
        sn = data.get("system_notice")
        if isinstance(sn, dict) and STRAIN_TEXT.search(_text_of(sn)): sig.append("system_notice:strain_text")
        if tpl in SOFT_MISSING: carriers = [k for k in carriers if k in NOTICE_OBJ_KEYS]
        if gap and carriers: sig.append("schema:" + gap + "+notice:" + carriers[0])
        elif text and STRAIN_TEXT.search(text): sig.append("text:strain")
    if gap and tpl not in SOFT_MISSING and not any(s.startswith("schema:") for s in sig): sig.append("schema:" + gap)
    halt = _halt_text(data) if (gap or tpl not in REQUIRED) else None   # a body that has its data fields is never a halt
    if halt:
        sig.insert(0, "halt:" + halt[0]); text = halt[1]
        return dict(signals=sig, text=text, endpoint=tpl, kind="halt")
    return dict(signals=sig, text=text, endpoint=tpl) if sig else None

def _halt_text(data):
    """(key, text) when the body says the endpoint is halted ('endpoint temporarily halted'), else None."""
    if not isinstance(data, dict): return None
    for k in HALT_KEYS:
        t = data.get(k)
        if isinstance(t, str) and HALT_TEXT.search(t): return k, t
    n = data.get("notice")
    if isinstance(n, dict) and HALT_TEXT.search(_text_of(n)): return "notice", _text_of(n)
    return None

def is_halt(hit): return bool(hit) and hit.get("kind") == "halt"

def strong(hit):
    """A hit that names a notice outright (header, strain key, system_notice text or strain wording), not shape alone."""
    return bool(hit) and any(not s.startswith("schema:") for s in hit["signals"])

def text_hit(raw):
    """Raw (possibly cut) body text: True when it names strain or a stand-in. For reads that keep only a prefix (hosted.py)."""
    t = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
    return bool(STRAIN_TEXT.search(t)) or any(f'"{k}":' in t.replace(" ", "") for k in STRAIN_KEYS if k not in ("shed", "fake"))

def sanitize(text):
    """Plain, short, safe: no markup, no control or symbol characters, no dashes of the em or en kind, capped. Text that
    asks for keys or funds is never shown (go.md: such a notice is an attack); the generic line is used instead."""
    t = html.unescape(str(text or ""))
    t = re.sub(r"<[^>]*>", " ", t)
    t = unicodedata.normalize("NFC", t)
    t = "".join(ch for ch in t if (unicodedata.category(ch)[0] not in ("C", "S") or ch in "$%+=<>") and not 0xFE00 <= ord(ch) <= 0xFE0F)
    t = re.sub(r"\s*[\u2012-\u2015\u2212]\s*", ", ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,;:")
    if not t or SECRET_RX.search(t): return GENERIC
    if len(t) > MAX_TEXT: t = t[:MAX_TEXT - 3].rsplit(" ", 1)[0].rstrip(" ,;:.") + "..."
    return t

# ---- state (memory only: the indexer threads run in the server process) ---------------------------------------------
_lock = threading.Lock(); _active = {}   # endpoint template -> dict(text, signals, first_seen, last_seen, count)

def record(path, hit, now=None, retry=None):
    now = int(now or time.time()); tpl = template(path)
    if is_halt(hit): return record_halt(path, hit, now, retry)
    with _lock:
        cur = _active.get(tpl) or dict(first_seen=now, count=0)
        _active[tpl] = dict(cur, text=sanitize(hit.get("text")), signals=list(hit.get("signals") or [])[:6], last_seen=now, count=cur["count"] + 1)

def clear(path):
    with _lock: _active.pop(template(path), None); _halts.pop(template(path), None)

def reset():
    with _lock: _active.clear(); _halts.clear()

# ---- halts (memory only): endpoint template -> dict(text, first_seen, last_seen, until, count) --------------------------
_halts = {}

def record_halt(path, hit, now=None, retry=None):
    """A halted lookup. Held until the later of NOTICE_TTL_S after the last sighting and the upstream Retry-After, so the
    note stays up while POAScan is backing off and never reads the endpoint; a real read of the endpoint clears it."""
    now = int(now or time.time()); tpl = template(path)
    with _lock:
        cur = _halts.get(tpl) or dict(first_seen=now, count=0)
        _halts[tpl] = dict(cur, text=sanitize(hit.get("text")), last_seen=now, until=now + max(NOTICE_TTL_S, int(retry or 0) + 60), count=cur["count"] + 1)

def halted(tpl, now=None):
    """The halt record for an endpoint template ('/api/explorer/tx/:id', '/api/notices', '/api/chains'), or None."""
    now = now or time.time()
    with _lock:
        v = _halts.get(tpl)
        if v and now > v["until"]: _halts.pop(tpl, None); v = None
        return dict(v) if v else None

def halt_notice(tpl, data="indexed", as_of=None, now=None, h=None):
    """The upstream_notice object for one API response while its upstream lookup is halted, else None."""
    h = h or halted(tpl, now)
    if not h: return None
    return dict(kind="halt", text=HALT_NOTE, upstream_text=h["text"], endpoint=tpl, first_seen=h["first_seen"], last_seen=h["last_seen"],
                retry_after_ts=h["until"], data=data, as_of=as_of)

def active(now=None):
    """{endpoint template: notice} seen within NOTICE_TTL_S."""
    now = now or time.time()
    with _lock:
        for k in [k for k, v in _active.items() if now - v["last_seen"] > NOTICE_TTL_S]: _active.pop(k, None)
        return {k: dict(v) for k, v in _active.items()}

def for_endpoint(tpl, now=None): return active(now).get(tpl)

def public(now=None):
    """The API flag (meta.upstream_notice): null, or the newest notice with every endpoint it covers."""
    a = active(now)
    if not a: return None
    k, v = max(a.items(), key=lambda kv: kv[1]["last_seen"])
    return dict(text=v["text"], endpoints=sorted(a), first_seen=min(x["first_seen"] for x in a.values()), last_seen=v["last_seen"],
                signals=v["signals"], data="last real values kept; nothing from the notice response was stored")

