"""Injectable clock seam (test-only). now() is the wall clock in production (defaults to time.time()); tests patch
poascan.clock.now to a fixed epoch so time-fragile assertions (the milestones chart range around the Oct 2026 upgrade
events) stay deterministic instead of rotting as the calendar advances. Prod behaviour is unchanged: callers that want
real time still get it. Keep this tiny and do not route unrelated time usage through it."""
import time

def now():
    """Seconds since the epoch, as a float. Patched by tests; real time otherwise."""
    return time.time()
