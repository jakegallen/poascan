"""Releases and notices to the threads that discuss them (POASCAN story queue item 3). Each release or notice on the
Builders page links the PUBLIC forum thread(s) whose TITLE names it by an exact token (a version string or a notice id),
high precision only: bounded match, a token shorter than TOK_MIN ignored, archived and skip communities and system authors
left out, titles and counts only, never a body. Usage: python3 tools/release_threads_test.py (temp database, no network)."""
import os, re, sys, tempfile, time
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
BOT = "poa1Z" + "Z" * 39

def seed():
    db.init()
    db.put_blob("params", {"trusted_graders": []})
    db.put_blob("communities", [{"slug": "general", "name": "General", "archived": 0}, {"slug": "bugs", "name": "Bugs", "archived": 0},
                                {"slug": "old", "name": "Old", "archived": 1}, {"slug": "poa-archive", "name": "Archive", "archived": 0}])
    # id, community, title, author, author_public_id
    posts = [(1, "general", "notes on 0.9.3 grading change", "Ann", A1),
             (2, "general", "the 0.9.30 follow up", "Bob", A2),                      # boundary: 0.9.30 must not match the token 0.9.3
             (3, "bugs", "reading 2026-10-24-genesis-cut carefully", "Cy", A3),      # a notice id in the title
             (4, "old", "0.9.3 in an archived community", "Ann", A1),                # archived community -> excluded
             (5, "poa-archive", "0.9.3 in the skip community", "Bob", A2),           # skip community -> excluded
             (6, "general", "0.9.3 from the bot", "Live-GrokBot", BOT)]              # skip author -> excluded
    db.write("INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body) "
             "VALUES(?,?,?,?,?,?,1,0,0,0,1,?)", [(p[0], p[1], p[2], p[3], p[4], ts(3 * 3600), "SECRET_BODY_" + str(p[0])) for p in posts], many=True)
    cid = 100; cmts = []
    def add(post, author, pid, ago):
        nonlocal cid; cid += 1; cmts.append((cid, post, None, author, pid, ts(ago), 0, "SECRET_COMMENT_BODY", None))
    add(1, "Bob", A2, 60); add(1, "Cy", A3, 90)   # post 1 gets 2 public replies
    add(3, "Ann", A1, 60)                          # post 3 gets 1
    db.write("INSERT INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body,edited_at) VALUES(?,?,?,?,?,?,?,?,?)", cmts, many=True)
    A._cache.clear()

seed()
v = TP.thread_links(["0.9.3"])
check("a version token links only the public thread whose title names it", [r["id"] for r in v] == [1])
check("bounded match: 0.9.3 does not match inside 0.9.30", 2 not in [r["id"] for r in v])
check("archived community, skip community and system author are never linked", not ({4, 5, 6} & {r["id"] for r in TP.thread_links(["0.9.3"], limit=10)}))
check("the 0.9.30 token matches its own thread exactly", [r["id"] for r in TP.thread_links(["0.9.30"])] == [2])
check("a notice id token links its thread", [r["id"] for r in TP.thread_links(["2026-10-24-genesis-cut"])] == [3])
check("a token shorter than TOK_MIN is ignored (no noisy bare-number match)", TP.thread_links(["1.0"]) == [] and TP.thread_links(["a"]) == [])
check("reply counts come from public non-bot comments", v and v[0]["replies"] == 2)

chips = TP.thread_chips(["0.9.3"])
check("chips link the thread to LabLeak with the id and an inline title (a full-size tap target, title not only a tooltip)",
      'minepoa.com/lableak/#/post/1' in chips and "#1" in chips and "notes on 0.9.3" in chips and 'class="relthread"' in chips and "Discussed" in chips)
check("chips carry no post body", "SECRET_BODY" not in chips and "SECRET_COMMENT_BODY" not in chips)
check("chips: no em or en dash", chr(0x2014) not in chips and chr(0x2013) not in chips)
check("no matching title yields an empty string (nothing rendered, no noise)", TP.thread_chips(["no-such-release-token"]) == "")
check("None or empty tokens are safe", TP.thread_chips([None]) == "" and TP.thread_chips([]) == "")

src = open(os.path.join(ROOT, "poascan", "topics.py")).read().split("def thread_links(")[1].split("def thread_chips")[0]
check("thread matching reads local tables only (no network fetch)", "fetch(" not in src and "requests" not in src and "http" not in src)
check("builders page wires the release thread chips", "_TOP.thread_chips(" in open(os.path.join(ROOT, "poascan", "views.py")).read())

# empty archive -> no crash, empty everywhere (title index is cached; clearing analytics cache busts it)
db.write("DELETE FROM forum_comments"); db.write("DELETE FROM forum_posts"); A._cache.clear()
check("empty forum archive yields no links and no crash", TP.thread_links(["0.9.3"]) == [] and TP.thread_chips(["0.9.3"]) == "")
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
