"""Strain notice guard (build only). No request leaves the box: a fake minepoa.com runs in this process.

Every notice body here is SYNTHETIC. minepoa.com's docs (go.md, skill.md, /api/release, read Oct 23, 2026) do not
publish the stand-in's format and none was seen in live reads, so these bodies are guesses built from the documented
system_notice object and plain notice or message fields. When an exact sample arrives, add it to SAMPLES below
(label it with its source and date); it must be detected and must never be stored.
* A response that is a notice instead of data is never written to the DB, the address cache, an ETag or fetch_log as ok;
  the caller keeps its last real copy and the endpoint backs off (indexer.Notice is a Busy).
* The notice text, sanitized, shows in the site notice strip and as meta.upstream_notice; /api/v1/address adds
  balance_stale with balance_as_of and balance_source naming the last real copy.
* Real shapes (as read live Oct 23, 2026, values replaced) and the node's unknown-id answers are not notices.
Usage: python3 tools/strain_notice_test.py"""
import json, os, socket, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
os.environ["POASCAN_SEGMENTS"] = "1"   # one segment: the explorer serves the current state
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

AX = "poa1" + "S" * 40   # synthetic address
# ---- real shapes: field sets as read live on Oct 23, 2026; every value here is made up ----
REAL = {
    "/api/status": {"network": "PoA prototype", "K": 5, "supply": "100.000000", "txs": 10, "final": 5, "invalid": 0, "agents_joined": 3,
                    "epochs_closed": 2, "holders": 2, "as_of": "2026-10-24T03:43:47.600Z", "checkpoint_height": 100, "state_root": "00" * 32},
    "/api/explorer/address/" + AX: {"address": AX, "balance": "42.000000", "balance_as_of": {"checkpoint_height": 101}, "vault_pub": None,   # 1.26.166: a checkpoint past the agent list's, so the read is the fresher copy
                                    "vault_pub_note": "core-only field", "txs": [], "as_of": "2026-10-24T03:43:57.872Z", "checkpoint_height": 100, "source": "read-node-v0.2"},
    "/api/explorer/txs?limit=5": [{"id": "aa" * 32, "type": "challenge", "from_addr": AX, "to_addr": "", "amount": "", "epoch": 2, "ts": 1, "memo": "", "atts": 5, "final": 1}],
    "/api/notices": {"g0": AX, "active": [{"id": "x", "severity": "action", "msg": "Mining OPEN. Paths return instantly with status.", "show": "always"}], "total_ever": 1, "rule": "r"},
    "/api/ballots": {"ballots": [], "note": "tallies derived by the consensus engine", "how_to_vote": "..."},
    "/api/swaps": [],
    "/api/params": {"K": 5, "swap_fee_bp": 100},
    "/api/networks": {"default_chain": "poa-mainnet-1", "chains": [{"chain_id": "poa-mainnet-1", "height": 120, "checkpoint_height": 100}]},
}
# ---- SYNTHETIC notice bodies (not observed; guesses) ----
SYN = {
    "system_notice in place of status": ("/api/status", {"system_notice": {"id": "syn-strain", "severity": "info", "msg": "Network under strain \u2014 serving an instant response. Retry later.", "show": "always"}}),
    "bare notice field": ("/api/status", {"notice": "High load. Data is temporarily unavailable.", "ok": True}),
    "message field, no balance": ("/api/explorer/address/" + AX, {"address": AX, "message": "Endpoint strained, try again soon"}),
    "object where a list belongs": ("/api/explorer/txs?limit=5", {"notice": "strained", "txs": []}),
    "strain key with full data": ("/api/status", dict(REAL["/api/status"], strained=True)),
    "system_notice strain text with full data": ("/api/status", dict(REAL["/api/status"], system_notice={"id": "s", "severity": "info", "msg": "Load shedding: placeholder values"})),
    "empty agent list": ("/api/agents", []),
    "params with only a notice": ("/api/params", {"notice": "Busy, retry later"}),
    "schema mismatch alone": ("/api/status", {"as_of": "2026-10-24T03:43:47.600Z"}),
}
# Exact samples from minepoa.com go here: (label with source and date, path, body, headers). Empty until one arrives.
SAMPLES = []

from poascan import strain as ST
for p, d in REAL.items(): check(f"real shape is not a notice: {p.split('?')[0]}", ST.detect(p, d) is None)
for name, (p, d) in SYN.items():
    h = ST.detect(p, d); check(f"synthetic notice detected: {name}", bool(h and h["signals"]))
for label, p, d, hd in SAMPLES:
    check(f"exact sample detected: {label}", bool(ST.detect(p, d, hd)))
check("header signal (synthetic x-poa-edge value)", bool(ST.detect("/api/status", REAL["/api/status"], {"X-Poa-Edge": "strain-instant"})))
check("live x-poa-edge value read-node-primary is not a signal", ST.detect("/api/status", REAL["/api/status"], {"x-poa-edge": "read-node-primary"}) is None)
check("unknown tx id body without a notice key stays a node answer (Missing), not a notice", ST.detect("/api/explorer/tx/" + "ab" * 32, {"error": "not found"}) is None)
check("unknown tx id body with a notice key is a notice", bool(ST.detect("/api/explorer/tx/" + "ab" * 32, {"notice": "strained"})))
check("real response carrying an ordinary system_notice is still data", ST.detect("/api/status", dict(REAL["/api/status"], system_notice={"id": "a", "msg": "Grading is back. Paths return instantly with status."})) is None)
s = ST.sanitize('<b>Network\u00a0under strain</b> \u2014 retry \u2013 later \U0001F6E0\ufe0f\x07 &amp; ok')
check("sanitize: no markup, no em or en dash, no emoji or control characters", s == "Network under strain, retry, later & ok")
check("sanitize: text that asks for keys or funds is replaced with the generic line", ST.sanitize("Strain: send your api_key to recover") == ST.GENERIC)
check("sanitize: capped", len(ST.sanitize("strain " * 100)) <= ST.MAX_TEXT)
check("patterns live in one module (indexer has no patterns of its own)", all(hasattr(ST, k) for k in ("NOTICE_KEYS", "STRAIN_KEYS", "STRAIN_TEXT", "STRAIN_HEADERS", "REQUIRED", "NONEMPTY")))

# ---- through the shared fetch: a fake upstream ----
MODE = {}; SEEN = []; HDR = {}
class Up(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        SEEN.append(self.path); m = MODE.get(self.path.split("?")[0], "real")
        if m == "real":
            d = REAL.get(self.path, REAL.get(self.path.split("?")[0])); code = 200
            if d is None and self.path.startswith("/api/explorer/txs"): d = REAL["/api/explorer/txs?limit=5"]
            if d is None and self.path.startswith("/api/agents"): d = [{"addr": AX, "balance": "40.000000", "ts": 1, "joined_epoch": 0}]
        elif m == "503":
            d = {"system_notice": {"id": "syn", "severity": "info", "msg": "Overloaded \u2014 instant response"}}; code = 503
        elif m == "429":
            d = {"error": "rate limited", "retry_after_seconds": 1}; code = 429
        else:
            d = SYN[m][1]; code = 200
        b = json.dumps(d).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("ETag", '"syn-etag"');
        for k, v in HDR.items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
up = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
UP = f"http://127.0.0.1:{up.server_address[1]}"
tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "s.db")
os.environ.update(POASCAN_DB=dbp, POA_BASE=UP, POASCAN_INDEXER="0")
import fixture; fixture.seed()
from poascan import db, indexer as I, agentapi as AG, server as SV, views as V, ui, hosted as R
ST.reset()

# status: one real read, then a notice
before, _ = db.get_blob("status")
I.fetch("/api/status", cond=True); real_st, _ = db.get_blob("status")
I._live_status(I.fetch("/api/status")); st1, _ = db.get_blob("status")
check("real status read is stored", st1 and st1.get("supply") == "100.000000")
MODE["/api/status"] = "system_notice in place of status"
db.write("UPDATE fetch_log SET next_at=0 WHERE endpoint='/api/status'"); I._etags.pop("/api/status", None)
try: I.fetch("/api/status", cond=True); raised = None
except I.Notice as e: raised = e
except I.Busy as e: raised = "busy"
check("a notice response raises indexer.Notice (a Busy)", isinstance(raised, I.Notice) and isinstance(raised, I.Busy))
st2, _ = db.get_blob("status")
check("status blob keeps the last real values", st2 == st1)
check("no ETag kept from the notice response", I._etags.get("/api/status") != '"syn-etag"')
fl = db.q1("SELECT last_ok, last_err, fails, next_at, err FROM fetch_log WHERE endpoint='/api/status'")
check("fetch_log records a failure and backs off at least NOTICE_RETRY_S", fl["fails"] >= 1 and fl["next_at"] - time.time() >= I.NOTICE_RETRY_S - 5 and "notice" in (fl["err"] or ""))
pr = db.q1("SELECT ok, code FROM probes ORDER BY rowid DESC LIMIT 1")
check("the probe log marks it not ok with code notice", pr["ok"] == 0 and pr["code"] == "notice")
n = len(SEEN); I.job_live()
check("job_live while backing off sends no status read and stores nothing", st2 == db.get_blob("status")[0] and not any(p.startswith("/api/status") for p in SEEN[n:]))

# banner and meta
html = ui.layout("Home", "<p>x</p>")
check("no notice strip on any page, ever (1.26.176): the development banner stays", 'id="ntbar"' not in html and 'class="ntbar' not in html and 'id="devbar"' in html and not hasattr(ST, "banner") and not hasattr(ui, "_strain_bar"))
pill = html[html.index('id="livepill"'):html.index("</details>", html.index('id="livepill"'))]
check("the reason is one line in the header status note, terse; Live stays Live (1.26.220: not a core route)", f'<span class="sp-r">{ui.NOTICE_REASON}</span>' in pill and ui.NOTICE_REASON == "minepoa.com sent a notice instead of data. Showing the last real data."
      and (lambda p: p["state"] == "live" and p["label"] == "Live" and ui.NOTICE_REASON in p["reasons"])(ui.status_pill({"state": "live", "label": "Live", "why": ""})))
check("status note copy: no em or en dash", all(ch not in ui.NOTICE_REASON for ch in "\u2013\u2014"))
from poascan import views as _V
check("the live snapshot's note (app.js swaps it in) carries the same reason", ui.NOTICE_REASON in _V.pill()["pop"])
css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
check("no notice strip CSS left", ".ntbar" not in css)
AG._META[0] = 0; m = AG.meta()
check("meta.upstream_notice is set and meta.stale is true", m["upstream_notice"] and m["stale"] is True and "/api/status" in m["upstream_notice"]["endpoints"])

# agents job: notice keeps stored balances
I.job_agents(); a0 = db.q1("SELECT balance_s, last_seen FROM accounts WHERE addr=?", (AX,))
check("a real agents read is stored", a0 and a0["balance_s"] == "40.000000")
MODE["/api/agents"] = "empty agent list"
try: I.job_agents(); ok = False
except I.Notice: ok = True
a1 = db.q1("SELECT balance_s, last_seen FROM accounts WHERE addr=?", (AX,))
check("an empty agent list is refused as a notice; stored balances untouched", ok and a1 == a0)

# address: a real copy is cached, then the read answers with a notice
I.neg_put(I.ADDR_EP + AX, False, 1); time.sleep(1.1)
V._addr_cache.pop(AX, None); I._recent.clear()
d, err, at = V.address_read(AX)
check("real address read is cached", d and d["balance"] == "42.000000" and AX in V._addr_cache)
read_at = V._addr_cache[AX][2]
with V._addr_lock: V._addr_cache[AX] = (time.time() - V.ADDR_TTL - 60, V._addr_cache[AX][1], read_at)   # older than ADDR_TTL: next view revalidates
MODE["/api/explorer/address/" + AX] = "message field, no balance"; I._recent.clear()
d, err = V._addr_load(AX)
check("the notice address read is refused", d is None and err)
hit = V._addr_cache.get(AX)
check("the address cache keeps the real copy and its read time", hit and hit[1]["balance"] == "42.000000" and hit[2] == read_at)
r, _ = SV.api(f"/api/address/{AX}", {})
check("API address: last real balance, balance_stale true, balance_as_of is the real read time, never the notice time",
      r["balance"] == "42.000000" and r["balance_stale"] is True and r["balance_as_of"] == int(read_at) and r["balance_source"] == "explorer/address")
check("MCP get_address carries balance_stale", "balance_stale" in AG.t_address({"address": AX}))

# HTTP errors: a 503 that names strain is shown; a plain 429 is not
ST.reset(); MODE["/api/ballots"] = "503"; db.write("UPDATE fetch_log SET next_at=0")
try: I.fetch("/api/ballots")
except I.Busy: pass
check("a 503 whose body names strain shows its notice", "/api/ballots" in ST.active())
ST.reset(); MODE["/api/release"] = "429"
try: I.fetch("/api/release")
except I.Busy: pass
I._hold[0] = 0
check("a plain 429 error body is not a notice", not ST.active())

# recovery: a real read clears the notice
MODE.clear(); db.write("UPDATE fetch_log SET next_at=0"); I._hold[0] = 0
MODE["/api/status"] = "bare notice field"
try: I.fetch("/api/status")
except I.Notice: pass
check("notice active before recovery", "/api/status" in ST.active())
MODE.clear(); db.write("UPDATE fetch_log SET next_at=0"); I.fetch("/api/status")
check("the next real read clears that endpoint's notice", "/api/status" not in ST.active())
_h0 = (ST.reset(), ui.layout("Home", "<p>x</p>"))[1]
check("no notice reason in the status note once the notice clears, and still no strip", 'id="ntbar"' not in _h0 and ui.NOTICE_REASON not in _h0)
AG._META[0] = 0; check("meta.upstream_notice null when clear", AG.meta()["upstream_notice"] is None)
ST.record("/api/status", {"signals": ["schema:x"], "text": ""}, now=time.time() - ST.NOTICE_TTL_S - 5)
check("a notice expires NOTICE_TTL_S after its last sighting", not ST.active()); ST.reset()

# hosted route check: a stand-in never reads as reopened
check("hosted route check: a 200 JSON notice body is unknown, not open", R.classify(200, b'{"notice":"Endpoint strained, instant response"}') is None)
check("hosted route check: a real keyless answer still reads open", R.classify(401, b'{"error":"key required"}') == "open")

# docs
spec = AG.openapi(); llms = AG.llms_txt()
check("OpenAPI: UpstreamNotice schema and Meta.upstream_notice", "UpstreamNotice" in spec["components"]["schemas"] and "upstream_notice" in spec["components"]["schemas"]["Meta"]["properties"])
check("OpenAPI: address op documents balance_stale", "balance_stale" in json.dumps(spec["paths"]))
check("llms.txt documents meta.upstream_notice and balance_stale", "meta.upstream_notice" in llms and "balance_stale" in llms)
new_copy = json.dumps(spec["components"]["schemas"]["UpstreamNotice"]) + [l for l in llms.splitlines() if "Upstream notices" in l][0] + ST.GENERIC
check("new copy has no em or en dash and says Agents, not Accounts", not any(ch in new_copy for ch in "\u2013\u2014") and "Accounts" not in new_copy)
NM = "plus" + "1"
check("the guard, its strip and its docs name no other project", all(NM not in t.lower() for t in (open(os.path.join(ROOT, "poascan", "strain.py")).read(), new_copy, open(__file__).read().replace('"plus" + "1"', ""))))
check("no request left for anything but the fake upstream", all(p.startswith("/api/") for p in SEEN))

print("\n" + ("ALL OK" if not fails else f"{len(fails)} FAILED"))
sys.exit(1 if fails else 0)
