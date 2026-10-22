"""PoA keys (pk_..., psk_...) must never pass through POAScan: not into outbound requests, logs, the database,
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
WARN = "That looks like a PoA key. POAScan never takes keys and sent nothing. Never paste it anywhere."

def has_key(s):
    """True when s, raw or URL-decoded, holds a key-shaped token."""
    if not s: return False
    if isinstance(s, bytes): s = s.decode("utf-8", "replace")
    if KEY_RX.search(s): return True
    try:
        d = urllib.parse.unquote_plus(urllib.parse.unquote_plus(s))
    except Exception:
        d = s
    return bool(KEY_RX.search(d))

def has_cred_param(query):
    """True when a query string carries a credential-shaped parameter. POAScan has none of its own."""
    return any(k.lower() in PARAM_NAMES for k in urllib.parse.parse_qs(query or "", keep_blank_values=True))

def redact(s):
    """Replace key-shaped tokens (content: forum text, memos, tx bodies). Placeholders such as key=YOUR_KEY stay."""
    if isinstance(s, bytes): return KEY_RXB.sub(REDACTED.encode(), s)
    if isinstance(s, str) and "k_" in s: return KEY_RX.sub(REDACTED, s)
    return s

def redact_log(s):
    """Logs: keys and every credential-shaped parameter value, raw or URL-encoded."""
    s = str(s)
    if "%" in s:
        try: s = urllib.parse.unquote_plus(s)
        except Exception: pass
    return PARAM_RX.sub(r"\1[redacted]", KEY_RX.sub(REDACTED, s))

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
            rows = db.q(f"SELECT rowid AS rid, {c} AS v FROM {t} WHERE {c} LIKE '%k\\_%' ESCAPE '\\'")
        except Exception:
            continue
        for r in rows:
            v = r["v"]
            if isinstance(v, str) and KEY_RX.search(v):
                db.write(f"UPDATE {t} SET {c}=? WHERE rowid=?", (KEY_RX.sub(REDACTED, v), r["rid"])); n += 1
    return n
