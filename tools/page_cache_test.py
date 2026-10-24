"""HTML page cache (1.26.87). Pages carry a weak ETag that ignores what app.js recomputes every second (toggle ids, countdown
text, ring and vessel fill, relative times), so two renders with the same data share it and a revalidation is a 304, while
any data change gives a new one. Cache-Control lets a browser reuse a page for 15 s and a shared cache for 30 s plus 15 s
stale-while-revalidate (45 s at most, inside the 60 s live feed cadence), with Vary: Accept-Encoding. /ops stays no-store and
private; JSON, fragments and assets keep their own headers. Test tokens are generated at runtime.
Usage: python3 tools/page_cache_test.py"""
import os, secrets, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
from poascan import server as S
CC = "public, max-age=15, s-maxage=30, stale-while-revalidate=15"
check("PAGE_CACHE: 15 s browser, 30 s shared plus 15 s stale-while-revalidate", S.PAGE_CACHE == CC)
a = (b'<b class="cd num" data-close="1792800000.0">57m 53s</b><span class="ring" data-start="1" data-close="2"><svg><circle class="rp" cx="20" cy="20" r="17" '
     b'pathLength="100" stroke-dasharray="83.92 100"/></svg></span><div class="vessel" data-start="1" data-close="2"><i class="molten" style="width:83.92%"></i>'
     b'<span class="vp num">84%</span></div><span class="xcd num" data-close="1792800000">2h 1m</span><time class="t rel" data-ts="1792800000">5s ago</time>'
     b'<button aria-controls="mp3"></button><b data-live="answers">1,234</b>')
b = (a.replace(b"57m 53s", b"57m 41s").replace(b"83.92", b"84.10").replace(b"84%", b"85%").replace(b"2h 1m", b"2h 0m").replace(b"5s ago", b"1m ago")
     .replace(b"mp3", b"mp17"))
check("ETag: the per-second parts app.js recomputes do not change it", S.page_etag(a) == S.page_etag(b) and S.page_etag(a).startswith('W/"'))
check("ETag: a data change does (count, close time, relative time anchor)", len({S.page_etag(x) for x in (a, a.replace(b"1,234", b"1,235"),
      a.replace(b'data-close="1792800000.0"', b'data-close="1792800060.0"'), a.replace(b'data-ts="1792800000"', b'data-ts="1792800001"'))}) == 4)
check("If-None-Match: weak comparison, lists and *", S.etag_match('W/"abc"', 'W/"abc"') and S.etag_match('"abc"', 'W/"abc"') and S.etag_match('"x", W/"abc"', 'W/"abc"')
      and S.etag_match("*", 'W/"abc"') and not S.etag_match('W/"abd"', 'W/"abc"') and not S.etag_match("", 'W/"abc"') and not S.etag_match(None, 'W/"abc"'))

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(base, u, h=None):
    try:
        with op.open(urllib.request.Request(base + u, None, h or {}), timeout=30) as f:
            d = {k.lower(): v for k, v in f.headers.items()}; d["vary#"] = len(f.headers.get_all("Vary") or []); return f.status, d, f.read()
    except urllib.error.HTTPError as e: return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
tmp = tempfile.mkdtemp(); port = free_port(); base = f"http://127.0.0.1:{port}"; tok = secrets.token_urlsafe(32)
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "c.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9",
           POASCAN_MAINTENANCE="0", POASCAN_STATS_TOKEN=tok)
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(150):
        try: get(base, "/healthz"); break
        except Exception: time.sleep(0.2)
    for p in ("/", "/start", "/about", "/epochs", "/agents", "/token", "/unlocks"):
        c, h, body = get(base, p, {"Accept-Encoding": "gzip"}); et = h.get("etag", "")
        c2, h2, b2 = get(base, p); c3, h3, _ = get(base, p, {"If-None-Match": et}); c4, _, _ = get(base, p, {"If-None-Match": et.removeprefix("W/")})
        c5, _, _ = get(base, p, {"If-None-Match": 'W/"0000000000000000"'})
        check(f"{p}: weak ETag, page Cache-Control, Vary once; same ETag on a second render; 304 weak and strong form; 200 on another tag ({c} {c3} {c4} {c5})",
              c == 200 and et.startswith('W/"') and h.get("cache-control") == CC and h.get("vary") == "Accept-Encoding" and h["vary#"] == 1 and h.get("content-encoding") == "gzip" and h2.get("etag") == et
              and h2.get("vary") == "Accept-Encoding" and c3 == 304 and c4 == 304 and c5 == 200 and h3.get("etag") == et and h3.get("cache-control") == CC
              and h3.get("vary") == "Accept-Encoding" and h3.get("strict-transport-security"))
    for p in ("/ops/dashboard", "/ops/internal", "/ops/visits"):
        c, h, _ = get(base, p, {"Authorization": "Bearer " + tok}); c0, h0, _ = get(base, p)
        check(f"{p}: never the page cache, with or without the token ({c} {h.get('cache-control')}; {c0} {h0.get('cache-control')})",
              "public" not in (h.get("cache-control") or "") and "public" not in (h0.get("cache-control") or "") and (c != 200 or h.get("cache-control") == "no-store")
              and not (h.get("etag") or "").startswith("W/") and not (h0.get("etag") or "").startswith("W/"))
    c, h, _ = get(base, "/api/v1/stats"); check(f"/api/v1 JSON keeps its own Cache-Control ({h.get('cache-control')})", "s-maxage" not in (h.get("cache-control") or ""))
    c, h, _ = get(base, "/healthz"); check("/healthz stays no-store", h.get("cache-control") == "no-store")
    c, h, _ = get(base, "/static/app.js?v=1"); check("versioned assets stay immutable", h.get("cache-control") == S.IMMUTABLE)
    c, h, _ = get(base, "/no-such-page-zz"); check(f"a 404 page is not cached publicly ({c})", c == 404 and "public" not in (h.get("cache-control") or ""))
finally:
    srv.terminate()
    try: srv.wait(10)
    except Exception: srv.kill()
print("\n%d failure(s)" % len(fails) if fails else "\nall ok"); sys.exit(1 if fails else 0)
