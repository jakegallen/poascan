"""Grading list gated checks (1.26.184): minepoa sends no ETag for /api/explorer/grading, so the response headers
(X-Poa-Blob-Age-S) decide whether the body is downloaded; a changed copy is downloaded at most every MIN_FULL_S outside
the close windows; a full read at least every FULL_MAX_S; Stale follows the last check and minepoa's own as_of.
Usage: python3 tools/grading_gate_test.py (temp database, a local HTTP server, no network)."""
import os, sys, tempfile, json, threading, time, http.server
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

STATE = dict(age="30", body=b"{}", served=0)
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "application/json")
        if STATE["age"] is not None: self.send_header("X-Poa-Blob-Age-S", STATE["age"])
        self.send_header("Content-Length", str(len(STATE["body"]))); self.end_headers()
        try: self.wfile.write(STATE["body"]); STATE["served"] += 1
        except Exception: pass

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["POA_BASE"] = f"http://127.0.0.1:{srv.server_address[1]}"
from poascan import db, grading as GR, indexer as I
I.BASE = os.environ["POA_BASE"]

def main():
    db.init()
    NOW = int(time.time())
    # pure decision
    m = dict(last_full=NOW - 600)
    check("no header: read", GR.gate_decision(None, NOW, m, NOW - 1000, None) == "read")
    check("no stored copy: read", GR.gate_decision(30, NOW, m, None, None) == "read")
    check("same copy served: same", GR.gate_decision(1000, NOW, m, NOW - 1000, None) == "same")
    check("within slack: same", GR.gate_decision(1000 - GR.GATE_SLACK_S, NOW, m, NOW - 1000, None) == "same")
    check("rebuilt, last download 10 min ago, far from a close: defer", GR.gate_decision(30, NOW, m, NOW - 1000, NOW + 3 * 3600) == "defer")
    check("rebuilt, near a close: read", GR.gate_decision(30, NOW, m, NOW - 1000, NOW + 600) == "read")
    check("rebuilt, just after a close: read", GR.gate_decision(30, NOW, m, NOW - 1000, NOW - 600) == "read")
    check("rebuilt, last download 20 min ago: read", GR.gate_decision(30, NOW, dict(last_full=NOW - GR.MIN_FULL_S), NOW - 1000, None) == "read")
    check("same copy but no full read in 6 h: read", GR.gate_decision(1000, NOW, dict(last_full=NOW - GR.FULL_MAX_S), NOW - 1000, None) == "read")
    check("header parse", GR.header_age({"X-Poa-Blob-Age-S": "61161"}) == 61161 and GR.header_age({}) is None and GR.header_age({"X-Poa-Blob-Age-S": "x"}) is None)

    # the fetch gate: headers first, body never read
    big = {"as_of": NOW - 30, "rows": [], "stats": {}, "epoch": 8, "pad": "x" * 2_000_000}
    STATE.update(age="30", body=json.dumps(big).encode())
    I._bytes.clear()
    r = I.fetch(GR.PATH, cond=True, gate=lambda h: h.get("X-Poa-Blob-Age-S") == "30")
    check("gate true: NOT_MODIFIED", r is I.NOT_MODIFIED)
    b = sum(v for (mm, ep), v in I._bytes.items() if ep == GR.PATH)
    check("gate true: counts the gated estimate, not the body", b == I.GATE_WIRE_BYTES)
    I._bytes.clear()
    r = I.fetch(GR.PATH, cond=True, gate=lambda h: False)
    check("gate false: body read", isinstance(r, dict) and r["epoch"] == 8)
    b = sum(v for (mm, ep), v in I._bytes.items() if ep == GR.PATH)
    check("gate false: full bytes counted", b > 2_000_000)

    # job end to end against the local server
    doc = {"as_of": NOW - 30, "epoch": 8, "rows": [], "open": [], "stats": {"pending": 0}, "rollups": [{"epoch": 7, "ts": NOW - 3 * 3600}, {"epoch": 6, "ts": NOW - 9 * 3600}],
           "settled": [], "leaderboard": [], "established": [], "trusted": []}
    STATE.update(age="30", body=json.dumps(doc).encode())
    check("first job: full download", GR.job(now=NOW, force=True) is True and GR.meta().get("last_full") == NOW and GR.current()["as_of"] == NOW - 30)
    full0 = GR.meta().get("full")
    STATE.update(age=str(630))   # same copy, 10 min later
    check("same copy: gated, no download", GR.job(now=NOW + 600, force=True) is True and GR.meta().get("full") == full0 and GR.meta().get("last_check") == NOW + 600)
    check("gated check: copy kept, checked_at moves", GR.fetched_at() == NOW and GR.checked_at() == NOW + 600)
    doc2 = dict(doc, as_of=NOW + 1100); STATE.update(age="10", body=json.dumps(doc2).encode())
    GR.job(now=NOW + 1110, force=True)
    m2 = GR.meta()
    check("rebuilt under 20 min after a download, far from a close: deferred", m2.get("deferred") == NOW + 1110 and GR.current()["as_of"] == NOW - 30)
    check("deferred: next check when 20 min have passed", NOW + GR.MIN_FULL_S <= m2["next_at"] <= NOW + GR.MIN_FULL_S + GR.JITTER_S + 60)
    STATE.update(age="200")
    GR.job(now=NOW + 1300, force=True)
    check("after 20 min: the rebuilt copy is downloaded", GR.current()["as_of"] == NOW + 1100 and GR.meta().get("last_full") == NOW + 1300 and not GR.meta().get("deferred"))
    STATE.update(age=None, body=json.dumps(dict(doc2, as_of=NOW + 1350)).encode())
    GR.job(now=NOW + 1400, force=True)
    check("no age header: full download", GR.current()["as_of"] == NOW + 1350)

    # stale rules
    t = GR.checked_at()
    check("fresh after a check", GR.stale_reason(now=t + 60) is None and not GR.stale(now=t + 60))
    check("no check in an hour: stale (check)", GR.stale_reason(now=t + GR.STALE_S + 1) == "check")
    db.put_blob(GR.META, dict(GR.meta(), last_check=NOW + 1350 + GR.UPSTREAM_STALE_S + 100)); GR._cur.clear()
    check("minepoa's copy over 2 h old: stale (upstream)", GR.stale_reason(now=NOW + 1350 + GR.UPSTREAM_STALE_S + 200) == "upstream")
    from poascan import gradingview as GV
    real = time.time
    try:
        time.time = lambda: NOW + 1350 + GR.UPSTREAM_STALE_S + 200
        f = GV.stale_flag()
    finally: time.time = real
    check("Stale tag names minepoa's list age", "Stale" in f and "minepoa&#x27;s grading list is from" in f.replace("&#39;", "&#x27;") or "minepoa's grading list is from" in f)
    import re
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "views.py")).read()
    check("/about explains the gated check", "X-Poa-Blob-Age-S" in src and "at most every 20 minutes" in src)
    check("no em or en dashes in the new copy", not re.search("[\u2013\u2014]", open(GR.__file__).read()))
    srv.shutdown()
    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all passed")); sys.exit(1 if fails else 0)

main()
