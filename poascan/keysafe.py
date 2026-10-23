"""PoA keys (pk_..., psk_..., and GUID-shaped keys) must never pass through POAScan: not into outbound requests, logs, the database,
caches, pages, titles, URLs, redirects or errors. A leaked key means stolen POA.

One pattern list, used everywhere: request intake (reject), outbound fetches (refuse), every log line (redact),
every string written to the database (redact), every text response and live push (redact)."""
import logging, re, urllib.parse

# pk_ / psk_ / sk_ followed by a long token. Short mentions such as "pk_..." or "pk_…" in docs stay readable.
KEY_RX = re.compile(r"(?<![A-Za-z0-9])(?:p?sk|pk)_[A-Za-z0-9_\-]{12,}")
KEY_RXB = re.compile(rb"(?<![A-Za-z0-9])(?:p?sk|pk)_[A-Za-z0-9_\-]{12,}")
# Credential-shaped query parameters (go.md: key=, token=, guid= carry the key or the token made from it).
PARAM_NAMES = ("key", "api_key", "apikey", "token", "auth_token", "access_token", "guid", "secret", "password", "pk")
PARAM_RX = re.compile(r"(?i)([?&;](?:" + "|".join(PARAM_NAMES) + r")=)[^&#\s\"'<>]+")
REDACTED = "pk_[redacted]"
# Live minepoa keys can also be 36 character GUIDs (Oct 23 runner test). A bare GUID is also a normal id (the WebSocket
# accept GUID, Emblem app ids, podcast guids), so content is redacted only where a GUID sits in a credential slot:
# key= guid= token= (and api_key, auth_token, access_token), an X-Api-Key header, a JSON "key"/"token"/"guid" field, or
# after Bearer. key_guard() also refuses a request whose path segment or query value is a bare GUID: POAScan has no
# GUID-shaped ids of its own, so that is a pasted key.
GUID = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
GUID_CTX_RX = re.compile(r"(?i)((?:^|(?<=[?&;\s\"'{,(]))(?:x-api-key|api[_-]?key|apikey|key|guid|auth_token|access_token|token)[\"']?\s*[:=]\s*[\"']?\s*|\bbearer\s+)("
                         + GUID + r")(?![0-9A-Fa-f-])")
GUID_PRE = re.compile(r"-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-")   # cheap precheck: most text has no GUID at all
def _guid_ctx(s): return bool(GUID_PRE.search(s)) and bool(GUID_CTX_RX.search(s))
def _guid_sub(s): return GUID_CTX_RX.sub(lambda m: m.group(1) + REDACTED, s) if GUID_PRE.search(s) else s
GUID_VAL_RX = re.compile(r"(?:^|[/=])" + GUID + r"(?:$|[&#/?])")
WARN = "That looks like a PoA key. POAScan never takes keys and sent nothing. Never paste it anywhere."

def has_key(s):
    """True when s, raw or URL-decoded, holds a key-shaped token."""
    if not s: return False
    if isinstance(s, bytes): s = s.decode("utf-8", "replace")
    if KEY_RX.search(s) or _guid_ctx(s): return True
    try:
        d = urllib.parse.unquote_plus(urllib.parse.unquote_plus(s))
    except Exception:
        d = s
    return bool(KEY_RX.search(d) or _guid_ctx(d))

def has_guid_value(path):
    """True when a request path segment or query value, raw or URL-decoded, is a bare GUID (a pasted GUID key)."""
    if not path or "-" not in path: return False
    try: d = urllib.parse.unquote_plus(urllib.parse.unquote_plus(path))
    except Exception: d = path
    return bool(GUID_VAL_RX.search(path) or GUID_VAL_RX.search(d))

def has_cred_param(query):
    """True when a query string carries a credential-shaped parameter. POAScan has none of its own."""
    return any(k.lower() in PARAM_NAMES for k in urllib.parse.parse_qs(query or "", keep_blank_values=True))

def redact(s):
    """Replace key-shaped tokens (content: forum text, memos, tx bodies). Placeholders such as key=YOUR_KEY stay."""
    if isinstance(s, bytes):
        s = KEY_RXB.sub(REDACTED.encode(), s)
        if b"-" in s:
            t = s.decode("utf-8", "surrogateescape")
            if _guid_ctx(t): s = _guid_sub(t).encode("utf-8", "surrogateescape")
        return s
    if isinstance(s, str):
        if "k_" in s: s = KEY_RX.sub(REDACTED, s)
        if "-" in s: s = _guid_sub(s)
    return s

def redact_log(s):
    """Logs: keys and every credential-shaped parameter value, raw or URL-encoded."""
    s = str(s)
    if "%" in s:
        try: s = urllib.parse.unquote_plus(s)
        except Exception: pass
    return PARAM_RX.sub(r"\1[redacted]", _guid_sub(KEY_RX.sub(REDACTED, s)))

class _Filter(logging.Filter):
    def filter(self, record):
        try:
            msg = record.getMessage()
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            clean = redact_log(msg)
            if record.exc_text: record.exc_text = redact_log(record.exc_text)
            if clean != msg or record.args:
                record.msg, record.args = clean, None
        except Exception:
            pass
        return True

def install_log_filter():
    """Attach the redactor to every root handler (and to the root logger for handlers added later)."""
    f = _Filter(); root = logging.getLogger()
    root.addFilter(f)
    for h in root.handlers: h.addFilter(f)

TEXT_COLS = [("forum_posts", "body"), ("forum_posts", "title"), ("forum_comments", "body"), ("tx_detail", "json"),
             ("txs", "memo"), ("blobs", "json"), ("snaps", "json"), ("swap_events", "json"), ("swaps", "memo")]

def purge_db(db):
    """One pass over the text columns that hold other people's words; rewrite any row with a key-shaped token.
    Returns the number of rows changed (never the values)."""
    n = 0
    for t, c in TEXT_COLS:
        try:
            rows = db.q(f"SELECT rowid AS rid, {c} AS v FROM {t} WHERE {c} LIKE '%k\\_%' ESCAPE '\\' OR {c} LIKE '%-____-____-____-%'")
        except Exception:
            continue
        for r in rows:
            v = r["v"]
            if isinstance(v, str) and (KEY_RX.search(v) or _guid_ctx(v)):
                db.write(f"UPDATE {t} SET {c}=? WHERE rowid=?", (redact(v), r["rid"])); n += 1
    return n
