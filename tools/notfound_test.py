"""Unknown address and same-name search (1.26.194). No request leaves the box: a fake minepoa.com answers every address the
way the real explorer does (200, balance 0, no txs), so only POAScan's archive decides.
* /address/<well-formed, unknown> is a 404 not-found state (no Balance stats, no tabs), never a full 0 POA Agent page.
* Real Agents still render 200: a current-segment Agent, an archived Segment 1 only Agent (one S1 tx), an account row only
  Agent and one the live read shows with a tx.
* Search: address matches carry known, balance and last_ts (API and MCP); the /search list shows Balance and Last active.
Usage: python3 tools/notfound_test.py"""
import json, os, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
LIVE_TX = "poa1" + "L" * 40
class Up(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/api/explorer/address/"):
            a = self.path.rsplit("/", 1)[1]
            txs = [{"id": "e1" * 32, "type": "join", "from_addr": a, "ts": int(time.time()) - 60, "final": 1}] if a == LIVE_TX else []
            b = json.dumps({"address": a, "balance": "0.000000", "txs": txs, "vault_pub": None}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        self.send_response(503); self.send_header("Content-Length", "0"); self.end_headers()
up = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
tmp = tempfile.mkdtemp()
os.environ.update(POASCAN_DB=os.path.join(tmp, "n.db"), POA_BASE=f"http://127.0.0.1:{up.server_address[1]}", POASCAN_INDEXER="0")
import fixture; fixture.seed()
from poascan import db, agentapi as AG, views as V
A1 = fixture.A1
UNK = "poa1cf1a4y6kqddkqj2nf5p5gcabgbpgxcrydkhrqj7crs2k"
S1 = "poa1" + "S" * 40; ACC = "poa1" + "R" * 40; SAME1, SAME2 = "poa1" + "M" * 40, "poa1" + "N" * 40
now = int(time.time())
db.write("INSERT INTO txs(id,type,from_addr,ts,final,first_seen,last_seen,source,segment) VALUES(?,?,?,?,?,?,?,?,?)", ("51" * 32, "join", S1, now - 9 * 86400, 1, now, now, "test", 1))
db.write("INSERT INTO accounts(addr,balance,balance_s,first_seen,last_seen) VALUES(?,?,?,?,?)", (ACC, 0.0, "0.000000", now, now))
for i, a in enumerate((SAME1, SAME2)):
    db.write("INSERT INTO txs(id,type,from_addr,memo,ts,final,first_seen,last_seen,source,segment) VALUES(?,?,?,?,?,?,?,?,?,?)", (f"6{i}" * 32, "join", a, "hosted join: TwinAgent", now - 3600 * (i + 1), 1, now, now, "test", 2))
db.write("INSERT INTO accounts(addr,balance,balance_s,first_seen,last_seen) VALUES(?,?,?,?,?)", (SAME1, 12.5, "12.500000", now, now))

def page(a):
    r = V.address(a); return (r[0], r[1]) if isinstance(r, tuple) else (200, r)
c, h = page(UNK)
check(f"unknown well-formed address: 404 not-found state ({c})", c == 404 and "No Agent at" in h and "Not found" in h)
check("not-found state: no Balance stats or address tabs, links onward", 'class="stats' not in h and 'aria-label="Address sections"' not in h and 'href="/start"' in h)
for name, a in (("current segment Agent", A1), ("archived Segment 1 only Agent", S1), ("account row only Agent", ACC), ("new join seen only by the live read", LIVE_TX)):
    c, h = page(a); check(f"{name} still renders (200)", c == 200 and "No Agent at" not in h and 'aria-label="Address sections"' in h)
check("live_known: explorer default (balance 0, no txs) is not a record", not V.live_known({"balance": "0.000000", "txs": []}) and V.live_known({"balance": "1", "txs": []}) and not V.live_known(None))
r = AG.t_search({"query": "TwinAgent"})["results"]; by = {x["id"]: x for x in r}
check("search API: same-name matches carry known, balance and last_ts", {SAME1, SAME2} <= set(by) and by[SAME1]["known"] and by[SAME1]["balance"] == "12.500000"
      and by[SAME2]["balance"] is None and by[SAME1]["last_ts"] == now - 3600 and by[SAME2]["last_ts"] == now - 7200)
u = AG.t_search({"query": UNK})["results"][0]
check("search API: an unknown address match says known false", u["id"] == UNK and u["known"] is False)
hh = V.search_hits("TwinAgent", r)
check("/search list: Balance and Last active columns", "<th" in hh and "Balance" in hh and "Last active" in hh and "12.50" in hh)
check("no em or en dashes", "\u2014" not in hh + page(UNK)[1] and "\u2013" not in hh + page(UNK)[1])
print("FAILED" if fails else "ALL OK", len(fails)); sys.exit(1 if fails else 0)
