"""1.26.269: a stale feed tag on the health view. When an upstream feed's last good read is older than
max(STALE_FLOOR_S, 3x its interval), /api/v1/health and the health page carry a Stale tag with how long it has been
stale, so a silent stall (the Nov 4 /api/networks 25 min timeout that recovered unseen) is visible. No banners, no
external notifications. A Retired feed is never also tagged Stale. Self contained: no network, no database.
Usage: python3 tools/stale_feed_test.py"""
import os, sys, time
os.environ["POASCAN_SEGMENTS"] = "1"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import analytics as A
from poascan import views2 as V2

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

now = 1_000_000

# ---- the pure threshold helper ------------------------------------------------------------------------------------
check("fresh read is not stale", A.feed_stale_s(now - 60, 60, now) is None)
check("a fast feed (60s) with no read for 20 min is stale (15 min floor)", A.feed_stale_s(now - 1200, 60, now) == 1200)
check("a fast feed just over the floor (900s) is stale", A.feed_stale_s(now - 901, 60, now) == 901)
check("a fast feed under the floor (900s) is not stale", A.feed_stale_s(now - 899, 60, now) is None)
check("a slow feed (hourly) uses 3x interval, not the floor: 2 h is not stale", A.feed_stale_s(now - 7200, 3600, now) is None)
check("a slow feed (hourly) at 4 h is stale (over 3x)", A.feed_stale_s(now - 14400, 3600, now) == 14400)
check("no interval (on-view feed) is never auto-stale here", A.feed_stale_s(now - 99999, 0, now) is None)
check("never read is not stale", A.feed_stale_s(None, 60, now) is None)

# ---- the health view renders the Stale tag with the age, and nothing for fresh feeds -------------------------------
fd = {"state": "OK", "chain": "Live", "routes": [], "feeds": [
    {"label": "Networks", "state": "OK", "last_ok": now - 1500, "stale": True, "stale_s": 1500},
    {"label": "Status", "state": "OK", "last_ok": now - 30},
    {"label": "Grading list", "state": "Retired", "last_ok": now - 20000, "retired": True},
]}
html = V2.feeds_html(fd)
seg = html.split('data-feed="Networks"')[1].split("</li>")[0]
check("the stale feed shows a Stale tag with a duration", ">Stale 25m" in seg or "Stale 25m" in seg)
fresh = html.split('data-feed="Status"')[1].split("</li>")[0]
check("a fresh feed shows no Stale tag", "Stale" not in fresh)
ret = html.split('data-feed="Grading list"')[1].split("</li>")[0]
check("a Retired feed is not also tagged Stale", "Stale" not in ret and ">Retired<" in ret)
# (repo-wide no-dash enforcement lives in design_tokens_test.py, which scans every tracked file)

print("\n" + ("all ok" if not fails else f"{len(fails)} FAILED: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
