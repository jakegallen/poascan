"""1.26.266: minepoa retired /api/explorer/grading on 2026-11-01, answering 200 with {"retired": true, "note": "..."}.

POAScan must read that as a Retired state, never Down and never degraded, back the read off to 6 h, and stop showing the
stale last copy's numbers. This test is self contained: no request leaves the box and no database is touched. The live
sample below is the exact body read from minepoa.com on 2026-11-05.
Usage: python3 tools/grading_retired_test.py"""
import os, sys
os.environ["POASCAN_SEGMENTS"] = "1"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import strain as ST, grading as GR, routehealth as RH, indexer as IX
from poascan import views2 as V2

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

PATH = "/api/explorer/grading"
# exact body minepoa.com returned on 2026-11-05 (HTTP 200)
LIVE = {"retired": True, "note": "The explorer grading view was retired on 2026-11-01; a replacement is planned."}
REAL = {"rows": [], "stats": {"pending": 0}, "epoch": 44, "as_of": 1}   # a valid (not retired) shape

# ---- detection ----------------------------------------------------------------------------------------------------
hit = ST.detect(PATH, LIVE)
check("the retired body is detected", bool(hit))
check("it is kind=retired", ST.is_retired(hit))
check("it is not a halt", not ST.is_halt(hit))
check("the note text is carried (for the log line, never shown as a strain notice)", "retired" in (hit or {}).get("text", "").lower())
check("{\"retired\": false} is not retired", not ST.is_retired(ST.detect(PATH, {"retired": False, "rows": [], "stats": {}, "epoch": 1}) or {}))
check("a valid grading body is not flagged at all", ST.detect(PATH, REAL) is None)
check("a valid grading body is not retired", not ST.is_retired(ST.detect(PATH, REAL) or {}))

# ---- the exception is distinct but still a Busy --------------------------------------------------------------------
check("indexer.Retired is a Busy subclass", issubclass(IX.Retired, IX.Busy))
check("indexer.Retired is not Notice", not issubclass(IX.Retired, IX.Notice))

# ---- grading.retired_at / is_retired over the stored meta ----------------------------------------------------------
orig_meta = GR.meta
try:
    GR.meta = lambda: {"retired": 1000, "last_full": 500}
    check("retired while last_full predates the marker", GR.is_retired() and GR.retired_at() == 1000)
    GR.meta = lambda: {"retired": 1000, "last_full": 2000}
    check("a later full copy (a replacement) clears retired", not GR.is_retired())
    GR.meta = lambda: {}
    check("no marker means not retired", not GR.is_retired())
    GR.meta = lambda: {"retired": 1000}
    check("retired with no last_full yet still reads retired", GR.is_retired())
finally:
    GR.meta = orig_meta

# ---- 6 h back-off, not the 30 min failure back-off ----------------------------------------------------------------
check("the retired read backs off to 6 h", GR.RETIRED_RETRY_S == 21600)

# ---- the headline: Retired never flips OK to Partial and is not listed as degraded ---------------------------------
feeds_ok = [{"label": "Grading list", "state": "Retired", "last_ok": 123, "retired": True},
            {"label": "Tx list", "state": "OK", "last_ok": 123}]
state, ok, core_bad, deg = RH.headline("Live", [], feeds_ok)
check("chain live + grading Retired stays OK", state == "OK")
check("Retired grading list is not in the degraded list", "Grading list" not in deg)
# a genuinely Down non-core feed still degrades, so the exclusion is specific to Retired
feeds_down = [{"label": "Grading list", "state": "Down", "last_ok": 123}, {"label": "Tx list", "state": "OK", "last_ok": 123}]
_, _, _, deg2 = RH.headline("Live", [], feeds_down)
check("a Down grading list would still be listed (control)", "Grading list" in deg2)

# ---- the tag table renders Retired without a KeyError --------------------------------------------------------------
check("FEED_TAG has a Retired entry", "Retired" in V2.FEED_TAG)

# ---- no em or en dashes in the new user-facing copy ---------------------------------------------------------------
import poascan.gradingview as GV
src = open(os.path.join(ROOT, "poascan", "gradingview.py")).read()
line = [l for l in src.splitlines() if "retired its grading list" in l]
check("the grading page has a Retired message", bool(line))
check("no em or en dash in the Retired copy", line and not any(d in line[0] for d in ("\u2014", "\u2013")))

print("\n" + ("all ok" if not fails else f"{len(fails)} FAILED: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
