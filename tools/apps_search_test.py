"""Unofficial Apps search (/api/v1/apps/search) across ticks, collections and agents.
Seeds a token, a collection and a labelled agent, then checks matching, the kind filter and paging.
No upstream reads, no em or en dashes. Usage: python3 tools/apps_search_test.py"""
import os, sys, tempfile, copy
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, apps as AP, indexer as IX, server as SV, agentapi as AG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()

DEP = "poa1DLtfHN8rajwqj7VdDHYLQ8MFwJGguXww6XU1tn7KNRVg"
AGT = "poa1cafebabedeadbeefcafebabedeadbeefcafebabe00"

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

# one ATP-20 token SEAL, one ATP-721 collection SEALERS titled "The Sealers", one labelled agent.
load(row(1, "ATP-20|d|SEAL|21000000|0||open:1000:50", DEP, ts=1795180000))
load(row(10, f"ATP-721|d|SEALERS|{'f'*64}|image/png|3333|111|MAM|20|50|The Sealers", DEP, ts=1795180200))
db.write("INSERT INTO labels(addr, label, source, ts) VALUES(?,?,?,?)", (AGT, "Sealmaster", "join memo", 1795180000))

# ---- substring match hits all three kinds for "seal" ----
s = api("/api/v1/apps/search", q="seal")
kinds = {x["kind"] for x in s["results"]}
check("search is unofficial and returns the result list",
      s["official"] is False and isinstance(s["results"], list) and s["next_cursor"] is None)
check("every result carries kind, id and label",
      all({"kind", "id", "label"} <= set(x) for x in s["results"]))
check("seal matches the tick, the collection and the agent",
      "tick" in kinds and "collection" in kinds and "agent" in kinds)
byid = {(x["kind"], x["id"]): x for x in s["results"]}
check("tick SEAL is found", ("tick", "SEAL") in byid)
check("collection SEALERS is found with its title as label",
      ("collection", "SEALERS") in byid and byid[("collection", "SEALERS")]["label"] == "The Sealers")
check("agent is found by its label", ("agent", AGT) in byid and byid[("agent", AGT)]["label"] == "Sealmaster")

# ---- kind filter ----
only = api("/api/v1/apps/search", q="seal", kind="tick")
check("kind=tick narrows to ticks only",
      all(x["kind"] == "tick" for x in only["results"]) and len(only["results"]) == 1)
check("agent address prefix search works",
      any(x["kind"] == "agent" and x["id"] == AGT for x in api("/api/v1/apps/search", q="poa1cafe")["results"]))

# ---- errors + paging ----
check("missing q is 400", "q is required" in expect_bad("/api/v1/apps/search", kind="tick"))
check("unknown kind is 400", "kind must be one of" in expect_bad("/api/v1/apps/search", q="x", kind="nope"))
check("bad cursor is 400", "bad cursor" in expect_bad("/api/v1/apps/search", q="seal", cursor="x"))
check("unknown query param is 400", "unknown parameter" in expect_bad("/api/v1/apps/search", q="seal", foo=1))
p1 = api("/api/v1/apps/search", q="seal", limit=1)
check("limit 1 returns one row and a cursor", len(p1["results"]) == 1 and p1["next_cursor"])
p2 = api("/api/v1/apps/search", q="seal", limit=1, cursor=p1["next_cursor"])
check("the cursor advances to a new row",
      p2["results"] and p2["results"][0]["id"] != p1["results"][0]["id"])

spec = AG.openapi()
check("openapi has /api/v1/apps/search", "/api/v1/apps/search" in spec["paths"])
check("llms.txt names search", "/apps/search" in AG.llms_txt())

print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
