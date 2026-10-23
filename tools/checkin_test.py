"""Signup check-ins (poascan/checkin.py, GET /j/...) and the private funnel (GET /ops/funnel).
* Allowlist: a known prompt version, a known client id (or none), start with no parameters, joined with exactly one addr=
  public poa1 address. Everything else is a 400 and stores nothing; pk_ and key= get the key guard's 400 first.
* Never blocks: 200 with a short line; a failed write is still a 200. Rate limited per IP (429 with Retry-After).
* Privacy: no IP, user agent, URL or query stored; server log lines show /j/[check-in] only; check-ins are not counted as
  page views. Not in the sitemap, robots, OpenAPI, llms.txt or MCP; noindex and no-store.
* Funnel: started, joined (matched to the on-chain join tx), answered and mined within 6 h, pending, resumed, unmatched,
  rates, the untagged baseline of every join; exact JSON shape; no address in the output.
* /ops/funnel: 404 without the token (same as /ops/internal), no-store, no CORS, at most 31 days, only from and to.
* No upstream request: urllib is trapped in the unit run; the server run points POA_BASE at a counter that must see zero.
Test tokens are generated at runtime. Usage: python3 tools/checkin_test.py"""
import json, os, re, secrets, socket, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

NOW = int(time.time())
def iso(t): return time.strftime("%Y-%m-%d", time.gmtime(t))
A = ["poa1" + c * 44 for c in "QRSTU"]     # valid-looking public addresses (base58 letters)
TOP = {"from", "to", "generated_ts", "since_ts", "window_s", "versions", "totals", "rows", "baseline", "definitions"}
ROWK = {"started", "probed", "probe_rate", "joined", "answered_6h", "mined_6h", "pending_6h", "resumed", "unmatched", "rate_429", "rate_429_by_route", "join_rate", "answer_rate", "mine_rate", "success_rate"}

def fixture(db, CK, now):
    H = 3600
    db.write("INSERT INTO txs(id,type,from_addr,ts) VALUES(?,?,?,?)", [
        ("j1", "join", A[0], now - 3 * H), ("c1", "challenge", A[0], now - 2 * H),            # joined, answered, still pending (6 h not over)
        ("j2", "join", A[1], now - 30 * H), ("c2", "challenge", A[1], now - 20 * H),          # joined, answer too late, mined in time
        ("j3", "join", A[2], now - 10 * 86400),                                                 # pasted again long after joining: resumed
        ("j5", "join", A[4], now - 4 * H)], many=True)                                          # untagged join: baseline only
    db.put_blob("epochs", [{"epoch": 1, "ts": now - 27 * H, "rewards": {A[1]: "12.5", A[0]: "0"}}, {"epoch": 2, "ts": now - 1 * H, "rewards": {}}])
    for cl, n in (("muse", 3), ("claude", 2), ("none", 1)):
        for _ in range(n): CK.record("v2.3", cl, "start", None, now=now - 5 * H)
    CK.record("v2.3", "muse", "joined", A[0], now=now - int(2.5 * H))
    CK.record("v2.3", "muse", "joined", A[0], now=now - 2 * H)          # a second check-in for the same address keeps the first
    CK.record("v2.3", "claude", "joined", A[1], now=now - 29 * H)
    CK.record("v2.3", "none", "joined", A[2], now=now - 1 * H)
    CK.record("v2.3", "claude", "joined", A[3], now=now - 1 * H)         # no join tx: unmatched
    for rt in ("register", "register", "mine"): CK.record("v2.3.1", "muse", "rate", rt, now=now - 1 * H)
    CK.record("v2.3.1", "none", "rate", "challenge", now=now - 1 * H)

def unit():
    tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "u.db")
    from poascan import db, checkin as CK, onboarding_prompt as OP, start as S, visits as VS
    db.DB_PATH = os.environ["POASCAN_DB"]; db.init(); CK.start(NOW - 86400)
    calls = []
    def trap(*a, **k): calls.append(1); raise AssertionError("upstream call during the funnel")
    orig = urllib.request.urlopen; urllib.request.urlopen = trap
    ok = [("/j/v2.3/start", ""), ("/j/v2.3/muse/start", ""), ("/j/v2.3/grok-bot/joined", "addr=" + A[0]), ("/j/v2.3/joined", "addr=" + A[1]), ("/j/v2.3/poaswap/start", "")]
    got = [CK.parse(p, q) for p, q in ok]
    check(f"allowlist accepts version, client or none, step and one addr ({got[2]})", got[0] == ("v2.3", "none", "start", None) and got[1][1] == "muse"
          and got[2] == ("v2.3", "grok-bot", "joined", A[0]) and got[3][1] == "none" and got[4][1] == "poaswap")
    bad = [("/j/v2.2/start", ""), ("/j/v9.9/muse/start", ""), ("/j/v2.3/evil/start", ""), ("/j/v2.3/none/start", ""), ("/j/v2.3/muse/stop", ""),
           ("/j/v2.3/muse/start", "x=1"), ("/j/v2.3/muse/start", "addr=" + A[0]), ("/j/v2.3/muse/joined", ""), ("/j/v2.3/muse/joined", "addr=poa1short"),
           ("/j/v2.3/muse/joined", "addr=" + A[0] + "&x=1"), ("/j/v2.3/muse/joined", "addr=" + A[0] + "&addr=" + A[1]), ("/j/v2.3/muse/joined", "addr=pk_abc"),
           ("/j/v2.3/muse/joined", "addr=" + A[0] + "0"), ("/j/v2.3/muse/joined", "addr=" + A[0].replace("Q", "O", 1)), ("/j/v2.3/Muse/start", ""),
           ("/j/v2.3/muse/extra/start", ""), ("/j", ""), ("/j/v2.3", ""), ("/j/v2.3/muse/joined", "addr=" + A[0] + "%0a"), ("/j/v2.3/muse/joined", "ADDR=" + A[0])]
    acc = []
    for p, q in bad:
        try: CK.parse(p, q); acc.append((p, q))
        except ValueError: pass
    check(f"allowlist refuses {len(bad)} shapes (versions, clients, steps, params, addresses) {acc}", not acc)
    check("versions: v2.3 to v2.4 still accepted (copies still in chats); the current v2.5 text carries no check-in",
          CK.VERSIONS == ("v2.3", "v2.3.1", "v2.3.2", "v2.4") and OP.VERSION == "v2.5" and OP.VERSION not in CK.VERSIONS
          and all("poascan.io/j/" not in t for t in OP.VARIANTS.values()) and OP.CHECKIN == "https://poascan.io/j/v2.4/")
    k4 = [CK.parse("/j/v2.4/start", ""), CK.parse("/j/v2.4/claude/joined", "addr=" + A[0]), CK.parse("/j/v2.4/kimi/rate", "route=answer"),
          CK.parse("/j/v2.4/kimi/probe", "w=qzxekd"), CK.parse("/j/v2.4/probe", "w=Wordy"), CK.parse("/j/v2.4/codex/start", ""), CK.parse("/j/v2.4/voice/start", "")]
    check(f"v2.4 check-ins: start, joined, rate and the new probe (word checked, never returned or kept); new registry clients codex and voice ({k4[3]})",
          k4 == [("v2.4", "none", "start", None), ("v2.4", "claude", "joined", A[0]), ("v2.4", "kimi", "rate", "answer"), ("v2.4", "kimi", "probe", None),
                 ("v2.4", "none", "probe", None), ("v2.4", "codex", "start", None), ("v2.4", "voice", "start", None)])
    pb = []
    for p_, q_ in [("/j/v2.3.2/kimi/probe", "w=abc"), ("/j/v2.3/probe", "w=abc"), ("/j/v2.4/probe", ""), ("/j/v2.4/probe", "w="), ("/j/v2.4/probe", "w=ab1"),
                   ("/j/v2.4/probe", "w=" + "a" * 17), ("/j/v2.4/probe", "w=abc&x=1"), ("/j/v2.4/probe", "w=abc&w=def"), ("/j/v2.4/probe", "W=abc"),
                   ("/j/v2.4/probe", "w=pk_abc"), ("/j/v2.4/probe", "key=abc"), ("/j/v2.4/probe", "w=ab%20c"), ("/j/v2.4/evil/probe", "w=abc"), ("/j/v2.4/muse/start", "w=abc")]:
        try: CK.parse(p_, q_); pb.append((p_, q_))
        except ValueError: pass
    check(f"probe check-in refuses older versions, missing, empty, non-letter, long, extra or repeated words, keys, unknown clients {pb}", not pb)
    k2 = [CK.parse("/j/v2.3.2/start", ""), CK.parse("/j/v2.3.2/kimi/joined", "addr=" + A[0]), CK.parse("/j/v2.3.2/muse/rate", "route=mine")]
    check(f"v2.3.2 check-ins: start, joined and rate ({k2})", k2 == [("v2.3.2", "none", "start", None), ("v2.3.2", "kimi", "joined", A[0]), ("v2.3.2", "muse", "rate", "mine")])
    rk = [CK.parse("/j/v2.3.1/rate", "route=register"), CK.parse("/j/v2.3.1/muse/rate", "route=me")] + [CK.parse("/j/v2.3.1/claude/rate", "route=" + r) for r in CK.ROUTES]
    check(f"rate check-in: v2.3.1, a client or none, one route from the allowlist ({rk[1]})", rk[0] == ("v2.3.1", "none", "rate", "register") and rk[1] == ("v2.3.1", "muse", "rate", "me")
          and [x[3] for x in rk[2:]] == list(CK.ROUTES) == ["register", "challenge", "answer", "mine", "me"])
    rb = []
    for p_, q_ in [("/j/v2.3/rate", "route=register"), ("/j/v2.3.1/rate", ""), ("/j/v2.3.1/rate", "route=grade"), ("/j/v2.3.1/rate", "route=REGISTER"), ("/j/v2.3.1/rate", "route=register&x=1"),
                   ("/j/v2.3.1/rate", "route=register&route=me"), ("/j/v2.3.1/rate", "addr=" + A[0]), ("/j/v2.3.1/rate", "route=ROUTE"), ("/j/v2.3.1/rate", "route=me%20"), ("/j/v2.3.1/evil/rate", "route=me")]:
        try: CK.parse(p_, q_); rb.append((p_, q_))
        except ValueError: pass
    check(f"rate check-in refuses v2.3, no route, unknown or cased routes, extra or other params, unknown clients {rb}", not rb)
    check("check-ins are not counted as page views", VS.skip("/j/v2.3/start") and VS.skip("/j/v2.3/muse/joined") and VS.skip("/j"))
    fixture(db, CK, NOW)
    cols = {r["name"] for t in ("checkin_counts", "checkin_addrs") for r in db.q(f"PRAGMA table_info({t})")}
    check(f"stored columns: day, version, client, step, n, addr, ts only ({sorted(cols)})", cols == {"day", "version", "client", "step", "n", "addr", "ts"})
    rc = {r["name"] for r in db.q("PRAGMA table_info(checkin_rates)")}
    check(f"rate columns: day, version, client, route, n only ({sorted(rc)})", rc == {"day", "version", "client", "route", "n"})
    first = db.q1("SELECT client, ts FROM checkin_addrs WHERE addr=?", (A[0],))
    check("first check-in per address wins", first["ts"] == NOW - int(2.5 * 3600))
    for cl, n in (("kimi", 2), ("claude", 1)):
        for _ in range(n): CK.record("v2.4", cl, "probe", None, now=NOW - 3600)
    CK.record("v2.4", "kimi", "start", None, now=NOW - 3600); CK.record("v2.4", "kimi", "start", None, now=NOW - 3600); CK.record("v2.4", "kimi", "start", None, now=NOW - 3600); CK.record("v2.4", "kimi", "start", None, now=NOW - 3600)
    t0 = time.time(); out = CK.report(iso(NOW - 3 * 86400), iso(NOW), now=NOW); ms = (time.time() - t0) * 1000
    check(f"top-level shape ({ms:.0f} ms)", set(out) == TOP and out["window_s"] == 21600 and out["versions"] == ["v2.3", "v2.3.1", "v2.3.2", "v2.4"] and set(out["totals"]) == ROWK
          and all(set(r) == ROWK | {"version", "client"} for r in out["rows"]) and out["since_ts"] == NOW - 86400)
    rows = {(r["version"], r["client"]): r for r in out["rows"]}
    check("probe: v2.4 probed per client and probe_rate = probed / started; older rows have none", rows[("v2.4", "kimi")]["probed"] == 2 and rows[("v2.4", "kimi")]["started"] == 4
          and rows[("v2.4", "kimi")]["probe_rate"] == 0.5 and rows[("v2.4", "claude")]["probed"] == 1 and rows[("v2.4", "claude")]["probe_rate"] is None
          and rows[("v2.3", "muse")]["probed"] == 0 and out["totals"]["probed"] == 3)
    mu, cl, no = rows[("v2.3", "muse")], rows[("v2.3", "claude")], rows[("v2.3", "none")]
    print("     rows", json.dumps(out["rows"]))
    check("muse: 3 started, 1 joined, answered in 6 h, not mined, pending", (mu["started"], mu["joined"], mu["answered_6h"], mu["mined_6h"], mu["pending_6h"], mu["resumed"], mu["unmatched"]) == (3, 1, 1, 0, 1, 0, 0)
          and mu["join_rate"] == 0.3333 and mu["success_rate"] == 0.3333 and mu["answer_rate"] == 1.0 and mu["mine_rate"] == 0.0)
    check("claude: 2 started, 1 joined (answer after 6 h does not count, reward close inside 6 h does), 1 unmatched", (cl["started"], cl["joined"], cl["answered_6h"], cl["mined_6h"], cl["pending_6h"], cl["unmatched"]) == (2, 1, 0, 1, 0, 1)
          and cl["success_rate"] == 0.0 and cl["join_rate"] == 0.5)
    check("none (untagged text): 1 started, a re-paste after joining long ago is resumed, not joined", (no["started"], no["joined"], no["resumed"]) == (1, 0, 1) and no["join_rate"] == 0.0)
    m1 = rows[("v2.3.1", "muse")]; n1 = rows[("v2.3.1", "none")]
    check(f"429 check-ins by version, client and route ({m1['rate_429_by_route']})", m1["rate_429"] == 3 and m1["rate_429_by_route"] == {"register": 2, "mine": 1}
          and n1["rate_429"] == 1 and n1["rate_429_by_route"] == {"challenge": 1} and n1["started"] == 0 and mu["rate_429"] == 0 and mu["rate_429_by_route"] == {}
          and out["totals"]["rate_429"] == 4 and out["totals"]["rate_429_by_route"] == {"register": 2, "mine": 1, "challenge": 1})
    tt = out["totals"]
    check(f"totals add up ({tt})", (tt["started"], tt["probed"], tt["joined"], tt["answered_6h"], tt["mined_6h"], tt["resumed"], tt["unmatched"]) == (6 + 4, 3, 2, 1, 1, 1, 1))   # + 4 v2.4 kimi starts
    bl = out["baseline"]
    check(f"baseline: every on-chain join in range, tagged share ({bl['chain_joins']}, {bl['tagged_joins']}, {bl['share_tagged']})",
          bl["chain_joins"] == sum(1 for t in (NOW - 3 * 3600, NOW - 30 * 3600, NOW - 4 * 3600) if t >= (NOW - 3 * 86400) // 86400 * 86400)
          and bl["tagged_joins"] == 2 and bl["share_tagged"] == round(2 / bl["chain_joins"], 4) and all(set(d) == {"day", "started", "chain_joins", "tagged_joins"} for d in bl["days"]))
    e = CK.report(iso(NOW - 40 * 86400), iso(NOW - 35 * 86400), now=NOW)
    check("an empty range: zeros and null rates, no rows", e["rows"] == [] and e["totals"]["started"] == 0 and e["totals"]["join_rate"] is None and e["baseline"]["share_tagged"] is None)
    s = json.dumps(out)
    check("no address, IP or user agent in the funnel", not any(a in s for a in A) and "poa1" not in s)
    check("no upstream call", not calls)
    CK.prune(NOW + 91 * 86400)
    urllib.request.urlopen = orig
    check("addresses pruned after 90 days", db.q1("SELECT COUNT(*) AS n FROM checkin_addrs")["n"] == 0 and db.q1("SELECT COUNT(*) AS n FROM checkin_counts")["n"] > 0)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def req(base, path, headers=None, method="GET"):
    r = urllib.request.Request(base + path, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as f: return f.status, dict(f.headers), f.read()
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read()

UPSTREAM = []
class Counter(BaseHTTPRequestHandler):
    def do_GET(self): UPSTREAM.append(self.path); self.send_response(503); self.end_headers()
    do_HEAD = do_POST = do_GET
    def log_message(self, *a): pass

def server():
    up = ThreadingHTTPServer(("127.0.0.1", 0), Counter); threading.Thread(target=up.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "s.db"); tok = secrets.token_urlsafe(32); wrong = secrets.token_urlsafe(32)
    port = free_port(); base = f"http://127.0.0.1:{port}"; slog = open(os.path.join(tmp, "server.log"), "w+")
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POA_BASE=f"http://127.0.0.1:{up.server_address[1]}", POASCAN_STATS_TOKEN=tok)
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=slog, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try: urllib.request.urlopen(base + "/healthz", timeout=2); break
            except Exception: time.sleep(0.2)
        IP = {"Fly-Client-IP": "198.51.100.7", "User-Agent": "CheckinTestAgent/3.1"}
        c, h, b = req(base, "/j/v2.3/muse/start", IP)
        check(f"start check-in: 200 short text, no-store, noindex ({c} {b[:40]})", c == 200 and b.decode().startswith("ok: check-in counted") and h.get("Cache-Control") == "no-store"
              and "noindex" in (h.get("X-Robots-Tag") or "") and h.get("Content-Type", "").startswith("text/plain"))
        c2, _, _ = req(base, "/j/v2.3/muse/joined?addr=" + A[0], IP); c3, _, _ = req(base, "/j/v2.3/start/", IP); c4, _, _ = req(base, "/j/v2.3/claude/start", IP, "HEAD")
        check(f"joined with a public address 200 ({c2}); trailing slash ok ({c3}); HEAD answers but is not counted ({c4})", c2 == 200 and c3 == 200 and c4 == 200)
        cr, _, _ = req(base, "/j/v2.3.1/muse/rate?route=register", IP)
        check(f"rate check-in with an allowed route: 200 ({cr})", cr == 200)
        c32 = [req(base, u, dict(IP, **{"Fly-Client-IP": f"198.51.108.{i}"}))[0] for i, u in enumerate(("/j/v2.3.2/kimi/start", "/j/v2.3.2/kimi/joined?addr=" + A[4], "/j/v2.3.2/kimi/rate?route=me"))]
        check(f"v2.3.2 start, joined and rate check-ins: 200 {c32}", c32 == [200] * 3)
        c24 = [req(base, u, dict(IP, **{"Fly-Client-IP": f"198.51.109.{i}"}))[0] for i, u in enumerate(("/j/v2.4/claude/start", "/j/v2.4/claude/probe?w=qzxekd", "/j/v2.4/claude/joined?addr=" + A[3], "/j/v2.4/claude/rate?route=register", "/j/v2.4/probe?w=Abc"))]
        check(f"v2.4 start, probe, joined and rate check-ins: 200 {c24}", c24 == [200] * 5)
        bp = [req(base, u, dict(IP, **{"Fly-Client-IP": f"198.51.110.{i}"}))[0] for i, u in enumerate(("/j/v2.4/claude/probe?w=pk_" + "d" * 30, "/j/v2.4/claude/probe?w=abc&key=x", "/j/v2.4/claude/probe?key=" + "e" * 30, "/j/v2.4/claude/probe", "/j/v2.3.2/claude/probe?w=abc", "/j/v2.4/claude/probe?w=abc&utm=1"))]
        check(f"v2.4 probe with a key, key=, no word, an older version or an extra param: all 400 {bp}", bp == [400] * 6)
        badp = ["/j/v2.3.1/muse/rate?route=pk_" + "c" * 30, "/j/v2.3.1/muse/rate?route=register&key=x", "/j/v2.3.1/muse/rate?route=grade", "/j/v2.3/muse/rate?route=me", "/j/v2.3/muse/joined?addr=pk_" + "a" * 30, "/j/v2.3/muse/start?key=abc", "/j/v2.3/pk_" + "b" * 30 + "/start", "/j/v2.3/muse/joined?addr=" + A[0] + "&key=x",
                "/j/v2.3/muse/joined?addr=" + A[0] + "&token=x", "/j/v2.3/evil/start", "/j/v2.2/start", "/j/v2.3/muse/start?ref=x", "/j/v2.3/muse/joined?addr=nope",
                "/j/v2.3/muse/joined?addr=" + A[1] + "&utm=1", "/j", "/j/whatever", "/j/v2.3/muse/joined?addr=" + A[2] + "%26key%3Dx"]
        codes = [req(base, u, dict(IP, **{"Fly-Client-IP": f"198.51.104.{i}"}))[0] for i, u in enumerate(badp)]
        check(f"pk_, key=, token=, unknown version or client, extra or bad params: all 400 {codes}", codes == [400] * len(badp))
        rl = [req(base, "/j/v2.3/grok/start", {"Fly-Client-IP": "198.51.105.1"})[0] for _ in range(16)]
        c, h, _ = req(base, "/j/v2.3/grok/start", {"Fly-Client-IP": "198.51.105.1"})
        check(f"rate limited per IP ({rl.count(429)} of 16 got 429), Retry-After", rl[:12] == [200] * 12 and 429 in rl and c == 429 and h.get("Retry-After"))
        nf = req(base, "/ops/funnel"); nw = req(base, "/ops/funnel", {"Authorization": "Bearer " + wrong})
        check(f"/ops/funnel: 404 without the token or with a wrong one ({nf[0]}, {nw[0]})", nf[0] == 404 and nw[0] == 404 and b"<html" in nf[2].lower() and b'"rows"' not in nf[2] and re.sub(rb'"mp\d+"', b"", nf[2]) == re.sub(rb'"mp\d+"', b"", nw[2]))
        H = {"Authorization": "Bearer " + tok, "Fly-Client-IP": "198.51.106.1"}
        c, h, b = req(base, f"/ops/funnel?from={iso(NOW - 86400)}&to={iso(NOW)}", H); d = json.loads(b) if c == 200 else {}
        print("     funnel", json.dumps(d.get("rows")), json.dumps(d.get("totals")))
        rows = {(r["version"], r["client"]): r for r in d.get("rows", [])}
        check("/ops/funnel with the token: 200, exact shape, no-store, noindex, no CORS", c == 200 and set(d) == TOP and h.get("Cache-Control") == "no-store"
              and "noindex" in (h.get("X-Robots-Tag") or "") and not any(k.lower().startswith("access-control") for k in h))
        check("funnel counts what the server accepted: muse 1 and none 1 started (start/ is untagged), grok 12, claude HEAD not counted, nothing from the 400s",
              rows.get(("v2.3", "muse"), {}).get("started") == 1 and rows.get(("v2.3", "none"), {}).get("started") == 1 and rows.get(("v2.3", "grok"), {}).get("started") == 12
              and ("v2.3", "claude") not in rows and ("v2.3", "evil") not in rows and rows[("v2.3", "muse")]["unmatched"] == 1
              and rows.get(("v2.3.1", "muse"), {}).get("rate_429_by_route") == {"register": 1})
        check("no IP, UA or address in the funnel", b"198.51" not in b and b"CheckinTestAgent" not in b and b"poa1" not in b)
        codes = [req(base, "/ops/funnel?" + q, dict(H, **{"Fly-Client-IP": f"198.51.107.{i}"}))[0] for i, q in enumerate(
            ("from=" + iso(NOW - 31 * 86400) + "&to=" + iso(NOW), "from=x", "x=1", "token=" + tok))]
        check(f"/ops/funnel: 32 days, a bad date, another parameter, a token in the URL: 400 {codes}", codes == [400] * 4)
        pub = b"".join(req(base, x)[2] for x in ("/", "/sitemap.xml", "/openapi.json", "/llms.txt", "/llms-full.txt", "/robots.txt", "/api"))
        check("/ops/funnel and /j/ are not in the home page, sitemap, OpenAPI, llms.txt, robots or /api", b"ops/funnel" not in pub and b"poascan.io/j/" not in pub.replace(b"https://poascan.io/j/v2.4/start once now", b"").replace(b"https://poascan.io/j/v2.4/probe?w=W", b"").replace(b"https://poascan.io/j/v2.4/joined?addr=", b"").replace(b"https://poascan.io/j/v2.4/rate?route=", b"")
              and b"/j/" not in req(base, "/robots.txt")[2] and b"/j/" not in req(base, "/sitemap.xml")[2])
        time.sleep(0.5); slog.flush(); slog.seek(0); lg = slog.read()
        check("server log: check-ins as /j/[check-in] only; never the client, address, key or query", "/j/[check-in]" in lg and "/j/v2.3" not in lg and "muse" not in lg and "route=" not in lg
              and A[0] not in lg and "addr=" not in lg and "pk_aaaa" not in lg and "198.51" not in lg and "CheckinTestAgent" not in lg)
        import sqlite3
        cx = sqlite3.connect(dbp); dump = "\n".join(cx.iterdump()); cx.close()
        check("database: no IP, user agent, key or query in any table", "198.51" not in dump and "CheckinTestAgent" not in dump and "pk_aaaa" not in dump and "addr=" not in dump
              and "evil" not in dump)
    finally:
        p.terminate(); p.wait(10)
    up.shutdown()
    check(f"no request reached the upstream ({len(UPSTREAM)})", not UPSTREAM)

if __name__ == "__main__":
    unit(); server()
    print("FAILED: " + ", ".join(fails) if fails else "all check-in checks passed")
    sys.exit(1 if fails else 0)
