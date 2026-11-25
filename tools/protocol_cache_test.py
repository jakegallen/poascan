"""1.26.431: /governance?tab=protocol is warmed, and a last-good pin older than a new
release or params_change is dropped so the page cannot show an older release than /api/v1/protocol.
No upstream read. Usage: python3 tools/protocol_cache_test.py"""
import os, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "pc.db"), POA_BASE="http://127.0.0.1:9", POASCAN_INDEXER="0", POASCAN_HTML_CACHE="1")
import fixture; fixture.seed()
from poascan import htmlcache as HC, protocol as PT

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

HC.register_tabs("/governance", ["protocol", "closes", "proposals", "standing"])
QS = {"tab": ["protocol"]}
k = HC.key("/governance", QS, None, False)
DASH = ("\u2014", "\u2013")

check("Protocol tab is in the warm set", "/governance?tab=protocol" in HC.WARM)
check("Protocol tab is warmed with grace", HC.is_warm("/governance", QS) and HC.grace("/governance", QS) == HC.WARM_GRACE)
check("a filtered Protocol view is not a warm key", not HC.is_warm("/governance", {"tab": ["protocol"], "kind": ["release"]}))

n = [0]
def page():
    n[0] += 1
    return "<html>NEW</html>"

# A pin newer than the seeded release first_seen is still current.
HC._c.clear(); HC._pin.clear()
HC.put(k, "<html>OLD</html>", now=time.time())
check("a current Protocol pin is served without a render", HC.render(k, 60, page) == "<html>OLD</html>" and n[0] == 0)

# A pin as old as, or older than, a new release first_seen must not be served.
ev = int(time.time())
ok_add = PT._add("release:testhash431", ev, "release", ev, version="v-test-431", txid="testhash431")
check("a new release event is recorded once", ok_add is True)
check("recording a release drops the Protocol pin", HC.last(k) is None)
h = HC.render(k, 60, page)
check("the next render is fresh and shows the new copy", h == "<html>NEW</html>" and n[0] == 1)
check("the same release event does not drop a fresh pin", PT._add("release:testhash431", ev, "release", ev, version="v-test-431", txid="testhash431") is False)
check("the fresh pin is still served", HC.render(k, 60, page) == "<html>NEW</html>" and n[0] == 1)

# params_change also drops the pin. Use a pin timestamp in the past so expiry still holds if the hook is skipped.
HC.put(k, "<html>STALE</html>", now=time.time() - 10)
ok_p = PT._add("params:aaa:bbb", int(time.time()), "params_change", int(time.time()), sha_old="aaa", sha_new="bbb",
               detail=dict(changed_keys=["settled_bound_from_epoch"]))
check("a new params change is recorded", ok_p is True)
check("recording a params change drops the Protocol pin", HC.last(k) is None)
check("protocol_pin_expired is false when nothing is stored", HC.protocol_pin_expired(k) is False)
h2 = HC.render(k, 60, page)
check("render after a params change is fresh", h2 == "<html>NEW</html>" and n[0] == 2)

# Safety net: even without going through _add, a stored copy older than the newest event is not served.
HC.put(k, "<html>OLDER</html>", now=ev - 30)
check("protocol_pin_expired is true for a copy older than the event", HC.protocol_pin_expired(k) is True)
n_before = n[0]
h3 = HC.render(k, 60, page)
check("render drops that older copy and renders again", h3 == "<html>NEW</html>" and n[0] == n_before + 1)

# drop_protocol_pins is local only (no fetch) and is scoped to the Protocol tab.
other = HC.key("/governance", {"tab": ["closes"]}, None, False)
HC.put(k, "<html>PROTO</html>")
HC.put(other, "<html>CLOSES</html>")
dropped = HC.drop_protocol_pins()
check("drop_protocol_pins removes the Protocol copy only", dropped >= 1 and HC.last(k) is None and HC.last(other) == "<html>CLOSES</html>")

src = open(HC.__file__, encoding="utf-8").read() + open(PT.__file__, encoding="utf-8").read() + open(__file__, encoding="utf-8").read()
check("no em or en dash", not any(d in src for d in DASH))

print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
