"""Staged network maintenance (minepoa.com, LabLeak post 1357). One switch, like SWAPS_LIVE.
While on, the freshness state is Upgrading instead of Lagging: the header pill hides and the home strip shows it; /upgrade explains.
Phases, from public data only: parked (checkpoint held at PARKED), then recovery (the checkpoint moved on; hosted routes reopen
in stages). Auto-clear: the mining route answers as open again (hosted.py) and the hardening notice is no longer active.
MAX_S is a safety stop that only applies while no fresh route read shows a pause."""
import os, re, time
from . import db, analytics as A

MAINTENANCE = os.environ.get("POASCAN_MAINTENANCE", "1") != "0"  # the switch; with it on, the official completion notice (complete()) ends maintenance by itself
POST_ID = 1357
POST_URL = f"https://minepoa.com/lableak/#/post/{POST_ID}"
STARTED = 1792609251          # 2026-10-21 19:00:51 UTC, when the post went up
PARKED = 24371                # checkpoint height held on purpose during the anchoring fix
WINDOW_H = (24, 72)           # expected mining downtime, hours
TTL_EPOCHS = 16               # pending grades expire after this many closes
MAX_S = 7 * 86400             # never claim maintenance for more than a week off the switch alone
PRE_SUPPLY = "1234828243.783275"   # /api/status supply at the parked checkpoint; equal after the move means balances carried over intact
NOTICE_ID = "2026-10-21-hardening" # the public system notice for this hardening (/api/notices)
# Joining (join-pow, register, join-connected, /j/<token>, link-auto, link-signed, adopt) may halt too, on the team's go-ahead.
# Automatic from the halt tracker's Joining group (halts.py); POASCAN_JOIN_OPEN=0 or 1 overrides; with neither, open.
JOIN_ENV = os.environ.get("POASCAN_JOIN_OPEN") or None
HOSTED = ("Hosted mining", "Answers", "Challenges")   # the groups behind "hosted mining" in public copy

def _surfaces():
    from . import halts as H
    d = H.current(); return _after_complete((d or {}).get("groups") or {}, (d or {}).get("probe") or {})

def _after_complete(groups, probe):
    """Once the upgrade is officially complete, tracker states read back; only a live probe read of a halted route stays paused."""
    if not complete(): return groups
    gs = {"open": "back", "unconfirmed": "unconfirmed", "halted": "paused"}[grading_state()["state"]] if "Grading" in groups else None
    return {g: ("paused" if probe.get(g) == "paused" else gs if g == "Grading" else "back") for g in groups}

def join_open():
    if JOIN_ENV is not None: return JOIN_ENV != "0"
    return _surfaces().get("Joining") != "paused"

JOIN_QUIET_S = 90 * 60       # no new join on the ledger for this long during maintenance reads as delayed

def last_join():
    r = db.q1("SELECT MAX(ts) AS t FROM txs WHERE type='join'"); return r["t"] if r else None

def _feed_fresh():
    """Our ledger feed is current, so a missing join is real and not a gap in our own reads."""
    r = db.q1("SELECT MAX(last_ok) AS last_ok FROM fetch_log WHERE endpoint IN ('/api/txs', '/api/explorer/txs')")   # 1.26.98: /api/txs is the tx list
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
    if complete() or mining_back(): return "back"     # the official signal, kept in the database; only two clear halted reads after it undo it
    rs = R.state("mining")
    if rs != "unknown": return "paused"   # a responding route is not back until it is official
    pr = (H.current() or {}).get("probe") or {}
    if "Hosted mining" in pr: return pr["Hosted mining"]   # the live probe answers directly (hosted/challenge, hosted/me)
    g = _surfaces(); st = [g[k] for k in HOSTED if k in g]
    if not st: return "paused"
    return "paused" if "paused" in st else "planned" if "planned" in st else "back"

# Payouts, split the way minepoa's notices split them (2026-10-22-grading-halted: "attestation earnings fully LIVE",
# "grading + challenge-pool payouts paused until further notice"; 2026-10-22-restored: "grading + pool payouts resume after ...").
POOL_PAUSED_RX = re.compile(r"pool payouts?\b[^.]*\b(?:paused|halted|resume after)", re.I)
ATTEST_PAUSED_RX = re.compile(r"attestation earnings?\b[^.]*\b(?:paused|halted)", re.I)

def _active_notices():
    """Active, unexpired notices in our /api/notices mirror, minus those the grading-resumed notice superseded."""
    d = db.get_blob("notices")[0]
    if not isinstance(d, dict): return []
    now = time.time()
    return [x for x in d.get("active") or [] if isinstance(x, dict) and not (isinstance(x.get("expires_ts"), (int, float)) and x["expires_ts"] < now)
            and not superseded(x)]

# ---- upgrade complete: the official end, from the public notice list only (no extra request).
# 2026-10-23-grading-resumed: "GRADING IS BACK, all paths OPEN (...). Hardening pause over, resume normal cadence." (on-ledger tx a241efae).
# A notice that says grading is back AND that the hardening/upgrade pause is over ends the upgrade. Kept in the database once seen,
# so it holds after that notice expires. Notices issued before it (the hardening, restored and grading-halted notices) are superseded:
# they stop counting as active even while still listed. A newer notice that halts something again counts as usual.
GRADING_BACK_RX = re.compile(r"\bgrading\b[^.]{0,24}?\b(?:is\s+back|back\s+online|resumed|reopened|re-?enabled|restored)\b", re.I)
OVER_RX = re.compile(r"\b(?:hardening|upgrade|maintenance)\b[^.]{0,24}?\b(?:over|complete[d]?|done|ended|finished|closed)\b", re.I)
COMPLETE_BLOB = "upgrade_complete"

def _says_complete(msg): return bool(GRADING_BACK_RX.search(msg or "") and OVER_RX.search(msg or ""))

def complete():
    """dict(at, notice_id, txid) once an official notice says grading is back and the hardening is over, else None.
    at is the notice's issued_ts (the official time). Persisted on first sight."""
    d = db.get_blob(COMPLETE_BLOB)[0]
    if isinstance(d, dict) and d.get("at"): return d
    n = db.get_blob("notices")[0]
    if not isinstance(n, dict): return None
    now = time.time()
    hit = [x for x in n.get("active") or [] if isinstance(x, dict) and isinstance(x.get("issued_ts"), (int, float))
           and not (isinstance(x.get("expires_ts"), (int, float)) and x["expires_ts"] < now) and _says_complete(str(x.get("msg") or ""))]
    if not hit: return None
    x = min(hit, key=lambda x: x["issued_ts"])
    d = dict(at=int(x["issued_ts"]), notice_id=x.get("id"), txid=x.get("txid"), seen_at=int(now))
    try: db.put_blob(COMPLETE_BLOB, d)
    except Exception: pass
    return d

def superseded(x):
    """True for a notice issued at or before the official completion notice (and not that notice itself)."""
    c = complete()
    if not c or not isinstance(x, dict) or x.get("id") == c.get("notice_id"): return False
    t = x.get("issued_ts")
    return isinstance(t, (int, float)) and t <= c["at"]

# ---- grading truth (1.26.58): the completion notice alone never shows grading as open. After it, grading is
# open only once POAScan's archive shows grade seals landing; an observed halt (the live probe's Grading group,
# a halted read of the grading route after the notice) or a newer official halt notice reads halted.
# No new request: the archive, the probe blob and the notices mirror are already kept.
GRADE_RECENT_S = 1800   # seals landed this recently (tx time) count as confirmation
GRADE_MIN_SEALS = 2     # at least this many in that window
GRADING_LABEL = {"open": "Grading open", "unconfirmed": "Grading: notice says open, not yet confirmed", "halted": "Grading halted"}
GRADING_SHORT = {"open": "Grading open.", "unconfirmed": "Grading not yet confirmed.", "halted": "Grading halted."}

def _observed_halt(c):
    """'probe' or 'route' when a live read since the completion notice saw grading halted, else None."""
    from . import pulse as P, hosted as R
    pr = P.current() or {}
    if (pr.get("groups") or {}).get("Grading") == "paused" and (pr.get("ts") or 0) >= c["at"]: return "probe"
    g = R.current().get("grading") or {}
    if g.get("state") == "paused" and (g.get("checked") or 0) >= c["at"]: return "route"
    return None

GRADING_MEMO_S = float(os.environ.get("POASCAN_GRADING_MEMO_S", "20"))   # one page or meta build asks up to ~15 times
_GMEMO = [0.0, None, -1]   # time, value, db.GEN at compute

def grading_state(now=None):
    """grading state, memoized when called without now, for GRADING_MEMO_S seconds and until the next db write (1.26.81: two COUNT DISTINCT scans over
    the grade-sealed rows, blob decodes and the probe read ran up to ~15 times per page, 38% of live CPU)."""
    if now is not None or GRADING_MEMO_S <= 0: return _grading_state(now)
    t = time.time(); m = _GMEMO; g = db.GEN[0]
    if m[1] is not None and m[2] == g and 0 <= t - m[0] < GRADING_MEMO_S: return dict(m[1])
    d = _grading_state(); m[0], m[1], m[2] = t, d, g
    return dict(d)

def grading_memo_clear(): _GMEMO[1] = None   # for a state change that is not a db write (tests patch hosted.state)

def _grading_state(now=None):
    """dict(state=open|unconfirmed|halted, basis, ...) with the evidence behind it. Before the completion notice the
    pre-1.26.58 rule stands (open when the grading route answers as open, else halted)."""
    from . import hosted as R
    now = int(now or time.time()); c = complete(); halt = A.grading_halt(now)
    ev = dict(notice_id=c.get("notice_id") if c else None, notice_at=c["at"] if c else None, halt_notice=halt,
              window_s=GRADE_RECENT_S, min_seals=GRADE_MIN_SEALS, feed_fresh=_feed_fresh())
    if c:
        r = db.q1("SELECT COUNT(*) AS n, COUNT(DISTINCT from_addr) AS g, MAX(ts) AS t FROM txs WHERE type='grade-sealed' AND ts >= ?", (c["at"],)) or {}
        rr = db.q1("SELECT COUNT(*) AS n, COUNT(DISTINCT from_addr) AS g FROM txs WHERE type='grade-sealed' AND ts >= ? AND ts > ?", (c["at"], now - GRADE_RECENT_S)) or {}
        ev.update(seals_since_notice=r["n"] or 0, sealers_since_notice=r["g"] or 0, last_seal_at=r["t"], seals_recent=rr["n"] or 0, sealers_recent=rr["g"] or 0)
    if halt: return dict(ev, state="halted", basis="notice")
    if not c:
        rs = R.state("grading")   # unknown before any clear read: not open, but nothing observed halted either (basis none)
        return dict(ev, state="open" if rs == "open" else "halted", basis="route" if rs != "unknown" else "none")
    ob = _observed_halt(c)
    if ob: return dict(ev, state="halted", basis=ob)
    if ev["feed_fresh"] and ev["seals_recent"] >= GRADE_MIN_SEALS: return dict(ev, state="open", basis="notice+seals")
    return dict(ev, state="unconfirmed", basis="notice")

def grading_open():
    """Grading is open: confirmed by grade seals after the completion notice (grading_state), or, before it, the route answers as open."""
    return grading_state()["state"] == "open"

def pool_payouts():
    """paused or live for challenge-pool payouts: paused while an active notice says so, or while grading is not open
    (answers only earn from the pool once graded, so with grading paused the pool can't pay them)."""
    from . import hosted as R
    if any(POOL_PAUSED_RX.search(str(x.get("msg") or "")) for x in _active_notices()): return "paused"
    if complete(): return "paused" if grading_state()["state"] == "halted" else "live"   # pool payouts follow the notice unless grading is seen halted
    return "live" if grading_open() else "paused"

def attestation_earnings():
    """live unless an active notice says attestation earnings are paused."""
    return "paused" if any(ATTEST_PAUSED_RX.search(str(x.get("msg") or "")) for x in _active_notices()) else "live"

# Only the hosted mining paths pause; self-custody miners (POST /api/submit plus /api/receipt) keep working.
def paused():
    from . import hosted as R
    return ((["hosted_mining"] if hosted_state() == "paused" else []) + (["grading"] if grading_state()["state"] == "halted" else []) + ([] if join_open() else ["onboarding"])
            + (["challenge_pool_payouts"] if pool_payouts() == "paused" else []) + (["attestation_earnings"] if attestation_earnings() == "paused" else []))
def working():
    return ((["onboarding"] if join_open() else []) + (["hosted_mining"] if hosted_state() == "back" else []) + (["grading"] if grading_open() else []) + ["self_custody_mining", "epoch_closes"] + (["attestation_earnings"] if attestation_earnings() == "live" else [])
            + (["challenge_pool_payouts"] if pool_payouts() == "live" else []) + ["balances", "explorer"])
def unconfirmed(): return ["grading"] if grading_state()["state"] == "unconfirmed" else []   # the notice says open, the archive shows no recent seals
PAUSED = ["hosted_mining", "grading", "challenge_pool_payouts"]; WORKING = ["onboarding", "self_custody_mining", "epoch_closes", "attestation_earnings", "balances", "explorer"]   # defaults

def payouts_phrase():
    """og/strip wording for payouts, from the same two states."""
    a, p = attestation_earnings(), pool_payouts()
    return "rewards paying" if a == p == "live" else "attestation earnings live" if a == "live" else "challenge-pool payouts live" if p == "live" else "payouts paused"

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
    if complete():   # officially complete: every hosted route is open, except grading, which needs seals landing (grading_state)
        g = {"open": "open", "unconfirmed": "unconfirmed", "halted": "paused"}[grading_state()["state"]]
        return {k: (g if k == "grading" else "open") for k in R.current()}
    for k, v in R.current().items():
        st = v["state"]
        if v["slow"]: st = "slow"
        elif k == "mining" and mining_back(): st = "open"   # officially back; an unknown or single halted read does not undo it
        elif st == "open": st = "open" if of["routes"] else "responding"
        out[k] = st
    return out

def og_desc():
    if complete():
        g = grading_state()["state"]
        if g == "open": return "Network upgrade complete: mining, grading and joining are open. Dates on POAScan."
        return f"Network upgrade complete per notice. Mining and joining open; {GRADING_SHORT[g][:-1].lower()}. Live status on POAScan."
    r = recovery()
    if r["moved"]:
        lead, tail = _recovery_line()
        bal = ", balances intact" if r["supply_intact"] else ""
        return f'{lead}: checkpoint {r["checkpoint"]:,}{bal}. {tail} Live status on POAScan.'.replace(". .", ".").replace("  ", " ")
    hs = hosted_state(); js = join_state()
    if hs == "paused" and js == "paused": return f"Hosted mining and joining paused for network upgrades, {payouts_phrase()}. Live status on POAScan."
    h = {"planned": "Hosted mining pauses soon", "back": "Hosted mining is back"}.get(hs, "Hosted mining paused")
    return f"{h} for network upgrades, joining {js}, {payouts_phrase()}. Live status on POAScan."

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
    c = complete()
    if not n: return dict(id=NOTICE_ID, active=False, issued_at=None, expires_at=None, superseded_by=c["notice_id"] if c else None)
    exp = n.get("expires_ts"); sup = superseded(n)
    return dict(id=n.get("id"), active=not sup and not (isinstance(exp, (int, float)) and exp < time.time()), issued_at=iso(n.get("issued_ts")), expires_at=iso(exp),
                superseded_by=c["notice_id"] if sup else None)

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

from decimal import Decimal

def _close_rows(c, key):
    """(minted total, labels) of the closes listed under cut[key], from the stored close records; None when one is missing."""
    from . import segments as S
    tot = 0.0; got = []
    for x in c.get(key) or []:
        with S.use(int(x["segment"])): r = next((r for r in A.epoch_rows() if r["epoch"] == int(x["epoch"])), None)
        if r is None: return None, f"S{x['segment']} E{x['epoch']}"
        tot += float(r["minted"] or 0); got.append(f"S{x['segment']} E{x['epoch']}")
    return tot, got

def cut_baseline():
    """Supply carried over the newest segment boundary (segments config), from POAScan's own /api/status snapshots and
    stored close records. Primary basis: the last supply read of the earlier segment, less the rewards of the closes the
    config lists under cut.excluded_closes. Cross check: the first read once the earlier segment's checkpoint reached its
    final height (cut_height), plus the rewards of cut.carried_closes. Both are compared with the first read in the new
    segment. None when there is no boundary."""
    from . import segments as S
    c = S.cut()
    if not c: return None
    prev = S.BY_N.get(c["from_segment"]) or {}; h = prev.get("cut_height")
    ex = "json_extract(json, '$.checkpoint_height')"; sp = "json_extract(json, '$.supply')"
    last = db.q1(f"SELECT ts, {sp} AS s FROM snaps WHERE kind='status' AND ts < ? AND {sp} IS NOT NULL ORDER BY ts DESC LIMIT 1", (c["ts"],))
    atcp = db.q1(f"SELECT ts, {sp} AS s FROM snaps WHERE kind='status' AND ts < ? AND {ex} = ? ORDER BY ts LIMIT 1", (c["ts"], h)) if h is not None else None
    a = db.q1(f"SELECT ts, {sp} AS s FROM snaps WHERE kind='status' AND ts >= ? AND {sp} IS NOT NULL ORDER BY ts LIMIT 1", (c["ts"],))
    sa = _num(a["s"]) if a else None
    lab = prev.get("label", "")
    exc, eg = _close_rows(c, "excluded_closes"); car, cg = _close_rows(c, "carried_closes")
    def side(b, add, sign, names, txt):
        if b is None or add is None: return None
        v = _num(b["s"]) + sign * Decimal(f"{add:.6f}")
        return dict(value=f"{v:.6f}", basis=txt + ((" less " if sign < 0 else " plus ") + ", ".join(names) + " rewards" if names else ""), ts=b["ts"],
                    intact=(abs(sa - v) < Decimal("0.00001")) if sa is not None else None)
    p1 = side(last, exc, -1, eg, f"last {lab} supply") if c.get("excluded_closes") is not None else None
    p2 = side(atcp, car, 1, cg, f"{lab} supply at checkpoint h{h}") if h is not None else None
    pr = p1 or p2
    return dict(before=pr["value"] if pr else None, after=f"{sa:.6f}" if sa is not None else None, basis=pr["basis"] if pr else None,
                before_ts=pr["ts"] if pr else None, after_ts=a["ts"] if a else None, intact=pr["intact"] if pr else None,
                cross_check=p2 if p1 and p2 else None, segment=c["segment"])

def recovery():
    """Public recovery facts from our own mirror: checkpoint moved, new state root, supply carried over, status freshness, counters."""
    st = dict(A.status()); sup = _num(st.get("supply")); pre = _num(PRE_SUPPLY)
    for k in ("checkpoint_height", "state_root", "as_of"):   # /api/status now and then answers without these: use our newest read that had them
        if st.get(k) is None: st[k] = _last_status(k)
    cp = st.get("checkpoint_height")
    if cp is None: cp = A.networks().get("checkpoint_height")
    t = A._ts(st.get("as_of")); age = int(time.time() - t) if t else None
    from . import segments as S   # a genesis cut restarts heights: a new segment's low checkpoint is not a parked one
    cb = cut_baseline() if S.has_cut() else None
    prev_cp = S.BY_N[S.cut()["from_segment"]].get("cut_height") if cb else PARKED
    if cb: pre_s, intact = cb["before"], cb["intact"]
    else: pre_s, intact = PRE_SUPPLY, sup is not None and sup == pre
    return dict(moved=cp is not None and (int(cp) > PARKED or S.has_cut()), checkpoint=int(cp) if cp is not None else None, previous_checkpoint=prev_cp,
                state_root=st.get("state_root"), supply=str(st.get("supply")) if st.get("supply") is not None else None, supply_before=pre_s,
                supply_intact=intact, supply_before_basis=cb["basis"] if cb else f"supply at parked checkpoint {PARKED}",
                supply_after_cut=cb["after"] if cb else None, supply_cross_check=cb["cross_check"] if cb else None, previous_segment=S.cut()["from_segment"] if cb else None, status_as_of=st.get("as_of"), status_age_s=age,
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
    if complete(): return "upgrade_complete"
    t = back_since()
    if t and time.time() - t > BACK_GRACE_S: return "mining_back"
    if time.time() - STARTED > MAX_S and not _paused_seen(): return "expired"
    return None

def _active(): return _cleared() is None

def state():
    from . import hosted as R
    cp = A.status().get("checkpoint_height"); cleared = _cleared(); active = cleared is None
    lj = last_join(); rec = recovery(); rt = R.current(); ck = R.checked_at(); hl = strip_text(); hm = strip_mobile(); c = complete()
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None
    head, short = (" ".join(x for x in (hl[0] + hl[1] + ".", hl[2]) if x), " ".join(x for x in (hm[0] + ".", hm[1]) if x))
    gs = grading_state()
    if c: head, short = DONE_LINE[gs["state"]]
    sn = segment_notice()
    if sn and sn["active"]: head, short = f'{sn["label"]}: {sn["note"]} {head}', f'{sn["label"]}. {short}'   # the active boundary notice first, tersely
    return dict(active=active, cleared_by=cleared, post_id=POST_ID, post_url=POST_URL, join_open=join_open(), join_state=join_state(),
                last_join_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(lj)) if lj else None, join_source=join_source(), hosted_mining=hosted_state(),
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(STARTED)),
                expected_window_h=list(WINDOW_H), paused=paused(), working=working(), self_custody="POST /api/submit plus /api/receipt keep working", pending_ttl_epochs=TTL_EPOCHS,
                parked_checkpoint=PARKED, checkpoint=cp, auto_clear="when an official notice says grading is back and the hardening is over (complete); before that, 6 hours after mining is officially back",
                halted_list_public=False, url="https://poascan.io/upgrade",
                phase="complete" if c else "recovery" if rec["moved"] else "parked", headline=head, headline_short=short,
                completed_at=iso(c and c["at"]), completed_by=dict(notice_id=c.get("notice_id"), txid=c.get("txid")) if c else None,
                updated_at=iso(c["at"] if c else stamp_ts()),
                hosted_routes={k: v["state"] for k, v in rt.items()}, hosted_routes_display=route_display(),
                official={k: v for k, v in official().items() if k != "post"}, mining_back_at=(lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None)(back_since()), hosted_routes_checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ck)) if ck else None,
                notice=notice(), segment_notice=sn, recovery=rec, unconfirmed=unconfirmed(), grading=_grading_public(gs), **_hs())

def segment_notice():
    """The newest segment boundary's notice (segments config) with its state in our /api/notices mirror: active is true
    while the mirror lists it unexpired, false once gone or expired, null when the mirror has never held it."""
    from . import segments as S
    c = S.cut()
    if not c or not c.get("notice_id"): return None
    d = db.get_blob("notices")[0]; now = time.time()
    x = next((x for x in ((d or {}).get("active") or []) if isinstance(x, dict) and x.get("id") == c["notice_id"]), None) if isinstance(d, dict) else None
    act = None if x is None and not isinstance(d, dict) else bool(x and not (isinstance(x.get("expires_ts"), (int, float)) and x["expires_ts"] < now))
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if isinstance(t, (int, float)) else None
    return dict(id=c["notice_id"], label=c["label"], note=c["note"], active=act, issued_at=iso((x or {}).get("issued_ts")) or iso(c["ts"]),
                expires_at=iso((x or {}).get("expires_ts")), severity=(x or {}).get("severity"), txid=(x or {}).get("txid") or c.get("txid"),
                segment=c["segment"], from_segment=c["from_segment"], from_height=c["from_height"], url="https://poascan.io/about#segments")

DONE_HEAD = "Upgrade complete. Mining, grading and joining are open."
DONE_LINE = {"open": (DONE_HEAD, "Upgrade complete."),
             "unconfirmed": ("Upgrade complete per notice. Grading not yet confirmed: no recent grade seals.", "Grading not yet confirmed."),
             "halted": ("Upgrade complete per notice, but grading is halted.", "Grading halted.")}

def _grading_public(g):
    """meta.maintenance.grading: state, label, basis and the archive evidence (times as ISO UTC)."""
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None
    return dict(state=g["state"], label=GRADING_LABEL[g["state"]], basis=g["basis"], notice_id=g["notice_id"], halt_notice=g["halt_notice"],
                seals_since_notice=g.get("seals_since_notice"), sealers_since_notice=g.get("sealers_since_notice"), last_seal_at=iso(g.get("last_seal_at")),
                seals_recent=g.get("seals_recent"), recent_window_s=g["window_s"], min_seals=g["min_seals"], feed_fresh=g["feed_fresh"])

def _hs():
    from . import halts as H
    d = H.summary(); pr = (H.current() or {}).get("probe") or {}
    if d.get("surfaces"): d["surfaces"] = _after_complete(d["surfaces"], pr)
    return d
