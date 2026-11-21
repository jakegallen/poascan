"""Unofficial Apps trending (/api/v1/apps/trending): top entities by trailing-hour activity.
Seeds recent ATP-20 and ATP-721 ops and checks the ranking, shape and window. No upstream reads.
Usage: python3 tools/apps_trending_test.py"""
import os, sys, tempfile, copy, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, apps as AP, indexer as IX, server as SV, agentapi as AG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()

DEP = "poa1DLtfHN8rajwqj7VdDHYLQ8MFwJGguXww6XU1tn7KNRVg"
A1 = "poa1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
A2 = "poa1bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
NOW = int(time.time())

def tid(n):
    return format(n, "064x")

def row(i, memo, fr, to=None, ts=None, final=1):
    return dict(id=tid(i) if isinstance(i, int) else i, type="transfer", from_addr=fr,
                to_addr=to if to is not None else fr, amount="0.000001", memo=memo,
                ts=ts if ts is not None else NOW - 100, final=final)

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

# Recent activity: AAA has 3 events, COLX has 2, BBB has 1. Plus one stale AAA op outside the window.
load(row(1, "ATP-20|d|AAA|21000000|0||open:1000:50", DEP, ts=NOW - 200),
     row(2, "ATP-20|m|AAA|1000", A1, ts=NOW - 150),
     row(3, "ATP-20|m|AAA|1000", A2, ts=NOW - 100))
load(row(4, "ATP-20|d|BBB|21000000|0||open:1000:50", DEP, ts=NOW - 90),
     row(5, "ATP-20|m|BBB|1000", A1, ts=NOW - 80))   # BBB deploy is outside count? no, within window
load(row(10, f"ATP-721|d|COLX|{'f'*64}|image/png|3333|0|MAM|20|50|X", DEP, ts=NOW - 7000),  # deploy stale
     row(11, "ATP-721|m|COLX|1", A1, ts=NOW - 70),
     row(12, "ATP-721|m|COLX|2", A2, ts=NOW - 60))
load(row(99, "ATP-20|m|AAA|1000", A1, ts=NOW - 99999))   # stale AAA mint, must not count

t = api("/api/v1/apps/trending")
check("trending is unofficial with the window and asof",
      t["official"] is False and t["window_s"] == 3600 and isinstance(t["asof"], int) and t["asof"] >= NOW)
check("at most three items", len(t["items"]) <= 3)
check("every item carries kind, id, label, events_1h, last_ts",
      all({"kind", "id", "label", "events_1h", "last_ts"} <= set(x) for x in t["items"]))
byid = {x["id"]: x for x in t["items"]}
check("AAA leads with 3 recent events as a tick (stale op not counted)",
      t["items"][0]["id"] == "AAA" and t["items"][0]["kind"] == "tick" and t["items"][0]["events_1h"] == 3)
check("COLX is present as a collection with 2 events (stale deploy not counted)",
      "COLX" in byid and byid["COLX"]["kind"] == "collection" and byid["COLX"]["events_1h"] == 2)
check("BBB is present with 2 recent events", "BBB" in byid and byid["BBB"]["events_1h"] == 2)
check("items are ranked by event count then recency",
      all(t["items"][i]["events_1h"] >= t["items"][i + 1]["events_1h"] for i in range(len(t["items"]) - 1)))
check("last_ts is recent epoch seconds", all(x["last_ts"] >= NOW - 3600 for x in t["items"]))
check("unknown query param is 400", "unknown parameter" in expect_bad("/api/v1/apps/trending", foo=1))

spec = AG.openapi()
check("openapi has /api/v1/apps/trending", "/api/v1/apps/trending" in spec["paths"])
check("llms.txt names trending", "/apps/trending" in AG.llms_txt())

print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
