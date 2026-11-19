"""Authoritative network facts, cross checked against POAScan's own derivation (minepoa /api/network-facts).

minepoa publishes the live network facts at /api/network-facts: the economics params the running network uses (the
establishment intake floor and rate, estab_ttl, grade_quorum, panel_size, pending_ttl, auto_epoch_seconds and K), the
system accounts v1 to v5 with their liveness, the trusted graders, and the engine and params hashes the running network
is on. POAScan already models these params per segment (netparams.py) and derives engine_sha256 and params_sha256 from
the signed release manifest (protocol.py), so the facts are read as an independent authority: the bundle of params
becomes an integrity signal when POAScan compares its own derived engine_sha and params_sha against the authoritative
ones. A match reads "matches consensus"; any difference reads "drift".

Server side only. The facts are read through indexer.fetch on the facts job cadence (FACTS_S, hourly) and cached in the
"network_facts" blob, exactly like the other hourly meta reads (one conditional GET, a 304 keeps the stored copy).
Nothing here adds a browser fetch or a hot poll. When the facts are unavailable the caller keeps POAScan's derived
values with a small "authoritative source unavailable" note; this module never raises into a page."""
import logging, time
from . import db

log = logging.getLogger("poascan.netfacts")

PATH = "/api/network-facts"
BLOB = "network_facts"
FACTS_S = 3600          # one conditional GET an hour, the same cadence as /api/params and /api/release
STALE_S = 3 * 3600      # a stored copy read longer ago than this is flagged Stale (matches ui.STALE_S)
METHOD = "/about#network-facts"

# The economics params POAScan surfaces from the facts, newest engine naming first with POAScan's own fallbacks.
# key: the field in the facts (and /api/params); label: the page wording; src: the matching netparams key, when any.
ECON = [
    ("estab_intake_floor", "Intake floor", None),
    ("estab_intake_rate", "Intake rate", None),
    ("estab_ttl", "Establishment TTL", "estab_ttl"),
    ("estab_waitlist_epochs", "Waitlist epochs", None),
    ("carry_cap_pools", "Carry cap pools", None),
    ("grade_quorum", "Grade quorum", None),
    ("panel_size", "Panel size", None),
    ("pending_ttl_epochs", "Pending TTL", "pending_ttl_epochs"),
    ("auto_epoch_seconds", "Auto epoch seconds", None),
    ("K", "K", None),
]


def _first(d, *keys):
    """The first key present (not None) in a dict, so a flat or a nested facts shape both read."""
    if not isinstance(d, dict): return None
    for k in keys:
        v = d.get(k)
        if v is not None: return v
    return None


def cached(now=None):
    """(facts dict or None, read ts or None) from the stored blob. No upstream read."""
    d, ts = db.get_blob(BLOB)
    return (d if isinstance(d, dict) else None), (int(ts) if ts else None)


def available(now=None):
    d, _ = cached(now); return d is not None


def stale(now=None):
    d, ts = cached(now)
    return d is None or not ts or (now or time.time()) - ts > STALE_S


# ---------------------------------------------------------------- parsing (pure, tolerant)
def _econ_src(facts):
    """Where the economics params live in the facts: a dedicated block when present, else the top level."""
    return _first(facts, "economics", "params", "economics_params") or facts or {}


def economics(facts=None):
    """[{key, label, value}] for the economics params the facts carry (value None when a key is absent)."""
    facts, _ = (facts, None) if facts is not None else cached()
    src = _econ_src(facts or {})
    out = []
    for key, label, _ in ECON:
        out.append(dict(key=key, label=label, value=src.get(key) if isinstance(src, dict) else None))
    return out


# 1.26.262: /api/params keys from minepoa v0.84-slotlatch-cc44 that the facts do not carry; listed beside Economics.
PARAMS_EXTRA = (("carry_correction", "Carry correction"), ("slot_latch_overrides", "Slot latch pins"))

def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0

def params_extra(p=None):
    """[{key, label, value, text}] for the v0.84 params keys present in /api/params (POAScan's hourly copy, no extra read).
    carry_correction: from_epoch, Agents, total and whether table_sha256 is the pinned ballot 2464 table.
    slot_latch_overrides: the pinned nonce slots, author, nonce and winning txid each."""
    if p is None:
        from . import analytics as A
        p = A.params()
    out = []
    cc = p.get("carry_correction") if isinstance(p, dict) else None
    if isinstance(cc, dict):
        ent = cc.get("entries") if isinstance(cc.get("entries"), dict) else {}
        tot = round(sum(_num(v) for v in ent.values()), 6)
        from . import correction as CC
        sha = str(cc.get("table_sha256") or "").lower() or None
        v = dict(from_epoch=cc.get("from_epoch"), agents=len(ent), total=tot, table_sha256=sha, pinned_table=sha == CC.SHA256)
        out.append(dict(key="carry_correction", label="Carry correction", value=v,
                        text=f"E{cc.get('from_epoch')} · {len(ent)} Agents · {tot / 1e6:,.2f}M"))
    sl = p.get("slot_latch_overrides") if isinstance(p, dict) else None
    if isinstance(sl, list):
        rows = [dict(author=r.get("author"), nonce=r.get("nonce"), txid=r.get("txid")) for r in sl if isinstance(r, dict)]
        out.append(dict(key="slot_latch_overrides", label="Slot latch pins", value=dict(count=len(rows), slots=rows), text=f"{len(rows)}"))
    cs = p.get("close_summary_from_epoch") if isinstance(p, dict) else None   # 1.26.270: the epoch close summaries start at (E28); shown terse, no empty summary before it
    if isinstance(cs, int) and not isinstance(cs, bool):
        out.append(dict(key="close_summary_from_epoch", label="Close summary from", value=cs, text=f"E{cs}"))
    return out


def _accounts_src(facts):
    return _first(facts, "system_accounts", "system_addresses", "system_accounts_liveness", "accounts", "system")


def system_accounts(facts=None):
    """[{id, address, live}] for the system accounts v1 to v5, from a dict keyed by id or a list of rows. live is the
    reported liveness (True, False or None when the facts do not say)."""
    facts, _ = (facts, None) if facts is not None else cached()
    src = _accounts_src(facts or {})
    out = []
    if isinstance(src, dict):
        for k in sorted(src):
            v = src[k]
            if isinstance(v, dict):
                out.append(dict(id=str(k), address=_first(v, "address", "addr", "account"), live=_live(v)))
            else:
                out.append(dict(id=str(k), address=v if isinstance(v, str) else None, live=None))
    elif isinstance(src, list):
        for v in src:
            if not isinstance(v, dict): continue
            out.append(dict(id=str(_first(v, "id", "name", "label") or "?"), address=_first(v, "address", "addr", "account"), live=_live(v),
                            **({"role": v["role"]} if isinstance(v.get("role"), str) else {})))
    return out


def _live(v):
    """The liveness a system account row reports, as True, False or None (several field names, several shapes)."""
    for k in ("live", "alive", "active", "online", "healthy"):
        if k in v and isinstance(v[k], bool): return v[k]
    s = _first(v, "status", "state", "liveness")
    if isinstance(s, str): return s.strip().lower() in ("live", "alive", "active", "online", "ok", "healthy", "up")
    return None


def trusted_graders(facts=None):
    """The trusted grader addresses the facts list (empty when none)."""
    facts, _ = (facts, None) if facts is not None else cached()
    v = _first(facts or {}, "trusted_graders", "trusted_grader_accounts")
    return [a for a in v if isinstance(a, str)] if isinstance(v, list) else []


def facts_hashes(facts=None):
    """{engine, params} as the facts report them (None when a hash is absent). A nested "hashes" block is read too."""
    facts, _ = (facts, None) if facts is not None else cached()
    f = facts or {}
    h = f.get("hashes") if isinstance(f.get("hashes"), dict) else {}
    engine = _first(f, "engine_sha256", "engine_sha", "engine_hash") or _first(h, "engine_sha256", "engine", "engine_sha")
    params = _first(f, "params_sha256", "params_sha", "params_hash") or _first(h, "params_sha256", "params", "params_sha")
    return dict(engine=engine, params=params)


# ---------------------------------------------------------------- cross check (the integrity signal)
def derived_hashes(rel=None):
    """POAScan's own engine_sha256 and params_sha256, from the signed release manifest (protocol.current_release)."""
    from . import protocol as P
    cur = P.current_release(rel) or {}
    return dict(engine=cur.get("engine_sha256") or cur.get("client_sha256"), params=cur.get("params_sha256"),
                version=cur.get("version"))


def crosscheck(facts=None, rel=None, now=None):
    """Compare POAScan's derived engine and params hashes against the authoritative ones the facts report.

    Returns {available, verdict, rows, derived_version}. verdict: "match" when every hash both sides carry is equal,
    "drift" when any pair the two sides both carry differs, "unknown" when the facts are unavailable or a hash is
    missing on either side so no pair can be compared. rows: one per hash, each {name, derived, authoritative, state}
    where state is "match", "drift" or "unknown"."""
    facts, fts = (facts, None) if facts is not None else cached(now)
    der = derived_hashes(rel); auth = facts_hashes(facts)
    rows = []
    compared = drift = 0
    for name in ("engine", "params"):
        d, a = der.get(name), auth.get(name)
        if d and a:
            compared += 1; ok = d == a
            if not ok: drift += 1
            rows.append(dict(name=name, derived=d, authoritative=a, state="match" if ok else "drift"))
        else:
            rows.append(dict(name=name, derived=d, authoritative=a, state="unknown"))
    verdict = "unknown" if facts is None or compared == 0 else ("drift" if drift else "match")
    return dict(available=facts is not None, verdict=verdict, rows=rows, derived_version=der.get("version"), as_of=fts)


# ---------------------------------------------------------------- established set cross check (/api/established)
EST_PATH = "/api/established"
EST_BLOB = "established_auth"


def _est_rows(facts):
    if isinstance(facts, dict):
        cur = facts.get("current")   # 1.26.257: the live shape, {current: {members: [{addr, since_epoch, ...}]}}
        if isinstance(cur, dict) and isinstance(cur.get("members"), list): return cur["members"]
        if isinstance(cur, list): return cur
        v = _first(facts, "established", "established_set", "set", "agents", "members")
        return v if isinstance(v, list) else []
    return facts if isinstance(facts, list) else []


def authoritative_established(facts=None):
    """(frozenset of established addresses, {addr: {since, expires}}) from the stored /api/established copy. Empty when
    unavailable. Accepts a list of addresses, a list of {address, since, expires} rows, or a dict wrapping either."""
    if facts is None: facts, _ = db.get_blob(EST_BLOB)
    aset, detail = set(), {}
    for r in _est_rows(facts):
        if isinstance(r, str):
            if r.startswith("poa1"): aset.add(r)
        elif isinstance(r, dict):
            a = _first(r, "address", "addr", "account")
            if isinstance(a, str) and a.startswith("poa1"):
                aset.add(a)
                detail[a] = dict(since=_first(r, "established_since", "since", "established_at", "since_epoch"),
                                 expires=_first(r, "expires_after", "expires", "expires_epoch", "expires_after_epoch"))
    return frozenset(aset), detail


def established_available():
    d, _ = db.get_blob(EST_BLOB); return d is not None


def established_reconcile(now=None):
    """POAScan's derived established set (analytics.established_set, from intake and estfold) against the authoritative
    /api/established copy. {available, agree, derived_size, authoritative_size, only_derived, only_authoritative, as_of}.
    agree is True when the two sets are identical; any address on exactly one side is a real signal worth a look. Fails
    soft: with no authoritative copy it still reports the derived size and agree None."""
    from . import analytics as A
    der = set(A.established_set())
    d, ts = db.get_blob(EST_BLOB)
    if d is None:
        return dict(available=False, agree=None, derived_size=len(der), authoritative_size=None,
                    only_derived=[], only_authoritative=[], as_of=None)
    auth, _ = authoritative_established(d)
    only_d, only_a = sorted(der - auth), sorted(auth - der)
    return dict(available=True, agree=(not only_d and not only_a), derived_size=len(der), authoritative_size=len(auth),
                only_derived=only_d, only_authoritative=only_a, as_of=int(ts) if ts else None)


def addr_established(a, facts=None):
    """{authoritative, since, expires} for one address from the cached /api/established copy, or None when the facts are
    unavailable. Read from the cached bulk set, never a per view upstream call (the per-address /api/established/<addr>
    read is allowlisted for a future on demand enrichment under the existing budget, not polled here)."""
    if facts is None: facts, _ = db.get_blob(EST_BLOB)
    if facts is None: return None
    aset, detail = authoritative_established(facts)
    info = detail.get(a) or {}
    return dict(authoritative=a in aset, since=info.get("since"), expires=info.get("expires"))


# ---------------------------------------------------------------- close report + settled split (/api/close-report, /api/settled)
CLOSE_PATH = "/api/close-report"
SETTLED_PATH = "/api/settled"
CLOSE_BLOB = "close_report_auth"
SETTLED_BLOB = "settled_auth"
CLOSE_FIELDS = [("passed", "Passed"), ("failed", "Failed"), ("expired", "Expired, no jury"),
                ("settled", "Settled"), ("grades", "Grades"), ("graders", "Graders")]


# 1.26.257: close-report counts grades cast on every dealt row and distinct graders over all seats; POAScan derives
# grades and graders from the settled rows' juries, so the two never line up (E42: 8,621 and 17 against 3,516 and 81).
NOT_COMPARED = {"grades": "minepoa counts grades cast on every dealt row; POAScan counts settled rows' jury grades",
                "graders": "minepoa counts distinct graders over every seat; POAScan counts graders on settled rows"}

def _concentration(dist):
    """{graders, grades, n_eff, top_share} for a {grader: grades} distribution. n_eff is the effective grader count
    (Herfindahl inverse, (sum w) squared over sum of w squared); top_share is the largest grader's share. n_eff and
    top_share are None with no grades."""
    vals = [float(v) for v in (dist or {}).values() if isinstance(v, (int, float)) and v > 0]
    tot = sum(vals)
    if not vals or tot <= 0:
        return dict(graders=len(vals), grades=int(tot), n_eff=None, top_share=None)
    n_eff = (tot * tot) / sum(v * v for v in vals)
    return dict(graders=len(vals), grades=int(tot), n_eff=round(n_eff, 2), top_share=round(max(vals) / tot, 4))


def _split_from(obj):
    """{passed, failed, expired} from a settled summary block (several key spellings), or None when it carries none."""
    if not isinstance(obj, dict): return None
    p, f = _first(obj, "passed", "pass", "accepted"), _first(obj, "failed", "fail", "rejected")
    x = _first(obj, "expired_no_jury", "expired", "expired_nojury")
    if p is None and f is None and x is None: return None
    g = lambda v: int(v) if isinstance(v, (int, float)) else 0
    return dict(passed=g(p), failed=g(f), expired=g(x))


def authoritative_close(now=None):
    """The authoritative last close, from /api/close-report and /api/settled (cached). {available, epoch, passed,
    failed, expired, settled, grades, graders, quorum_rows, n_eff, top_grader_share, as_of}. The settled split is read
    from close-report's settled block, else counted from the /api/settled rows (outcome.counts). Empty when neither
    endpoint has a copy."""
    from . import outcome as OC
    cr, crt = db.get_blob(CLOSE_BLOB); se, set_ = db.get_blob(SETTLED_BLOB)
    if cr is None and se is None:
        return dict(available=False, as_of=None)
    cr = cr if isinstance(cr, dict) else {}
    ss = cr.get("settled_split")   # 1.26.257: the live shape (settled_split, panels, concentration, establishment)
    split = (dict(passed=int(ss.get("passed") or 0), failed=int(ss.get("failed") or 0),
                  expired=int(ss.get("expired_empty_jury") or 0) + int(ss.get("expired_with_seals") or 0)) if isinstance(ss, dict) else None) \
        or _split_from(cr.get("settled")) or _split_from(cr)
    rows = se if isinstance(se, list) else (se.get("settled") if isinstance(se, dict) and isinstance(se.get("settled"), list) else None)
    if split is None and rows is not None:
        c = OC.counts(rows); split = dict(passed=c["passed"], failed=c["failed"], expired=c["expired_no_jury"])
    split = split or dict(passed=None, failed=None, expired=None)
    dist = _first(cr, "grades_by_grader", "grader_grades", "grader_distribution", "graders_served")
    conc = _concentration(dist if isinstance(dist, dict) else None)
    pn = cr.get("panels") if isinstance(cr.get("panels"), dict) else {}; cn = cr.get("concentration") if isinstance(cr.get("concentration"), dict) else {}
    grades = _first(cr, "grades", "grades_cast", "grade_count") if _first(pn, "grades_cast") is None else pn["grades_cast"]
    graders = _first(cr, "graders", "grader_count", "n_graders") if _first(cn, "distinct_graders") is None else cn["distinct_graders"]
    if cn.get("n_eff_inverse_herfindahl") is not None: conc = dict(conc, n_eff=cn["n_eff_inverse_herfindahl"])
    if cn.get("top_grader_share") is not None: conc = dict(conc, top_share=cn["top_grader_share"])
    settled = None if split["passed"] is None else (split["passed"] + split["failed"] + split["expired"])
    est = cr.get("establishment") if isinstance(cr.get("establishment"), dict) else None
    return dict(available=True, epoch=_first(cr, "close_epoch", "epoch", "close", "epoch_number"), establishment=est,
                passed=split["passed"], failed=split["failed"], expired=split["expired"], settled=settled,
                grades=int(grades) if isinstance(grades, (int, float)) else (conc["grades"] or None),
                graders=int(graders) if isinstance(graders, (int, float)) else (conc["graders"] or None),
                quorum_rows=_first(pn, "rows_reaching_quorum") if _first(pn, "rows_reaching_quorum") is not None else _first(cr, "quorum_rows", "rows_at_quorum", "reached_quorum", "at_quorum"),
                n_eff=conc["n_eff"], top_grader_share=conc["top_share"], as_of=int(crt) if crt else (int(set_) if set_ else None))


def derived_close():
    """POAScan's own last close stats, from the close records (analytics.epoch_rows and grade_counts). The grader
    concentration is derived from POAScan's grade rows. quorum_rows is authoritative only (None here)."""
    from . import analytics as A
    rows = A.epoch_rows()
    if not rows: return dict(available=False)
    r = rows[-1]
    raw = A.epochs_raw()
    conc = _concentration(dict(A.grade_counts(raw[-1])) if raw else {})
    return dict(available=True, epoch=r["epoch"], passed=r["settled_passed"], failed=r["settled_failed"],
                expired=r["settled_expired_no_jury"], settled=r["settled"], grades=r["grades"], graders=r["graders"],
                quorum_rows=None, n_eff=conc["n_eff"], top_grader_share=conc["top_share"])


def close_crosscheck(now=None):
    """Authoritative last close against POAScan's own close stats. {available, verdict, rows, preferred, epoch,
    quorum_rows, n_eff, top_grader_share, as_of}. verdict: match when every field both sides carry is equal, differ
    when any differs, unknown when the authoritative close is unavailable. preferred takes the authoritative value where
    present and falls back to the derived one (so the page shows the authoritative split and derived where it is not)."""
    auth = authoritative_close(now); der = derived_close()
    rows = []; compared = diff = 0; preferred = {}
    for key, label in CLOSE_FIELDS:
        a = auth.get(key) if auth.get("available") else None
        d = der.get(key) if der.get("available") else None
        preferred[key] = a if a is not None else d
        if key in NOT_COMPARED:
            rows.append(dict(name=key, label=label, authoritative=a, derived=d, state="not_compared", note=NOT_COMPARED[key])); continue
        if a is not None and d is not None:
            compared += 1; ok = a == d
            if not ok: diff += 1
            rows.append(dict(name=key, label=label, authoritative=a, derived=d, state="match" if ok else "differ"))
        else:
            rows.append(dict(name=key, label=label, authoritative=a, derived=d, state="unknown"))
    verdict = "unknown" if not auth.get("available") or compared == 0 else ("differ" if diff else "match")
    return dict(available=auth.get("available", False), verdict=verdict, rows=rows, preferred=preferred,
                epoch=auth.get("epoch") if auth.get("available") else (der.get("epoch") if der.get("available") else None),
                quorum_rows=auth.get("quorum_rows"), n_eff=auth.get("n_eff"), top_grader_share=auth.get("top_grader_share"),
                as_of=auth.get("as_of"))


# ---------------------------------------------------------------- API block (no upstream read)
def api_block(now=None):
    facts, ts = cached(now)
    cc = crosscheck(facts)
    return dict(available=facts is not None, as_of=ts, stale=stale(now),
                economics={e["key"]: e["value"] for e in economics(facts)},
                system_accounts=system_accounts(facts), trusted_graders=trusted_graders(facts),
                hashes=facts_hashes(facts), crosscheck=cc,
                established=established_reconcile(now), close=close_crosscheck(now),
                expiry=dict(expiry_schedule(now), crosscheck=expiry_crosscheck(now)),
                method="https://poascan.io" + METHOD)


# ---------------------------------------------------------------- the indexer job (server side, gated, cached)
def fetch_facts():
    """One conditional GET through indexer.fetch; stores the facts blob on a 200, keeps the stored copy on a 304.
    Raises indexer.Busy on a failure, like the other meta reads, so run_forever logs and backs the endpoint off."""
    from . import indexer as I
    d = I.fetch(PATH, cond=True)
    if d is I.NOT_MODIFIED: return None
    if isinstance(d, dict):
        db.put_blob(BLOB, d)
    return d


def job():
    from . import indexer as I
    if not I.can_fetch(PATH):
        I.skip_backoff(PATH); return
    try:
        fetch_facts()
    except I.Busy as e:
        log.warning("%s: %s", PATH, e)


def fetch_established():
    """One conditional GET of /api/established through indexer.fetch; stores the established_auth blob on a 200, keeps
    the stored copy on a 304. Raises indexer.Busy on a failure, like the other meta reads."""
    from . import indexer as I
    d = I.fetch(EST_PATH, cond=True)
    if d is I.NOT_MODIFIED: return None
    if isinstance(d, (list, dict)):
        db.put_blob(EST_BLOB, d)
    return d


def established_job():
    from . import indexer as I
    if not I.can_fetch(EST_PATH):
        I.skip_backoff(EST_PATH); return
    try:
        fetch_established()
    except I.Busy as e:
        log.warning("%s: %s", EST_PATH, e)


def _fetch_one(path, blob):
    from . import indexer as I
    d = I.fetch(path, cond=True)
    if d is I.NOT_MODIFIED: return None
    if isinstance(d, (list, dict)):
        db.put_blob(blob, d)
    return d


def fetch_close():
    """One conditional GET of /api/close-report; stores the close_report_auth blob on a 200, keeps it on a 304."""
    return _fetch_one(CLOSE_PATH, CLOSE_BLOB)


def fetch_settled():
    """One conditional GET of /api/settled; stores the settled_auth blob on a 200, keeps it on a 304."""
    return _fetch_one(SETTLED_PATH, SETTLED_BLOB)


def close_job():
    from . import indexer as I
    if I.can_fetch(CLOSE_PATH):
        try: fetch_close()
        except I.Busy as e: log.warning("%s: %s", CLOSE_PATH, e)
    else:
        I.skip_backoff(CLOSE_PATH)


def settled_job():
    from . import indexer as I
    if I.can_fetch(SETTLED_PATH):
        try: fetch_settled()
        except I.Busy as e: log.warning("%s: %s", SETTLED_PATH, e)
    else:
        I.skip_backoff(SETTLED_PATH)


def fetch_expiry():
    """One conditional GET of /api/expiry-schedule; stores the expiry_schedule_auth blob on a 200, keeps it on a 304."""
    return _fetch_one(EXPIRY_PATH, EXPIRY_BLOB)


def expiry_job():
    from . import indexer as I
    if I.can_fetch(EXPIRY_PATH):
        try: fetch_expiry()
        except I.Busy as e: log.warning("%s: %s", EXPIRY_PATH, e)
    else:
        I.skip_backoff(EXPIRY_PATH)


# ---------------------------------------------------------------- rendering (Network > Overview)
_VERDICT = {"match": ("ok", "Matches consensus"), "drift": ("bad", "Drift"), "unknown": ("warn", "Authoritative source unavailable")}


def _badge(cc):
    from .ui import flag
    tone, word = _VERDICT[cc["verdict"]]
    if cc["verdict"] == "match":
        det = "POAScan's derived engine and params hashes equal the ones the running network reports."
    elif cc["verdict"] == "drift":
        bad = ", ".join(r["name"] for r in cc["rows"] if r["state"] == "drift")
        det = f"POAScan's derived hash differs from the running network's for: {bad}. A real signal worth a look."
    else:
        det = "POAScan keeps its own derived values; the authoritative /api/network-facts was not read."
    return flag(word, det, tone=tone)


def render_card(now=None):
    """The Network facts card for Network > Overview. Fails soft: with no facts it shows POAScan's derived hashes with an
    "authoritative source unavailable" note and never raises. Returns a full card section."""
    from .ui import card, flag, short, E
    facts, ts = cached(now)
    cc = crosscheck(facts)
    hrow = lambda name: next((r for r in cc["rows"] if r["name"] == name), {})

    def hash_kv(name, label):
        r = hrow(name)
        d, a = r.get("derived"), r.get("authoritative")
        st = r.get("state")
        tag = flag("match", "Derived equals authoritative", tone="ok") if st == "match" else (
              flag("drift", "Derived differs from authoritative", tone="bad") if st == "drift" else "")
        val = (f'<span class="mono" title="authoritative {E(a)}">{E(short(a, 8, 6))}</span>' if a
               else (f'<span class="mono dim" title="derived {E(d)}">{E(short(d, 8, 6))}</span>' if d else '<span class="na">-</span>'))
        return f'<div class="kv"><span>{E(label)}</span><div>{val} {tag}</div></div>'

    note = ("" if facts is not None else
            '<p class="na">Authoritative source unavailable; showing POAScan\'s derived values. The cross check needs a '
            '/api/network-facts read.</p>')
    head = f'<div class="kv"><span>Integrity</span><div>{_badge(cc)}</div></div>'
    hashes = hash_kv("engine", "Engine hash") + hash_kv("params", "Params hash")

    econ_rows = economics(facts)
    def ev(v): return f'<b>{E(str(v))}</b>' if v is not None else '<span class="na">-</span>'
    px = "".join(f'<div><span title="/api/params {E(x["key"])}">{E(x["label"])}</span><b>{E(x["text"])}</b></div>' for x in params_extra())
    econ = ('<div class="sy">' + "".join(f'<div><span>{E(e["label"])}</span>{ev(e["value"])}</div>' for e in econ_rows) + px + '</div>'
            if facts is not None else ('<div class="sy">' + px + '</div>' if px else '<p class="na">No economics params without a facts read.</p>'))

    accts = system_accounts(facts)
    def live_tag(a):
        if a["live"] is True: return flag("live", "Reported live by the network facts", tone="ok")
        if a["live"] is False: return flag("down", "Reported not live by the network facts", tone="bad")
        return flag("unknown", "The facts do not report this account's liveness", tone="warn")
    acct_html = ("".join(f'<div class="kv"><span>{E(a["id"])}</span><div>'
                         + (f'<span class="mono">{E(short(a["address"], 6, 4))}</span> ' if a.get("address") else "")
                         + live_tag(a) + '</div></div>' for a in accts)
                 if accts else '<p class="na">No system accounts in the facts read.</p>')

    tg = trusted_graders(facts)
    tg_html = f'<div class="kv"><span>Trusted graders</span><div><b>{len(tg)}</b></div></div>'

    extra = f'<span class="na small" title="Read {E(PATH)} hourly; derived from the signed release">authoritative</span>'
    body = (f'{head}{hashes}{tg_html}'
            f'<h3>Economics</h3>{econ}'
            f'<h3>System accounts</h3>{acct_html}'
            f'{_established_block()}{note}')
    return card("Network facts · authoritative", body, extra)


def _established_block():
    """The established set reconciliation sub-block for the facts card (derived vs authoritative /api/established)."""
    from .ui import flag, short, E
    rec = established_reconcile()
    if not rec["available"]:
        tag = flag("unknown", "Authoritative /api/established not read; POAScan shows its derived set.", tone="warn")
        return f'<h3>Established set</h3><div class="kv"><span>Reconciliation</span><div>{tag} <span class="na">derived {rec["derived_size"]}</span></div></div>'
    if rec["agree"]:
        badge = flag("Matches derivation", "The authoritative established set equals POAScan's derived set.", tone="ok")
    else:
        badge = flag("Differs", f"{len(rec['only_derived'])} only in POAScan's derivation, {len(rec['only_authoritative'])} only authoritative. A real signal.", tone="bad")
    rows = f'<div class="kv"><span>Reconciliation</span><div>{badge}</div></div>'
    rows += f'<div class="kv"><span>Size, derived / authoritative</span><div><b>{rec["derived_size"]}</b> / <b>{rec["authoritative_size"]}</b></div></div>'

    def addrs(label, lst):
        if not lst: return ""
        shown = " ".join(f'<a class="mono" href="/address/{E(x)}">{E(short(x, 6, 4))}</a>' for x in lst[:6])
        more = f' <span class="dim">+{len(lst) - 6}</span>' if len(lst) > 6 else ""
        return f'<div class="kv"><span>{label}</span><div>{shown}{more}</div></div>'

    rows += addrs("Only in derivation", rec["only_derived"]) + addrs("Only authoritative", rec["only_authoritative"])
    return f'<h3>Established set</h3>{rows}'


def addr_row(a, derived_established):
    """(label, value) for the Established (authoritative) row on the address page, or None when no facts are cached.
    Shows established since and expires after from the cached /api/established copy, and a Drift tag when the
    authoritative membership disagrees with POAScan's own derivation for this address. Fails soft."""
    info = addr_established(a)
    if info is None: return None
    from .ui import flag, E
    auth = info["authoritative"]
    tag = '<span class="tag ok">YES</span>' if auth else '<span class="tag">NO</span>'
    bits = []
    if info["since"] is not None: bits.append(f'since E{E(str(info["since"]))}')
    if info["expires"] is not None: bits.append(f'expires after E{E(str(info["expires"]))}')
    det = (' <span class="dim">· ' + " · ".join(bits) + "</span>") if bits else ""
    drift = flag("Drift", "POAScan's derivation disagrees with the authoritative set for this address.", tone="bad") if auth != bool(derived_established) else ""
    return ("Established (authoritative)", f'{tag}{det} {drift}')


# ---------------------------------------------------------------- close report card (Network > Overview)
_CLOSE_VERDICT = {"match": ("ok", "Matches close stats"), "differ": ("bad", "Differs"), "unknown": ("warn", "Authoritative source unavailable")}


def render_close_card(now=None):
    """The authoritative last close card: the settled split (passed, failed, expired), grades cast, rows reaching
    quorum and grader concentration (n_eff, top-grader share), each preferring the authoritative figure and falling
    back to POAScan's derived one, with a match or differ badge against POAScan's own close stats. Fails soft."""
    from .ui import card, flag, stat, E
    cc = close_crosscheck(now)
    tone, word = _CLOSE_VERDICT[cc["verdict"]]
    if cc["verdict"] == "match":
        det = "The authoritative settled split and grade counts equal POAScan's own close stats."
    elif cc["verdict"] == "differ":
        bad = ", ".join(r["label"] for r in cc["rows"] if r["state"] == "differ")
        det = f"The authoritative close differs from POAScan's close stats for: {bad}. A real signal worth a look."
    else:
        det = "POAScan keeps its own derived close stats; the authoritative /api/close-report was not read."
    ep = cc["epoch"]
    head = (f'<div class="kv"><span>{"Close E" + str(E(str(ep))) if ep is not None else "Last close"}</span>'
            f'<div>{flag(word, det, tone=tone)}</div></div>')
    pref = cc["preferred"]
    def v(k): return pref.get(k)
    def row(label, val, tip=None):
        shown = f'<b>{E(str(val))}</b>' if val is not None else '<span class="na">-</span>'
        t = f' title="{E(tip)}"' if tip else ""
        return f'<div class="kv"><span{t}>{E(label)}</span><div>{shown}</div></div>'
    juried = None
    if v("passed") is not None and v("failed") is not None:
        juried = v("passed") + v("failed")
    rate = f'{round(100 * v("passed") / juried)}%' if juried else None
    body = (head
            + row("Settled", v("settled"))
            + row("Passed / failed / expired", f'{_n(v("passed"))} / {_n(v("failed"))} / {_n(v("expired"))}')
            + (row("Pass rate (juried)", rate) if rate is not None else "")
            + row("Grades cast", v("grades")) + row("Graders", v("graders"))
            + row("Rows at quorum", cc["quorum_rows"], tip="Pending rows that reached grade_quorum (authoritative)")
            + row("Effective graders (n_eff)", cc["n_eff"], tip="Herfindahl effective grader count; low means a few graders cast most grades")
            + row("Top grader share", f'{round(100 * cc["top_grader_share"])}%' if cc["top_grader_share"] is not None else None, tip="Share of this close's grades cast by the single busiest grader"))
    if not cc["available"]:
        body += ('<p class="na">Authoritative source unavailable; showing POAScan\'s derived close stats. The cross check '
                 'needs a /api/close-report read.</p>')
    extra = '<span class="na small" title="Read /api/close-report and /api/settled hourly">authoritative</span>'
    return card("Last close · authoritative", body, extra)


def _n(v): return str(v) if v is not None else "-"


# ---------------------------------------------------------------- expiry schedule (/api/expiry-schedule)
EXPIRY_PATH = "/api/expiry-schedule"
EXPIRY_BLOB = "expiry_schedule_auth"


def _int(v):
    try: return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError): return None


def _expiry_rows(sched):
    """[(close, pending)] sorted by close, from a list of rows, a dict wrapper around one, or a {close: count} map."""
    src = sched
    if isinstance(sched, dict):
        inner = _first(sched, "schedule", "expiry_schedule", "rows", "by_close", "pending_by_close")
        if isinstance(inner, (list, dict)): src = inner
    out = []
    if isinstance(src, dict):
        for k, v in src.items():
            c = _int(k); n = _int(_first(v, "pending", "count", "n") if isinstance(v, dict) else v)
            if c is not None and n is not None: out.append((c, n))
    elif isinstance(src, list):
        for r in src:
            if not isinstance(r, dict): continue
            c = _int(_first(r, "close", "epoch", "expires_close", "expiry_close", "expires"))
            n = _int(_first(r, "pending", "count", "n", "answers"))
            if c is not None and n is not None: out.append((c, n))
    return sorted(out)


def expiry_schedule(now=None):
    """{available, rows:[{close, pending}], total, next_close, as_of} from the cached /api/expiry-schedule copy."""
    d, ts = db.get_blob(EXPIRY_BLOB)
    if d is None:
        return dict(available=False, rows=[], total=None, next_close=None, as_of=None)
    rows = [dict(close=c, pending=n) for c, n in _expiry_rows(d)]
    return dict(available=True, rows=rows, total=sum(r["pending"] for r in rows),
                next_close=(rows[0]["close"] if rows else None), as_of=int(ts) if ts else None)


def expiry_crosscheck(now=None):
    """The authoritative schedule's total and next expiry close against POAScan's derived horizon (horizon.horizon).
    {available, verdict, authoritative_total, derived_total, authoritative_next, derived_next}. verdict match when the
    totals agree, differ when they do not, unknown when the schedule is unavailable or the derivation has no total."""
    sched = expiry_schedule(now)
    try:
        from . import horizon as H
        h = H.horizon(); d_total, d_next = h.get("total"), h.get("next_expiry")
    except Exception:
        d_total = d_next = None
    if not sched["available"]:
        return dict(available=False, verdict="unknown", authoritative_total=None, derived_total=d_total,
                    authoritative_next=None, derived_next=d_next)
    a_total = sched["total"]
    verdict = "unknown" if d_total is None else ("match" if a_total == d_total else "differ")
    return dict(available=True, verdict=verdict, authoritative_total=a_total, derived_total=d_total,
                authoritative_next=sched["next_close"], derived_next=d_next)


_EXPIRY_VERDICT = {"match": ("ok", "Matches derived horizon"), "differ": ("bad", "Differs from derived horizon"),
                   "unknown": ("warn", "Not cross checked")}


def render_expiry_card(now=None):
    """The authoritative forward expiry schedule: pending answers by expiry close, with the total cross checked against
    POAScan's derived horizon. Fails soft to a note pointing at the derived horizon when the schedule is unavailable."""
    from .ui import card, flag, table, E
    sched = expiry_schedule(now); cc = expiry_crosscheck(now)
    if not sched["available"]:
        body = ('<p class="na">Authoritative source unavailable; POAScan shows its derived expiry horizon on Governance, '
                'Queue. The forward curve needs a /api/expiry-schedule read.</p>')
        return card("Expiry schedule · authoritative", body, '<span class="na small">authoritative</span>')
    tone, word = _EXPIRY_VERDICT[cc["verdict"]]
    if cc["verdict"] == "match":
        det = "The authoritative total pending equals POAScan's derived horizon total."
    elif cc["verdict"] == "differ":
        det = f"Authoritative total {cc['authoritative_total']}, POAScan's derived horizon {cc['derived_total']}. A real signal worth a look."
    else:
        det = "POAScan has no derived horizon total to compare yet."
    head = f'<div class="kv"><span>Total pending</span><div><b>{sched["total"]}</b> {flag(word, det, tone=tone)}</div></div>'
    rows = [[f'E{E(str(r["close"]))}', f'{r["pending"]:,}', _bar(r["pending"], sched["rows"])] for r in sched["rows"]]
    tbl = table(["Expiry close", "Pending", ""], rows, cls="wrapt") if rows else '<p class="na">No pending cohorts scheduled to expire.</p>'
    extra = '<span class="na small" title="Read /api/expiry-schedule hourly">authoritative</span>'
    return card("Expiry schedule · authoritative", head + tbl, extra)


def _bar(n, rows):
    """A plain unicode block bar for one schedule row, scaled to the largest pending count (no CSS, no color)."""
    mx = max((r["pending"] for r in rows), default=0) or 1
    width = max(1, round(12 * n / mx)) if n else 0
    return f'<span class="mono dim" aria-hidden="true">{"█" * width}</span>'
