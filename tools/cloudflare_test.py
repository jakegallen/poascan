"""Safe behind Cloudflare and without it (1.26.241). The visitor's IP comes from CF-Connecting-IP only when Fly-Client-IP is
a Cloudflare edge (bundled ranges, no fetch), else from Fly-Client-IP as before; page limits use it; the live feed pings
well inside Cloudflare's 100 s idle cut; a response that names no cache policy is sent no-store, so a CDN never keeps an
error, a 429 or a refusal; /privacy says so. Run: python3 tools/cloudflare_test.py (--print: compare the bundled ranges
with Cloudflare's published lists, a network read, not part of CI)."""
import os, sys, socket, subprocess, tempfile, time, types, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import clientip as CIP, live
fails = []
def ok(c, m): print(("ok   " if c else "FAIL ") + m); c or fails.append(m)
if "--print" in sys.argv:
    import json
    r = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.cloudflare.com/client/v4/ips", headers={"User-Agent": "poascan-ranges-check"}), timeout=20).read())["result"]
    for k, have in (("ipv4_cidrs", CIP.CF_V4), ("ipv6_cidrs", CIP.CF_V6)):
        print(k, "same" if sorted(r[k]) == sorted(have) else "DIFFERENT: " + " ".join(r[k]))
    sys.exit(0)
CF4, CF6, OTHER = "172.70.1.2", "2a06:98c1::5", "203.0.113.9"
ok(CIP.is_cloudflare(CF4) and CIP.is_cloudflare(CF6) and CIP.is_cloudflare("::ffff:" + CF4), "Cloudflare edges (v4, v6, v4 mapped) are recognised")
ok(not CIP.is_cloudflare(OTHER) and not CIP.is_cloudflare("") and not CIP.is_cloudflare("nonsense") and not CIP.is_cloudflare("172.63.255.255"), "other addresses are not")
ok(len(CIP.CF_V4) == 15 and len(CIP.CF_V6) == 7, "15 v4 and 7 v6 ranges bundled")
ok(CIP.of({"Fly-Client-IP": CF4, "CF-Connecting-IP": "198.51.100.4"}) == "198.51.100.4", "through Cloudflare: the visitor from CF-Connecting-IP")
ok(CIP.of({"Fly-Client-IP": CF6, "CF-Connecting-IP": "2001:db8::1"}) == "2001:db8::1", "through a v6 edge: the v6 visitor")
ok(CIP.of({"Fly-Client-IP": OTHER, "CF-Connecting-IP": "198.51.100.4"}) == OTHER, "direct to Fly: a sent CF-Connecting-IP is ignored")
ok(CIP.of({"Fly-Client-IP": CF4, "CF-Connecting-IP": "not-an-ip"}) == CF4 and CIP.of({"Fly-Client-IP": CF4}) == CF4, "a bad or missing CF header from an edge: the edge, as before")
ok(CIP.of({"Fly-Client-IP": OTHER}) == OTHER, "without Cloudflare: Fly-Client-IP exactly as before")
ok(CIP.of({"X-Forwarded-For": "192.0.2.1, 10.0.0.1"}, "127.0.0.1") == "192.0.2.1" and CIP.of({}, "127.0.0.1") == "127.0.0.1", "local runs: the old fallback")
ok(CIP.proxied({"CF-Connecting-IP": "198.51.100.4"}) is None and CIP.proxied({"Fly-Client-IP": CF4, "CF-Connecting-IP": "198.51.100.4"}) == "198.51.100.4", "socket cap and page limit key: None without Fly-Client-IP, the visitor through Cloudflare")
ok(live.PING_EVERY < 100 and live.PING_EVERY <= 60, f"live feed pings every {live.PING_EVERY:g} s, inside Cloudflare's 100 s idle cut")
from poascan import server as S
h = types.SimpleNamespace(headers={"Fly-Client-IP": CF4, "CF-Connecting-IP": "198.51.100.7"}, client_address=("127.0.0.1", 1))
ok(S.H.client_ip(h) == "198.51.100.7", "server client_ip (limits, visitor estimate, upstream budget) uses it")

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def req(base, path, hd=None):
    try: r = urllib.request.urlopen(urllib.request.Request(base + path, headers=hd or {}), timeout=60); return r.status, r.headers
    except urllib.error.HTTPError as e: return e.code, e.headers
port = free_port(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
           POA_BASE="http://127.0.0.1:9", POASCAN_PAGE_BURST="2", POASCAN_PAGE_RATE="0.001")
env.pop("POASCAN_STATS_TOKEN", None)
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(150):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    A = "/address/poa12621aNUTb3G1qNQmjphFjHFmu7492XuWh7nQnSb8GoVo"
    va = {"Fly-Client-IP": CF4, "CF-Connecting-IP": "198.51.100.10"}; vb = {"Fly-Client-IP": CF4, "CF-Connecting-IP": "198.51.100.11"}
    a = [req(base, A, va)[0] for _ in range(3)]; b = req(base, A, vb)[0]
    ok(a[2] == 429 and b != 429, f"page limit per visitor behind one Cloudflare edge (A {a}, B {b})")
    sp = [req(base, A, {"Fly-Client-IP": OTHER, "CF-Connecting-IP": f"198.51.100.{20 + i}"})[0] for i in range(3)]
    ok(sp[2] == 429, f"a direct client cannot dodge the limit with a made up CF-Connecting-IP ({sp})")
    c, hh = req(base, A, va); ok(c == 429 and hh.get("Cache-Control") == "no-store", "a 429 is no-store")
    for path, want in (("/nope-404", "no-store"), ("/api/v1/nope", "no-store"), ("/ws", "no-store"), ("/mcp", "no-store"), ("/ops", "no-store"),
                       ("/healthz", "no-store"), ("/api/live", "no-store"), ("/api/summary", "no-store"), ("/api/v1/epochs.csv", "no-store")):
        c, hh = req(base, path); ok(hh.get("Cache-Control") == want, f"{path} {c}: Cache-Control {hh.get('Cache-Control')!r}")
    c, hh = req(base, "/privacy"); ok(c == 200 and "s-maxage=" in (hh.get("Cache-Control") or ""), "public pages keep their short shared cache")
    c, hh = req(base, "/robots.txt"); ok(hh.get("Cache-Control") == "public, max-age=3600", "static routes keep their own policy")
    pv = urllib.request.urlopen(base + "/privacy", timeout=30).read().decode()
    ok("CF-Connecting-IP" in pv and "Cloudflare's published addresses" in pv and "Hosting and delivery." in pv and "Updated 2026-10-30." in pv, "/privacy names Cloudflare and the header")
    ok("\u2013" not in pv and "\u2014" not in pv, "/privacy has no em or en dash")
finally: p.terminate(); p.wait(10)
ok(not any("\u2013" in l or "\u2014" in l for f in (__file__, CIP.__file__) for l in open(f, encoding="utf-8")), "no em or en dash")
print("\nall ok" if not fails else f"\n{len(fails)} FAILED"); sys.exit(1 if fails else 0)
