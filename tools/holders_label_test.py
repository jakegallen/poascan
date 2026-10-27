"""Holders (1.26.88, one number since 1.26.174). The node's own count (/api/status holders) is the one Holders number on Home,
/token, the FAQ, every chart, the API and MCP (holders_count); POAScan's list count (/api/agents above zero plus paid addresses
missing from it) is holders_in_list and the basis of the rich list. Network > Health still sets the two side by side, marked
balances and node; the method is on /about#holders only. E4 and E5 (the Oct 25 step-ups) are milestones on Holders only.
Temp database, no network. Usage: python3 tools/holders_label_test.py"""
import os, sys, tempfile, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "h.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
from poascan import db, views as V, views2 as V2, views3 as V3, faq as FQ, chartpop as CP, reconcile as RE, agentapi as AG
db.init()
check("chart pop-out title Holders", CP.CHARTS["holders"]["title"] == "Holders")
src = {m: open(getattr(m, "__file__")).read() for m in (V, V3, FQ)}
check("home, /token, FAQ stats and Network charts read Holders; no Holders (node) label left",
      src[V].count('stat("Holders"') == 2 and "Holders (node)" not in src[V].split('<li id="holders">')[0] and 'stat("Holders"' in src[FQ] and '"Holders", "holders", hc' in src[V3]
      and "Holders (node)" not in src[FQ] + src[V3])
from poascan import analytics as A, milestones as MS
db.put_blob("status", {"holders": 1665, "agents_joined": 5377})
A._cache.clear()
A.holders = lambda: dict(rows=[dict(addr="poa1" + str(i) * 40, balance=10.0 - i, share=.1, rank=i + 1, src="/api/agents") for i in range(3)], total=27.0, count=3,
                         in_agents=3, missing=0, top10_share=1.0, top1_share=.37, gini=.1, median=9.0, cluster_balance=None, cluster_count=0, cluster_share=None)
A.rewards_by_addr = lambda: {}
check("one number: holders_count is the node's /api/status holders", A.holders_count() == 1665)
c = A.concentration.__wrapped__() if hasattr(A.concentration, "__wrapped__") else A.concentration()
check("concentration holders is the same number; the list count is holders_in_list", c["holders"] == 1665 and c["holders_in_list"] == 3)
r = AG.t_richlist({})
check("MCP rich list: holders is the same number, holders_in_list the list", r["holders"] == 1665 and r["holders_in_list"] == 3)
db.put_blob("status", {"agents_joined": 5377}); A._cache.clear()
check("no node count: falls back to the list count", A.holders_count() == 3)
ev = {e["key"]: e for e in MS.events()}
check("E4 and E5 closes are milestones at their close record times", ev["s2_e4_close"]["ts"] == 1792965018 and ev["s2_e5_close"]["ts"] == 1792986742
      and ev["s2_e4_close"]["label"] == "E4 close" and ev["s2_e5_close"]["label"] == "E5 close")
on = lambda k: [c for c in ("mined", "supply", "circ", "agents", "joins", "active", "holders", "txs", "home-agents") if k in [e["key"] for e in MS.events(c)]]
check(f"E4 and E5 only on Holders ({on('s2_e4_close')}, {on('s2_e5_close')})", on("s2_e4_close") == ["holders"] and on("s2_e5_close") == ["holders"])
now = int(time.time())
row = dict(key="holders", label="Holders", poascan=727, node=729, diff=-2, unit="int", state="differs", reason="read at different times",
           poascan_source="", poascan_as_of=now - 60, node_source="", node_as_of=now - 120)
other = dict(row, key="agents", label="Agents", poascan=800, node=801)
RE.reconcile = lambda: dict(rows=[row, other], per_close=[], matched=0, explained=0, differs=2)
html = V2.recon_card()
i = html.index("<b>Holders</b>"); hrow = html[i:html.index("</tr>", i)]; j = html.index("<b>Agents</b>"); arow = html[j:html.index("</tr>", j)]
check("Health: the holders row marks its cells balances and node; other rows unchanged", ">balances · " in hrow and ">node · " in hrow and hrow.index("balances") < hrow.index("node · ")
      and "balances" not in arow and "node · " not in arow and "727" in hrow and "729" in hrow)
ab = V.about() if hasattr(V, "about") else ""
check("/about#holders: one number, the node's count, and the list as holders_in_list", 'id="holders"' in ab and "one number everywhere" in ab and "holders_in_list" in ab and "E4 and E5" in ab)
check("llms methodology names one number and the list", "one number everywhere" in AG.llms_txt() + AG.llms_full_txt() and "holders_in_list" in AG.llms_txt() + AG.llms_full_txt())
check("no em or en dash", not any(c in html + ab for c in "\u2014\u2013"))
print("ALL OK" if not fails else f"{len(fails)} FAILED"); sys.exit(1 if fails else 0)
