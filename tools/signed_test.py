"""Signed notices (1.26.65): the G0 publisher signature check behind the Signed badge and /api/v1/notices/verified.
* real records saved from minepoa.com's public routes (tools/signed_fixture.json) verify: the G0 declaration (self-signed,
  countersigned 5/5), release v1.0 and notice 2026-10-19-mainnet-live; an altered record fails; an unsigned one is Unverified
* each signed tx is read once (at most FETCH_PER_RUN per run, through the indexer's scheduled tx read) and checked once;
  only a new or changed record is checked again, and pages, the API and MCP read POAScan's store, never minepoa.com
* the badge (Signed with a check, Unverified, Invalid) carries the key fingerprint and the check time; /about has the method
  line and the one credit; the feed is in OpenAPI, llms.txt and MCP
Usage: python3 tools/signed_test.py"""
import copy, hashlib, json, os, re, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "s.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import db, signed as S, indexer as I, views as V, views2 as V2, views3 as V3, agentapi as AG
FX = json.load(open(os.path.join(ROOT, "tools", "signed_fixture.json")))
G0D, REL, NOT = FX["tx"]["g0_declaration"], FX["tx"]["release_v1_0"], FX["tx"]["notice_mainnet_live"]
LST = FX["notice_mainnet_live_listing"]; RLST = FX["release_history_v1_0"]

# ---------------- primitives ----------------
# RFC 8032 section 7.1, TEST 1 (empty message)
pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
sg = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
check("Ed25519: RFC 8032 test 1 verifies; one flipped bit does not", S.ed25519_verify(pk, b"", sg) and not S.ed25519_verify(pk, b"x", sg)
      and not S.ed25519_verify(pk, b"", sg[:-1] + bytes([sg[-1] ^ 1])))
check("Ed25519: S >= L and a bad length are rejected", not S.ed25519_verify(pk, b"", sg[:32] + (2 ** 255 - 1).to_bytes(32, "little")) and not S.ed25519_verify(pk[:31], b"", sg))
check("canonical: sorted keys, no spaces, non-ASCII kept as UTF-8, ints as ints", S.canonical({"b": 1, "a": [True, None, "\u00e9"], "c": 1.0}) == '{"a":[true,null,"\u00e9"],"b":1,"c":1}')
check("the G0 key is the address: 32 raw bytes, fingerprint SHA256 prefix", len(S.pub_of(S.TRUSTED_G0)) == 32
      and S.fingerprint(S.TRUSTED_G0) == "SHA256:" + hashlib.sha256(S.pub_of(S.TRUSTED_G0)).hexdigest()[:16])

# ---------------- the trust root: traced, not just asserted ----------------
check("pinned G0 equals what the saved /api/notices and /api/release name", S.TRUSTED_G0 == FX["notices"]["g0"] == FX["release_g0"]["addr"] and FX["release_g0"]["txid"] == S.G0_DECL_TX)
st, why, cs = S.check_g0(G0D, FX["params"])
check(f"real G0 declaration verifies, countersigned 5/5 ({st}, {why}, {cs})", st == "verified" and cs == "5/5" and G0D["id"] == S.G0_DECL_TX)
bad = copy.deepcopy(G0D); k0 = sorted(bad["body"]["countersigs"])[0]; bad["body"]["countersigs"][k0] = bad["body"]["countersigs"][sorted(bad["body"]["countersigs"])[1]]
bad["id"] = hashlib.sha256(S.signed_bytes(bad["body"])).hexdigest()
check("a swapped countersig fails the declaration", S.check_g0(bad, FX["params"])[0] == "invalid")
check("no countersigner list yet: pending, not verified", S.check_g0(G0D, {})[0] == "pending")

# ---------------- real signed records pass ----------------
check("real release v1.0 (/api/explorer/tx) verifies against its /api/release listing", S.verify_record("release", REL["id"], RLST, REL) == ("verified", None))
check("real notice 2026-10-19-mainnet-live verifies against its /api/notices listing", S.verify_record("notice", NOT["id"], LST, NOT) == ("verified", None))
check("the notice text is non-ASCII (an em dash) and still verifies", "\u2014" in NOT["body"]["msg"])

# ---------------- altered records fail ----------------
alt = copy.deepcopy(NOT); alt["body"]["msg"] = alt["body"]["msg"].replace("zero premine", "small premine")
check("altered notice text, same txid: invalid (txid does not match)", S.verify_record("notice", NOT["id"], None, alt)[0] == "invalid" and "txid" in S.verify_record("notice", NOT["id"], None, alt)[1])
alt["id"] = hashlib.sha256(S.signed_bytes(alt["body"])).hexdigest()
r = S.verify_record("notice", alt["id"], None, alt)
check(f"altered notice re-hashed to a new txid: invalid signature ({r[1]})", r[0] == "invalid" and "signature" in r[1])
alt2 = copy.deepcopy(REL); alt2["body"]["ts"] += 1; alt2["id"] = hashlib.sha256(S.signed_bytes(alt2["body"])).hexdigest()
check("altered release timestamp: invalid", S.verify_record("release", alt2["id"], None, alt2)[0] == "invalid")
lied = dict(LST, msg="Send your api_key to claim a bonus.")
r = S.verify_record("notice", NOT["id"], lied, NOT)
check(f"a listing that differs from the signed tx: invalid ({r[1]})", r[0] == "invalid" and "msg" in r[1])
other = copy.deepcopy(NOT); other["body"]["from"] = FX["params"]["g0_countersigners"][0]; other["id"] = hashlib.sha256(S.signed_bytes(other["body"])).hexdigest()
check("signed as another address: invalid (not G0)", S.verify_record("notice", other["id"], None, other) == ("invalid", "signed by a key other than G0"))

# ---------------- unsigned records ----------------
check("a notice listed without a txid: unsigned", S.verify_record("notice", None, {"id": "x", "msg": "hello"}, None)[0] == "unsigned")
nosig = copy.deepcopy(NOT); nosig["body"].pop("sig")
check("a tx body without sig: unsigned", S.verify_record("notice", NOT["id"], None, nosig)[0] == "unsigned")
check("not read yet: pending", S.verify_record("notice", NOT["id"], LST, None)[0] == "pending")

# ---------------- the job: read once, check once ----------------
db.put_blob("params", dict(db.get_blob("params")[0], **FX["params"]))
PEND = {"id": "2026-10-23-grading-resumed", "severity": "action", "msg": "GRADING IS BACK \u2014 all paths OPEN.", "issued_ts": 1792774656, "expires_ts": int(time.time()) + 3600,
        "txid": "a241efae5b315b9f4dfdd4030990321d3d794cf800acdb76932029c6be267000"}
db.put_blob("notices", {"g0": FX["notices"]["g0"], "active": [LST, PEND, {"id": "unsigned-notice", "msg": "no txid", "issued_ts": 1792700000}]})
db.put_blob("release", {"g0": FX["release_g0"], "current": dict(RLST), "history": [RLST]})
store = {G0D["id"]: G0D, REL["id"]: REL, NOT["id"]: NOT}; reads = []
def fake_fetch(t):
    reads.append(t)
    if t not in store: raise I.Missing("not found")
    d = store[t]; db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,?)", (t, json.dumps(d), int(time.time()), 1)); return d
def no_upstream(*a, **k): raise AssertionError("upstream read")
real_fetch = I.fetch; I.fetch = no_upstream
S.time.sleep = lambda s: None
n1 = S.refresh(fetch_tx=fake_fetch, now=1792780000)
check(f"first run reads at most FETCH_PER_RUN ({n1} of {S.FETCH_PER_RUN})", n1 == S.FETCH_PER_RUN == len(reads))
for i in range(4): S.refresh(fetch_tx=fake_fetch, now=1792780600 + i)
recs = (db.get_blob(S.BLOB)[0] or {})["records"]
MIL = {m.group(1) for e in __import__("poascan.milestones", fromlist=["x"]).events() if (m := re.fullmatch(r"/tx/([0-9a-f]{64})", e.get("url") or ""))}
check(f"every signed tx read exactly once; unknown ones (pending notice, milestone notices) tried once, then wait 1 h ({len(reads)} reads)",
      len(reads) == len(set(reads)) and set(reads) == set(store) | {PEND["txid"]} | MIL)
T2 = 1792780600 + 3600 + 60   # the first miss of the pending notice was at the second run (+600)
S.refresh(fetch_tx=fake_fetch, now=T2 - 120)
check("a missing tx is not tried again before its 1 h wait", reads.count(PEND["txid"]) == 1)
S.refresh(fetch_tx=fake_fetch, now=T2)
rp = (db.get_blob(S.BLOB)[0] or {})["records"][PEND["txid"]]
check(f"after the wait it is tried once more, and the next wait doubles to 2 h (tries {rp['tries']})", reads.count(PEND["txid"]) == 2 and rp["tries"] == 2 and rp["next_try"] == T2 + 7200)
reads.clear()
check("G0 declaration, release and notice verified; the unread notice pending", recs[S.G0_DECL_TX]["status"] == "verified" and recs[REL["id"]]["status"] == "verified"
      and recs[NOT["id"]]["status"] == "verified" and recs[PEND["txid"]]["status"] == "pending")
calls = []; ev = S.ed25519_verify; S.ed25519_verify = lambda *a: calls.append(1) or ev(*a)
recs = (db.get_blob(S.BLOB)[0] or {})["records"]; ok3 = [t for t in (S.G0_DECL_TX, REL["id"], NOT["id"])]
before = json.dumps([recs[t] for t in ok3], sort_keys=True); S.refresh(fetch_tx=fake_fetch, now=T2 + 60)
after = (db.get_blob(S.BLOB)[0] or {})["records"]
check("an unchanged record is not checked again (no signature math, same checked_at)", not calls and json.dumps([after[t] for t in ok3], sort_keys=True) == before)
db.put_blob("notices", {"g0": FX["notices"]["g0"], "active": [dict(LST, msg=LST["msg"] + " Edited."), PEND]})
S.refresh(fetch_tx=fake_fetch, now=T2 + 600); after = (db.get_blob(S.BLOB)[0] or {})["records"]
check("a changed listing is checked again from the stored tx (no new read) and fails", len(calls) == 1 and after[NOT["id"]]["status"] == "invalid" and after[NOT["id"]]["checked_at"] == T2 + 600
      and NOT["id"] not in reads)
db.put_blob("notices", {"g0": FX["notices"]["g0"], "active": [LST, PEND]}); S.refresh(fetch_tx=fake_fetch, now=1792791200)
check("restored listing verifies again", (db.get_blob(S.BLOB)[0] or {})["records"][NOT["id"]]["status"] == "verified")
S.ed25519_verify = ev
busy = []
def busy_fetch(t): busy.append(t); raise I.Busy("HTTP 503", 60)
db.put_blob("release", {"g0": FX["release_g0"], "current": dict(RLST), "history": [RLST, {"version": "v9", "ts": 1792800000, "txid": "ab" * 32}, {"version": "v10", "ts": 1792800001, "txid": "cd" * 32}]})
S.refresh(fetch_tx=busy_fetch, now=1792792000)
check(f"a 503 stops further reads in that run ({len(busy)} read)", len(busy) == 1)
jobs = {j[0]: j for j in I.JOBS}
check("job 'signed' every 600 s on the scheduled tx read key (shared backoff)", "signed" in jobs and jobs["signed"][2] == 600 and jobs["signed"][3] == I.BG_TX_EP == "/api/explorer/tx/:id")
check("FETCH_PER_RUN is small (no new aggressive polling)", 1 <= S.FETCH_PER_RUN <= 2)

# ---------------- the feed ----------------
db.put_blob("release", {"g0": FX["release_g0"], "current": dict(RLST), "history": [RLST]})
S.refresh(fetch_tx=fake_fetch, now=1792793000)
from poascan import server as SV
d, is_list = SV.api("/api/notices/verified", {})
rows = {r["txid"]: r for r in d["records"]}; n = rows.get(NOT["id"]) or {}
check("feed: one record per notice and release, never the declaration itself", NOT["id"] in rows and REL["id"] in rows and S.G0_DECL_TX not in rows and not is_list)
need = {"kind", "id", "title", "txid", "time_utc", "time_pt", "signer", "signer_fingerprint", "status", "reason", "checked_at_utc", "checked_at_pt", "source_url"}
check("feed record fields: id, title, time UTC and PT, signer key, status, checked time, source URL", need <= set(n))
check("feed record values", n.get("id") == "2026-10-19-mainnet-live" and n.get("time_utc") == "2026-10-19T17:49:09Z" and n.get("time_pt") == "2026-10-19T10:49:09-07:00"
      and n.get("status") == "verified" and n.get("signer") == S.TRUSTED_G0 and n.get("source_url") == "https://minepoa.com/api/explorer/tx/" + NOT["id"]
      and n.get("checked_at_utc") and n.get("checked_at_pt", "").endswith("-07:00"))
check("feed: an unread notice is pending with its reason", (rows.get(PEND["txid"]) or {}).get("status") == "pending" and rows[PEND["txid"]]["reason"])
check("feed signer: key, fingerprint, source and a verified 5/5 declaration", d["signer"]["address"] == S.TRUSTED_G0 and d["signer"]["fingerprint"].startswith("SHA256:")
      and d["signer"]["declaration"]["status"] == "verified" and d["signer"]["declaration"]["countersigned"] == "5/5" and "/api/notices" in d["signer"]["key_source"]
      and d["signer"]["g0_live_matches"] is True and len(d["signer"]["public_key_hex"]) == 64)
check("feed counts and statuses", d["counts"]["verified"] >= 2 and set(d["statuses"]) == set(S.STATUSES))
txt = json.dumps(d, ensure_ascii=False)
check("feed: no em or en dash, no key-shaped value", "\u2014" not in txt and "\u2013" not in txt and not re.search(r"pk_[A-Za-z0-9]{20,}", txt))
try: SV.api("/api/notices/verified", {"x": ["1"]}); check("unknown parameter is a 400", False)
except SV.BadRequest: check("unknown parameter is a 400", True)
db.put_blob("notices", {"g0": "poa1" + "Z" * 44, "active": [LST]}); S.refresh(fetch_tx=fake_fetch, now=1792794000)
check("a different live G0 is reported, never trusted silently", SV.api("/api/notices/verified", {})[0]["signer"]["g0_live_matches"] is False)
db.put_blob("notices", {"g0": FX["notices"]["g0"], "active": [LST, PEND]}); S.refresh(fetch_tx=fake_fetch, now=1792794600)

# ---------------- severity and server overrides ----------------
check("feed: notices carry severity (action here), releases none", n.get("severity") == "action" and (rows.get(REL["id"]) or {}).get("severity") is None and "severity" in rows[REL["id"]])
OV = dict(LST, source="server-override")   # /me.system_notice can come as a server override; even with a txid it is never Signed
check("a server-override notice is unsigned (informational only), never verified, even with a real txid",
      S.verify_record("notice", NOT["id"], OV, NOT)[0] == "unsigned" and "informational only" in S.verify_record("notice", NOT["id"], OV, NOT)[1])
OV2 = {"id": "edge-override-1", "severity": "critical", "msg": "Mining paused.", "issued_ts": 1792795000, "source": "server-override"}
db.put_blob("notices", {"g0": FX["notices"]["g0"], "active": [LST, PEND, OV2]}); S.refresh(fetch_tx=fake_fetch, now=1792795000)
fo = [r for r in SV.api("/api/notices/verified", {})[0]["records"] if r["id"] == "edge-override-1"]
check("feed lists a server-override notice as unsigned, critical, informational_only, no txid", len(fo) == 1 and fo[0]["status"] == "unsigned" and fo[0]["severity"] == "critical"
      and fo[0]["informational_only"] is True and fo[0]["txid"] is None and fo[0]["notice_source"] == "server-override")
ob = S.badge(S.lookup(notice_id="edge-override-1"))
check("its badge reads Unverified with 'informational only' and a CRITICAL severity tag beside it", ">Unverified<" in ob and "informational only" in ob and 'class="sigsev critical"' in ob and ">Signed<" not in ob)
check("the verified notice's badge has its severity tag next to it", 'class="sigsev action"' in S.badge_tx(NOT["id"]))
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
check("no 36-character GUID (live key shape) in the fixture, the test or signed.py",
      not any(GUID.search(open(os.path.join(ROOT, f), encoding="utf-8").read()) for f in ("tools/signed_fixture.json", "tools/signed_test.py", "poascan/signed.py")))

# ---------------- badge and pages ----------------
b = S.badge_tx(NOT["id"])
check("Signed badge: check icon, the word Signed, fingerprint and check time in the tooltip", 'class="sigb ok"' in b and "<svg" in b and ">Signed<" in b
      and S.fingerprint(S.TRUSTED_G0) in b and "UTC" in b and "PDT" in b)
check("Unverified badge for a pending notice", ">Unverified<" in S.badge_tx(PEND["txid"]) and 'class="sigb un"' in S.badge_tx(PEND["txid"]))
check("Invalid badge", ">Invalid<" in S.badge(dict(status="invalid", reason="Ed25519 signature does not verify", checked_at=1792790000)))
check("no badge for an unknown tx", S.badge_tx("ef" * 32) == "")
db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,?)", (alt["id"], json.dumps(alt), int(time.time()), 1))
check("/tx page of a notice: Signed on the Signature row", ">Signed<" in V.tx(NOT["id"]))
check("/tx page of an altered notice (not in the feed): checked locally, Invalid", ">Invalid<" in V.tx(alt["id"]))
check("/tx page of an ordinary transfer: no badge", "sigb" not in V.tx(fixture.TX))
check("/network Recent releases: Signed next to the version", ">Signed<" in V.network_overview(""))
from poascan import milestones as MS
mev = [e for e in MS.events() if (e.get("url") or "").startswith("/tx/")]
cb = V3.charts_body("all")
check("Charts milestones that link a notice tx carry its badge", bool(mev) and cb.count('class="sigb') >= 1 and "Milestones" in cb)
ab = V.about()
sec = ab[ab.index('id="signed"'):]; sec = sec[:sec.index("<h3", 5)]
check("/about#signed: short method line with the feed link", "Ed25519" in sec and "/api/v1/notices/verified" in sec and len(re.sub("<[^>]+>", "", sec)) < 800)
check("/about credits Patches once, linked to x.com/TMCC_Patches", ab.count("TMCC_Patches") == 2 and ab.count("adapted from POA Observatory by Patches") == 1 and 'href="https://x.com/TMCC_Patches"' in ab)
srcs = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in ["CHANGELOG.md", "README.md", "poascan/views2.py", "poascan/views3.py", "poascan/agentapi.py", "poascan/ui.py", "static/app.js"]}
check("the credit is on /about only (not CHANGELOG, README, other views or the API docs)", all("TMCC_Patches" not in t for t in srcs.values()))
check("no em or en dash in signed.py strings or the about line", "\u2014" not in sec and "\u2013" not in sec and not re.search('"[^"\\n]*[\u2013\u2014][^"\\n]*"', open(os.path.join(ROOT, "poascan", "signed.py"), encoding="utf-8").read()))
css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
check("badge CSS present, cache version bumped", ".sigb{" in css and ".sigb.ok{" in css and ".sigb.bad{" in css and "style.css?v=103" in open(os.path.join(ROOT, "poascan", "ui.py")).read())

# ---------------- docs ----------------
spec = AG.openapi(); llms = AG.llms_txt()
check("OpenAPI lists /api/v1/notices/verified", "/api/v1/notices/verified" in spec["paths"])
check("llms.txt mentions the feed", "/notices/verified" in llms)
check("MCP get_verified_notices returns the feed", "get_verified_notices" in AG.TOOL_FN and AG.TOOL_FN["get_verified_notices"]({})["signer"]["address"] == S.TRUSTED_G0)
I.fetch = real_fetch
print(f"\n{len(fails)} failure(s)" if fails else "\nall passed"); sys.exit(1 if fails else 0)
