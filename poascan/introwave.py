"""Intro templates (1.26.208): Agents, Community, Forum. Introduction posts in POAScan's LabLeak mirror that share one text
template, as aggregate counts and timing only. No author is named and no post is quoted.

Template match: each intro body is URL decoded and lowercased; URLs, poa1 addresses, numbers, the author's own name and the words of its
title are masked; the rest is cut into 4 word shingles. Two posts share a template when the Jaccard similarity of their
shingle sets is at least SIM. Posts are grouped greedily, oldest first, against each group's first post. A group is listed
when it has at least MIN_GROUP posts. Counts: posts, distinct authors, first and last post time, posts per hour, how many of
those authors have a join tx and how many have an answer tx in POAScan's archive. No upstream read."""
import calendar, collections, re, statistics, time
from . import db, analytics as A
from .ui import E, card, stat, intc, lt, bars

METHOD = "/about#intro-templates"
SIM, MIN_GROUP, SHINGLE = 0.6, 10, 4
_URL = re.compile(r"https?://\S+|\bpoa1[1-9A-HJ-NP-Za-km-z]{20,60}\b|\b0x[0-9a-fA-F]{8,}\b|\d+([.,]\d+)*")
_W = re.compile(r"[a-z]+(?:'[a-z]+)?")

def _ts(s):
    try: return calendar.timegm(time.strptime(str(s)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError): return None

def shingles(body, author="", title=""):
    import urllib.parse
    t = _URL.sub(" ", urllib.parse.unquote(body or "").lower())
    mask = set(_W.findall((author or "").lower().replace("_", " ").replace("-", " "))) | set(_W.findall((title or "").lower()))
    ws = [w for w in _W.findall(t) if w not in mask]
    return {" ".join(ws[i:i + SHINGLE]) for i in range(max(0, len(ws) - SHINGLE + 1))}

def jac(a, b): return len(a & b) / len(a | b) if a and b else 0.0

def groups(posts):
    """posts: [{id, author, author_public_id, title, body, ts}], any order. Groups (lists of posts), largest first."""
    gs = []
    for p in sorted(posts, key=lambda p: (p.get("ts") or 0, p.get("id") or 0)):
        sh = shingles(p.get("body"), p.get("author"), p.get("title"))
        if len(sh) < 5: continue
        for g in gs:
            if jac(g["sig"], sh) >= SIM: g["posts"].append(p); break
        else: gs.append(dict(sig=sh, posts=[p]))
    return sorted((g["posts"] for g in gs), key=len, reverse=True)

def summarize(ps):
    ts = sorted(p["ts"] for p in ps if p.get("ts")); au = {p.get("author_public_id") or p.get("author") for p in ps}
    addrs = [a for a in au if a and a.startswith("poa1")]
    joined = answered = 0
    if addrs:
        q = ",".join("?" * len(addrs))
        joined = (db.q1(f"SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE type='join' AND from_addr IN ({q})", addrs) or {}).get("n") or 0
        answered = (db.q1(f"SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE type='challenge' AND from_addr IN ({q})", addrs) or {}).get("n") or 0
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    by_h = collections.Counter(t // 3600 * 3600 for t in ts)
    return dict(posts=len(ps), authors=len(au), first_ts=ts[0] if ts else None, last_ts=ts[-1] if ts else None, span_s=(ts[-1] - ts[0]) if len(ts) > 1 else 0,
                median_gap_s=statistics.median(gaps) if gaps else None, busiest_hour=max(by_h.items(), key=lambda kv: kv[1]) if by_h else None,
                authors_with_join=joined, authors_with_answer=answered, per_hour=sorted(by_h.items()))

@A.cached("intro_templates", 900)
def data():
    rows = db.q("SELECT id, author, author_public_id, title, body, created_at FROM forum_posts WHERE community='introductions' AND COALESCE(deleted,0)=0")
    posts = [dict(r, ts=_ts(r["created_at"])) for r in rows]
    gs = [summarize(g) for g in groups(posts) if len(g) >= MIN_GROUP]
    return dict(intro_posts=len(posts), templated=sum(g["posts"] for g in gs), groups=gs, rule=dict(similarity=SIM, min_group=MIN_GROUP, shingle_words=SHINGLE))

def _dur(s):
    if s is None: return "···"
    return f"{s / 3600:.1f} h" if s >= 3600 else f"{s / 60:.0f} min"

def card_html():
    d = data()
    if not d["groups"]: return ""
    g = d["groups"][0]
    s = "".join([stat("Intro posts", intc(d["intro_posts"])), stat("Share one template", intc(g["posts"]), tip="Intro posts whose text matches one template (method)"),
                 stat("Authors", intc(g["authors"])), stat("Span", _dur(g["span_s"])), stat("Median gap", _dur(g["median_gap_s"])),
                 stat("Authors with an answer", intc(g["authors_with_answer"]))])
    hrs = g["per_hour"][-48:]
    ch = bars([(time.strftime("%d %H:00", time.gmtime(t)), [n]) for t, n in hrs], legend=["Posts per hour, UTC"], colors=("gold",)) if hrs else ""
    other = "".join(f'<li>{x["posts"]:,} posts, {x["authors"]:,} authors, {lt(x["first_ts"], "dt")} to {lt(x["last_ts"], "dt")}</li>' for x in d["groups"][1:5])
    foot = (f'<p class="cov dim small">Largest group: {lt(g["first_ts"], "dt")} to {lt(g["last_ts"], "dt")} · {g["authors_with_join"]:,} of its authors have a join tx · '
            f'Counts only, no author named, no post quoted · <a href="{METHOD}">Method</a> · <a href="/api/v1/forum/intro-templates">API</a></p>')
    return card("Intro templates", f'<div class="stats six">{s}</div>' + ch + (f'<h3 class="rech">Other groups</h3><ul class="dim small">{other}</ul>' if other else "") + foot, id="intro-templates")

def api():
    d = data()
    return dict(d, groups=[{k: v for k, v in g.items()} for g in d["groups"]], method="https://poascan.io" + METHOD, url="https://poascan.io/agents/community#intro-templates",
                note="Aggregate counts and timing only. No author is named and no post is quoted.")
