"""Route halts from POAScan's existing probes (1.26.188). No new request to minepoa.com: this job reads only what other
jobs already store, once a minute, off the database.
Sources, per route (each a read another job already makes):
  pulse      the private live prober's per-endpoint answers (pulse.py, every 5 min, off the node)
  route      the hosted route check (hosted.py, every 15 min, only while maintenance is on)
  writes     the swap write check (hosted.write_job, about every 10 min; hosted.swap_route() is its resolver)
  fetch_log  POAScan's own reads of lookup endpoints (tx, address, keyless assignments), with their consecutive failures
  seals      grade seals landing in POAScan's archive (maint.grading_state, 1.26.200): a good read for Grading at the newest
             seal's time while grading is confirmed open
  seal gap   1.26.201: no grade seal for 15 min while 20+ answers landed is Stale; 30 min gives failing reads (Down since
             the newest seal). See GAP_* below
  route      also the always-on keyless grade route read (hosted.grade_job, 1.26.201, about every 15 min) for Grading
A read is ok, halt (HTTP 503 with the halt text) or fail (5xx, timeout, no answer, a notice in place of data). 401, 404,
429 and sheds are not route reads. Hysteresis: a route turns Halted (or Down, with no halt text) after BAD_N bad reads in
a row, and back to Open after GOOD_N good reads in a row, so one failed or one good probe never flips it. 'since' is the
first bad read of the run that turned it. Stored in the routewatch blob; public through state(), /api/v1/health,
meta.maintenance.route_halts, MCP get_route_status, the header status note, Network > Health and /upgrade."""
import time, logging
from . import db

log = logging.getLogger("poascan.routewatch")
BLOB = "routewatch"
BAD_N, GOOD_N = 2, 2          # bad reads in a row to turn Halted or Down; good reads in a row to clear
STALE_S = 2 * 3600            # a route whose newest read is older than this is shown with a Stale tag
KEEP_ENDED = 10               # ended halts kept for the API (newest first)
# id, label, sources. fetch_log keys are the indexer's endpoint keys; pulse ids come from pulse.ROUTE_MAP; route ids from hosted.ROUTES.
ROUTES = [
    ("hosted_mining", "Hosted mining", dict(pulse="hosted_mining", route="mining")),
    ("assignments", "Assignments", dict(pulse="assignments", fetch=("/api/assignments/:addr",))),
    ("grading", "Grading", dict(pulse="grading", route="grading", seals=True)),
    ("path_actions", "Path actions", dict(pulse="path_actions")),
    ("swap_writes", "Swap writes", dict(writes=True)),
    ("tx_lookup", "Tx lookup", dict(fetch=("/api/explorer/tx/:id", "/api/explorer/tx/:id (on demand)", "/api/explorer/tx/:id (swaps)"))),
    ("address_lookup", "Address lookup", dict(fetch=("/api/explorer/address/:addr",))),
]
LABEL = {i: l for i, l, _ in ROUTES}
WORD = {"open": "Open", "halted": "Halted", "down": "Down", "unknown": "No read"}   # word is Degraded for a covered Tx lookup (state())

def _err_kind(err):
    """halt, fail or None (not a route read) for one fetch_log error text."""
    e = str(err or "")
    if e.endswith(" halted"): return "halt"
    if e.startswith("HTTP 4"): return None   # 401 under load, 404 missing, 429 rate limit: not the route failing
    return "fail"

def _fetch_obs(keys, seen):
    """New reads since the last pass, from fetch_log rows: [(ts, kind, source)]. seen holds each key's last row."""
    out = []
    for k in keys:
        r = db.q1("SELECT last_ok, last_err, err, fails FROM fetch_log WHERE endpoint=?", (k,))
        if not r: continue
        lo, le, fl = r["last_ok"] or 0, r["last_err"] or 0, r["fails"] or 0
        p = seen.get(k)
        if p is None:   # first pass: take the row as it stands (its last good read, then its failure run after it)
            if lo: out.append((lo, "ok", k))
            kd = _err_kind(r["err"]) if le > lo and fl else None
            if kd: out += [(le, kd, k)] * min(fl, BAD_N)
        else:
            plo, ple, pfl = p
            if lo > plo and lo >= le: out.append((lo, "ok", k))
            if le > ple and le > lo:
                kd = _err_kind(r["err"])
                n = fl - pfl if fl > pfl and lo <= plo else max(fl, 1)
                if kd: out += [(le, kd, k)] * max(1, min(n, BAD_N))
        seen[k] = (lo, le, fl)
    return out

def _pulse_obs(rid, seen):
    from . import pulse as P
    d = db.get_blob(P.BLOB)[0] or {}
    ts, kd = d.get("ts") or 0, (d.get("routes") or {}).get(rid)
    if not kd or ts <= seen.get("pulse:" + rid, 0): return []
    seen["pulse:" + rid] = ts
    return [(ts, kd, "pulse")]

def _route_obs(rid, seen):
    from . import hosted as HO
    r = ((db.get_blob(HO.BLOB)[0] or {}).get("routes") or {}).get(rid) or {}
    t = r.get("tried") or 0
    if t <= seen.get("route:" + rid, 0): return []
    seen["route:" + rid] = t
    if r.get("checked") == t and r.get("state") in ("open", "paused"): return [(t, "ok" if r["state"] == "open" else "halt", "route")]
    if r.get("slow_since") and r.get("checked") != t: return [(t, "fail", "route")]
    return []

def _writes_obs(seen):
    from . import hosted as HO
    w = db.get_blob(HO.WRITE_BLOB)[0] or {}
    t = w.get("tried") or 0
    if t <= seen.get("writes", 0): return []
    seen["writes"] = t
    if w.get("checked_at") != t: return []   # an unclear try (404, 429, edge page): not a read
    return [(t, {"open": "ok", "paused": "halt", "down": "fail"}.get(w.get("state")), "writes")] if w.get("state") in ("open", "paused", "down") else []

def _seal_obs(seen):
    """A good Grading read at the newest seal's time, once per new seal, while maint.grading_state() is open (seals landed
    in the last 30 min after the completion notice and no halt was observed). Local only: the archive POAScan already keeps."""
    from . import maint as M
    try: g = M.grading_state()
    except Exception: return []
    t = int(g.get("last_seal_at") or 0) if str(g.get("last_seal_at") or "").isdigit() else 0
    if g.get("state") != "open" or not t or t <= seen.get("seals", 0): return []
    seen["seals"] = t
    return [(t, "ok", "seals")]

# 1.26.201: the seal gap rule. Grade seals normally land every few minutes while answers land; a run with none is the
# clearest public sign that grading stopped (the 503 since about 1:18 AM PT Oct 28 never reached a probe). From the
# archive only, once a minute: with GAP_MIN_ANSWERS or more answers archived since the newest seal (so the tx feed is
# live and there is work to grade), a gap of GAP_STALE_S marks the Grading row Stale ("No grade seals for N min") and a
# gap of GAP_DOWN_S gives it two failing reads, the first at the newest seal, so it reads Down since that seal. A new
# seal is a good read again only through the seals source (grading confirmed open), so Open needs seals to resume.
GAP_STALE_S, GAP_DOWN_S, GAP_MIN_ANSWERS = 15 * 60, 30 * 60, 20

def seal_gap(now=None):
    """dict(last_seal_at, gap_s, answers) from the archive: the newest grade seal and the answers archived after it."""
    now = int(now or time.time())
    r = db.q1("SELECT MAX(ts) AS t FROM txs WHERE type='grade-sealed' AND ts <= ?", (now,)) or {}
    t = int(r["t"] or 0) if r.get("t") is not None else 0
    if not t: return dict(last_seal_at=None, gap_s=None, answers=0)
    a = db.q1("SELECT COUNT(*) AS n FROM txs WHERE type='challenge' AND ts > ? AND ts <= ?", (t, now)) or {}
    return dict(last_seal_at=t, gap_s=now - t, answers=int(a["n"] or 0))

def gap_level(g):
    """None, 'stale' or 'down' for a seal_gap() reading."""
    if not g or not g.get("last_seal_at") or (g.get("answers") or 0) < GAP_MIN_ANSWERS: return None
    return "down" if g["gap_s"] >= GAP_DOWN_S else "stale" if g["gap_s"] >= GAP_STALE_S else None

def _gap_obs(g, now, seen):
    """Two failing reads for a down-level gap: one at the newest seal (so since is when seals stopped), one now."""
    if gap_level(g) != "down": return []
    out = []
    if seen.get("gap_from") != g["last_seal_at"]: out.append((g["last_seal_at"] + 1, "fail", "seal gap")); seen["gap_from"] = g["last_seal_at"]
    out.append((now, "fail", "seal gap"))
    return out

def step(r, ts, kind, src):
    """One read into a route's record (hysteresis). r: dict(state, since, bad, good, first_bad, halt_seen, as_of, last_ok_at, last_bad_at)."""
    if ts < (r.get("as_of") or 0) - 3600: return r   # far older than what we have: ignore
    if kind == "ok" and ts < (r.get("last_bad_at") or 0): return r   # sources arrive out of order: an older good read never breaks a newer bad run
    if kind != "ok" and ts < (r.get("last_ok_at") or 0): return r    # nor an older bad read a newer good run
    r["as_of"] = max(r.get("as_of") or 0, ts); r.setdefault("sources", [])
    if src not in r["sources"]: r["sources"] = sorted(set(r["sources"]) | {src})
    bad = r.get("state") in ("halted", "down")
    if kind == "ok":
        r["last_ok_at"] = max(r.get("last_ok_at") or 0, ts); r["bad"] = 0; r["first_bad"] = None; r["halt_seen"] = False
        if bad:
            r["good"] = (r.get("good") or 0) + 1
            if r["good"] >= GOOD_N:
                r.setdefault("ended", []).insert(0, dict(state=r["state"], since=r["since"], until=ts)); r["ended"] = r["ended"][:KEEP_ENDED]
                r.update(state="open", since=ts, good=0)
        elif r.get("state") != "open": r.update(state="open", since=ts, good=0)
        return r
    r["good"] = 0; r["last_bad_at"] = max(r.get("last_bad_at") or 0, ts)
    r["bad"] = (r.get("bad") or 0) + 1; r["first_bad"] = r.get("first_bad") or ts; r["halt_seen"] = bool(r.get("halt_seen")) or kind == "halt"
    if bad:
        if r["state"] == "down" and kind == "halt": r["state"] = "halted"   # the halt text names it: same run, same since
    elif r["bad"] >= BAD_N:
        r.update(state="halted" if r["halt_seen"] else "down", since=r["first_bad"])
    return r

def job(now=None):
    """Indexer job: fold every new read into the per-route records. Local only."""
    now = int(now or time.time())
    d = db.get_blob(BLOB)[0] or {}; recs = d.get("routes") or {}; seen = {k: tuple(v) if isinstance(v, list) else v for k, v in (d.get("seen") or {}).items()}
    for rid, _, src in ROUTES:
        obs = []
        if src.get("pulse"): obs += _pulse_obs(src["pulse"], seen)
        if src.get("route"): obs += _route_obs(src["route"], seen)
        if src.get("writes"): obs += _writes_obs(seen)
        if src.get("fetch"): obs += _fetch_obs(src["fetch"], seen)
        if src.get("seals"):
            obs += _seal_obs(seen)
            try: g = seal_gap(now)
            except Exception: g = None
            obs += _gap_obs(g, now, seen)
        r = recs.get(rid) or dict(state="unknown")
        if src.get("seals"): r["gap"] = g
        for ts, kd, s in sorted(o for o in obs if o[1]): r = step(r, ts, kd, s)
        if src.get("seals") and r.get("state") == "down" and gap_level(g) == "down" and (r.get("since") or 0) > g["last_seal_at"]:
            r["since"] = g["last_seal_at"]   # a seal gap run: Down since the newest seal, even when a later route read broke the first bad read
        recs[rid] = r
    hist = _hist_add(d.get("hist") or {}, recs, now)
    db.put_blob(BLOB, dict(routes=recs, seen=seen, ts=now, hist=hist))

# 1.26.201: a 24 h strip per route. One cell per HIST_S (15 min) holding the worst state the route was in during that
# slot (down or halted over unknown over open), from this job's own passes; kept HIST_N slots. No new read.
HIST_S, HIST_N = 900, 96
_RANK = {"open": 0, "unknown": 1, "halted": 2, "down": 3}
def _hist_add(hist, recs, now):
    b = now - now % HIST_S; lo = b - (HIST_N - 1) * HIST_S; out = {}
    for rid, _, _ in ROUTES:
        h = {int(k): v for k, v in (hist.get(rid) or {}).items() if int(k) >= lo}
        st = (recs.get(rid) or {}).get("state") or "unknown"
        if _RANK.get(st, 1) >= _RANK.get(h.get(b), -1): h[b] = st
        out[rid] = {str(k): v for k, v in h.items()}
    return out

def history(rid, now=None):
    """[(slot_start_ts, state or None)] for the last 24 h, oldest first; None where the job has no pass."""
    now = int(now or time.time()); b = now - now % HIST_S
    h = ((db.get_blob(BLOB)[0] or {}).get("hist") or {}).get(rid) or {}
    return [(t, h.get(str(t))) for t in range(b - (HIST_N - 1) * HIST_S, b + 1, HIST_S)]

def _iso(t): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(t))) if t else None

def state(now=None):
    """Public view: dict(as_of, routes [{id, label, state, since, as_of, stale, sources, ...}], halted [ids], method).
    state: open, halted (503 with the halt text), down (failing without it) or unknown (no read yet)."""
    now = now or time.time(); d = db.get_blob(BLOB)[0] or {}; recs = d.get("routes") or {}; out = []
    for rid, lab, _ in ROUTES:
        r = recs.get(rid) or {}; st = r.get("state") or "unknown"; ao = r.get("as_of")
        g = r.get("gap") if rid == "grading" else None; gl = gap_level(g)
        sr = (f"No grade seals for {int(g['gap_s'] // 60)} min while {g['answers']:,} answers landed" if gl else None)
        out.append(dict(id=rid, label=lab, state=st, word=WORD[st], since=_iso(r.get("since")) if st != "unknown" else None, since_ts=r.get("since") if st != "unknown" else None,
                        as_of=_iso(ao), as_of_ts=ao, stale=bool(ao and now - ao > STALE_S) or (gl == "stale" and st == "open"), stale_reason=sr if gl == "stale" and st == "open" else ("No read in over 2 h" if ao and now - ao > STALE_S else None),
                        seal_gap=(dict(last_seal_at=_iso(g["last_seal_at"]), gap_s=g["gap_s"], answers=g["answers"], level=gl) if g else None) if rid == "grading" else None,
                        down_reason=sr if gl == "down" and st == "down" else None,
                        bad_reads=r.get("bad") or 0, good_reads=r.get("good") or 0,
                        last_ok_at=_iso(r.get("last_ok_at")), last_bad_at=_iso(r.get("last_bad_at")), sources=r.get("sources") or [],
                        ended=[dict(state=e["state"], since=_iso(e["since"]), until=_iso(e["until"])) for e in r.get("ended") or []]))
    for r in out:   # 1.26.201: a Tx lookup outage the fast index answers for reads Degraded (state keeps the minepoa.com read)
        r["covered_by"] = None
        if r["id"] == "tx_lookup" and r["state"] in ("halted", "down"):
            try:
                from . import fastindex as FX
                f = FX.feed(now) if FX.enabled() else None
            except Exception: f = None
            if f and f.get("state") == "OK": r.update(covered_by="fast index", word="Degraded")
    ts = [r["as_of_ts"] for r in out if r["as_of_ts"]]
    return dict(as_of=_iso(max(ts)) if ts else None, as_of_ts=max(ts) if ts else None, checked_at=_iso(d.get("ts")), routes=out,
                halted=[r["id"] for r in out if r["state"] in ("halted", "down")],
                rule=f"Halted or Down after {BAD_N} bad reads in a row, Open after {GOOD_N} good reads in a row; Stale when the newest read is over {STALE_S // 3600} h old",
                method="https://poascan.io/about#route-halts")

def halted(now=None):
    """[route dicts] currently Halted or Down."""
    return [r for r in state(now)["routes"] if r["state"] in ("halted", "down")]

def meta():
    """Compact block for meta.maintenance.route_halts: as_of and the routes Halted or Down now (id, label, state, since)."""
    d = state()
    return dict(as_of=d["as_of"], halted=[dict(id=r["id"], label=r["label"], state=r["state"], since=r["since"], stale=r["stale"]) for r in d["routes"] if r["state"] in ("halted", "down")],
                url="https://poascan.io/api/v1/routes")

def public():
    """/api/v1/routes and MCP get_route_status: every route, plus the swap order placement resolver."""
    from . import hosted as HO
    return dict(state(), swap_route=HO.swap_route())

def halted_ids():
    try: return {r["id"] for r in halted()}
    except Exception: return set()

def names(rs):
    ls = [r["label"] for r in rs]
    return ls[0] if len(ls) == 1 else ", ".join(ls[:-1]) + " and " + ls[-1]
