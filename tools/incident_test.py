"""Regression tests for the 2026-10-22 outage (CPU throttled shared vCPU, guard restart loop).
* history.grading_index() is cached: a second call with the same parsed epochs blob returns the same object without
  re-reading the blob, and a new blob (new ts) rebuilds it.
* guard: /healthz failures while the VM is CPU throttled (steal-dominant) do not trigger the restart that a plain hang
  does; a long throttled run still exits; a success resets both counters; steal_share reads /proc/stat deltas.
Usage: python3 tools/incident_test.py"""
import os, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_DB", os.path.join(tempfile.mkdtemp(), "t.db"))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import analytics as A, history as HI, guard as GD

blob = [{"epoch": 1, "ts": 100, "basis": {"pending": {"t1": {"kind": "short", "since": 1, "panel": ["g1"]}}, "settled": []}},
        {"epoch": 2, "ts": 200, "basis": {"pending": {}, "settled": [{"answer": "t1", "passed": True, "jury": [{"grader": "g2"}]}]}}]
calls = {"raw": 0, "sorted": 0}
cur = {"v": blob, "ts": 1}
def fake_raw():
    calls["raw"] += 1; A._epochs["v"] = cur["v"]; A._epochs["ts"] = cur["ts"]; return cur["v"]
A.epochs_raw = fake_raw
A.params = lambda: {}
real_sorted = sorted
def counting_sorted(*a, **k):
    calls["sorted"] += 1; return real_sorted(*a, **k)
HI.sorted = counting_sorted   # grading_index's full scan starts with sorted(raw, ...)

v1 = HI.grading_index(); v2 = HI.grading_index()
check("grading_index: second call returns the cached object", v1 is v2)
check("grading_index: the blob is scanned once for two calls", calls["sorted"] == 1)
check("grading_index: content", v1["rec"]["t1"]["s"][1] is True and "t1" in v1["by"]["g1"] and "t1" in v1["by"]["g2"] and v1["last"] == 2)
cur["v"] = [dict(e) for e in blob]; cur["ts"] = 2
v3 = HI.grading_index()
check("grading_index: a new blob rebuilds", v3 is not v1 and calls["sorted"] == 2)
check("grading_index: cached again after rebuild", HI.grading_index() is v3 and calls["sorted"] == 2)
del HI.sorted

# guard counters
GD.state.update(fails=0, throttled_fails=0)
r = [GD.on_check(False, None) for _ in range(GD.HANG_FAILS)]
check("guard: plain hang exits after HANG_FAILS", r[-1] is not None and all(x is None for x in r[:-1]))
GD.state.update(fails=0, throttled_fails=0)
r = [GD.on_check(False, 0.9) for _ in range(GD.HANG_FAILS * 3)]
check("guard: throttled failures do not restart", all(x is None for x in r) and GD.state["fails"] == 0)
r = [GD.on_check(False, 0.9) for _ in range(GD.THROTTLED_FAILS)]
check("guard: a long throttled run still exits", any(x is not None for x in r))
GD.on_check(True, 0.9)
check("guard: success resets both counters", GD.state["fails"] == 0 and GD.state["throttled_fails"] == 0)
check("guard: low steal counts as a hang", GD.on_check(False, 0.1) is None and GD.state["fails"] == 1)
GD.state.update(fails=0, throttled_fails=0)

# 2026-10-26: the memory guard ran a full gc.collect() on every 15 s check while RSS sat over RSS_TRIM_MB (always, at a
# ~340 MB working set), the largest CPU user in the process; trims are now once a minute and full collections every GC_EVERY s
check("guard: no trim on back to back checks", not GD.due_trim(1000.0, 1000.0 - GD.CHECK_EVERY))
check("guard: trim once TRIM_EVERY has passed", GD.due_trim(1000.0, 1000.0 - GD.TRIM_EVERY) and GD.TRIM_EVERY >= 60)
check("guard: RSS over RSS_TRIM_MB alone forces no full gc", not GD.due_gc(1000.0, 1000.0 - GD.TRIM_EVERY, GD.RSS_TRIM_MB + 50))
check("guard: full gc every GC_EVERY s", GD.due_gc(1000.0, 1000.0 - GD.GC_EVERY, 100) and GD.GC_EVERY >= 300)
check("guard: full gc at once over RSS_EXIT_MB", GD.due_gc(1000.0, 999.0, GD.RSS_EXIT_MB + 1))
calls = {"gc": 0}; _gc = GD.gc.collect; GD.gc.collect = lambda *a: calls.__setitem__("gc", calls["gc"] + 1)
GD.trim(); check("guard: trim() without full skips gc.collect", calls["gc"] == 0)
GD.trim(True); check("guard: trim(full=True) collects", calls["gc"] == 1)
GD.gc.collect = _gc
import inspect
src = inspect.getsource(GD._watch)
check("guard: the watch loop no longer trims on every check over RSS_TRIM_MB", "m > RSS_TRIM_MB or" not in src and "due_trim(" in src and "due_gc(" in src)

d = tempfile.mkdtemp(); p1, p2 = os.path.join(d, "a"), os.path.join(d, "b")
open(p1, "w").write("cpu  100 0 50 800 0 0 0 50 0 0\ncpu0 1 2 3\n")
open(p2, "w").write("cpu  110 0 52 800 0 0 0 138 0 0\ncpu0 1 2 3\n")
a, b = GD.cpu_times(p1), GD.cpu_times(p2)
check("guard: cpu_times parses /proc/stat", a == (50, 1000) and b == (138, 1100))
check("guard: steal_share", abs(GD.steal_share(a, b) - 0.88) < 1e-9 and GD.steal_share(None, b) is None and GD.steal_share(b, a) is None)
check("guard: cpu_times on a missing file is None", GD.cpu_times(os.path.join(d, "missing")) is None)

print("\n%d failure(s)" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
