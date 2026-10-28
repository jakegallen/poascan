"""Earn check in production mode (1.26.195): POAScan's own archive in process, never minepoa.com. A fixture DB, a fake
minepoa.com that counts requests, and the real server: /help?address=, /api/v1/earn/<addr> and MCP get_earn_check.
Usage: python3 tools/earn_local_test.py"""
import json, os, sys, tempfile, threading, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
SEEN = []
class Up(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        SEEN.append(self.path); self.send_response(503); self.send_header("Content-Length", "0"); self.end_headers()
up = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "l.db"), POA_BASE=f"http://127.0.0.1:{up.server_address[1]}", POASCAN_INDEXER="0")
os.environ.pop("POASCAN_EARN_SOURCE", None); os.environ.pop("POASCAN_EARN_FORUM_FIXTURE", None)
import fixture; fixture.seed()
from poascan import server as SV, agentapi as AG, earn as EA
check("production mode: no preview source, LabLeak mirror reader", not EA.SOURCE and not EA.FORUM_FIXTURE)
srv = SV.Server(("127.0.0.1", 0), SV.H); base = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(p):
    try: r = urllib.request.urlopen(base + p, timeout=60); return r.status, r.read().decode("utf-8", "replace"), r.headers
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace"), e.headers
n0 = len(SEEN)
c, b, h = get(f"/api/v1/earn/{fixture.A1}"); d = json.loads(b) if c == 200 else {}
check(f"/api/v1/earn: 200 with disclaimer ({c})", c == 200 and d.get("disclaimer") == EA.DISCLAIMER)
check("history from the stored close records", d.get("history") and all("close" in r and "lines" in r for r in d["history"]) and d["history"][-1]["close"] >= d["history"][0]["close"])
check("grading and ways in the result", isinstance(d.get("grading"), dict) and [w["key"] for w in d.get("ways") or []][:3] == ["answers", "attest", "grading"])
c, b, _ = get(f"/help?address={fixture.A1}")
check(f"/help?address=: 200 with history, Grading, Ways to earn and the disclaimer ({c})", c == 200 and 'id="history"' in b and 'id="grading"' in b and "Ways to earn" in b and "Unofficial guidance." in b)
c, b, _ = get(f"/help?address={fixture.A1}&sort=paid&dir=asc")
check("sorted history renders", c == 200 and 'aria-sort="ascending"' in b)
r = AG.call_tool("get_earn_check", {"address": fixture.A1}) if hasattr(AG, "call_tool") else AG.t_earn({"address": fixture.A1})
r = r if isinstance(r, dict) else {}
check("MCP get_earn_check carries the disclaimer", (r.get("disclaimer") or json.dumps(r).find("Unofficial guidance") >= 0))
check(f"no minepoa.com request for any of it ({len(SEEN) - n0})", len(SEEN) == n0)
c, b, _ = get("/about")
check("methodology at /about#earn-check", c == 200 and 'id="earn-check"' in b and "newcomer dampening" in b)
print("FAILED" if fails else "ALL OK", len(fails)); sys.exit(1 if fails else 0)
