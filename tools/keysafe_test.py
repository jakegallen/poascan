"""POAScan never echoes, stores, logs or forwards a PoA key: key-shaped input is refused (400) with no echo, request logs
are redacted, stored text is rendered redacted, outbound fetches refuse keys, and the security headers are present.
Test keys are built at runtime and are not real. Usage: python3 tools/keysafe_test.py"""
import json, os, random, socket, sqlite3, string, subprocess, sys, tempfile, time, urllib.request, urllib.error
from urllib.parse import quote
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
FAKE = "pk" + "_" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(32))   # never a real key
TXID = "c3" * 32

def seed(path):
    os.environ["POASCAN_DB"] = path
    import fixture; fixture.seed()
    from poascan import db
    db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,ts,atts,final) VALUES(?,?,?,?,?,?)", [(TXID, "memo", "poa1" + "C" * 40, int(time.time()) - 60, 3, 1)], many=True)

def req(base, path, data=None, ctype=None):
    r = urllib.request.Request(base + path, data=data, headers={"Content-Type": ctype} if ctype else {})
    try:
        x = urllib.request.urlopen(r, timeout=20); return x.status, dict(x.headers), x.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()

def main():
    tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "k.db"); logp = os.path.join(tmp, "server.log")
    subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {os.path.dirname(os.path.abspath(__file__))!r}); import keysafe_test as K; K.seed({dbp!r})"], cwd=ROOT, check=True)
    con = sqlite3.connect(dbp)   # legacy rows written before the scrub existed: raw insert, bypassing db.write
    con.execute("UPDATE txs SET memo=? WHERE id=?", ("hello " + FAKE + " bye", TXID))
    con.execute("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,1)", (TXID, json.dumps({"id": TXID, "final": True, "type": "memo", "body": {"memo": "hello " + FAKE + " bye"}}), int(time.time())))
    con.execute("INSERT OR REPLACE INTO forum_posts(id,community,title,author,created_at,score,comment_count,deleted,pinned,fetched,body) VALUES(990001,'general',?,'x','2026-10-21 00:00:00',1,0,0,0,0,?)", ("leak " + FAKE, "body " + FAKE))
    con.commit(); con.close()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="1")
    lf = open(logp, "w"); p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=lf, stderr=lf)
    fails = []
    def check(name, ok):
        print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
    try:
        for _ in range(100):
            try: urllib.request.urlopen(base + "/healthz", timeout=2); break
            except Exception: time.sleep(0.2)
        k = FAKE.encode()
        probes = ["/search?q=" + FAKE, "/search?q=" + quote(quote(FAKE)), "/address/" + FAKE, "/api/v1/address/" + FAKE, "/fragment/suggest?q=" + FAKE,
                  "/start?name=" + FAKE, "/api/v1/search?q=" + FAKE, "/?key=" + FAKE, "/chain/txs?api_key=abc", "/?token=abc", "/tx/" + FAKE]
        for path in probes:
            c, h, b = req(base, path)
            check(f"refused, no echo: {path.replace(FAKE, '<fake key>')} ({c})", c == 400 and k not in b and FAKE not in json.dumps(h) and "Location" not in h
                  and "no-store" in h.get("Cache-Control", "") and b"never takes keys" in b)
        c, h, b = req(base, "/api/v1/address/poa1" + "C" * 40)
        check(f"ordinary request still served ({c})", c in (200, 404))
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "poascan_search", "arguments": {"q": FAKE}}}).encode()
        c, h, b = req(base, "/mcp", body, "application/json")
        check("MCP call carrying a key is refused, no echo", k not in b and b"never takes keys" in b)
        c, h, b = req(base, "/tx/" + TXID)
        check(f"stored memo renders redacted on /tx ({c})", c == 200 and k not in b and b"pk_[redacted]" in b)
        c, h, b = req(base, "/api/v1/tx/" + TXID)
        check(f"stored memo redacted in the API ({c})", k not in b)
        for path in ("/agents/community", "/agents/builders", "/api/v1/forum", "/"):
            c, h, b = req(base, path)
            check(f"forum text redacted: {path} ({c})", k not in b)
        c, h, b = req(base, "/")
        hl = {x.lower(): v for x, v in h.items()}
        check("headers: strict CSP", "default-src 'self'" in hl.get("content-security-policy", "") and "frame-ancestors 'none'" in hl.get("content-security-policy", "")
              and "googleapis" not in hl.get("content-security-policy", ""))
        check("headers: nosniff, no-referrer, frame deny", hl.get("x-content-type-options") == "nosniff" and hl.get("referrer-policy") == "no-referrer" and hl.get("x-frame-options") == "DENY")
        check("pages load no third-party resources", b"fonts.googleapis" not in b and b"gstatic" not in b and b'name="referrer" content="no-referrer"' in b)
        check("external links carry noreferrer", b'rel="noopener"' not in req(base, "/start")[2] and b'rel="noopener"' not in b)
        c, h, _ = req(base, "/static/fonts/spacegrotesk-latin-4ecc7e.woff2")
        check(f"self-hosted font serves ({c})", c == 200 and h.get("Content-Type") == "font/woff2")
    finally:
        p.terminate(); p.wait(timeout=10); lf.close()
    log = open(logp, "rb").read()
    check("server log never holds the key or a credential value", k not in log and b"token=abc" not in log and b"api_key=abc" not in log and b"refused a request" in log)
    from poascan import keysafe as KS
    check("log redaction helper", "[redacted]" in KS.redact_log("GET /x?q=1&token=abc&key=" + FAKE) and FAKE not in KS.redact_log("GET /x?q=" + quote(FAKE)))
    import keyscan as SS
    gh = "gh" + "p_" + "A1b2" * 9
    hits = SS.scan_text("t", [(1, "x = '" + FAKE + "'"), (2, gh), (3, "https://minepoa.com/x?key=" + FAKE[3:]), (4, "key=YOUR_KEY pk_… api_key (pk_…)")])
    check("secret scan catches keys and tokens, ignores placeholders", [h.split(": ")[1] for h in hits] == ["PoA key", "GitHub token", "credential in URL"])
    check("request log holds no query strings", b"/search?" not in log and b"?q=" not in log and b"?key" not in log)
    check("placeholders survive", KS.redact("key=YOUR_KEY and pk_…") == "key=YOUR_KEY and pk_…")
    os.environ["POASCAN_DB"] = dbp
    from poascan import db, indexer
    n = KS.purge_db(db)
    con = sqlite3.connect(dbp)
    left = sum(con.execute(f"SELECT COUNT(*) FROM {t} WHERE {c} LIKE ?", ("%" + FAKE + "%",)).fetchone()[0] for t, c in (("txs", "memo"), ("tx_detail", "json"), ("forum_posts", "title"), ("forum_posts", "body")))
    con.close()
    check(f"stored keys purged from the DB ({n} rows changed, {left} left)", n >= 3 and left == 0)
    try: indexer.fetch("/api/status?key=" + FAKE); ok = False
    except Exception as e: ok = FAKE not in str(e)
    check("outbound fetch refuses a key and does not echo it", ok)
    print("\nALL OK" if not fails else f"\n{len(fails)} FAILED"); sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
