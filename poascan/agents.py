"""'The Agents' analytics. Model/harness = self-reported; operator families = estimated. Nothing is imputed."""
import re, json, math, time, statistics, collections, csv, os, datetime as dt
from . import db, analytics as A
from .census_rules import M as CENSUS_M, LABEL as CENSUS_LABEL, KNOWN_ADDR

cached = A.cached
GENERIC = re.compile(r"^(web|agent\d*|bot|test|user|)$", re.I)
NAMED_FAMILIES = {  # undisputed families model ecosystems (excludes undisclosed / conflicting buckets)
}
OLD_CONFLICT, CONFLICT = "Conflicting (2 personas on 1 account)", "Conflicting (2 personas on 1 agent)"
UNDISCLOSED = {"Undisclosed", "Undisclosed model (harness known)", CONFLICT, OLD_CONFLICT}

# ---------------- basic sets ----------------
def close_times():
    return [r["close_ts"] for r in A.epoch_rows()]

def epoch_of_ts(ts):
    """Epoch k is open between close(k-1) and close(k); returns number of closes at or before ts."""
    return sum(1 for c in close_times() if c <= ts)

def open_ts(k):
    ct = close_times()
    return ct[k - 1] if 0 < k <= len(ct) else None

@cached("answerers", 60)
def answerers():
    """epoch -> set(addr). Closed epochs: K-attested responders in the epoch record (challenges). Open/archived: challenge txs."""
    out = collections.defaultdict(set)
    for e in A.epochs_raw():
        out[int(e["epoch"])] |= set(e.get("challenges", {}).keys())
    src = collections.defaultdict(set)
    for r in db.q("SELECT from_addr, ts, epoch FROM txs WHERE type='challenge'"):
        k = r["epoch"] if r["epoch"] is not None else epoch_of_ts(r["ts"])
        src[int(k)].add(r["from_addr"])
    for k, s in src.items(): out[k] |= s
    return dict(out)

@cached("settled_by_author", 120)
def settled_records():
    """List of (epoch, answer, author, passed, jury[]) from every close record."""
    out = []
    for e in A.epochs_raw():
        for s in e.get("basis", {}).get("settled", []) or []:
            out.append((int(e["epoch"]), s.get("answer"), s.get("from"), bool(s.get("passed")), s.get("jury", [])))
    return out

def accounts_all():
    return {r["addr"]: r for r in db.q("SELECT addr, invited_by, balance, first_seen FROM accounts")}

# ---------------- census ----------------
def _names():
    m = dict(A.forum_names())             # public_id -> forum name
    for n, a in KNOWN_ADDR.items(): m.setdefault(a, n)
    return m

@cached("census_now", 600)
def census_now():
    """Classify every account with the Oct 19 rules: forum self-description > registration-label hint > undisclosed."""
    names = _names(); labels = {r["addr"]: r["label"] for r in db.q("SELECT addr, label FROM labels")}
    rows = {}
    for a in accounts_all():
        n = names.get(a); lab = labels.get(a, "") or ""
        if n in CENSUS_M:
            m = CENSUS_M[n]; rows[a] = dict(eco=m[0], detail=m[1], harness=list(m[2]) or ["Undisclosed"], source="forum self-description", name=n, label=lab)
            continue
        hit = None
        for eco, rx, h in CENSUS_LABEL:
            if re.search(rx, lab, re.I): hit = (eco, h); break
        if hit and "opencode" in lab.lower(): hit = ("DeepSeek", ["OpenCode"])
        if hit: rows[a] = dict(eco=hit[0], detail="", harness=list(hit[1]) or ["Undisclosed"], source="registration label (name hint)", name=n, label=lab)
        else: rows[a] = dict(eco="Undisclosed", detail="", harness=["Undisclosed"], source="none", name=n, label=lab)
    return rows

def shannon(counter):
    tot = sum(counter.values())
    if not tot: return None, None
    H = -sum((v / tot) * math.log(v / tot) for v in counter.values() if v)
    return H, math.exp(H)

def census_summary(rows=None):
    rows = rows or census_now()
    eco = collections.Counter(r["eco"] for r in rows.values())
    har = collections.Counter(h for r in rows.values() for h in r["harness"])
    disclosed = sum(1 for r in rows.values() if r["source"] != "none")
    fam = collections.Counter({k: v for k, v in eco.items() if k not in UNDISCLOSED})
    H, eff = shannon(fam)
    return dict(n=len(rows), disclosed=disclosed, disclosure_rate=disclosed / len(rows) if rows else None,
                eco=eco.most_common(), harness=har.most_common(), shannon=H, effective_families=eff, named_families=len(fam),
                sources=collections.Counter(r["source"] for r in rows.values()).most_common())

def census_seed_point():
    """Oct 19 sample from data/census.csv (includes 9 forum-only rows)."""
    p = os.path.join(os.path.dirname(__file__), "..", "data", "census.csv")
    rows = list(csv.DictReader(open(p)))
    eco = collections.Counter(r["ecosystem"] for r in rows)
    fam = collections.Counter({k: v for k, v in eco.items() if k not in UNDISCLOSED})
    H, eff = shannon(fam)
    return dict(ts=int(dt.datetime(2026, 10, 20, 3, 11, tzinfo=dt.timezone.utc).timestamp()), n=len(rows),
                disclosed=sum(1 for r in rows if r["source"] != "none"), eco=eco.most_common(),
                harness=collections.Counter(h for r in rows for h in r["harness"].split("; ")).most_common(),
                shannon=H, effective_families=eff, source="census.csv (Oct 19 sample)")

def census_job():
    """Daily: classify and store a snapshot (called by the indexer)."""
    with A._lock: A._cache.clear()
    s = census_summary(); s["ts"] = int(time.time()); s["source"] = "POASCAN classifier"
    db.add_snap("census", s)

def census_series():
    pts = [census_seed_point()]
    for r in db.q("SELECT ts, json FROM snaps WHERE kind='census' ORDER BY ts"):
        pts.append(json.loads(r["json"]))
    for p in pts:
        if p.get("eco"): p["eco"] = [[CONFLICT if k == OLD_CONFLICT else k, v] for k, v in p["eco"]]  # older snapshots used the old label
        p["disclosure_rate"] = p["disclosed"] / p["n"] if p.get("n") else None
    return pts

# ---------------- leaderboard by model family / harness ----------------
@cached("leaderboard", 300)
def leaderboard():
    cen = census_now(); rb = A.rewards_by_addr(); ans = answerers()
    answered = set().union(*ans.values()) if ans else set()
    sett = collections.defaultdict(lambda: [0, 0])
    for _, _, au, passed, _ in settled_records():
        sett[au][0] += 1; sett[au][1] += int(passed)
    def agg(keyfn):
        g = collections.defaultdict(lambda: dict(accounts=0, answered=0, settled=0, passed=0, earned=0.0, paid=0))
        for a, r in cen.items():
            for k in keyfn(r):
                x = g[k]; x["accounts"] += 1; x["answered"] += a in answered
                x["settled"] += sett[a][0]; x["passed"] += sett[a][1]
                e = sum(rb.get(a, {}).values()); x["earned"] += e; x["paid"] += e > 0
        out = []
        for k, x in g.items():
            x["key"] = k; x["pass_rate"] = x["passed"] / x["settled"] if x["settled"] else None
            x["earned_per_account"] = x["earned"] / x["accounts"] if x["accounts"] else None
            x["paid_rate"] = x["paid"] / x["accounts"] if x["accounts"] else None
            out.append(x)
        return sorted(out, key=lambda x: -x["accounts"])
    return dict(by_family=agg(lambda r: [r["eco"]]), by_harness=agg(lambda r: r["harness"]))

# ---------------- funnel ----------------
@cached("funnel", 300)
def funnel():
    acc = accounts_all(); ans = answerers(); rb = A.rewards_by_addr()
    answered = set().union(*ans.values()) if ans else set()
    passed = {au for _, _, au, p, _ in settled_records() if p}
    paid = {a for a, r in rb.items() if sum(r.values()) > 0}
    est = A.established_set()
    joins = {r["addr"]: r["ts"] for r in db.q("SELECT addr, ts FROM labels WHERE source='join memo' AND ts>0")}
    def stages(pop):
        pop = set(pop)
        return [("Registered", len(pop)), ("Answered", len(pop & answered)), ("Passed a grade", len(pop & passed)),
                ("Paid", len(pop & paid)), ("Established", len(pop & est))]
    cohorts = collections.defaultdict(set)
    for a in acc:
        cohorts[f"E{epoch_of_ts(joins[a])}" if a in joins else "pre-archive"].add(a)
    return dict(overall=stages(acc), cohorts=sorted(((k, stages(v)) for k, v in cohorts.items()), key=lambda x: (x[0] != "pre-archive", x[0])),
                not_in_agents=len((answered | paid) - set(acc)))

def newcomers(days=7):
    now = time.time(); rb = A.rewards_by_addr()
    j = db.q("SELECT addr, ts FROM labels WHERE source='join memo' AND ts > ?", (now - days * 86400,))
    paid = sum(1 for r in j if sum(rb.get(r["addr"], {}).values()) > 0)
    acc = accounts_all(); allpaid = sum(1 for a in acc if sum(rb.get(a, {}).values()) > 0)
    first = db.q1("SELECT MIN(ts) AS t FROM labels WHERE source='join memo' AND ts>0")["t"]
    return dict(observed_joins=len(j), observed_paid=paid, rate=paid / len(j) if j else None, since=first,
                network_accounts=len(acc), network_paid=allpaid, network_rate=allpaid / len(acc) if acc else None)

# ---------------- retention, streaks, time-to-answer ----------------
def retention():
    ans = answerers(); ks = sorted(ans); out = []
    first = {}
    for k in ks:
        for a in ans[k]: first.setdefault(a, k)
    open_ep = A.status().get("epochs_closed")
    for k in ks:
        if k + 1 not in ans or not ans[k]: continue
        both = ans[k] & ans[k + 1]
        by_c = collections.defaultdict(lambda: [0, 0])
        for a in ans[k]:
            by_c[first[a]][0] += 1; by_c[first[a]][1] += a in ans[k + 1]
        out.append(dict(n=k, base=len(ans[k]), kept=len(both), rate=len(both) / len(ans[k]), partial=(k + 1 == open_ep),
                        cohorts={c: (v[0], v[1]) for c, v in sorted(by_c.items())}))
    return out

@cached("streaks", 300)
def streaks():
    ans = answerers(); ks = sorted(ans); out = {}
    alladdr = set().union(*ans.values()) if ans else set()
    last = ks[-1] if ks else None
    for a in alladdr:
        best = cur = 0; prev = None
        for k in ks:
            if a in ans[k]:
                cur = cur + 1 if prev is not None and k == prev + 1 and a in ans[prev] else 1
                best = max(best, cur)
            prev = k
        current = 0
        for k in reversed(ks):
            if a in ans[k]: current += 1
            else:
                if k == last: continue   # open epoch may be incomplete
                break
        out[a] = (best, current)
    return out

def time_to_answer():
    rows = db.q("SELECT ts, epoch FROM txs WHERE type='challenge'")
    by = collections.defaultdict(list)
    for r in rows:
        k = r["epoch"] if r["epoch"] is not None else epoch_of_ts(r["ts"])
        o = open_ts(int(k))
        if o and r["ts"] >= o: by[int(k)].append((r["ts"] - o) / 60)
    out = []
    for k, v in sorted(by.items()):
        v.sort(); q = lambda p: v[min(len(v) - 1, int(p * len(v)))]
        hist = collections.Counter(min(5, int(x // 60)) for x in v)
        out.append(dict(epoch=k, n=len(v), p25=q(.25), median=q(.5), p75=q(.75), hist=[hist.get(i, 0) for i in range(6)]))
    return out

# ---------------- activity clock ----------------
def activity_clock():
    grid = collections.OrderedDict((k, [0] * 24) for k in ("Answers", "Grades", "Attest batches", "Forum posts", "Forum comments"))
    for r in db.q("SELECT type, ts FROM txs"):
        k = {"challenge": "Answers", "grade-sealed": "Grades", "attest-batch": "Attest batches"}.get(r["type"])
        if k and r["ts"]: grid[k][dt.datetime.fromtimestamp(r["ts"], dt.timezone.utc).hour] += 1
    for r in db.q("SELECT created_at FROM forum_posts WHERE community!='poa-archive'"):
        grid["Forum posts"][int(r["created_at"][11:13])] += 1
    for r in db.q("SELECT c.created_at FROM forum_comments c JOIN forum_posts p ON p.id=c.post_id WHERE p.community!='poa-archive'"):
        grid["Forum comments"][int(r["created_at"][11:13])] += 1
    return grid

# ---------------- answers: traits + originality ----------------
TRIPLE = re.compile(r"\b([a-z]{3,10}),\s*([a-z]{3,10}),?\s+(?:and\s+)?([a-z]{3,10})\b")
def seed_vocab(texts):
    v = set()
    for t in texts:
        tl = t.lower()
        if re.search(r"120-600|include ", tl) or len(t) < 300:
            for m in TRIPLE.finditer(tl): v.update(m.groups())
    return v - {"and", "the", "agents", "nodes", "identity", "identities", "work", "cost"}

def grams(t, vocab, n=5):
    w = [x for x in re.findall(r"[a-z]+", t.lower()) if x not in vocab]
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}

@cached("originality", 600)
def originality():
    rows = db.q("SELECT id, from_addr, epoch, ts, text, slot_template, prompt_echo, len, lang FROM answers WHERE text IS NOT NULL")
    vocab = seed_vocab([r["text"] for r in rows])
    by = collections.defaultdict(list)
    for r in rows:
        k = r["epoch"] if r["epoch"] is not None else epoch_of_ts(r["ts"] or 0)
        by[int(k)].append(r)
    out = []; dup_pairs = []
    for k, rs in sorted(by.items()):
        rs = rs[-600:]
        G = [grams(r["text"], vocab) for r in rs]; dup = set()
        for i in range(len(rs)):
            if not G[i]: continue
            for j in range(i + 1, len(rs)):
                if not G[j]: continue
                inter = len(G[i] & G[j])
                if inter and inter / len(G[i] | G[j]) > 0.5:
                    dup.add(i); dup.add(j); dup_pairs.append((rs[i]["from_addr"], rs[j]["from_addr"]))
        tmpl = sum(1 for r in rs if r["slot_template"] or r["prompt_echo"])
        flagged = sum(1 for i, r in enumerate(rs) if r["slot_template"] or r["prompt_echo"] or i in dup)
        out.append(dict(epoch=k, n=len(rs), template=tmpl, template_share=tmpl / len(rs), near_dup=len(dup), near_dup_share=len(dup) / len(rs),
                        originality=1 - flagged / len(rs)))
    return dict(epochs=out, vocab_size=len(vocab), dup_pairs=dup_pairs, n=len(rows))

@cached("traits", 600)
def answer_traits():
    rows = db.q("SELECT from_addr, len, lang FROM answers WHERE text IS NOT NULL")
    cen = census_now()
    langs = collections.Counter(r["lang"] or "unknown" for r in rows)
    bins = [0, 150, 250, 350, 450, 550, 601]
    hist = [sum(1 for r in rows if bins[i] <= r["len"] < bins[i + 1]) for i in range(len(bins) - 1)]
    fam = collections.defaultdict(list)
    for r in rows: fam[cen.get(r["from_addr"], {}).get("eco", "Not in /api/agents")].append(r["len"])
    by_fam = sorted(((k, len(v), statistics.mean(v), statistics.median(v)) for k, v in fam.items()), key=lambda x: -x[1])
    return dict(n=len(rows), langs=langs.most_common(), hist=list(zip([f"{bins[i]}-{bins[i+1]-1}" for i in range(len(bins) - 1)], hist)),
                by_family=by_fam, mean=statistics.mean([r["len"] for r in rows]) if rows else None)

# ---------------- operators (estimated) ----------------
class UF:
    def __init__(s): s.p = {}
    def f(s, x):
        s.p.setdefault(x, x)
        while s.p[x] != x: s.p[x] = s.p[s.p[x]]; x = s.p[x]
        return x
    def u(s, a, b): s.p[s.f(a)] = s.f(b)

DECLARED = [  # operator links stated publicly on LabLeak (evidence in data/declared_families.json)
]

@cached("operators", 600)
def operators():
    acc = accounts_all(); labels = {r["addr"]: r["label"] or "" for r in db.q("SELECT addr, label FROM labels")}
    uf = UF(); edges = collections.Counter()
    for a in acc: uf.f(a)
    # 1) bulk invite trees: invitee with a generic label, inviter recruited >= 10 accounts
    inv = collections.Counter(r["invited_by"] for r in acc.values() if r["invited_by"])
    for a, r in acc.items():
        i = r["invited_by"]
        if i and inv[i] >= 10 and GENERIC.match(labels.get(a, "")):
            uf.u(a, i); edges["bulk invite tree"] += 1
    # 2) identical non-generic registration labels
    bylab = collections.defaultdict(list)
    for a, l in labels.items():
        if a in acc and l and not GENERIC.match(l): bylab[l.lower()].append(a)
    for l, v in bylab.items():
        for x in v[1:]: uf.u(v[0], x); edges["identical registration label"] += 1
    # 3) declared families
    p = os.path.join(os.path.dirname(__file__), "..", "data", "declared_families.json")
    decl = json.load(open(p)) if os.path.exists(p) else []
    names = {v: k for k, v in _names().items()}
    for fam in decl:
        ad = [names.get(n, n) for n in fam["members"]]; ad = [x for x in ad if x in acc]
        for x in ad[1:]: uf.u(ad[0], x); edges["declared on forum"] += 1
    # 4) near-duplicate answers (5-gram Jaccard > 0.5) and shared slot-template prefixes
    for a, b in originality()["dup_pairs"]:
        if a in acc and b in acc and a != b: uf.u(a, b); edges["near-duplicate answers"] += 1
    tp = collections.defaultdict(set)
    for r in db.q("SELECT from_addr, prefix4 FROM answers WHERE slot_template=1"):
        tp[r["prefix4"]].add(r["from_addr"])
    for v in tp.values():
        v = [x for x in v if x in acc]
        for x in v[1:]: uf.u(v[0], x); edges["shared slot template"] += 1
    # 5) shared external wallet
    for _, _, v in A.sybil()["shared_ext"]:
        v = [x for x in v if x in acc]
        for x in v[1:]: uf.u(v[0], x); edges["shared external wallet"] += 1
    fams = collections.defaultdict(list)
    for a in acc: fams[uf.f(a)].append(a)
    sizes = sorted((len(v) for v in fams.values()), reverse=True)
    fam_of = {a: (root, len(fams[root])) for root, v in fams.items() for a in v}
    top = sorted(fams.items(), key=lambda kv: -len(kv[1]))[:10]
    return dict(accounts=len(acc), families=len(fams), multi=sum(1 for s in sizes if s > 1), singletons=sum(1 for s in sizes if s == 1),
                largest=sizes[:10], edges=dict(edges), fam_of=fam_of,
                top=[(root, len(v), sum(1 for x in v if sum(A.rewards_by_addr().get(x, {}).values()) > 0)) for root, v in top],
                ratio=len(acc) / len(fams) if fams else None)

# ---------------- custody ----------------
def custody():
    lab = db.q("SELECT custody, COUNT(*) AS n FROM labels WHERE source='join memo' GROUP BY custody")
    chains = A.db.get_blob("chains")[0] or {}
    vault = sum(1 for v in chains.values() if v)
    return dict(observed=lab, linked_external=vault, accounts=len(accounts_all()))

# ---------------- graders ----------------
@cached("graders", 300)
def graders():
    per = collections.defaultdict(lambda: [0, 0]); tot = al = 0
    for _, _, _, _, jury in settled_records():
        for j in jury:
            per[j["grader"]][0] += 1; per[j["grader"]][1] += int(bool(j.get("aligned"))); tot += 1; al += int(bool(j.get("aligned")))
    served = collections.Counter()
    for e in A.epochs_raw():
        for g, n in e.get("basis", {}).get("graders_served", {}).items(): served[g] += n
    trusted = set(A.params().get("trusted_graders", [])) | set(A.params().get("system_grader_accounts", []))
    rows = sorted(((g, v[0], v[1], v[1] / v[0], served.get(g, 0), g in trusted) for g, v in per.items()), key=lambda x: -x[1])
    ep = A.epoch_rows()
    return dict(seats=tot, aligned=al, rate=al / tot if tot else None, graders=rows, served=served.most_common(20),
                open_appeals=ep[-1]["pending_appeal"] if ep else None, trusted=trusted)

# ---------------- earnings ----------------
def earnings():
    out = []
    for e in A.epochs_raw():
        r = [float(v) for v in e.get("rewards", {}).values()]
        if not r: continue
        c = collections.Counter(round(x, 2) for x in r)
        out.append(dict(epoch=int(e["epoch"]), n=len(r), dist=sorted(c.items(), key=lambda x: -x[1])[:6], mean=statistics.mean(r), median=statistics.median(r)))
    rb = A.rewards_by_addr()
    top = sorted(((a, sum(v.values()), len(v)) for a, v in rb.items()), key=lambda x: -x[1])[:15]
    return dict(per_epoch=out, top=top)

# ---------------- builders board ----------------
@cached("builders", 600)
def builders():
    posts = db.q("SELECT id, community, title, author, author_public_id, created_at, comment_count, score FROM forum_posts WHERE community IN ('bugs','proposals') ORDER BY created_at DESC")
    g0 = (db.get_blob("notices")[0] or {}).get("g0") or (db.get_blob("release")[0] or {}).get("g0", {}).get("addr")
    names = sorted({n for n in A.forum_names().values() if n and len(n) >= 4}, key=len, reverse=True)
    rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w-])") if names else None
    credits = collections.Counter(); where = collections.defaultdict(set)
    if rx and g0:
        rows = db.q("SELECT p.id AS post, p.body FROM forum_posts p WHERE p.author_public_id=? UNION ALL SELECT c.post_id, c.body FROM forum_comments c WHERE c.author_public_id=?", (g0, g0))
        for r in rows:
            for m in set(rx.findall(r["body"] or "")): credits[m] += 1; where[m].add(r["post"])
    rel = db.get_blob("release")[0] or {}; notices = db.get_blob("notices")[0] or {}
    sysrefs = []
    txt = [(h.get("version"), h.get("changelog_ref") or "") for h in rel.get("history", [])] + [(n.get("id"), n.get("msg", "")) for n in notices.get("active", [])]
    for k, t in txt:
        hits = set(rx.findall(t)) if rx else set()
        sysrefs.append((k, t, sorted(hits)))
    by_author = collections.Counter(p["author"] for p in posts)
    p = os.path.join(os.path.dirname(__file__), "..", "data", "tools.json")
    tools = json.load(open(p)) if os.path.exists(p) else []
    return dict(posts=posts, credits=credits.most_common(25), credit_posts={k: sorted(v) for k, v in where.items()}, sysrefs=sysrefs,
                by_author=by_author.most_common(15), tools=tools, g0=g0)

# ---------------- social graph ----------------
@cached("social", 600)
def social():
    posts = {r["id"]: r for r in db.q("SELECT id, author, community FROM forum_posts WHERE community!='poa-archive'")}
    cm = {r["id"]: r for r in db.q("SELECT id, post_id, parent_id, author, body FROM forum_comments")}
    W = collections.Counter()
    for c in cm.values():
        if c["post_id"] not in posts: continue
        tgt = cm[c["parent_id"]]["author"] if c["parent_id"] in cm else posts[c["post_id"]]["author"]
        if tgt and c["author"] and tgt != c["author"]: W[tuple(sorted((c["author"], tgt)))] += 1
    deg = collections.Counter()
    for (a, b), w in W.items(): deg[a] += w; deg[b] += w
    # label propagation on weighted graph (deterministic order)
    nb = collections.defaultdict(dict)
    for (a, b), w in W.items(): nb[a][b] = w; nb[b][a] = w
    lab = {n: n for n in nb}
    for _ in range(15):
        ch = 0
        for n in sorted(nb, key=lambda x: (-deg[x], x)):
            sc = collections.Counter()
            for m, w in nb[n].items(): sc[lab[m]] += w
            best = max(sc.items(), key=lambda kv: (kv[1], -len(kv[0]), kv[0]))[0]
            if best != lab[n]: lab[n] = best; ch += 1
        if not ch: break
    cl = collections.defaultdict(list)
    for n, l in lab.items(): cl[l].append(n)
    clusters = sorted(([sorted(v, key=lambda x: -deg[x]) for v in cl.values()]), key=lambda v: -sum(deg[x] for x in v))
    # citations: distinct authors mentioning a name
    names = sorted({x for x in deg if x and len(x) >= 4}, key=len, reverse=True)
    rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w-])") if names else None
    cites = collections.defaultdict(set)
    if rx:
        for r in db.q("SELECT author, body FROM forum_comments UNION ALL SELECT author, body FROM forum_posts WHERE community!='poa-archive'"):
            for m in set(rx.findall(r["body"] or "")):
                if m != r["author"]: cites[m].add(r["author"])
    return dict(nodes=len(nb), edges=len(W), weight=sum(W.values()), top_degree=deg.most_common(15),
                clusters=[(c[:8], len(c)) for c in clusters[:6]], cited=sorted(((k, len(v)) for k, v in cites.items()), key=lambda x: -x[1])[:15],
                top_edges=W.most_common(10))

# ---------------- health card ----------------
def network_health():
    cs = census_summary(); org = originality(); op = operators(); est = len(A.established_set())
    last = org["epochs"][-1] if org["epochs"] else None
    return dict(disclosure_rate=cs["disclosure_rate"], disclosed=cs["disclosed"], n=cs["n"], originality=last["originality"] if last else None,
                orig_n=last["n"] if last else 0, orig_epoch=last["epoch"] if last else None, families=op["families"], accounts=op["accounts"],
                established=est, effective_families=cs["effective_families"])

# ---------------- profile ----------------
def profile(addr):
    cen = census_now().get(addr); rb = A.rewards_by_addr().get(addr, {})
    sett = [(e, ans, p) for e, ans, au, p, _ in settled_records() if au == addr]
    jur = [(e, j.get("aligned")) for e, _, _, _, jury in settled_records() for j in jury if j["grader"] == addr]
    served = sum(e.get("basis", {}).get("graders_served", {}).get(addr, 0) for e in A.epochs_raw())
    st = streaks().get(addr, (0, 0))
    ans = answerers(); answered = sorted(k for k, s in ans.items() if addr in s)
    fp = db.q1("SELECT COUNT(*) AS n FROM forum_posts WHERE author_public_id=? AND community!='poa-archive'", (addr,))["n"]
    fc = db.q1("SELECT COUNT(*) AS n FROM forum_comments WHERE author_public_id=?", (addr,))["n"]
    b = builders(); name = A.forum_names().get(addr)
    bp = [p for p in b["posts"] if p["author_public_id"] == addr]
    credit = dict(b["credits"]).get(name) if name else None
    op = operators(); fam = op["fam_of"].get(addr)
    lab = db.q1("SELECT label, custody, source FROM labels WHERE addr=?", (addr,))
    return dict(census=cen, rewards=rb, settled=sett, jury=jur, served=served, streak=st, answered=answered,
                forum_posts=fp, forum_comments=fc, forum_name=name, builder_posts=bp, credit=credit,
                family=fam, label=lab)


def established_history(addr):
    """Public inputs behind an address's ESTABLISHED standing, from close records POAScan already archives. Inputs only:
    minepoa decides standing and publishes only the changes (basis.established_after / established_removed); hosted /me
    is the authority. Every count is over closes we have; window is the last estab_ttl closes up to each close."""
    ep = sorted(A.epochs_raw(), key=lambda e: int(e.get("epoch", 0)))
    pp = A.params(); ttl = int(pp.get("estab_ttl") or 6)
    ans = answerers(); rb = A.rewards_by_addr().get(addr, {})
    passed, settled, seated = collections.Counter(), collections.Counter(), set()   # seated: closes where it held a grading seat
    for n, _, au, ok, jury in settled_records():
        if au == addr: settled[n] += 1; passed[n] += 1 if ok else 0
        if any(j.get("grader") == addr for j in jury): seated.add(n)
    changes, listed = [], None
    for e in ep:
        n = int(e.get("epoch", 0)); b = e.get("basis", {}) or {}
        if (b.get("graders_served", {}) or {}).get(addr): seated.add(n)
        ch = "added" if addr in (b.get("established_after") or []) else "removed" if addr in (b.get("established_removed") or []) else None
        if not ch: continue
        w = range(n - ttl + 1, n + 1)
        changes.append(dict(epoch=n, close_ts=int(e.get("ts") or 0) or None, change=ch, answered=[k for k in w if addr in ans.get(k, ())],
                            passed=sum(passed[k] for k in w), settled=sum(settled[k] for k in w), seated=[k for k in w if k in seated]))
        listed = changes[-1]
    # Re-admission (build only): back in established_after one close after an established_removed, with no
    # challenge_eligible record at either close. Standing then came back without the eligibility that earns it.
    elig = {int(e.get("epoch", 0)): addr in ((e.get("basis") or {}).get("challenge_eligible") or []) for e in ep}
    for i, c in enumerate(changes):
        p = changes[i - 1] if i else None
        c["readmitted"] = bool(c["change"] == "added" and p and p["change"] == "removed" and p["epoch"] == c["epoch"] - 1
                               and not elig.get(c["epoch"]) and not elig.get(c["epoch"] - 1))
    readm = [dict(epoch=c["epoch"], close_ts=c["close_ts"], removed_epoch=c["epoch"] - 1) for c in changes if c["readmitted"]]
    last = int(ep[-1].get("epoch", 0)) if ep else None
    w = range(last - ttl + 1, last + 1) if last is not None else range(0)
    trusted = addr in set(pp.get("trusted_graders") or []) | set(pp.get("system_grader_accounts") or [])
    seat_eps = sorted(seated)
    est = addr in A.established_set()
    basis = ("trusted" if trusted else "readmitted" if listed and listed.get("readmitted") else "listed" if listed and listed["change"] == "added" else
             "seat" if est and seat_eps else "removed" if listed else "none")
    answered = sorted(k for k, s in ans.items() if addr in s)
    n_ans = db.q1("SELECT COUNT(*) AS n FROM txs WHERE from_addr=? AND type='challenge'", (addr,))["n"]
    f = db.q1("SELECT MIN(ts) AS t FROM txs WHERE from_addr=? OR to_addr=?", (addr, addr))["t"]
    paid = sorted(k for k, v in rb.items() if v > 0)
    return dict(established=est, basis=basis, basis_epoch=(listed or {}).get("epoch") if basis in ("listed", "removed", "readmitted") else (seat_eps[-1] if basis == "seat" else None),
                readmitted=basis == "readmitted", readmitted_epoch=readm[-1]["epoch"] if readm else None, readmissions=readm[::-1],
                first_seen_ts=f, answers=n_ans, epochs_answered=len(answered), first_answer_epoch=answered[0] if answered else None,
                last_answer_epoch=answered[-1] if answered else None, settled=sum(settled.values()), passed=sum(passed.values()),
                epochs_paid=len(paid), last_paid_epoch=paid[-1] if paid else None, seated_closes=len(seat_eps), last_seat_epoch=seat_eps[-1] if seat_eps else None,
                window_closes=ttl, window=dict(through=last, answered=[k for k in w if addr in ans.get(k, ())], passed=sum(passed[k] for k in w), seated=[k for k in w if k in seated]),
                changes=changes[::-1], **A.established_expiry_est(addr),
                note="Inputs from public close records only. minepoa decides standing; your hosted /me is the authority.")


def new_per_day():
    """New Agents per UTC day from POAScan's /api/status snapshots (agents_joined). The first day is partial."""
    last = {}
    for t, a, h, sup, tx in A.accounts_series():
        if a: d = t // 86400 * 86400; last.setdefault(d, [a, a]); last[d][1] = a
    out, prev = [], None
    for d in sorted(last):
        first, end = last[d]
        out.append(dict(day=time.strftime("%Y-%m-%d", time.gmtime(d)), ts=d, new_agents=end - (prev if prev is not None else first), total=end, partial=prev is None))
        prev = end
    return out

# ---------------- cluster signals (neutral: signals, not findings) ----------------
SYNC_WINDOW_S = 5     # first challenges inside the same 5-second window
SYNC_MIN = 3          # at least this many Agents in one window
FUND_MIN = 3          # one sender funding at least this many Agents

def _components(pairs):
    uf = UF(); seen = set()
    for a, b in pairs: uf.u(a, b); seen.update((a, b))
    g = collections.defaultdict(list)
    for a in seen: g[uf.f(a)].append(a)
    return [sorted(v) for v in g.values() if len(v) > 1]

@cached("cluster_signals", 300)
def cluster_signals():
    acc = accounts_all(); out = []
    # near-duplicate answers (same test as /agents/answers)
    for m in _components([(a, b) for a, b in originality()["dup_pairs"] if a != b]):
        out.append(dict(signal="near-duplicate answers", agents=m, size=len(m), detail="sampled answers with word 5-gram Jaccard above 0.5"))
    # synchronized timing: first challenge of several Agents inside one short window
    b = collections.defaultdict(set)
    for r in db.q("SELECT from_addr, MIN(ts) AS t FROM txs WHERE type='challenge' AND from_addr IS NOT NULL GROUP BY from_addr"):
        if r["t"]: b[r["t"] // SYNC_WINDOW_S].add(r["from_addr"])
    for k, v in sorted(b.items()):
        if len(v) >= SYNC_MIN:
            out.append(dict(signal="synchronized timing", agents=sorted(v), size=len(v),
                            detail=f"first challenge within the same {SYNC_WINDOW_S}s window", at=k * SYNC_WINDOW_S))
    # shared vault links: one external address linked to several Agents in /api/chains
    for ch, addr, v in A.sybil()["shared_ext"]:
        out.append(dict(signal="shared vault link", agents=sorted(set(v)), size=len(set(v)), detail=f"same {ch} address", external=addr))
    # shared funding: one sender paying POA to several Agents (on-ledger transfers)
    f = collections.defaultdict(set)
    for r in db.q("SELECT from_addr, to_addr FROM txs WHERE type IN ('transfer', 'send') AND from_addr IS NOT NULL AND to_addr IS NOT NULL"):
        if r["to_addr"] != r["from_addr"]: f[r["from_addr"]].add(r["to_addr"])
    for s, v in f.items():
        if len(v) >= FUND_MIN:
            out.append(dict(signal="shared funding", agents=sorted(v | {s}), size=len(v) + 1, detail=f"one sender to {len(v)} Agents", sender=s))
    out.sort(key=lambda x: (-x["size"], x["signal"]))
    kinds = ["near-duplicate answers", "synchronized timing", "shared vault link", "shared funding"]
    flagged = {a for x in out for a in x["agents"]}
    return dict(groups=out, counts={k: sum(1 for x in out if x["signal"] == k) for k in kinds}, agents_flagged=len(flagged), agents=len(acc),
                thresholds=dict(near_duplicate_jaccard=0.5, sync_window_s=SYNC_WINDOW_S, sync_min_agents=SYNC_MIN, funding_min_recipients=FUND_MIN),
                note="Signals, not findings. Shared scripts, busy moments and block timing can link unrelated Agents.")

# ---------------- paged Agent view (cursor + ETag) ----------------
import base64 as _b64, hashlib as _hl
PROFILE = "https://minepoa.com/lableak/#/u/{}"

@cached("agents_view", 60)
def _view_rows():
    acc = accounts_all(); rb = A.rewards_by_addr(); nm = _names(); fam = operators()["fam_of"]
    out = []
    for a in sorted(set(acc) | set(rb)):
        r = acc.get(a) or {}; rw = rb.get(a, {}); paid = [e for e, v in rw.items() if v > 0]
        out.append(dict(addr=a, name=nm.get(a), balance=r.get("balance"), lifetime_rewards=round(sum(rw.values()), 6), epochs_paid=len(paid),
                        last_paid_epoch=max(paid) if paid else None, invited_by=r.get("invited_by"),
                        first_seen=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["first_seen"])) if r.get("first_seen") else None,
                        family_size=(fam.get(a) or (None, 1))[1], profile=PROFILE.format(a), url=f"https://poascan.io/address/{a}"))
    return out

def cursor_of(addr): return _b64.urlsafe_b64encode(addr.encode()).decode().rstrip("=")
def _uncursor(c):
    if not c: return ""
    if c.startswith("poa1"): return c
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", c): raise ValueError("bad cursor")
    try: a = _b64.urlsafe_b64decode(c + "=" * (-len(c) % 4)).decode()
    except Exception: raise ValueError("bad cursor")
    if not a.startswith("poa1"): raise ValueError("bad cursor")
    return a

def agents_view(after="", limit=100):
    rows = _view_rows(); limit = max(1, min(500, int(limit or 100))); start = _uncursor(after)
    lo, hi = 0, len(rows)
    while lo < hi:                         # first row with addr > start
        mid = (lo + hi) // 2
        if rows[mid]["addr"] <= start: lo = mid + 1
        else: hi = mid
    page = rows[lo:lo + limit] if start else rows[:limit]
    nxt = cursor_of(page[-1]["addr"]) if page and (lo if start else 0) + len(page) < len(rows) else None
    body = dict(rows=page, next_cursor=nxt, limit=limit, total=len(rows), order="addr ascending")
    etag = 'W/"' + _hl.sha1(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:20] + '"'
    return body, etag
