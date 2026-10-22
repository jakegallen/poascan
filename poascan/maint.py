"""Staged network maintenance (minepoa.com, LabLeak post 1357). One switch, like SWAPS_LIVE.
While on, the header pill reads Upgrading instead of Lagging for the parked checkpoint, and /status#upgrade explains.
Auto-clear: minepoa.com exposes no public list of halted surfaces, so the one public signal is the checkpoint
leaving its parked height (the team said it resumes when the anchoring fix lands). MAX_S is a safety stop."""
import os, time
from . import db, analytics as A

MAINTENANCE = os.environ.get("POASCAN_MAINTENANCE", "1") != "0"  # set the default to "0" once the hardening is over
POST_ID = 1357
POST_URL = f"https://minepoa.com/lableak/#/post/{POST_ID}"
STARTED = 1792609251          # 2026-10-21 19:00:51 UTC, when the post went up
PARKED = 24371                # checkpoint height held on purpose during the anchoring fix
WINDOW_H = (24, 72)           # expected mining downtime, hours
TTL_EPOCHS = 16               # pending grades expire after this many closes
MAX_S = 7 * 86400             # never claim maintenance for more than a week off one switch
# Joining (register, join-connected, /j/<token>, link-auto, link-signed, adopt) may halt too, on the team's go-ahead.
# Automatic from the halt tracker's Joining group (halts.py); POASCAN_JOIN_OPEN=0 or 1 overrides; with neither, open.
JOIN_ENV = os.environ.get("POASCAN_JOIN_OPEN") or None
HOSTED = ("Hosted mining", "Answers", "Challenges")   # the groups behind "hosted mining" in public copy

def _surfaces():
    from . import halts as H
    d = H.current(); return (d or {}).get("groups") or {}

def join_open():
    if JOIN_ENV is not None: return JOIN_ENV != "0"
    return _surfaces().get("Joining") != "paused"

JOIN_QUIET_S = 90 * 60       # no new join on the ledger for this long during maintenance reads as delayed

def last_join():
    r = db.q1("SELECT MAX(ts) AS t FROM txs WHERE type='join'"); return r["t"] if r else None

def _feed_fresh():
    """Our ledger feed is current, so a missing join is real and not a gap in our own reads."""
    r = db.q1("SELECT last_ok FROM fetch_log WHERE endpoint='/api/explorer/txs'")
    return bool(r and r["last_ok"] and time.time() - r["last_ok"] < 900)

def join_quiet():
    """Derived pause: maintenance is on, our feed is current and no join has landed for JOIN_QUIET_S.
    A new join flips it back. Only applies while the tracker and the manual switch say joining is open."""
    if not join_open() or JOIN_ENV is not None or not _active(): return False
    t = last_join()
    return bool(t and _feed_fresh() and time.time() - t > JOIN_QUIET_S)

def join_state():
    """open or paused. Paused comes from the tracker, the manual switch, or join_quiet()."""
    return "paused" if not join_open() or join_quiet() else "open"

def join_source(): return "manual" if JOIN_ENV is not None else ("tracker" if "Joining" in _surfaces() else "default")   # the probe never covers joining

def hosted_state():
    """paused, planned or back for hosted mining. Without tracker data the manual switch means paused."""
    from . import halts as H
    pr = (H.current() or {}).get("probe") or {}
    if "Hosted mining" in pr: return pr["Hosted mining"]   # the live probe answers directly (hosted/challenge, hosted/me)
    g = _surfaces(); st = [g[k] for k in HOSTED if k in g]
    if not st: return "paused"
    return "paused" if "paused" in st else "planned" if "planned" in st else "back"

# Only the hosted mining paths pause; self-custody miners (POST /api/submit plus /api/receipt) keep working.
def paused():
    return (["hosted_mining"] if hosted_state() == "paused" else []) + ["grading"] + ([] if join_open() else ["onboarding"])
def working(): return (["onboarding"] if join_open() else []) + ["self_custody_mining", "epoch_closes", "reward_payouts", "balances", "explorer"]
PAUSED = ["hosted_mining", "grading"]; WORKING = ["onboarding", "self_custody_mining", "epoch_closes", "reward_payouts", "balances", "explorer"]   # defaults

# Copy, one place. Joining wording follows join_open(); never hard-code it elsewhere.
def join_line():
    j = join_state()
    if join_quiet(): return "Joining is paused during the upgrade. Your agent may need to retry later."
    return "Join now; your agent starts earning once it's back." if j == "open" else "Joining pauses during the upgrade too."
def strip_text():
    """Home strip: (lead, aside, tail). The aside may hide at 390px. Words chosen not to repeat the home screen."""
    h = hosted_state(); j = join_state() != "paused"
    ok = "Joining works."
    if h == "planned": return ("Hosted mining pauses soon", " for maintenance", ok if j else "Joining too.")
    if h == "back": return ("Hosted mining is back", "", ok if j else "Joining paused.")
    return ("Hosted mining paused", " for maintenance", ok) if j else ("Hosted mining and joining paused", " for maintenance", "")
def og_desc():
    hs = hosted_state(); js = join_state()
    if hs == "paused" and js == "paused": return "Hosted mining and joining paused for network upgrades, rewards paying. Live status on POAScan."
    h = {"planned": "Hosted mining pauses soon", "back": "Hosted mining is back"}.get(hs, "Hosted mining paused")
    return f"{h} for network upgrades, joining {js}, rewards paying. Live status on POAScan."

def seen(window=3600):
    """Answers and grade seals in our own feed over the last hour: what actually still lands."""
    since = int(time.time()) - window
    r = {x["type"]: x["n"] for x in db.q("SELECT type, COUNT(*) AS n FROM txs WHERE ts > ? AND type IN ('challenge','grade-sealed') GROUP BY type", (since,))}
    return dict(answers=r.get("challenge", 0), seals=r.get("grade-sealed", 0), window_s=window)

def _active():
    cp = A.status().get("checkpoint_height")
    return MAINTENANCE and not (cp is not None and int(cp) > PARKED) and not (time.time() - STARTED > MAX_S)

def state():
    now = time.time(); cp = A.status().get("checkpoint_height")
    moved = cp is not None and int(cp) > PARKED
    expired = now - STARTED > MAX_S
    active = MAINTENANCE and not moved and not expired
    lj = last_join()
    cleared = None if active else ("switch_off" if not MAINTENANCE else "checkpoint_moved" if moved else "expired")
    return dict(active=active, cleared_by=cleared, post_id=POST_ID, post_url=POST_URL, join_open=join_open(), join_state=join_state(),
                last_join_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(lj)) if lj else None, join_source=join_source(), hosted_mining=hosted_state(),
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(STARTED)),
                expected_window_h=list(WINDOW_H), paused=paused(), working=working(), self_custody="POST /api/submit plus /api/receipt keep working", pending_ttl_epochs=TTL_EPOCHS,
                parked_checkpoint=PARKED, checkpoint=cp, auto_clear="checkpoint height above parked_checkpoint",
                halted_list_public=False, url="https://poascan.io/upgrade", **_hs())

def _hs():
    from . import halts as H
    return H.summary()
