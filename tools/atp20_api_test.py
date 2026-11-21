"""ATP-20 unofficial read API (1.26.410): keyset-paged list, holders, txs, pending and balance,
every balance and holder figure labeled unofficial, coverage fields, default 20 rows, no pages,
no upstream reads, no em or en dashes.
Usage: python3 tools/atp20_api_test.py"""
import json, os, sys, tempfile, copy
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, atp20 as T, indexer as IX, server as SV, agentapi as AG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
DASH = ("\u2014", "\u2013")
db.init()

DEP = "poa1DLtfHN8rajwqj7VdDHYLQ8MFwJGguXww6XU1tn7KNRVg"
# 21 synthetic holders so the default page size of 20 must cursor
HOLDERS = ["poa1aabbccddeef" + ch + "aaaaaaaaaaaaaaaaaaa" for ch in "abcdefghjkmnpqrstuvwx"]

def tid(n):
    return format(n, "064x")

def row(i, memo, fr, to=None, ts=1795179000, final=1, typ="transfer"):
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

load(row(1, "ATP-20|d|SEAL|21000000|8|1000", DEP, ts=1795174507),
     row(2, "ATP-20|m|SEAL|1000", DEP, ts=1795175185),
     row(3, "ATP-20|d|MAM|21000000|0||open:1000:5", DEP, ts=1795178150))
for i, addr in enumerate(HOLDERS):
    load(row(100 + i, "ATP-20|m|MAM|1000", addr, ts=1795180000 + i))
# one pending MAM mint and one ignored over-cap mint
load(row(200, "ATP-20|m|MAM|1000", HOLDERS[0], ts=1795181000, final=0))
load(row(201, "ATP-20|m|MAM|1000", HOLDERS[0], ts=1795181001, final=1))  # second mint ok
load(row(202, "ATP-20|m|MAM|999", HOLDERS[1], ts=1795181002, final=1))   # wrong amount, ignored

# ---- list ----
lst = api("/api/v1/atp20/tokens")
check("tokens: unofficial envelope and coverage",
      lst["official"] is False and "Unofficial" in lst["official_note"]
      and lst["coverage"]["official"] is False and lst["coverage"]["ordering"] == "ts_id"
      and lst["coverage"]["burn"] == "from_addr" and lst["next_cursor"] is None)
ticks = [t["tick"] for t in lst["tokens"]]
check("tokens: SEAL then MAM, each unofficial", ticks == ["SEAL", "MAM"] and all(t["official"] is False for t in lst["tokens"]))
check("tokens: unknown query param is 400", "unknown parameter" in expect_bad("/api/v1/atp20/tokens", foo=1))

# ---- one token ----
one = api("/api/v1/atp20/token/SEAL")
check("token SEAL: unofficial minted 1000", one["official"] is False and one["token"]["official"] is False
      and one["token"]["minted"] == "1000" and one["token"]["decimals"] == 8 and one["coverage"]["ordering"] == "ts_id")
check("unknown tick is 404", expect_404("/api/v1/atp20/token/NOPE") == "unknown tick")
check("lowercase tick is 404 endpoint", "unknown" in expect_404("/api/v1/atp20/token/seal"))

# ---- holders keyset, default 20 ----
h = api("/api/v1/atp20/token/MAM/holders")
check("holders default page is 20 with a next cursor",
      len(h["holders"]) == 20 and h["next_cursor"] and all(x["official"] is False for x in h["holders"]))
h2 = api("/api/v1/atp20/token/MAM/holders", cursor=h["next_cursor"])
check("holders second page has the rest and no further cursor",
      len(h2["holders"]) >= 1 and h2["next_cursor"] is None
      and not set(x["addr"] for x in h["holders"]) & set(x["addr"] for x in h2["holders"]))
# first of 21 mints should still be 1000; HOLDERS[0] minted twice so 2000 and should be first
check("highest holder is first and unofficial", h["holders"][0]["amount"] == "2000" and h["holders"][0]["official"] is False
      and h["holders"][0]["addr"] == HOLDERS[0])
check("bad holders cursor is 400", expect_bad("/api/v1/atp20/token/MAM/holders", cursor="!!!") == "bad cursor")

# ---- txs: final only, includes ignored, newest first, keyset ----
# 21 first-mints + second mint + ignored 999 + deploy = 24 final MAM ops
tx = api("/api/v1/atp20/token/MAM/txs")
check("txs default page is 20 with a cursor", len(tx["txs"]) == 20 and tx["next_cursor"] and tx["official"] is False)
tx2 = api("/api/v1/atp20/token/MAM/txs", cursor=tx["next_cursor"])
check("txs second page completes the set", len(tx["txs"]) + len(tx2["txs"]) == 24 and tx2["next_cursor"] is None)
ids = [r["txid"] for r in tx["txs"] + tx2["txs"]]
check("pending mint is not in the txs list", tid(200) not in ids)
check("ignored wrong-amount mint is in the txs list with a reason",
      any(r["txid"] == tid(202) and r["valid"] == 0 and r["reason"] == "mint_amount" for r in tx["txs"] + tx2["txs"]))
all_tx = tx["txs"] + tx2["txs"]
check("txs are newest first", all(all_tx[i]["ts"] >= all_tx[i+1]["ts"] for i in range(len(all_tx) - 1)))

# ---- pending ----
pend = api("/api/v1/atp20/pending/MAM")
check("pending lists the unfinalized mint only",
      len(pend["pending"]) == 1 and pend["pending"][0]["txid"] == tid(200) and pend["next_cursor"] is None
      and pend["official"] is False)

# ---- balance ----
bal = api("/api/v1/atp20/balance/MAM/" + HOLDERS[0])
check("balance is unofficial and 2000", bal["official"] is False and "Unofficial" in bal["official_note"]
      and bal["amount"] == "2000" and bal["mint_count"] == 2 and bal["coverage"]["official"] is False)
zero = api("/api/v1/atp20/balance/MAM/" + DEP)
check("known tick, no mints: unofficial zero", zero["amount"] == "0" and zero["official"] is False)
check("balance unknown tick is 404", expect_404("/api/v1/atp20/balance/NOPE/" + DEP) == "unknown tick")

# ---- v1 alias and limit cap ----
v1 = SV.api  # prefix rewrite is in the handler, not api(); check http() accepts /api/atp20
# server rewrites /api/v1 before api(). Simulate that.
check("limit 1 pages with a cursor", len(api("/api/v1/atp20/tokens", limit=1)["tokens"]) == 1
      and api("/api/v1/atp20/tokens", limit=1)["next_cursor"])
# out of range clamps
check("limit above max is clamped to 200", len(api("/api/v1/atp20/token/MAM/holders", limit=5000)["holders"]) <= 200)
check("bare /api/atp20 is 404", "unknown" in expect_404("/api/atp20"))
check("unknown atp20 path is 404", "unknown" in expect_404("/api/v1/atp20/nope"))

# ---- minters: newest first mint first, default 20, HOLDERS[0] minted twice ----
mn = api("/api/v1/atp20/token/MAM/minters")
check("minters default page is 20 with a next cursor",
      len(mn["minters"]) == 20 and mn["next_cursor"] and all(x["official"] is False for x in mn["minters"]))
mn2 = api("/api/v1/atp20/token/MAM/minters", cursor=mn["next_cursor"])
check("minters second page completes the 21 agents with no further cursor",
      len(mn["minters"]) + len(mn2["minters"]) == 21 and mn2["next_cursor"] is None)
allm = {x["agent"]: x for x in mn["minters"] + mn2["minters"]}
check("the twice-minter shows mint_count 2 and a last_txid", allm[HOLDERS[0]]["mint_count"] == 2 and bool(allm[HOLDERS[0]]["last_txid"]))
check("minters rows carry agent, first_mint_ts, mint_count and last_txid",
      all({"agent", "first_mint_ts", "mint_count", "last_txid"} <= set(x) for x in mn["minters"]))
check("unknown tick minters is 404", "unknown" in expect_404("/api/v1/atp20/token/ZZZ/minters"))
check("bad minters cursor is 400", expect_bad("/api/v1/atp20/token/MAM/minters", cursor="!!!") == "bad cursor")

# ---- OpenAPI and llms ----
spec = AG.openapi()
paths = spec["paths"]
for pth in ("/api/v1/atp20/tokens", "/api/v1/atp20/token/{tick}", "/api/v1/atp20/token/{tick}/holders",
            "/api/v1/atp20/token/{tick}/txs", "/api/v1/atp20/token/{tick}/minters", "/api/v1/atp20/pending/{tick}", "/api/v1/atp20/balance/{tick}/{address}"):
    check(f"openapi has {pth}", pth in paths)
txt = AG.llms_txt()
check("llms.txt names the unofficial ATP-20 routes", "/atp20/tokens" in txt and "official is always false" in txt)
check("no em or en dash in new API strings",
      not any(d in T.OFFICIAL_NOTE or d in T.ORDERING_NOTE or d in json.dumps(lst) or d in txt for d in DASH))

print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
