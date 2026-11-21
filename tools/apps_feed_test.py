"""Unofficial Apps activity feed (/api/v1/apps/feed and the SSE catch-up). Seeds a few ATP-20,
ATP-721 and forum rows, then checks the merged newest-first feed, the type filter, keyset paging
and the emit-and-close SSE body. No upstream reads, no em or en dashes.
Usage: python3 tools/apps_feed_test.py"""
import json, os, sys, tempfile, copy
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, apps as AP, indexer as IX, server as SV, agentapi as AG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
DASH = ("\u2014", "\u2013")
db.init()

DEP = "poa1DLtfHN8rajwqj7VdDHYLQ8MFwJGguXww6XU1tn7KNRVg"
A1 = "poa1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
A2 = "poa1bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

def tid(n):
    return format(n, "064x")

def row(i, memo, fr, to=None, ts=1795179000, final=1):
    return dict(id=tid(i) if isinstance(i, int) else i, type="transfer", from_addr=fr,
                to_addr=to if to is not None else fr, amount="0.000001", memo=memo, ts=ts, final=final)

def load(*rows):
    IX.upsert_txs([copy.deepcopy(r) for r in rows], "test")

def api(path, **q):
    if path == "/api/v1" or path.startswith("/api/v1/"):
        path = "/api" + path[len("/api/v1"):]
    qs = {k: [str(v)] for k, v in q.items() if v is not None}
    return SV.api(path, qs)[0]

def expect_bad(path, **q):
    try:
        api(path, **q); return "no-error"
    except SV.BadRequest as e:
        return str(e)
    except Exception as e:
        return type(e).__name__ + " " + str(e)

# ATP-20 deploy + mint, ATP-721 deploy + mint, one forum post. Ascending ts so order is known.
load(row(1, "ATP-20|d|SEAL|21000000|0||open:1000:5", DEP, ts=1795180000),
     row(2, "ATP-20|m|SEAL|1000", A1, ts=1795180100))
load(row(10, f"ATP-721|d|MAM-GENESIS|{'f'*64}|image/png|3333|111|MAM|20|5|AWAKENS", DEP, ts=1795180200),
     row(11, "ATP-721|m|MAM-GENESIS|1", A2, ts=1795180300))
# a forum post, newest of all
db.write("INSERT INTO forum_posts(id, community, title, author, author_public_id, created_at, deleted) "
         "VALUES(?,?,?,?,?,?,?)", (501, "bugs", "A proposal", "Someone", A1, "2026-11-21T00:00:00Z", 0))

# ---- default feed: merged newest first ----
f = api("/api/v1/apps/feed")
check("feed is unofficial with a local-archive coverage",
      f["official"] is False and f["coverage"]["official"] is False and f["coverage"]["source"] == "local_archive")
types_seen = [x["type"] for x in f["feed"]]
check("feed merges atp20, atp721 and post events",
      "atp20_mint" in types_seen and "atp721_mint" in types_seen and "post" in types_seen
      and "atp20_deploy" in types_seen and "atp721_mint" in types_seen)
check("feed is sorted newest first",
      all(f["feed"][i]["ts"] >= f["feed"][i + 1]["ts"] for i in range(len(f["feed"]) - 1)))
check("the forum post is the newest item and names the author as agent",
      f["feed"][0]["type"] == "post" and f["feed"][0]["agent"] == A1 and f["feed"][0]["label"] == "A proposal")
check("every row carries the full item shape",
      all({"id", "ts", "type", "tick", "col", "unit", "amt", "agent", "txid", "label"} <= set(x) for x in f["feed"]))
mint20 = [x for x in f["feed"] if x["type"] == "atp20_mint"][0]
check("atp20 mint agent is the recipient and amt and tick are set",
      mint20["agent"] == A1 and mint20["tick"] == "SEAL" and mint20["amt"] == "1000")
mint721 = [x for x in f["feed"] if x["type"] == "atp721_mint"][0]
check("atp721 mint carries col and unit and the minter as agent",
      mint721["agent"] == A2 and mint721["col"] == "MAM-GENESIS" and mint721["unit"] == 1)

# ---- type filter ----
only20 = api("/api/v1/apps/feed", type="atp20_mint")
check("type filter narrows to the one type",
      len(only20["feed"]) == 1 and only20["feed"][0]["type"] == "atp20_mint"
      and only20["types"] == ["atp20_mint"])
check("game type is accepted but yields nothing (no source)",
      api("/api/v1/apps/feed", type="game")["feed"] == [])
check("unknown type is 400", "type must be one of" in expect_bad("/api/v1/apps/feed", type="nope"))
check("unknown query param is 400", "unknown parameter" in expect_bad("/api/v1/apps/feed", foo=1))

# ---- keyset paging ----
p1 = api("/api/v1/apps/feed", limit=2)
check("first page honours the limit and returns a cursor", len(p1["feed"]) == 2 and p1["next_cursor"])
p2 = api("/api/v1/apps/feed", limit=2, cursor=p1["next_cursor"])
ids1 = [x["id"] for x in p1["feed"]]
check("second page continues with no overlap",
      all(x["id"] not in ids1 for x in p2["feed"]) and len(p2["feed"]) >= 1)
total = len(api("/api/v1/apps/feed", limit=50)["feed"])
# atp20 deploy + atp20 mint + atp721 mint + post = 4. The atp721 deploy is not a feed type.
check("paging covers the whole feed", total == 4)
check("bad cursor is 400", "bad cursor" in expect_bad("/api/v1/apps/feed", cursor="!!!"))

# ---- SSE catch-up body ----
sse = AP.feed_sse({})
check("sse body is event-stream text with id, event and data lines",
      "retry: 5000" in sse and "\nid: " in sse and "\nevent: post\n" in sse and "\ndata: {" in sse)
# Last-Event-ID at the newest item should yield an empty catch-up (nothing newer)
newest_eid = "%s|%s|%s" % (f["feed"][0]["ts"], f["feed"][0]["type"], f["feed"][0]["id"])
sse_tail = AP.feed_sse({}, last_event_id=newest_eid)
check("sse honours Last-Event-ID and emits nothing past the newest", "\nid: " not in sse_tail)

# ---- OpenAPI + llms ----
spec = AG.openapi()
for pth in ("/api/v1/apps/feed", "/api/v1/apps/feed/stream"):
    check(f"openapi has {pth}", pth in spec["paths"])
txt = AG.llms_txt()
check("llms.txt names the apps feed", "/apps/feed" in txt)
check("no em or en dash in new feed strings",
      not any(d in AP.OFFICIAL_NOTE_FEED or d in json.dumps(f) or d in sse for d in DASH))

print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
