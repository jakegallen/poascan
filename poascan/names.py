"""Agent name availability, from POAScan's own archive only (never a minepoa.com read).

What the archive shows (checked 2026-10-22): minepoa.com does not enforce unique names. go.md and skill.md only ask for
a "unique, creative" name, and the registration labels in the archive repeat (one label is used by 876 addresses).
No two archived spellings differ only by case, so there is no sign of case folding either; POAScan compares
case-insensitively after trimming, the strictest reading. Names come from registration labels (join memos and the
Oct 19 census import) and forum author names. The queried name is never logged or stored (query strings never reach
the log; counters keep the route only)."""
import time, datetime as dt
from . import db
from .analytics import cached

TAKEN = "Taken: {name} is already an agent. Try another."

def norm(n): return (n or "").strip().casefold()

@cached("agent_names", 60)
def _index():
    s = set()
    for r in db.q("SELECT label FROM labels WHERE label IS NOT NULL AND label != ''"): s.add(norm(r["label"]))
    for r in db.q("SELECT author FROM forum_posts UNION SELECT author FROM forum_comments"):
        if r["author"]: s.add(norm(r["author"]))
    s.discard("")
    t = db.q1("SELECT MAX(ts) AS t FROM labels")
    return s, (t["t"] if t and t["t"] else None)

def _iso(ts): return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None

def taken(name):
    return norm(name) in _index()[0]

def suggest(name):
    """First free name-2, name-3 ... that still fits 32 characters."""
    names = _index()[0]
    for i in range(2, 100):
        sfx = f"-{i}"; c = name[:32 - len(sfx)] + sfx
        if norm(c) not in names: return c
    return None

def available(name):
    """(http_status, body) for GET /api/v1/agents/name-available. Validation messages are the /start ones."""
    from .start import name_error
    from . import keysafe as KS
    now = _iso(int(time.time())); synced = _iso(_index()[1])
    if KS.has_key(name or ""): name = ""
    err = name_error(name or "")
    if err:
        return 400, dict(name=(name or "")[:64], valid=False, available=None, reason=err, checked_ts=now, synced_ts=synced)
    if taken(name):
        return 200, dict(name=name, valid=True, available=False, reason=TAKEN.format(name=name), suggestion=suggest(name), checked_ts=now, synced_ts=synced)
    return 200, dict(name=name, valid=True, available=True, reason="", checked_ts=now, synced_ts=synced)


# ---- Join popup prototype: did this public poa1 address join? POAScan's own index only (no minepoa.com read). Anything that is
# not a poa1 address (a key above all) is refused without being echoed, stored or logged.
import re as _re
ADDR = _re.compile(r"poa1[1-9A-HJ-NP-Za-km-z]{30,60}")
def joined(a):
    from . import keysafe as KS
    now = _iso(int(time.time()))
    if not a or KS.has_key(a) or not ADDR.fullmatch(a):
        return 400, dict(found=None, reason="Not a poa1 address.", checked_ts=now)
    r = db.q1("SELECT MIN(ts) AS t FROM txs WHERE type='join' AND from_addr=?", (a,))
    l = db.q1("SELECT ts FROM labels WHERE addr=?", (a,))
    t = (r and r["t"]) or (l and l["ts"]) or None
    s = db.q1("SELECT MAX(ts) AS t FROM txs")
    return 200, dict(address=a, found=bool(t), joined_ts=_iso(t), checked_ts=now, synced_ts=_iso(s["t"] if s and s["t"] else None))
