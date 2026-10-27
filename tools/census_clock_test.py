"""Census clock (1.26.177). The Census page shows when the daily census last ran and when it runs next, in the visitor's zone
(lt time tags, UTC text without script), tags Stale when the last run is over 26 h old, and reads Due once the next run time
has passed. /api/health and the MCP census tool carry the same clock. Temp database, no network.
Usage: python3 tools/census_clock_test.py"""
import os, sys, tempfile, time, re
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "c.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
from poascan import db, agents as G, views as V, agentapi as AG, indexer as I, server as SV
db.init()
now = int(time.time())
check("the clock follows the indexer's census interval", G.CENSUS_EVERY_S == [j for j in I.JOBS if j[0] == "census"][0][2] == 86400 and G.CENSUS_STALE_S == 26 * 3600)
c = G.census_clock(now)
check("no run yet: no times, not stale", c["last_run"] is None and c["next_run"] is None and not c["stale"] and not c["due"])
check("no run yet: the page line says so", "Census not run yet" in V.census_clock_html(c))
snap = lambda t: dict(ts=t, n=10, disclosed=2, eco=[["Claude", 2], ["Undisclosed", 8]], harness=[["Undisclosed", 10]], shannon=0.0, effective_families=1.0, source="POASCAN classifier")
db.add_snap("census", snap(now - 3 * 86400), ts=now - 3 * 86400); db.add_snap("census", snap(now - 3 * 3600), ts=now - 3 * 3600)
c = G.census_clock(now)
check("last run is the newest snapshot; next is a day later", c["last_run"] == now - 3 * 3600 and c["next_run"] == now - 3 * 3600 + 86400 and not c["stale"] and not c["due"])
h = V.census_clock_html(c)
ts = [int(x) for x in re.findall(r'<time class="t lt" datetime="[^"]+" data-ts="(\d+)" data-f="dt">[^<]+ UTC</time>', h)]
check("both times are visitor-local lt tags with a UTC fallback", ts == [c["last_run"], c["next_run"]])
check("terse labels, no Stale tag on a fresh run", "Last run " in h and "Next run " in h and "Stale" not in h and "Due" not in h)
check("copy: no em or en dash", "\u2014" not in h and "\u2013" not in h)
c = G.census_clock(now + 22 * 3600)
check("next run time passed, under 26 h: Due, not stale", c["due"] and not c["stale"] and '<span class="cdue">Due</span>' in V.census_clock_html(c))
c = G.census_clock(now + 24 * 3600)
h = V.census_clock_html(c)
check("missed run (over 26 h): Stale tag beside the times", c["stale"] and 'class="tag warn"' in h and ">Stale</summary>" in h and "a run was missed" in h)
page = V.census_page()
check("the Census page carries the clock under its tabs", 'id="census-clock"' in page and page.index('id="census-clock"') < page.index("Model families"))
check("Journey tab has no census clock (no census data there)", 'id="census-clock"' not in V.census_page("journey"))
hj = SV.api("/api/health", {})[0]
check("/api/health carries the census clock", hj["census"]["last_run"] == now - 3 * 3600 and hj["census"]["next_run"] == now - 3 * 3600 + 86400 and hj["census"]["stale"] is False)
t = AG.t_census({})
check("MCP census tool carries last_run, next_run and stale", t["last_run"] == now - 3 * 3600 and t["next_run"] == now - 3 * 3600 + 86400 and t["stale"] is False)
css = open(os.path.join(ROOT, "static", "style.css")).read()
check("clock CSS present", ".cclk{" in css and ".cclk .cdue" in css)
check("/about says when the census runs and when it is Stale", 'id="census-clock-method"' in V.about() and "26 h" in V.about())
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
