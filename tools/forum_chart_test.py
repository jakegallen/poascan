"""Forum posts per day on the Network charts (POASCAN story queue item 4). A 'Forum posts / day' small multiple is woven
into Network > Charts and its pop-out, from POAScan's own forum archive (public communities, system authors and the
archived community left out), counts only, cached hourly. Usage: python3 tools/forum_chart_test.py (temp database, no network)."""
import os, sys, tempfile, time, calendar
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
def dts(day, hh=12): return "%s %02d:00:00" % (day, hh)   # a forum timestamp "YYYY-MM-DD HH:MM:SS"
def midnight(day): return int(calendar.timegm(time.strptime(day, "%Y-%m-%d")))

def seed():
    db.init()
    db.put_blob("params", {"trusted_graders": []})
    db.put_blob("communities", [{"slug": "general", "name": "General", "archived": 0}, {"slug": "bugs", "name": "Bugs", "archived": 0},
                                {"slug": "old", "name": "Old", "archived": 1}, {"slug": "poa-archive", "name": "Archive", "archived": 0}])
    # 2 public posts on day A, 1 public on day B; plus an archived-community post and a bot post that must NOT be counted
    # (id, community, created_at, author, author_public_id)
    posts = [(1, "general", dts("2026-11-10"), "Ann", A1), (2, "bugs", dts("2026-11-10"), "Bob", A2),
             (3, "general", dts("2026-11-11"), "Cy", A3),
             (4, "old", dts("2026-11-10"), "Ann", A1),               # archived community -> excluded
             (5, "poa-archive", dts("2026-11-10"), "Bob", A2),       # skip community -> excluded
             (6, "general", dts("2026-11-11"), "Live-GrokBot", BOT)]  # skip author -> excluded
    db.write("INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body) "
             "VALUES(?,?,?,?,?,?,1,0,0,0,1,?)", [(pid, comm, "post %d" % pid, author, apid, created, "B%d" % pid) for pid, comm, created, author, apid in posts], many=True)
    # comments: 2 public on day A (post 1), 1 bot on day A (excluded)
    cmts = [(101, 1, None, "Bob", A2, dts("2026-11-10"), 0, "c", None), (102, 1, None, "Cy", A3, dts("2026-11-10"), 0, "c", None),
            (103, 1, None, "Live-GrokBot", BOT, dts("2026-11-10"), 0, "c", None)]
    db.write("INSERT INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body,edited_at) VALUES(?,?,?,?,?,?,?,?,?)", cmts, many=True)
    A._cache.clear()

seed()
d = TP.posts_daily()
byday = {ts: (p, c) for ts, p, c in d}
check("posts per day counts public non-bot posts only (day A has 2, not the archived or skip posts)", byday.get(midnight("2026-11-10"), (0, 0))[0] == 2)
check("day B public posts exclude the bot (1, not 2)", byday.get(midnight("2026-11-11"), (0, 0))[0] == 1)
check("comments per day count public non-bot comments only (2 on day A)", byday.get(midnight("2026-11-10"), (0, 0))[1] == 2)
check("rows are (utc_midnight_ts, posts, comments), oldest first", [r[0] for r in d] == sorted(r[0] for r in d) and all(len(r) == 3 for r in d))
check("archived community and skip community never counted", sum(p for _, p, _ in d) == 3)
check("series is posts per day (ts, posts) for the chart", [(ts, p) for ts, p, c in d] == [(midnight("2026-11-10"), 2), (midnight("2026-11-11"), 1)])

v3 = open(os.path.join(ROOT, "poascan", "views3.py")).read()
check("Network charts render the forum posts per day cell", "posts_daily()" in v3 and 'card("Forum posts / day"' in v3 and "{fcell}" in v3)
check("the forum chart expands locally (no fetch endpoint, the series is POASCAN's own)",
      'pop_btn_local("cx-forum"' in v3 and 'id="cx-forum"' in v3 and '"forum"' not in open(os.path.join(ROOT, "poascan", "chartpop.py")).read())
tp = open(os.path.join(ROOT, "poascan", "topics.py")).read()
src = tp.split("def posts_daily(")[1].split("\ndef ")[0] if "def posts_daily(" in tp else ""
check("posts_daily reads local tables only (no network fetch)", "db.q" in src and "fetch(" not in src and "requests" not in src)

# empty archive -> empty series, no crash
db.write("DELETE FROM forum_comments"); db.write("DELETE FROM forum_posts"); A._cache.clear()
check("empty forum archive yields an empty series (no crash)", TP.posts_daily() == [])
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
