"""Every /governance tab is kept like a warmed page once rendered (1.26.366): a visitor gets the last good copy at any
age without waiting, and a background thread renders the next one.

Root cause covered: a cold tab render reads every close (about a minute and 200 MB) and used to run inside a visitor's
serving slot, so tabs outside the warm list (settlement, graders, queue ...) held a slot for 12 to 150 s.

Run: python3 tools/govpin_test.py (temp db, in-process, no network).
"""
import os, sys, tempfile, threading, time

os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "govpin.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_HTML_CACHE"] = "1"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import poascan.server as SV
from poascan import htmlcache as HC, governance as GV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

tabs = [k for k, _ in GV.TABS]
for t in tabs:
    ok(HC.is_warm("/governance", HC.canon_qs("/governance", {"tab": [t]})), f"tab {t} is kept as a pinned page")
ok(HC.is_warm("/governance", {}), "the bare page is pinned")
ok(not HC.is_warm("/governance", HC.canon_qs("/governance", {"tab": ["settlement"], "sort": ["n"]})), "a sorted view stays in the normal cache")
ok(HC.canon_qs("/governance", {"tab": ["nope"]}) == {}, "an unknown tab collapses onto the bare page")
ok(not HC.is_warm("/address/poa1x", {}), "other pages are unchanged")

k = HC.key("/governance", {"tab": ["settlement"]}, 2, False)
HC.put(k, "<p>v1</p>", now=time.time() - 3600)
calls = []; done = threading.Event()
def fn():
    calls.append(threading.current_thread().name); time.sleep(0.2); done.set(); return "<p>v2</p>"
t0 = time.time(); h = HC.render(k, 60, fn); dt = time.time() - t0
ok(h == "<p>v1</p>" and dt < 0.1, f"an hour old copy is served at once ({dt:.3f} s)")
done.wait(3)
ok(calls == ["htmlrefresh"], f"the next copy renders on a background thread ({calls})")
time.sleep(0.05)
ok(HC.last(k) == "<p>v2</p>", "and replaces the pinned copy when finished")
ok(k in HC._pin and k not in HC._c, "kept outside the size-bounded FIFO")

k2 = HC.key("/governance", {"tab": ["settlement"], "sort": ["n"]}, 2, False)
HC.put(k2, "<p>s</p>")
ok(k2 in HC._c and k2 not in HC._pin, "a sorted view is stored in the FIFO as before")
print("FAIL:" if fails else "all ok", fails if fails else "")
sys.exit(1 if fails else 0)
