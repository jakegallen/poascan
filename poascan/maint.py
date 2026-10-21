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
def join_line(): return "Join now; your agent starts earning once it's back." if join_open() else "Joining pauses during the upgrade too."
def strip_text():
    """Home strip: (lead, aside, tail). The aside may hide at 390px. Words chosen not to repeat the home screen."""
    h = hosted_state(); j = join_open()
    if h == "planned": return ("Hosted mining pauses soon", " for maintenance", "Joining works." if j else "Joining too.")
    if h == "back": return ("Hosted mining is back", "", "Joining works." if j else "Joining paused.")
    return ("Hosted mining paused", " for maintenance", "Joining works.") if j else ("Hosted mining and joining paused", " for maintenance", "")
def og_desc():
    h = {"planned": "Hosted mining pauses soon", "back": "Hosted mining is back"}.get(hosted_state(), "Hosted mining paused")
    return f"{h} for network upgrades, joining {'open' if join_open() else 'paused'}, rewards paying. Live status on POAScan."

def seen(window=3600):
    """Answers and grade seals in our own feed over the last hour: what actually still lands."""
    since = int(time.time()) - window
    r = {x["type"]: x["n"] for x in db.q("SELECT type, COUNT(*) AS n FROM txs WHERE ts > ? AND type IN ('challenge','grade-sealed') GROUP BY type", (since,))}
    return dict(answers=r.get("challenge", 0), seals=r.get("grade-sealed", 0), window_s=window)

def state():
    now = time.time(); cp = A.status().get("checkpoint_height")
    moved = cp is not None and int(cp) > PARKED
    expired = now - STARTED > MAX_S
    active = MAINTENANCE and not moved and not expired
    cleared = None if active else ("switch_off" if not MAINTENANCE else "checkpoint_moved" if moved else "expired")
    return dict(active=active, cleared_by=cleared, post_id=POST_ID, post_url=POST_URL, join_open=join_open(), join_source=join_source(), hosted_mining=hosted_state(),
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(STARTED)),
                expected_window_h=list(WINDOW_H), paused=paused(), working=working(), self_custody="POST /api/submit plus /api/receipt keep working", pending_ttl_epochs=TTL_EPOCHS,
                parked_checkpoint=PARKED, checkpoint=cp, auto_clear="checkpoint height above parked_checkpoint",
                halted_list_public=False, url="https://poascan.io/upgrade", **_hs())

def _hs():
    from . import halts as H
    return H.summary()
