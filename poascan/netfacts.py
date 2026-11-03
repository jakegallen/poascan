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


def _accounts_src(facts):
    return _first(facts, "system_accounts", "system_accounts_liveness", "accounts", "system")


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
            out.append(dict(id=str(_first(v, "id", "name", "label") or "?"), address=_first(v, "address", "addr", "account"), live=_live(v)))
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
        v = _first(facts, "established", "established_set", "set", "agents")
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


# ---------------------------------------------------------------- API block (no upstream read)
def api_block(now=None):
    facts, ts = cached(now)
    cc = crosscheck(facts)
    return dict(available=facts is not None, as_of=ts, stale=stale(now),
                economics={e["key"]: e["value"] for e in economics(facts)},
                system_accounts=system_accounts(facts), trusted_graders=trusted_graders(facts),
                hashes=facts_hashes(facts), crosscheck=cc, method="https://poascan.io" + METHOD)


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
    econ = ('<div class="sy">' + "".join(f'<div><span>{E(e["label"])}</span>{ev(e["value"])}</div>' for e in econ_rows) + '</div>'
            if facts is not None else '<p class="na">No economics params without a facts read.</p>')

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
