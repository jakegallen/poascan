"""Watchdog tells CPU-busy from hung (1.26.284, S1, poascan/guard.py): a legitimately slow render on the one dedicated
core must not read as a hang. While heavy serving slots are in use the self-check gets a longer timeout, and a miss
counts toward a much larger BUSY_FAILS rather than the small HANG_FAILS; but a genuine hang still exits (stuck renders
keep the slots busy, so BUSY_FAILS is reached), and a real hang with no heavy work in flight still exits after HANG_FAILS.
No network, no database. Usage: python3 tools/busy_watchdog_test.py"""
import os, sys, inspect
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import guard as GD
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

check("the busy self-check timeout is longer than the hang timeout", GD.BUSY_SELF_TIMEOUT > GD.HANG_SELF_TIMEOUT)

# heavy_busy reflects the heavy-slot occupancy
b0 = GD.heavy_busy()
got = GD.slots.acquire(blocking=False)
check("heavy_busy rises when a heavy slot is taken", GD.heavy_busy() == b0 + 1)
if got: GD.slots.release()
check("heavy_busy returns to baseline when the slot is released", GD.heavy_busy() == b0)

# a miss while heavy renders are in flight does not count toward HANG_FAILS
GD.state.update(fails=0, throttled_fails=0, busy_fails=0)
r = [GD.on_check(False, None, busy=2) for _ in range(GD.HANG_FAILS + 1)]
check("busy misses never trip the small HANG_FAILS", all(x is None for x in r) and GD.state["fails"] == 0 and GD.state["busy_fails"] == GD.HANG_FAILS + 1)

# a sustained busy run still exits (a genuine hang that keeps the slots busy is not immortal)
GD.state.update(fails=0, throttled_fails=0, busy_fails=0)
r = [GD.on_check(False, None, busy=1) for _ in range(GD.BUSY_FAILS)]
check("a sustained busy run still exits at BUSY_FAILS", any(x is not None for x in r))

# a busy but answering check resets the busy counter
GD.state.update(fails=0, throttled_fails=0, busy_fails=5)
GD.on_check(True, None, busy=3)
check("a busy but answering check resets busy_fails", GD.state["busy_fails"] == 0 and GD.state["fails"] == 0)

# a real hang with no heavy work in flight still exits after HANG_FAILS (unchanged)
GD.state.update(fails=0, throttled_fails=0, busy_fails=0)
r = [GD.on_check(False, None, busy=0) for _ in range(GD.HANG_FAILS)]
check("a real hang (not busy, not throttled) still exits after HANG_FAILS", r[-1] is not None and all(x is None for x in r[:-1]))

# throttled exemption is untouched
GD.state.update(fails=0, throttled_fails=0, busy_fails=0)
check("a throttled miss still does not count as a hang", GD.on_check(False, 0.9, busy=0) is None and GD.state["fails"] == 0 and GD.state["throttled_fails"] == 1)

# the watch loop chooses the timeout by heavy_busy and passes busy to on_check
src = inspect.getsource(GD._watch)
check("the watch loop picks the timeout by heavy_busy and passes busy to on_check",
      "heavy_busy()" in src and "BUSY_SELF_TIMEOUT" in src and "on_check(ok, st, busy)" in src)

# heavy_busy fails safe to 0 (no exemption) when the semaphore internals are unexpected: strict, never soft
_sl = GD.slots; GD.slots = object()
check("heavy_busy on an unexpected object is 0 (strict, never soft)", GD.heavy_busy() == 0)
GD.slots = _sl

# telemetry surfaces the new counters
t = GD.telemetry()
check("telemetry exposes busy_fails and heavy_busy", "busy_fails" in t and "heavy_busy" in t)

import re
gsrc = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "guard.py"), encoding="utf-8").read()
check("no em or en dash", not re.search(r"[\u2013\u2014]", gsrc + open(__file__, encoding="utf-8").read()))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
