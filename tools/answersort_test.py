#!/usr/bin/env python3
"""Answer Sort context surface (read-only, measurements not verdicts).

POAScan surfaces a small read-only slice of minepoa's official Answer Sort tool beside the grading queue board and in
the agent-facing board API. This covers the client's read path and the surface: it pages with the published cursor,
honors a 429 Retry-After with backoff, caches per epoch close (POAScan's open-epoch signal) without polling, is
non-blocking and last-good on failure, and is clearly labeled and linked. It must never change a grade, reward or any
on-chain value.

Run: python3 tools/answersort_test.py (in-process; the HTTP layer is stubbed, no real network)."""
import json, os, sys, tempfile, time, io, urllib.error
os.environ["POASCAN_SEGMENTS"] = "1"
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "as.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, answersort as AS, board as BD, segments as SG
import urllib.request
ORIG_GET = AS._get   # the real HTTP getter, restored for the 429 test
db.init()
db.put_blob("status", {"epochs_closed": 70, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
A._cache.clear()

fails = []
def check(name, ok): print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

BUILD = {"build_id": "70.efb0d9ad.15", "as_of_close": 70, "n_answers": 190305,
         "kpi": {"answers_in_multi_author_families": 57322, "share": 0.3012}}
FAM_FIELDS = ["fam", "n", "authors", "e0", "e1", "sample"]
FAM_ROWS = [["9c9fe21d43e383be", 4803, 558, 0, 70, "think of a toll that charges per impostor"],
            ["d0b229b941c12156", 2687, 410, 1, 70, "a seed word every answer must contain"]]

def reset_cache(): AS._cache.update(key=None, ctx=None, ts=0, refreshing=False, last_try=0.0)

# ---------------------------------------------------------------- 1. context parses the build + families slice
calls = []
def stub_get(path, timeout=AS.TIMEOUT):
    calls.append(path)
    if path.startswith("api/build"): return dict(BUILD)
    if path.startswith("api/families"): return {"fields": FAM_FIELDS, "rows": [list(r) for r in FAM_ROWS], "next_cursor": None}
    raise AssertionError("unexpected path " + path)
reset_cache(); AS._get = stub_get
ctx = AS.context(force=True)
for _ in range(100):
    if AS._cache["ctx"] is not None: break
    time.sleep(0.02)
ctx = AS.context()
check("context is available after the background fetch", ctx.get("available") is True)
check("label is 'Measurements, not verdicts' and the tool is linked", ctx["label"] == "Measurements, not verdicts" and ctx["tool_url"] == AS.TOOL_URL)
check("build_id, as_of_close and the multi-author share pass through", ctx["build_id"] == "70.efb0d9ad.15" and ctx["as_of_close"] == 70 and abs(ctx["multi_author_share"] - 0.3012) < 1e-9)
top = ctx["top_cross_author_families"]
check("top cross-author families carry members, authors and the shared sentence (positional fields decoded by name)",
      top and top[0]["members"] == 4803 and top[0]["authors"] == 558 and "toll" in top[0]["sample"])
check("the note says measurements only and never a grade or on-chain change", "no scores or verdicts" in ctx["note"] and "on-chain" in ctx["note"])

# ---------------------------------------------------------------- 2. cached per close, no refetch within the epoch (no polling)
n_before = len(calls)
for _ in range(5): AS.context()
check("a second view in the same close does not refetch (cached per epoch, no polling)", len(calls) == n_before)

# the close advances: the key changes and exactly one refresh runs
db.put_blob("status", {"epochs_closed": 71, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}); A._cache.clear()
AS.context()
for _ in range(100):
    if AS._cache["key"] == A.open_gkey(): break
    time.sleep(0.02)
check("a new close triggers a refresh keyed on the new open epoch", AS._cache["key"] == A.open_gkey() and len(calls) > n_before)

# ---------------------------------------------------------------- 3. cold placeholder is non-blocking and still labeled/linked
def failing_get(path, timeout=AS.TIMEOUT): raise RuntimeError("down")
reset_cache(); AS._get = failing_get
t0 = time.time(); ph = AS.context(force=True); dt = time.time() - t0
check("a cold or failing fetch returns immediately (non-blocking board)", dt < 0.2)
check("the placeholder is not available but still carries the label and tool link", ph.get("available") is False and ph["label"] == "Measurements, not verdicts" and ph["tool_url"] == AS.TOOL_URL)

# ---------------------------------------------------------------- 4. _get honors a 429 Retry-After then succeeds
class FakeResp:
    def __init__(self, body): self._b = body; self.headers = {}
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False
seq = []
def fake_urlopen(req, timeout=None):
    seq.append(time.time())
    if len(seq) == 1:
        raise urllib.error.HTTPError(req.full_url, 429, "rate limited", {"Retry-After": "1"}, None)
    return FakeResp(json.dumps({"ok": 1}).encode())
AS.urllib.request.urlopen = fake_urlopen
import poascan.answersort as _ASmod
_ASmod._get = ORIG_GET   # restore the real getter so it exercises the 429 retry path
t0 = time.time(); got = _ASmod._get("api/build"); waited = time.time() - t0
check("a 429 Retry-After is honored then the request succeeds", got == {"ok": 1} and len(seq) == 2 and waited >= 1.0)

# ---------------------------------------------------------------- 5. the pager follows next_cursor and passes it back
pages = []
def paging_get(path, timeout=AS.TIMEOUT):
    pages.append(path)
    if "cursor=" not in path: return {"fields": FAM_FIELDS, "rows": [list(FAM_ROWS[0])], "next_cursor": "CUR2"}
    return {"fields": FAM_FIELDS, "rows": [list(FAM_ROWS[1])], "next_cursor": None}
AS._get = paging_get
rows, fields, truncated = AS._paged("api/families", {"min_authors": 2}, key="rows", limit=100, max_pages=6)
check("the pager follows next_cursor across pages and stops at the last", len(rows) == 2 and not truncated)
check("the next_cursor is passed back on the following request", any("cursor=CUR2" in p for p in pages))

# ---------------------------------------------------------------- 6. the board card renders the label, link and families
AS._get = stub_get; reset_cache(); AS.context(force=True)
for _ in range(100):
    if AS._cache["ctx"] is not None: break
    time.sleep(0.02)
html = BD.answer_sort_html()
check("board card shows the 'Measurements, not verdicts' label", "Measurements, not verdicts" in html)
check("board card links the Answer Sort tool", AS.TOOL_URL in html and "Answer Sort tool" in html)
check("board card shows a shared sentence measurement", "toll" in html)
check("no em or en dash in the Answer Sort copy", not any(c in (html + (AS.LABEL or "") + (AS.context()["note"])) for c in "\u2014\u2013"))

# the cold placeholder card is still labeled and linked, and renders without the network
reset_cache(); AS._get = failing_get
ph_html = BD.answer_sort_html()
check("cold board card still labels and links the tool", "Measurements, not verdicts" in ph_html and AS.TOOL_URL in ph_html)

# ---------------------------------------------------------------- 7. read-only: the context has no grade/reward/on-chain fields
AS._get = stub_get; reset_cache(); AS.context(force=True)
for _ in range(100):
    if AS._cache["ctx"] is not None: break
    time.sleep(0.02)
ctx = AS.context()
ALLOWED_KEYS = {"available", "label", "tool_url", "docs_url", "build_id", "as_of_close", "n_answers",
                "answers_in_multi_author_families", "multi_author_share", "top_cross_author_families",
                "families_truncated", "epoch_key", "fetched_at", "note"}
fam_keys = set().union(*[set(f) for f in ctx["top_cross_author_families"]]) if ctx["top_cross_author_families"] else set()
check("the context carries only display keys (no grade, reward, seal, balance or signature field)",
      set(ctx) <= ALLOWED_KEYS and fam_keys <= {"fam", "members", "authors", "sample"})
check("answersort.py performs no database writes (read-only module)",
      not any(w in open(os.path.join(os.path.dirname(__file__), "..", "poascan", "answersort.py")).read() for w in ("db.write", "db.execute", "put_blob", "INSERT", "UPDATE", "DELETE")))

print(("\nFAILED: " + ", ".join(fails)) if fails else "\nall passed")
sys.exit(1 if fails else 0)
