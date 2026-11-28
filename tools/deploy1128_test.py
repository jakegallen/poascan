"""1.26.437 deploy and load fixes. (1) main() starts answering before the indexer boot work, the txs micro warm and the
chart warm, and times each phase into BOOT (/api/health boot). (2) /governance?level=directory and the other level chips
are kept like a warmed page; Directory is in WARM with a 300 s TTL. (3) /chain?tab=pending|grading and /chain/txs?type=<a
known type> are kept like a warmed page (a fixed set: an unknown type is not); Grading is in WARM with a 120 s TTL.
(5) A shed in the first POASCAN_WARMUP_S after the server starts listening gets the Warming up card (HTML) or a plain
text warming line (API), Retry-After 10, X-POAScan-Warming; outside that window the Busy card is unchanged.
Run: python3 tools/deploy1128_test.py (temp db, in-process, no network)."""
import os, re, sys, tempfile, time
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "dep.db"), POASCAN_INDEXER="0", POASCAN_HTML_CACHE="1", POASCAN_MAX_WORKERS="4",
                  POASCAN_SERVE_RESERVE="2", POASCAN_HEAVY_WAIT="0.2", POA_BASE="http://127.0.0.1:9")
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, ".."); sys.path.insert(0, ROOT)
from poascan import guard as GD, db, htmlcache as HC, segments as SG
import poascan.server as SV
fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)
db.init()
HUMAN = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
class Req(SV.H):
    def __init__(self, path, cmd="GET"):
        self.path = path; self.command = cmd; self.headers = {"User-Agent": HUMAN}; self.sent = []
    def send(self, code, body="", ctype="text/html; charset=utf-8", extra=None, pre=None):
        self.sent.append((code, body, ctype, dict(extra or {}))); return code

# (1) boot order
src = open(os.path.join(ROOT, "poascan", "server.py")).read(); m = src[src.index("def main():"):]
ok(m.index("Server((host, port), H)") < m.index("I.start(") and m.index("serve_forever") < m.index("I.start(") and m.index("serve_forever") < m.index("warm_txs_micro)"),
   "main listens before the indexer start and the txs micro warm")
ok(m.index("HC.load_pins") < m.index("serve_forever"), "the last good pages reload before the server answers")
b = SV.boot_state()
ok(set(b) == {"serving_at", "done_at", "phases_s", "warming"} and b["warming"] is False, "boot state shape; not warming when main never ran")

# (2) Governance levels
for lv in HC.GOV_LEVELS: ok(HC.is_warm("/governance", {"level": [lv]}), f"/governance?level={lv} is kept like a warmed page")
ok(not HC.is_warm("/governance", {"level": ["zzz"]}) and not HC.is_warm("/governance", {"level": ["directory"], "sort": ["name"]}), "unknown level or a sorted copy is not pinned")
ok("/governance?level=directory" in HC.WARM and HC.ttl("/governance", {"level": ["directory"]}) == 300, "Directory warmed, 300 s TTL")

# (3) Chain
ok(all(HC.is_warm("/chain/txs", {"type": [t]}) for t in HC.TX_TYPES) and HC.is_warm("/chain", {"tab": ["grading"]}) and HC.is_warm("/chain", {"tab": ["pending"]}), "Chain tabs and tx type filters are pinned")
ok(not HC.is_warm("/chain/txs", {"type": ["random1"]}) and not HC.is_warm("/chain/txs", {"type": ["transfer"], "page": ["3"]}), "unknown type or a later page is not pinned")
ok("/chain?tab=grading" in HC.WARM and HC.ttl("/chain", {"tab": ["grading"]}) == 120 and HC.ttl("/chain", {}) == HC.DEFAULT_TTL, "Grading warmed, 120 s TTL; /chain unchanged")
seg = SG.selected()
k = HC.key("/chain/txs", {"type": ["transfer"]}, seg, False)
HC.put(k, "<html>OLD-TRANSFERS</html>", now=time.time() - 7200)
ok(HC.last(k) == "<html>OLD-TRANSFERS</html>" and k in HC._pin, "a type filter page is stored as a pin")

# (5) Warming up card
W = SV.WARM_HTML
ok("Warming up" in W and "Busy" not in W and "Back in a moment" in W and 'http-equiv="refresh"' in W and len(W) < 4000, "warming card is small and says Warming up")
ok(not re.search("[\u2013\u2014]", W) and "<script" not in W and "https://" not in W, "warming card copy rules: no dashes, no script, no outside request")
heavy, cheap = [], []
while GD.slots.acquire(blocking=False): heavy.append(1)
while GD.cheap is not None and GD.cheap.acquire(blocking=False): cheap.append(1)
HC._c.clear(); HC._pin.clear(); HC._bytes[0] = 0
r = Req("/network?tab=charts"); r._gated(lambda: "X"); code, body, ctype, hd = r.sent[-1]
ok(code == 503 and body == SV.BUSY_HTML, "not warming: the Busy card as before")
SV.BOOT["serving_ts"] = time.time() - 30
r = Req("/network?tab=charts"); r._gated(lambda: "X"); code, body, ctype, hd = r.sent[-1]
ok(code == 503 and body == W and hd.get("Retry-After") == "10" and hd.get("X-POAScan-Warming") == "1" and hd.get("Cache-Control") == "no-store", f"warming: the Warming up card ({code})")
ok(SV.boot_state()["warming"] is True, "/api/health boot.warming is true in the window")
SV.BOOT["serving_ts"] = time.time() - SV.WARMUP_S - 5
r = Req("/network?tab=charts"); r._gated(lambda: "X"); code, body, ctype, hd = r.sent[-1]
ok(code == 503 and body == SV.BUSY_HTML, "past the window: Busy again")
SV.BOOT["serving_ts"] = None
print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
