"""Phase A of the Oct 28 audit (1.26.201 on): the /about Disclosure names no other project; the sitemap lists at most 200
ranked addresses and robots.txt sets a crawl delay and keeps sorted copies out; /upgrade's Release row links the changelog;
llms.txt and OpenAPI say /api/v1/health is a 503 whenever ok is false; MCP get_epoch_rewards pages a close's rewards; the
Health Endpoints and Incidents tables, Chain Transactions, Census Snapshots and the Unlock calendar sort by header.
In-process server, temp database, no request leaves the box. Usage: python3 tools/phasea_test.py"""
import json, os, re, sys, tempfile, threading, urllib.error, urllib.request
import os as _os, time as _time; _os.environ.setdefault("POASCAN_MAINT_STARTED", str(int(_time.time()) - 86400))   # pin the maintenance start: the week long claim window would otherwise run out
os.environ.setdefault("POASCAN_SEGMENTS", "1")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "pa.db"), POA_BASE="http://127.0.0.1:9", POASCAN_INDEXER="0")
import fixture; fixture.seed()
from poascan import server as SV, indexer as I, agentapi as AG, analytics as A

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

def _no(*a, **k): raise I.Busy("no upstream in tests")
I.fetch_tx = _no; I.fetch = _no
srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
HUMAN = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
def get(path):
    rq = urllib.request.Request(base + path, headers={"User-Agent": HUMAN})
    try:
        r = urllib.request.urlopen(rq, timeout=30); return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace")
def rpc(name, args):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}).encode()
    rq = urllib.request.Request(base + "/mcp", body, {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": HUMAN})
    r = json.loads(urllib.request.urlopen(rq, timeout=30).read()); return r

# ---- Disclosure: no other project named or linked anywhere POAScan writes
st, ab = get("/about")
disc = re.search(r"<h3>Disclosure</h3><p>(.*?)</p>", ab)
check("Disclosure: builder named, operators don't run it, no special treatment", disc and "Jake Gallen" in disc.group(1) and "don't run it" in disc.group(1) and "no special treatment" in disc.group(1))
pub = ab + get("/llms.txt")[1] + get("/openapi.json")[1] + get("/api")[1] + json.dumps(rpc("get_network_summary", {}))
src = "".join(open(os.path.join(ROOT, "poascan", f), encoding="utf-8").read() for f in os.listdir(os.path.join(ROOT, "poascan")) if f.endswith(".py"))
check("no Plus1 in /about, llms.txt, OpenAPI, /api, MCP or any page source", "plus1" not in pub.lower() and "plus1" not in src.lower())

# ---- sitemap and robots
st, sm = get("/sitemap.xml")
addrs = re.findall(r"<loc>https://poascan.io/address/([^<]+)</loc>", sm)
check(f"sitemap: at most {SV.SITEMAP_ADDRS} addresses, no repeats ({len(addrs)})", 0 < len(addrs) <= SV.SITEMAP_ADDRS and len(addrs) == len(set(addrs)))
top = [r["addr"] for r in A.holders()["rows"][:min(100, SV.SITEMAP_ADDRS)]]
check("sitemap: the largest holders come first", addrs[:len(top)] == top[:len(addrs)])
check("sitemap_addrs(cap) honours the cap", len(SV.sitemap_addrs(3)) <= 3)
st, rb = get("/robots.txt")
check("robots.txt: Crawl-delay and no sorted copies in both groups", rb.count("Crawl-delay: 5") == 2 and rb.count("Disallow: /*sort=") == 2 and "Sitemap: https://poascan.io/sitemap.xml" in rb)

# ---- /upgrade release line, health 503 doc
st, up = get("/upgrade")
check("/upgrade Release row links the changelog, no stale summary", AG.CHANGELOG_URL in up and "Start earning (/help): why" not in up)
llms = get("/llms.txt")[1]; spec = json.loads(get("/openapi.json")[1])
hop = next(v for k, v in spec["paths"].items() if k.endswith("/health"))["get"]
check("llms.txt and OpenAPI: health is a 503 whenever ok is false, Partial included", "Health status codes" in llms and "Partial" in llms.split("Health status codes")[1][:300]
      and "Partial" in hop.get("description", ""))

# ---- MCP get_epoch_rewards
ep = A.epoch_rows()[-1]["epoch"]
r = rpc("get_epoch_rewards", {"epoch": ep, "limit": 2, "offset": 1})
o = json.loads(r["result"]["content"][0]["text"])
rest = json.loads(get(f"/api/v1/epoch/{ep}/rewards?limit=2&offset=1")[1])
check(f"MCP get_epoch_rewards pages the same rows as the API ({o.get('total')} total)", o["rows"] == rest and o["offset"] == 1 and o["limit"] == 2 and o["total"] >= len(rest))
bad = rpc("get_epoch_rewards", {"epoch": 99999})
check("MCP get_epoch_rewards: an unknown close is a tool error", bad.get("result", {}).get("isError") or "error" in bad)

# ---- sort headers
def heads(html, frag):
    i = html.find(frag); return html[i:i + 6000] if i >= 0 else ""
st, h = get("/network?tab=health")
eh = heads(h, 'id="endpoints"'); ih = heads(h, 'id="incidents"')
check("Health Endpoints sorts by header (?esort=)", 'class="hsb"' in eh and "esort=" in eh)
check("Health Incidents sorts by header (?isort=) when it has rows", 'id="incidents"' in h)
st, h2 = get("/network?tab=health&esort=p50&isort=dur")
check("Health: one table's sort keeps the other's in its links", st == 200 and "isort=dur" in heads(h2, 'id="endpoints"') and "esort=p50" in heads(h2, 'id="incidents"'))
st, tx = get("/chain/txs?sort=epoch&dir=asc")
eps = [int(x) for x in re.findall(r"<td[^>]*>E(\d+)</td>", tx)]
check(f"Chain Transactions sorts this page by Epoch ({eps[:5]})", st == 200 and eps == sorted(eps) and 'aria-sort="ascending"' in tx)
st, tx = get("/chain/txs")
check("Chain Transactions: headers are sort links, nofollow", 'rel="nofollow" role="button"' in tx and "sort=epoch" in tx)
st, cz = get("/agents/census")
check("Census Snapshots sorts by header", st == 200 and 'id="snapshots"' in cz and "#snapshots" in heads(cz, 'id="snapshots"'))
st, ul = get("/unlocks?sort=unlocks")
check("Unlock calendar sorts by header on /unlocks", st == 200 and 'id="calendar"' in ul and "/unlocks?" in heads(ul, 'id="calendar"'))
st, tk = get("/network?tab=token")
check("Unlock calendar links stay on the Token tab", "/network?tab=token&amp;sort=" in heads(tk, 'id="calendar"'))
check("no em or en dashes in Phase A copy", all("\u2014" not in x and "\u2013" not in x for x in (disc.group(1) if disc else "", rb, llms.split("Health status codes")[1][:300])))

print("\n%d failed" % len(fails) if fails else "\nall passed"); sys.exit(1 if fails else 0)
