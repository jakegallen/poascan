"""Apps tabs and subpages are pinned snapshots (1.26.415): a visitor gets the last good
copy at any age with no serving slot, and the existing warmer keeps them fresh.

Root cause covered: a tab click fetches the full /apps?tab=... page (kit swap). Art
views used to backfill and reassemble every work on the request, holding a slot for
about 10 to 17 s, so the next click waited on a slot and often got the Busy page.
Posts scanned every AC1 memo on each render. Only the bare /apps URL was warmed.

Run: python3 tools/appspin_test.py (temp db, in-process, no network).
"""
import os, sys, tempfile, threading, time

os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "appspin.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_HTML_CACHE"] = "1"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import poascan.server as SV
from poascan import db, htmlcache as HC, apps as AP, ac1art as R, agentapi as AG
db.init()

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

DASH = ("\u2014", "\u2013")

# ---- cache keys ----
tabs = [k for k, _ in AP.TABS]
for t in tabs:
    qs = HC.canon_qs("/apps", {"tab": [t]})
    ok(HC.is_warm("/apps", qs), f"tab {t} is kept as a pinned page")
ok(HC.is_warm("/apps", {}), "the bare page is pinned")
ok("/apps?tab=posts" in HC.WARM and "/apps?tab=games" in HC.WARM
   and "/apps?tab=atp20" in HC.WARM and "/apps?tab=art" in HC.WARM,
   "every Apps tab is on the warm list")
ok(HC.grace("/apps", {"tab": ["art"]}) == HC.WARM_GRACE
   and HC.grace("/apps", {"tab": ["posts"]}) == HC.WARM_GRACE,
   "warmed Apps tabs get grace past their TTL")
ok(HC.is_warm("/apps", HC.canon_qs("/apps", {"tab": ["art"], "col": ["MAM-GENESIS"]})),
   "a collection page is pinned")
ok(HC.is_warm("/apps", HC.canon_qs("/apps", {"tab": ["art"], "col": ["MAM-GENESIS"], "offset": ["20"]})),
   "a collection pager page is pinned")
ok(HC.is_warm("/apps", HC.canon_qs("/apps", {"tab": ["posts"], "offset": ["20"]})),
   "a posts pager page is pinned")
ok(HC.is_warm("/apps", HC.canon_qs("/apps", {"tab": ["atp20"], "tick": ["MAM"]})),
   "a tick page is pinned")
ok(HC.canon_qs("/apps", {"tab": ["nope"], "cb": ["1"]}) == {},
   "an unknown tab and a cache buster collapse onto the bare page")
ok(HC.canon_qs("/apps", {"tab": ["atp20"], "sort": ["circ"], "dir": ["asc"], "cb": ["1"]})
   == {"tab": ["atp20"], "sort": ["circ"], "dir": ["asc"]},
   "ATP-20 sort and dir survive canon and a cache buster is dropped")
ok(HC.is_warm("/apps", HC.canon_qs("/apps", {"tab": ["atp20"], "sort": ["holders"]})),
   "a sorted ATP-20 view is pinned once rendered")
ok(not HC.is_warm("/address/poa1x", {}), "other pages are unchanged")

# an hour-old pin is served at once; the next copy renders off the request
k = HC.key("/apps", {"tab": ["art"]}, 2, False)
HC.put(k, "<p>v1</p>", now=time.time() - 3600)
calls = []; done = threading.Event()
def fn():
    calls.append(threading.current_thread().name); time.sleep(0.2); done.set(); return "<p>v2</p>"
t0 = time.time(); h = HC.render(k, 60, fn); dt = time.time() - t0
ok(h == "<p>v1</p>" and dt < 0.1, f"an hour old Art tab copy is served at once ({dt:.3f} s)")
done.wait(3)
ok(calls == ["htmlrefresh"], f"the next copy renders on a background thread ({calls})")
time.sleep(0.05)
ok(HC.last(k) == "<p>v2</p>", "and replaces the pinned copy when finished")
ok(k in HC._pin and k not in HC._c, "kept outside the size-bounded FIFO")

# ---- request path never backfills art, listing is snapshotted ----
hits = []
real_backfill = R.backfill
def _bf():
    hits.append("backfill")
    return real_backfill()
R.backfill = _bf
try:
    AP.page_html({"tab": ["art"]})
    AP.page_html({"tab": ["art"], "col": ["MAM-GENESIS"]})
    AP.page_html({"tab": ["art"], "offset": ["20"]})
    ok(not hits, "Art tab and subpages do not backfill on a visitor render")
finally:
    R.backfill = real_backfill

disco = []
real_discover = R.discover_cids
def _dc():
    disco.append(1)
    return real_discover()
R.invalidate()
R.discover_cids = _dc
try:
    R.works(); R.works()
    ok(len(disco) == 1, f"works() reuses the listed snapshot ({len(disco)} discover calls)")
    R.invalidate()
    R.works()
    ok(len(disco) == 2, "invalidate drops the listing so the next read rebuilds it")
finally:
    R.discover_cids = real_discover

# rasters are content-addressed and already on disk
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "server.py"), encoding="utf-8").read()
idx = src.find('path.startswith("/art/raster/")')
chunk = src[idx:idx + 800] if idx >= 0 else ""
ok(idx >= 0 and "IMMUTABLE" in chunk and "max-age=3600" not in chunk,
   "art rasters are served with the long immutable cache header")
ok(SV.IMMUTABLE == "public, max-age=31536000, immutable", "IMMUTABLE is a year-long immutable policy")
ok("/apps/memo-img/" in src and "AP.memo_raster" in src and src.count('startswith("/apps/memo-img/")') >= 2,
   "memo image route is slot-free and uses memo_raster")
ok("img-src 'self' data:" in SV.CSP, "CSP allows data images; the memo route is still same-origin")

ok(AG.VERSION == "1.26.433", "version is 1.26.433")
cl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "CHANGELOG.md"), encoding="utf-8").read()
block = cl.split("## [1.26.415]")[1].split("## [")[0] if "## [1.26.415]" in cl else ""
ok("## [1.26.415]" in cl and "Busy" in block and "warmer" in block,
   "changelog records the Apps snapshot fix")
ok(not any(d in block for d in DASH), "changelog has no typographic dash")
ok(callable(getattr(HC, "APPS_WARM", None)) and isinstance(AP.warm_urls(), list),
   "the warmer can list Apps subpages")

print("FAIL:" if fails else "all ok", fails if fails else "")
sys.exit(1 if fails else 0)
