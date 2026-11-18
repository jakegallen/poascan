"""Homepage forum pulse (POAScan story queue item 5): the hottest public thread this epoch and replies today, as one terse
line in the existing epoch/live block. Forum archive only, cached hourly, public communities, system authors left out,
titles and counts only. Usage: python3 tools/forum_pulse_test.py (temp database, no network)."""
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

def seed():
    db.init()
    db.put_blob("params", {"trusted_graders": []})
    db.put_blob("communities", [{"slug": "general", "name": "General", "archived": 0}, {"slug": "bugs", "name": "Bugs", "archived": 0},
                                {"slug": "old", "name": "Old", "archived": 1}, {"slug": "poa-archive", "name": "Archive", "archived": 0}])
    db.put_blob("epochs", [{"epoch": 1, "ts": NOW - 2 * 3600, "basis": {"settled": [], "pending": {}}}])   # this-epoch window starts 2h ago
    posts = [(1, "general", "grading seat payout", "Ann", A1, ts(3 * 3600), 1, 5),
             (2, "bugs", "wallet binding bug", "Bob", A2, ts(3 * 3600), 1, 2),
             (3, "old", "archived thread hidden", "Ann", A1, ts(3 * 3600), 9, 9),          # archived community -> excluded
             (4, "poa-archive", "poa-archive thread hidden", "Bob", A2, ts(3 * 3600), 9, 9)]  # skip community -> excluded
    db.write("INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body) "
             "VALUES(?,?,?,?,?,?,?,?,0,0,1,?)", [(p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], "SECRET_BODY_" + str(p[0])) for p in posts], many=True)
    cid = 100; cmts = []
    def add(post, author, pid, ago):
        nonlocal cid; cid += 1; cmts.append((cid, post, None, author, pid, ts(ago), 0, "SECRET_COMMENT_BODY", None))
    # recent public replies (this epoch + today): post 1 gets 3 distinct, post 2 gets 1
    add(1, "Bob", A2, 60); add(1, "Cy", A3, 90); add(1, "Bob", A2, 120)
    add(2, "Ann", A1, 60)
    # a bot reply on post 1 (excluded) and a reply on the archived thread (excluded)
    add(1, "Live-GrokBot", "poa1Z" + "Z" * 39, 30)
    add(4, "Ann", A1, 60)
    db.write("INSERT INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body,edited_at) VALUES(?,?,?,?,?,?,?,?,?)", cmts, many=True)
    A._cache.clear()

seed()
p = TP.pulse()
check("hottest thread is the most-replied PUBLIC thread this epoch, bot replies excluded", p["hottest"] and p["hottest"]["id"] == 1 and p["hottest"]["replies"] == 3)
check("archived community and the skip community are never the hottest", p["hottest"]["community"] == "general")
check("replies today counts public non-bot replies only (3 on p1 + 1 on p2 = 4)", p["replies_today"] == 4)

line = TP.pulse_line()
check("pulse line: terse, labelled, links the thread to LabLeak and Topics", "Forum pulse" in line and "minepoa.com/lableak/#/post/1" in line and "/agents/community?tab=topics" in line)
check("pulse line: titles and counts only, never a body", "SECRET_BODY" not in line and "SECRET_COMMENT_BODY" not in line)
check("pulse line: no em or en dash", "\u2014" not in line and "\u2013" not in line)
check("pulse line: not a separate panel (plain <p>, no card)", line.strip().startswith("<p") and "class=\"card" not in line)

# empty state: no public forum data -> empty line, no crash (pulse is @cached; clearing analytics cache busts it)
db.write("DELETE FROM forum_comments"); db.write("DELETE FROM forum_posts"); A._cache.clear()
check("empty forum archive yields an empty line (no crash)", TP.pulse_line() == "")

pulse_src = open(os.path.join(ROOT, "poascan", "topics.py")).read().split("def pulse(")[1].split("def pulse_line")[0]
check("pulse reads local tables only (db.q / A.epochs_raw), no network fetch", "db.q" in pulse_src and "fetch(" not in pulse_src and "requests" not in pulse_src)
check("home() renders the pulse line in the epoch/live block", "_TOP.pulse_line()" in open(os.path.join(ROOT, "poascan", "views.py")).read())
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
