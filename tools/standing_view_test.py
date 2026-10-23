"""Per-address standing view and the at-risk list (standing.py; LabLeak 1357 c3553, c3737, c3743, c3747).
Checks: the at-risk flag (drop within the next 2 closes, same rule as the 1.26.55 estimate), pending answers with panel and
grade counts matched by the address's answer txs, marks from basis.marks, /api/v1/address/<a>/standing, /api/v1/agents/at-risk
(JSON and CSV, 400 on params), MCP get_standing and list_at_risk, OpenAPI and llms.txt, the address page rows and
the Swaps card (POAScan /swap/<id> plus POASwap's read-only per-offer status, no fee text), /agents/at-risk (sort by drop
close, names to LabLeak profiles, Standing Watch credit to EmBot-Lantern), /at-risk 301, /about#standing (the marks
observation is labelled observed, not documented, and appears only there and in tooltips), no dashes, 'Agents' wording,
and the join prompt unchanged. Then, from tools/standing_view_fixture.json (the real E0 to E11 records, reduced), every
removal at E8+ sits at last challenge_eligible + 7 and every E11 mark count equals that address's losing-side jury votes.
Usage: python3 tools/standing_view_test.py   (temp database, no network)"""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error, collections
TMP = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(TMP, "t.db")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from poascan import db, analytics as A

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)
def addr(c): return "poa1" + c * 40
NEXT, AFTER, LATER, SEATONLY, GONE, TRUST, NAMED = (addr(c) for c in "NAXSGTL")
DASH = re.compile("[\u2013\u2014]")
def tx(c): return c * 64

def close(n, ts, elig=(), after=(), removed=(), served=(), pending=None, marks=None):
    return {"epoch": n, "ts": ts, "pool": 1e9, "rewards": {}, "challenges": {}, "propagation": {},
            "basis": {"challenge_eligible": list(elig), "established_after": list(after), "established_removed": list(removed),
                      "graders_served": {a: 1 for a in served}, "pending": pending or {}, "marks": marks or {}, "settled": []}}

def seed():
    db.init(); now = time.time(); last_ts = now - 600
    db.put_blob("params", {"estab_ttl": 6, "K": 5, "grade_quorum": 4, "auto_epoch_seconds": 21600, "trusted_graders": [TRUST]})
    db.put_blob("status", {"epochs_closed": 12})
    E = [close(n, last_ts - (11 - n) * 21600) for n in range(12)]
    E[5]["basis"].update(challenge_eligible=[NEXT, NAMED, TRUST], established_after=[NEXT, NAMED, TRUST])   # L=5: drops at E12 (open close)
    E[6]["basis"].update(challenge_eligible=[AFTER], established_after=[AFTER])                            # L=6: drops at E13
    E[7]["basis"].update(challenge_eligible=[LATER], established_after=[LATER])                            # L=7: drops at E14, not at risk
    E[4]["basis"].update(challenge_eligible=[GONE], established_after=[GONE])
    E[11]["basis"]["established_removed"] = [GONE]                                                         # L=4 + 7 = 11
    E[11]["basis"]["graders_served"] = {SEATONLY: 3}
    E[3]["basis"]["marks"] = {NEXT: 1}
    E[11]["basis"]["marks"] = {NEXT: 2, GONE: 1}
    E[11]["basis"]["pending"] = {tx("a"): {"kind": "short", "panel": [], "since": 11, "grades": []},
                                 tx("b"): {"kind": "short", "panel": [AFTER, LATER], "since": 10,
                                           "grades": [{"grader": AFTER, "score": 2, "ts": 1}, {"grader": LATER, "score": 3, "ts": 2}, {"grader": LATER, "score": 3, "ts": 3}]},
                                 tx("e"): {"kind": "short", "panel": [], "since": 9, "grades": []}}   # someone else's answer
    db.put_blob("epochs", E)
    for t, ep in ((tx("a"), 11), (tx("b"), 10), (tx("c"), 12)):
        db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,epoch,ts,atts,final) VALUES(?,?,?,?,?,?,?)", (t, "challenge", NEXT, ep, int(now) - (12 - ep) * 3600, 5, 1))
    db.write("INSERT OR REPLACE INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body) VALUES(?,?,?,?,?,?,?,?)",
             (1, 1357, None, "Lantern-Test", NAMED, "2026-10-23 21:00:00", 0, ""))
    db.write("INSERT OR REPLACE INTO swaps(offer_id,maker,poa,chain,asset,want,pay_to,expires_ts,created_ts,status,taker) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
             ("f" * 64, NEXT, 10000.0, "solana", "SOL", 0.004, "So1ana", int(now) + 86400, int(now) - 600, "open", None))
    A._cache.clear()
    return E

def fixture_checks():
    F = json.load(open(os.path.join(ROOT, "tools", "standing_view_fixture.json")))["epochs"]
    last, bad, seen = {}, 0, 0
    for e in F:
        n = e["epoch"]
        for a in e["challenge_eligible"]: last[a] = n
        if n >= 8:
            for a in e["established_removed"]: seen += 1; bad += last.get(a) != n - 6 - 1
    check(f"real records: {seen} removals at E8 to E11 all at last challenge_eligible + estab_ttl 6 + 1 (L + 7)", seen == 76 and bad == 0)
    e11 = [e for e in F if e["epoch"] == 11][0]; lose = collections.Counter(a for ls in e11["settled_losers"] for a in ls)
    ok = all(lose[a] == v for a, v in e11["marks"].items())
    check(f"real records: all {len(e11['marks'])} E11 marks equal that address's losing-side jury votes (observed, not documented)", len(e11["marks"]) == 14 and ok)

def main():
    seed()
    from poascan import standing as SD
    s = SD.standing(NEXT)
    check("NEXT: established, L=5, drop E12, 1 close left, at risk", s["established"] and s["last_challenge_eligible_epoch"] == 5 and s["established_expires_epoch_est"] == 12
          and s["established_expires_closes_left"] == 1 and s["at_risk"] is True)
    check("AFTER: drop E13 (2 closes) is at risk", SD.standing(AFTER)["at_risk"] is True and SD.standing(AFTER)["established_expires_closes_left"] == 2)
    check("LATER: drop E14 (3 closes) is not at risk", SD.standing(LATER)["at_risk"] is False)
    check("at_risk null when established but unknown (seat only), false when not established (removed)", SD.standing(SEATONLY)["at_risk"] is None and SD.standing(GONE)["at_risk"] is False)
    check("trusted grader never at risk", SD.standing(TRUST)["at_risk"] is None or SD.standing(TRUST)["at_risk"] is False)
    p = s["pending"]
    check("pending: two of its answers in the E11 record, matched by its answer txs (not someone else's)", p["count"] == 2 and {x["tx"] for x in p["answers"]} == {tx("a"), tx("b")} and p["as_of_close"] == 11)
    b = [x for x in p["answers"] if x["tx"] == tx("b")][0]; a0 = [x for x in p["answers"] if x["tx"] == tx("a")][0]
    check("pending: panel size, has_panel, distinct grades (a repeat grader counts once), scores", b["panel"] == 2 and b["has_panel"] and b["grades"] == 2 and b["scores"] == [2, 3]
          and a0["panel"] == 0 and not a0["has_panel"] and a0["grades"] == 0)
    check("pending: with_panel 1, without_panel 1, grades 2, quorum 4, one answer awaiting its first close", (p["with_panel"], p["without_panel"], p["grades"], p["quorum"], p["awaiting_close"]) == (1, 1, 2, 4, 1))
    m = s["marks"]
    check("marks: 2 at the latest close (E11), 3 in total, by close E3 1 and E11 2", m["latest_close"] == 11 and m["at_latest_close"] == 2 and m["total"] == 3
          and m["by_close"] == [dict(epoch=3, marks=1), dict(epoch=11, marks=2)])
    check("marks note: observed, not documented", "observed, not documented" in m["note"] and "losing-side jury votes at E11" in m["note"])
    r = SD.at_risk()
    check(f"at-risk list: NEXT and NAMED at E12, AFTER at E13; not LATER, TRUST, SEATONLY or GONE ({[x['address'][4] for x in r['rows']]})",
          [x["address"] for x in r["rows"]] == sorted([NAMED, NEXT], key=lambda a: ("Lantern-Test" if a == NAMED else "~").lower()) + [AFTER]
          and r["by_close"] == {"12": 2, "13": 1} and r["closes"] == [12, 13] and r["count"] == 3)
    check("at-risk list agrees with established_expiry_est for every established Agent",
          all((A.established_expiry_est(a)["established_expires_closes_left"] or 99) <= 2 for a in [x["address"] for x in r["rows"]])
          and not [a for a in A.established_set() if (A.established_expiry_est(a)["established_expires_closes_left"] or 99) <= 2 and a not in {x["address"] for x in r["rows"]}])
    nm = [x for x in r["rows"] if x["address"] == NAMED][0]
    check("at-risk row: name and LabLeak profile when known, marks at the latest close", nm["name"] == "Lantern-Test" and nm["profile"] == "https://minepoa.com/lableak/#/u/" + NAMED
          and [x for x in r["rows"] if x["address"] == NEXT][0]["marks_latest"] == 2)
    check("tracker: EmBot-Lantern's Standing Watch, https, no query or referral code", SD.TRACKER == "https://embot-lantern.codeberg.page/poa-field-guide/standing/" and "?" not in SD.TRACKER and SD.TRACKER_BY == "EmBot-Lantern")
    from poascan import start as S
    check("join prompt template_sha256 unchanged (6762aa1c, v2.8)", S.template_sha256() == "6762aa1cb3bf173a20f6d25af3045b10ef4463a962754e8f1f58dc28878b5cdd")
    fixture_checks()
    sp = socket.socket(); sp.bind(("127.0.0.1", 0)); port = sp.getsockname()[1]; sp.close(); base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", SWAP_FLAG_URL="")
    srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    def get(u, data=None, h=None):
        try:
            with op.open(urllib.request.Request(base + u, data, h or {}), timeout=30) as x: return x.status, x.read().decode(), dict(x.headers)
        except urllib.error.HTTPError as e: return e.code, e.read().decode(), dict(e.headers)
    H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    def mcp(name, args):
        c, j, _ = get("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}).encode(), H)
        return json.loads(j)["result"]
    try:
        for _ in range(100):
            try: get("/healthz"); break
            except Exception: time.sleep(0.2)
        c, j, _ = get(f"/api/v1/address/{NEXT}/standing"); d = json.loads(j)
        check(f"API standing ({c}): at_risk, drop close, pending and marks, tracker link", c == 200 and d["at_risk"] is True and d["established_expires_epoch_est"] == 12
              and d["pending"]["count"] == 2 and d["marks"]["at_latest_close"] == 2 and d["links"]["tracker"] == SD.TRACKER and d["links"]["tracker_by"] == "EmBot-Lantern")
        c, j, _ = get("/api/address/poa1bad!/standing")
        check(f"API standing: a bad address is not 200 ({c})", c in (400, 404))
        c, j, _ = get("/api/v1/agents/at-risk"); d = json.loads(j)
        check(f"API at-risk ({c}): rows soonest first with counts per close", c == 200 and [x["drop_close"] for x in d["rows"]] == [12, 12, 13] and d["by_close"] == {"12": 2, "13": 1})
        c, t, h = get("/api/v1/agents/at-risk.csv")
        check(f"API at-risk CSV ({c}): header and 3 rows", c == 200 and t.splitlines()[0].startswith("address,") and "drop_close" in t.splitlines()[0] and len(t.strip().splitlines()) == 4)
        c, j, _ = get("/api/v1/agents/at-risk?range=24h")
        check(f"API at-risk: range and other parameters are a 400 ({c})", c == 400)
        sc = mcp("get_standing", {"address": NEXT}).get("structuredContent") or {}
        check("MCP get_standing: at_risk, pending, marks, url", sc.get("at_risk") is True and sc["pending"]["count"] == 2 and sc["marks"]["total"] == 3 and sc.get("url", "").endswith("#standing"))
        sc = mcp("list_at_risk", {"close": 13}).get("structuredContent") or {}
        check("MCP list_at_risk close=13: AFTER only", [x["address"] for x in sc.get("rows", [])] == [AFTER])
        c, j, _ = get("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(), H)
        tl = {t["name"]: t["description"] for t in json.loads(j)["result"]["tools"]}
        check("MCP tools/list: get_standing and list_at_risk, estimate wording, no dashes", "get_standing" in tl and "list_at_risk" in tl and "estimate" in tl["get_standing"]
              and "not an official rule" in tl["get_standing"] and not DASH.search(tl["get_standing"] + tl["list_at_risk"]))
        spec = json.loads(get("/openapi.json")[1]); llms = get("/llms.txt")[1]
        check("OpenAPI: /api/address/{address}/standing and /api/agents/at-risk", any(k.endswith("/address/{address}/standing") for k in spec["paths"]) and any(k.endswith("/agents/at-risk") for k in spec["paths"]))
        check("llms.txt: standing, at-risk, MCP tools and the tracker", "/standing" in llms and "/agents/at-risk" in llms and "get_standing" in llms and "list_at_risk" in llms and SD.TRACKER in llms)
        c, h, _ = get(f"/address/{NEXT}")
        ex = re.search(r'<div class="kv"><span>Est\. expires</span><div>(.*?)</div></div>', h, re.S)
        check(f"address page ({c}): AT RISK tag on Est. expires, links the at-risk list", c == 200 and ex is not None and ">AT RISK<" in ex.group(1) and 'href="/agents/at-risk"' in ex.group(1))
        pd = re.search(r'<div class="kv"><span>Pending</span><div>(.*?)</div></div>', h, re.S)
        check("address page: Pending row (2, 1 with panel, 2 grades)", pd is not None and pd.group(1).startswith("2 ") and "1 with panel" in pd.group(1) and "2 grades" in pd.group(1))
        mk = re.search(r'<div class="kv"><span>Marks</span><div>(.*?)</div></div>', h, re.S)
        check("address page: Marks row 2 at E11, the observation only in its tooltip", mk is not None and '<span class="num">2</span>' in mk.group(1)
              and re.search(r'title="[^"]*observed, not documented[^"]*"', mk.group(1)) is not None
              and "observed, not documented" not in re.sub(r'title="[^"]*"', "", h))
        check("address page: pending table with panel and grades columns", "Pending answer" in h and "<th>Panel</th>" in h and "<th>Grades</th>" in h)
        check("address page: Standing Watch link credited to EmBot-Lantern, at-risk and standing API links, #standing anchor",
              f'href="{SD.TRACKER}"' in h and "by EmBot-Lantern" in h and f'/api/v1/address/{NEXT}/standing' in h and 'id="standing"' in h)
        sw = re.search(r'<section class="card [^"]*" id="swaps">(.*?)</section>', h, re.S)
        check("address page: Swaps card links POAScan /swap/<id> and POASwap's per-offer status, no fee text",
              sw is not None and f'href="/swap/{"f" * 64}"' in sw.group(1) and f'href="https://poaswap.io/track?offer={"f" * 64}"' in sw.group(1) and "fee" not in sw.group(1).lower())
        c, h2, _ = get(f"/address/{LATER}")
        check("address page: no Swaps card without offers, no AT RISK when 3 closes out", c == 200 and 'id="swaps"' not in h2 and ">AT RISK<" not in h2)
        c, h, _ = get("/agents/at-risk")
        tb = re.search(r'<table class="hist cal risk">(.*?)</table>', h, re.S)
        check(f"/agents/at-risk ({c}): table with Drops at sort link, rows soonest first", c == 200 and tb is not None and 'href="/agents/at-risk?sort=-drop"' in tb.group(1)
              and [int(x) for x in re.findall(r'<span class="tag warn">E(\d+)</span>', tb.group(1))] == [12, 12, 13])
        check("/agents/at-risk: Agent names link to their LabLeak profile", f'href="https://minepoa.com/lableak/#/u/{NAMED}"' in h and ">Lantern-Test<" in h)
        check("/agents/at-risk: stat cards (watermarked .stat), no range options, no share buttons", h.count('<div class="stat">') >= 4 and "range=" not in tb.group(1) and "24h" not in tb.group(1) and "share" not in h.lower().replace("shared", ""))
        check("/agents/at-risk: Standing Watch credited by handle, CSV and API links, At risk sub-tab on", f'href="{SD.TRACKER}"' in h and "by EmBot-Lantern" in h
              and "/api/v1/agents/at-risk.csv" in h and 'class="chip on">At risk<' in h)
        c, h3, _ = get("/agents/at-risk?sort=-drop"); tb3 = re.search(r'<table class="hist cal risk">(.*?)</table>', h3, re.S)
        check("/agents/at-risk?sort=-drop: latest drop first", tb3 is not None and [int(x) for x in re.findall(r'<span class="tag warn">E(\d+)</span>', tb3.group(1))] == [13, 12, 12])
        c, _, hd = get("/at-risk")
        check(f"/at-risk is a 301 to /agents/at-risk ({c})", c == 301 and hd.get("Location", "").endswith("/agents/at-risk"))
        c, ab, _ = get("/about"); st = re.search(r'<p id="standing">(.*?)</p>', ab, re.S)
        check("/about#standing: at risk, pending, marks observed not documented, tracker credit", st is not None and "observed, not documented" in st.group(1)
              and "At risk" in st.group(1) and "EmBot-Lantern" in st.group(1) and SD.TRACKER in st.group(1))
        new = (st.group(1) if st else "") + h + (sw.group(1) if sw else "") + json.dumps(tl.get("get_standing", "")) + json.dumps(tl.get("list_at_risk", ""))
        check("new surfaces: no em or en dashes", not DASH.search(re.sub(r"<script.*?</script>", "", new, flags=re.S)))
        check("new surfaces: no Plus1 mention and no 'Accounts' wording", "plus1" not in new.lower() and not re.search(r"\bAccounts\b", re.sub(r"<[^>]+>", " ", (st.group(1) if st else "") + (tb.group(1) if tb else ""))))
    finally:
        srv.terminate()
        try: srv.wait(10)
        except Exception: srv.kill()
    print("\n%d failure(s)" % len(fails) if fails else "\nall ok"); sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
