"""Busy shell (1.26.288, UI/UX P0). With every slot held, a human page that has any stored copy (pinned or FIFO, up to
PIN_MAX_AGE_S old) serves that copy with no slot and no edge caching; a page with no copy gets the small branded busy
page (503, Retry-After, reloads itself). The API, MCP and data files keep the plain text 503 their clients parse.
Run: python3 tools/busyshell_test.py (temp db, in-process, no network)."""
import os, re, sys, tempfile, time
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "busy.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_HTML_CACHE"] = "1"
os.environ["POASCAN_MAX_WORKERS"] = "4"
os.environ["POASCAN_SERVE_RESERVE"] = "2"
os.environ["POASCAN_HEAVY_WAIT"] = "0.2"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
from poascan import guard as GD, db, htmlcache as HC, segments as SG
import poascan.server as SV

fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m); c or fails.append(m)
db.init()
HUMAN = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
class Req(SV.H):
    def __init__(self, path, cmd="GET"):
        self.path = path; self.command = cmd; self.headers = {"User-Agent": HUMAN}; self.sent = []
    def send(self, code, body="", ctype="text/html; charset=utf-8", extra=None, pre=None):
        self.sent.append((code, body, ctype, dict(extra or {}))); return code

B = SV.BUSY_HTML
ok(B.startswith("<!doctype html>") and 'http-equiv="refresh"' in B and "Busy" in B and len(B) < 4000, f"busy page is small self-contained HTML ({len(B)} bytes)")
ok(not re.search("[\u2013\u2014]", B) and "Account" not in B and "share" not in B.lower(), "busy page copy rules: no dashes, no Accounts, no share")
ok("<script" not in B and "http://" not in B and "https://" not in B, "busy page makes no request beyond the favicon")

heavy, cheap = [], []
while GD.slots.acquire(blocking=False): heavy.append(1)
while GD.cheap is not None and GD.cheap.acquire(blocking=False): cheap.append(1)
seg = SG.selected()
HC._c.clear(); HC._pin.clear(); HC._bytes[0] = 0
# an unwarmed page with an old FIFO copy (older than CHEAP_STALE, so _html_hit says no)
k = HC.key("/agents/operators", {}, seg, False)
HC.put(k, "<html>OPS-COPY</html>", now=time.time() - 3600)
r = Req("/agents/operators"); ran = []
r._gated(lambda: (ran.append(1), "X")[1])
code, body, ctype, hd = r.sent[-1]
ok(code == 200 and "OPS-COPY" in body and not ran, f"a stored copy is served instead of a 503 ({code})")
ok(hd.get("Cache-Control") == "no-store" and hd.get("X-POAScan-Copy") == "last-good", "the last-good copy is never edge cached and is labelled")
# a copy past PIN_MAX_AGE_S is not served
k2 = HC.key("/privacy", {}, seg, False)
HC.put(k2, "<html>ANCIENT</html>", now=time.time() - HC.PIN_MAX_AGE_S - 60)
r = Req("/privacy"); r._gated(lambda: "X")
code, body, ctype, hd = r.sent[-1]
ok(code == 503 and body == B and hd.get("Retry-After") == "3" and hd.get("Cache-Control") == "no-store", f"a copy older than a day is not served; busy page instead ({code})")
# no copy at all: branded busy page
r = Req("/network?tab=charts"); r._gated(lambda: "X")
code, body, ctype, hd = r.sent[-1]
ok(code == 503 and body == B and ctype.startswith("text/html"), f"a page with no copy gets the busy page ({code})")
# 1.26.316: a crawler reuses the visitor last-good copy instead of getting the Busy card
k3 = HC.key("/agents/operators", {}, seg, False)
HC.put(k3, "<html>OPS-COPY</html>", now=time.time() - 3600)
r = Req("/agents/operators"); r.headers = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}
ran = []
r._gated(lambda: (ran.append(1), "X")[1])
code, body, ctype, hd = r.sent[-1]
ok(code == 200 and "OPS-COPY" in body and not ran, f"Googlebot is served the visitor last-good copy ({code})")
ok(hd.get("Cache-Control") == "no-store" and hd.get("X-POAScan-Copy") == "last-good", "Googlebot last-good is no-store and labelled")
# no copy: Busy is 503 with a longer Retry-After, never 200 or 403
r = Req("/network?tab=charts"); r.headers = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}
r._gated(lambda: "X")
code, body, ctype, hd = r.sent[-1]
ok(code == 503 and body == B and hd.get("Retry-After") == "60" and hd.get("Cache-Control") == "no-store", f"Googlebot with no copy gets Busy as 503 Retry-After 60 ({code})")
# API, MCP, files keep the text. 1.26.319: /api/v1/address itself is the light path, so the shed probe is /txs.
r = Req("/api/v1/address/poa1" + "D" * 40); ran = []
out = r._gated(lambda: (ran.append(1), "LIGHT")[1])
ok(ran == [1] and out == "LIGHT" and not r.sent, "the address API is the light path, not the plain text 503")
for p in ("/api/v1/address/poa1" + "D" * 40 + "/txs", "/api/v1/epochs", "/openapi-gpt.json", "/llms-full.txt", "/fragment/rows"):
    r = Req(p); r._gated(lambda: "X")
    code, body, ctype, hd = r.sent[-1] if r.sent else (None, "", "", {})
    ok(code == 503 and "server busy" in body and body != B, f"{p} keeps the plain text 503 ({code})")
r = Req("/mcp", "POST")
ok(not r._html_shed_ok(), "POST /mcp is never an HTML shed")
for _ in heavy: GD.slots.release()
for _ in cheap: GD.cheap.release()
print(f"\n{len(fails)} failure(s)"); sys.exit(1 if fails else 0)
