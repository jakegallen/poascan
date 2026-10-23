"""Upgrade surface states from a private live prober (base URL in POASCAN_PULSE_SRC, never published).
One GET <src>/probe every 5 minutes, off the node (no load on minepoa.com). Only derived per-group states
(paused or back) are stored; codes, bodies, timings and every other probe field are dropped here.
A stale (age_s > MAX_PROBE_AGE) or unreachable probe marks the result unusable, so halts.py falls back to the doc."""
import os, re, json, time, logging, urllib.request
from . import db

log = logging.getLogger("poascan.pulse")
SRC = os.environ.get("POASCAN_PULSE_SRC", "").strip().rstrip("/")
EVERY, TIMEOUT, MAX_PROBE_AGE, MAX_AGE = 300, 20, 900, 1200   # the probe runs its checks on request, ~5s
BLOB = "pulse"
# Probe endpoint -> public groups. Endpoints not listed (status, indexes, snapshot, internals) are never published.
MAP = [(r"hosted/challenge", ("Challenges", "Hosted mining")), (r"hosted/me\b", ("Agent profile", "Hosted mining")),
       (r"hosted/assignments", ("Assignments",)), (r"hosted/grade\b", ("Grading",)), (r"/a/<|path-action", ("Path actions",))]   # grade: read only if the probe already reports it

def _halted(r):
    b = r.get("body"); b = b if isinstance(b, str) else json.dumps(b or "")
    return r.get("code") == 503 and "temporarily halted" in b.lower()

def parse(d, seen=()):
    """Probe JSON -> (groups {group: paused|back}, seen_halted [groups]). Raises ValueError on stale or malformed input.
    Paused: any endpoint of the group answers 503 halted. Back: every endpoint answers 200 and the group was halted before.
    Anything else (5xx without the halt notice, timeouts, 200 never halted) leaves the group to the doc."""
    if not isinstance(d, dict) or not isinstance(d.get("results"), list): raise ValueError("no results")
    age = d.get("age_s")
    if not isinstance(age, (int, float)) or age > MAX_PROBE_AGE: raise ValueError("stale probe")
    per = {}
    for r in d["results"]:
        if not isinstance(r, dict): continue
        e = str(r.get("endpoint", "")).lower()
        st = "halted" if _halted(r) else "ok" if r.get("code") == 200 else "unknown"
        for rx, gs in MAP:
            if re.search(rx, e):
                for g in gs: per.setdefault(g, []).append(st)
    seen = set(seen); groups = {}
    for g, sts in per.items():
        if "halted" in sts: groups[g] = "paused"; seen.add(g)
        elif all(s == "ok" for s in sts) and g in seen: groups[g] = "back"
    return groups, sorted(seen)

def job():
    if not SRC: return
    prev = db.get_blob(BLOB)[0] or {}
    try:
        req = urllib.request.Request(SRC + "/probe", headers={"User-Agent": "POAScan/1 (+https://poascan.io/about)"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r: d = json.loads(r.read(500_000))
        groups, seen = parse(d, prev.get("seen") or ())
    except Exception as e:
        log.warning("pulse: probe unusable, doc decides (%s)", type(e).__name__)
        db.put_blob(BLOB, dict(prev, ok=False)); return
    db.put_blob(BLOB, dict(groups=groups, seen=seen, ok=True, ts=int(time.time())))

def current():
    """Fresh derived groups, or None (no source, unusable or older than MAX_AGE)."""
    d = db.get_blob(BLOB)[0]
    if not d or not d.get("ok") or not d.get("groups") or time.time() - (d.get("ts") or 0) > MAX_AGE: return None
    return d
