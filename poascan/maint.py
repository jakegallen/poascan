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
PAUSED = ["mining", "grading"]
WORKING = ["onboarding", "epoch_closes", "reward_payouts", "balances", "explorer"]

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
    return dict(active=active, cleared_by=cleared, post_id=POST_ID, post_url=POST_URL,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(STARTED)),
                expected_window_h=list(WINDOW_H), paused=PAUSED, working=WORKING, pending_ttl_epochs=TTL_EPOCHS,
                parked_checkpoint=PARKED, checkpoint=cp, auto_clear="checkpoint height above parked_checkpoint",
                halted_list_public=False, url="https://poascan.io/status#upgrade")
