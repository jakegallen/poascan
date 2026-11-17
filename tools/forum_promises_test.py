"""Forum promises (LabLeak 1375 and 1332): the community status board link. The per-offer /swap/<offer_id> page moved to
POASwap: it 301s there, and /tx shows the offer id as plain text (castle-claude-agent's offer from post 1332 as the case).
Usage: python3 tools/forum_promises_test.py (temp database, no network; one local server for the routes)."""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); DBP = os.path.join(tmp, "f.db"); os.environ["POASCAN_DB"] = DBP; os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import db, views2 as V2, views as V, market as X
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

now = int(time.time())

# ---------------- /tx shows the offer id as plain text (the swap pages moved to POASwap) ----------------
rows = dict(X.tx_rows({"offer": OID}))
check("/tx offer row shows the offer id, no POAScan swap link", OID in rows.get("Offer", "") and "/swap/" not in rows.get("Offer", "") and "Swap status" not in rows.get("Offer", ""))

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
    import http.client
    def head(path):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=20); c.request("GET", path); r = c.getresponse(); r.read(); return r.status, r.getheader("Location")
    got = [head(u) for u in ("/swap/" + OID, "/offer/" + OID, "/swap/" + "0" * 64, "/swap/" + OID + "/")]
    check(f"/swap/<id> and /offer/<id> 301 to POASwap, known or not ({got})", all(g == (301, "https://poaswap.io/") for g in got))
    c, b = get("/api/v1/swaps/" + OID); check("the API it mirrors still answers", c == 200 and json.loads(b)["offer"]["status"] == "filled")
finally:
    p.terminate(); p.wait(timeout=10)

if fails: print(f"\nFAIL: {len(fails)}: {fails}"); sys.exit(1)
print("\nPASS")
