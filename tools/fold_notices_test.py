"""Data-state notices folded into the header status note (1.26.181). The Home and /start Upgrading strip (views.upgrade_strip,
start.strip) and the in-page "lookup paused" note (ui.upnote) are gone and cannot render; their reasons sit in the header status
note: Upgrading shows the strip's line (the pill is never hidden, no separate Upgrading dot), a paused minepoa.com lookup turns
Live into Partial with "minepoa.com paused tx lookups. Showing indexed data." Temp database, no network.
Usage: python3 tools/fold_notices_test.py"""
import os, sys, tempfile, time, re
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "f.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
from poascan import db, ui, views as V, start as SP, strain as ST, maint as M, indexer as I, analytics as A
db.init()
check("the strip, the dot and the in-page note are gone from the code", not hasattr(V, "upgrade_strip") and not hasattr(V, "upline") and not hasattr(SP, "strip")
      and not hasattr(ui, "upnote") and not hasattr(ui, "updot"))
css = open(os.path.join(ROOT, "static", "style.css")).read(); js = open(os.path.join(ROOT, "static", "app.js")).read()
src = "".join(open(os.path.join(ROOT, "poascan", f)).read() for f in ("views.py", "start.py", "ui.py", "views2.py", "views3.py", "views4.py"))
check("no CSS for them", ".upstrip" not in css and ".updot" not in css and ".ntin" not in css and ".stup" not in css)
check("no client hooks for them", "data-upline" not in js and "data-upstamp" not in js and "#updot" not in js and 'p.hidden=f.state=="up"' not in js and "p.hidden=false" in js)
check("no page markup can emit them", 'class="upstrip' not in src and 'class="ntin' not in src and 'id="updot"' not in src)
# Upgrading: the strip's line in the note, Details to /upgrade, pill shown
up = M.state()["active"]
lead, aside, tail = M.strip_text(); want = f"{lead}{aside}." + (f" {tail}" if tail else "")
p = ui.status_pill({"state": "up", "label": "Upgrading", "why": "Network upgrade in progress", "fetched_at": int(time.time())})
check(f"Upgrading: the note's first line is the old strip's line ({p['reasons'][:1]})", (not up) or (p["reasons"][0] == want and want.startswith("Hosted mining")))
check("Upgrading: Details to /upgrade, label Upgrading", 'href="/upgrade">Details</a>' in p["pop"] and p["label"] == "Upgrading")
p2 = ui.status_pill({"state": "stale", "label": "Stale", "why": "No fresh read from minepoa.com"})
check("Stale outranks Upgrading: the note still carries the upgrade line and Details", (not up) or (want in p2["reasons"] and 'href="/upgrade">Details</a>' in p2["pop"]))
h = ui.pill_html({"state": "up", "label": "Upgrading", "why": ""})
check("the header pill is never hidden (Upgrading included)", '<details class="qtip hv spill" id="livepill"><summary class="pill up"' in h and " hidden" not in h[:80])
home = V.home() if hasattr(V, "home") else ""
fs = A.freshness()["state"]
check(f"home: no strip; while the header shows Upgrading its note carries the line (state {fs})", bool(home) and 'class="upstrip' not in home and (fs != "up" or f'<span class="sp-r">{want}</span>' in home))
# a paused lookup: Live turns Partial, one terse line
check("no halt: no reason", ui._halt_reason() == "")
ST.record_halt("/api/explorer/tx/" + "a" * 64, {"text": "endpoint temporarily halted", "signals": []})
p = ui.status_pill({"state": "live", "label": "Live", "why": "", "fetched_at": int(time.time())})
check(f"tx lookup paused: one line with the reason, Live stays Live (1.26.220: tx lookup is not core) ({p['reasons']})", p["state"] == "live" and "minepoa.com paused tx lookups. Showing indexed data." in p["reasons"])
ST.record_halt("/api/chains", {"text": "endpoint temporarily halted", "signals": []})
check("two paused lookups read as one line", ui._halt_reason() == "minepoa.com paused tx and wallet link lookups. Showing indexed data.")
ST.reset()
check("cleared: no reason", ui._halt_reason() == "")
allc = " ".join([want, "minepoa.com paused tx and wallet link lookups. Showing indexed data."])
check("copy: no em or en dash, Agents not Accounts", "\u2014" not in allc and "\u2013" not in allc and "Accounts" not in allc)
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
