"""Agents hub (1.26.388): one hero and one tabbed module for Rankings, Models, Operators and Community; every old URL opens
its tab; the first funnel stage is labelled Archive; rank arrows come from the per-close snapshot; no header shortcut links,
no dashes, no For agents card. Usage: python3 tools/agents_hub_test.py (fixture database, no network)."""
import os, re, sys, tempfile
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db"); os.environ["POASCAN_INDEXER"] = "0"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import fixture
fixture.seed(12)
from poascan import server as S, db, agents as G, views4 as V4, analytics as A
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)
def pg(path, **qs):
    r = S.page(path, {k: [v] for k, v in qs.items()})
    return r if isinstance(r, str) else (r[0] if isinstance(r, tuple) else str(r))
strip = lambda h: re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)

PAGES = {"/agents": "rankings", "/agents/top": "rankings", "/agents/census": "models", "/agents/operators": "operators", "/agents/community": "community"}
for p, tab in PAGES.items():
    h = pg(p)
    cur = re.search(r'class="chip on" data-kit-tab="(\w+)"', h)
    check(f"{p}: hero (Established ring, live strip, six KPIs) over one module, tab {tab} is current",
          'class="ring hring ering"' in h and 'id="score"' in h and h.count('class="stat') >= 6 and 'id="colony"' in h and cur and cur.group(1) == tab)
    check(f"{p}: four tabs, Rankings, Models, Operators, Community", all(f'data-kit-tab="{k}"' in h for k in ("rankings", "models", "operators", "community")))
    check(f"{p}: no For agents card, no Top 5, no header shortcut links, no dash", "For agents" not in h and "Top 5" not in h and "FROM POASCAN" not in h
          and not re.search("[\u2013\u2014]", strip(h)) and 'class="more"' not in h.split('id="colony"')[1])
for q, tab in (("/agents/top?tab=richlist", "richlist"), ("/agents/top?tab=streaks", "streaks"), ("/agents/top?tab=forum", "forum")):
    k = q.split("=")[1]; h = pg("/agents/top", tab=k)
    check(f"{q}: metric chip {k} is current inside Rankings", f'data-kit-sub="{k}" aria-current="page"' in h and 'data-kit-tab="rankings"' in h)
for k, sub in (("ai", "rates"), ("models", "rates")):
    h = pg("/agents/top", tab=k)
    check(f"/agents/top?tab={k} opens Models > Pass rates", f'data-kit-sub="{sub}" aria-current="page"' in h and 'data-kit-tab="models"' in h)
check("/agents/census?tab=journey opens Models > Journey with a retention strip", 'data-kit-sub="journey" aria-current="page"' in pg("/agents/census", tab="journey") and "Time to answer" in pg("/agents/census", tab="journey"))
h = pg("/agents")
check("Rankings table is capped at 20 rows", len(re.findall(r'<td data-v="\d+" class="rk p">', h)) <= 20)
check("funnel first stage is labelled Archive (10,419 style count), never Registered", ">Archive<" in h and ">Registered<" not in h)
check("Miners per epoch has a New Agents toggle (two panes, one hidden)", 'data-pane="m"' in h and 'data-pane="n"' in h and 'class="kit-pane" data-p="n" hidden' in h)
check("Agents KPI is the live chain count (status agents_joined)", f'{int(A.status().get("agents_joined") or 0):,}' in h)
# rank arrows: a snapshot for the previous close puts A2 at rank 1 and A1 at rank 2 on the Earned board, the current ranks are A1 then A2
ce = G._latest_close_epoch()
G.agent_rank("earnings", 200)   # writes the snapshot for the latest close
db.write("INSERT OR REPLACE INTO agent_rank_snap(close_epoch,metric,rank,addr,value) VALUES(?,?,?,?,?)", [(ce - 1, "earnings", 1, fixture.A2, 9.0), (ce - 1, "earnings", 2, fixture.A1, 8.0)], many=True)
h = pg("/agents/top", tab="richlist")
check("Earned shows a rank arrow since the previous close (up for the Agent that gained, down for the one that fell)", 'class="mv up"' in h and 'class="mv dn"' in h)
check("rank arrows are HTML only: the leaderboard API rows carry no mv field", all("mv" not in x for x in V4.rows("richlist")))
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
check("app.js: sub chips swap in place, chart toggle and ring count-up respect reduced motion", "a[data-kit-sub]" in js and ".kit-tg [data-pane]" in js and "if(RM||!(v>0))return" in js)
css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
check("css: reduced motion stops the ring fill transition and the arrow flash is no-preference only", "@media (prefers-reduced-motion:reduce){.ering .rp{transition:none}}" in css and "@media (prefers-reduced-motion:no-preference){.mv{animation" in css)
print("\nall passed" if not fails else f"\n{len(fails)} failed"); sys.exit(1 if fails else 0)
