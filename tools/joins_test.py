"""Home headline row and Agents / hr (1.26.24).
* joins_rate_calc: trailing 24 h by default; an ended pause (agents_joined flat 2 h or more) starts the window where it ended,
  at least 1 h; an ongoing pause keeps 24 h; 1h, 6h and 24h rates; no data is None
* joins_rate reads POAScan's own status snapshots only (no upstream call) and is cached
* the home page leads with Total mined, Circulating supply, Agents and Agents / hr in a .kpis row: terse labels, no sub-line,
  no share buttons, the watermark on every card, 'Agents' not 'Accounts'; Holders and heights stay on the page
* /about#home explains each; /api/v1/summary and /api/v1/status carry agent_joins_per_hour and its window (additive)
Usage: python3 tools/joins_test.py"""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "j.db"); os.environ["POASCAN_DB"] = dbp; os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import db, analytics as A
H = 3600; T = 1_800_000_000

# ---------------- pure calc ----------------
steady = [(T + i * 900, 1000 + i * 8) for i in range(4 * 30)]          # 32 an hour for 30 h, a read every 15 min
r = A.joins_rate_calc(steady)
check("steady 32/h over 24 h: 32, window 24h", r["agent_joins_per_hour"] == 32 and r["window"] == "24h" and abs(r["window_hours"] - 24) < .01 and r["joins"] == 768)
check("trailing 1h, 6h and 24h rates", r["trailing"] == {"1h": 32.0, "6h": 32.0, "24h": 32.0})
# 20 h flat (paused), then 3 h at 40/h
pts = [(T + i * 900, 1000 + i * 8) for i in range(16)]
flat = pts[-1][1]; t = pts[-1][0]
pts += [(t + i * 900, flat) for i in range(1, 4 * 20 + 1)]
t = pts[-1][0]; pts += [(t + i * 900, flat + i * 10) for i in range(1, 13)]
r = A.joins_rate_calc(pts)
check("ended pause: window starts where it ended (3 h at 40/h -> 40)", r["window"] == "since_pause" and r["agent_joins_per_hour"] == 40 and abs(r["window_hours"] - 3) < .01 and r["paused_until"] == t)
check("the 24 h trailing rate is still reported (drags low)", r["trailing"]["24h"] < 10 and r["trailing"]["1h"] == 40.0)
# reopened 15 min ago: window is at least 1 h
pts2 = [(T + i * 900, 500) for i in range(12)] + [(T + 12 * 900, 520)]
r = A.joins_rate_calc(pts2)
check("window never shorter than 1 h", r["window_hours"] >= 1 and r["agent_joins_per_hour"] == 20)
# ongoing pause: keep the honest 24 h figure
pts3 = [(T + i * 900, 1000 + i * 8) for i in range(4 * 20)] ; t = pts3[-1][0]
pts3 += [(t + i * 900, pts3[-1][1]) for i in range(1, 4 * 5)]
r = A.joins_rate_calc(pts3)
check("ongoing pause keeps the 24 h window", r["window"] == "24h" and r["paused_until"] is None)
check("slow but moving (a join every 90 min) is not a pause", A.joins_rate_calc([(T + i * 900, 100 + i // 6) for i in range(100)])["window"] == "24h")
check("no data: None", A.joins_rate_calc([]) is None and A.joins_rate_calc([(T, 5)]) is None)

# ---------------- DB read ----------------
now = int(time.time())
db.write("DELETE FROM snaps WHERE kind='status'")
for i in range(4 * 26): db.add_snap("status", {"agents_joined": 3000 + i * 9, "supply": "980933293.9"}, now - (4 * 26 - 1 - i) * 900)
A._cache.clear(); r = A.joins_rate()
check("from POAScan's status snapshots: 36/h over 24 h", r and r["agent_joins_per_hour"] == 36 and r["window"] == "24h")
src = open(os.path.join(ROOT, "poascan", "analytics.py"), encoding="utf-8").read()
fn = src[src.index("# ---- Agents / hr"):]
check("no upstream call in the Agents / hr code", not any(w in fn for w in ("urlopen", "requests", "fetch(", "POA_BASE")))
check("cached (A.cached, 120 s)", '@cached("joins_rate", 120)' in fn)

# ---------------- server ----------------
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env)
get = lambda u: urllib.request.urlopen(base + u, timeout=30).read().decode()
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    home = get("/")
    m = re.search(r'<section class="stats four kpis"[^>]*>(.*?)</section>', home, re.S)
    k = m.group(1) if m else ""
    labels = re.findall(r'<div class="sl">(?:<svg.*?</svg>)?(?:<span[^>]*>)?([^<]+)', k)
    check(f"headline row: Total mined, Circulating supply, Agents, Agents / hr {labels}", labels == ["Total mined", "Circulating supply", "Agents", "Agents / hr"])
    check("Agents / hr value is live (data-live=joins_hr) and shows 36", re.search(r'data-live="joins_hr"><span class="num"[^>]*>36<', k) is not None)
    check("no sub-line, share button or 'Accounts' in the row", k.count('class="stat"') == 4 and not any(x in k for x in ('class="sub', "share", "Share", "Accounts", "asof")))
    css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
    check("every stat card carries the watermark; the row is 4 across and 2 x 2 on phones",
          ".stat::after" in css and "wm.svg" in css and ".kpis{grid-template-columns:repeat(4" in css and re.search(r"max-width:900px\)\{\.kpis\{grid-template-columns:repeat\(2", css) is not None)
    check("Holders and heights stay on the home page", all(f'data-live="{x}"' in home for x in ("holders", "height", "checkpoint")))
    ab = get("/about"); sec = ab[ab.index('id="home"'):] if 'id="home"' in ab else ""; sec = sec[:sec.index("</ul>")] if sec else ""
    check("/about#home explains all four", all(x in sec for x in ("Total mined", "Circulating supply", "<b>Agents</b>", "Agents / hr", "2 h", "1 h")))
    for u in ("/api/v1/summary", "/api/v1/status"):
        d = json.loads(get(u)); w = d.get("agent_joins_per_hour_window") or {}
        check(f"{u}: agent_joins_per_hour 36 with its window", d.get("agent_joins_per_hour") == 36 and w.get("kind") == "24h" and set(w.get("trailing_per_hour") or {}) == {"1h", "6h", "24h"})
    check("no em dash in the new copy", "\u2014" not in k + sec)
finally:
    p.terminate(); p.wait(10)
print(f"\n{'FAILED: ' + ', '.join(fails) if fails else 'all passed'}"); sys.exit(1 if fails else 0)
