"""extras1026: the Unverifiable tag on server-only signed releases (Protocol timeline, Release stat, /api/v1/protocol) and
per-row Sealed and Graded times on the settle queue from the last close record (page, header sort, API, Agent governance);
timestamps only, never a pending score. Temp database, no network. Usage: python3 tools/extras1026_test.py"""
import json, os, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ["POASCAN_SEGMENTS"] = "1"
os.environ.update(POASCAN_DB=os.path.join(tmp, "x.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import db
db.init()
now = int(time.time()); t0 = now - 4 * 21600
A, B, C, D, X = ("poa1" + c * 40 for c in "ABCDX")
aid = lambda i: f"{i:064x}"
h64 = lambda c: c * 64
SCORE_MARK = 2.718281828   # a pending grade score: must never appear in any output

# ---------------------------------------------------------------- (1) server-only releases
rel = lambda v, ts, txc, **kw: dict(version=v, ts=ts, txid=h64(txc), engine_sha256=kw.get("client"), client_sha256=kw.get("client"), web_client_sha256=kw.get("web"),
                                    server_sha256=kw.get("server", h64("e")), worker_sha256=h64("f"), params_sha256=h64("9"))
R = [rel("v1.0", t0 - 9000, "1", client=h64("a"), web=h64("b"), server=h64("c")),
     rel("v1.1", t0 - 8000, "2", client=h64("a"), web=h64("b"), server=h64("d")),       # server only
     rel("v1.2", t0 - 7000, "3", client=h64("7"), web=h64("b"), server=h64("d")),       # client moved
     rel("v1.3", t0 - 6000, "4", client=h64("7"), web=h64("b"), server=h64("8")),       # server only (current)
     dict(version="v1.4-nohash", ts=t0 - 5000, txid=h64("5"))]                            # names no client hash
store = dict(current=R[3], history=[R[0], R[1], R[2], R[4]])
db.put_blob("release", store)
from poascan import protocol as PT, protocolview as PV
PT._ensure(); PT.sync_releases(store, now)
db.put_blob(PT.META, dict(PT.meta(), files={"client": dict(sha=h64("7"), bytes=1, first_seen=t0), "web_client": dict(sha=h64("b"), bytes=1, first_seen=t0)}, last_ok=now, last_check=now))
so = PT.server_only_txids()
check(f"server only: v1.1, v1.3 and the release naming no client hash ({sorted(x[:1] for x in so)})", so == {h64("2"), h64("4"), h64("5")})
check("the first release and one that moves a client hash are verifiable", h64("1") not in so and h64("3") not in so)
from poascan import server as SV, agentapi as AG, governance as GV, views as V
d = SV.api("/api/protocol", {"kind": ["release"]})[0]
byv = {r["release_version"]: r for r in d["rows"]}
check("API: server_only and verifiable on release rows", byv["v1.3"]["server_only"] is True and byv["v1.3"]["verifiable"] is False and byv["v1.2"]["verifiable"] is True)
d2 = SV.api("/api/protocol", {})[0]
check("API: non release rows carry verifiable null", all(r["verifiable"] is None for r in d2["rows"] if r["kind"] != "release"))
h = GV.page({"tab": ["protocol"]})
check("Protocol tab: Unverifiable tag with its tooltip", h.count(">Unverifiable</summary>") >= 4 and PT.UNVERIFIABLE_TIP in h)
st = PV.stats_row()
check("Release stat: Unverifiable while the current release is server only", "Unverifiable" in st)
check("tooltip copy", PT.UNVERIFIABLE_TIP == "Server-only release. No public artifact to verify.")
ab = V.about()
check("/about: Unverifiable methodology", "<b>Unverifiable</b>" in ab and "server_only" in ab)

# ---------------------------------------------------------------- (2) Sealed and Graded on the settle queue
eps = [
  {"epoch": 0, "ts": t0 + 21600, "rewards": {A: "5"}, "challenges": {A: "1"},
   "basis": {"pending": {aid(3): {"since": 0, "kind": "short", "panel": [], "grades": [{"grader": B, "score": SCORE_MARK, "ts": t0 + 10}]}},
             "settled": [], "established_after": [A, B], "established_removed": [], "slashed": []}},
  {"epoch": 1, "ts": t0 + 43200, "rewards": {}, "challenges": {},
   "basis": {"pending": {aid(3): {"since": 0, "kind": "short", "panel": [],
                                  "grades": [{"grader": C, "score": SCORE_MARK, "ts": t0 + 900}, {"grader": B, "score": SCORE_MARK, "ts": t0 + 500},
                                             {"grader": B, "score": SCORE_MARK, "ts": t0 + 700}, {"grader": A, "score": SCORE_MARK, "ts": t0 + 300}]},
                         aid(4): {"since": 1, "kind": "short", "panel": []},
                         aid(5): {"since": 1, "kind": "short", "panel": [], "grades": [{"grader": D, "score": SCORE_MARK, "ts": t0 + 40000}]}},
             "settled": [], "established_after": [], "established_removed": [], "slashed": []}}]
db.put_blob("epochs", eps)
db.put_blob("params", {"K": 5, "grade_quorum": 4, "estab_ttl": 6, "auto_epoch_seconds": 21600})
db.put_blob("status", {"epochs_closed": 2, "checkpoint_height": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))})
db.put_blob("networks", {"chains": [{"chain_id": "poa-mainnet-1", "status": "live", "default": True}]})
row = lambda i, au, raw: {"id": aid(i), "author": au, "born": 1, "since": 1, "expires": 17, "kind": "short", "raw": raw, "qual": 0, "need": 4,
                          "grades": [{"g": B, "ts": now - 60, "t": 0, "q": 0}] * raw}
db.put_blob("grading", {"epoch": 2, "as_of": now, "fetched_at": now, "stats": {"pending": 4}, "rollups": [{"ts": t0 + 43200}], "established": [],
                        "rows": [row(3, D, 3), row(4, D, 0), row(5, X, 1), row(6, X, 0)], "open": [row(8, X, 0)]})
from poascan import analytics as _A; _A._cache.clear()   # earlier pages read the header status (1.26.216: it reads the close records), so drop what they cached before these blobs
from poascan import gradingview as GVW
q = {r["id"]: r for r in GVW.queue_select("", "need", "desc")}
check(f"Sealed: first seal; one time per distinct grader, earliest ({q[aid(3)].get('seal_times')})",
      q[aid(3)]["seal_times"] == [t0 + 300, t0 + 500, t0 + 900] and q[aid(3)]["sealed_ts"] == t0 + 300)
check("Graded: the latest seal in the last close record (not an earlier close)", q[aid(3)]["graded_ts"] == t0 + 900)
check("one seal: Sealed and Graded are the same", q[aid(5)]["sealed_ts"] == q[aid(5)]["graded_ts"] == t0 + 40000)
check("no grades, or not pending at the last close: blank", q[aid(4)]["sealed_ts"] is None and q[aid(6)]["graded_ts"] is None and q[aid(6)]["seal_times"] == [])
rs = [r["id"] for r in GVW.queue_select("", "sealed", "desc")]
check(f"sort by Sealed, newest first, blanks last", rs[:2] == [aid(5), aid(3)] and set(rs[2:]) == {aid(4), aid(6)})
rs = [r["id"] for r in GVW.queue_select("", "graded", "asc")]
check("sort by Graded, oldest first, blanks last", rs[:2] == [aid(3), aid(5)])
h = GV.page({"tab": ["queue"]})
check("queue page: Sealed and Graded headers sort", ">Sealed<" in h and ">Graded<" in h and "sort=sealed" in h and "sort=graded" in h)
check("queue page: times in the visitor's zone (time.lt), muted placeholder when blank", f'data-ts="{t0 + 300}" data-f="d"' in h and f'data-ts="{t0 + 300}" data-f="t"' in h and '<span class="dim">···</span>' in h)
check("queue page: footer names the close record", "Sealed and Graded: first and latest seal in the E1 close record" in h)
check("queue page: never a pending score, no em or en dash", str(SCORE_MARK) not in h and "\u2014" not in h and "\u2013" not in h)
qa = SV.api("/api/governance/queue", {"sort": ["sealed"]})[0]
check("queue API: sealed_ts, graded_ts and seal_times on rows; sort=sealed", qa["rows"][0]["id"] == aid(5) and all(k in qa["rows"][0] for k in ("sealed_ts", "graded_ts", "seal_times")))
check("queue API: never a pending score", str(SCORE_MARK) not in json.dumps(qa, default=str))
csv = SV.to_csv(qa["rows"])
check("queue CSV: sealed_ts and graded_ts columns", "sealed_ts" in csv.splitlines()[0] and "graded_ts" in csv.splitlines()[0])
ag = SV.api(f"/api/address/{D}/governance", {})[0]
pa = {r["id"]: r for r in (ag.get("grading") or {}).get("pending_answers") or []}
check(f"Agent governance (API and MCP get_agent_governance): pending rows by address carry the times ({len(pa)})", pa.get(aid(3), {}).get("sealed_ts") == t0 + 300 and pa[aid(3)]["graded_ts"] == t0 + 900)
check("Agent governance: never a pending score", str(SCORE_MARK) not in json.dumps(ag, default=str))
spec = AG.openapi()["paths"]["/api/v1/governance/queue"]["get"]
srt = [x for x in spec["parameters"] if x.get("name") == "sort"][0]["schema"]["enum"]
check(f"OpenAPI: queue sort lists sealed and graded, rows document the times", "sealed" in srt and "graded" in srt and "sealed_ts" in json.dumps(spec))
for f in ("govv2.py", "gradingview.py", "protocol.py", "protocolview.py"):
    src = open(os.path.join(ROOT, "poascan", f)).read()
    check(f"{f}: no em or en dash, says Agents not Accounts", "\u2014" not in src and "\u2013" not in src and "Accounts" not in src)
src = open(os.path.join(ROOT, "poascan", "govv2.py")).read()
check("govv2.py never reads a grade score", '"score"' not in src and "'score'" not in src)
css = open(os.path.join(ROOT, "static", "style.css")).read()
check("settle queue fits at 1280: desktop only, 4px cell padding and names capped at 16ch, scoped to table.queue",
      "@media (min-width:641px){table.queue td,table.queue th{padding-left:4px;padding-right:4px}table.queue .ag>.agn{max-width:16ch}}" in css)
print("all passed" if not fails else f"{len(fails)} failed"); sys.exit(1 if fails else 0)
