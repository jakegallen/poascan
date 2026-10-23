"""Forum promises (LabLeak 1375 and 1332): the community status board link, and /swap/<offer_id>, a read-only per-offer
swap status page built from POAScan's own swap data (castle-claude-agent's offer from post 1332 as the case).
Usage: python3 tools/forum_promises_test.py (temp database, no network; one local server for the routes)."""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); DBP = os.path.join(tmp, "f.db"); os.environ["POASCAN_DB"] = DBP; os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import db, offer as OF, prompts as PR, views2 as V2, views as V, market as X
FX = json.load(open(os.path.join(HERE, "castle_offer_fixture.json")))
OID = FX["swap"]["offer_id"]; SW = FX["swap"]

def seed_castle(db):
    cols = ",".join(SW); db.write(f"INSERT OR REPLACE INTO swaps({cols}) VALUES({','.join('?' * len(SW))})", tuple(SW.values()))
    for e in FX["events"]:
        db.write("INSERT OR REPLACE INTO swap_events(txid, offer_id, kind, addr, ts, json, final, checked, dropped, first_seen) VALUES(?,?,?,?,?,?,?,?,0,?)",
                 (e["txid"], OID, e["kind"], e["addr"], e["ts"], "{}", 1, e["ts"], e["ts"]))
    db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, ts, atts, final) VALUES(?, 'swap-fill', ?, ?, ?, 1)", (SW["fill_txid"], SW["taker"], SW["fill_ts"], FX["fill_atts"]))
    db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, ts, final) VALUES(?, 'swap-offer', ?, ?, 1)", (OID, SW["maker"], SW["created_ts"]))
    db.put_blob("chains", FX["chains"])
seed_castle(db)
def nodash(h): return not any(c in h for c in "\u2014\u2013") and "&mdash;" not in h and "&ndash;" not in h

# ---------------- /swap/<offer_id>: castle-claude-agent's offer (post 1332) ----------------
t, h = OF.page_body(OID)
check("castle offer renders with a short title", t == "Swap 9d095580…6937d2")
check("status Filled", '<span class="tag ok">Filled</span>' in h)
check("escrow: 10,000 POA locked by the maker, offer tx linked", "10,000</span> <span class=\"unit\">POA</span> locked by the maker" in h and f'href="/tx/{OID}"' in h)
check("wants 0.001 SOL on Solana to the maker's address (Solscan)", "0.001</span> <span class=\"unit\">SOL</span> on Solana" in h and "https://solscan.io/account/" + SW["pay_to"] in h)
check("payment ref links the external tx", "https://solscan.io/tx/" + SW["ext_ref"] in h)
check("fill tx, time, 5 attestations, final", f'href="/tx/{SW["fill_txid"]}"' in h and "5 attestations" in h and '<span class="ok">final</span>' in h)
check("stage history: offered then filled, both final", h.index("Offered (escrow locked)") < h.index(">Filled<", h.index("Stage history")) and h.count('<span class="ok">final</span>') >= 3)
check("next steps for Filled: stop, don't take or pay again", "Filled and final: nothing left to do. Stop checking." in h and "Don&#x27;t take or pay this offer again." in h)
check("names what POAScan can't see (nonce rent) and links the taker's verified Solana address", "durable nonce account" in h and "https://solscan.io/account/" + FX["chains"][SW["taker"]]["solana"]["addr"] in h)
check("no fee on this page (it lives on the Swap Fee card)", not re.search(r"\bfee\b|9,900|1%", h, re.I))
check("track and API links, read-only line", f"https://poaswap.io/status/{OID}" in h and "track?offer=" not in h and f'href="/api/v1/swaps/{OID}"' in h and "never signs or sends anything" in h)
check("no em or en dashes", nodash(h))
tt, pp = PR.swap_status(OID)
check("Ask agent prompt on the page (copy-ready, read only)", "data-ask=" in h and "Check this swap&#x27;s status" in h)
check("prompt: poaswap check and POAScan offer reads, safe rules", f"https://poaswap.io/api/v1/check?offer={OID}" in pp and f"https://poascan.io/api/v1/swaps/{OID}" in pp
      and "Stop at Filled, Expired or Failed" in pp and "Check status before any re-take" in pp and "Never loop" in pp and "Never send payment outside the network." in pp and "Read-only" in pp)
check("prompt: no key, no referral, no fee, no dashes", "MY_KEY" not in pp and "pk_" not in pp and "referral" not in pp.lower() and "invite" not in pp.lower() and "fee" not in pp.lower() and nodash(pp))
check("prompt id is registered for click counts", PR.pid(tt) in {PR.pid(x) for x in PR.titles()})

# ---------------- other stages ----------------
def variant(**kw):
    o = dict(SW, **kw); oid = kw.get("offer_id")
    cols = ",".join(o); db.write(f"INSERT OR REPLACE INTO swaps({cols}) VALUES({','.join('?' * len(o))})", tuple(o.values()))
    return OF.page_body(oid)[1]
now = int(time.time())
h = variant(offer_id="op" + "1" * 30, status="open", taker=None, fill_txid=None, fill_ts=None, ext_ref=None, expires_ts=now + 3600)
check("open: check status before any take, network flow only, never loop", "Check status before any take or re-take." in h and "Never send payment outside the network." in h and "never loop" in h
      and "Stop at Filled, Expired or Failed." in h and '<span class="tag ok">Open</span>' in h)
h = variant(offer_id="ex" + "1" * 30, status="open", taker=None, fill_txid=None, fill_ts=None, ext_ref=None, expires_ts=now - 60)
check("past expiry reads Expired: stop", '<span class="tag ">Expired</span>' in h and "Expired: stop." in h)
oid = "pf" + "1" * 30
db.write("INSERT OR REPLACE INTO swap_events(txid, offer_id, kind, addr, ts, json, final, checked, dropped, first_seen) VALUES(?,?,?,?,?,?,0,NULL,0,?)", ("ab" * 32, oid, "swap-fill", SW["taker"], now, "{}", now))
h = variant(offer_id=oid, status="open", taker=None, fill_txid=None, fill_ts=None, ext_ref=None, expires_ts=now + 3600)
check("a fill seen but not final reads Fill landing: wait, don't re-take", "Fill landing" in h and "Don&#x27;t re-take or pay again while it lands." in h)
check("unknown or malformed offer ids render nothing", OF.page_body("nope" * 3) is None and OF.page_body("bad id!") is None and OF.page_body("x" * 200) is None)

# ---------------- /tx links the status page ----------------
rows = dict(X.tx_rows({"offer": OID}))
check("/tx offer row links /swap/<offer_id>", f'href="/swap/{OID}">Swap status' in rows.get("Offer", ""))

# ---------------- status board link ----------------
URL = "https://embot-lantern.codeberg.page/poa-field-guide/status/"
a = V2._board()
check("status board link: exact URL, new tab, noopener, terse label, no referral", f'href="{URL}"' in a and 'target="_blank"' in a and "noopener" in a and ">Community status board ↗<" in a
      and not re.search(r"[?&](ref|invite|r|via|utm_[a-z]+)=", URL))
check("Health tab carries it", a in V2.status_body())
check("community list carries it", URL in V2.community_html())
db.put_blob("notices", {"active": [{"id": "2026-10-23-grading-resumed", "issued_ts": 1792774656, "expires_ts": now + 3600, "txid": "a2" * 32,
                                    "msg": "GRADING IS BACK, all paths OPEN. Hardening pause over, resume normal cadence."}]})
check("/upgrade carries it", a in V2.upgrade_body())

# ---------------- routes ----------------
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
port = free_port(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=DBP, POASCAN_INDEXER="0", POASCAN_ROUTE_CHECK="0")
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def get(path):
    try:
        with urllib.request.urlopen(base + path, timeout=20) as r: return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
try:
    for _ in range(60):
        try: get("/healthz"); break
        except Exception: time.sleep(0.25)
    c, b = get("/swap/" + OID); c2, b2 = get("/offer/" + OID)
    check(f"GET /swap/<id> 200 and /offer/<id> the same page ({c}, {c2})", c == 200 and c2 == 200 and "Stage history" in b and "Stage history" in b2)
    c, b = get("/swap/" + "0" * 64)
    check(f"unknown offer is a 404 page ({c})", c == 404 and "POAScan holds no swap offer" in b)
    c, _ = get("/swap/bad%20id"); check(f"malformed id is a 404 ({c})", c == 404)
    c, b = get("/api/v1/swaps/" + OID); check("the API it mirrors still answers", c == 200 and json.loads(b)["offer"]["status"] == "filled")
finally:
    p.terminate(); p.wait(timeout=10)

if fails: print(f"\nFAIL: {len(fails)}: {fails}"); sys.exit(1)
print("\nPASS")
