"""Network upgrade surfaces from a private halt tracker (URL in POASCAN_HALT_SRC, never published).
Read every 10 minutes off the node (it adds no load to minepoa.com). Only the derived public state leaves this
module: one of paused, planned or back per surface group. Nothing else from the source is stored or shown.
Fetch or parse failures keep the last good state; with none, maint.py's manual switches decide."""
import os, re, time, logging, urllib.request
from . import db

log = logging.getLogger("poascan.halts")
SRC = os.environ.get("POASCAN_HALT_SRC", "").strip()
EVERY, TIMEOUT, MAX_AGE = 600, 8, 6 * 3600   # poll interval, fetch timeout, oldest state still trusted (s)
BLOB = "halts"

# Public surface groups, in display order, and how a halt-table endpoint cell maps to one.
GROUPS = ["Answers", "Grading", "Challenges", "Agent profile", "Hosted mining", "Joining", "Assignments", "Path actions", "MCP mining tools"]
MATCH = [("Joining", r"join|/j/|link-auto|link-signed|adopt|hosted/register"), ("Answers", r"hosted/answer"), ("Grading", r"hosted/grade"),
         ("Challenges", r"hosted/challenge"), ("Agent profile", r"hosted/me\b"), ("Hosted mining", r"hosted/mine"), ("Assignments", r"assignments"),
         ("Path actions", r"/a/<|path-action"), ("MCP mining tools", r"/mcp")]
RANK = {"paused": 3, "planned": 2, "back": 1, "live": 0}
STAYS = [("Self-custody mining", r"/api/submit"), ("Explorer", r"explorer"), ("Swap reads", r"swaps?"), ("Status", r"/api/status")]

def group_of(endpoint):
    e = endpoint.lower()
    for g, rx in MATCH:
        if re.search(rx, e): return g
    return None

def state_of(status):
    """Defensive read of one Status cell. Returns paused, planned, back, live, or None for unknown (no change)."""
    s = status.lower()
    if re.search(r"re-?enabled|cleared|\bback\b|restored|lifted|resumed", s): return "back"
    if "❌" in s or "cancel" in s: return "live"
    if not re.search(r"\bhalt", s): return None
    if "🟢" in s or re.search(r"\bhalted\b|\bdone\b|\blive\b", s): return "paused"
    if any(c in s for c in "⏳🟡⬜") or re.search(r"await|in progress|not started|planned", s): return "planned"
    return None

def _cells(line): return [c.strip() for c in line.strip().strip("|").split("|")]

def parse(md):
    """{groups: {group: state}, unknown: [n], stays_live: [public groups]} from section '1. Halt list'. Raises ValueError."""
    m = re.search(r"^#+\s*1\.\s*Halt list.*?$(.*?)(?=^#+\s*\d+\.|\Z)", md, re.M | re.S)
    if not m: raise ValueError("no halt list section")
    sec = m.group(1); rows = [l for l in sec.splitlines() if l.strip().startswith("|")]
    if len(rows) < 3: raise ValueError("no halt table")
    head = [h.lower() for h in _cells(rows[0])]
    try: ie, ist = next(i for i, h in enumerate(head) if h.startswith("endpoint")), next(i for i, h in enumerate(head) if h.startswith("status"))
    except StopIteration: raise ValueError("halt table columns changed")
    groups, unknown = {}, 0
    for l in rows[2:]:
        c = _cells(l)
        if len(c) <= max(ie, ist): continue
        g, st = group_of(c[ie]), state_of(c[ist])
        if g is None or st is None:
            unknown += 1; log.warning("halts: unmapped row (group %s, state %s)", g, st); continue
        if RANK[st] > RANK.get(groups.get(g), -1): groups[g] = st
    sl = re.search(r"stays live[^:]*:\**\s*(.*?)(?:\n\s*\n|\Z)", sec, re.I | re.S)
    stays = [g for g, rx in STAYS if sl and re.search(rx, sl.group(1), re.I)]
    if not groups: raise ValueError("no mapped rows")
    return dict(groups=groups, unknown=unknown, stays_live=stays)

def job():
    """Indexer job: fetch, parse, keep the last good state. Unknown rows leave that group's previous state."""
    if not SRC: return
    try:
        req = urllib.request.Request(SRC, headers={"User-Agent": "POAScan/1 (+https://poascan.io/about)"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r: md = r.read(200_000).decode("utf-8", "replace")
        d = parse(md)
    except Exception as e:
        log.warning("halts: keeping last good state (%s)", type(e).__name__); return
    prev = (db.get_blob(BLOB)[0] or {}).get("groups") or {}
    db.put_blob(BLOB, dict(groups=dict(prev, **d["groups"]), stays_live=d["stays_live"], ts=int(time.time())))

def current():
    """Last good derived state, or None when there is none (or it is older than MAX_AGE)."""
    d = db.get_blob(BLOB)[0]
    if not d or not d.get("groups") or time.time() - (d.get("ts") or 0) > MAX_AGE: return None
    return d

def summary():
    """Public block for meta.maintenance: surfaces by group, source, as of."""
    d = current()
    if not d: return dict(surfaces=None, surfaces_source="manual", surfaces_as_of=None, stays_live=None)
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(d["ts"]))
    return dict(surfaces={g: d["groups"][g] for g in GROUPS if g in d["groups"]}, surfaces_source="tracker", surfaces_as_of=iso, stays_live=d.get("stays_live") or [])
