"""Swap HTML cutover (1.26.17, /swaps explorer since 1.26.409): /how-to-buy-poa 301 to POASwap (GET and HEAD, trailing slash, any query, www),
while every swap data route (/api/v1/swaps*, /api/swaps, /api/v1/price, price-history) stays 200 JSON here and never redirects.
/swaps is a read-only explorer view (200). Offer pages still 301 to POASwap. No /swaps#xemb link in the pages or llms.
Usage: python3 tools/swap_cutover_test.py"""
import http.client, json, os, re, socket, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "sw.db"), POASCAN_MAINTENANCE="1", POA_BASE="http://127.0.0.1:9")
sys.path.insert(0, ROOT)
from poascan import db
db.init()
fails = []
def check(n, c): print(("ok   " if c else "FAIL ") + n); c or fails.append(n)
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close()
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0"),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def raw(method, path, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request(method, path, headers={"Host": host} if host else {}); r = c.getresponse(); b = r.read(); c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, b
try:
    for _ in range(100):
        try: urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    leave = [("/how-to-buy-poa", "https://poaswap.io/about#faq"), ("/how-to-buy-poa/", "https://poaswap.io/about#faq"), ("/how-to-buy-poa?a=b", "https://poaswap.io/about#faq")]
    got = [(m, u, h, raw(m, u, h)) for m in ("GET", "HEAD") for u, _ in leave for h in (None, "www.poascan.io")]
    exp = {u: t for u, t in leave}
    bad = [(m, u, h, s, hd.get("location")) for m, u, h, (s, hd, _) in got if s != 301 or hd.get("location") != exp[u]]
    check(f"301 to POASwap for /how-to-buy-poa, GET and HEAD, trailing slash, any query, apex and www (one hop) {bad}", not bad and len(got) == 12)
    stay = [("/swaps",), ("/swaps/",), ("/swaps?pair=SOL&x=1",)]
    got = [(m, u, h, raw(m, u[0], h)) for m in ("GET", "HEAD") for u in stay for h in (None, "www.poascan.io")]
    # www hops to the apex first; apex /swaps is the explorer (200).
    bad = [(m, u, h, s, hd.get("location")) for m, u, h, (s, hd, b) in got
           if (h and (s != 301 or not (hd.get("location") or "").endswith(u))) or (not h and s != 200)]
    check(f"/swaps is the explorer (200 on apex; www hops to apex) {bad}", not bad)
    data = ["/api/v1/swaps", "/api/swaps", "/api/v1/swaps/status", "/api/swaps/status", "/api/v1/price", "/api/price", "/api/v1/swaps/price-history",
            "/api/swaps/price-history", "/api/v1/swaps?format=csv"]
    res = {u: raw("GET", u) for u in data}
    bad = [(u, s, hd.get("content-type"), hd.get("location")) for u, (s, hd, b) in res.items() if s != 200 or "location" in hd
           or not (hd.get("content-type", "").startswith("application/json") or (u.endswith("csv") and "csv" in hd.get("content-type", "")))]
    check(f"swap data routes stay 200 here, never redirect {bad}", not bad)
    check("swap JSON parses", all(json.loads(res[u][2]) is not None for u in data if not u.endswith("csv")))
    pages = {u: raw("GET", u)[2].decode() for u in ("/", "/start", "/network?tab=token", "/about", "/privacy", "/agents", "/api", "/llms.txt", "/llms-full.txt", "/sitemap.xml", "/upgrade")}
    left = {u: re.findall(r'(?:href="|https://poascan\.io)/swaps(?:#xemb)?\b[^"\s]*', h) for u, h in pages.items() if u != "/sitemap.xml"}
    left = {u: v for u, v in left.items() if v}
    check(f"no internal /swaps or /swaps#xemb link in pages or llms {left}", not left)
    check("sitemap lists /swaps; /about and /privacy say trading lives on POASwap", "poascan.io/swaps" in pages["/sitemap.xml"]
          and 'Trading lives on <a href="https://poaswap.io/" rel="noopener noreferrer">POASwap</a>' in pages["/about"]
          and 'Swaps and wallet setup are on <a href="https://poaswap.io/start" rel="noopener noreferrer">POASwap</a>' in pages["/privacy"])
    from poascan import agentapi as AG
    names = {t[0] for t in AG.TOOLS}
    check("MCP: get_swap_status stays, list_swap_offers and get_swap_offer are gone, swap url points to poaswap.io",
          "get_swap_status" in names and not names & {"list_swap_offers", "get_swap_offer"} and AG._swap_url() == "https://poaswap.io/start" and "/swaps\"" not in json.dumps(AG.TOOLS, default=str))
finally:
    p.terminate(); p.wait(10)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
