"""POAScan reads POASwap's swap flag (poascan/swapflag.py) as the single source. No request leaves the box: a fake
poaswap.io runs in this process. Covers live, paused, 304 with If-None-Match, timeout, stale past 15 minutes, bad JSON,
the boot fallback, message cleaning, url on every swap link, and that POAScan only ever sends plain GETs.
Usage: python3 tools/swapflag_test.py"""
import json, os, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

SEEN = []                       # (method, path, headers, body length)
MODE = {"m": "live"}
BODY = lambda **k: dict(dict(status="live", available=True, swaps_live=True, reason=None, message="Swaps are live", open_offer_count=3,
                             updated_at="2026-10-23T16:50:43Z", url="https://poaswap.io/start", source="poaswap", version=1), **k)
ETAG = 'W/"abc123"'
class Up(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _rec(self): SEEN.append((self.command, self.path, dict(self.headers), int(self.headers.get("Content-Length") or 0)))
    def do_POST(self): self._rec(); self.send_response(405); self.end_headers()
    do_PUT = do_PATCH = do_DELETE = do_POST
    def do_GET(self):
        self._rec(); m = MODE["m"]
        if m == "timeout": time.sleep(5)
        if m == "304" and self.headers.get("If-None-Match") == ETAG:
            self.send_response(304); self.send_header("ETag", ETAG); self.end_headers(); return
        b = {"live": json.dumps(BODY()), "304": json.dumps(BODY()), "timeout": json.dumps(BODY()),
             "paused": json.dumps(BODY(status="paused", available=False, swaps_live=True, reason="book_stale", message="Book data stale", open_offer_count=0)),
             "coming_soon": json.dumps(BODY(status="coming_soon", available=False, swaps_live=False, message="Swaps open soon \u2014 stay tuned")),
             "badjson": "{not json", "badshape": json.dumps({"status": "maybe"}),
             "evilurl": json.dumps(BODY(url="javascript:alert(1)", message="<b>hi</b>"))}[m]
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("ETag", ETAG)
        self.send_header("Cache-Control", "public, max-age=30"); self.end_headers(); self.wfile.write(b.encode())
srv = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=srv.serve_forever, daemon=True).start()

os.environ["POASCAN_DB"] = tempfile.mktemp(suffix=".db")
os.environ["SWAP_FLAG_URL"] = f"http://127.0.0.1:{srv.server_address[1]}/api/v1/swaps/status"
from poascan import db; db.init()
from poascan import swapflag as F, agentapi as AG, faq as FQ
from poascan.swap import market as M, config as C, faq as SF
F.TIMEOUT = 1
T0 = 1_800_000_000.0
def api(): return M.swap_status_api()
def note(): return AG.t_swap_status({})["note"]
def buy(): return SF._buy_now()
def tile(): return SF._swaps()

# boot fallback: POASwap never reached since boot, SWAPS_LIVE (True) decides status
F._reset()
d = api(); fl = F.current(T0)
check("fallback: status live from SWAPS_LIVE, basis fallback, fetched_at null", fl["status"] == "live" and fl["basis"] == "fallback" and fl["fetched_at"] is None and C.SWAPS_LIVE is True)
check("fallback: api exposes source poaswap, flag_basis fallback, url poaswap.io/start", d["source"] == "poaswap" and d["flag_basis"] == "fallback" and d["url"] == "https://poaswap.io/start")
check("fallback: available follows POAScan's own minepoa read (none here: false, upgrading)", d["available"] is False and d["state"] == "upgrading")

# live
MODE["m"] = "live"; r = F.refresh(T0)
d = api()
check("live: refresh ok", r == "ok")
check("live: status live, available true, state available", (d["status"], d["available"], d["state"]) == ("live", True, "available"))
check("live: clean POASwap message shown (with a period)", d["message"] == "Swaps are live.")
check("live: url, source, fetched_at, open_offer_count, updated_at", d["url"] == "https://poaswap.io/start" and d["source"] == "poaswap" and d["fetched_at"] and d["open_offer_count"] == 3 and d["updated_at"] == "2026-10-23T16:50:43Z")
check("live: MCP note says live and links url", note().startswith("Swaps are live on minepoa.com.") and "https://poaswap.io/start" in note())
check("live: FAQ 'Can I buy right now?' says yes and links url", buy().startswith("Yes. Swaps are live on minepoa.com.") and 'href="https://poaswap.io/start"' in buy())
check("live: FAQ tile Available", ">Available<" in tile())

# 304: If-None-Match sent, last good copy kept and refreshed
MODE["m"] = "304"; n0 = len(SEEN); r = F.refresh(T0 + 60)
check("304: If-None-Match carries the ETag", SEEN[n0][2].get("If-None-Match") == ETAG)
check("304: not_modified keeps the body and moves fetched_at", r == "not_modified" and F.current(T0 + 60)["status"] == "live" and F.current(T0 + 60)["age_s"] == 0)

# paused
MODE["m"] = "paused"; F.refresh(T0 + 120); d = api()
check("paused: status paused, available false, state upgrading", (d["status"], d["available"], d["state"]) == ("paused", False, "upgrading"))
check("paused: POASwap message used, reason passed through", d["message"] == "Book data stale." and d["reason"] == "book_stale")
check("paused: MCP note", note() == "Swaps are paused. Don't call swap-offer or swap-take; tell the user to check back soon.")
check("paused: FAQ copy and tile", buy().startswith("Not right now. Book data stale. See <a href=\"https://poaswap.io/start\">") and ">Paused<" in tile())

# coming_soon with a dash in the message: POAScan's own label instead
MODE["m"] = "coming_soon"; F.refresh(T0 + 180); d = api()
check("coming_soon: dashed message replaced by POAScan's label", d["status"] == "coming_soon" and d["message"] == "Swaps are coming soon." and d["state"] == "coming_soon")
check("coming_soon: FAQ and MCP note", buy().startswith("Not yet. Swaps are coming soon.") and note().startswith("Swaps are coming soon. Don't call swap-offer or swap-take yet"))

# timeout: short timeout, the last good copy stays
MODE["m"] = "live"; F.refresh(T0 + 200)
MODE["m"] = "timeout"; t = time.time(); r = F.refresh(T0 + 260); dt = time.time() - t
check("timeout: returns within ~1 s, keeps last good copy", dt < 3 and r != "ok" and F.current(T0 + 260)["status"] == "live" and F.current(T0 + 260)["last_error"])

# bad JSON and bad shape: last good copy stays
MODE["m"] = "badjson"; r1 = F.refresh(T0 + 320); MODE["m"] = "badshape"; r2 = F.refresh(T0 + 380)
check("bad JSON and bad shape: errors, last good copy kept", r1 == "bad JSON" and r2 == "bad JSON" and F.current(T0 + 380)["status"] == "live" and F.current(T0 + 380)["fetched_at"] == F._iso(T0 + 200))

# stale past 15 minutes: unknown
fl = F.current(T0 + 200 + 900); check("stale: at exactly 15 min still live", fl["status"] == "live")
fl = F.current(T0 + 200 + 901)
check("stale: past 15 min status unknown, available false, basis expired", fl["status"] == "unknown" and fl["available"] is False and fl["basis"] == "expired")
F._state["ok_ts"] = time.time() - 1000   # api() reads the clock
d = api()
check("stale: api status unknown, state unknown, label", (d["status"], d["state"], d["available"], d["message"]) == ("unknown", "unknown", False, "Swap status is unknown right now."))
check("stale: MCP note and FAQ", note().startswith("POAScan can't read POASwap's swap status right now.") and buy().startswith("POAScan can't read the swap status right now.") and ">Unknown<" in tile())

# hostile values: non-https url falls back, HTML in message replaced
MODE["m"] = "evilurl"; F.refresh(); d = api()
check("non-https url ignored, HTML message replaced by label", d["url"] == "https://poaswap.io/start" and d["message"] == "Swaps are live on minepoa.com.")

# summary, MCP summary, offers and the home Market link all carry the flag
MODE["m"] = "live"; F.refresh()
s = AG.t_summary({})
check("MCP summary swaps block: status, source, fetched_at", s["swaps"]["status"] == "live" and s["swaps"]["source"] == "poaswap" and s["swaps"]["fetched_at"])
check("llms.txt: swap line uses url", "Swaps and wallet setup are on POASwap: https://poaswap.io/start." in AG.llms_txt())
from poascan import views as V
check("home Market link uses url", 'class="more mswap" href="https://poaswap.io/start"' in V.home())

# POAScan only reads: every request was a plain GET with no body
check("only GETs, no request body, nothing sent to POASwap", SEEN and all(m == "GET" and n == 0 for m, _, _, n in SEEN))
check("no POAScan data in the request (only UA, Accept, If-None-Match)", all(set(k.lower() for k in h) <= {"host", "user-agent", "accept", "accept-encoding", "if-none-match", "connection"} for _, _, h, _ in SEEN))

# empty URL: never read
F.URL = ""; check("SWAP_FLAG_URL empty: refresh is off", F.refresh() == "off")
print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
