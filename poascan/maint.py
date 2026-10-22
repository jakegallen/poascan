"""Staged network maintenance (minepoa.com, LabLeak post 1357). One switch, like SWAPS_LIVE.
While on, the freshness state is Upgrading instead of Lagging: the header pill hides and the home strip shows it; /upgrade explains.
Phases, from public data only: parked (checkpoint held at PARKED), then recovery (the checkpoint moved on; hosted routes reopen
in stages). Auto-clear: the mining route answers as open again (hosted.py) and the hardening notice is no longer active.
MAX_S is a safety stop that only applies while no fresh route read shows a pause."""
import os, time
from . import db, analytics as A

MAINTENANCE = os.environ.get("POASCAN_MAINTENANCE", "1") != "0"  # set the default to "0" once the hardening is over
POST_ID = 1357
POST_URL = f"https://minepoa.com/lableak/#/post/{POST_ID}"
STARTED = 1792609251          # 2026-10-21 19:00:51 UTC, when the post went up
PARKED = 24371                # checkpoint height held on purpose during the anchoring fix
WINDOW_H = (24, 72)           # expected mining downtime, hours
TTL_EPOCHS = 16               # pending grades expire after this many closes
MAX_S = 7 * 86400             # never claim maintenance for more than a week off the switch alone
PRE_SUPPLY = "1234828243.783275"   # /api/status supply at the parked checkpoint; equal after the move means balances carried over intact
NOTICE_ID = "2026-10-21-hardening" # the public system notice for this hardening (/api/notices)
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
    from . import halts as H, hosted as R
    rs = R.state("mining")
    if rs != "unknown": return "back" if rs == "open" else "paused"   # our own keyless route read answers first
    pr = (H.current() or {}).get("probe") or {}
    if "Hosted mining" in pr: return pr["Hosted mining"]   # the live probe answers directly (hosted/challenge, hosted/me)
    g = _surfaces(); st = [g[k] for k in HOSTED if k in g]
    if not st: return "paused"
    return "paused" if "paused" in st else "planned" if "planned" in st else "back"

# Only the hosted mining paths pause; self-custody miners (POST /api/submit plus /api/receipt) keep working.
def paused():
    from . import hosted as R
    return (["hosted_mining"] if hosted_state() == "paused" else []) + ([] if R.state("grading") == "open" else ["grading"]) + ([] if join_open() else ["onboarding"])
def working(): return (["onboarding"] if join_open() else []) + ["self_custody_mining", "epoch_closes", "reward_payouts", "balances", "explorer"]
PAUSED = ["hosted_mining", "grading"]; WORKING = ["onboarding", "self_custody_mining", "epoch_closes", "reward_payouts", "balances", "explorer"]   # defaults

# Copy, one place. Joining wording follows join_open(); never hard-code it elsewhere.
def join_line():
    j = join_state()
    if join_quiet(): return "Joining is paused during the upgrade. Your agent may need to retry later."
    return "Join now; your agent starts earning once it's back." if j == "open" else "Joining pauses during the upgrade too."
def strip_text():
    """Home strip: (lead, aside, tail). The aside may hide at 390px (strip_mobile() replaces the line there). Words chosen not to repeat the home screen."""
    r = recovery()
    if r["moved"]:
        lead, tail = _recovery_line()
        aside = f': new checkpoint {r["checkpoint"]:,}' + (", balances intact" if r["supply_intact"] else "") if lead == "Recovery in progress" else ""
        return (lead, aside, tail)
    h = hosted_state(); j = join_state() != "paused"
    ok = "Joining works."
    if h == "planned": return ("Hosted mining pauses soon", " for maintenance", ok if j else "Joining too.")
    if h == "back": return ("Hosted mining is back", "", ok if j else "Joining paused.")
    return ("Hosted mining paused", " for maintenance", ok) if j else ("Hosted mining and joining paused", " for maintenance", "")

def _recovery_line():
    """(lead, tail) after the checkpoint moved, from the live route states. Never a reopen time."""
    from . import hosted as R
    rt = R.current(); mo, go = rt["mining"]["state"] == "open", rt["grading"]["state"] == "open"
    rest = [k for k, v in rt.items() if k not in ("mining", "grading") and v["state"] != "open"]
    if mo and go: return ("Mining and grading reopened", "Other routes reopen in stages." if rest else "All hosted routes open.")
    if mo: return ("Mining reopened", "Grading still paused." if rt["grading"]["state"] == "paused" else "Grading reopens in stages.")
    if go: return ("Grading reopened", "Mining still paused." if rt["mining"]["state"] == "paused" else "Mining reopens in stages.")
    return ("Recovery in progress", "Mining and grading reopen in stages.")

def strip_mobile():
    """The strip at 390px: (lead, tail), short enough to fit beside the status and Details."""
    if not recovery()["moved"]:
        lead, _, tail = strip_text(); return (lead, tail)
    lead, _ = _recovery_line()
    return {"Recovery in progress": ("Recovering", "Mining still paused."), "Mining reopened": ("Mining reopened", "Grading paused."),
            "Grading reopened": ("Grading reopened", "Mining paused."), "Mining and grading reopened": ("Mining and grading reopened", "")}[lead]

def og_desc():
    r = recovery()
    if r["moved"]:
        lead, tail = _recovery_line()
        bal = ", balances intact" if r["supply_intact"] else ""
        return f'{lead}: checkpoint {r["checkpoint"]:,}{bal}. {tail} Live status on POAScan.'.replace(". .", ".").replace("  ", " ")
    hs = hosted_state(); js = join_state()
    if hs == "paused" and js == "paused": return "Hosted mining and joining paused for network upgrades, rewards paying. Live status on POAScan."
    h = {"planned": "Hosted mining pauses soon", "back": "Hosted mining is back"}.get(hs, "Hosted mining paused")
    return f"{h} for network upgrades, joining {js}, rewards paying. Live status on POAScan."

def seen(window=3600):
    """Answers and grade seals in our own feed over the last hour: what actually still lands."""
    since = int(time.time()) - window
    r = {x["type"]: x["n"] for x in db.q("SELECT type, COUNT(*) AS n FROM txs WHERE ts > ? AND type IN ('challenge','grade-sealed') GROUP BY type", (since,))}
    return dict(answers=r.get("challenge", 0), seals=r.get("grade-sealed", 0), window_s=window)

def _num(v):
    from decimal import Decimal, InvalidOperation
    try: return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError): return None

def notice():
    """The hardening notice in our /api/notices mirror: dict(id, active, issued_at, expires_at), or None with no mirror yet."""
    d = db.get_blob("notices")[0]
    if not isinstance(d, dict): return None
    act = [x for x in d.get("active") or [] if isinstance(x, dict)]
    n = next((x for x in act if x.get("id") == NOTICE_ID), None) or next((x for x in act if "harden" in str(x.get("id", "")).lower()), None)
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if isinstance(t, (int, float)) else None
    if not n: return dict(id=NOTICE_ID, active=False, issued_at=None, expires_at=None)
    exp = n.get("expires_ts")
    return dict(id=n.get("id"), active=not (isinstance(exp, (int, float)) and exp < time.time()), issued_at=iso(n.get("issued_ts")), expires_at=iso(exp))

def open_ballots():
    """Ballots still taking votes in our /api/ballots mirror, or None with no mirror yet."""
    d = db.get_blob("ballots")[0]
    if not isinstance(d, dict) or not isinstance(d.get("ballots"), list): return None
    done = ("closed", "final", "finalized", "passed", "failed", "ended", "tallied", "rejected", "adopted")
    return sum(1 for b in d["ballots"] if isinstance(b, dict) and str(b.get("status", "")).lower() not in done)

STATUS_FRESH_S = 600   # /api/status as_of within this many seconds, without minepoa's own stale flag, reads as fresh

def recovery():
    """Public recovery facts from our own mirror: checkpoint moved, new state root, supply carried over, status freshness, counters."""
    st = A.status(); cp = st.get("checkpoint_height"); sup = _num(st.get("supply")); pre = _num(PRE_SUPPLY)
    t = A._ts(st.get("as_of")); age = int(time.time() - t) if t else None
    return dict(moved=cp is not None and int(cp) > PARKED, checkpoint=int(cp) if cp is not None else None, previous_checkpoint=PARKED,
                state_root=st.get("state_root"), supply=str(st.get("supply")) if st.get("supply") is not None else None, supply_before=PRE_SUPPLY,
                supply_intact=sup is not None and sup == pre, status_as_of=st.get("as_of"), status_age_s=age,
                status_fresh=age is not None and age <= STATUS_FRESH_S and not st.get("stale"),
                txs=st.get("txs"), final=st.get("final"), epochs_closed=st.get("epochs_closed"), open_ballots=open_ballots())

def mining_back():
    """Mining officially back: our route read says the mining route is open and the hardening notice is no longer active."""
    from . import hosted as R
    n = notice()
    return R.state("mining") == "open" and not (n and n["active"])

def _paused_seen():
    from . import hosted as R
    return any(v["state"] == "paused" for v in R.current().values())

def _cleared():
    if not MAINTENANCE: return "switch_off"
    if mining_back(): return "mining_back"
    if time.time() - STARTED > MAX_S and not _paused_seen(): return "expired"
    return None

def _active(): return _cleared() is None

def state():
    from . import hosted as R
    cp = A.status().get("checkpoint_height"); cleared = _cleared(); active = cleared is None
    lj = last_join(); rec = recovery(); rt = R.current(); ck = R.checked_at(); hl = strip_text(); hm = strip_mobile()
    return dict(active=active, cleared_by=cleared, post_id=POST_ID, post_url=POST_URL, join_open=join_open(), join_state=join_state(),
                last_join_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(lj)) if lj else None, join_source=join_source(), hosted_mining=hosted_state(),
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(STARTED)),
                expected_window_h=list(WINDOW_H), paused=paused(), working=working(), self_custody="POST /api/submit plus /api/receipt keep working", pending_ttl_epochs=TTL_EPOCHS,
                parked_checkpoint=PARKED, checkpoint=cp, auto_clear="the mining route answers as open and the hardening notice is no longer active",
                halted_list_public=False, url="https://poascan.io/upgrade",
                phase="recovery" if rec["moved"] else "parked", headline=" ".join(x for x in (hl[0] + hl[1] + ".", hl[2]) if x),
                headline_short=" ".join(x for x in (hm[0] + ".", hm[1]) if x),
                hosted_routes={k: v["state"] for k, v in rt.items()}, hosted_routes_checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ck)) if ck else None,
                notice=notice(), recovery=rec, **_hs())

def _hs():
    from . import halts as H
    return H.summary()
