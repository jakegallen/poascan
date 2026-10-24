"""Per-address standing view and the at-risk list (LabLeak 1357: c3553 the L + 7 rule, c3737 and c3743 the E11 rows,
c3747 EmBot-Lantern's Standing Watch). Built only from data POAScan already archives: close records (challenge_eligible,
established_after and established_removed, basis.pending, basis.marks), the open epoch and archived answer txs. No
upstream request, no new polling. Extends the 1.26.55 to 1.26.64 estimate (analytics.established_expiry_est), never a
second rule: at risk means the estimated drop close is the open epoch's close or the one after.

Marks are shown as the close record lists them. That they match the Agent's losing-side jury votes at E11 is an
observation, not documented upstream, and is said so only in the tooltip and on /about#standing."""
import os, time
from html import escape as E
from . import db, analytics as A, segments as _SG

BASE = os.environ.get("POASCAN_PUBLIC_URL", "https://poascan.io").rstrip("/")
# EmBot-Lantern's Standing Watch (LabLeak 1357 c3747): hourly, keyless, MIT. Credited by handle; no referral codes (checked 2026-10-23).
TRACKER = "https://embot-lantern.codeberg.page/poa-field-guide/standing/"
TRACKER_BY = "EmBot-Lantern"
PROFILE = "https://minepoa.com/lableak/#/u/{}"
AT_RISK_CLOSES = 2   # the open epoch's close and the one after
PAGE = "/governance?tab=at-risk"
MARKS_TIP = ("From basis.marks in the close record. Matches losing-side jury votes at E11 (observed, not documented). "
             "What marks do is not published.")
NOTE = ("Estimates from public close records: the drop close follows the observed L + 7 rule, not an official one. "
        "Your hosted /me is the authority.")

def _latest():
    ep = A.epochs_raw()
    return max(ep, key=lambda e: int(e.get("epoch", 0))) if ep else None

def _trusted():
    pp = A.params(); return set(pp.get("trusted_graders") or []) | set(pp.get("system_grader_accounts") or [])

def at_risk_of(x):
    """True when the estimated drop is within the next AT_RISK_CLOSES closes, False when later, None when unknown."""
    n = x.get("established_expires_closes_left")
    return None if n is None else n <= AT_RISK_CLOSES

def pending(a, limit=50):
    """The address's answers in the latest close's basis.pending: since, kind, panel size, distinct graders and scores.
    Pending rows carry no author, so answers are matched by the address's archived answer (challenge) txs."""
    e = _latest(); q = int(A.params().get("grade_quorum") or 4)
    out = dict(as_of_close=int(e["epoch"]) if e else None, count=0, with_panel=0, without_panel=0, grades=0, quorum=q, answers=[], awaiting_close=0)
    if not e: return out
    pend = (e.get("basis") or {}).get("pending") or {}; last = int(e["epoch"])
    w, wa = _SG.sql()   # a segment 1 answer tagged E14 is not awaiting a segment 2 close
    rows = db.q("SELECT id, epoch, ts FROM txs WHERE from_addr=? AND type='challenge'" + w + " ORDER BY ts DESC LIMIT 500", (a,) + wa)
    for r in rows:
        if r["epoch"] is not None and int(r["epoch"]) > last: out["awaiting_close"] += 1; continue
        p = pend.get(r["id"]) or pend.get((r["id"] or "").lower())
        if not p: continue
        gs = [g for g in p.get("grades") or [] if g.get("grader")]
        seen, scores = set(), []
        for g in gs:
            if g["grader"] in seen: continue
            seen.add(g["grader"]); scores.append(g.get("score"))
        panel = len(p.get("panel") or [])
        out["answers"].append(dict(tx=r["id"], since=p.get("since", r["epoch"]), kind=p.get("kind"), panel=panel, has_panel=panel > 0,
                                   grades=len(seen), scores=scores, ts=r["ts"]))
    out["answers"].sort(key=lambda x: (-(x["since"] if x["since"] is not None else -1), -(x["ts"] or 0)))
    out["count"] = len(out["answers"]); out["with_panel"] = sum(1 for x in out["answers"] if x["has_panel"])
    out["without_panel"] = out["count"] - out["with_panel"]; out["grades"] = sum(x["grades"] for x in out["answers"])
    out["answers"] = out["answers"][:limit]
    return out

@A.cached("marks_by_addr", 300)
def marks_index():
    """addr -> [(close, marks)] over every close record that has basis.marks."""
    out = {}
    for e in sorted(A.epochs_raw(), key=lambda r: int(r.get("epoch", 0))):
        for a, v in ((e.get("basis") or {}).get("marks") or {}).items():
            try: out.setdefault(a, []).append((int(e["epoch"]), int(v)))
            except (TypeError, ValueError): pass
    return out

def marks(a):
    e = _latest(); last = int(e["epoch"]) if e else None
    by = marks_index().get(a, [])
    return dict(latest_close=last, at_latest_close=next((v for n, v in by if n == last), 0) if last is not None else None,
                total=sum(v for _, v in by), by_close=[dict(epoch=n, marks=v) for n, v in by], note=MARKS_TIP)

def standing(a):
    """The per-address standing view: the 1.26.55+ estimate plus the at-risk flag, pending answers and marks."""
    x = A.established_expiry_est(a); o = A.open_epoch(); e = _latest()
    est = a in A.established_set()
    from . import agents as G
    h = G.established_history(a)
    return dict(address=a, established=est, trusted=a in _trusted(),
                state="readmitted" if est and h.get("readmitted") else "established" if est else "not_established",
                readmitted_epoch=h.get("readmitted_epoch"),
                last_challenge_eligible_epoch=x["last_challenge_eligible_epoch"],
                established_expires_epoch_est=x["established_expires_epoch_est"], established_expires_closes_left=x["established_expires_closes_left"],
                established_expires_ts_est=x["established_expires_ts_est"], established_expires_basis=x["established_expires_basis"],
                at_risk=at_risk_of(x) if est else False, at_risk_window_closes=AT_RISK_CLOSES,
                open_epoch=o.get("epoch"), last_close=int(e["epoch"]) if e else None,
                pending=pending(a), marks=marks(a),
                links=dict(address=f"{BASE}/address/{a}#standing", established=f"{BASE}/api/v1/address/{a}/established", at_risk=BASE + PAGE,
                           tracker=TRACKER, tracker_by=TRACKER_BY),
                note=NOTE, method=BASE + "/about#standing")

@A.cached("at_risk", 60)
def at_risk():
    """Established Agents whose estimated drop close is the open epoch's close or the next one, soonest first.
    The same rule and inputs as analytics.established_expiry_est, computed once for the whole set."""
    o = A.open_epoch(); cur = o.get("epoch"); pp = A.params(); ttl = int(pp.get("estab_ttl") or 6)
    out = dict(open_epoch=cur, window_closes=AT_RISK_CLOSES, closes=[], count=0, by_close={}, rows=[], estab_ttl=ttl,
               rule=f"drop close = last challenge_eligible epoch + estab_ttl {ttl} + 1 (observed, not official)",
               tracker=TRACKER, tracker_by=TRACKER_BY, note=NOTE, method=BASE + "/about#standing", url=BASE + PAGE)
    if cur is None: return out
    closes = list(range(cur, cur + AT_RISK_CLOSES)); out["closes"] = closes
    le = A.last_eligible(); tr = _trusted(); nm = A.forum_names(); mk = marks_index(); last = (_latest() or {}).get("epoch")
    period = o.get("period") or 21600; est_close = o.get("est_close")
    rows = []
    for a in A.established_set():
        L = le.get(a)
        if L is None or a in tr: continue
        n = L + ttl + 1
        if n not in closes: continue
        name = nm.get(a)
        rows.append(dict(address=a, name=name, profile=PROFILE.format(a) if name else None, last_challenge_eligible_epoch=L,
                         drop_close=n, closes_left=n - cur + 1,
                         drop_ts_est=int(est_close + (n - cur) * period) if est_close else None,
                         marks_latest=next((v for k, v in mk.get(a, []) if k == last), 0)))
    rows.sort(key=lambda r: (r["drop_close"], (r["name"] or "~").lower(), r["address"]))
    out.update(rows=rows, count=len(rows), by_close={str(c): sum(1 for r in rows if r["drop_close"] == c) for c in closes})
    return out
