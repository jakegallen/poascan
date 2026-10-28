"""Audit fixes (1.26.199): a crawler's page view never spends the on-demand minepoa.com or fast index budget (the
archive answers it; API and MCP callers keep their reads); minepoa.com API links carry rel=nofollow; every tab of a
tabbed page is its own canonical URL (hyphenated tabs too) and /help, /wallet and the Network tabs have their own
descriptions; /api/v1/epochs pages with from and limit; /api/v1/epoch/<n>/rewards lists one close's rewards (CSV,
limit, offset, 404 for an unknown close); llms.txt has the new Agent loop, the read table, the small epochs line and
never tells anyone to put a credential in a URL; /about names the official links and no other account.
In-process server, temp database, no request leaves the box. Usage: python3 tools/audit1028_test.py"""
import json, os, sys, tempfile, threading, urllib.error, urllib.request
os.environ.setdefault("POASCAN_SEGMENTS", "1")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "a28.db"), POA_BASE="http://127.0.0.1:9", POASCAN_INDEXER="0")
import fixture; fixture.seed()
from poascan import server as SV, views as V, indexer as I, fastindex as FX, agentapi as AG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

UP = []   # every on-demand upstream read that got past the budget checks
def _fake_tx(tid, endpoint, timeout): UP.append(("tx", tid)); raise I.Busy("no upstream in tests")
def _fake_fetch(path, **k): UP.append(("fetch", path)); raise I.Busy("no upstream in tests")
I.fetch_tx = _fake_tx; I.fetch = _fake_fetch
FXQ = []
FX.URL = "http://127.0.0.1:9/x"   # enabled, never reachable: _take decides whether a read would be sent
_take0 = FX._take
def _take(kind, visitor, now=None):
    ok = _take0(kind, visitor, now); FXQ.append((kind, visitor, ok)); return ok
FX._take = _take

srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
BOT = "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)"
HUMAN = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
def get(path, ua=HUMAN):
    rq = urllib.request.Request(base + path, headers={"User-Agent": ua})
    try:
        r = urllib.request.urlopen(rq, timeout=30); return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

# ---- crawler page views read the archive only
T1, T2, T3 = "d1" * 32, "d2" * 32, "d3" * 32
A_NEW = "poa1" + "Q" * 40
UP.clear(); FXQ.clear()
st, body, _ = get("/tx/" + T1, BOT)
check(f"crawler tx page: no minepoa.com read ({UP})", not UP)
check(f"crawler tx page: no fast index lookup sent ({FXQ})", not any(ok for k, v, ok in FXQ))
check(f"crawler tx page answers ({st})", st in (200, 404, 503))
st, body, _ = get("/address/" + A_NEW, BOT)
check(f"crawler address page: no minepoa.com read ({UP})", not UP)
check(f"crawler address page: no fast index lookup sent ({FXQ})", not any(ok for k, v, ok in FXQ))
check(f"crawler address page renders ({st})", st in (200, 404))
UP.clear(); FXQ.clear()
get("/tx/" + T2, HUMAN)
check(f"a person's tx page still reads upstream ({UP})", any(k == "tx" for k, _ in UP))
UP.clear()
get("/api/v1/tx/" + T3, BOT)
check(f"an API call with a bot user agent keeps its read ({UP})", any(k == "tx" for k, _ in UP))
I.CLIENT.crawler = True
try: I.fetch_ondemand("/api/explorer/tx/" + "d4" * 32, I.TX_EP, "d4" * 32); res = "read"
except I.Limited: res = "limited"
except Exception as e: res = type(e).__name__
I.CLIENT.crawler = False
check(f"fetch_ondemand refuses a crawler with Limited ({res})", res == "limited")
check("visitor_cap:crawler is a counted deny reason", "visitor_cap:crawler" in I.DENY_REASONS)
I.CLIENT.crawler = True
check("fast index: a crawler's visitor lookup is not sent", _take0("tx", True) is False)
check("fast index: the sync's own reads still go", _take0("overview", False) is True)
I.CLIENT.crawler = False
check("fast index refusal counted as crawler", FX._refused.get("crawler", 0) >= 1)

# ---- nofollow on minepoa.com API links
src = open(os.path.join(ROOT, "poascan", "views.py")).read()
import re
links = re.findall(r'href="https://minepoa\.com/api/[^"]*"[^>]*', src)
check(f"every minepoa.com API link is nofollow ({len(links)})", links and all("nofollow" in l for l in links))

# ---- canonical and descriptions
st, body, _ = get("/governance?tab=at-risk")
check("governance at-risk tab is its own canonical", 'rel="canonical" href="https://poascan.io/governance?tab=at-risk"' in body)
st, body, _ = get("/governance")
check("governance overview canonical is the bare path", 'rel="canonical" href="https://poascan.io/governance"' in body)
st, body, _ = get("/help")
check("/help has its own description", 'name="description" content="Start earning on Proof of Agent' in body)
st, body, _ = get("/wallet")
check("/wallet has its own description", 'name="description" content="Check a Proof of Agent wallet' in body)
st, body, _ = get("/network?tab=anchors")
check("Network anchors tab has its own description", 'name="description" content="Proof of Agent anchor timeline' in body)

# ---- epochs paging and per close rewards
st, body, _ = get("/api/v1/epochs"); allr = json.loads(body)
check(f"/epochs unchanged without from or limit ({len(allr)} rows)", st == 200 and len(allr) == 12)
st, body, _ = get("/api/v1/epochs?from=5&limit=3"); pg = json.loads(body)
check(f"/epochs?from=5&limit=3 ({[r['epoch'] for r in pg]})", st == 200 and [r["epoch"] for r in pg] == [5, 6, 7])
st, body, _ = get("/api/v1/epochs?from=x")
check(f"/epochs?from=x is a 400 ({st})", st == 400)
st, body, _ = get("/api/v1/epoch/3/rewards"); rw = json.loads(body)
check(f"/epoch/3/rewards rows highest first ({[(r['rank'], r['reward']) for r in rw]})", st == 200 and [r["rank"] for r in rw] == [1, 2, 3] and rw[0]["addr"] == fixture.A1
      and set(rw[0]) >= {"rank", "epoch", "addr", "reward"})
st, body, _ = get("/api/v1/epoch/3/rewards?limit=1&offset=1"); rw2 = json.loads(body)
check("/epoch/3/rewards limit and offset", st == 200 and len(rw2) == 1 and rw2[0]["rank"] == 2)
st, body, hd = get("/api/v1/epoch/3/rewards.csv")
check("/epoch/3/rewards.csv", st == 200 and "text/csv" in hd.get("Content-Type", "") and body.splitlines()[0].startswith("rank,"))
st, body, _ = get("/api/v1/epoch/999/rewards")
check(f"/epoch/999/rewards is a 404 ({st})", st == 404)
spec = json.loads(get("/openapi.json")[1]); ek = next((k for k in spec["paths"] if k.endswith("/epochs")), None)
check(f"OpenAPI lists the rewards route and epochs from and limit ({ek})", any(k.endswith("/epoch/{n}/rewards") for k in spec["paths"])
      and ek and '"from"' in json.dumps(spec["paths"][ek]) and '"limit"' in json.dumps(spec["paths"][ek]))
st, body, _ = get("/epoch/3")
check("epoch page Payouts card links the rewards CSV", "/api/v1/epoch/3/rewards.csv" in body)

# ---- llms.txt
st, llms, _ = get("/llms.txt")
check("llms.txt: new Agent loop", "## New Agent loop" in llms and "get_earn_check" in llms)
check("llms.txt: read table", "## Which read answers what" in llms and "| /routes | get_route_status |" in llms)
check("llms.txt: small epochs line", "/epoch/<n>/rewards" in llms and "?from=<epoch>&limit=<n>" in llms)
saf = llms[llms.index("## Safety"):]; saf = saf[:saf.find("\n## ", 5) if saf.find("\n## ", 5) > 0 else len(saf)]
check("llms.txt Safety: no credential in a URL, a header instead (the join prompt text is unchanged here)", "key= is legacy" not in llms
      and not re.search(r"(?i)(token|key)=(AUTH_TOKEN|pk_|YOUR_KEY|SAVED_KEY|API_KEY)", saf) and "in a header" in saf)
check("llms.txt: no em or en dashes", "\u2014" not in llms and "\u2013" not in llms)

# ---- about
st, about, _ = get("/about")
seg = about[about.index('id="official"'):about.index("<h3>Disclosure</h3>")] if 'id="official"' in about else ""
check("about: official links", "poascan.io" in seg and "github.com/jakegallen/poascan" in seg and "POAScan account on LabLeak" in seg)
check("about: the official links line names no other account", "kinmeng" not in seg.lower() and "/u/" not in seg)

print("\n%d failed" % len(fails) if fails else "\nall passed"); sys.exit(1 if fails else 0)
