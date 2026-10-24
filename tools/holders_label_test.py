"""Holder count labels (1.26.88). Two holder counts can differ by a few: the node's own count (/api/status holders) and
POAScan's count from balances (/api/agents above zero plus paid addresses missing from it). Tiles and charts that show the
node's count read Holders (node); Network > Health marks its two cells balances and node; the method is on /about#holders only.
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
check("chart pop-out title Holders (node)", CP.CHARTS["holders"]["title"] == "Holders (node)" if hasattr(CP, "CHARTS") else "Holders (node)" in open(CP.__file__).read())
src = {m: open(getattr(m, "__file__")).read() for m in (V, V3, FQ)}
check("home, /token, FAQ stats and Network charts label the node count Holders (node); no bare Holders stat left",
      src[V].count('stat("Holders (node)"') == 2 and 'stat("Holders"' not in src[V] and 'stat("Holders (node)"' in src[FQ] and '"Holders (node)", "holders", hc' in src[V3])
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
check("/about#holders explains both counts", 'id="holders"' in ab and "Holders (node)" in ab and "Holders (balances)" in ab)
check("llms methodology names both counts", "Holders (node)" in AG.llms_txt() + AG.llms_full_txt() and "Holders (balances)" in AG.llms_txt() + AG.llms_full_txt())
check("no em or en dash", not any(c in html + ab for c in "\u2014\u2013"))
print("ALL OK" if not fails else f"{len(fails)} FAILED"); sys.exit(1 if fails else 0)
