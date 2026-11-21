"""Live hub: the header pill opens /live, API and Network Health redirect here, nav has no Live or API tab."""
import http.client, os, sys, tempfile, time, subprocess, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import server as S, ui as UI

fails = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

check("NAV has no Live or API tab", [n for _, n in UI.NAV] == ["Chain", "Agents", "Network", "Governance", "Apps"]
      and all(h != "/live" and h != "/api" for h, _ in UI.NAV))
check("moved() no longer sends /live to Pending", S.moved("/live", {}) is None)
check("moved() /status goes to /live", S.moved("/status", {}) == "/live")
check("/live and /live?tab=feeds are in the sitemap list; /api is not",
      "/live" in S.STATIC_ROUTES and "/live?tab=feeds" in S.STATIC_ROUTES and "/api" not in S.STATIC_ROUTES)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
port = 18765
tmp = tempfile.mkdtemp(prefix="livehub-")
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "t.db"),
           POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True)
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env)
def get(u, follow=False):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request("GET", u); r = c.getresponse(); b = r.read().decode("utf-8", "replace"); h = dict(r.getheaders()); c.close()
    if follow and r.status in (301, 302) and h.get("Location"):
        return get(h["Location"], follow=False)
    return r.status, b, h
try:
    for _ in range(100):
        try: get("/healthz"); break
        except Exception: time.sleep(0.2)
    st, body, hd = get("/live")
    check("/live is 200", st == 200)
    check("/live has Last 24 min, Routes, Connect, REST and no Live nav item",
          "Last 24 min" in body and "Routes" in body and "Connect" in body and 'data-kit-tab="rest"' in body
          and '<a href="/live"' not in body[body.index('<nav class="nav" id="nav">'):body.index("</nav>")]
          and "Live</a>" not in body[body.index('<nav class="nav" id="nav">'):body.index("</nav>")])
    check("/live marks the pill current and does not put Live in the nav",
          'id="livepill"' in body and 'data-href="/live"' in body and 'class="qtip hv spill on"' in body
          and '<h1 class="sr-only">Live</h1>' in body)
    check("/live hero has chain lanes and call lanes", "Answers" in body and "Attests" in body and "Seals" in body
          and "HTTP" in body and ">Tools<" in body and "CSV" in body)
    check("/live KPIs are Height, Finalized, Lag, Submitted, Serving, Calls",
          all(x in body for x in ("Height", "Finalized", "Lag", "Submitted", "Serving", "Calls")))
    check("no em or en dash on /live", "\u2014" not in body and "\u2013" not in body)
    st, _, hd = get("/api")
    check("GET /api -> 301 /live", st == 301 and hd.get("Location") == "/live")
    st, _, hd = get("/api?tab=mcp&group=agents")
    check("GET /api keeps query on the way to /live", st == 301 and hd.get("Location") == "/live?tab=mcp&group=agents")
    st, _, hd = get("/network?tab=health")
    check("GET /network?tab=health -> 301 /live?tab=feeds", st == 301 and hd.get("Location") == "/live?tab=feeds")
    st, _, hd = get("/network?tab=health&view=details")
    check("GET health details -> 301 /live?tab=feeds&view=details", st == 301 and hd.get("Location") == "/live?tab=feeds&view=details")
    st, net, _ = get("/network")
    check("/network stays 200 as Charts", st == 200 and 'data-kit-tab="charts"' in net and 'data-kit-tab="health"' not in net)
    st, _, hd = get("/status")
    check("GET /status -> 301 /live", st == 301 and hd.get("Location") == "/live")
    st, ref, _ = get("/api/reference")
    check("/api/reference stays 200", st == 200)
    home = get("/")[1]
    check("Home strip dropped the word Live; the pill still says it",
          'id="livepill"' in home and ">Live<" in home[home.index('id="livepill"'):home.index('id="livepill"')+800]
          and '<span class="lbl on">Live</span>' not in home)
    # pending still has a home
    st, pend, _ = get("/chain?tab=pending")
    check("Pending stays on Chain", st == 200 and 'data-kit-tab="pending"' in pend)
finally:
    p.terminate(); p.wait(timeout=10)

print("\n" + ("all passed" if not fails else f"{len(fails)} failed: {fails}"))
sys.exit(1 if fails else 0)
