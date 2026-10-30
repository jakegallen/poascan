"""Aggregate visit counts (poascan/visits.py) and the private /ops/visits endpoint.
* No IP, user agent, hash, path or URL is ever persisted; the three tables have no column that could hold one.
* Memory stays bounded under 1M synthetic hits; the HyperLogLog estimate is within 5% at 10k and 100k visitors.
* Static, healthz, ops and other skipped requests are not counted; HEAD and errors are not counted.
* /ops/visits is the normal 404 with the token env unset, with no header, a wrong token or ?token=; 200 with the right one.
* /ops is not in the sitemap, OpenAPI, llms.txt or the MCP tool list.
Test tokens are generated at runtime. Usage: python3 tools/visits_test.py"""
import json, os, re, secrets, socket, sqlite3, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

UA_H = "Mozilla/5.0 (X11; Linux x86_64) TestBrowser/9.9.9 Gecko/20100101"
UA_B = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
IPS = ["203.0.113.%d" % i for i in range(1, 60)] + ["2001:db8::%x" % i for i in range(1, 20)]
IP_RX = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|[0-9a-f]{1,4}(?::[0-9a-f]{0,4}){2,}", re.I)
HEX_RX = re.compile(r"[0-9a-f]{12,}", re.I)

def scan(path):
    """Every value in the three visit tables: no IP, UA, hash, path or URL; only the expected columns exist."""
    con = sqlite3.connect(path); bad = []
    cols = {t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")] for t in ("visit_views", "visit_referrers", "visit_uniques")}
    check("visit table columns are day/group/kind/count only", cols == {"visit_views": ["day", "grp", "kind", "views"],
          "visit_referrers": ["day", "domain", "views"], "visit_uniques": ["day", "uniques", "segments"]})
    n = 0
    for t in cols:
        for row in con.execute(f"SELECT * FROM {t}"):
            n += 1
            for v in row:
                s = str(v)
                if isinstance(v, str) and (IP_RX.search(s) or HEX_RX.search(s) or "/" in s or "?" in s or ":" in s or "mozilla" in s.lower()
                                           or "testbrowser" in s.lower() or " " in s): bad.append((t, s))
    con.close(); return n, bad

def unit():
    tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "u.db")
    from poascan import db, visits as VS
    db.DB_PATH = os.environ["POASCAN_DB"]; db.init()
    # classification
    for p, g in [("/", "home"), ("/epoch/12", "epochs"), ("/tx/" + "a" * 64, "txs"), ("/address/poa1abc", "address"), ("/agents/top", "agents"),
                 ("/swaps", "swaps"), ("/privacy", "privacy"), ("/api", "apidocs"), ("/api/v1", "apidocs"), ("/api/v1/swaps", "api"),
                 ("/mcp", "mcp"), ("/llms-full.txt", "agentdocs"), ("/openapi.json", "agentdocs"), ("/.well-known/mcp.json", "agentdocs"), ("/zzz", "other")]:
        check(f"group {p} -> {g}", VS.group(p) == g)
    for p in ["/static/app.css", "/fragment/rows", "/og/home.png", "/ws", "/healthz", "/robots.txt", "/sitemap.xml", "/favicon.ico", "/ops/visits",
              "/ops", "/apple-touch-icon.png", "/site.webmanifest", "/BingSiteAuth.xml", "/90354056b13ed723e3724008f1e8f063.txt", "/static/swap.js"]:
        check(f"skip {p}", VS.skip(p))
    check("kinds", VS.kind("/api/x", UA_H) == "agent" and VS.kind("/", UA_B) == "bot" and VS.kind("/", "") == "bot"
          and VS.kind("/", "curl/8.0") == "bot" and VS.kind("/", UA_H) == "human" and VS.kind("/mcp", UA_H) == "agent")
    VS.BOT_NAMES = ["ClaudeBot", "ChatGPT-User"]; check("AI bot names are bots", VS.kind("/", "Mozilla/5.0 AppleWebKit ChatGPT-User/1.0") == "bot")
    check("referrer hostnames", VS.referrer("https://www.X.com:443/some/path?q=1") == "x.com" and VS.referrer("https://poascan.io/a") is None
          and VS.referrer("https://sub.poascan.io/") is None and VS.referrer("android-app://com.slack/") == "app" and VS.referrer("") is None
          and VS.referrer("https://" + "a" * 70 + ".com/") == "other" and VS.referrer("not a url") == "other")
    # HLL accuracy
    import random
    for n, seed in ((0, 0), (1, 1), (100, 2), (10000, 3), (10000, 4), (100000, 5)):
        h = VS.HLL(); rnd = random.Random(seed)
        for _ in range(n): h.add(rnd.getrandbits(64))
        e = h.estimate(); check(f"HLL estimate {e} within 5% of {n}", abs(e - n) <= max(1, 0.05 * n))
    # counting through a clock we control
    clock = [1792540800.0 + 3600]   # 2026-10-22 01:00 UTC
    c = VS.Counter(now=lambda: clock[0]); c.start()
    hit = lambda path, ua, ip, ref=None, m="GET", code=200: c.hit(m, code, path, ua, ref, lambda: ip)
    for i, ip in enumerate(IPS):
        hit(f"/address/poa1{'Z' * 30}?q=secret{i}", UA_H, ip, ref=f"https://www.example.org/p/{i}?u={ip}")
        hit("/privacy", UA_H, ip, ref="https://news.ycombinator.com/item?id=1")
        hit("/", UA_H + str(i), ip, ref=f"https://tiny{i}.example.net/")   # one-off referrers fold into 'other'
        hit("/api/v1/swaps", UA_H, ip); hit("/", UA_B, ip)
        hit("/static/app.css", UA_H, ip); hit("/healthz", UA_H, ip); hit("/ops/visits", UA_H, ip)
        hit("/", UA_H, ip, m="HEAD"); hit("/nope", UA_H, ip, code=404); hit("/search", UA_H, ip, code=302)
    hit("/mcp", "python-httpx/0.27", "198.51.100.7", m="POST")
    hit("/chain", UA_H, "198.51.100.8", code=304)
    check("flush ok", c.flush())
    day = VS.today(clock[0]); r = VS.report(day, day)["days"][0]; v = r["views"]
    n = len(IPS)
    check("views by group and kind", v["address"]["human"] == n and v["privacy"]["human"] == n and v["home"]["human"] == n and v["home"]["bot"] == n
          and v["api"]["agent"] == n and v["mcp"]["agent"] == 1 and v["epochs"]["human"] == 1)
    check("static, healthz, ops, HEAD, 404 and 302 not counted", set(v) == {"address", "privacy", "home", "api", "mcp", "epochs"})
    check(f"uniques estimate {r['uniques']} near {2 * n + 1}", abs(r["uniques"] - (2 * n + 1)) <= 5)   # IP+UA pairs: n, n with a varied UA, 1
    check("referrers: hostnames only; a domain under 3 views today is held in memory, never written by name", r["referrers"].get("example.org") == n
          and r["referrers"].get("news.ycombinator.com") == n and not any(k.startswith("tiny") for k in r["referrers"])
          and not db.q("SELECT 1 FROM visit_referrers WHERE domain LIKE 'tiny%'") and sum(v for k, v in c.refs.items() if k.startswith("tiny")) == n)
    hit("/", UA_H, IPS[0], ref="https://tiny0.example.net/"); hit("/", UA_H, IPS[1], ref="https://tiny0.example.net/"); c.flush()
    check("a domain that reaches 3 views today is written by name", db.q1("SELECT views FROM visit_referrers WHERE day=? AND domain='tiny0.example.net'", (day,)) == {"views": 3})
    hit("/", UA_H, IPS[0], ref="https://tiny0.example.net/"); c.flush()
    check("then every later view of it is written too", db.q1("SELECT views FROM visit_referrers WHERE day=? AND domain='tiny0.example.net'", (day,)) == {"views": 4})
    # day rollover: flush, fold, new salt and sketch
    salt0 = c.salt; clock[0] += 86400; hit("/", UA_H, IPS[0])
    check("new salt and empty sketch at UTC midnight", c.salt != salt0 and c.day == VS.today(clock[0]) and len(c.salt) == 32)
    raw = db.q("SELECT domain, views FROM visit_referrers WHERE day=?", (day,))
    check("finished day: referrers under 3 folded into 'other' in the table", not any(x["views"] < 3 and x["domain"] != "other" for x in raw)
          and any(x["domain"] == "other" and x["views"] == n - 1 for x in raw) and not any(x["domain"].startswith("tiny") and x["domain"] != "tiny0.example.net" for x in raw))
    m2 = VS.Counter(now=lambda: clock[0]); m2.hit("GET", 200, "/", UA_H, "https://rare.example.com/", lambda: IPS[0]); m2.flush(final=True)
    check("shutdown flush (final) writes a rare referrer as 'other', not by name", not db.q("SELECT 1 FROM visit_referrers WHERE domain='rare.example.com'"))
    db.write("INSERT INTO visit_views(day,grp,kind,views) VALUES('2020-01-01','home','human',1)"); db.write("INSERT INTO visit_uniques(day,uniques) VALUES('2020-01-01',1)")
    VS.fold_before(VS.today(clock[0]))
    check("visit_views and visit_uniques pruned after 400 days", not db.q("SELECT 1 FROM visit_views WHERE day='2020-01-01'") and not db.q("SELECT 1 FROM visit_uniques WHERE day='2020-01-01'"))
    c.flush()
    rows, bad = scan(os.environ["POASCAN_DB"])
    check(f"no IP, UA, hash, path or URL persisted ({rows} rows scanned)", rows > 0 and not bad)
    # memory: 1M synthetic human hits with distinct referrers, IPs and UAs
    m = VS.Counter(now=lambda: clock[0])
    for i in range(1000000):
        m.hit("GET", 200, "/agents" if i % 2 else "/address/poa1" + str(i), UA_H + str(i % 997), "https://site%d.example.com/" % i, lambda: "10.%d.%d.%d" % (i >> 16 & 255, i >> 8 & 255, i & 255))
    sz = m.size()
    tot = (sys.getsizeof(m.hll.r) + sys.getsizeof(m.views) + sum(sys.getsizeof(k) + sum(sys.getsizeof(x) for x in k) + 28 for k in m.views)
           + sys.getsizeof(m.refs) + sum(sys.getsizeof(k) + 28 for k in m.refs) + sys.getsizeof(m.salt))
    check(f"memory bounded after 1M hits: {sz}, about {tot // 1024} KB", sz["registers"] == 4096 and sz["views_keys"] <= len(VS.GROUPS) * 3
          and sz["referrer_keys"] <= VS.REF_CAP and tot < 64 * 1024 and m.refs.get("other", 0) > 900000)
    check(f"1M-hit estimate {m.hll.estimate()} within 5%", abs(m.hll.estimate() - 1000000) / 1000000 < 0.05)
    check("token: unset or short is refused", not VS.token_ok("Bearer x") and (os.environ.__setitem__("POASCAN_STATS_TOKEN", "short") or not VS.token_ok("Bearer short")))
    os.environ.pop("POASCAN_STATS_TOKEN", None)
    for q, ok in [({}, True), ({"from": ["2026-01-01"], "to": ["2026-10-22"]}, True), ({"from": ["2025-01-01"], "to": ["2026-10-22"]}, False),
                  ({"from": ["2026-10-23"], "to": ["2026-10-22"]}, False), ({"from": ["x"]}, False), ({"to": ["2026-02-30"]}, False)]:
        try: VS.parse_range(q, clock[0]); got = True
        except ValueError: got = False
        check(f"range {q} {'accepted' if ok else 'refused'}", got == ok)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def req(base, path, headers=None):
    r = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=20) as f: return f.status, dict(f.headers), f.read()
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read()

def serve(dbp, token):
    port = free_port(); env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
    env.pop("POASCAN_STATS_TOKEN", None)
    if token: env["POASCAN_STATS_TOKEN"] = token
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    return p, base

MPID = re.compile(rb'"mp\d+"')
def same(b1, b2): return MPID.sub(b"", b1) == MPID.sub(b"", b2)   # toggle ids count up on every render of any page

def shape(h):
    return {k: v for k, v in h.items() if k not in ("Date", "Content-Length")}   # length moves with the toggle ids

def server():
    tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "s.db"); tok = secrets.token_urlsafe(32); wrong = secrets.token_urlsafe(32)
    p, base = serve(dbp, None)
    try:
        ref = req(base, "/ops/visits"); ref_h = shape(ref[1])
        check(f"env unset: /ops/visits -> {ref[0]}", ref[0] == 404)
        c, h, b = req(base, "/ops/visits", {"Authorization": "Bearer " + tok})
        check("env unset: any token is the same 404", c == 404 and same(b, ref[2]) and shape(h) == ref_h)
    finally: p.terminate(); p.wait(10)
    p, base = serve(dbp, tok)
    try:
        H = {"User-Agent": UA_H, "Fly-Client-IP": "203.0.113.77", "Referer": "https://www.example.org/a/b?c=d"}
        for path in ["/", "/privacy", "/static/app.css", "/healthz", "/robots.txt", "/ops/visits", "/ops/visits?token=" + tok]: req(base, path, H)
        req(base, "/api/v1/swaps", {"User-Agent": "python-httpx/0.27", "Fly-Client-IP": "203.0.113.78"})
        nf = req(base, "/ops/visits"); nf_h = shape(nf[1])
        check(f"no header: /ops/visits -> {nf[0]}", nf[0] == 404)
        for name, hd, path in [("wrong token", {"Authorization": "Bearer " + wrong}, "/ops/visits"),
                               ("token without Bearer", {"Authorization": tok}, "/ops/visits"), ("Basic scheme", {"Authorization": "Basic " + tok}, "/ops/visits")]:
            c, h, b = req(base, path, hd)
            check(f"{name}: identical normal 404", c == 404 and same(b, nf[2]) and shape(h) == nf_h)
        c, _, b = req(base, "/ops/visits?token=" + tok)
        check(f"token in query never works (key guard refuses credential params: {c})", c in (400, 404) and b"days" not in b)
        c, _, pv = req(base, "/privacy"); pv = pv.decode()
        check("/privacy copy: visit counts, local storage, setup code before who sees totals, updated date; no Google Fonts", c == 200 and "Daily visit counts." in pv
              and "poascan.swap.connected" in pv and "Only POAScan's operator, on a private dashboard, next to public network totals.</p>" in pv
              and "Updated 2026-10-30." in pv and "Signup check-ins." in pv and "/j/[check-in]" in pv and "Google Fonts" not in pv and "not sold" not in pv and chr(0x2014) not in pv
              and 0 < pv.find("<h3>Setup code (optional)</h3>") < pv.find("<h3>Who sees the totals</h3>"))
        c404, _, b404 = req(base, "/no-such-page")
        check("the 404 is the normal not-found page", c404 == 404 and b"<html" in b404.lower() and b"<html" in nf[2].lower())
        c, h, b = req(base, "/ops/visits", {"Authorization": "Bearer " + tok})
        d = json.loads(b) if c == 200 else {}
        check(f"right token: 200 JSON ({c})", c == 200 and "days" in d and "from" in d and "to" in d)
        check("headers: no-store, noindex, no CORS", h.get("Cache-Control") == "no-store" and "noindex" in (h.get("X-Robots-Tag") or "")
              and not any(k.lower().startswith("access-control") for k in h))
        v = (d.get("days") or [{}])[0].get("views", {})
        check(f"counted: home, privacy (human), api (agent); not static, healthz, robots or ops: {v}",
              v.get("home", {}).get("human") == 1 and v.get("privacy", {}).get("human") == 1 and v.get("api", {}).get("agent") == 1
              and set(v) == {"home", "privacy", "api"})
        c, _, b = req(base, "/ops/visits?from=2020-01-01&to=2026-10-22", {"Authorization": "Bearer " + tok})
        check(f"over 400 days -> {c}", c == 400)
        pub = b"".join(req(base, x)[2] for x in ("/sitemap.xml", "/openapi.json", "/openapi-gpt.json", "/llms.txt", "/llms-full.txt", "/.well-known/mcp.json"))
        tl = urllib.request.urlopen(urllib.request.Request(base + "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
                                    {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}), timeout=20).read()
        check("/ops not in sitemap, OpenAPI, llms.txt or MCP", b"/ops" not in pub and b"/ops" not in tl and b"visits" not in tl)
        for q in ("?client=claude", "?client=claude&name=pjoin-secret-name", "", "?name=pjoin-secret-name", "?client=poaswap", "?client=poaswap", "?client=poaswap&name=pjoin-secret-name"): req(base, "/api/v1/prompts/join" + q)
        req(base, "/api/v1/prompts/join?client=not-a-client")                                   # 400: not counted
        urllib.request.urlopen(urllib.request.Request(base + "/api/v1/prompts/join?client=claude", method="HEAD"), timeout=20)   # HEAD: not counted
    finally: p.terminate(); p.wait(10)
    pj = dict(sqlite3.connect(dbp).execute("SELECT key, SUM(n) FROM visit_counts WHERE metric='pjoin' GROUP BY key").fetchall())
    check(f"1.26.44: /api/v1/prompts/join GETs counted by client variant, poaswap (POASwap's server fetch) on its own (no name, no 400s, no HEAD) ({pj})", pj == {"claude": 2, "none": 2, "poaswap": 3})
    raw0 = open(dbp, "rb").read() + (open(dbp + "-wal", "rb").read() if os.path.exists(dbp + "-wal") else b"")
    check("the ?name= of a prompt fetch is never stored", b"pjoin-secret-name" not in raw0)
    rows, bad = scan(dbp)
    check(f"server DB after SIGTERM flush: rows saved, none hold an IP, UA, hash or URL ({rows} rows)", rows > 0 and not bad)
    raw = open(dbp, "rb").read() + (open(dbp + "-wal", "rb").read() if os.path.exists(dbp + "-wal") else b"")
    check("raw DB bytes hold no test IP, UA or token", b"203.0.113.77" not in raw and b"TestBrowser" not in raw and tok.encode() not in raw)

def migrate():
    """1.26.44: an older visit_counts (CHECK without 'pjoin') is rebuilt by db.init(), every row kept, and then takes pjoin rows."""
    tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "m.db"); c = sqlite3.connect(dbp)
    c.executescript("CREATE TABLE visit_counts(day TEXT NOT NULL, metric TEXT NOT NULL CHECK (metric IN ('api','mcp','client','prompt','tag','device','country','edge','search','404','5xx','ms')),"
                    " key TEXT NOT NULL CHECK (length(key) <= 64), n INTEGER NOT NULL DEFAULT 0 CHECK (n >= 0), PRIMARY KEY (day, metric, key)) WITHOUT ROWID;"
                    " INSERT INTO visit_counts VALUES('2026-10-01','prompt','start.copy',4),('2026-10-01','mcp','get_onboarding_steps',2);"); c.commit(); c.close()
    r = subprocess.run([sys.executable, "-c", "import os,sys; sys.path.insert(0, os.getcwd()); os.environ['POASCAN_DB']=sys.argv[1]\nfrom poascan import db; db.DB_PATH=sys.argv[1]; db.init(); db.init()\n"
                        "db.write(\"INSERT INTO visit_counts VALUES('2026-10-02','pjoin','none',1)\")", dbp], cwd=ROOT, capture_output=True, text=True)
    c = sqlite3.connect(dbp); rows = sorted(c.execute("SELECT * FROM visit_counts").fetchall()); sql = c.execute("SELECT sql FROM sqlite_master WHERE name='visit_counts'").fetchone()[0]
    left = c.execute("SELECT count(*) FROM sqlite_master WHERE name='visit_counts_new'").fetchone()[0]
    check(f"1.26.44 migration: old visit_counts rebuilt once, rows kept, pjoin allowed ({r.returncode}, {r.stderr[-200:]})", r.returncode == 0 and "'pjoin'" in sql and "WITHOUT ROWID" in sql and left == 0
          and rows == [("2026-10-01", "mcp", "get_onboarding_steps", 2), ("2026-10-01", "prompt", "start.copy", 4), ("2026-10-02", "pjoin", "none", 1)])

if __name__ == "__main__":
    unit(); migrate(); server()
    print("FAILED: " + ", ".join(fails) if fails else "all visit checks passed")
    sys.exit(1 if fails else 0)
