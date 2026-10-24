"""Swap settlement fields on /api/v1/swaps and /api/v1/swaps/<offer_id> (and MCP get_swap_offer, OpenAPI, llms.txt, /about).
* taker_credit (final fills only): poa minus fee_poa (poa x fee_bp / 10000), with taker_credit_at (fill tx time, UTC ISO)
  and taker_credit_txid. null otherwise.
* refund_txid and refund_at: the final swap-cancel tx of a cancelled offer. null otherwise; an expired offer stays null
  until the maker cancels (documented: null does not mean not refunded).
* receipt_state: 'signed' when a finalized swap-fill tx (not dropped) carries the seller's receipt signature
  (proof.recv_sig), else null; a fill that never finalized reads null (documented: receipts before a fill are not public).
* Built from archived public txs only: no upstream read. No ext_ref_status, take_state, pending_takes or durable_in_flight.
Real records: tools/swap_fields_fixture.json (de1ddefb expired with a never-final fill, cb83e695 filled, c4e566fa cancelled).
Usage: python3 tools/swap_fields_test.py (temp database, no network)."""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
os.environ["POASCAN_SWAP_EVIDENCE"] = ""   # ledger-only states: no balance evidence applied
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "f.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import db, swapclient as SC, indexer as I, agentapi as AA, views as V
import importlib; SA = importlib.import_module("poascan.swap.api")
def no_upstream(*a, **k): raise AssertionError("upstream read")
I.fetch = no_upstream

FX = json.load(open(os.path.join(HERE, "swap_fields_fixture.json")))
def put(o, events, dropped=()):
    cols = ",".join(o); db.write(f"INSERT OR REPLACE INTO swaps({cols}) VALUES({','.join('?' * len(o))})", tuple(o.values()))
    for e in events:
        db.write("INSERT OR REPLACE INTO swap_events(txid, offer_id, kind, addr, ts, json, final, checked, dropped, first_seen) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (e["txid"], o["offer_id"], e["kind"], e["addr"], e["ts"], json.dumps(e.get("body") or {}), 1 if e["final"] else 0, e["ts"], 1 if e["txid"] in dropped else 0, e["ts"]))
for x in FX["offers"]: put(x["swap"], x["events"])
EXP, FIL, CAN = (x["swap"]["offer_id"] for x in FX["offers"])
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
KEYS = ("taker_credit", "taker_credit_at", "taker_credit_txid", "refund_txid", "refund_at", "receipt_state")
BANNED = ("ext_ref_status", "take_state", "pending_takes", "durable_in_flight")

f = SC.offer(FIL)["offer"]
check(f"filled cb83e695: taker_credit 4950 = 5000 - fee_poa 50 ({f.get('taker_credit')}, {f.get('fee_poa')})",
      f["status"] == "filled" and f["fee_poa"] == 50.0 and f["taker_credit"] == 4950.0 and f["taker_credit"] == round(f["poa"] - f["fee_poa"], 6))
check("filled: taker_credit_at is the fill tx time (UTC ISO), taker_credit_txid the fill txid",
      f["taker_credit_at"] == iso(f["fill_ts"]) == "2026-10-23T21:35:56Z" and f["taker_credit_txid"] == f["fill_txid"] == "68e123b9c59026836e51284e5e5666cf870dc3470e61fb295793dc04f2802a9d")
check("filled: refund null, receipt_state signed (fill carries proof.recv_sig)", f["refund_txid"] is None and f["refund_at"] is None and f["receipt_state"] == "signed")

c = SC.offer(CAN)["offer"]
check("cancelled c4e566fa: refund_txid is the swap-cancel txid, refund_at its tx time",
      c["status"] == "cancelled" and c["refund_txid"] == "d6970ae16cc19f822bfb834c23576c237745ad13e7b5bdc213b8ac0003534de5" and c["refund_at"] == iso(c["cancel_ts"]) == "2026-10-23T21:32:21Z")
check("cancelled: taker_credit null, receipt_state null (no fill)", all(c[k] is None for k in ("taker_credit", "taker_credit_at", "taker_credit_txid", "receipt_state")))

e = SC.offer(EXP)["offer"]
check("expired de1ddefb: no taker_credit (its fill never finalized), refund_txid null until a cancel", e["status"] == "expired" and all(e[k] is None for k in KEYS[:5]))
check("expired de1ddefb: receipt_state null (its fill b994976f carries a receipt but never finalized)", e["receipt_state"] is None)
d1 = SC.offer(EXP)["events"]
check("fixture: de1ddefb's fill is never final and carries proof.recv_sig", any(x["kind"] == "swap-fill" and not x["final"] for x in d1)
      and any(x["kind"] == "swap-fill" and (x.get("body") or {}).get("proof", {}).get("recv_sig") for x in FX["offers"][0]["events"]))

rows = {r["offer_id"]: r for r in SC.offers()}
check("list /api/v1/swaps carries the same six fields on every row", all(all(k in r for k in KEYS) for r in rows.values())
      and all(rows[o][k] == SC.offer(o)["offer"][k] for o in (EXP, FIL, CAN) for k in KEYS))
check("no ext_ref_status, take_state, pending_takes or durable_in_flight", not any(k in r for r in rows.values() for k in BANNED))
check("fill_atts and fill_final left as they were (no new finality fields)", "fill_final" not in f or isinstance(f["fill_final"], bool))

# only a finalized fill counts: final makes it signed, dropped or no recv_sig does not; fee_bp unknown leaves taker_credit null
db.write("UPDATE swap_events SET final=1 WHERE offer_id=? AND kind='swap-fill'", (EXP,)); SA._rc.clear()
check("the same fill once final reads signed", SC.offer(EXP)["offer"]["receipt_state"] == "signed")
db.write("UPDATE swap_events SET dropped=1 WHERE offer_id=? AND kind='swap-fill'", (EXP,)); SA._rc.clear()
check("a dropped fill does not make receipt_state signed", SC.offer(EXP)["offer"]["receipt_state"] is None)
db.write("UPDATE swap_events SET dropped=0, json='{\"proof\": {\"ref\": \"x\"}}' WHERE offer_id=? AND kind='swap-fill'", (EXP,)); SA._rc.clear()
check("a final fill without recv_sig leaves receipt_state null", SC.offer(EXP)["offer"]["receipt_state"] is None)
db.write("UPDATE swap_events SET final=0 WHERE offer_id=? AND kind='swap-fill'", (EXP,))
r = SA.settle(dict(status="filled", fill_txid="t", fill_ts=1, poa=100.0, fee_bp=None), False)
check("fee_bp unknown: taker_credit null, time and txid still given", r["taker_credit"] is None and r["taker_credit_txid"] == "t" and r["taker_credit_at"] == "1970-01-01T00:00:01Z")
r = SA.settle(dict(status="filled", fill_txid="t", fill_ts=1, poa=10729.310509, fee_bp=100), False)
check("rounding matches fee_poa (6 dp)", r["taker_credit"] == round(10729.310509 - round(10729.310509 * 100 / 10000, 6), 6) == 10622.017404)
db.write("UPDATE swap_events SET json=? WHERE offer_id=? AND kind='swap-fill'", (json.dumps(FX["offers"][0]["events"][1]["body"]), EXP)); SA._rc.clear()

# docs: OpenAPI, llms.txt, MCP tool description, /about
blob = json.dumps(AA.openapi())
check("OpenAPI documents all six fields with null semantics", all(k in blob for k in KEYS) and "null does not mean not refunded" in blob and "Receipts before a fill are not public" in blob)
llms = AA.llms_txt()
check("llms.txt documents them", all(k in llms for k in ("taker_credit", "refund_txid", "receipt_state")) and "null does not mean not refunded" in llms and "Receipts before a fill are not public" in llms)
tool = next(t for t in AA.TOOLS if t[0] == "get_swap_offer") if hasattr(AA, "TOOLS") else None
td = json.dumps(tool[:3]) if tool else json.dumps(AA.handle_mcp(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode())[1])
check("MCP get_swap_offer description names the fields", "taker_credit" in td and "receipt_state" in td and "pre-fill receipts are not public" in td)
ab = open(os.path.join(ROOT, "poascan", "views.py"), encoding="utf-8").read()
check("/about#swap-settle explains the fields", 'id="swap-settle"' in ab and "null does not mean not refunded" in ab and "Receipts before a fill are not public" in ab)
src = "".join(open(os.path.join(ROOT, p), encoding="utf-8").read() for p in ("poascan/swap/api.py", "poascan/swap/store.py", "tools/swap_fields_test.py"))
check("no em or en dashes in the new code and copy", "\u2014" not in src and "\u2013" not in src and "\u2014" not in llms and "\u2013" not in llms)

# over HTTP and MCP (server subprocess, indexer off, no upstream)
sp = socket.socket(); sp.bind(("127.0.0.1", 0)); port = sp.getsockname()[1]; sp.close(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", SWAP_FLAG_URL="")
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(u, data=None, h=None):
    try:
        with op.open(urllib.request.Request(base + u, data, h or {}), timeout=30) as x: return x.status, x.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
try:
    for _ in range(100):
        try: get("/healthz"); break
        except Exception: time.sleep(0.2)
    code, j = get(f"/api/v1/swaps/{FIL}"); o = json.loads(j)["offer"]
    check(f"HTTP /api/v1/swaps/<filled> ({code}) carries taker_credit 4950", code == 200 and o["taker_credit"] == 4950.0 and o["receipt_state"] == "signed")
    code, j = get(f"/api/v1/swaps/{CAN}"); o = json.loads(j)["offer"]
    check(f"HTTP /api/v1/swaps/<cancelled> ({code}) carries refund_txid", code == 200 and o["refund_txid"] == c["refund_txid"])
    code, j = get("/api/v1/swaps.csv")
    check(f"CSV list ({code}) has the columns", code == 200 and all(k in j.splitlines()[0] for k in KEYS))
    H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    code, j = get("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_swap_offer", "arguments": {"offer_id": EXP}}}).encode(), H)
    sc = json.loads(j)["result"].get("structuredContent") or {}
    check("MCP get_swap_offer returns them (de1ddefb null)", "offer" in sc and sc["offer"].get("receipt_state") is None and all(k in sc["offer"] for k in KEYS))
finally:
    srv.terminate(); srv.wait(10)

print("\n%d failed" % len(fails) if fails else "\nall passed"); sys.exit(1 if fails else 0)
