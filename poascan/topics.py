"""Community Topics (Agents, Community, Topics tab): what LabLeak is talking about, from the forum archive POASCAN already
keeps (forum_posts, forum_comments) and nothing else. No upstream request: a page view or API call reads POASCAN's own
tables, recomputed at most hourly and cached. Titles and counts only, never post bodies. Public communities only; the
archived community and the system/bot authors are left out, reusing governance.FORUM_SKIP_COMMUNITIES and
FORUM_SKIP_AUTHORS. Five panels: activity over time (posts plus comments per day, stacked by community), most replied
threads (7d / 30d / all), key conversations (most distinct Agents replying in 7d), top posters and repliers as Agents, and
keyword clusters from the titles (plain TF-IDF, no model calls, shown as term chips, no invented headlines)."""
import calendar, collections, math, re, time
from html import escape as E
from . import db, analytics as A
from .analytics import cached
from .ui import card, table, agent, bars, qtip, stat, intc, utc

METHOD = "/about#community-topics"
DAY = 86400
RANGES = [("7d", "7d", 7 * DAY), ("30d", "30d", 30 * DAY), ("all", "All", None)]
TOP_COMMUNITIES = 6          # activity chart stacks the busiest communities, the rest fold into "Other"
PALETTE = ("gold", "steel", "ember", "verd", "bone", "copper", "mute")   # one series colour per stacked community (ui.SERIES)
ACTIVITY_DAYS = 30           # the stacked chart shows the last N UTC days
LIST_CAP = 20                # lists cut at 20 rows with a reveal button
CLUSTERS_MIN, CLUSTERS_MAX = 8, 12
STOP = set(("the a an and or of to in for on is are be with that this it as at by from you your we our they their i my "
            "how what why when who which can do does did will would should could not no yes if then than so but just "
            "about into out up down new get got any all more most some one two poa agent agents").split())

def _public():
    """slug -> display name for public (non-archived) communities, minus the governance skip list."""
    from .governance import FORUM_SKIP_COMMUNITIES
    skip = set(FORUM_SKIP_COMMUNITIES)
    comms = db.get_blob("communities")[0] or []
    return {c["slug"]: (c.get("name") or c["slug"]) for c in comms if not int(c.get("archived") or 0) and c["slug"] not in skip}

def _toks(title):
    return [t for t in re.findall(r"[a-z0-9]{3,}", (title or "").lower()) if t not in STOP]

@cached("community_topics", 3600)
def topics():
    """Computed at most hourly from the forum archive (the hourly forum sync refreshes the tables; this reads them)."""
    from .governance import FORUM_SKIP_AUTHORS
    pub = _public()
    ok = lambda community, author: community in pub and (author or "") not in FORUM_SKIP_AUTHORS
    posts = db.q("SELECT id, community, title, author, author_public_id, created_at, comment_count, score FROM forum_posts")
    cmts = db.q("SELECT c.post_id, c.author, c.author_public_id, c.created_at, p.community FROM forum_comments c JOIN forum_posts p ON p.id=c.post_id")
    P = [p for p in posts if ok(p["community"], p["author"])]
    C = [c for c in cmts if ok(c["community"], c["author"])]
    now = time.time()
    pts = {p["id"]: A.utc_to_ts(p["created_at"]) for p in P}
    pmeta = {p["id"]: p for p in P}

    # Panel 1: activity per UTC day, stacked by the busiest communities (posts + comments together)
    act_tot = collections.Counter()
    for p in P: act_tot[p["community"]] += 1
    for c in C: act_tot[c["community"]] += 1
    top_comm = [s for s, _ in act_tot.most_common(TOP_COMMUNITIES)]
    bucket = lambda slug: slug if slug in top_comm else "other"
    buckets = top_comm + (["other"] if any(s not in top_comm for s in act_tot) else [])
    day = collections.defaultdict(lambda: collections.Counter())
    def _day(ts): return time.strftime("%Y-%m-%d", time.gmtime(ts))
    for p in P: day[_day(pts[p["id"]])][bucket(p["community"])] += 1
    for c in C:
        t = A.utc_to_ts(c["created_at"]); day[_day(t)][bucket(c["community"])] += 1
    days = sorted(day)[-ACTIVITY_DAYS:]
    activity = dict(days=days, buckets=buckets,
                    names=[pub.get(b, "Other") if b != "other" else "Other" for b in buckets],
                    rows=[[day[d][b] for b in buckets] for d in days])

    # comments grouped by post, with ts, for the thread panels
    by_post = collections.defaultdict(list)
    for c in C: by_post[c["post_id"]].append((A.utc_to_ts(c["created_at"]), c["author_public_id"]))

    def replied(span):
        t0 = now - span if span else 0
        out = []
        for pid, cs in by_post.items():
            if pid not in pmeta: continue
            n = sum(1 for t, _ in cs if t >= t0)
            if not n: continue
            last = max([t for t, _ in cs] + [pts[pid]])
            p = pmeta[pid]
            out.append(dict(id=pid, title=(p["title"] or "")[:90], community=p["community"],
                            replies=n, last_ts=int(last), author=p["author"], author_id=p["author_public_id"]))
        out.sort(key=lambda r: (-r["replies"], -r["last_ts"]))
        return out[:LIST_CAP]
    most_replied = {k: replied(span) for k, _, span in RANGES}

    # Panel 3: key conversations, most DISTINCT agents replying in the last 7d
    t7 = now - 7 * DAY; conv = []
    for pid, cs in by_post.items():
        if pid not in pmeta: continue
        who = {a for t, a in cs if t >= t7 and a}
        if len(who) < 2: continue
        last = max([t for t, _ in cs] + [pts[pid]]); p = pmeta[pid]
        conv.append(dict(id=pid, title=(p["title"] or "")[:90], community=p["community"], agents=len(who), last_ts=int(last)))
    conv.sort(key=lambda r: (-r["agents"], -r["last_ts"]))
    key_conversations = conv[:LIST_CAP]

    # Panel 4: top posters and repliers (reuses the same filtered sets as forum stats)
    nm = A.forum_names()
    def rank(counter):
        return [dict(address=a, name=nm.get(a), n=n) for a, n in counter.most_common(LIST_CAP) if a]
    posters = rank(collections.Counter(p["author_public_id"] for p in P))
    repliers = rank(collections.Counter(c["author_public_id"] for c in C))

    # Panel 5: keyword clusters from titles only (plain TF-IDF salience + co-occurrence, no invented headlines)
    titlesets = [set(_toks(p["title"])) for p in P]
    titlesets = [s for s in titlesets if s]
    N = len(titlesets) or 1
    df = collections.Counter(); cf = collections.Counter()
    for s in titlesets:
        for t in s: df[t] += 1
        for t in s: cf[t] += 1
    cand = [t for t in df if 3 <= df[t] <= 0.9 * N]   # drop only near-ubiquitous terms; TF-IDF idf already downweights common ones
    score = {t: cf[t] * math.log(1 + N / df[t]) for t in cand}
    co = collections.defaultdict(collections.Counter)
    for s in titlesets:
        ss = [t for t in s if t in score]
        for t in ss:
            for u in ss:
                if u != t: co[t][u] += 1
    clusters = []; used = set()
    for lead in sorted(cand, key=lambda t: -score[t]):
        if lead in used: continue
        mates = [u for u, _ in co[lead].most_common() if u not in used and u != lead][:3]
        terms = [lead] + mates
        clusters.append(dict(terms=terms, titles=df[lead]))
        used.update(terms)
        if len(clusters) >= CLUSTERS_MAX: break
    clusters = clusters[:CLUSTERS_MAX] if len(clusters) >= CLUSTERS_MIN else clusters

    return dict(updated=int(now), communities=len(pub), posts=len(P), comments=len(C),
                participants=len({p["author_public_id"] for p in P} | {c["author_public_id"] for c in C}),
                activity=activity, most_replied=most_replied, key_conversations=key_conversations,
                posters=posters, repliers=repliers, clusters=clusters)

# ---------------------------------------------------------------- HTML (Agents, Community, Topics tab)
def _q(qs, k, d=""): return ((qs or {}).get(k) or [d])[0]
def _thread(pid, title): return f'<a href="https://minepoa.com/lableak/#/post/{int(pid)}" rel="noopener noreferrer">#{int(pid)} {E(title or "")}</a>'
def _comm(slug): return f'<a href="https://minepoa.com/lableak/#/a/{E(slug)}" rel="noopener noreferrer">a/{E(slug)}</a>'

def section(qs=None):
    t = topics()
    tr = _q(qs, "tr", "7d"); tr = tr if tr in dict((k, lab) for k, lab, _ in RANGES) else "7d"
    link = lambda r: f'/agents/community?tab=topics&amp;tr={r}#threads'
    # activity chart stacked by community
    a = t["activity"]
    series = [(d[5:], a["rows"][i]) for i, d in enumerate(a["days"])] if a["days"] else []
    act = (bars(series, height=170, colors=PALETTE[:len(a["buckets"])], legend=a["names"], stacked=True)
           if series else '<p class="na">No forum activity yet.</p>')
    actcard = card("Activity · posts and comments per UTC day",
                   act, qtip("Posts plus comments per day, stacked by community. Archived community and system authors left out.", METHOD, "About Activity"), cls="gpc")
    # most replied threads (range selectable)
    rchips = "".join(f'<a href="{link(k)}" class="chip {"on" if k == tr else ""}">{lab}</a>' for k, lab, _ in RANGES)
    mr = t["most_replied"][tr]
    mrows = [[_thread(r["id"], r["title"]), _comm(r["community"]), agent(r["author_id"], r["author"] or ""), intc(r["replies"]), utc(r["last_ts"])] for r in mr]
    mrtab = (table(["Thread", "Community", "Author", "Replies", "Last activity"], mrows, cls="wrapt")
             if mrows else f'<p class="na">No replied threads in {tr}.</p>')
    threadcard = card(f"Most replied threads · {len(mr)}", f'<div class="chips">{rchips}</div>' + mrtab,
                      qtip("Threads ranked by replies in the selected window. Titles link to LabLeak.", METHOD, "About Most replied"), cls="histc", id="threads")
    # key conversations (7d)
    kc = t["key_conversations"]
    kcrows = [[_thread(r["id"], r["title"]), _comm(r["community"]), intc(r["agents"]), utc(r["last_ts"])] for r in kc]
    kctab = table(["Thread", "Community", "Agents", "Last activity"], kcrows, cls="wrapt") if kcrows else '<p class="na">No multi-Agent conversations in 7d.</p>'
    convcard = card(f"Key conversations · 7d · {len(kc)}", kctab,
                    qtip("Threads with the most distinct Agents replying in the last 7 days.", METHOD, "About Key conversations"), cls="histc")
    # posters / repliers
    def people(rows, unit):
        if not rows: return f'<p class="na">No {unit} yet.</p>'
        return table(["Agent", unit.title()], [[agent(r["address"], r["name"] or ""), intc(r["n"])] for r in rows], cls="wrapt")
    postcard = card(f"Top posters · {len(t['posters'])}", people(t["posters"], "posts"),
                    qtip("Agents by posts in public communities. System authors left out.", METHOD, "About Top posters"), cls="histc")
    replycard = card(f"Top repliers · {len(t['repliers'])}", people(t["repliers"], "replies"),
                     qtip("Agents by comments in public communities. System authors left out.", METHOD, "About Top repliers"), cls="histc")
    # clusters
    if t["clusters"]:
        chips = "".join('<span class="clink"><b>' + E(c["terms"][0]) + "</b>" + ("".join(" " + E(x) for x in c["terms"][1:]))
                        + f' <i class="dim">{intc(c["titles"])}</i></span>' for c in t["clusters"])
        clus = f'<div class="chips wrapchips">{chips}</div>'
    else:
        clus = '<p class="na">Not enough titles to cluster.</p>'
    cluscard = card("Topic clusters · titles", clus,
                    qtip("Keyword clusters from thread titles only (TF-IDF salience, plain terms, no invented headlines).", METHOD, "About Topic clusters"), cls="histc")
    st = f'<div class="stats four">{stat("Communities", intc(t["communities"]))}{stat("Posts", intc(t["posts"]))}{stat("Comments", intc(t["comments"]))}{stat("Participants", intc(t["participants"]))}</div>'
    foot = f'<p class="cov dim small">Titles and counts only, never post bodies. Public communities only. <a href="/api/v1/governance/community-topics">API</a> · <a href="/api/v1/governance/community-topics.csv">CSV</a> · <a href="{METHOD}">Method</a></p>'
    return (st
            + f'<div class="grid2">{actcard}{cluscard}</div>'
            + f'<div class="grid2">{threadcard}{convcard}</div>'
            + f'<div class="grid2">{postcard}{replycard}</div>'
            + foot)

# ---------------------------------------------------------------- API + CSV
def api(rng="7d"):
    rng = rng if rng in dict((k, lab) for k, lab, _ in RANGES) else "7d"
    t = topics()
    prof = lambda a: f"https://minepoa.com/lableak/#/u/{a}" if a else None
    mr = [dict(range=rng, id=r["id"], title=r["title"], community=r["community"], replies=r["replies"], last_ts=r["last_ts"],
               author=r["author"], author_id=r["author_id"], thread=f"https://minepoa.com/lableak/#/post/{r['id']}") for r in t["most_replied"][rng]]
    return dict(updated=t["updated"], range=rng, communities=t["communities"], posts=t["posts"], comments=t["comments"], participants=t["participants"],
                activity=t["activity"], rows=mr,
                key_conversations=[dict(r, thread=f"https://minepoa.com/lableak/#/post/{r['id']}") for r in t["key_conversations"]],
                posters=[dict(address=r["address"], name=r["name"], posts=r["n"], profile=prof(r["address"]) if r["name"] else None) for r in t["posters"]],
                repliers=[dict(address=r["address"], name=r["name"], replies=r["n"], profile=prof(r["address"]) if r["name"] else None) for r in t["repliers"]],
                clusters=t["clusters"],
                source="forum_posts and forum_comments (LabLeak archive POASCAN keeps); titles and counts only, never post bodies; public communities only, archived community and system authors left out",
                method="https://poascan.io" + METHOD)

CSV_FIELDS = ("range", "id", "title", "community", "author", "author_id", "replies", "last_ts", "thread")
def csv_rows(rows):
    """Flatten the most-replied rows from api()['rows'] for the generic CSV handler (mirrors graderpat.csv_rows)."""
    return [{k: r.get(k) for k in CSV_FIELDS} for r in rows]

# ---------------------------------------------------------------- Homepage forum pulse (story queue item 5)
@cached("forum_pulse", 3600)
def pulse():
    """Two terse facts for the homepage epoch/live section: the hottest public thread this epoch (most replies since the last
    close) and replies today. Forum archive only (local tables), cached hourly, public communities, system authors left out."""
    from .governance import FORUM_SKIP_AUTHORS
    pub = list(_public())
    if not pub: return dict(hottest=None, replies_today=0, posts_today=0)
    skip = list(FORUM_SKIP_AUTHORS)
    now = time.time()
    ers = A.epochs_raw() or []
    estart = max((int(e.get("ts") or 0) for e in ers), default=0) or int(now - 6 * 3600)   # this-epoch window = after the last close
    es = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(estart))
    t0 = time.strftime("%Y-%m-%d 00:00:00", time.gmtime(now))
    pc = ",".join("?" * len(pub)); sc = ",".join("?" * len(skip))
    cskip = f" AND c.author NOT IN ({sc})" if skip else ""   # exclude bot/system replies from the counts
    hot = db.q(f"SELECT p.id AS id, p.title AS title, p.community AS community, COUNT(c.id) AS n "
               f"FROM forum_posts p JOIN forum_comments c ON c.post_id=p.id "
               f"WHERE p.community IN ({pc}){cskip} AND c.created_at >= ? "
               f"GROUP BY p.id ORDER BY n DESC, MAX(c.created_at) DESC LIMIT 1", tuple(pub) + tuple(skip) + (es,))
    hottest = None
    if hot and hot[0]["n"]:
        r = hot[0]; hottest = dict(id=r["id"], title=_trim(r["title"]), community=r["community"], replies=r["n"])
    rt = (db.q1(f"SELECT COUNT(*) AS n FROM forum_comments c JOIN forum_posts p ON p.id=c.post_id "
                f"WHERE p.community IN ({pc}){cskip} AND c.created_at >= ?", tuple(pub) + tuple(skip) + (t0,)) or {}).get("n") or 0
    pt = (db.q1(f"SELECT COUNT(*) AS n FROM forum_posts WHERE community IN ({pc})"
                + (f" AND author NOT IN ({sc})" if skip else "") + " AND created_at >= ?", tuple(pub) + tuple(skip) + (t0,)) or {}).get("n") or 0
    return dict(hottest=hottest, replies_today=rt, posts_today=pt)

@cached("forum_reply_days", 3600)
def reply_days(n=30):
    """1.26.376 Heartbeat: public replies per UTC day for the last n days, [(day start ts, count)], oldest first, for the
    Replies today sparkline on Home. Forum archive only (local tables), cached hourly, system authors left out."""
    from .governance import FORUM_SKIP_AUTHORS
    pub = list(_public())
    if not pub: return []
    skip = list(FORUM_SKIP_AUTHORS); now = time.time()
    t0 = int(now // 86400 * 86400) - (n - 1) * 86400
    pc = ",".join("?" * len(pub)); sc = ",".join("?" * len(skip))
    cskip = f" AND c.author NOT IN ({sc})" if skip else ""
    rows = db.q(f"SELECT substr(c.created_at, 1, 10) AS d, COUNT(*) AS n FROM forum_comments c JOIN forum_posts p ON p.id=c.post_id "
                f"WHERE p.community IN ({pc}){cskip} AND c.created_at >= ? GROUP BY d", tuple(pub) + tuple(skip) + (time.strftime("%Y-%m-%d 00:00:00", time.gmtime(t0)),))
    by = {r["d"]: int(r["n"] or 0) for r in rows}
    return [(t0 + i * 86400, by.get(time.strftime("%Y-%m-%d", time.gmtime(t0 + i * 86400)), 0)) for i in range(n)]

def _trim(title, n=80):
    """Shorten a thread title to at most n characters at a word boundary, ending in an ellipsis (never mid-word).
    Trailing punctuation left by the cut is dropped, so a cut after 'removed),' ends as 'removed' plus the ellipsis."""
    t = " ".join((title or "").split())
    if len(t) <= n: return t
    cut = t[:n - 1]
    if not t[n - 1].isspace() and " " in cut: cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.-(/[{") + "\u2026"

def _plur(n, s="repl", one="y", many="ies"): return f"{int(n):,} {s}{one if n == 1 else many}"

def pulse_line():
    """One terse homepage line (empty string if nothing to show). Titles and counts only; links out to LabLeak + Topics."""
    p = pulse()
    if not p["hottest"] and not p["replies_today"]: return ""
    h, parts = p["hottest"], []
    if h:
        parts.append(f'<a class="fpt" href="https://minepoa.com/lableak/#/post/{int(h["id"])}" rel="noopener noreferrer"><span class="fpid">#{int(h["id"])}</span> {E(h["title"])}</a>')
    meta = ([f'{_plur(h["replies"])} this epoch'] if h else []) + ([f'{int(p["replies_today"]):,} today'] if p["replies_today"] else [])
    if meta: parts.append(f'<span class="fpm">{" · ".join(meta)}</span>')
    return f'<p class="fpulse"><span class="fpl">Forum pulse</span>{"".join(parts)}<a class="more" href="/agents/community?tab=topics">Topics →</a></p>'

# ---------------------------------------------------------------- Forum moments in the epoch timeline (story queue item 2)
@cached("epoch_threads", 3600)
def epoch_threads(prev_ts, close_ts, limit=3):
    """Up to N most-replied PUBLIC threads whose replies landed in this epoch's window (prev close, close]. Forum archive
    only, public communities, system/bot replies left out, titles and counts only."""
    pub = list(_public())
    if not pub or not close_ts: return []
    from .governance import FORUM_SKIP_AUTHORS
    skip = list(FORUM_SKIP_AUTHORS)
    a = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(prev_ts or 0)))
    b = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(close_ts)))
    pc = ",".join("?" * len(pub)); sc = ",".join("?" * len(skip))
    cskip = f" AND c.author NOT IN ({sc})" if skip else ""
    rows = db.q(f"SELECT p.id AS id, p.title AS title, p.community AS community, COUNT(c.id) AS n "
                f"FROM forum_posts p JOIN forum_comments c ON c.post_id=p.id "
                f"WHERE p.community IN ({pc}){cskip} AND c.created_at > ? AND c.created_at <= ? "
                f"GROUP BY p.id ORDER BY n DESC, MAX(c.created_at) DESC LIMIT ?", tuple(pub) + tuple(skip) + (a, b, int(limit)))
    return [dict(id=r["id"], title=_trim(r["title"]), community=r["community"], replies=r["n"]) for r in rows]

def epoch_threads_card(n, prev_ts, close_ts):
    """Small 'Forum moments' card for an epoch page, or empty string when no public thread saw replies in the window."""
    ts_ = epoch_threads(prev_ts, close_ts)
    if not ts_: return ""
    rows = "".join(f'<li><a class="fmt" href="https://minepoa.com/lableak/#/post/{int(t["id"])}" rel="noopener noreferrer"><span class="fpid">#{int(t["id"])}</span> {E(t["title"])}</a>'
                   f'<span class="dim fmm">{E(t["community"])} · {_plur(t["replies"])}</span></li>' for t in ts_)
    return card("Forum moments", f'<ul class="fmoments">{rows}</ul>')

# ---------------------------------------------------------------- Releases and notices to the threads that discuss them (story queue item 3)
# Ballots and a/proposals already link their own LabLeak threads (governance.BALLOTS topics and the Post column). The gap is
# the Releases and notices card, which linked nowhere. This points each release or notice at the PUBLIC forum thread(s) whose
# TITLE names it by an exact token (a version string or a notice id), high precision only: nothing is shown unless a title
# plainly carries the token, so there are no fuzzy or noisy guesses. Forum archive only, titles and counts, no bodies.
TOK_MIN = 4   # ignore tokens shorter than this; a version or notice id is longer, a bare 2 or 3 char token would be noisy

@cached("title_index", 3600)
def _title_index():
    """(id, title, lower, replies) for public, non-skip-author threads, built hourly for exact title-token matching."""
    from .governance import FORUM_SKIP_AUTHORS
    pub = list(_public())
    if not pub: return []
    skip = list(FORUM_SKIP_AUTHORS)
    pc = ",".join("?" * len(pub)); sc = ",".join("?" * len(skip))
    aexcl = f" AND author NOT IN ({sc})" if skip else ""
    cexcl = f" AND c.author NOT IN ({sc})" if skip else ""
    posts = db.q(f"SELECT id, title FROM forum_posts WHERE community IN ({pc}){aexcl}", tuple(pub) + tuple(skip))
    rc = {r["post_id"]: r["n"] for r in db.q(
        f"SELECT c.post_id AS post_id, COUNT(*) AS n FROM forum_comments c JOIN forum_posts p ON p.id=c.post_id "
        f"WHERE p.community IN ({pc}){cexcl} GROUP BY c.post_id", tuple(pub) + tuple(skip))}
    return [dict(id=p["id"], title=p["title"] or "", lower=(p["title"] or "").lower(), replies=rc.get(p["id"], 0)) for p in posts]

def _tok_re(tok):
    """Bounded, case-insensitive matcher for one token: not glued to another letter or digit, so '0.9.3' does not match
    inside '0.9.30' and a plain number only matches when the token carries its own '#'."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(tok) + r"(?![a-z0-9])")

def thread_links(tokens, exclude_ids=(), limit=2):
    """Up to `limit` public threads whose TITLE contains one of the exact tokens, most replied first. High precision: a
    token shorter than TOK_MIN is ignored and the match is bounded, so only a title that plainly names the release links."""
    toks = [t.lower() for t in (str(x).strip() for x in (tokens or []) if x) if len(t) >= TOK_MIN]
    if not toks: return []
    pats = [_tok_re(t) for t in toks]; ex = {int(x) for x in exclude_ids}
    hits = [r for r in _title_index() if r["id"] not in ex and any(p.search(r["lower"]) for p in pats)]
    hits.sort(key=lambda r: (-r["replies"], -r["id"]))
    return [dict(id=r["id"], title=_trim(r["title"]), replies=r["replies"]) for r in hits[:limit]]

def thread_chips(tokens, exclude_ids=()):
    """Inline LabLeak thread links for a release or notice (empty string when no public title names it). Reuses the terse
    dim styling, so the Releases and notices table gains meaning without a mostly empty extra column."""
    links = thread_links(tokens, exclude_ids)
    if not links: return ""
    inner = " ".join(f'<a href="https://minepoa.com/lableak/#/post/{int(x["id"])}" rel="noopener noreferrer" '
                     f'title="{E(x["title"])} · {_plur(x["replies"])}">#{int(x["id"])}</a>' for x in links)
    return f' <span class="dim small">· {inner}</span>'

# ---------------------------------------------------------------- Forum posts per day, for the Network charts (story queue item 4)
@cached("forum_posts_daily", 3600)
def posts_daily():
    """[(utc_midnight_ts, posts, comments)] per UTC day over all history, public communities, system authors left out.
    Feeds the 'Forum posts / day' small multiple on Network > Charts and its pop-out. Forum archive only, counts only."""
    from .governance import FORUM_SKIP_AUTHORS
    pub = list(_public())
    if not pub: return []
    skip = list(FORUM_SKIP_AUTHORS)
    pc = ",".join("?" * len(pub)); sc = ",".join("?" * len(skip))
    aexcl = f" AND author NOT IN ({sc})" if skip else ""
    cexcl = f" AND c.author NOT IN ({sc})" if skip else ""
    prows = db.q(f"SELECT substr(created_at, 1, 10) AS d, COUNT(*) AS n FROM forum_posts WHERE community IN ({pc}){aexcl} "
                 f"AND created_at IS NOT NULL GROUP BY d", tuple(pub) + tuple(skip))
    crows = db.q(f"SELECT substr(c.created_at, 1, 10) AS d, COUNT(*) AS n FROM forum_comments c JOIN forum_posts p ON p.id=c.post_id "
                 f"WHERE p.community IN ({pc}){cexcl} AND c.created_at IS NOT NULL GROUP BY d", tuple(pub) + tuple(skip))
    pm = {r["d"]: r["n"] for r in prows}; cm = {r["d"]: r["n"] for r in crows}
    out = []
    for d in sorted(set(pm) | set(cm)):
        try: ts = int(calendar.timegm(time.strptime(d, "%Y-%m-%d")))
        except (ValueError, TypeError): continue
        out.append((ts, pm.get(d, 0), cm.get(d, 0)))
    return out
