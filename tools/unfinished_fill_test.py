"""Unfinished fill: money_moved is null (unknown), not false, when a swap-fill tx was submitted but is not final.
Case: de1ddefb (expired) has fill b994976f with final 0 and 1 attestation; the buyer's SOL payment landed on Solana,
yet the offer read as if nothing was paid. POAScan can't see external-chain payments.
* money_moved on /api/v1/swaps/<offer_id>, the list, CSV and MCP: true on a filled offer, null when a non-dropped
  swap-fill is not final (any status but filled), false only when no swap-fill tx exists (a dropped one does not count).
* /swap/<offer_id>: status still Expired (terminal status wins); stage history 'Fill submitted, not final'; Fill row
  'Submitted, not final'; Payment ref says unknown, not '···'; next steps say the payment may have landed.
* Ask prompt, OpenAPI, llms.txt, MCP descriptions and /about#swap-settle: null means a fill was submitted but is not
  final and POAScan can't see external-chain payments. No em or en dashes.
Real records: tools/swap_fields_fixture.json. Usage: python3 tools/unfinished_fill_test.py (temp database, no network)."""
import importlib, json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "u.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import db, swapclient as SC, indexer as I, agentapi as AA, offer as OF, prompts as PR
SA = importlib.import_module("poascan.swap.api")
def no_upstream(*a, **k): raise AssertionError("upstream read")
I.fetch = no_upstream

FX = json.load(open(os.path.join(HERE, "swap_fields_fixture.json")))
def put(o, events):
    cols = ",".join(o); db.write(f"INSERT OR REPLACE INTO swaps({cols}) VALUES({','.join('?' * len(o))})", tuple(o.values()))
    for e in events:
        db.write("INSERT OR REPLACE INTO swap_events(txid, offer_id, kind, addr, ts, json, final, checked, dropped, first_seen) VALUES(?,?,?,?,?,?,?,?,0,?)",
                 (e["txid"], o["offer_id"], e["kind"], e["addr"], e["ts"], json.dumps(e.get("body") or {}), 1 if e["final"] else 0, e["ts"], e["ts"]))
for x in FX["offers"]: put(x["swap"], x["events"])
EXP, FIL, CAN = (x["swap"]["offer_id"] for x in FX["offers"])
FILL = "b994976f1127606f9a988d2ad3788753697c65b1d2423580aff64d7b9d47ecba"
def fresh(): SA._rc.clear()

e = SC.offer(EXP)
check("de1ddefb: expired, fill b994976f not final, money_moved null", e["offer"]["status"] == "expired" and e["offer"]["money_moved"] is None
      and any(x["txid"] == FILL and not x["final"] for x in e["events"]))
check("filled cb83e695: money_moved true", SC.offer(FIL)["offer"]["money_moved"] is True)
check("cancelled c4e566fa (no fill tx): money_moved false", SC.offer(CAN)["offer"]["money_moved"] is False)
rows = {r["offer_id"]: r for r in SC.offers()}
check("list carries money_moved on every row, same as the offer route", all("money_moved" in r for r in rows.values())
      and [rows[o]["money_moved"] for o in (EXP, FIL, CAN)] == [None, True, False])
put(dict(FX["offers"][2]["swap"]), [dict(txid="f" * 64, kind="swap-fill", addr="poa1x", ts=1792791000, final=False, body={})]); fresh()
check("cancelled with a non-final fill: money_moved null (any status)", SC.offer(CAN)["offer"]["money_moved"] is None)
db.write("UPDATE swap_events SET dropped=1 WHERE txid=?", ("f" * 64,)); fresh()
check("a dropped fill does not count: back to false", SC.offer(CAN)["offer"]["money_moved"] is False)
o2 = dict(FX["offers"][0]["swap"], offer_id="a" * 64, status="open", expires_ts=int(time.time()) + 3600); put(o2, []); fresh()
check("open offer with no fill: false", SC.offer("a" * 64)["offer"]["money_moved"] is False)
put(o2, [dict(txid="b" * 64, kind="swap-fill", addr="poa1x", ts=int(time.time()), final=False, body={})]); fresh()
check("open offer with a fill landing: null", SC.offer("a" * 64)["offer"]["money_moved"] is None)
check("settle(): filled stays true even beside a pending fill", SA.settle(dict(status="filled", fill_txid="t", fill_ts=1, poa=1.0, fee_bp=100), False, True)["money_moved"] is True)

# page
t, h = OF.page_body(EXP)
tag = re.search(r'<span>Status</span><div><span class="tag[^"]*">([^<]+)</span>', h)
check("page: status still Expired", tag and tag.group(1) == "Expired")
check("page: stage history 'Fill submitted, not final', no 'Fill attempt' or 'never final'",
      "Fill submitted, not final" in h and "Fill attempt" not in h and "never final" not in h and '<span class="dim">not final</span>' in h)
fr = re.search(r'<span>Fill</span><div>(.*?)</div></div>', h); pr = re.search(r'<span>Payment ref</span><div>(.*?)</div></div>', h)
check("page: Fill row reads Submitted, not final with the tx", fr and "Submitted, not final" in fr.group(1) and FILL[:10] in fr.group(1))
check("page: Payment ref says unknown, not '···'", pr and "can&#x27;t see external-chain payments" in pr.group(1) and "···" not in pr.group(1))
check("page: next steps say the payment may have landed", "The payment may have landed on the external chain" in h and "If you paid and it never filled" not in h)
_, hf = OF.page_body(FIL)
check("page: a filled offer keeps its Fill row and Payment ref", "Submitted, not final" not in hf and "Fill submitted, not final" not in hf)
_, pp = PR.swap_status(EXP)
check("Ask prompt: money_moved null is unknown, never nothing paid", "money_moved is null" in pp and "never that nothing was paid" in pp)

# docs
blob = json.dumps(AA.openapi()); llms = AA.llms_txt()
td = json.dumps(AA.handle_mcp(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode())[1])
ab = open(os.path.join(ROOT, "poascan", "views.py"), encoding="utf-8").read()
for nm, txt in (("OpenAPI", blob), ("llms.txt", llms), ("MCP get_swap_offer", td), ("/about#swap-settle", ab)):
    check(f"{nm}: money_moved null means a fill was submitted but is not final; POAScan can't see external-chain payments",
          "money_moved" in txt and "submitted but is not final" in txt and "see external-chain payments" in txt.replace("\\u2019", "'").replace("can\\'t", "can't"))
src = "".join(open(os.path.join(ROOT, p), encoding="utf-8").read() for p in ("poascan/offer.py", "poascan/swap/api.py", "poascan/swap/store.py", "poascan/prompts.py", "tools/unfinished_fill_test.py"))
check("no em or en dashes", not any(c in src + llms + h for c in ("\u2014", "\u2013")))

# HTTP, CSV and MCP (server subprocess, indexer off, no upstream)
sp = socket.socket(); sp.bind(("127.0.0.1", 0)); port = sp.getsockname()[1]; sp.close(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", SWAP_FLAG_URL="")
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(u, data=None, hd=None):
    try:
        with op.open(urllib.request.Request(base + u, data, hd or {}), timeout=30) as x: return x.status, x.read().decode()
    except urllib.error.HTTPError as ex: return ex.code, ex.read().decode()
try:
    for _ in range(100):
        try: get("/healthz"); break
        except Exception: time.sleep(0.2)
    c, j = get(f"/api/v1/swaps/{EXP}"); o = json.loads(j)["offer"]
    check(f"HTTP /api/v1/swaps/de1ddefb ({c}): money_moved null (present, not missing)", c == 200 and "money_moved" in o and o["money_moved"] is None)
    c, j = get("/api/v1/swaps.csv"); lines = j.splitlines(); hdr = lines[0].split(","); i = hdr.index("money_moved") if "money_moved" in hdr else -1
    row = next((l for l in lines if l.startswith(EXP)), "")
    check(f"CSV ({c}) has a money_moved column, empty for de1ddefb", c == 200 and i >= 0 and row and "False" not in row.split(",")[i] and "false" not in row.split(",")[i].lower())
    H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    for name, args, pick in (("get_swap_offer", {"offer_id": EXP}, lambda s: s["offer"]), ("list_swap_offers", {"status": "expired"}, lambda s: next(x for x in s["offers"] if x["offer_id"] == EXP))):
        c, j = get("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}).encode(), H)
        sc = json.loads(j)["result"].get("structuredContent") or {}
        try: v = pick(sc); ok = "money_moved" in v and v["money_moved"] is None
        except Exception: ok = False
        check(f"MCP {name}: de1ddefb money_moved null", ok)
    c, h2 = get(f"/swap/{EXP}")
    check(f"HTTP /swap/de1ddefb ({c}) reads Expired with Fill submitted, not final", c == 200 and "Fill submitted, not final" in h2 and ">Expired<" in h2)
finally:
    srv.terminate(); srv.wait(10)

print("\n%d failed" % len(fails) if fails else "\nall passed"); sys.exit(1 if fails else 0)
