"""Feedback sweep (2026-10-23 gap review): tx and receipt 404s, archive fallback, open epoch, payout status, receipt
basis_state, established history. Temp database, no network: the node is http://127.0.0.1:9 (refused), so every
on-demand read fails the way a busy node does. Usage: python3 tools/feedback_test.py"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
os.environ.setdefault("POASCAN_SEGMENTS", "1")   # synthetic history is relative to now and spans the real genesis cut: one segment (segments.py)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "f.db")
os.environ.update(POASCAN_DB=DB, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
from poascan import db, analytics as A, indexer as I, maint as M, receipts as RC, agents as G
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

def addr(c): return "poa1" + c * 40
X, Y, Z, W = addr("X"), addr("Y"), addr("Z"), addr("W")
OLD, NONANS, UNKNOWN = "0a" * 32, "0b" * 32, "00" * 32
SET, PEND, VAN, GONE, PAIDABS, NEW = ("1a" * 32, "1b" * 32, "1c" * 32, "1d" * 32, "1e" * 32, "1f" * 32)
now = int(time.time()); P = 21600; t0 = now - 10 * P - 600   # closes E0..E9; the last one about 10 minutes ago

def close(n, **b):
    return {"epoch": n, "ts": t0 + (n + 1) * P, "pool": 1e9, "rewards": b.pop("rewards", {}), "challenges": b.pop("challenges", {}),
            "propagation": {}, "basis": dict({"pending": {}, "settled": [], "challenge_eligible": [], "established_after": [], "established_removed": []}, **b)}

db.init()
eps = [close(n) for n in range(10)]
eps[3]["basis"]["established_after"] = [X]
eps[6]["basis"]["established_removed"] = [X]
eps[8]["basis"]["established_after"] = [X]
eps[4]["basis"]["challenge_eligible"] = [X]; eps[4]["challenges"] = {X: "7731958.762886"}; eps[4]["rewards"] = {X: "1006134.83"}
eps[7]["basis"]["settled"] = [{"answer": SET, "from": X, "passed": True, "jury": [{"grader": Y, "aligned": True}]}]
eps[7]["rewards"] = {X: "5"}
eps[8]["basis"]["graders_served"] = {X: 3}
eps[9]["basis"]["pending"] = {PEND: {"kind": "short", "panel": [Y], "since": 9}}
eps[8]["basis"]["pending"] = {VAN: {"kind": "short", "panel": [], "since": 8}}
db.put_blob("epochs", eps)
db.put_blob("params", {"estab_ttl": 6, "auto_epoch_seconds": P, "grade_quorum": 4})
db.put_blob("status", {"epochs_closed": 10, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))})
def tx(i, typ, frm, ep, ts): db.write("INSERT INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)", (i, typ, frm, ep, ts, 5, 5, 1))
tx(OLD, "challenge", X, 6, t0 + 6 * P + 100)
db.write("INSERT INTO answers VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL)", (OLD, X, 6, t0 + 6 * P + 100, 22, 0, 0, "An a", now, "An archived E6 answer.", "en"))
tx(NONANS, "attest-batch", Y, 9, now - 3000)
tx(SET, "challenge", X, 7, t0 + 7 * P + 50); tx(PEND, "challenge", X, 9, t0 + 9 * P + 50)
tx(VAN, "challenge", X, 8, t0 + 8 * P + 50); tx(GONE, "challenge", X, 5, t0 + 5 * P + 50)
tx(PAIDABS, "challenge", X, 4, t0 + 4 * P + 50); tx(NEW, "challenge", X, 10, now - 60)
A._cache.clear()

# ---- item 5: open epoch follows answers tagged with the next epoch (3 distinct Agents), not a lagging close count
o = A.open_epoch()
check("open epoch: 10 from the close count while answers carry 10", o["epoch"] == 10 and o["last_close"] == t0 + 10 * P and not o["start_estimated"])
for i, a in enumerate((X, Y)): tx(f"2{i}" + "e" * 62, "challenge", a, 11, now - 30 + i)
check("open epoch: two Agents tagged 11 are not enough", A.open_epoch()["epoch"] == 10)
tx("22" + "e" * 62, "challenge", Z, 11, now - 20)
o = A.open_epoch()
check("open epoch: three Agents tagged 11 make it 11, start estimated from the first", o["epoch"] == 11 and o["start_estimated"] and o["last_close"] == now - 30)
db.put_blob("status", {"epochs_closed": 11}); o = A.open_epoch()
check("open epoch: the status read catching up keeps 11", o["epoch"] == 11)
db.put_blob("status", {"epochs_closed": 10})

# ---- item 7: payouts follow the notice, and grading
db.put_blob("notices", {"active": [{"id": "2026-10-22-grading-halted", "msg": "Mining, joins, answers & attestation earnings fully LIVE. Challenge GRADING is HALTED \u2014 answers accepted & safe, but grading + challenge-pool payouts paused until further notice.", "expires_ts": now + 3600}]})
check("payouts: the notice pauses challenge-pool payouts, attestation earnings working, no reward_payouts",
      "challenge_pool_payouts" in M.paused() and "attestation_earnings" in M.working() and "reward_payouts" not in M.working() + M.paused())
check("payouts: og line says attestation earnings live, not rewards paying", "attestation earnings live" in M.og_desc() and "rewards paying" not in M.og_desc())
db.put_blob("notices", {"active": [{"id": "2026-10-22-restored", "msg": "Challenge grading + pool payouts resume after the panel-stability fix.", "expires_ts": now + 3600}]})
check("payouts: 'pool payouts resume after' reads as paused", M.pool_payouts() == "paused")
db.put_blob("notices", {"active": [{"id": "old", "msg": "grading + challenge-pool payouts paused", "expires_ts": now - 10}]})
db.put_blob("hosted_routes", {"routes": {"grading": {"state": "open", "checked": now, "since": now}}})
from poascan import hosted as R
real_state = R.state
R.state = lambda rid: "open" if rid == "grading" else real_state(rid); M.grading_memo_clear()
check("payouts: expired notice and grading open: pool payouts working, rewards paying",
      M.pool_payouts() == "live" and "challenge_pool_payouts" in M.working() and "rewards paying" in M.og_desc())
R.state = lambda rid: "paused" if rid == "grading" else real_state(rid); M.grading_memo_clear()   # a patch, not a db write
check("payouts: no notice but grading paused: pool payouts paused", M.pool_payouts() == "paused" and "challenge_pool_payouts" in M.paused())
R.state = real_state
db.put_blob("notices", {"active": [{"id": "x", "msg": "grading + challenge-pool payouts paused", "expires_ts": now + 3600}]})

# ---- item 8: basis_state and the paid-but-absent class
A._cache.clear(); r = lambda t: RC.receipt(t)
check("receipt: settled", r(SET)["basis_state"] == "settled" and r(SET)["paid_via_challenge_eligible"] is False)
check("receipt: pending", r(PEND)["basis_state"] == "pending")
check("receipt: vanished is absent", r(VAN)["basis_state"] == "absent" and r(VAN)["status"] == "vanished")
check("receipt: never recorded is absent, not paid", r(GONE)["basis_state"] == "absent" and r(GONE)["paid_via_challenge_eligible"] is False and r(GONE)["challenge_eligible"] is False)
pa = r(PAIDABS)
check("receipt: absent but challenge-eligible with a challenges entry is paid_via_challenge_eligible",
      pa["basis_state"] == "absent" and pa["challenge_eligible"] is True and pa["challenges_amount"] == "7731958.762886" and pa["paid_via_challenge_eligible"] is True)
check("receipt: epoch not closed yet has no basis_state", r(NEW)["basis_state"] is None and r(NEW)["paid_via_challenge_eligible"] is None)
check("receipt: paid text names the class", "challenge-eligible, not in basis" in RC.paid_txt(pa))

# ---- item 4: established history
h = G.established_history(X)
check("established: added E3, removed E6, added E8, newest first", [(c["epoch"], c["change"]) for c in h["changes"]] == [(8, "added"), (6, "removed"), (3, "added")])
check("established: basis listed at E8, estimate yes", h["basis"] == "listed" and h["basis_epoch"] == 8 and h["established"] is True)
c6 = h["changes"][1]
check("established: E6 removal inputs (window E1 to E6: answered E4, E5, E6; no pass yet)", c6["answered"] == [4, 5, 6] and c6["passed"] == 0 and c6["seated"] == [])
check("established: E8 inputs count the E7 pass and the E8 seat", h["changes"][0]["passed"] == 1 and h["changes"][0]["seated"] == [8])
check("established: totals", h["answers"] >= 7 and h["passed"] == 1 and h["settled"] == 1 and h["epochs_paid"] == 2 and h["seated_closes"] == 1 and h["first_seen_ts"] == t0 + 4 * P + 50)
h0 = G.established_history(W)
check("established: unknown address is empty, not established", h0["basis"] == "none" and not h0["established"] and h0["answers"] == 0 and h0["changes"] == [])

# ---- server: /api/v1/tx, /api/v1/receipt, /api/v1/address/<a>/established, /address card
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def get(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r: return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
port = free_port(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1")
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=1); break
        except Exception: time.sleep(0.2)
    c, b = get(base + f"/api/v1/tx/{OLD}"); d = json.loads(b)
    check("tx: node down, archived E6 answer is 200 from the archive with its text", c == 200 and d.get("found") is True and d.get("source") == "archive"
          and d["body"].get("answer") == "An archived E6 answer." and d.get("epoch") == 6 and d.get("from_addr") == X)
    c, b = get(base + f"/api/v1/tx/{UNKNOWN}"); d = json.loads(b)
    check("tx: unknown is a JSON 404 with found false, not 503 or unknown endpoint", c == 404 and d.get("found") is False and d.get("tx") == UNKNOWN
          and d.get("error") == "transaction not found" and d.get("node") in ("unavailable", "not_found") and "answered_txid" in d.get("hint", ""))
    c, b = get(base + f"/api/v1/receipt/{UNKNOWN}"); d = json.loads(b)
    check("receipt: unknown is a JSON 404 with found false", c == 404 and d.get("found") is False and d.get("error") != "unknown endpoint")
    c, b = get(base + f"/api/v1/receipt/{NONANS}"); d = json.loads(b)
    check("receipt: a known non-answer tx says so", c == 404 and d.get("found") is True and d.get("answer") is False)
    c, b = get(base + f"/api/v1/receipt/{PAIDABS}"); d = json.loads(b)
    check("receipt API carries basis_state and paid_via_challenge_eligible", c == 200 and d.get("basis_state") == "absent" and d.get("paid_via_challenge_eligible") is True)
    c, b = get(base + "/api/v1/nope/thing"); check("a bad route still says unknown endpoint", c == 404 and json.loads(b).get("error") == "unknown endpoint")
    c, b = get(base + f"/api/v1/address/{X}/established"); d = json.loads(b)
    check("established API", c == 200 and d.get("basis") == "listed" and len(d.get("changes", [])) == 3 and d.get("method", "").endswith("/about#established"))
    c, b = get(base + f"/address/{X}")
    card = b[b.find('id="established"') - 200:]; card = card[:card.find("</section>") + 10] if "</section>" in card else card[:4000]
    check("address page: Established history card with Added at the E8 close and the change rows",
          c == 200 and "Established history" in b and "Added at the E8 close" in b and "E6 close" in b and "our estimate" in b)
    check("address page: no em or en dashes in the card", "\u2014" not in card and "\u2013" not in card)
    c, b = get(base + "/upgrade")
    check("/upgrade: Challenge-pool payouts under Still paused", c == 200 and "Challenge-pool payouts" in b[b.find('data-grp="paused"'):] if 'data-grp="paused"' in b else False)
    c, b = get(base + "/openapi.json"); spec = json.loads(b)
    check("openapi: established route and receipt basis_state", "/api/v1/address/{address}/established" in spec.get("paths", {}) or "/api/address/{address}/established" in spec.get("paths", {}))
finally:
    p.terminate(); p.wait(10)

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
