"""Pending row interning keys rows by repr (1.26.365) and groups exactly the rows the json.dumps key grouped.

Run: python3 tools/intern_test.py (no db, no network).
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import closestore as CS

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)

def old(p):
    seen = {}
    for k, v in p.items():
        if isinstance(v, dict):
            o = seen.setdefault(json.dumps(v), v)
            if o is not v: p[k] = o
    return p

raw = json.dumps({
    "a": {"kind": "q", "panel": ["x", "y"], "originalPassed": True, "since": 3, "grades": [1, 2]},
    "b": {"kind": "q", "panel": ["x", "y"], "originalPassed": True, "since": 3, "grades": [1, 2]},
    "c": {"kind": "q", "panel": ["x", "y"], "originalPassed": True, "since": 3, "grades": [2, 1]},
    "d": {"kind": "q", "panel": [], "originalPassed": 1, "since": 3, "grades": []},
    "e": {"kind": "q", "panel": [], "originalPassed": True, "since": 3, "grades": []},
    "f": {"kind": "q", "panel": [], "originalPassed": True, "since": 3.0, "grades": []},
    "g": {"since": 3, "kind": "q", "panel": [], "originalPassed": True, "grades": []},
    "h": "not a row", "i": None,
})
a = old(json.loads(raw)); b = CS._interned(json.loads(raw))
ok(a == b, "same values as the json.dumps key")
groups = lambda p: sorted(sorted(k for k in p if id(p[k]) == i) for i in {id(v) for v in p.values()})
ok(groups(a) == groups(b), "same rows share one dict")
ok(b["a"] is b["b"] and b["a"] is not b["c"], "equal rows shared, different rows kept apart")
ok(b["d"] is not b["e"] and b["e"] is not b["f"], "1 vs True and 3 vs 3.0 stay distinct, as before")
ok(CS._interned(None) is None and CS._interned([1]) == [1], "non dict pending passes through")
print("FAIL:" if fails else "all ok", fails if fails else "")
sys.exit(1 if fails else 0)
