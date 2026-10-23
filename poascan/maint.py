"""Staged network maintenance (minepoa.com, LabLeak post 1357). One switch, like SWAPS_LIVE.
While on, the freshness state is Upgrading instead of Lagging: the header pill hides and the home strip shows it; /upgrade explains.
Phases, from public data only: parked (checkpoint held at PARKED), then recovery (the checkpoint moved on; hosted routes reopen
in stages). Auto-clear: the mining route answers as open again (hosted.py) and the hardening notice is no longer active.
MAX_S is a safety stop that only applies while no fresh route read shows a pause."""
import os, re, time
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
    if mining_back(): return "back"     # the official signal, kept in the database; only two clear halted reads after it undo it
    rs = R.state("mining")
    if rs != "unknown": return "paused"   # a responding route is not back until it is official
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
        lead, tail = _recovery_line(); fr = back_phrase()
        if fr: aside = f": {fr}"
        else: aside = f': new checkpoint {r["checkpoint"]:,}' + (", balances intact" if r["supply_intact"] else "") if lead == "Recovery in progress" else ""
        return (lead, aside, tail)
    h = hosted_state(); j = join_state() != "paused"
    ok = "Joining works."
    if h == "planned": return ("Hosted mining pauses soon", " for maintenance", ok if j else "Joining too.")
    if h == "back": return ("Hosted mining is back", "", ok if j else "Joining paused.")
    return ("Hosted mining paused", " for maintenance", ok) if j else ("Hosted mining and joining paused", " for maintenance", "")

def back_phrase():
    """How much of the hosted surface is back, from our own route reads. Words, never a count we cannot back:
    no fresh read at all says 'some endpoints are back' (public word that they return in stages); none open says nothing."""
    from . import hosted as R
    k, n = R.counts(); total = len(R.ROUTES)
    if R.slow(): return "some endpoints are slow"   # reads timing out: say so, never a fraction that counts them either way
    if n == 0: return "some endpoints are back"
    if k == 0: return ""
    f = k / total
    if k == total: return "all hosted routes are back"
    if f < 0.3: return "some endpoints are back"
    if f < 0.45: return "about a third of endpoints are back"
    if f < 0.6: return "about half of endpoints are back"
    if f < 0.8: return "about two thirds of endpoints are back"
    return "most endpoints are back"

def stamp_ts():
    """When the data behind the upgrade lines was read: our last route read, else the /api/status as_of."""
    from . import hosted as R
    ck = R.checked_at()
    if ck: return int(ck)
    t = A._ts(recovery()["status_as_of"]); return t

def _names(ks): return " and ".join(ks)

def _recovery_line():
    """(lead, tail) after the checkpoint moved. A route read alone says 'responding'; 'reopened' needs official() too. Never a reopen time."""
    from . import hosted as R
    rt = R.current(); of = official()
    if paused_again():
        return ("Mining paused again", "Grading still paused." if rt["grading"]["state"] == "paused" else "Grading reopens in stages.")
    mof = mining_back()
    mo, go = mof or rt["mining"]["state"] == "open", rt["grading"]["state"] == "open"
    gof = go and of["routes"]
    rest = [k for k, v in rt.items() if k not in ("mining", "grading") and v["state"] != "open"]
    if mo and go:
        if mof and gof: return ("Mining and grading reopened", "Other routes reopen in stages." if rest else "All hosted routes open.")
        return ("Mining and grading endpoints responding", "Other routes reopen in stages." if rest else "All hosted routes responding.")
    if mo:
        return ("Mining reopened" if mof else "Mining endpoint responding", "Grading still paused." if rt["grading"]["state"] == "paused" else "Grading reopens in stages.")
    if go:
        return ("Grading reopened" if gof else "Grading endpoint responding", "Mining still paused." if rt["mining"]["state"] == "paused" else "Mining reopens in stages.")
    return ("Recovery in progress", "Mining and grading reopen in stages.")

MOBILE = {"Recovery in progress": ("Recovering", "Mining still paused."), "Mining reopened": ("Mining reopened", "Grading paused."),
          "Mining paused again": ("Mining paused again", "Grading paused."),
          "Mining endpoint responding": ("Mining endpoint responding", "Grading paused."), "Grading reopened": ("Grading reopened", "Mining paused."),
          "Grading endpoint responding": ("Grading endpoint responding", "Mining paused."), "Mining and grading reopened": ("Mining and grading reopened", ""),
          "Mining and grading endpoints responding": ("Mining and grading responding", "")}

def strip_mobile():
    """The strip at 390px: (lead, tail), short enough to fit beside the status and Details."""
    if not recovery()["moved"]:
        lead, _, tail = strip_text(); return (lead, tail)
    return MOBILE[_recovery_line()[0]]

# ---- official signal: only this turns 'responding' into 'reopened' and ends maintenance
# 1. the hardening notice is gone from our /api/notices mirror (removed, or replaced by a notice that is not about the hardening);
# 2. the author of pinned LabLeak post 1357 says mining is back, in the post itself or in a comment on it. Read from POAScan's
#    existing forum mirror (public, keyless, refreshed by the forum job every 30 minutes); no extra request. Matched conservatively:
#    a sentence naming mining with back, reopened, re-enabled, restored or resumed, and no hedge word (not, soon, will, until, once, if...).
OFFICIAL_RX = re.compile(r"\b(?:hosted\s+)?mining(?:\s+(?:and|&)\s+grading)?(?:\s+(?:paths?|endpoints?|routes?))?\s+(?:is|are|has|have)\s+(?:now\s+)?(?:been\s+)?"
                         r"(?:back|reopened|re-?enabled|restored|resumed|live again)\b", re.I)
HEDGE_RX = re.compile(r"\b(?:not|no longer|soon|will|until|once|if|when|expect|plan|should|may|might|before|partly|partially|mostly)\b|n't", re.I)

def _says_back(text):
    for sent in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if OFFICIAL_RX.search(sent) and not HEDGE_RX.search(sent): return True
    return False

def official_post():
    """{'at': created/edited time} when the post 1357 author says mining is back, else None."""
    try:
        p = db.q1("SELECT author_public_id AS a, body, edited_at FROM forum_posts WHERE id=?", (POST_ID,))
        if not p or not p["a"]: return None
        if _says_back(p["body"]): return dict(at=p["edited_at"] or None, where="post")
        for c in db.q("SELECT body, created_at, edited_at FROM forum_comments WHERE post_id=? AND author_public_id=? ORDER BY created_at DESC LIMIT 50", (POST_ID, p["a"])):
            if _says_back(c["body"]): return dict(at=c["edited_at"] or c["created_at"], where="comment")
    except Exception: return None
    return None

# Operator comments on post 1357 that /upgrade Details cites, read only from our forum mirror (no extra request).
CITES = [(3121, "All clear"), (3123, "Grading clarification")]
def citations():
    """[(label, comment id, created_at as stored)] for CITES that our mirror holds, written by the post 1357 author."""
    try:
        p = db.q1("SELECT author_public_id AS a FROM forum_posts WHERE id=?", (POST_ID,))
        if not p or not p["a"]: return []
        out = []
        for cid, lab in CITES:
            c = db.q1("SELECT created_at FROM forum_comments WHERE id=? AND post_id=? AND author_public_id=?", (cid, POST_ID, p["a"]))
            if c and c["created_at"]: out.append((lab, cid, str(c["created_at"])))
        return out
    except Exception: return []

def official():
    """mining: official word that mining is back. routes: official word for every hosted route (the notice is gone).
    source: notice, post, or None."""
    n = notice(); gone = n is not None and not n["active"]
    post = None if gone else official_post()
    live = dict(mining=gone or post is not None, routes=gone, source="notice" if gone else "post" if post else None, post=post)
    return _persist_official(live)

OFFICIAL_BLOB = "official_signal"
def _persist_official(live):
    """The official word, kept in the database: once seen it stays, whatever a later read of the notice or forum mirror says
    (a mirror gap, a restart or a deploy never clears it). mining_at / routes_at: when POAScan first saw it."""
    d = db.get_blob(OFFICIAL_BLOB)[0] or {}; now = int(time.time()); ch = False
    if live["mining"] and not d.get("mining_at"): d.update(mining_at=now, source=live["source"]); ch = True
    if live["routes"] and not d.get("routes_at"): d.update(routes_at=now); ch = True
    if ch:
        try: db.put_blob(OFFICIAL_BLOB, d)
        except Exception: pass
    return dict(mining=bool(live["mining"] or d.get("mining_at")), routes=bool(live["routes"] or d.get("routes_at")),
                source=live["source"] or d.get("source"), post=live["post"], mining_at=d.get("mining_at"))

def route_display():
    """Route list states: open only when official, responding when our read says open but nothing official yet,
    slow when the newest read got no answer (timeout or network error; never called paused or offline)."""
    from . import hosted as R
    of = official(); out = {}
    for k, v in R.current().items():
        st = v["state"]
        if v["slow"]: st = "slow"
        elif k == "mining" and mining_back(): st = "open"   # officially back; an unknown or single halted read does not undo it
        elif st == "open": st = "open" if of["routes"] else "responding"
        out[k] = st
    return out

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

def _last_status(field, window=86400):
    """Newest value of one /api/status field in our own status snapshots (last day), or None."""
    try:
        r = db.q1(f"SELECT json_extract(json, '$.{field}') AS v FROM snaps WHERE kind='status' AND ts > ? AND json_extract(json, '$.{field}') IS NOT NULL "
                  "ORDER BY ts DESC LIMIT 1", (int(time.time()) - window,))
        return r["v"] if r else None
    except Exception: return None

STATUS_FRESH_S = 600   # /api/status as_of within this many seconds reads as fresh (A.LAG_NODE_S: minepoa's own stale flag counts only past this age)

def recovery():
    """Public recovery facts from our own mirror: checkpoint moved, new state root, supply carried over, status freshness, counters."""
    st = dict(A.status()); sup = _num(st.get("supply")); pre = _num(PRE_SUPPLY)
    for k in ("checkpoint_height", "state_root", "as_of"):   # /api/status now and then answers without these: use our newest read that had them
        if st.get(k) is None: st[k] = _last_status(k)
    cp = st.get("checkpoint_height")
    if cp is None: cp = A.networks().get("checkpoint_height")
    t = A._ts(st.get("as_of")); age = int(time.time() - t) if t else None
    return dict(moved=cp is not None and int(cp) > PARKED, checkpoint=int(cp) if cp is not None else None, previous_checkpoint=PARKED,
                state_root=st.get("state_root"), supply=str(st.get("supply")) if st.get("supply") is not None else None, supply_before=PRE_SUPPLY,
                supply_intact=sup is not None and sup == pre, status_as_of=st.get("as_of"), status_age_s=age,
                status_fresh=age is not None and age <= STATUS_FRESH_S, status_stale_flag=bool(st.get("stale")),   # same rule as the pill: a stale flag on a read under 10 minutes old is not lag
                txs=st.get("txs"), final=st.get("final"), epochs_closed=st.get("epochs_closed"), open_ballots=open_ballots())

PAUSED_AGAIN_READS = 2   # clear halted reads in a row on the mining route, after the official time, before "Mining paused again"

def paused_again():
    """True only after PAUSED_AGAIN_READS consecutive clear halted (503) reads of the mining route that started after the official
    signal. Unknown reads (timeouts, network errors, odd codes) never count."""
    from . import hosted as R
    of = official(); m = R.current()["mining"]
    return bool(of["mining"] and m["state"] == "paused" and m["streak"] >= PAUSED_AGAIN_READS and (m["since"] or 0) >= (of.get("mining_at") or 0))

def mining_back():
    """Mining back: the official signal (persisted) and no clear sign since that mining paused again."""
    return bool(official()["mining"]) and not paused_again()

def _paused_seen():
    from . import hosted as R
    return any(v["state"] == "paused" for v in R.current().values())

BACK_GRACE_S = 6 * 3600   # after the official signal the strip says "Mining reopened" this long, then maintenance ends

# 1.26.17 cleared the stored time at 00:16:36Z when a stale route read turned 'unknown'. The value it held, restored once.
BACK_RESTORE_AT = 1792712749   # 2026-10-22T23:45:49Z, as served by /api/v1/status before the bug
BUG_CLEARED_TS = 1792714596    # the exact time the bug wrote the empty blob; the restore applies to that blob only

def back_since():
    """When mining_back() first held, kept in the database. Never cleared by a route read; only a clear 'paused again'
    (two halted reads in a row after the official time) ends it, and the next official return starts a new one."""
    raw, bts = db.get_blob("mining_back"); d = raw or {}
    if not mining_back():
        if d.get("at") and paused_again(): db.put_blob("mining_back", {"ended": int(time.time()), "prev": d.get("at")})
        return d.get("at") if not paused_again() else None
    if not d.get("at"):
        of = official(); t = int(time.time())
        if raw == {} and bts == BUG_CLEARED_TS and of.get("source") == "post": t = BACK_RESTORE_AT   # the empty blob the bug left
        d = {"at": t}; db.put_blob("mining_back", d)
    return d["at"]

def _cleared():
    if not MAINTENANCE: return "switch_off"
    t = back_since()
    if t and time.time() - t > BACK_GRACE_S: return "mining_back"
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
                parked_checkpoint=PARKED, checkpoint=cp, auto_clear="6 hours after the mining route answers with an official signal that mining is back: the hardening notice is gone, or the author of LabLeak post 1357 says so",
                halted_list_public=False, url="https://poascan.io/upgrade",
                phase="recovery" if rec["moved"] else "parked", headline=" ".join(x for x in (hl[0] + hl[1] + ".", hl[2]) if x),
                headline_short=" ".join(x for x in (hm[0] + ".", hm[1]) if x), updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp_ts())) if stamp_ts() else None,
                hosted_routes={k: v["state"] for k, v in rt.items()}, hosted_routes_display=route_display(),
                official={k: v for k, v in official().items() if k != "post"}, mining_back_at=(lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None)(back_since()), hosted_routes_checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ck)) if ck else None,
                notice=notice(), recovery=rec, **_hs())

def _hs():
    from . import halts as H
    return H.summary()
