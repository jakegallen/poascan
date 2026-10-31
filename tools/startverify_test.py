"""/start verification strip (startv2.py + static/startv2.js): the sv-vf strip renders three honest badges
(Prompt copied, Network open, Answer verified) plus an optional "Check my Agent" poa1 input. The strip reads only
POAScan's own /api/v1 routes, never minepoa and never a key; the input validates against the server's own address shape
and the server 400s a bad address. Light on purpose: no MCP, no Playwright, no full suite.
Usage: python3 tools/startverify_test.py"""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "sv.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
os.environ.pop("POASCAN_MAINTENANCE", None)   # maintenance off: the strip renders on a live card
sys.path.insert(0, ROOT)
fails = []
def check(n, c): print(("ok   " if c else "FAIL ") + n); c or fails.append(n)

js = open(os.path.join(ROOT, "static", "startv2.js"), encoding="utf-8").read()

# ---- the JS wiring (static, no server needed)
check("startv2.js: copied() and vf() defined; badge 1 lit at the three copy sites, not the connector URL copy",
      'function copied(){vf("copied",true)}' in js and "function vf(k,v)" in js
      and js.count('vf("copied",true)') >= 3 and "copied()" in js)
check("startv2.js: badge 2 reads /api/v1/routes for hosted_mining open and not stale, polls on an interval; badge 3 reads the challenge tx count; no await, no minepoa, no external fetch",
      "/api/v1/routes" in js and 'x.id=="hosted_mining"' in js and 'row.state=="open"&&!row.stale' in js
      and '/api/v1/address/"+encodeURIComponent(a)+"/txs?type=challenge&limit=1' in js and "d.types.challenge" in js
      and "await" not in js and "minepoa.com/api" not in js and not re.search(r'fetch\("https?://', js))
check("startv2.js: the Agent input validates against the server's own poa1 shape, rejecting key-shaped input; no dashes",
      "/^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$/" in js and 'data-sv-vf-addr' in js and not any(c in js for c in "—–"))

# ---- the rendered strip (needs the body only, no server)
from poascan import startv2 as SV
h = SV.body()
for lab in ("Prompt copied", "Network open", "Answer verified"):
    check(f"strip: badge label present once: {lab}", h.count(">" + lab + "<") == 1)
check("strip: one sv-vf group, aria-live polite, three sv-vf-b badges, the Check my Agent input, inside sv-card before foot",
      h.count('class="sv-vf"') == 1 and 'data-sv-vf' in h and 'aria-live="polite"' in h and h.count('class="sv-vf-b"') == 3
      and 'data-sv-vf-b="copied"' in h and 'data-sv-vf-b="network"' in h and 'data-sv-vf-b="answer"' in h
      and 'data-sv-vf-addr' in h and ">Check my Agent<" in h
      and h.index('class="sv-vf"') < h.index('data-sv-foot') and h.index('class="sv-card"') < h.index('class="sv-vf"'))
check("strip: honest and consistent copy: Agents not Accounts, no em or en dash, never a key field",
      "Accounts" not in h and not any(c in h for c in "—–") and 'type="password"' not in h and "never a key" in h)
reg = h[h.index('class="sv-vf"'):h.index('data-sv-foot')]
check("strip: the sv-vf region reuses none of the classes the other tests count (sv-t , sv-o, sv-live, sv-b sv-bc, sv-b sv-bp, sv-other)",
      not any(x in reg for x in ('class="sv-t ', 'class="sv-o"', 'class="sv-live"', 'sv-b sv-bc', 'sv-b sv-bp', 'class="sv-other"')))

# ---- the server: a bad poa1 400s on the txs route the strip polls; a well-shaped one is accepted
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close(); base = f"http://127.0.0.1:{port}"
slog = open(os.path.join(tmp, "server.log"), "w+")
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT,
                     env=dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0"), stdout=slog, stderr=subprocess.STDOUT)
def req(u):
    try: r = urllib.request.urlopen(urllib.request.Request(base + u), timeout=30); return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    cb, _ = req("/api/v1/address/poa1badkeyshaped/txs?type=challenge&limit=1")
    check(f"server: a bad poa1 address 400s on the txs route the strip polls (key-shaped input never reaches a read) {cb}", cb == 400)
    good = "poa1" + "q" * 38
    cg, bg = req("/api/v1/address/" + good + "/txs?type=challenge&limit=1")
    check(f"server: a well-shaped poa1 is accepted and the response carries the challenge count the badge reads {cg}",
          cg == 200 and "types" in json.loads(bg))
    cr, br = req("/api/v1/routes")
    check(f"server: /api/v1/routes serves the route rows with hosted_mining and a stale flag the badge reads {cr}",
          cr == 200 and any(r.get("id") == "hosted_mining" and "state" in r and "stale" in r for r in json.loads(br).get("routes", [])))
    cs, hs = req("/start")
    ms = hs[hs.index("<main"):hs.index("</main>")]
    check("server: /start renders the live strip with the three badges", cs == 200 and ms.count('class="sv-vf-b"') == 3
          and all(x in ms for x in ("Prompt copied", "Network open", "Answer verified")))
finally:
    p.terminate(); p.wait(10)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
