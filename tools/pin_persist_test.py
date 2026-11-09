"""Warm pins survive a restart (1.26.284, E5, poascan/htmlcache.py): the pinned rendered pages are checkpointed to a
SQLite blob on the /data volume and reloaded at boot, before the warm loop runs, so the first visitors after a deploy or
OOM restart get a warm (if slightly stale) copy at once. Bounded in size and age; a reloaded pin keeps its original
timestamp and is keyed exactly as the in-memory pin (oversized, too old, or wrongly keyed entries are skipped). In
process, temp database, no request leaves the box. Usage: python3 tools/pin_persist_test.py"""
import os, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "pp.db"), POASCAN_INDEXER="0", POASCAN_HTML_CACHE="1")
from poascan import db, htmlcache as HC
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

check("enabled with the indexer off via POASCAN_HTML_CACHE=1", HC.ENABLED)
# a warm key (one of WARM) pins when put; a non-warm key does not
k = HC.key("/network", {}, None, False)
check("/network is a warm key", HC._pinned_key(k))
HC.put(k, "<html>net</html>", now=time.time())
check("put stores it as a pin", k in HC._pin and HC.last(k) == "<html>net</html>")

# round trip: persist then clear then reload -> served warm at boot
n = HC.persist_pins(force=True)
check("persist writes the pin to a blob", n >= 1 and db.get_blob(HC.PIN_BLOB)[0]["pins"])
HC._pin.clear(); HC._c.clear()
check("pin gone after a simulated restart", HC.last(k) is None)
loaded = HC.load_pins()
check("load_pins restores the pin", loaded == 1 and HC.last(k) == "<html>net</html>")
check("a reloaded pin is served warm (fresh get hit, no render needed)", HC.get(k, 60) == "<html>net</html>")

# age honesty: the original timestamp is kept, so a reloaded pin is still subject to the TTL (not fresh forever)
HC._pin.clear()
old_ts = time.time() - 100
HC.put(k, "<html>old</html>", now=old_ts)
HC.persist_pins(force=True); HC._pin.clear()
HC.load_pins()
check("reloaded pin keeps its original age (about 100 s), not reset to now", 95 <= HC.age(k) <= 140)
check("an aged reloaded pin is not served as fresh under a short TTL", HC.get(k, 30) is None and HC.last(k) == "<html>old</html>")

# oversized entry is skipped on load (crafted blob: a body over the per pin cap)
big = "z" * (HC.MAX_BYTES // 8 + 1000)
bad_key = HC._key_to_list(HC.key("/governance", {}, None, False))   # a real warm key, but an oversized body
db.put_blob(HC.PIN_BLOB, {"v": 1, "saved_at": time.time(), "pins": [{"k": bad_key, "ts": time.time(), "html": big}]})
HC._pin.clear(); HC.load_pins()
check("an oversized reloaded pin is skipped", HC.last(HC.key("/governance", {}, None, False)) is None)

# too old is skipped
oldk = HC._key_to_list(HC.key("/about", {}, None, False))
db.put_blob(HC.PIN_BLOB, {"v": 1, "saved_at": time.time(), "pins": [{"k": oldk, "ts": time.time() - HC.PIN_MAX_AGE_S - 10, "html": "<html>a</html>"}]})
HC._pin.clear(); HC.load_pins()
check("a pin older than PIN_MAX_AGE_S is skipped", HC.last(HC.key("/about", {}, None, False)) is None)

# a non warm (wrongly keyed) entry is never reloaded as a pin
notwarm = ["/address/poa1xyz", [], None, False]
invalid = {"k": ["/network", "notalist", None, False], "ts": time.time(), "html": "<html>x</html>"}
db.put_blob(HC.PIN_BLOB, {"v": 1, "saved_at": time.time(),
                          "pins": [{"k": notwarm, "ts": time.time(), "html": "<html>addr</html>"}, invalid,
                                   {"k": None, "ts": time.time(), "html": "<html>y</html>"}]})
HC._pin.clear(); got = HC.load_pins()
check("a non warm key is not reloaded as a pin, and malformed entries are skipped", got == 0 and HC.last(HC.key("/address/poa1xyz", {}, None, False)) is None)

# total size cap keeps the freshest pins first
HC._pin.clear()
cap = HC.PIN_PERSIST_MAX_BYTES; HC.PIN_PERSIST_MAX_BYTES = 4000
for i, p in enumerate(["/network", "/governance", "/about"]):
    HC.put(HC.key(p, {}, None, False), "q" * 1800, now=time.time() + i)   # /about is freshest
saved = HC.persist_pins(force=True)
check("the total persisted size is capped (freshest kept)", saved <= 2 and db.get_blob(HC.PIN_BLOB)[0]["pins"][0]["k"][0] == "/about")
HC.PIN_PERSIST_MAX_BYTES = cap

import re
src = open(os.path.join(ROOT, "poascan", "htmlcache.py"), encoding="utf-8").read()
check("no em or en dash in the source or this test", not re.search(r"[\u2013\u2014]", src + open(__file__, encoding="utf-8").read()))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
