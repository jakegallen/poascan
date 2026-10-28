"""Genesis cut carry (1.26.209, Governance, Established): per address carry of Established across the genesis cut from the
genesis import and both segments' close records, neutral labels, addresses only, sortable headers, filters, the card,
/api/v1/governance/genesis-carry and MCP get_genesis_carry. No network. Usage: python3 tools/carry_test.py"""
import json, os, re, sys, tempfile
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "c.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, carry as CY, estfold as EF, agentapi as AG, views as V, governance as G, segments as SG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
ad = lambda i: "poa1" + format(i, "040d").replace("0", "Q")
S1X = {"epoch": 3, "basis": {"established_after": [ad(8)], "established_removed": [ad(1)], "challenge_eligible": [ad(8)]}}   # after the carried close: ignored
S1 = [{"epoch": 0, "basis": {"established_after": [ad(1), ad(2), ad(3)], "challenge_eligible": [ad(1), ad(2), ad(3), ad(4)]}},
      {"epoch": 1, "basis": {"established_removed": [ad(3)], "challenge_eligible": [ad(1), ad(4)]}},
      {"epoch": 2, "basis": {"established_after": [ad(4)], "challenge_eligible": [ad(1), ad(2)]}}]
S2 = [{"epoch": 0, "basis": {"established_after": [ad(5)]}, "rewards": {ad(1): "10", ad(5): "4", ad(9): "0"}},
      {"epoch": 1, "basis": {}, "rewards": {ad(1): "5", ad(2): "1"}}]
IMP = frozenset([ad(1), ad(2), ad(6)])
db.init(); A._cache.clear()
A.segment_closes = lambda n: {1: S1 + [S1X], 2: S2}.get(n, [])
_cc_real = CY.carried_close(); CY.carried_close = lambda: 2
EF.imported = lambda seg: IMP if seg == 2 else frozenset()
EF.import_info = lambda seg: {"url": "https://example.invalid/genesis", "sha256": "ab" * 32, "established_count": 3}
A.params = lambda: {}
d = CY.data(); R = {r["address"]: r for r in d["rows"]}
check("rows: import set plus S1 established at the carried close (1, 2, 4, 6); closes after it ignored", sorted(R) == sorted([ad(1), ad(2), ad(4), ad(6)]))
check("counts: carried 3, S1 last close 3, both 2, import only 1, records only 1", d["counts"] == dict(rows=4, carried=3, s1_established=3, both=2, carried_only=1, s1_only=1))
check("S1 close is the carried close E2", d["s1_close"] == 2)
check("carried close read from segments.json", _cc_real == max(x["epoch"] for c in SG.cuts() for x in c.get("carried_closes") or [] if x.get("segment") == 1))
check("ad1: carried, S1 established, eligible at E2, S2 rewards 15 over 2 closes", R[ad(1)]["carried"] and R[ad(1)]["s1_established"] and R[ad(1)]["s1_eligible"]
      and R[ad(1)]["s2_rewards"] == 15 and R[ad(1)]["s2_paid_closes"] == 2)
check("ad4: established at E2 in S1, not carried, not eligible at E2", not R[ad(4)]["carried"] and R[ad(4)]["s1_established"] and not R[ad(4)]["s1_eligible"])
check("ad6: carried, not established in S1 records", R[ad(6)]["carried"] and not R[ad(6)]["s1_established"] and not R[ad(6)]["s1_eligible"])
check("ad3 removed in S1 and not imported: no row; ad8 (after the carried close) no row", ad(3) not in R and ad(8) not in R)
check("S2 admitted only for addresses not carried", all(r["s2_admitted"] is None for r in d["rows"] if r["carried"]))
check("rows carry no display name", all("name" not in r for r in d["rows"]))
check("filters", len(CY.select("carried")) == 3 and len(CY.select("not_carried")) == 1)
check("sort by S2 rewards, desc", [r["address"] for r in CY.select("", "s2_rw", "desc")][:2] == [ad(1), ad(2)])
h = CY.card_html({"carry": ["carried"]}, G.href)
check("card: id carry, title, chips with counts, sortable headers, method link", 'id="carry"' in h and "Genesis cut carry · 3" in h and "Not carried" in h and "/about#carry" in h and "csort=" in h)
check("card: neutral, no ranking words", not re.search(r"\b(unfair|excluded|cheat|winner|loser|rank)\w*", h, re.I))
a = CY.api(ad(4))
check("api ?address=: one row", a["total"] == 1 and a["rows"][0]["address"] == ad(4) and a["genesis_import"]["sha256"] == "ab" * 32)
check("api filter", CY.api(None, "not_carried")["total"] == 1)
check("MCP get_genesis_carry listed", "get_genesis_carry" in [x[0] for x in AG.TOOLS])
check("OpenAPI lists /governance/genesis-carry", "genesis-carry" in json.dumps(AG.openapi()))
ab = V.about(); sec = ab[ab.find('id="carry"'):ab.find('id="records"')]
check("about: #carry with the column definitions", 'id="carry"' in ab and "challenge_eligible" in sec and "established_after" in sec)
src = open(CY.__file__).read() + sec + h
check("no dashes in copy", "\u2014" not in src and "\u2013" not in src)
check("no prohibited names or close numbers outside the carried close", not re.search(r"plus\s?1|\bE1[24]\b|\bE3\b|excluded", src, re.I))
check("api names no segment 1 close but the carried one", "s1_last" not in json.dumps(a) and CY.api()["s1_carried_close"] == 2)
print("ALL OK" if not fails else f"{len(fails)} FAILED: {fails}"); sys.exit(1 if fails else 0)
