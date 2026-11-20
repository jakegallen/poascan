"""Community Topics tab (Agents, Community, Topics): activity stacked by community, most replied threads (7d/30d/all),
key conversations (distinct Agents in 7d), top posters and repliers, and title-only keyword clusters. All from the forum
archive (forum_posts, forum_comments), titles and counts only, public communities only, archived community and system
authors left out. HTML + API + CSV. Usage: python3 tools/topics_test.py (temp database, no network)."""
import os, sys, tempfile, time, json
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, topics as TP, views as V, server as SV, governance as GV

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NOW = int(time.time())
def ts(ago): return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(NOW - ago))
DAY = 86400
A1, A2, A3, A4 = ("poa1" + c * 40 for c in "ABCD")   # public ids

def seed():
    db.init()
    db.put_blob("params", {"trusted_graders": []})
    db.put_blob("communities", [{"slug": "general", "name": "General", "archived": 0}, {"slug": "bugs", "name": "Bugs", "archived": 0},
                                {"slug": "proposals", "name": "Proposals", "archived": 0}, {"slug": "old", "name": "Old", "archived": 1},
                                {"slug": "poa-archive", "name": "Archive", "archived": 0}])
    posts = [
        # id, community, title, author, pid, created_at(ago), score, comment_count
        (1, "general", "grading seat payout question", "Ann", A1, ts(2 * DAY), 3, 5),
        (2, "bugs", "grading bug on seat payout", "Bob", A2, ts(3 * DAY), 1, 4),
        (3, "proposals", "payout curve proposal for grading", "Cy", A3, ts(10 * DAY), 8, 3),
        (4, "general", "seat assignment delay", "Ann", A1, ts(20 * DAY), 2, 2),
        (5, "bugs", "wallet binding seat issue", "Dee", A4, ts(40 * DAY), 0, 1),
        (6, "general", "grading rubric payout clarity", "Bob", A2, ts(1 * DAY), 4, 6),
        (7, "proposals", "new payout epoch grading rule", "Cy", A3, ts(5 * DAY), 5, 2),
        (8, "old", "archived community post should be hidden", "Ann", A1, ts(2 * DAY), 9, 9),          # archived community -> excluded
        (9, "poa-archive", "poa-archive post should be hidden", "Bob", A2, ts(2 * DAY), 9, 9),         # skip community -> excluded
        (10, "general", "spam from the bot should be hidden", "Live-GrokBot", "poa1Z" + "Z" * 39, ts(1 * DAY), 0, 0),  # system author -> excluded
        (11, "general", "seat payout grading payout seat", "Dee", A4, ts(2 * DAY), 1, 3),
        (12, "bugs", "grading seat wallet payout", "Ann", A1, ts(6 * DAY), 2, 2),
    ]
    db.write("INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body) "
             "VALUES(?,?,?,?,?,?,?,?,0,0,1,?)", [(p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], "SECRET_BODY_" + str(p[0])) for p in posts], many=True)
    # comments: distinct repliers for key conversations; recent for 7d
    cid = 100; cmts = []
    def add(post, author, pid, ago):
        nonlocal cid; cid += 1; cmts.append((cid, post, None, author, pid, ts(ago), 0, "SECRET_COMMENT_BODY", None))
    # post 1: three distinct repliers in 7d (key conversation)
    add(1, "Bob", A2, 1 * DAY); add(1, "Cy", A3, 1 * DAY); add(1, "Dee", A4, 2 * DAY)
    # post 6: two distinct repliers in 7d
    add(6, "Ann", A1, 1 * DAY); add(6, "Cy", A3, 1 * DAY)
    # post 2: one replier, older (30d window)
    add(2, "Dee", A4, 20 * DAY)
    # post 3: repliers but old (only in 'all')
    add(3, "Ann", A1, 40 * DAY); add(3, "Bob", A2, 40 * DAY)
    # grok bot comment (excluded) and poa-archive comment (excluded by community)
    add(1, "Live-GrokBot", "poa1Z" + "Z" * 39, 1 * DAY); add(9, "Ann", A1, 1 * DAY)
    db.write("INSERT INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body,edited_at) VALUES(?,?,?,?,?,?,?,?,?)", cmts, many=True)
    A._cache.clear()

seed()
t = TP.topics()
check("archived community, poa-archive and the system author are excluded from posts", t["posts"] == 9)   # 12 - old - poa-archive - grokbot
check("comments exclude the grok bot and the poa-archive thread", all(True for _ in [0]) and t["comments"] == 8)  # 10 added - grokbot - poa-archive-thread
check("participants counted from public posters and repliers", t["participants"] == 4)

sec = TP.section({})
for panel in ("Activity", "Most replied threads", "Key conversations", "Top posters", "Top repliers", "Topic clusters"):
    check(f"panel present: {panel}", panel in sec)
check("titles and counts only, never the post or comment body", "SECRET_BODY" not in sec and "SECRET_COMMENT_BODY" not in sec)
check("threads link out to LabLeak posts", "minepoa.com/lableak/#/post/1" in sec)
check("communities link out to LabLeak", "minepoa.com/lableak/#/a/general" in sec)
check("says Agents (profiles), not Accounts", "Accounts" not in sec)
check("equal-height side by side cards (grid2)", sec.count('class="grid2"') >= 3)
check("no em or en dash", "\u2014" not in sec and "\u2013" not in sec)
check("the hidden archived/spam posts do not appear", "should be hidden" not in sec)

# key conversations: post 1 (3 distinct) ranks above post 6 (2 distinct); only multi-Agent threads in 7d
kc = t["key_conversations"]
check("key conversations rank by distinct Agents in 7d", kc and kc[0]["id"] == 1 and kc[0]["agents"] == 3 and all(r["agents"] >= 2 for r in kc))

# range selection: 7d has fewer replied threads than all
mr7 = t["most_replied"]["7d"]; mrall = t["most_replied"]["all"]
check("most replied 7d is a subset of all and ranked by replies", len(mr7) <= len(mrall) and mr7 and mr7[0]["replies"] >= (mr7[-1]["replies"]))
check("most replied rows carry title, community, author id and last activity", all(set(("id", "title", "community", "author_id", "replies", "last_ts")) <= set(r) for r in mr7))

# posters / repliers
check("top posters and repliers are non-empty Agent lists with counts", t["posters"] and t["repliers"] and all("n" in r and "address" in r for r in t["posters"]))
check("lists cut at 20 rows", len(t["most_replied"]["all"]) <= 20 and len(t["posters"]) <= 20)

# clusters: real title terms only, counts, no invented headlines (grading/payout/seat appear)
terms = {x for c in t["clusters"] for x in c["terms"]}
check("keyword clusters use real title terms with counts", t["clusters"] and all(c.get("titles") for c in t["clusters"]) and ({"grading", "payout", "seat"} & terms))

# API + CSV through the governance dispatch
d = SV.governance_api("/api/governance/community-topics", {})
check("API default range 7d, rows + panels + source/method", d["range"] == "7d" and "rows" in d and d["method"].endswith("#community-topics") and "never post bodies" in d["source"])
d30 = SV.governance_api("/api/governance/community-topics", {"range": ["30d"]})
check("API honours range", d30["range"] == "30d")
try: SV.governance_api("/api/governance/community-topics", {"range": ["1y"]}); ok = False
except SV.BadRequest: ok = True
check("API 400 on bad range", ok)
try: SV.governance_api("/api/governance/community-topics", {"x": ["1"]}); ok = False
except SV.BadRequest: ok = True
check("API 400 on unknown parameter", ok)
cs = SV.to_csv(TP.csv_rows(d["rows"]))
check("CSV flat columns, no nested JSON, no body", cs.splitlines()[0].startswith("range,id,title,community,author,author_id,replies,last_ts,thread") and "{" not in cs and "SECRET" not in cs)

# tab wiring
check("Topics is a Community sub-tab", "topics" in dict(V.COMMUNITY_TABS) and dict(V.COMMUNITY_TABS)["topics"] == "Topics")
check("GOV_API registers the endpoint params", SV.GOV_API.get("/api/governance/community-topics") == {"range"})

# Forum and Topics read one definition: public communities (not archived, not poa-archive), no system author, no deleted post or its comments
A._cache.clear(); f = A.forum(); t = TP.topics()
check("Forum and Topics agree on communities, posts, comments and participants",
      (f["communities"], f["posts"], f["comments"], f["participants"]) == (t["communities"], t["posts"], t["comments"], t["participants"]) and f["communities"] == 3)
db.write("UPDATE forum_posts SET deleted=1 WHERE id=1")   # post 1 had 4 comments in public communities (one by the system author)
A._cache.clear(); f = A.forum(); t = TP.topics()
check("a deleted post and its comments leave both Forum and Topics, which still agree",
      t["posts"] == 8 and t["comments"] == 5 and (f["posts"], f["comments"], f["participants"]) == (t["posts"], t["comments"], t["participants"]))
check("governance forum_stats skips archived communities too", "old" in GV.skip_communities() and "poa-archive" in GV.skip_communities())

A._cache.clear(); f = A.forum()
check("Forum Boards: archived boards and poa-archive are out, the rows add up to the chips",
      {c["slug"] for c in f["per_community"]} == {"general", "bugs", "proposals"} and sum(c["posts"] for c in f["per_community"]) == f["posts"] and sum(c["comments"] for c in f["per_community"]) == f["comments"])
from poascan import agentshub as _AH
_fh = _AH.forum()
check("Forum Boards table has no archived board and no Status column", "a/old" not in _fh and "a/poa-archive" not in _fh and ">Status<" not in _fh and "a/general" in _fh)
src = open(os.path.join(ROOT, "poascan", "topics.py")).read()
check("topics.py: no em or en dash, says Agents not Accounts, reads only titles", "\u2014" not in src and "\u2013" not in src and "Accounts" not in src and "p[\"body\"]" not in src and "c[\"body\"]" not in src)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
