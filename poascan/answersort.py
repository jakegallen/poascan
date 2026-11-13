"""Answer Sort context (read-only, measurements not verdicts).

minepoa.com's official grading-context tool (https://minepoa.com/tools/answer-sort/) publishes sentence families,
similarity edges, neighbors and timing over every PoA answer. Its own framing is "measurements, not verdicts": counts
and sentence overlaps, no scores, thresholds or quality labels. POAScan surfaces a small read-only slice beside the
grading queue board so a grader or agent can see cross-author sentence reuse as context. It never feeds a grade, a
reward or any on-chain value; it is display only.

Read path (mirrors the tool's own guidance):
  - The tool rebuilds about once per epoch close, so this caches per close. The key is POAScan's own open-epoch signal
    (analytics.open_gkey): a fetch happens only when the close changes, never on a timer, so this does NOT poll.
  - It pages with the published next_cursor (bounded by MAX_PAGES), and honors a 429 Retry-After with bounded backoff.
  - The board render triggers at most one background fetch per close; the render itself never blocks on the network and
    never breaks if the tool is slow or down (it serves the last good copy, or a label-and-link placeholder when cold).
  - On repeated failure it backs off (RETRY_COOLDOWN_S) instead of refetching on every view.
"""
import gzip, json, threading, time, urllib.error, urllib.parse, urllib.request
from . import analytics as A

TOOL_URL = "https://minepoa.com/tools/answer-sort/"
DOCS_URL = "https://minepoa.com/tools/answer-sort/docs"
BASE = TOOL_URL
UA = "POAScan/1.0 (+https://poascan.io; read-only)"
LABEL = "Measurements, not verdicts"

TIMEOUT = 12            # seconds per request
MAX_PAGES = 6           # cursor pages this client will follow at most (the tool caps v2 lists at 1000 rows a page)
MAX_BACKOFF_S = 20      # the longest 429 Retry-After honored on the request path before giving up to the last-good copy
PAGE_PAUSE_S = 0.6      # stay under the tool's 2 tokens/s refill between pages (never a burst)
RETRY_COOLDOWN_S = 120  # after a failed fetch, wait at least this long before trying again (no hot retry loop)
FAMILIES_SHOWN = 10     # top cross-author families surfaced on the board

_lock = threading.Lock()
_cache = {"key": None, "ctx": None, "ts": 0, "refreshing": False, "last_try": 0.0}


def _retry_after(v):
    try: return int(float(v))
    except (TypeError, ValueError): return 2


def _get(path, timeout=TIMEOUT):
    """One GET against the Answer Sort API. Returns parsed JSON or raises. Honors one 429 Retry-After (bounded)."""
    req = urllib.request.Request(BASE + path, headers={
        "User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip", "Cache-Control": "no-cache"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                if raw[:1] not in (b"{", b"["):
                    raise ValueError("answer-sort: non-JSON response")
                return json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                wait = _retry_after(e.headers.get("Retry-After"))
                if 0 < wait <= MAX_BACKOFF_S:
                    time.sleep(wait); continue
            raise
    raise RuntimeError("answer-sort: retry budget spent")


def _paged(path, params, key="rows", limit=1000, max_pages=MAX_PAGES):
    """Follow the published next_cursor up to max_pages, honoring 429 between pages. Returns (rows, fields, truncated)."""
    out, fields, cur, pages = [], None, None, 0
    while pages < max_pages:
        q = dict(params, limit=min(int(limit), 1000))
        if cur: q["cursor"] = cur
        d = _get(path + "?" + urllib.parse.urlencode(q))
        fields = fields or d.get("fields") or d.get("rowFields")
        out.extend(d.get(key) or d.get("rows") or [])
        cur = d.get("next_cursor"); pages += 1
        if not cur: break
        time.sleep(PAGE_PAUSE_S)
    return out, fields, (cur is not None)


def _epoch_key():
    """POAScan's existing open-epoch signal, reused as the cache key so the fetch runs once per close, not on a timer."""
    try: return A.open_gkey()
    except Exception: return None


def _placeholder(key):
    return dict(available=False, label=LABEL, tool_url=TOOL_URL, docs_url=DOCS_URL, epoch_key=key,
                note="Read-only measurements from minepoa's Answer Sort tool (counts and sentence overlaps only, no "
                     "scores or verdicts). It loads at the next close view.")


def _build_context(key):
    """Fetch a small read-only slice for the current close: build stamp, the multi-author KPI, and the top cross-author
    sentence families. Two requests per close (build, one families page), paged and 429-aware. Measurements only."""
    build = _get("api/build")
    fams, fields, truncated = _paged("api/families", {"min_authors": 2, "sort": "authors"}, key="rows", limit=100, max_pages=1)
    idx = {name: i for i, name in enumerate(fields or [])}
    def col(row, name, d=None):
        i = idx.get(name)
        return row[i] if (i is not None and i < len(row)) else d
    top = [dict(fam=col(r, "fam"), members=col(r, "n"), authors=col(r, "authors"), sample=col(r, "sample"))
           for r in fams[:FAMILIES_SHOWN]]
    kpi = build.get("kpi") or {}
    return dict(available=True, label=LABEL, tool_url=TOOL_URL, docs_url=DOCS_URL,
                build_id=build.get("build_id"), as_of_close=build.get("as_of_close"),
                n_answers=build.get("n_answers"),
                answers_in_multi_author_families=kpi.get("answers_in_multi_author_families"),
                multi_author_share=kpi.get("share"),
                top_cross_author_families=top, families_truncated=bool(truncated),
                epoch_key=key, fetched_at=int(time.time()),
                note="Read-only measurements from minepoa's Answer Sort tool: counts and sentence overlaps only, no "
                     "scores or verdicts. Cached per epoch close, refreshed when the close changes. It never changes a "
                     "grade, a reward or any on-chain value.")


def _refresh(key):
    try:
        ctx = _build_context(key)
    except Exception:
        ctx = None   # keep the previous copy (last-good); a cold failure leaves the placeholder, retried after the cooldown
    with _lock:
        _cache["refreshing"] = False
        if ctx is not None:
            _cache.update(key=key, ctx=ctx, ts=time.time())


def context(force=False):
    """Read-only Answer Sort context for the current close. Non-blocking: returns the cached copy (or a label-and-link
    placeholder when cold) and starts at most one background refresh per close. Never polls and never blocks the board."""
    key = _epoch_key()
    now = time.time()
    with _lock:
        fresh = _cache["ctx"] is not None and _cache["key"] == key
        last = _cache["ctx"]
        if fresh and not force:
            return last
        # Refresh on a new close (the key changed) or on force; when a fetch keeps failing within the same close, back
        # off (RETRY_COOLDOWN_S) instead of refetching on every view. A new close always refetches, cooldown or not.
        due = force or _cache["key"] != key or now - _cache["last_try"] > RETRY_COOLDOWN_S
        if not _cache["refreshing"] and due:
            _cache["refreshing"] = True; _cache["last_try"] = now
            threading.Thread(target=_refresh, args=(key,), daemon=True).start()
    return last or _placeholder(key)
