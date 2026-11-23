"""ATP-721 unofficial read API (1.26.415): keyset-paged collections, units, holders and txs,
every figure labeled unofficial, coverage fields, default 20 rows, no upstream reads, no em or en dashes.
Usage: python3 tools/atp721_api_test.py"""
import os, sys, tempfile, copy, json
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, atp721 as T, atp20 as T20, indexer as IX, server as SV, agentapi as AG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
DASH = ("\u2014", "\u2013")
db.init()

DEP = "poa1DLtfHN8rajwqj7VdDHYLQ8MFwJGguXww6XU1tn7KNRVg"
SHA = "f24fe8eb6b21cc3f86bd2b3f79b28f65964dbde0fd79f91bee5f644594d59d8e"
# 21 holders so the default page of 20 must cursor
HOLDERS = ["poa1aabbccddeef" + ch + "aaaaaaaaaaaaaaaaaaa" for ch in "abcdefghjkmnpqrstuvwx"]

def tid(n):
    return format(n, "064x")

def row(i, memo, fr, to=None, ts=1795214976, final=1, typ="transfer"):
    return dict(id=tid(i) if isinstance(i, int) else i, type=typ, from_addr=fr, to_addr=to if to is not None else fr,
                amount="0.000001", memo=memo, ts=ts, final=final)

def load(*rows):
    IX.upsert_txs([copy.deepcopy(r) for r in rows], "test")

def api(path, **q):
    if path == "/api/v1" or path.startswith("/api/v1/"):
        path = "/api" + path[len("/api/v1"):]
    qs = {k: [str(v)] for k, v in q.items() if v is not None}
    return SV.api(path, qs)[0]

def expect_bad(path, **q):
    try:
        api(path, **q)
        return "no-error"
    except SV.BadRequest as e:
        return str(e)
    except Exception as e:
        return type(e).__name__ + " " + str(e)

def expect_404(path, **q):
    try:
        api(path, **q)
        return "no-error"
    except SV.NotFound as e:
        return str(e)
    except Exception as e:
        return type(e).__name__ + " " + str(e)

load(row(8000, "ATP-20|d|MAM|21000000|0|open", DEP, ts=1795174507))
load(row(8001, "ATP-20|m|MAM|100000", DEP, ts=1795174508))
for i, addr in enumerate(HOLDERS):
    load(row(8100 + i, f"ATP-20|m|MAM|100000", addr, ts=1795174510 + i))
load(row(1, f"ATP-721|d|MAM-GENESIS|{SHA}|image/png|3333|111|MAM|20|5|THE AGENT AWAKENS", DEP, ts=1795214976))
for i, addr in enumerate(HOLDERS):
    load(row(100 + i, f"ATP-721|m|MAM-GENESIS|{i+1}", addr, ts=1795218000 + i))
load(row(200, "ATP-721|m|MAM-GENESIS|50", HOLDERS[0], ts=1795219000, final=0))
load(row(201, "ATP-721|m|MAM-GENESIS|1", HOLDERS[1], ts=1795219001, final=1))  # duplicate of unit 1, ignored

lst = api("/api/v1/atp721/collections")
check("collections: unofficial envelope and coverage",
      lst["official"] is False and "Unofficial" in lst["official_note"]
      and lst["coverage"]["official"] is False and lst["coverage"]["ordering"] == "ts_id"
      and lst["coverage"]["fee_debit"] == "minter" and lst["next_cursor"] is None)
check("collections: MAM-GENESIS unofficial",
      [c["col"] for c in lst["collections"]] == ["MAM-GENESIS"]
      and lst["collections"][0]["official"] is False and lst["collections"][0]["minted"] == 21
      and lst["collections"][0]["fee_burned"] == "483" and lst["collections"][0]["deployer_fees"] == "1848")
check("unknown query param is 400", "unknown parameter" in expect_bad("/api/v1/atp721/collections", foo=1))

one = api("/api/v1/atp721/collection/MAM-GENESIS")
check("collection summary unofficial minted 21",
      one["official"] is False and one["collection"]["official"] is False
      and one["collection"]["minted"] == 21 and one["collection"]["title"] == "THE AGENT AWAKENS")
check("unknown collection is 404", expect_404("/api/v1/atp721/collection/NOPE") == "unknown collection")

u = api("/api/v1/atp721/collection/MAM-GENESIS/units")
check("units default page is 20 with a next cursor",
      len(u["units"]) == 20 and u["next_cursor"] and all(x["official"] is False for x in u["units"])
      and u["units"][0]["unit"] == 1)
u2 = api("/api/v1/atp721/collection/MAM-GENESIS/units", cursor=u["next_cursor"])
check("units second page has the last unit and no further cursor",
      len(u2["units"]) == 1 and u2["next_cursor"] is None and u2["units"][0]["unit"] == 21)

h = api("/api/v1/atp721/collection/MAM-GENESIS/holders")
check("holders page lists 20 of 21 with a cursor",
      len(h["holders"]) == 20 and h["next_cursor"] and all(x["official"] is False for x in h["holders"]))
h2 = api("/api/v1/atp721/collection/MAM-GENESIS/holders", cursor=h["next_cursor"])
check("holders second page completes the set",
      len(h["holders"]) + len(h2["holders"]) == 21 and h2["next_cursor"] is None)

tx = api("/api/v1/atp721/collection/MAM-GENESIS/txs")
check("txs default page is 20 with a cursor", len(tx["txs"]) == 20 and tx["next_cursor"] and tx["official"] is False)
tx2 = api("/api/v1/atp721/collection/MAM-GENESIS/txs", cursor=tx["next_cursor"])
ids = [r["txid"] for r in tx["txs"] + tx2["txs"]]
check("pending mint is not in the txs list", tid(200) not in ids)
check("ignored duplicate is in the txs list with a reason",
      any(r["txid"] == tid(201) and r["valid"] == 0 and r["reason"] == "duplicate_unit" for r in tx["txs"] + tx2["txs"]))
# 1 deploy + 21 mints + 1 ignored = 23 final
check("txs second page completes the set", len(tx["txs"]) + len(tx2["txs"]) == 23 and tx2["next_cursor"] is None)

# ---- editions: 21 minted units, owner + collection art digest, by unit ascending ----
ed = api("/api/v1/atp721/collection/MAM-GENESIS/editions")
ed2 = api("/api/v1/atp721/collection/MAM-GENESIS/editions", cursor=ed["next_cursor"])
eds = ed["editions"] + ed2["editions"]
check("editions default page is 20 with a next cursor",
      len(ed["editions"]) == 20 and ed["next_cursor"] and all(x["official"] is False for x in ed["editions"]))
check("editions second page completes the 21 units", len(eds) == 21 and ed2["next_cursor"] is None
      and [x["unit"] for x in eds] == list(range(1, 22)))
check("edition rows carry unit, owner, image_ref, mint_txid, mint_ts; image_ref is the collection digest",
      all({"unit", "owner", "image_ref", "mint_txid", "mint_ts"} <= set(x) for x in eds)
      and eds[0]["owner"] == HOLDERS[0] and all(x["image_ref"] == SHA for x in eds))
check("unknown collection editions is 404", expect_404("/api/v1/atp721/collection/NOPE/editions") == "unknown collection")
check("bad editions cursor is 400", expect_bad("/api/v1/atp721/collection/MAM-GENESIS/editions", cursor="!!!") == "bad cursor")

# ---- op= filter: mint (21 + 1 ignored dup = 22), no transfers, burn is not an ATP-721 op ----
mt = api("/api/v1/atp721/collection/MAM-GENESIS/txs", op="mint")
mt2 = api("/api/v1/atp721/collection/MAM-GENESIS/txs", op="mint", cursor=mt["next_cursor"])
mints = mt["txs"] + mt2["txs"]
check("op=mint returns only mint ops and all 22 of them",
      len(mints) == 22 and mt2["next_cursor"] is None and all(r["op"] == "m" for r in mints)
      and tid(1) not in [r["txid"] for r in mints])
check("op=transfer returns an empty page with no cursor",
      len(api("/api/v1/atp721/collection/MAM-GENESIS/txs", op="transfer")["txs"]) == 0
      and api("/api/v1/atp721/collection/MAM-GENESIS/txs", op="transfer")["next_cursor"] is None)
check("op=burn is 400 for ATP-721", "op must be one of" in expect_bad("/api/v1/atp721/collection/MAM-GENESIS/txs", op="burn"))
check("unknown op value is 400", "op must be one of" in expect_bad("/api/v1/atp721/collection/MAM-GENESIS/txs", op="swap"))

check("limit 1 pages with a cursor", len(api("/api/v1/atp721/collections", limit=1)["collections"]) == 1)
check("bare /api/atp721 is 404", "unknown" in expect_404("/api/atp721"))
check("unknown atp721 path is 404", "unknown" in expect_404("/api/v1/atp721/nope"))

# ---- minters: newest first mint first, default 20, 21 agents each minting one ----
mn = api("/api/v1/atp721/collection/MAM-GENESIS/minters")
check("minters default page is 20 with a next cursor",
      len(mn["minters"]) == 20 and mn["next_cursor"] and all(x["official"] is False for x in mn["minters"]))
mn2 = api("/api/v1/atp721/collection/MAM-GENESIS/minters", cursor=mn["next_cursor"])
check("minters second page completes the 21 agents with no further cursor",
      len(mn["minters"]) + len(mn2["minters"]) == 21 and mn2["next_cursor"] is None)
check("minters rows carry agent, first_mint_ts, mint_count and last_txid",
      all({"agent", "first_mint_ts", "mint_count", "last_txid"} <= set(x) and x["mint_count"] >= 1 for x in mn["minters"]))
check("unknown collection minters is 404", expect_404("/api/v1/atp721/collection/NOPE/minters") == "unknown collection")
check("bad minters cursor is 400", expect_bad("/api/v1/atp721/collection/MAM-GENESIS/minters", cursor="!!!") == "bad cursor")

# art works API (static hash, no memos in this temp db)
works = api("/api/v1/art/works")
check("art works unofficial and names Genesis by Digivatar",
      works["official"] is False and works["coverage"]["official"] is False
      and works["works"][0]["id"] == "e85fe08f" and works["works"][0]["name"] == "Genesis"
      and works["works"][0].get("credit") == "Digivatar"
      and works["works"][0]["ok"] is True
      and works["works"][0]["gif"] in ("/static/apps/digivatar-e85fe08f.gif", "/art/raster/e85fe08f"))
onew = api("/api/v1/art/works/e85fe08f")
check("one work is unofficial and hash-checked",
      onew["official"] is False and onew["work"]["ok"] is True
      and onew["work"]["file_sha"] == "415322abc005eb984a8200868fb4fe6ddf0e126dd024b03e21d3eae7d232d217")
check("unknown work is 404", "unknown" in expect_404("/api/v1/art/works/deadbeef"))

# ---- apps art gallery: unique AC1 works mapped to the card shape ----
ag = api("/api/v1/apps/art")
check("apps art unofficial, lists Genesis mapped to the card shape",
      ag["official"] is False and ag["coverage"]["official"] is False and len(ag["art"]) >= 1
      and ag["art"][0]["id"] == "e85fe08f" and ag["art"][0]["title"] == "Genesis"
      and {"id", "title", "owner", "image_ref", "still_ref", "seal"} <= set(ag["art"][0])
      and ag["art"][0]["image_ref"] in ("/static/apps/digivatar-e85fe08f.gif", "/art/raster/e85fe08f"))
check("apps unknown path is 404", "unknown" in expect_404("/api/v1/apps/nope"))

spec = AG.openapi()
paths = spec["paths"]
for pth in ("/api/v1/atp721/collections", "/api/v1/atp721/collection/{col}",
            "/api/v1/atp721/collection/{col}/units", "/api/v1/atp721/collection/{col}/holders",
            "/api/v1/atp721/collection/{col}/txs", "/api/v1/atp721/collection/{col}/editions",
            "/api/v1/atp721/collection/{col}/minters",
            "/api/v1/art/works", "/api/v1/art/works/{id}", "/api/v1/apps/art"):
    check(f"openapi has {pth}", pth in paths)
txt = AG.llms_txt()
check("llms.txt names the unofficial ATP-721 and art routes",
      "/atp721/collections" in txt and "/art/works" in txt and "/apps/art" in txt and "official is always false" in txt)
check("version is 1.26.423", AG.VERSION == "1.26.423")
check("no em or en dash in new API strings",
      not any(d in T.OFFICIAL_NOTE or d in T.ORDERING_NOTE or d in json.dumps(lst) or d in txt for d in DASH))

print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
