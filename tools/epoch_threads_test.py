"""Forum moments in the epoch timeline (POAScan story queue item 2): up to 3 most-replied PUBLIC threads whose replies
landed in this epoch's window (prev close, close], shown as a small card on the epoch page. Forum archive only, public
communities, system authors left out, titles and counts only. Usage: python3 tools/epoch_threads_test.py (temp db)."""
import os, sys, tempfile, time
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, topics as TP

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NOW = int(time.time())
def ts(ago): return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(NOW - ago))
A1, A2, A3 = ("poa1" + c * 40 for c in "ABC")
PREV, CLOSE = NOW - 4 * 3600, NOW - 2 * 3600   # this epoch's window: 4h ago .. 2h ago

def seed():
    db.init()
    db.put_blob("params", {"trusted_graders": []})
    db.put_blob("communities", [{"slug": "general", "name": "General", "archived": 0}, {"slug": "bugs", "name": "Bugs", "archived": 0},
                                {"slug": "old", "name": "Old", "archived": 1}, {"slug": "poa-archive", "name": "Archive", "archived": 0}])
    posts = [(1, "general", "grading seat payout", "Ann", A1, ts(5 * 3600), 1, 5), (2, "bugs", "wallet binding bug", "Bob", A2, ts(5 * 3600), 1, 2),
             (3, "old", "archived thread hidden", "Ann", A1, ts(5 * 3600), 9, 9), (4, "poa-archive", "poa-archive hidden", "Bob", A2, ts(5 * 3600), 9, 9)]
    db.write("INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body) "
             "VALUES(?,?,?,?,?,?,?,?,0,0,1,?)", [(p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], "SECRET_BODY_" + str(p[0])) for p in posts], many=True)
    cid = 100; cmts = []
    def add(post, author, pid, ago):
        nonlocal cid; cid += 1; cmts.append((cid, post, None, author, pid, ts(ago), 0, "SECRET_COMMENT_BODY", None))
    add(1, "Bob", A2, 3 * 3600); add(1, "Cy", A3, 3 * 3600); add(1, "Bob", A2, 3 * 3600 + 60)   # p1: 3 in window
    add(2, "Ann", A1, 3 * 3600); add(2, "Cy", A3, 3 * 3600)                                       # p2: 2 in window
    add(1, "Live-GrokBot", "poa1Z" + "Z" * 39, 3 * 3600)                                           # bot reply in window -> excluded
    add(1, "Bob", A2, 1 * 3600)                                                                    # after close -> outside window
    add(3, "Ann", A1, 3 * 3600)                                                                    # archived community -> excluded
    db.write("INSERT INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body,edited_at) VALUES(?,?,?,?,?,?,?,?,?)", cmts, many=True)
    A._cache.clear()

seed()
t = TP.epoch_threads(PREV, CLOSE)
check("thread 1 is the top moment with 3 in-window replies, bot excluded", t and t[0]["id"] == 1 and t[0]["replies"] == 3)
check("thread 2 is second with 2 in-window replies", len(t) == 2 and t[1]["id"] == 2 and t[1]["replies"] == 2)
check("archived community and after-close replies are excluded", all(x["community"] in ("general", "bugs") for x in t))
check("capped at 3 moments", len(t) <= 3)

card = TP.epoch_threads_card(7, PREV, CLOSE)
check("card: labelled Forum moments, links threads to LabLeak", "Forum moments" in card and "minepoa.com/lableak/#/post/1" in card and "minepoa.com/lableak/#/post/2" in card)
check("card: titles and counts only, never a body", "SECRET_BODY" not in card and "SECRET_COMMENT_BODY" not in card)
check("card: no em or en dash", chr(0x2014) not in card and chr(0x2013) not in card)

A._cache.clear()
check("empty window renders no card (empty string)", TP.epoch_threads_card(8, NOW - 100, NOW - 50) == "")
check("epoch() renders the forum-moments card in the body", "_TOP.epoch_threads_card(" in open(os.path.join(ROOT, "poascan", "views.py")).read())
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
