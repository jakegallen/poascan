"""Pending TTL from network params and the expiry horizon per pending cohort (1.26.186, LabLeak post 1582 Proposal L,
comment 6150). The pending and establishment TTLs come from /api/params per segment (segments.json for an archived one),
16 only as a fallback tagged Stale and Unconfirmed; the grading list cross check (Differs); cohorts by entry epoch with
count, no seal, expiry close, closes left and countdown; Watched E18 to E20 in segment 2; Queue tab card with header sort;
API, CSV, MCP get_pending_horizon, OpenAPI, llms.txt, /about#ttl; /upgrade, the epoch card tip and maint follow the param;
never a pending score. Usage: python3 tools/horizon_test.py (temp database, no network)."""
import os, sys, tempfile, time, json
os.environ.pop("POASCAN_SEGMENTS", None)
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "h.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, segments as SG, netparams as NP, horizon as HZ, governance as GV, agentapi as AG, server as SV, views as V, maint as M, bench as BN

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NOW = int(time.time()); CUR = SG.CURRENT
SCORE_MARK = 2.718281828   # a pending grade score: must never appear in any output
Z = "poa1" + "Z" * 40
check("the default segment config has segment 2 current", CUR == 2)

def pend():
    p = {}
    for i in range(5): p[f"s2-{i}"] = {"since": 2, "kind": "short", "panel": [], "grades": ([{"grader": Z, "score": SCORE_MARK, "ts": NOW - 9000}] if i == 0 else [])}
    for i in range(4): p[f"s3-{i}"] = {"since": 3, "kind": "short", "panel": []}            # no grades key: no seal
    for i in range(3): p[f"s4-{i}"] = {"since": 4, "kind": "short", "panel": [], "grades": []}
    p["s9-0"] = {"since": 9, "kind": "short", "panel": [Z], "grades": [{"grader": Z, "score": SCORE_MARK, "ts": NOW - 4000}]}
    return p

def seed(params, params_ts=None):
    db.init()
    eps = [{"epoch": n, "ts": NOW - (11 - n) * 21600 + 3600, "rewards": {}, "challenges": {},
            "basis": {"pending": pend() if n == 10 else {}, "settled": [], "established_after": [], "established_removed": [], "challenge_eligible": []}} for n in range(11)]
    db.put_blob("epochs", eps)
    db.put_blob("epochs:s1", [{"epoch": 14, "ts": SG.CUT_TS - 7200, "rewards": {}, "basis": {"pending": {"x1": {"since": 13, "kind": "short", "panel": []}}, "settled": []}}])
    db.put_blob("params", params)
    if params_ts: db.write("UPDATE blobs SET ts=? WHERE kind='params'", (params_ts,))
    db.put_blob("status", {"epochs_closed": 11, "checkpoint_height": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW))})
    db.write("INSERT OR IGNORE INTO txs(id,type,from_addr,epoch,ts,final,segment) VALUES(?,?,?,?,?,?,?)", ("open1", "challenge", Z, 11, NOW - 60, 1, CUR))
    A._cache.clear()

P = {"auto_epoch_seconds": 21600, "pending_ttl_epochs": 16, "estab_ttl": 6, "grade_quorum": 4}
seed(P)

# 1. the TTL read
t = NP.pending_ttl()
check(f"pending TTL from /api/params, confirmed, fresh ({t['source']})", t["value"] == 16 and t["source"] == "/api/params pending_ttl_epochs" and t["confirmed"] and not t["stale"] and not t["fallback"])
e = NP.estab_ttl()
check("establishment TTL from /api/params", e["value"] == 6 and e["confirmed"] and e["source"] == "/api/params estab_ttl")
s1 = NP.pending_ttl(1)
check(f"archived segment 1 reads the value it closed under from segments.json ({s1['source']})", s1["value"] == 16 and s1["confirmed"] and s1["archived"] and "segments.json" in s1["source"])

# 2. cohorts
h = HZ.horizon(); by = {r["cohort"]: r for r in h["rows"]}
check(f"cohorts by entry epoch, oldest first, plus the open epoch ({[r['cohort'] for r in h['rows']]})", [r["cohort"] for r in h["rows"]] == [2, 3, 4, 9, 11] and by[11]["source"] == "open")
check("counts and no seal (empty or missing grades list)", by[2]["pending"] == 5 and by[2]["no_seal"] == 4 and by[3]["no_seal"] == 4 and by[4]["no_seal"] == 3 and by[9]["no_seal"] == 0)
check("expires = entry epoch + 16; closes left counted to the open E11 (comment 6150: E18 is 7 left)",
      by[2]["expires_close"] == 18 and by[2]["closes_left"] == 7 and by[3]["expires_close"] == 19 and by[4]["expires_close"] == 20 and by[4]["closes_left"] == 9)
check("Watched: exactly the E18 to E20 cohorts in segment 2", [r["cohort"] for r in h["rows"] if r["watched"]] == [2, 3, 4])
lc_ts = NOW - 21600 + 3600
check("countdown time: last close plus auto_epoch_seconds per close", by[2]["expires_est_ts"] == lc_ts + 8 * 21600)
check("next expiry and total", h["next_expiry"] == 18 and h["total"] == 14)

# 3. a param change moves every horizon (Proposal L style flip, no code change)
seed(dict(P, pending_ttl_epochs=26, estab_ttl=26))
h2 = HZ.horizon(); b2 = {r["cohort"]: r for r in h2["rows"]}
check("pending_ttl_epochs 26: E2 expires E28, nothing Watched", b2[2]["expires_close"] == 28 and not any(r["watched"] for r in h2["rows"]) and h2["ttl"] == 26)
check("estab_ttl 26 is read too", NP.estab_ttl()["value"] == 26 and h2["estab_ttl"]["value"] == 26)
check("pending-by-epoch follows the param with its source", A.pending_by_epoch()["ttl_epochs"] == 26 and A.pending_by_epoch()["ttl_source"] == "/api/params pending_ttl_epochs")
rl = GV.rules()
check("Rules: lapse text follows estab_ttl (L + 27)", "L + 27" in rl and "estab_ttl is 26 in /api/params estab_ttl" in rl)
check("maint state, the epoch card tip and the /upgrade prompt follow the param",
      M._ttl() == 26 and "after 26 epochs" in BN.tip("answers") and "last 26 epochs" in NP.live_text("pending grades last 16 epochs"))

# 4. no param: fallback 16, Stale and Unconfirmed
seed({"auto_epoch_seconds": 21600})
t3 = NP.pending_ttl()
check("missing pending_ttl_epochs: 16 as fallback, flagged", t3["value"] == 16 and t3["fallback"] and t3["stale"] and not t3["confirmed"] and t3["source"] == "fallback")
check("flags: Stale and Unconfirmed", [w for w, _ in NP.flags(t3)] == ["Stale", "Unconfirmed"])
h3 = HZ.horizon(); c3 = HZ.card_html({}, GV.href)
check("horizon keeps working on the fallback and says so", h3["rows"][0]["expires_close"] == 18 and h3["ttl_fallback"] and h3["ttl_flags"] == ["Stale", "Unconfirmed"] and ">Unconfirmed<" in c3 and ">Stale<" in c3)
check("the establishment fallback (6) is flagged too", NP.estab_ttl()["value"] == 6 and NP.estab_ttl()["fallback"])

# 5. an old params copy: the value stands, tagged Stale but confirmed
seed(P, NOW - 5 * 3600)
t4 = NP.pending_ttl()
check("params read 5 h ago: value kept, Stale, still confirmed", t4["value"] == 16 and t4["stale"] and t4["confirmed"] and [w for w, _ in NP.flags(t4)] == ["Stale"])

# 6. the grading list cross check
seed(P)
rows = [{"id": f"g{i}", "since": 2, "expires": 18} for i in range(5)] + [{"id": "g9", "since": 3, "expires": 19}]
db.put_blob("grading", {"epoch": 11, "fetched_at": NOW, "as_of": NOW, "rows": rows, "open": [], "stats": {}, "established": [], "leaderboard": []})
A._cache.clear(); o = NP.observed_pending_ttl()
check("grading list expires minus since agrees: 16 on 6 rows, no Differs", o["ttl"] == 16 and o["rows"] == 6 and o["agree"] == 6 and "Differs" not in [w for w, _ in NP.flags(NP.pending_ttl(), o)])
o2 = NP.observed_pending_ttl([{"since": 2, "expires": 28}, {"since": 3, "expires": 29}])
check("a list that expires 26 after entry: Differs", [w for w, _ in NP.flags(NP.pending_ttl(), o2)] == ["Differs"])

# 7. the Queue tab card
seed(P)
q = GV.page({"tab": ["queue"]})
check("Queue tab carries the Expiry horizon card with one line per cohort", 'id="horizon"' in q and "Expiry horizon · 5" in q and q.count("<tr class=hw>") == 3)
check("terse headers, sortable, own sort keys (hsort, hdir)", all(f">{w}<" in q or f">{w}</a>" in q or f"{w}<" in q for w in ("Cohort", "Pending", "No seal", "Expires", "Left", "In")) and "hsort=pending" in q)
hs = HZ.card_html({"hsort": ["pending"]}, GV.href)
check("sort by Pending puts the largest cohort first", hs.index(">E2<") < hs.index(">E3<") < hs.index(">E4<"))
check("note cites comment 6150 and post 1582; Watched tag; countdown ticks", "comment 6150" in q and "lableak/#/post/1582" in q and ">Watched<" in q and 'class="cd num" data-close=' in q)
check("TTL line: Pending TTL 16 from /api/params, Establishment TTL 6", "Pending TTL <b class=\"num\">16</b> closes, /api/params" in q and "Establishment TTL <b class=\"num\">6</b>" in q)
check("no em or en dash, no Accounts, no score", "\u2014" not in HZ.card_html({}, GV.href) and "\u2013" not in HZ.card_html({}, GV.href) and "Accounts" not in HZ.card_html({}, GV.href) and str(SCORE_MARK) not in q)
with SG.use(1):
    A._cache.clear(); qa = GV.page({"tab": ["queue"], "segment": ["1"]}); ha = HZ.horizon()
    check("segment 1: its own cohorts and TTL from segments.json, ended, no countdown", ha["archived"] and ha["rows"][0]["cohort"] == 13 and ha["rows"][0]["expires_close"] == 29
          and ha["rows"][0]["closes_left"] is None and "segments.json" in ha["ttl_source"] and ">Ended<" in qa and not any(r["watched"] for r in ha["rows"]))
A._cache.clear()

# 8. API, CSV, MCP, OpenAPI, llms, about
d = SV.governance_api("/api/governance/pending-horizon", {})
check("API: rows, ttl with source and flags, estab_ttl, watch, rule, method", d["ttl"] == 16 and d["ttl_source"] == "/api/params pending_ttl_epochs" and d["ttl_flags"] == []
      and d["estab_ttl"]["value"] == 6 and d["watch"]["comment"] == 6150 and d["method"].endswith("/about#ttl") and len(d["rows"]) == 5)
d2 = SV.governance_api("/api/governance/pending-horizon", {"sort": ["pending"], "dir": ["asc"]})
check("API: sort and dir", [r["cohort"] for r in d2["rows"]][-1] == 2)
for bad in ({"sort": ["x"]}, {"limit": ["5"]}):
    try: SV.governance_api("/api/governance/pending-horizon", bad); ok = False
    except SV.BadRequest: ok = True
    check(f"API 400 on {bad}", ok)
cs = SV.to_csv(HZ.csv_rows(d["rows"]))
check("CSV: flat rows with the TTL and its source", cs.splitlines()[0].startswith("cohort,pending,no_seal,expires_close,closes_left") and "ttl_source" in cs.splitlines()[0] and cs.count("\n") == 6 and "{" not in cs)
src = open(os.path.join(ROOT, "poascan", "server.py")).read()
check("CSV route flattens the horizon rows", "_HZ.csv_rows(rows)" in src and '"/api/governance/pending-horizon",' in src)
r = AG.TOOL_FN["get_pending_horizon"]({})
tl = {t["name"]: t for t in AG.tools_list()}
check("MCP get_pending_horizon answers like the API", r["ttl"] == 16 and len(r["rows"]) == 5 and "get_pending_horizon" in tl and "Use it" in tl["get_pending_horizon"]["description"])
ov = SV.governance_api("/api/governance", {})
check("governance overview API carries both TTLs with provenance", ov["ttl"]["pending_ttl"]["value"] == 16 and ov["ttl"]["estab_ttl"]["value"] == 6 and ov["ttl"]["fallbacks"]["pending_ttl_epochs"] == 16)
check("OpenAPI and llms.txt", "/api/v1/governance/pending-horizon" in json.dumps(AG.openapi()) and "get_pending_horizon" in AG.llms_txt())
ab = V.about()
check("/about#ttl explains the source order, fallback and Watched", 'id="ttl"' in ab and all(w in ab for w in ("pending_ttl_epochs", "falls back to 16", "comment 6150", "Proposal L")))
check("API text: no pending score", str(SCORE_MARK) not in json.dumps(d) and "score" not in json.dumps(d["rows"]))
for f in ("netparams.py", "horizon.py"):
    s = open(os.path.join(ROOT, "poascan", f)).read()
    check(f"{f}: no em or en dash, no Accounts, never reads a score", "\u2014" not in s and "\u2013" not in s and "Accounts" not in s and '"score"' not in s)
print("all passed" if not fails else f"{len(fails)} failed"); sys.exit(1 if fails else 0)
