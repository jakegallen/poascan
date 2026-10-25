"""Chain segments (1.26.91). minepoa.com cut poa-mainnet-1 on 2026-10-24: the chain continued from checkpoint h44003 as a
new segment, epochs and checkpoint heights restarted, and the old history was archived as poa-mainnet-1-segment1
(notice 2026-10-24-genesis-cut, on-ledger tx e1c4ea26). Balances carried over.

Epoch numbers, checkpoint heights and nonces repeat across segments, so every place POAScan keys on one of them also
keys on the segment. Txs, answers and anchors carry a segment column (existing rows are segment 1; db.init migrates).
Close records live in one blob per segment: "epochs" holds the current segment, "epochs:s<n>" an archived one.

Segment boundaries, labels, heights and per segment flags are config (segments.json), so adding a segment or moving a
boundary is one config edit: db.init reassigns stored rows and regroups close records to match on the next boot.

The segment a request reads is per thread: server.py sets it from ?segment=<n>, MCP tools from their segment argument,
and everything else reads the current segment. analytics.cached keys every cached value on it."""
import contextlib, datetime as _dt, json, os, threading

# 1.26.92: segments come from config (segments.json, or the file named by POASCAN_SEGMENTS_FILE), never from code.
# A boundary is the next entry's start_ts; end_ts, the archived flags and the cut fields are derived from the list.
CONFIG_PATH = os.environ.get("POASCAN_SEGMENTS_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "segments.json")

def _load(path=None):
    with open(path or CONFIG_PATH, encoding="utf-8") as f: cfg = json.load(f)
    segs = [dict(x) for x in cfg.get("segments") or []]
    if not segs: raise ValueError("segments config: no segments")
    segs.sort(key=lambda x: int(x["n"]))
    for i, x in enumerate(segs):
        x["n"] = int(x["n"]); x.setdefault("label", f"Segment {x['n']}"); x.setdefault("start_ts", None)
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        x["end_ts"] = int(nxt["start_ts"]) if nxt and nxt.get("start_ts") is not None else None
        if i and x.get("start_ts") is None: raise ValueError(f"segments config: segment {x['n']} needs start_ts")
    return segs, dict(cfg.get("sources") or {})

SEGMENTS, SOURCES = _load()
# POASCAN_SEGMENTS=1: one live segment and no cut (a fork on another network, or a test whose synthetic history spans the
# configured boundary). Everything then reads as before 1.26.91.
if os.environ.get("POASCAN_SEGMENTS") == "1":
    SEGMENTS, SOURCES = [dict(n=1, label="Segment 1", chain_id=SEGMENTS[-1].get("chain_id"), start_ts=None, end_ts=None)], {}
BY_N = {s["n"]: s for s in SEGMENTS}
NUMBERS = tuple(BY_N)

def live_chain(networks):
    """The chain /api/networks marks live and default (else live, else default), or None."""
    ch = [c for c in (networks or {}).get("chains") or [] if isinstance(c, dict)]
    pick = ([c for c in ch if c.get("status") == "live" and c.get("default")] or [c for c in ch if c.get("status") == "live"]
            or [c for c in ch if c.get("default")])
    return (pick[0].get("chain_id") if pick else None) or (networks or {}).get("default_chain")

def current_of(networks, segs=None, now=None):
    """The current segment: the latest configured segment that has started and whose chain_id is the live chain in
    /api/networks; with no networks data (or no configured match), the latest started segment."""
    import time as _t
    segs = segs or SEGMENTS; now = now or _t.time()
    started = [x for x in segs if x.get("start_ts") is None or int(x["start_ts"]) <= now] or segs[:1]
    lc = live_chain(networks)
    m = [x for x in started if lc and x.get("chain_id") == lc]
    return (m or started)[-1]["n"]

def _networks_blob():
    """The stored /api/networks read (the db module imports this one, so read the file directly)."""
    import sqlite3
    p = os.environ.get("POASCAN_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "poascan.db"))
    if not os.path.exists(p): return None
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        try: r = c.execute("SELECT json FROM blobs WHERE kind='networks'").fetchone()
        finally: c.close()
        return json.loads(r[0]) if r else None
    except (sqlite3.Error, ValueError): return None

CURRENT = SEGMENTS[-1]["n"] if len(SEGMENTS) == 1 else current_of(_networks_blob())

def _cut_of(x):
    """The cut that opened segment x (its start), or None for the first segment."""
    prev = BY_N.get(x.get("from_segment")) or next((y for y in SEGMENTS if y.get("end_ts") == x.get("start_ts") and y is not x), None)
    if x.get("start_ts") is None or prev is None: return None
    c = dict(x.get("cut") or {}); h = x.get("from_height", prev.get("cut_height"))
    lab = c.get("label") or "Segment boundary"
    note = f"{x['label']} began at h{h} of {prev['label'][0].lower() + prev['label'][1:]}. Earlier history archived." if h is not None else f"{x['label']} began. Earlier history archived."
    return dict(label=lab, ts=int(x["start_ts"]), notice_id=c.get("notice_id"), txid=c.get("txid"), from_segment=prev["n"], from_height=h,
                segment=x["n"], archive_url=prev.get("archive_url"), note=note, carried_closes=list(c.get("carried_closes") or []),
                excluded_closes=list(c["excluded_closes"]) if c.get("excluded_closes") is not None else None,
                carry_unlocked=c.get("carry_unlocked") if isinstance(c.get("carry_unlocked"), bool) else None)

CUTS = [c for c in (_cut_of(x) for x in SEGMENTS) if c]
_LAST = next((c for c in CUTS if c["segment"] == CURRENT), None) or (CUTS[-1] if CUTS else {})   # the cut that opened the current segment
# Names kept from 1.26.91: the newest cut (the current segment's start), derived from config.
CUT_TS = _LAST.get("ts") or 0
CUT_NOTICE = _LAST.get("notice_id")
CUT_TX = _LAST.get("txid")
ARCHIVE_URL = _LAST.get("archive_url")
CUT_NOTE = _LAST.get("note") or ""
CUT_LABEL = _LAST.get("label") or ""

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

def closes_of(m):
    """Closes in segment m: the config count for an archived segment, else its stored close records (None for the current one)."""
    if m == CURRENT: return None
    c = BY_N[m].get("closes")
    if c is not None: return int(c)
    try:
        from . import db
        return len(db.get_blob(blob_kind(m))[0] or [])
    except Exception: return 0

def offset(n=None):
    """Closes in every earlier segment: segment n's epoch k is lifetime close number offset(n) + k (vesting, lifetime rewards)."""
    n = n or selected(); return sum(int(closes_of(m) or 0) for m in NUMBERS if m < n)

def gkey(epoch, n=None): return offset(n) + int(epoch)

def split_gkey(g):
    """(segment, epoch) for a lifetime close number."""
    g = int(g)
    for n in NUMBERS:
        c = closes_of(n)
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

def _unconfirmed_set():
    """(segment, epoch) of every close whose rewards are not confirmed in later balances: config unconfirmed_closes,
    plus each boundary's excluded_closes (closes left out of the carried supply)."""
    out = {(n, int(k)) for n in NUMBERS for k in BY_N[n].get("unconfirmed_closes") or []}
    for x in SEGMENTS:
        for e in (x.get("cut") or {}).get("excluded_closes") or []:
            if int(e["segment"]) in BY_N: out.add((int(e["segment"]), int(e["epoch"])))
    return out

def unconfirmed(epoch, n=None):
    """True when this close's rewards are not confirmed in later balances (see _unconfirmed_set)."""
    n = n or selected(); return (n, int(epoch)) in _unconfirmed_set()

def unconfirmed_g(g):
    n, k = split_gkey(g); return unconfirmed(k, n)

def unconfirmed_list():
    """[{segment, epoch}] for every close whose rewards are not confirmed in later balances."""
    return [dict(segment=n, epoch=k) for n, k in sorted(_unconfirmed_set())]

def source_segment(name):
    """The segment an upstream source serves (config sources, e.g. explorer), or the current segment."""
    v = SOURCES.get(name)
    return int(v) if v in BY_N else CURRENT

def checkpoint_of(n, networks=None):
    """Segment n's checkpoint height: /api/networks for its chain_id (data) when listed, else its config cut_height."""
    s = BY_N.get(n) or {}
    for c in (networks or {}).get("chains") or []:
        if c.get("chain_id") == s.get("chain_id") and c.get("checkpoint_height") is not None:
            try: return int(c["checkpoint_height"])
            except (TypeError, ValueError): pass
    return s.get("cut_height")

def has_cut(): return len(SEGMENTS) > 1

def cut():
    """The newest cut (the current segment's start), for API responses and pages (None in a single segment world)."""
    return dict(_LAST) if _LAST else None

def cuts(): return [dict(c) for c in CUTS]

def ep_label(g):
    """A lifetime close number as a label: E3 in the current segment, S1 E3 in an archived one."""
    n, k = split_gkey(g); return f"E{k}" if n == CURRENT else f"S{n} E{k}"

def ep_href(g):
    n, k = split_gkey(g); return f"/epoch/{k}" + ("" if n == CURRENT else f"?segment={n}")

def qs(n=None):
    """?segment=<n> for a link that stays in an archived segment, "" in the current one."""
    n = n or selected(); return "" if n == CURRENT else f"?segment={n}"

def carry_unlocked():
    """1.26.123: whether rewards carried into the current segment from earlier ones are fully spendable since the cut
    (segments config cut.carry_unlocked). True: unlocked at the cut. False: they keep vesting on lifetime closes. None
    (unset): not confirmed network-wide; POAScan then shows the vesting figures as bounds (circulating a lower bound)."""
    v = ((BY_N[CURRENT].get("cut") or {}) if has_cut() else {}).get("carry_unlocked")
    return v if isinstance(v, bool) else None

def carry_basis():
    """circulating_basis for API responses: carry_unlocked, vesting_continues, or unconfirmed (flag unset)."""
    if not has_cut(): return "vesting"
    v = carry_unlocked(); return "carry_unlocked" if v is True else "vesting_continues" if v is False else "unconfirmed"
