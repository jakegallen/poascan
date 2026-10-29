"""Settled answer outcomes (1.26.224).

A close record lists an answer in basis.settled[] when its grading ends. With a jury it passed or failed. The engine
also settles answers that waited too long and never got a jury: those rows carry expired: true, passed: false and
an empty jury[]. POAScan reads them as Expired, no jury, never as a failure: no juror judged the answer. Pass rates are
over juried rows only (passed plus failed). Method: /about#expired."""

PASSED, FAILED, EXPIRED = "passed", "failed", "expired_no_jury"
LABEL = {PASSED: "Passed", FAILED: "Failed", EXPIRED: "Expired, no jury"}
SHORT = {PASSED: "Passed", FAILED: "Failed", EXPIRED: "Expired"}
TAG = {PASSED: "ok", FAILED: "bad", EXPIRED: ""}
METHOD = "/about#expired"

def no_jury(s):
    """True for a settled row that expired with no jury: not passed, expired true and an empty jury. A row the engine
    marks expired that still lists jurors was judged, so it stays a jury outcome."""
    s = s or {}
    return not s.get("passed") and s.get("expired") is True and not (s.get("jury") or [])

def of(s):
    """passed, failed (a jury failed it) or expired_no_jury, for one basis.settled[] row (or minepoa's grading list row)."""
    s = s or {}
    if s.get("passed"): return PASSED
    return EXPIRED if no_jury(s) else FAILED

def counts(rows):
    """{passed, failed, expired_no_jury} over basis.settled[] rows."""
    c = {PASSED: 0, FAILED: 0, EXPIRED: 0}
    for s in rows or []: c[of(s)] += 1
    return c

def rate(passed, juried):
    """Pass rate over juried rows; None with no juried row."""
    return passed / juried if juried else None

def tag(o, close=None, short=False):
    """A status tag. short: Expired with the full label as its tooltip (narrow tables)."""
    at = f" · {close}" if close is not None else ""
    if o == EXPIRED and short:
        return f'<span class="tag" title="{LABEL[EXPIRED]}">{SHORT[EXPIRED]}{at}</span>'
    return f'<span class="tag {TAG.get(o, "")}">{LABEL.get(o, o)}{at}</span>'
