"""Chain segments (1.26.91). minepoa.com cut poa-mainnet-1 on 2026-10-24: the chain continued from checkpoint h44003 as a
new segment, epochs and checkpoint heights restarted, and the old history was archived as poa-mainnet-1-segment1
(notice 2026-10-24-genesis-cut, on-ledger tx e1c4ea26). Balances carried over.

Epoch numbers, checkpoint heights and nonces repeat across segments, so every place POAScan keys on one of them also
keys on the segment. Txs, answers and anchors carry a segment column (existing rows are segment 1; db.init migrates).
Close records live in one blob per segment: "epochs" holds the current segment, "epochs:s<n>" an archived one.

The segment a request reads is per thread: server.py sets it from ?segment=<n>, MCP tools from their segment argument,
and everything else reads the current segment. analytics.cached keys every cached value on it."""
import contextlib, datetime as _dt, os, threading

CUT_TS = 1792875660   # 2026-10-24T21:01:00Z: issued_ts of notice 2026-10-24-genesis-cut (/api/notices), the boundary POAScan uses
CUT_NOTICE = "2026-10-24-genesis-cut"
CUT_TX = "e1c4ea26349b41a6781bcb76f98e3da4118398d6a212122c099ab75561b38373"
ARCHIVE_URL = "https://github.com/EmblemCompany/ProofOfAgent/tree/poa-mainnet-1-segment1"

# n, label, chain id on /api/networks, start and end (UTC seconds; end None while live), the height the next segment
# continued from, closes in the segment (archived only) and the segment's final anchor state root (archived only).
SEGMENTS = (
    dict(n=1, label="Segment 1", chain_id="poa-mainnet-1-segment1", start_ts=None, end_ts=CUT_TS, cut_height=44003, closes=15,
         final_state_root="b45a8a5c6965cd4053f74e403f2817154f589fa5a3bc5d055ed016968fdd12a7", archive_url=ARCHIVE_URL),
    dict(n=2, label="Segment 2", chain_id="poa-mainnet-1", start_ts=CUT_TS, end_ts=None, from_height=44003, from_segment=1),
)
# POASCAN_SEGMENTS=1: one live segment and no cut (a fork on another network, or a test whose synthetic history spans the
# real cut time). Everything then reads as before 1.26.91.
if os.environ.get("POASCAN_SEGMENTS") == "1":
    SEGMENTS = (dict(n=1, label="Segment 1", chain_id="poa-mainnet-1", start_ts=None, end_ts=None),)
BY_N = {s["n"]: s for s in SEGMENTS}
CURRENT = SEGMENTS[-1]["n"]
NUMBERS = tuple(BY_N)
CUT_NOTE = "Segment 2 began at h44003 of segment 1. Earlier history archived."
CUT_LABEL = "Genesis cut"

_ctx = threading.local()

def selected():
    """The segment this thread reads (?segment=, an MCP segment argument), else the current one."""
    return getattr(_ctx, "n", None) or CURRENT

def set_selected(n):
    _ctx.n = n if n in BY_N else None

def reset(): _ctx.n = None

@contextlib.contextmanager
def use(n):
    prev = getattr(_ctx, "n", None); set_selected(n)
    try: yield
    finally: _ctx.n = prev

def parse(v):
    """A ?segment= value: an int in NUMBERS, None when absent or empty. ValueError otherwise."""
    if v is None or str(v).strip() == "": return None
    s = str(v).strip().lower().lstrip("s")
    if not s.isdigit() or int(s) not in BY_N: raise ValueError("segment must be " + " or ".join(str(n) for n in NUMBERS))
    return int(s)

def archived(n=None): return (n or selected()) != CURRENT

def label(n=None):
    n = n or selected(); return BY_N[n]["label"] + (" (archived)" if n != CURRENT else "")

def of_ts(ts):
    """The segment a tx, answer or snapshot with this UTC time belongs to (None or 0: the current one)."""
    try: t = int(ts or 0)
    except (TypeError, ValueError): return CURRENT
    if not t: return CURRENT
    for s in SEGMENTS:
        if (s["start_ts"] is None or t >= s["start_ts"]) and (s["end_ts"] is None or t < s["end_ts"]): return s["n"]
    return CURRENT

def iso_ts(s):
    try: return int(_dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except Exception: return None

def of_anchor(a):
    """An anchor row's segment: an archived segment's final state root always belongs to it (a late re-anchor of h44003
    stays in segment 1); otherwise the anchored_at time decides."""
    root = (a.get("state_root") or "").lower()
    for s in SEGMENTS:
        if s.get("final_state_root") and root == s["final_state_root"]: return s["n"]
    t = iso_ts(a.get("anchored_at"))
    return of_ts(t) if t else CURRENT

def blob_kind(n=None):
    """The blobs row holding a segment's close records."""
    n = n or selected(); return "epochs" if n == CURRENT else f"epochs:s{n}"

def of_record(e):
    """A close record's segment, by its close time (ts in seconds; a millisecond value is scaled)."""
    t = e.get("ts") if isinstance(e, dict) else None
    if isinstance(t, (int, float)) and t > 1e11: t = t / 1000
    return of_ts(t)

def offset(n=None):
    """Closes in every earlier segment: segment n's epoch k is lifetime close number offset(n) + k (vesting, lifetime rewards)."""
    n = n or selected(); return sum(int(BY_N[m].get("closes") or 0) for m in NUMBERS if m < n)

def gkey(epoch, n=None): return offset(n) + int(epoch)

def split_gkey(g):
    """(segment, epoch) for a lifetime close number."""
    g = int(g)
    for n in NUMBERS:
        c = BY_N[n].get("closes")
        if n == CURRENT or c is None or g < offset(n) + int(c): return n, g - offset(n)
    return CURRENT, g - offset(CURRENT)

def sql(alias=""):
    """(" AND <alias>segment = ?", (n,)) for the selected segment."""
    return f" AND {alias + '.' if alias else ''}segment = ?", (selected(),)

def info(n=None):
    """Public description of a segment for API responses."""
    n = n or selected(); s = BY_N[n]
    d = dict(segment=n, label=s["label"], archived=n != CURRENT, chain_id=s["chain_id"],
             start_ts=s["start_ts"], end_ts=s["end_ts"])
    if s.get("cut_height") is not None: d["cut_height"] = s["cut_height"]
    if s.get("closes") is not None: d["closes"] = s["closes"]
    if s.get("archive_url"): d["archive_url"] = s["archive_url"]
    if s.get("from_height") is not None: d.update(from_height=s["from_height"], from_segment=s["from_segment"])
    return d

def all_info(): return [info(n) for n in NUMBERS]

def has_cut(): return len(SEGMENTS) > 1

def cut():
    """The genesis cut, for API responses and pages (None in a single segment world)."""
    if not has_cut(): return None
    return dict(label=CUT_LABEL, ts=CUT_TS, notice_id=CUT_NOTICE, txid=CUT_TX, from_segment=1, from_height=44003, segment=CURRENT,
                archive_url=ARCHIVE_URL, note=CUT_NOTE)

def ep_label(g):
    """A lifetime close number as a label: E3 in the current segment, S1 E3 in an archived one."""
    n, k = split_gkey(g); return f"E{k}" if n == CURRENT else f"S{n} E{k}"

def ep_href(g):
    n, k = split_gkey(g); return f"/epoch/{k}" + ("" if n == CURRENT else f"?segment={n}")

def qs(n=None):
    """?segment=<n> for a link that stays in an archived segment, "" in the current one."""
    n = n or selected(); return "" if n == CURRENT else f"?segment={n}"
