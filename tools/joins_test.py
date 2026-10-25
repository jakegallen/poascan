"""Home headline row and Agents / hr, the API join rate (1.26.24; the Home card is Active Agents since 1.26.116).
* joins_rate_calc: trailing 24 h by default; an ended pause (agents_joined flat 2 h or more) starts the window where it ended,
  at least 1 h; an ongoing pause keeps 24 h; 1h, 6h and 24h rates; no data is None
* joins_rate reads POAScan's own status snapshots only (no upstream call) and is cached
* the home page leads with (no USD on that row, audit SC-020; USD stays on Market and /token) Total mined, Circulating supply, Agents and Agents / hr in a .kpis row: terse labels, no sub-line,
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
import routes_test; routes_test.seed(dbp)   # the fixture plus a filled swap and fx, so USD renders where it belongs
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

# ---------------- genesis cut (1.26.x agentsph): agents_joined restarted lower with the carried Agents ----------------
C = T + 20 * H   # the cut: 20 h at 40/h in segment 1 (to 1800), 6 h flat (halted), then 1000 carried, +3/h in segment 2
s1 = [(T + i * 900, 1000 + i * 10) for i in range(4 * 14 + 1)]
s1 += [(s1[-1][0] + i * 900, s1[-1][1]) for i in range(1, 4 * 6)]
s2 = [(C + 600 + i * 900, 1000 + (i * 3) // 4) for i in range(4 * 3 + 1)]
pts = s1 + s2; end = pts[-1][0]
r = A.joins_rate_calc(pts, floor=C)
check(f"since the cut: 3/h over the segment, kind since_cut {r and (r['agent_joins_per_hour'], r['window'], r['window_hours'], r['joins'])}",
      r and r["agent_joins_per_hour"] == 3 and r["window"] == "since_cut" and r["joins"] == 9 and abs(r["window_hours"] - 3) < .01)
check("since the cut: 6h and 24h trailing are None (longer than the segment), 1h is real", r["trailing"]["6h"] is None and r["trailing"]["24h"] is None and r["trailing"]["1h"] == 3.0)
check("since the cut: under 1 h of the segment read is None, not a figure over minutes", A.joins_rate_calc(s1 + s2[:3], floor=C) is None)
check("a cut more than 24 h back: the normal 24 h window", A.joins_rate_calc(steady, floor=T - 10)["window"] == "24h")
st = A.join_steps(pts, [C])
check("join_steps: no step across the cut (no -800, no fake zero pair)", all(d >= 0 for _, d in st) and len(st) == len(pts) - 2 and sum(d for _, d in st) == 560 + 9)
hj = A.hourly_joins(pts, [C], now=end + H)
check("hourly: no bucket for the hour that straddles the cut", not any(t == (C // H) * H for t, _ in hj) and all(v >= 0 for _, v in hj))
check("hourly: real 40/h before the halt, 0 while halted, 3/h after the cut", hj[0][1] == 40 and any(v == 0 and t < C for t, v in hj) and [v for t, v in hj if t > C][:2] == [3, 3])
hj2 = A.hourly_joins(pts, [C], now=end)
check("hourly: the hour still filling is left out", max(t for t, _ in hj2) < (end // H) * H)
check("hourly without cuts keeps the old behaviour (the cross-cut hour clamps to 0)", any(t == (C // H) * H and v == 0 for t, v in A.hourly_joins(pts, [], now=end + H)))
jt = [C + 2 * H + i * 1200 for i in range(6)]   # joining reopened 2 h after the cut: 6 joins, one every 20 min
s2b = [(C + 600 + i * 900, 1000 + max(0, (C + 600 + i * 900 - jt[0]) // 1200 + 1) if C + 600 + i * 900 >= jt[0] else 1000) for i in range(4 * 4)]
now2 = C + 4 * H
r = A.joins_rate_calc(s1 + s2b, now=now2, floor=C, join_ts=jt)
check(f"since the cut from join txs: 6 joins over the 2 h since the first join -> 3, joining_from set {r and (r['agent_joins_per_hour'], r['window_hours'], r['source'])}",
      r and r["agent_joins_per_hour"] == 3 and r["joins"] == 6 and abs(r["window_hours"] - 2) < .01 and r["joining_from"] == jt[0] and r["source"] == "join_txs" and r["window"] == "since_cut")
r0 = A.joins_rate_calc(s1 + [(C + 600, 1000), (C + 2 * H, 1000)], now=C + 2 * H, floor=C, join_ts=[])
check("since the cut, none joined yet in a segment over 1 h old: 0 (real), not None and not a pre-cut figure", r0 and r0["agent_joins_per_hour"] == 0 and r0["joining_from"] is None)
rg = A.joins_rate_calc(s1 + s2b, now=now2, floor=C, join_ts=jt[:2])
check("fewer join txs than agents_joined rose (feed gap): status reads instead", rg and rg["source"] == "status")
js = A.joins_series(s1 + s2b, now=now2 + 1, floor=C, join_ts=jt)
check(f"chart since the cut: join txs per whole hour of the segment {[(t - C) // H for t, _ in js if t >= C - H]}",
      [(t, v) for t, v in js if t >= C - H] == [(C - H, 0), (C, 0), (C + H, 0), (C + 2 * H, 3), (C + 3 * H, 3)])
js = A.joins_series(s1 + s2b, now=now2 + 1, floor=C + 600, join_ts=jt)
check("a cut inside an hour: that hour has no point (the line breaks there), the next whole hour starts the segment",
      not any(t == C for t, _ in js) and min(t for t, _ in js if t > C) == C + H and max(t for t, _ in js if t < C) == C - H)
from poascan import ui as U
sv = U.spark([(t, v) for t, v in hj], breaks=[C])
check("sparkline breaks at the cut: two polylines", sv.count("<polyline") == 2 and U.spark([(t, v) for t, v in hj]).count("<polyline") == 1)

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
    check(f"headline row: Total mined, Circulating supply, Agents, Active Agents {labels}", labels == ["Total mined", "Circulating supply", "Agents", "Active Agents"])
    check("Active Agents value is live (data-live=active); no Agents / hr card (1.26.116)", re.search(r'data-live="active"><span class="num"', k) is not None and "joins_hr" not in k)
    check("no sub-line, share button or 'Accounts' in the row", len(re.findall(r'class="stat[ "]', k)) == 4 and not any(x in k for x in ('class="sub', "share", "Share", "Accounts", "asof")))
    css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
    check("every stat card carries the watermark; the row is 4 across and 2 x 2 on phones",
          ".stat::after" in css and "wm.svg" in css and ".kpis{grid-template-columns:repeat(4" in css and re.search(r"max-width:900px\)\{\.kpis\{grid-template-columns:repeat\(2", css) is not None)
    check("no USD on the headline row (audit SC-020); the Market card keeps it", 'class="usd"' not in k and "\u2248$" not in k and 'class="usd"' in home)
    from poascan import views as V
    lc = V.live_snapshot()["cards"]
    check("live cards: circ (home) has no USD; vest (token page) keeps it", 'class="usd"' not in lc.get("circ", "x usd") and 'data-live="circ"' in lc["circ"] and 'class="usd"' in lc["vest"])
    check("Holders and heights stay on the home page", all(f'data-live="{x}"' in home for x in ("holders", "height", "checkpoint")))
    ab = get("/about"); sec = ab[ab.index('id="home"'):] if 'id="home"' in ab else ""; sec = sec[:sec.index("</ul>")] if sec else ""
    check("/about#home explains all four and the API join rate", all(x in sec for x in ("Total mined", "Circulating supply", "<b>Agents</b>", "<b>Active Agents</b>", "agent_joins_per_hour", "2 h", "1 h")))
    for u in ("/api/v1/summary", "/api/v1/status"):
        d = json.loads(get(u)); w = d.get("agent_joins_per_hour_window") or {}
        check(f"{u}: agent_joins_per_hour 36 with its window", d.get("agent_joins_per_hour") == 36 and w.get("kind") == "24h" and set(w.get("trailing_per_hour") or {}) == {"1h", "6h", "24h"})
    check("no em dash in the new copy", "\u2014" not in k + sec)
finally:
    p.terminate(); p.wait(10)
print(f"\n{'FAILED: ' + ', '.join(fails) if fails else 'all passed'}"); sys.exit(1 if fails else 0)
