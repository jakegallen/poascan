"""Opt-in kin groups: mutual claims on one LabLeak claim post. No request leaves the box (fetch is replaced and counted)
and no comment is ever posted: POAScan only reads its own forum archive.

* A group is active only while EVERY listed member's latest claim lists exactly the same sorted members and label.
* `kin: leave` drops that member at once; a changed list or no claim makes the group inactive. Nothing is inferred.
* Cap 50 members; malformed claims are ignored. group_id = sha256 of the sorted members joined with commas.
* API kin field, /api/v1/kin/<group_id>, MCP get_address kin and get_kin_group, OpenAPI, llms.txt, address Kin row, /about#kin.
* Seating, grading and operator families do not read kin claims.
Usage: python3 tools/kin_groups_test.py"""
import hashlib, json, os, re, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

POST, OTHER = 9001, 9002
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "k.db"), POA_BASE="http://127.0.0.1:9", POASCAN_INDEXER="0", POASCAN_KIN_POST=str(POST))
import fixture; fixture.seed()
from poascan import db, kin as KN, indexer as I, agentapi as AG, server as SV, views as V, agents as G, analytics as AN
UP = []
def _nofetch(*a, **k): UP.append(a[0] if a else "?"); raise I.Busy("no upstream in tests")
I.fetch = _nofetch
V.address_read = lambda a: (None, None, None)   # address pages and API: archive only

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def ad(i): return "poa1" + "K" + B58[i // 58 % 58] + B58[i % 58] + "k" * 37
A, B, C, D, E_, F, G_, H, J = (ad(i) for i in range(1, 10))
check("test addresses are valid poa1 addresses", all(KN.ADDR_RX.match(x) for x in (A, B, C, D, E_, F, G_, H, J)))
db.write("INSERT OR IGNORE INTO accounts(addr,balance,balance_s,first_seen,last_seen) VALUES(?,?,?,?,?)", [(x, 1.0, "1.000000", 1, 1) for x in (A, B, C, D, E_, F, G_, H, J)], many=True)
T0 = 1_792_000_000
CID = [5000]
def at(t): return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))
def say(addr, body, t, post=POST):
    CID[0] += 1
    db.write("INSERT INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body) VALUES(?,?,?,?,?,?,?,?)",
             (CID[0], post, None, "n" + addr[-4:], addr, at(t), 0, body))
    KN.sync(); return CID[0]
def claim(addr, label, members, t, post=POST): return say(addr, f"kin: {label} members: {','.join(members)}", t, post)
def gid(ms): return hashlib.sha256(",".join(sorted(ms)).encode()).hexdigest()

fam0 = {k: v for k, v in G.operators()["fam_of"].items()}

# ---------------- mutual match ----------------
AB = sorted([A, B])
claim(A, "alpha team", AB, T0 + 10)
k = KN.kin(A)
check("one side only: A's group is inactive, B has no kin (never claimed)", k and k["status"] == "inactive" and KN.kin(B) is None and k["declared_at"] is None)
c2 = claim(B, "alpha team", AB, T0 + 20)
ka, kb = KN.kin(A), KN.kin(B)
check("mutual match: both active, same group", ka["status"] == kb["status"] == "active" and ka["group_id"] == kb["group_id"] == gid(AB))
check("group_id is sha256 of the sorted members joined with commas", ka["group_id"] == hashlib.sha256(f"{AB[0]},{AB[1]}".encode()).hexdigest())
check("kin shape: group_id, label, members, status, declared_at, evidence_urls, active_before_declared",
      set(ka) == {"group_id", "label", "members", "status", "declared_at", "evidence_urls", "active_before_declared"} and ka["label"] == "alpha team" and ka["members"] == AB)
check("declared_at is when the last member's matching claim landed", ka["declared_at"] == T0 + 20 and ka["active_before_declared"] is False)
check("evidence_urls: one claim comment per member", len(ka["evidence_urls"]) == 2 and any(str(c2) in u for u in ka["evidence_urls"]) and all(u.startswith("https://minepoa.com/lableak/#/post/9001") for u in ka["evidence_urls"]))

# ---------------- one-sided claim (no inference) ----------------
claim(C, "solo", sorted([C, D]), T0 + 30)
g = KN.group(gid([C, D]))
check("one-sided claim: inactive, the unclaimed member reads none and has no kin", KN.kin(C)["status"] == "inactive" and KN.kin(D) is None
      and {m["address"]: m["state"] for m in g["member_claims"]} == {C: "match", D: "none"})

# ---------------- mismatch ----------------
EFG = sorted([E_, F, G_]); EF = sorted([E_, F])
claim(E_, "trio", EFG, T0 + 40); claim(F, "trio", EF, T0 + 41); claim(G_, "trio", EFG, T0 + 42)
check("mismatch: different member lists make both groups inactive", KN.kin(E_)["status"] == "inactive" and KN.kin(F)["status"] == "inactive"
      and KN.kin(G_)["group_id"] == gid(EFG) and KN.kin(F)["group_id"] == gid(EF))
check("mismatch: member_claims shows the member on a different list", {m["address"]: m["state"] for m in KN.group(gid(EFG))["member_claims"]}[F] == "different")
HJ = sorted([H, J])
claim(H, "one", HJ, T0 + 43); claim(J, "two", HJ, T0 + 44)
check("mismatch: same members under different labels stay inactive", KN.kin(H)["status"] == "inactive" and KN.kin(J)["status"] == "inactive" and KN.kin(J)["label"] == "two")
claim(F, "trio", EFG, T0 + 45)
check("a member that fixes its list makes the group active", KN.kin(E_)["status"] == "active" and KN.kin(F)["group_id"] == gid(EFG) and KN.kin(E_)["declared_at"] == T0 + 45)

# ---------------- leave and re-join ----------------
say(A, "kin: leave", T0 + 50)
g = KN.group(gid(AB))
check("leave: the member drops at once (no kin), the group reads inactive for the rest", KN.kin(A) is None and KN.kin(B)["status"] == "inactive"
      and {m["address"]: m["state"] for m in g["member_claims"]}[A] == "left" and g["periods"] == [dict(start=T0 + 20, end=T0 + 50)])
check("inactive keeps the last declared_at; evidence lists only matching claims", KN.kin(B)["declared_at"] == T0 + 20 and len(KN.kin(B)["evidence_urls"]) == 1)
claim(A, "alpha team", AB, T0 + 60)
ka = KN.kin(A)
check("re-join: active again, declared_at is the re-join, active_before_declared true", ka["status"] == "active" and ka["declared_at"] == T0 + 60 and ka["active_before_declared"] is True
      and len(KN.group(gid(AB))["periods"]) == 2)
say(B, "KIN: Leave", T0 + 70)
check("leave is case-insensitive", KN.kin(B) is None and KN.kin(A)["status"] == "inactive")
claim(B, "alpha team", AB, T0 + 80)

# ---------------- cap ----------------
big = sorted([A] + [ad(100 + i) for i in range(50)])   # 51
cid = say(A, f"kin: big members: {','.join(big)}", T0 + 90)
row = db.q1("SELECT kind, reason FROM kin_claims WHERE comment_id=?", (cid,))
check("cap: 51 members is rejected (malformed) and does not replace A's latest claim", row["kind"] == "malformed" and "50" in row["reason"] and KN.kin(A)["group_id"] == gid(AB))
fifty = sorted([C] + [ad(200 + i) for i in range(49)])
claim(C, "fifty", fifty, T0 + 91)
check("cap: exactly 50 members is accepted", KN.kin(C)["group_id"] == gid(fifty) and len(KN.kin(C)["members"]) == 50 and KN.kin(C)["status"] == "inactive")

# ---------------- A to Z with mixed case ----------------
U1 = "poa1" + "Zq" + "k" * 38; L1 = "poa1" + "aq" + "k" * 38; U2 = "poa1" + "Bq" + "k" * 38   # base58 mixes cases
check("byte order and A to Z differ for mixed case", sorted([U1, L1, U2]) == [U2, U1, L1] and sorted([U1, L1, U2], key=str.lower) == [L1, U2, U1])
AZ = [L1, U2, U1]; BY = [U2, U1, L1]
claim(L1, "mixed", AZ, T0 + 95); claim(U2, "mixed", BY, T0 + 96); claim(U1, "mixed", AZ, T0 + 97)
k = KN.kin(L1)
check("A to Z (case-insensitive) and byte order both pass, and are the same group", k and k["status"] == "active" and k["group_id"] == gid(AZ) == gid(BY) and k["members"] == BY
      and KN.kin(U2)["group_id"] == k["group_id"])
cid = say(L1, f"kin: mixed members: {U1},{L1},{U2}", T0 + 98)
check("an order that is neither A to Z nor byte order is still malformed", db.q1("SELECT kind FROM kin_claims WHERE comment_id=?", (cid,))["kind"] == "malformed" and KN.kin(L1)["status"] == "active")
check("addresses stay case-sensitive: a case variant is a different member", KN.parse(f"kin: x members: {'poa1' + 'Aq' + 'k' * 38},{L1}", L1)["kind"] == "claim"
      and gid([L1, "poa1" + "Aq" + "k" * 38]) != gid([L1, "poa1" + "aQ" + "k" * 38]))

# ---------------- malformed ----------------
bad = {"unsorted": f"kin: x members: {AB[1]},{AB[0]}", "commenter missing": f"kin: x members: {','.join(sorted([D, H]))}",
       "duplicate": f"kin: x members: {A},{A}", "bad address": f"kin: x members: {A},poa1bad", "one member": f"kin: x members: {A}",
       "bad label": f"kin: <b>x</b> members: {','.join(AB)}", "two lines": f"kin: x members: {AB[0]},\n{AB[1]}", "no members": "kin: hello",
       "label leave": f"kin: leave members: {','.join(AB)}"}
ok = True
for why, body in bad.items():
    cid = say(A, body, T0 + 100); r = db.q1("SELECT kind FROM kin_claims WHERE comment_id=?", (cid,))
    ok = ok and r is not None and r["kind"] == "malformed"
check("malformed claims are stored as malformed: " + ", ".join(bad), ok)
check("malformed claims never change the latest claim or status", KN.kin(A)["group_id"] == gid(AB) and KN.kin(A)["status"] == "active")
say(A, "great thread, kin is a nice idea", T0 + 101)
check("ordinary comments on the claim post are not kin comments", db.q1("SELECT COUNT(*) AS n FROM kin_claims WHERE comment_id=?", (CID[0],))["n"] == 0)
claim(D, "elsewhere", sorted([C, D]), T0 + 102, post=OTHER)
check("claims on any other post are ignored", KN.kin(D) is None)
db.write("INSERT INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body) VALUES(?,?,?,?,?,?,?,?)",
         (99999, POST, None, "anon", "not-an-address", at(T0 + 103), 0, f"kin: x members: {','.join(AB)}")); KN.sync()
check("comments without a poa1 author are ignored", db.q1("SELECT COUNT(*) AS n FROM kin_claims WHERE comment_id=99999")["n"] == 0)

# ---------------- no inference ----------------
check("no inference: shared invites, labels or families never create a kin group", all(KN.kin(x) is None for x in (fixture.A1, fixture.A2, fixture.A3, D)))
AN._cache.clear()   # recompute operator families from scratch
check("operator families are unchanged by kin claims", G.operators()["fam_of"] == fam0)
src = {f: open(os.path.join(ROOT, "poascan", f)).read() for f in ("agents.py", "standing.py", "calibration.py")}
check("seating, grading and family code never read kin", not any(re.search(r"\bkin\b|kin_claims", s) for s in src.values()))

# ---------------- API and MCP ----------------
r, _ = SV.api(f"/api/address/{A}", {})
check("/api/v1/address carries kin", r["kin"]["group_id"] == gid(AB) and r["kin"]["status"] == "active")
r, _ = SV.api(f"/api/address/{D}", {})
check("/api/v1/address kin is null without a claim", "kin" in r and r["kin"] is None)
r, _ = SV.api(f"/api/kin/{gid(AB)}", {})
check("/api/v1/kin/<group_id>: group with member_claims and periods", r["members"] == AB and {m["state"] for m in r["member_claims"]} == {"match"} and len(r["periods"]) == 3 and r["method"] == "/about#kin")
r, _ = SV.api(f"/api/kin/{gid(AB).upper()}", {})
check("/api/v1/kin accepts upper-case hex", r["group_id"] == gid(AB))
for p, qs, exc in ((f"/api/kin/{'0' * 64}", {}, SV.NotFound), ("/api/kin/abc", {}, SV.BadRequest), (f"/api/kin/{gid(AB)}", {"x": ["1"]}, SV.BadRequest)):
    try: SV.api(p, qs); ok = False
    except exc: ok = True
    check(f"/api/v1/kin rejects {p[9:21]}{' with a parameter' if qs else ''} ({exc.__name__})", ok)
mcp = lambda name, args: AG.handle_mcp(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}).encode())[1]
res = mcp("get_kin_group", {"group_id": gid(AB)})
body = json.loads(res["result"]["content"][0]["text"]) if "result" in res else {}
check("MCP get_kin_group returns the group", body.get("found") is True and body.get("group_id") == gid(AB) and body.get("status") == "active")
res = mcp("get_kin_group", {"group_id": "0" * 64})
body = json.loads(res["result"]["content"][0]["text"]) if "result" in res else {}
check("MCP get_kin_group: an unknown group reads found false", body.get("found") is False)
res = mcp("get_kin_group", {"group_id": "nope"})
check("MCP get_kin_group rejects a bad group_id", res.get("result", {}).get("isError") is True or "error" in res)
res = mcp("get_address", {"address": A, "tx_limit": 0})
body = json.loads(res["result"]["content"][0]["text"]) if "result" in res else {}
check("MCP get_address carries kin", (body.get("kin") or {}).get("group_id") == gid(AB))
check("MCP tools list get_kin_group", "get_kin_group" in [t["name"] for t in AG.tools_list()])
spec = AG.openapi()
check("OpenAPI: /api/v1/kin/{group_id}, Kin and KinGroup schemas, kin on the address op", "/api/v1/kin/{group_id}" in spec["paths"] and {"Kin", "KinGroup"} <= set(spec["components"]["schemas"])
      and "kin" in json.dumps(spec["paths"]["/api/v1/address/{address}"]))
try: llms = AG.llms_txt()
except Exception: llms = ""
check("llms.txt describes kin groups", "/kin/<group_id>" in llms and "get_kin_group" in llms)

# ---------------- pages ----------------
html = V.address(A)
row = re.search(r'<span>Kin</span><div>(.*?)</div></div>', html)
check("address page: Kin row, ACTIVE, label, links to the other member", row and "ACTIVE" in row.group(1) and "alpha team" in row.group(1) and f'href="/address/{B}"' in row.group(1) and "about#kin" in row.group(1))
check("Kin row is one line: no sub-lines, no em or en dash", row and "<br" not in row.group(1) and "<p" not in row.group(1) and not re.search("[\u2013\u2014]", row.group(1)))
say(A, "kin: leave", T0 + 200)
row = re.search(r'<span>Kin</span><div>(.*?)</div></div>', V.address(B))
check("address page: INACTIVE after a member leaves", row and "INACTIVE" in row.group(1))
check("address page: no Kin row without a claim", "<span>Kin</span>" not in V.address(D) and "<span>Kin</span>" not in V.address(A))
cr = re.search(r'<span>Kin</span><div>(.*?)</div></div>', V.address(C)).group(1)
check("a 50-member group shows 8 links and a +41 link to the group API", cr.count('class="mono addr"') == 8 and f'/api/v1/kin/{gid(fifty)}">+41<' in cr)
ab = V.about()
check("/about#kin has the method, no em or en dash", 'id="kin"' in ab and "kin: leave" in ab and not re.search("[\u2013\u2014]", V.kin_method()))

# ---------------- ingest and config ----------------
db.write("DELETE FROM kin_claims")
I.ingest_post({"id": POST, "community": "poa", "title": "Kin claims", "author": "x", "author_public_id": A, "created_at": at(T0), "pinned": 1,
               "comments": [{"id": 7001, "author_public_id": H, "created_at": at(T0 + 300), "body": f"kin: duo members: {','.join(HJ)}"},
                            {"id": 7002, "author_public_id": J, "created_at": at(T0 + 301), "body": f"kin: duo members: {','.join(HJ)}"}]})
check("ingesting the claim post rebuilds kin claims from its comments", KN.kin(H)["status"] == "active" and KN.kin(H)["label"] == "duo")
check("kin made no upstream request", UP == [])
# The hourly forum job reads the claim post's comments only when its comment count changes; nothing else is added.
calls = []
def fake(path, *a, **k):
    calls.append(path)
    if path.endswith("/communities"): return [{"slug": "workshop"}]
    if "/posts?" in path: return [{"id": POST, "community": "workshop", "title": "Kin groups", "author": "POAScan", "author_public_id": A, "created_at": at(T0), "comment_count": NC[0]}]
    if path.endswith(f"/posts/{POST}"): return {"id": POST, "community": "workshop", "title": "Kin groups", "author": "POAScan", "author_public_id": A, "created_at": at(T0),
                                                "comments": [{"id": 7101, "author_public_id": H, "created_at": at(T0 + 400), "body": f"kin: trio members: {','.join(HJ)}"},
                                                             {"id": 7102, "author_public_id": J, "created_at": at(T0 + 401), "body": f"kin: trio members: {','.join(HJ)}"}][:NC[0]]}
    raise AssertionError(path)
db.write("DELETE FROM forum_posts WHERE id=?", (POST,)); db.write("DELETE FROM forum_comments WHERE post_id=?", (POST,))   # a new post, as 1431 was
NC = [2]; I.fetch = fake; _sleep = I.time.sleep; I.time.sleep = lambda s: None
try:
    I.job_forum(); first = list(calls); calls.clear(); I.job_forum(); second = list(calls)
finally: I.time.sleep = _sleep; I.fetch = _nofetch
check("forum job: a changed comment count fetches the claim post once and rebuilds kin", first.count(f"/lableak/api/posts/{POST}") == 1 and KN.kin(H)["label"] == "trio" and KN.kin(H)["status"] == "active")
check("forum job: an unchanged post is not fetched again (communities plus one list per community only)", f"/lableak/api/posts/{POST}" not in second and len(second) == 2)
KN.KIN_POST_ID = None; KN.sync()
check("no claim post set: kin is null and the table is empty", KN.kin(H) is None and KN.group(gid(HJ)) is None and db.q1("SELECT COUNT(*) AS n FROM kin_claims")["n"] == 0)
check("no claim post set: /about#kin says none is chosen", "not chosen yet" in V.kin_method())
import importlib; os.environ.pop("POASCAN_KIN_POST"); importlib.reload(KN)
check("shipped default: the live claim post 1431", KN.KIN_POST_ID == 1431 and KN.POST_URL.format(pid=KN.KIN_POST_ID) == "https://minepoa.com/lableak/#/post/1431")

print("\n" + ("ALL OK" if not fails else f"{len(fails)} FAILED"))
sys.exit(1 if fails else 0)
