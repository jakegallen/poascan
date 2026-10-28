"""Grading halt rule (1.26.201): no grade seal for 15 min while 20+ answers land marks the Grading route Stale; 30 min
turns it Down since the newest seal; seals resuming (grading confirmed open) clear it after two good reads. Fewer answers
never trigger it. The keyless grade route read is a bare GET (no key, query, body or auth header), maps 503 with the halt
text to Halted, a JSON 401 to Open and a 5xx or no answer to a failing read, and lands in the hosted grading entry.
Temp database, no request leaves the box. Usage: python3 tools/sealgap_test.py"""
import os, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "sg.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
from poascan import db, routewatch as RW, maint as M, hosted as HO
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

T0 = 1_800_000_000; n = [0]
def tx(typ, ts):
    n[0] += 1; db.write("INSERT INTO txs(id, type, ts) VALUES(?,?,?)", (f"{typ}{n[0]}", typ, ts))
SEALS = []
def seal(ts): tx("grade-sealed", ts); SEALS.append(ts)
def gs(now=None):
    import time as _t
    now = int(now or _t.time()); rec = [t for t in SEALS if now - 1800 < t <= now]
    return dict(state="open" if len(rec) >= 2 else "unconfirmed", last_seal_at=max([t for t in SEALS if t <= now], default=None))
M.grading_state = gs
RW.ROUTES = [("grading", "Grading", dict(seals=True))]
import time as _time
def run(a, b, answers_every=None):
    for now in range(a, b, 60):
        if answers_every: [tx("challenge", now + k) for k in range(0, 60, answers_every)]
        _time.time = lambda v=now: v
        RW.job(now)
    return RW.state(b - 60)["routes"][0]

for k in range(0, 600, 30): seal(T0 + k); tx("challenge", T0 + k)
g = run(T0 + 600, T0 + 660)
check(f"seals landing: Open ({g['state']})", g["state"] == "open" and not g["stale"])
last = T0 + 570
g = run(T0 + 660, last + 16 * 60, answers_every=20)
check(f"16 min without seals, answers landing: Stale with a reason ({g['stale_reason']})", g["state"] == "open" and g["stale"] and __import__("re").search(r"No grade seals for 1[56] min while \d+ answers landed", g["stale_reason"] or "") is not None)
check("seal_gap in the row: level stale, answers counted", (g["seal_gap"] or {}).get("level") == "stale" and g["seal_gap"]["answers"] >= 20)
g = run(last + 16 * 60, last + 32 * 60, answers_every=20)
check(f"over 30 min: Down since the newest seal ({g['since_ts'] - last if g['since_ts'] else None} s after it)", g["state"] == "down" and g["since_ts"] == last and "No grade seals" in (g["down_reason"] or ""))
check("Down shows in halted ids", "grading" in RW.halted_ids())
for k in (0, 60, 120): seal(last + 32 * 60 + k)
g = run(last + 32 * 60 + 30, last + 36 * 60, answers_every=20)
check(f"seals resume: Open again after two good reads ({g['state']}, ended {g['ended'][:1]})", g["state"] == "open" and g["ended"] and g["ended"][0]["state"] == "down")

# a quiet network: few answers, no seals for an hour, never Down
db.write("DELETE FROM txs"); SEALS.clear(); db.put_blob(RW.BLOB, {})
T1 = T0 + 100_000
for k in range(0, 600, 30): seal(T1 + k)
g = run(T1 + 600, T1 + 4200, answers_every=None)
for k in range(5): tx("challenge", T1 + 1000 + k * 300)
g = run(T1 + 4200, T1 + 4300)
check(f"few answers (under {RW.GAP_MIN_ANSWERS}): no Stale, no Down ({g['state']}, {g['stale']})", g["state"] == "open" and not g["stale_reason"])

# ---- keyless grade route read
rq = HO.grade_request()
check("grade read: GET, no query, no body, no key or auth header", rq.get_method() == "GET" and "?" not in rq.full_url and rq.data is None
      and not any(h.lower() in ("authorization", "x-api-key", "cookie") for h in rq.headers) and rq.full_url.endswith("/api/hosted/grade"))
db.put_blob(HO.BLOB, {}); db.put_blob(HO.GRADE_BLOB, {})
HO.grade_job(now=T0, get=lambda: (503, b'{"error":"grading is temporarily halted"}'), force=True)
check("503 with the halt text: hosted grading paused", HO.current(T0)["grading"]["state"] == "paused")
HO.grade_job(now=T0 + 900, get=lambda: (401, b'{"error":"missing key"}'), force=True)
check("JSON 401: open", HO.current(T0 + 900)["grading"]["state"] == "open")
HO.grade_job(now=T0 + 1800, get=lambda: (502, b"bad gateway"), force=True)
c = HO.current(T0 + 1800)["grading"]
check("502 without the halt text: a failing read (slow), last clear state kept", c["slow"] and c["state"] == "open")
b = db.get_blob(HO.GRADE_BLOB)[0]
check(f"next read in about 15 min ({b['next_at'] - (T0 + 1800)} s)", 840 <= b["next_at"] - (T0 + 1800) <= 960)
HO.grade_job(now=T0 + 1900, get=lambda: (_ for _ in ()).throw(AssertionError("too soon")))
check("no read before next_at", True)
# ---- Tx lookup covered by the fast index reads Degraded; 24 h strip
from poascan import fastindex as FX, views2 as V2, ui as UI
RW.ROUTES = [("grading", "Grading", dict(seals=True)), ("tx_lookup", "Tx lookup", dict(fetch=("/api/explorer/tx/:id",)))]
d = db.get_blob(RW.BLOB)[0] or {}; d.setdefault("routes", {})["tx_lookup"] = dict(state="down", since=T0, as_of=T0 + 60, bad=2); db.put_blob(RW.BLOB, d)
_en, _fd = FX.enabled, FX.feed
FX.enabled = lambda: True; FX.feed = lambda now=None: dict(state="OK", lag_s=120)
tl = next(r for r in RW.state(T0 + 120)["routes"] if r["id"] == "tx_lookup")
check(f"Tx lookup down with the fast index OK: Degraded, covered_by fast index, state kept ({tl['word']}, {tl['state']})", tl["word"] == "Degraded" and tl["covered_by"] == "fast index" and tl["state"] == "down")
check("halt word: degraded", M.halt_word([tl]) == "degraded" and M.halt_word([tl, dict(state="halted")]) == "halted or degraded")
FX.feed = lambda now=None: dict(state="Lagging", lag_s=4000)
tl = next(r for r in RW.state(T0 + 120)["routes"] if r["id"] == "tx_lookup")
check("fast index behind: Tx lookup stays Down", tl["word"] == "Down" and tl["covered_by"] is None)
FX.enabled, FX.feed = _en, _fd
for k in range(0, 3 * 3600, 600): RW.job(T0 + 200_000 + k)
h = RW.history("grading", T0 + 200_000 + 3 * 3600)
check(f"24 h history: {RW.HIST_N} slots of {RW.HIST_S // 60} min, filled for the passes run", len(h) == RW.HIST_N and sum(1 for _, v in h if v) >= 10)
_time.time = lambda: T0 + 200_000 + 3 * 3600
html = V2.routes_html(RW.state(T0 + 200_000 + 3 * 3600))
check("Routes card: a strip per route with an accessible label", html.count('class="rstrip"') >= 1 and 'aria-label="Grading, last 24 hours"' in html)

print("\n%d failed" % len(fails) if fails else "\nall passed"); sys.exit(1 if fails else 0)
