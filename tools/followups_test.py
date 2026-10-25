"""Phase 1 follow-ups (1.26.121 and 1.26.122). Stat state tags: stale or unconfirmed values carry a small tag beside the label (ui.flag) instead of a sub-line
under the value. Hover shows the detail (title), tap opens it (details/summary), aria-label names it. Network Charts has 24h, 7d, 30d and All. Temp database, no network.
Usage: python3 tools/followups_test.py"""
import os, re, sys, tempfile, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "f.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
from poascan import ui as U
now = time.time()
old = U.stat("K", "12", asof=now - 4 * 3600)
check("an hourly source read 4h ago is tagged Stale beside the label", '<summary class="tag warn" aria-label="Stale: Last read 4h 0m ago" title="Last read 4h 0m ago">Stale</summary>' in old
      and old.index("Stale") < old.index('class="sv"'))
fresh = U.stat("K", "12", asof=now - 600)
check("a fresh read has no tag, its age is on the label hover", "sflag" not in fresh and 'title="Read 10m ago">K<' in fresh)
bal = U.stat("Balance", "7.24M", asof_text="As of checkpoint 44003")
check("a balance from an earlier segment: Stale tag with the checkpoint as its detail", 'aria-label="Stale: As of checkpoint 44003"' in bal and '<span class="qbox" role="note">As of checkpoint 44003</span>' in bal)
un = U.stat("Total rewards", "7.95M", flag_html=U.flag("Unconfirmed", "Includes Unconfirmed rewards"))
check("Unconfirmed tag on total rewards", 'aria-label="Unconfirmed: Includes Unconfirmed rewards"' in un and ">Unconfirmed</summary>" in un)
for h in (old, fresh, bal, un):
    after = h[h.index('class="sv"'):]
    check("no sub-line under the value", "asof" not in h and after.count("<div") == 0 and not re.search(r"</div>\s*<div", after))
check("tags are tap tooltips (details/summary, the qtip note app.js closes)", '<details class="qtip sflag">' in old)
from poascan import db, views3 as V3
db.init()
cb = V3.charts_body("30d")
check("Network Charts: 24h, 7d, 30d and All chips, 30d on", all(f">{t}</a>" in cb for t in ("24h", "7d", "30d", "All")) and 'range=30d" class="chip on"' in cb)
check("an unknown range falls back to 7d", 'class="chip on">7d<' in V3.charts_body("90d"))
check("no em or en dash", not any(c in old + bal + un for c in "\u2013\u2014"))
print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
