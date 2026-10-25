"""Governance facts and POAScan's Score per Agent (1.26.108).

Facts come from data POAScan already keeps: the archived close records of a segment (established_after,
established_removed, challenge_eligible, graders_served, settled with jury alignment, marks, audit.slashed, rewards,
attestations), the archived tx stream (challenge, grade-sealed, attest-batch) and the LabLeak mirror (posts and comments
by author_public_id, which is the poa1 address). No new upstream reads.

Score: 0 to 100, 100 best, deterministic, weights in govscore.json. Four parts: Standing, Grading, Forum, Consistency.
It is POAScan's own score, not an official minepoa grade. Method on /about#score.

v2 (1.26.138): Grading counts qualifying seals (seals that count toward quorum, from POAScan's store of minepoa's grading
list) and the qualifying rate, and Standing's level is at most unconfirmed_level while minepoa's list does not confirm an
Agent POAScan counts as established (Unconfirmed). Without the store it falls back to archived grade-sealed txs."""
import json, math, os, time, datetime as dt, collections
from . import db, analytics as A, segments as SG, standing as SD

GRADING_KEYS = {1: ("seats", "seals", "aligned"), 2: ("seats", "seals", "qual_rate", "aligned")}
CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "govscore.json")
def load_cfg(path=None):
    with open(path or CFG_PATH) as f: c = json.load(f)
    w = c["weights"]; assert abs(sum(w.values()) - 1) < 1e-9, "weights must sum to 1"
    for part in ("standing", "grading", "forum"):
        ks = {"standing": ("held", "level", "passed"), "grading": GRADING_KEYS.get(c.get("version", 1), GRADING_KEYS[1]), "forum": ("posts", "comments", "engaged")}[part]
        assert abs(sum(c[part][k] for k in ks) - 1) < 1e-9, f"{part} weights must sum to 1"
    if c.get("version", 1) >= 2: assert 0 <= c["standing"].get("unconfirmed_level", 0.5) <= 1, "unconfirmed_level is 0 to 1"
    return c
CFG = load_cfg()
PARTS = [("standing", "Standing"), ("grading", "Grading"), ("forum", "Forum"), ("consistency", "Consistency")]
TIP = "Built by POAScan from public network data. Not an official ranking. Meant to help explain how Agents become established."

def _uts(v):
    s = str(v or "").replace("Z", "+00:00").replace("T", " ")
    try:
        d = dt.datetime.fromisoformat(s)
        return int((d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp())
    except ValueError: return None

def _clamp(x, lo=0.0, hi=1.0): return max(lo, min(hi, x))
def _logpart(n, target): return _clamp(math.log1p(max(0, n)) / math.log1p(target)) if target else 0.0
def _shrunk(k, n, prior, m): return (k + prior * m) / (n + m) if (n + m) else prior

def close_facts(closes, trusted=frozenset(), resets=frozenset(), ttl=6):
    """Per address: facts from close records (any order in, folded in epoch order). Pure: no db reads.
    resets: epochs where standing starts fresh (the first close of each segment when closes span segments).
    Closes established uses the same fold as governance.segment_standing at every close: established_after adds,
    established_removed drops, a grading seat within ttl closes after the last removal counts, plus trusted graders seen."""
    eps = sorted(closes, key=lambda e: int(e.get("epoch", 0)))
    F = collections.defaultdict(lambda: dict(closes_established=0, added=0, removed=0, eligible=0, seat_closes=0, grades_served=0, jury_seats=0, jury_aligned=0,
                                             settled=0, passed=0, marks=0, slashed=0, rewards=0.0, paid_closes=0, attestations_received=0,
                                             first_close=None, last_close=None, active_closes=[], added_epochs=[], removed_epochs=[]))
    est, seat, rem = set(), {}, {}
    for e in eps:
        n = int(e.get("epoch", 0)); b = e.get("basis", {}) or {}
        touched = set()
        if n in resets: est, seat, rem = set(), {}, {}
        add = set(b.get("established_after") or []); gone = set(b.get("established_removed") or [])
        for a in add: F[a]["added"] += 1; F[a]["added_epochs"].append(n); touched.add(a)
        for a in gone: F[a]["removed"] += 1; F[a]["removed_epochs"].append(n)   # a removal is not activity
        est = (est - gone) | add
        for a in gone: rem[a] = n
        for a in b.get("challenge_eligible") or []: F[a]["eligible"] += 1; touched.add(a)
        for a, v in (b.get("graders_served") or {}).items():
            F[a]["seat_closes"] += 1; touched.add(a); seat[a] = n
            try: F[a]["grades_served"] += int(v)
            except (TypeError, ValueError): pass
        for x in b.get("settled") or []:
            fr = x.get("from")
            if fr: F[fr]["settled"] += 1; F[fr]["passed"] += 1 if x.get("passed") else 0; touched.add(fr)
            for j in x.get("jury") or []:
                g = j.get("grader")
                if g: F[g]["jury_seats"] += 1; F[g]["jury_aligned"] += 1 if j.get("aligned") else 0; touched.add(g); seat[g] = n
        for a, v in (b.get("marks") or {}).items():
            try: F[a]["marks"] += int(v)
            except (TypeError, ValueError): pass
        for a in ((b.get("audit") or {}).get("slashed") or []) + (b.get("slashed") or []):
            if isinstance(a, str): F[a]["slashed"] += 1
        for a, v in (e.get("rewards") or {}).items():
            try:
                if float(v) > 0: F[a]["rewards"] += float(v); F[a]["paid_closes"] += 1; touched.add(a)
            except (TypeError, ValueError): pass
        for a, v in (b.get("attestations") or {}).items():
            try: F[a]["attestations_received"] += int(v)
            except (TypeError, ValueError): pass
        held = est | {a for a, k in seat.items() if k > rem.get(a, -1) and k > n - ttl}
        held |= trusted & (set(seat) | held)
        for a in held: F[a]["closes_established"] += 1
        for a in touched:
            f = F[a]; f["active_closes"].append(n)
            if f["first_close"] is None: f["first_close"] = n
            f["last_close"] = n
    last = int(eps[-1].get("epoch", 0)) if eps else None
    return {a: f for a, f in F.items() if a and a.startswith("poa1")}, last, len(eps)

def tx_facts(where="", args=()):
    """Per address: challenge answers, grade-sealed and attest-batch txs sent (archived tx stream)."""
    out = collections.defaultdict(lambda: dict(challenges=0, seals=0, attest_txs=0))
    key = {"challenge": "challenges", "grade-sealed": "seals", "attest-batch": "attest_txs"}
    for r in db.q("SELECT from_addr AS a, type AS t, COUNT(*) AS n FROM txs WHERE type IN ('challenge','grade-sealed','attest-batch') AND from_addr IS NOT NULL" + where + " GROUP BY from_addr, type", args):
        out[r["a"]][key[r["t"]]] = r["n"]
    return out

def forum_facts(t0=None, t1=None, ballot_posts=frozenset(), operators=frozenset()):
    """Per address (author_public_id): posts, comments, proposals, ballot-thread comments, replies received from others,
    posts with a reply from someone else and with an operator reply, in [t0, t1)."""
    inwin = lambda t: t is not None and (t0 is None or t >= t0) and (t1 is None or t < t1)
    posts = [r for r in db.q("SELECT id, community, author_public_id AS a, created_at FROM forum_posts WHERE COALESCE(deleted, 0) = 0")]
    cm = db.q("SELECT id, post_id, author_public_id AS a, created_at FROM forum_comments")
    owner = {p["id"]: p["a"] for p in posts}
    F = collections.defaultdict(lambda: dict(posts=0, comments=0, proposals=0, ballot_comments=0, replies_received=0, posts_replied=0, posts_operator_replied=0))
    by_post = collections.defaultdict(set)
    for c in cm:
        t = _uts(c["created_at"])
        if not inwin(t): continue
        if c["a"]: F[c["a"]]["comments"] += 1
        if c["a"] and c["post_id"] in ballot_posts: F[c["a"]]["ballot_comments"] += 1
        o = owner.get(c["post_id"])
        if o and c["a"] and c["a"] != o: F[o]["replies_received"] += 1; by_post[c["post_id"]].add(c["a"])
    for p in posts:
        if not p["a"] or not inwin(_uts(p["created_at"])): continue
        f = F[p["a"]]; f["posts"] += 1; f["proposals"] += 1 if p["community"] == "proposals" else 0
        rs = by_post.get(p["id"]) or set()
        if rs: f["posts_replied"] += 1
        if rs & operators: f["posts_operator_replied"] += 1
    return {a: f for a, f in F.items() if a.startswith("poa1")}

def consistency(active, first, last_close, min_span):
    """Share of closes with activity from the Agent's first active close to the segment's last close, scaled down when
    that span is shorter than min_span closes (one good close is not a record)."""
    if first is None or last_close is None: return 0.0
    span = last_close - first + 1
    return _clamp(len(set(active)) / span) * _clamp(span / min_span)

def score(f, level, last_close, n_closes, cfg=None):
    """Parts and overall, 0 to 100 integers. f: merged facts; level: risk, watch, safe, norecord, system or none."""
    c = cfg or CFG; s, g, fo = c["standing"], c["grading"], c["forum"]
    span = (last_close - f["first_close"] + 1) if f.get("first_close") is not None and last_close is not None else 0
    held = f["closes_established"] / span if span else 0.0
    pen = min(s["penalty_cap"], s["removal_penalty"] * f["removed"] + s["slash_penalty"] * f["slashed"])
    lvv = s["level_values"].get(level, 0.0)
    if f.get("unconfirmed") and "unconfirmed_level" in s: lvv = min(lvv, s["unconfirmed_level"])   # v2: at most 0.5 while Unconfirmed
    st = 100 * (s["held"] * _clamp(held) + s["level"] * lvv + s["passed"] * _shrunk(f["passed"], f["settled"], s["prior_pass"], s["prior_n"]) * (1 if f["settled"] or f["eligible"] else 0)) - pen
    graded = f["seat_closes"] or f["seals"] or f["jury_seats"]
    qs = f.get("seals_qual", f["seals"]) if "qual_rate" in g else f["seals"]
    qr = (_shrunk(f.get("seals_listed_qual", 0), f.get("seals_listed", 0), g["prior_qual"], g["prior_qual_n"]) if graded else 0) if "qual_rate" in g else 0
    gr = 100 * (g["seats"] * _clamp(f["seat_closes"] / g["seat_closes_target"]) + g["seals"] * _logpart(qs, g["seals_target"]) + g.get("qual_rate", 0) * qr
                + g["aligned"] * (_shrunk(f["jury_aligned"], f["jury_seats"], g["prior_aligned"], g["prior_n"]) if graded else 0)) - min(g["penalty_cap"], g["mark_penalty"] * f["marks"])
    eng = _shrunk(f["posts_replied"], f["posts"], fo["prior_engaged"], fo["prior_n"]) if f["posts"] else 0.0
    eng = _clamp(eng + fo["operator_bonus"] * (f["posts_operator_replied"] > 0))
    fr = 100 * (fo["posts"] * _logpart(f["posts"], fo["posts_target"]) + fo["comments"] * _logpart(f["comments"], fo["comments_target"]) + fo["engaged"] * eng)
    cs = 100 * consistency(f["active_closes"], f["first_close"], last_close, c["consistency"]["min_span"])
    parts = {k: int(round(_clamp(v, 0, 100))) for k, v in (("standing", st), ("grading", gr), ("forum", fr), ("consistency", cs))}
    overall = sum(c["weights"][k] * _clamp(v, 0, 100) for k, v in (("standing", st), ("grading", gr), ("forum", fr), ("consistency", cs)))
    return dict(score=int(round(_clamp(overall, 0, 100))), **parts)

EMPTY_TX = dict(challenges=0, seals=0, attest_txs=0)
EMPTY_FORUM = dict(posts=0, comments=0, proposals=0, ballot_comments=0, replies_received=0, posts_replied=0, posts_operator_replied=0)

def grading_inputs(f, listed):
    """v2 seal inputs on facts f (seals: archived grade-sealed txs). listed: (seals, qualifying) for the Agent in POAScan's
    store of minepoa's grading list over the same window, or None. seals_qual: the archived seals scaled by the listed
    qualifying rate, never below the qualifying seals listed; without a listing, the archived seals (fallback)."""
    n, q = listed or (0, 0)
    f["seals_listed"], f["seals_listed_qual"] = n, q
    f["qual_rate"] = (q / n) if n else None
    f["seals_qual"] = max(int(round(f["seals"] * q / n)), q) if n else f["seals"]
    f["seals_source"] = "minepoa_grading" if n else "archived_txs"
    return f

def build(closes, where, args, t0, t1, levels, ballot_posts, operators, trusted, resets=frozenset(), ttl=6, listed=None, unconfirmed=frozenset()):
    """{address: facts + level + score parts} for a set of closes, a tx filter and a forum window. listed: {address: (seals,
    qualifying)} from the grading list store; unconfirmed: established Agents minepoa's list does not confirm."""
    listed = listed or {}
    cf, last, n = close_facts(closes, trusted, resets, ttl)
    tf = tx_facts(where, args); ff = forum_facts(t0, t1, ballot_posts, operators)
    out = {}
    for a in set(cf) | set(tf) | set(ff):
        if not a.startswith("poa1"): continue
        f = dict(cf.get(a) or _blank())
        f.update(tf.get(a) or EMPTY_TX); f.update(ff.get(a) or EMPTY_FORUM)
        if f["first_close"] is None and not (f["challenges"] or f["seals"] or f["attest_txs"] or f["posts"] or f["comments"]): continue
        lv = levels.get(a, "none"); f["level"] = lv
        grading_inputs(f, listed.get(a)); f["unconfirmed"] = a in unconfirmed
        f.update(score(f, lv, last, n))
        out[a] = f
    return out, last, n

def _blank():
    return dict(closes_established=0, added=0, removed=0, eligible=0, seat_closes=0, grades_served=0, jury_seats=0, jury_aligned=0, settled=0, passed=0, marks=0,
                slashed=0, rewards=0.0, paid_closes=0, attestations_received=0, first_close=None, last_close=None, active_closes=[], added_epochs=[], removed_epochs=[])
