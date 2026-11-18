"""Forum activity on the Agent profile (POASCAN story queue item 2). A "Forum activity" card on the Agent profile shows the
Agent's public post and reply counts, the threads they started that drew the most replies, and the Agents they reply to
most. Forum archive only, public communities, system authors left out of reply counts, titles and counts only, never a
body. Usage: python3 tools/agent_forum_test.py (temp database, no network)."""
import os, sys, tempfile
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, topics as TP

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

A1, A2, A3 = ("poa1" + c * 40 for c in "ABC")
BOT = "poa1Z" + "Z" * 39

def seed():
    db.init()
    db.put_blob("params", {"trusted_graders": []})
    db.put_blob("communities", [{"slug": "general", "name": "General", "archived": 0}, {"slug": "bugs", "name": "Bugs", "archived": 0},
                                {"slug": "old", "name": "Old", "archived": 1}, {"slug": "poa-archive", "name": "Archive", "archived": 0}])
    # (id, community, author, author_public_id)
    posts = [(1, "general", "Ann", A1), (2, "bugs", "Ann", A1),   # A1's public posts
             (3, "old", "Ann", A1),                                # archived community -> excluded from A1's counts
             (4, "general", "Bob", A2), (5, "general", "Cy", A3)]  # other Agents' posts A1 will reply to
    db.write("INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body) "
             "VALUES(?,?,?,?,?,'2026-11-10 12:00:00',1,0,0,0,1,?)", [(pid, comm, "post %d" % pid, author, apid, "SECRET_BODY_%d" % pid) for pid, comm, author, apid in posts], many=True)
    # (id, post, parent, author, author_public_id)
    cmts = [(101, 1, None, "Bob", A2), (102, 1, None, "Cy", A3), (103, 1, None, "Live-GrokBot", BOT),   # replies on A1's post 1: 2 human + 1 bot
            (104, 2, None, "Bob", A2),                                                                   # a reply on A1's post 2
            (210, 5, None, "Cy", A3),                                                                    # A3's own comment on post 5
            (301, 4, None, "Ann", A1),        # A1 replies to post 4 (author A2) -> target A2
            (302, 5, None, "Ann", A1),        # A1 replies to post 5 (author A3) -> target A3
            (303, 5, 210, "Ann", A1)]         # A1 replies to A3's comment 210 -> target A3
    db.write("INSERT INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body,edited_at) "
             "VALUES(?,?,?,?,?,'2026-11-10 12:30:00',0,'SECRET_COMMENT_BODY',NULL)", cmts, many=True)
    A._cache.clear()

seed()
f = TP.agent_forum(A1)
check("counts the Agent's public posts (2, not the archived one)", f and f["posts"] == 2)
check("counts the Agent's public replies (3)", f["replies"] == 3)
check("most-replied threads are the Agent's own posts, most replied first", [t["id"] for t in f["most_replied"]] == [1, 2])
check("reply counts leave out the bot (post 1 has 2 human replies, not 3)", f["most_replied"][0]["replies"] == 2)
check("the archived-community post is never listed", 3 not in [t["id"] for t in f["most_replied"]])
rt = {r["address"]: r["n"] for r in f["reply_to"]}
check("replies-most-to uses the parent comment author, else the post author", rt.get(A3) == 2 and rt.get(A2) == 1)
check("the Agent never counts as replying to itself", A1 not in rt)
check("reply targets carry names", f["reply_to"] and f["reply_to"][0]["name"] in ("Cy", "Bob"))

card = TP.agent_forum_card(A1)
check("card shows counts, most-replied threads and replies-most-to", 'class="stats two"' in card and "Most replied threads" in card and "Replies most to" in card)
check("the counts stat reads Posts and Comments (comments written), distinct from replies received", "Comments" in card and "Posts" in card)
check("card links threads to LabLeak", "minepoa.com/lableak/#/post/1" in card)
check("card carries no post or comment body", "SECRET_BODY" not in card and "SECRET_COMMENT_BODY" not in card)
check("card has no em or en dash", chr(0x2014) not in card and chr(0x2013) not in card)

src = open(os.path.join(ROOT, "poascan", "topics.py")).read().split("def agent_forum(")[1].split("\ndef ")[0]
check("agent_forum reads local tables only (no network fetch)", "db.q" in src and "fetch(" not in src and "requests" not in src)
check("the Agent profile overview renders the card", "_TOP.agent_forum_card(a)" in open(os.path.join(ROOT, "poascan", "views.py")).read())

# an Agent with no forum record: None and an empty card, no crash
check("an Agent with no forum record yields None and an empty card", TP.agent_forum(BOT[:4] + "Q" * 40) is None and TP.agent_forum_card(BOT[:4] + "Q" * 40) == "")
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
