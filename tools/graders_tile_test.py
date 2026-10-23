"""Open epoch Graders tile: what it counts, the official graders served, and the Halted state from /api/notices.
Usage: python3 tools/graders_tile_test.py (uses a temp database, no network)."""
import os, sys, tempfile, time
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, views as V

NOW = time.time()
HALT = {"id": "2026-10-22-grading-halted", "severity": "action", "issued_ts": NOW - 3600, "expires_ts": NOW + 86400,
        "msg": "Mining, joins, answers & attestation earnings fully LIVE. Challenge GRADING is HALTED \u2014 answers accepted & safe."}
RESTORED = {"id": "2026-10-22-restored", "issued_ts": NOW - 7200, "expires_ts": NOW + 86400,
            "msg": "Mining & joins OPEN. Challenge grading + pool payouts resume after the panel-stability fix."}
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

def close(n, ts, served):
    return {"epoch": n, "ts": ts, "pool": 1e9, "rewards": {}, "challenges": {}, "propagation": {}, "basis": {"graders_served": served}}

def seal(i, a, ts):
    db.conn().execute("INSERT INTO txs (id, type, from_addr, ts) VALUES (?, 'grade-sealed', ?, ?)", (f"{i:064x}", a, ts))

def reset(notices):
    A._cache.clear(); db.put_blob("notices", notices)

def main():
    db.init()
    last = NOW - 3900
    db.put_blob("params", {"auto_epoch_seconds": 21600})
    db.put_blob("status", {"epochs_closed": 11})
    db.put_blob("epochs", [close(9, last - 144000, {"poa1" + "N" * 40: 3}), close(10, last, {})])
    seal(1, "poa1" + "G" * 40, last - 300)          # before the close: not counted
    for i, c in enumerate("ABC", 2): seal(i, "poa1" + c * 40, last + 3300 + i)
    seal(9, "poa1" + "A" * 40, last + 3400)           # same sender twice: counted once

    reset({"active": [RESTORED, HALT]})
    o = A.open_epoch()
    check("counts distinct grade-sealed senders since the last close", o["graders"] == 3)
    check("official graders served at the last close is reported", o["graders_served_last"] == 0)
    check("halt notice turns grading_halted on", o["grading_halted"] is True and o["grading_halt_notice"] == HALT["id"])
    h = V.tracker_html()
    check("tile keeps the count", 'data-live="graders"' in h and '>3</span></b>' in h)
    check("tile shows a Halted tag", '<span class="tag warn">Halted</span>' in h)
    check("tooltip names the official count and the notice", "Official graders served at that close: 0." in h and HALT["id"] in h)
    check("live hero carries the same tile", '<span class="tag warn">Halted</span>' in V.live_hero())
    check("no em or en dashes in the tile", "\u2014" not in h and "\u2013" not in h and "&mdash;" not in h)

    reset({"active": [RESTORED]})
    o = A.open_epoch(); h = V.tracker_html()
    check("no halt notice: not halted and no tag", o["grading_halted"] is False and "Halted" not in h)
    check("'resume after' wording is not read as a halt", A.grading_halt() is None)

    reset({"active": [dict(HALT, expires_ts=NOW - 1)]})
    check("an expired halt notice is ignored", A.grading_halt() is None)
    reset({"active": [{"id": "2026-11-01-update", "msg": "Challenge grading is no longer halted."}]})
    check("'no longer halted' is not a halt", A.grading_halt() is None)
    reset({"active": [{"id": "x", "msg": "Challenge grading is halted until further notice."}]})
    check("a halt is read from the message too", A.grading_halt() == "x")
    reset(None)
    check("no notices mirror yet: not halted", A.grading_halt() is None and A.open_epoch()["grading_halted"] is False)
    sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
