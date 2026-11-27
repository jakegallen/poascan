"""ATP-20 balances per address (1.26.435): /api/v1/atp20/address/<poa1...> lists every tick one address holds, A to Z,
keyset 20 a page, official false, archive only; the address page shows an ATP-20 tab (Holdings, 20 a page with Next)
only when the address holds a tick. Temp database, no network. Usage: python3 tools/atp20_address_test.py"""
import json, os, re, sys, tempfile, copy
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, atp20 as T, indexer as IX, server as SV, agentapi as AG, views as V, analytics as A

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
DEP = "poa1DLtfHN8rajwqj7VdDHYLQ8MFwJGguXww6XU1tn7KNRVg"
OTHER = "poa1aabbccddeefaaaaaaaaaaaaaaaaaaa"
EMPTY = "poa1aabbccddeefbbbbbbbbbbbbbbbbbbb"
TICKS = ["T%03d" % i for i in range(1, 23)]   # 22 ticks so the default page of 20 must cursor

def tid(n): return format(n, "064x")
def row(i, memo, fr, to=None, ts=1795179000, final=1):
    return dict(id=tid(i), type="transfer", from_addr=fr, to_addr=to if to is not None else fr,
                amount="0.000001", memo=memo, ts=ts, final=final)

rows = []
for i, t in enumerate(TICKS):
    rows.append(row(10 + i, f"ATP-20|d|{t}|21000000|{8 if t == 'T001' else 0}|1000", DEP, ts=1795174000 + i))
    rows.append(row(100 + i, f"ATP-20|m|{t}|1000", DEP, ts=1795175000 + i))
rows.append(row(300, "ATP-20|m|T002|1000", OTHER, ts=1795176000))          # deployer-only tick: ignored, OTHER holds nothing
rows.append(row(301, "ATP-20|d|ZZZ|21000000|0|1000", OTHER, ts=1795176001))  # OTHER deploys and mints ZZZ
rows.append(row(302, "ATP-20|m|ZZZ|1000", OTHER, ts=1795176002))
rows.append(row(303, "ATP-20|m|ZZZ|1000", OTHER, ts=1795176003, final=0))   # pending: not applied
IX.upsert_txs([copy.deepcopy(r) for r in rows], "test")

def api(path, **q):
    if path.startswith("/api/v1/"): path = "/api" + path[len("/api/v1"):]
    return SV.api(path, {k: [str(v)] for k, v in q.items()})[0]
def err(path, **q):
    try: api(path, **q); return "no-error"
    except (SV.BadRequest, SV.NotFound) as e: return type(e).__name__ + " " + str(e)

r = api("/api/v1/atp20/address/" + DEP)
check("API: unofficial envelope with coverage", r["official"] is False and "Unofficial" in r["official_note"] and r["coverage"]["official"] is False and r["address"] == DEP)
check("API: default page is 20, A to Z, with a cursor", len(r["balances"]) == 20 and [b["tick"] for b in r["balances"]] == TICKS[:20] and r["next_cursor"])
r2 = api("/api/v1/atp20/address/" + DEP, cursor=r["next_cursor"])
check("API: second page has the rest and no cursor", [b["tick"] for b in r2["balances"]] == TICKS[20:] and r2["next_cursor"] is None)
b1 = r["balances"][0]
check("API: row has tick, amount in base units, decimals, mint_count, official false",
      b1 == dict(tick="T001", addr=DEP, amount="1000", mint_count=1, official=False, decimals=8))
o = api("/api/v1/atp20/address/" + OTHER)
check("API: pending and ignored ops are not applied", [(b["tick"], b["amount"]) for b in o["balances"]] == [("ZZZ", "1000")])
e = api("/api/v1/atp20/address/" + EMPTY)
check("API: no holdings is an empty list, not a 404", e["balances"] == [] and e["next_cursor"] is None)
check("API: limit 1 pages", len(api("/api/v1/atp20/address/" + DEP, limit=1)["balances"]) == 1)
check("API: malformed address is 400", "poa1 address" in err("/api/v1/atp20/address/nope"))
check("API: unknown parameter is 400", "unknown parameter" in err("/api/v1/atp20/address/" + DEP, foo=1))
check("API: bad cursor is 400", "bad cursor" in err("/api/v1/atp20/address/" + DEP, cursor="!!!"))
check("count helper", T.address_count(DEP) == 22 and T.address_count(OTHER) == 1 and T.address_count(EMPTY) == 0)
plan = " ".join(str(dict(x)) for x in db.q("EXPLAIN QUERY PLAN " + T._ADDR_SQL + " ORDER BY b.tick ASC LIMIT 21", (DEP,)))
check("query uses the addr index", "atp20_bal_addr" in plan)
spec = AG.openapi()["paths"]
check("OpenAPI lists /api/v1/atp20/address/{address}", "/api/v1/atp20/address/{address}" in spec)
check("llms.txt names the route", "/atp20/address/" in AG.llms_txt())

A._cache.clear()
V.REQ.qs = {"tab": ["atp20"]}
pg = V.address(DEP); pg = pg[1] if isinstance(pg, tuple) else pg
check("page: ATP-20 tab chip with count 22", '?tab=atp20"' in pg and "ATP-20 <small>22</small>" in pg)
card = pg[pg.find('id="atp20"'):]
check("page: Holdings card, ticks link to their token page, 8 decimals shown",
      'id="atp20"' in pg and "Holdings" in card and 'href="/apps?tab=atp20&amp;tick=T001"' in card and ">0.00001<" in card and ">1,000<" in card)
check("page: 20 rows then Next to offset 20", card.count("/apps?tab=atp20&amp;tick=") == 20 and "?tab=atp20&amp;offset=20" in card and ">Next<" in card)
V.REQ.qs = {"tab": ["atp20"], "offset": ["20"]}
pg2 = V.address(DEP); pg2 = pg2[1] if isinstance(pg2, tuple) else pg2
c2 = pg2[pg2.find('id="atp20"'):]
check("page: offset 20 shows T021 and T022 with Prev", "tick=T021" in c2 and "tick=T022" in c2 and "tick=T001" not in c2 and ">Prev<" in c2)
check("page: no More, Full list or dashes", not re.search(r">(More|Full list|Load more)<", card[:card.find("</section>")]) and "\u2014" not in card and "\u2013" not in card)
V.REQ.qs = {}
pe = V.address(OTHER); pe = pe[1] if isinstance(pe, tuple) else pe
check("page: holder of one tick gets the tab", "ATP-20 <small>1</small>" in pe)
print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
