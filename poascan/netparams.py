"""Network params POAScan reads from minepoa (1.26.186): the pending TTL and the establishment TTL, segment aware.

Source order for a key in the selected segment:
  current segment: /api/params (POAScan's hourly cached copy, blob "params"; no extra upstream read). Stale when that copy
                   is older than ui.STALE_S (3 h). Missing there: the segment's "params" block in segments.json, flagged
                   Unconfirmed. Missing there too: the built in fallback (FALLBACK), flagged Stale and Unconfirmed.
  archived segment: its "params" block in segments.json (the values that segment closed under), else the fallback.
The pending TTL is cross checked against minepoa's grading list (expires minus since on its rows), when a copy is held.

Proposal L (LabLeak post 1582) may change the establishment TTL and the intake door by an operational flip, without a
ballot: every caller reads the value here per segment, so a flip shows up at the next hourly params read."""
import collections, time
from . import db, segments as SG

FALLBACK = {"pending_ttl_epochs": 16, "estab_ttl": 6}
LABEL = {"pending_ttl_epochs": "Pending TTL", "estab_ttl": "Establishment TTL"}
STALE_S = 3 * 3600   # same as ui.STALE_S: hourly sources read longer ago than this are Stale
METHOD = "/about#ttl"
_obs = {}

def _seg_params(n):
    return dict((SG.BY_N.get(n) or {}).get("params") or {})

def _int(v):
    try: return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError): return None

def read(key, seg=None, now=None):
    """{key, label, value, source, confirmed, stale, fallback, as_of, age_s, segment, note} for one TTL param.
    confirmed: the value comes from /api/params (or, for an archived segment, the values it closed under).
    stale: the params copy is older than STALE_S, or there is no params value at all."""
    seg = seg or SG.selected(); now = int(now or time.time()); fb = FALLBACK[key]
    out = dict(key=key, label=LABEL[key], segment=seg, archived=SG.archived(seg), as_of=None, age_s=None)
    cfg = _int(_seg_params(seg).get(key))
    if SG.archived(seg):
        if cfg is not None:
            return dict(out, value=cfg, source=f"segments.json ({SG.BY_N[seg]['label']} closed under it)", confirmed=True, stale=False, fallback=False,
                        note="The value this archived segment ran under, from POAScan's segment config.")
        return dict(out, value=fb, source="fallback", confirmed=False, stale=True, fallback=True, note=f"No recorded value for this segment; {fb} is POAScan's fallback.")
    p, ts = db.get_blob("params")
    v = _int((p or {}).get(key)) if isinstance(p, dict) else None
    if v is not None:
        age = now - int(ts) if ts else None; stale = age is None or age > STALE_S
        return dict(out, value=v, source=f"/api/params {key}", confirmed=True, stale=stale, fallback=False, as_of=int(ts) if ts else None, age_s=age,
                    note=("minepoa's params, read hourly" + (f"; last read {age // 3600}h ago" if stale and age is not None else "")))
    if cfg is not None:
        return dict(out, value=cfg, source="segments.json", confirmed=False, stale=True, fallback=False, as_of=int(ts) if ts else None,
                    note=f"/api/params has no {key}; POAScan's segment config value is used.")
    return dict(out, value=fb, source="fallback", confirmed=False, stale=True, fallback=True, as_of=int(ts) if ts else None,
                note=f"/api/params has no {key}" + ("" if p else " (no params copy yet)") + f"; {fb} is POAScan's fallback, not a live value.")

def value(key, seg=None): return read(key, seg)["value"]
def pending_ttl(seg=None): return read("pending_ttl_epochs", seg)
def estab_ttl(seg=None): return read("estab_ttl", seg)

def observed_pending_ttl(rows=None):
    """From minepoa's grading list copy (current segment only): the most common expires minus since over pending rows,
    with how many rows carry both and how many agree. None without rows."""
    if rows is None:
        if SG.archived(): return None
        try:
            from . import grading as GR
            d = GR.current()
        except Exception: return None
        if not d: return None
        k = (id(d), d.get("fetched_at"), len(d.get("rows") or []))
        if _obs.get("k") == k: return _obs["v"]   # once per grading list read, not per page view
        v = observed_pending_ttl(list(d.get("rows") or []) + list(d.get("open") or []))
        _obs.update(k=k, v=v); return v
    c = collections.Counter()
    for r in rows:
        e, s = _int((r or {}).get("expires")), _int((r or {}).get("since"))
        if e is not None and s is not None: c[e - s] += 1
    if not c: return None
    mode, n = c.most_common(1)[0]
    return dict(ttl=mode, rows=sum(c.values()), agree=n, values=dict(sorted(c.items())), source="minepoa grading list (expires minus since)")

def flags(t, obs=None):
    """Tag words for a TTL read: Stale (old or missing params), Unconfirmed (not from params), Differs (the grading list's
    expires minus since disagrees)."""
    out = []
    if t["stale"]: out.append(("Stale", t["note"]))
    if not t["confirmed"]: out.append(("Unconfirmed", t["note"]))
    if obs and t["key"] == "pending_ttl_epochs" and obs["ttl"] != t["value"]:
        out.append(("Differs", f"minepoa's grading list rows expire {obs['ttl']} epochs after entry ({obs['agree']:,} of {obs['rows']:,} rows); params say {t['value']}."))
    return out

def flag_html(t, obs=None):
    from .ui import flag
    return "".join(flag(w, d) for w, d in flags(t, obs))

def api_block(seg=None):
    """Both TTLs with provenance, for the API and MCP."""
    p = pending_ttl(seg); obs = observed_pending_ttl() if not p["archived"] else None
    e = estab_ttl(seg)
    return dict(pending_ttl=dict(p, observed=obs, flags=[w for w, _ in flags(p, obs)]), estab_ttl=dict(e, flags=[w for w, _ in flags(e)]),
                fallbacks=dict(FALLBACK), method="https://poascan.io" + METHOD)

def live_text(s, seg=None):
    """Rewrites the fixed '16 epochs' pending TTL wording in a static text (prompts, tips) with the live value."""
    v = value("pending_ttl_epochs", seg)
    return s if v == 16 else s.replace("last 16 epochs", f"last {v} epochs").replace("after 16 epochs", f"after {v} epochs").replace("keep 16 epochs", f"keep {v} epochs")
