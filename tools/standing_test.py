"""Established standing expiry estimate (analytics.established_expiry_est): L is the Agent's last challenge_eligible epoch;
standing is expected to drop at close L + estab_ttl + 1 (L + 7 today). An estimate from observed behavior, labelled so on
every surface, null when unknown (not established, trusted grader, no eligible epoch on record, or the close already passed).
Grading seats don't refresh it. Checks the address page Established card, /api/v1/address/<a>/established, MCP get_address,
/about#established-expiry and that the join prompt is untouched.
Usage: python3 tools/standing_test.py            (temp database, no network)
       python3 tools/standing_test.py --check FILE  (also checks every established_removed entry at E8+ in a saved /api/epochs dump)"""
import hashlib, json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
TMP = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(TMP, "t.db")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from poascan import db, analytics as A

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)
def addr(c): return "poa1" + c * 40
OLD, MID, FRESH, NEVER, SEATED, TRUST, SEATONLY = (addr(c) for c in "OMFNSTQ")

def close(n, ts, elig=(), after=(), removed=(), served=()):
    return {"epoch": n, "ts": ts, "pool": 1e9, "rewards": {}, "challenges": {}, "propagation": {},
            "basis": {"challenge_eligible": list(elig), "established_after": list(after), "established_removed": list(removed),
                      "graders_served": {a: 1 for a in served}}}

def check_dump(path):
    """Every established_removed entry at close N (N >= 8) has its last challenge_eligible epoch at N - estab_ttl - 1."""
    E = json.load(open(path)); ttl = 6; last = {}; bad = 0; seen = 0
    for e in sorted(E, key=lambda r: int(r["epoch"])):
        n = int(e["epoch"]); b = e.get("basis") or {}
        for a in b.get("challenge_eligible") or []: last[a] = n
        if n < 8: continue
        for a in b.get("established_removed") or []:
            seen += 1; bad += last.get(a) != n - ttl - 1
    check(f"dump: {seen} removals at E8+ all at last eligible + {ttl} + 1", seen > 0 and bad == 0)

def seed():
    db.init(); now = time.time(); last_ts = now - 600
    db.put_blob("params", {"estab_ttl": 6, "auto_epoch_seconds": 21600, "trusted_graders": [TRUST]})
    db.put_blob("status", {"epochs_closed": 11})
    E = [close(n, last_ts - (10 - n) * 21600) for n in range(11)]
    E[1]["basis"].update(challenge_eligible=[OLD, SEATED], established_after=[OLD, SEATED])
    E[3]["basis"].update(challenge_eligible=[MID, OLD, TRUST], established_after=[MID])
    E[5]["basis"].update(challenge_eligible=[FRESH], established_after=[FRESH])
    E[9]["basis"].update(challenge_eligible=[FRESH])
    E[8]["basis"]["established_removed"] = [SEATED]            # last eligible 1: drops at close 8
    E[8]["basis"]["graders_served"] = {SEATED: 5}              # a grading seat does not refresh standing
    E[10]["basis"]["established_removed"] = [OLD, MID]          # last eligible 3: drops at close 10
    E[10]["basis"]["graders_served"] = {SEATONLY: 2}            # established from a seat, never challenge_eligible
    db.put_blob("epochs", E)
    db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,ts,atts,final) VALUES(?,?,?,?,?,?)", ("c1" * 32, "challenge", FRESH, int(now) - 3600, 5, 1))
    A._cache.clear()
    return E

def main():
    E = seed()
    f = A.established_expiry_est(FRESH)
    check("last challenge_eligible epoch is the latest one (9), not the first", f["last_challenge_eligible_epoch"] == 9)
    check("estimate is close L + estab_ttl + 1 (16)", f["established_expires_epoch_est"] == 16)
    check("basis says observed estimate, not official, with L and estab_ttl", "estimate" in f["established_expires_basis"] and "not an official rule" in f["established_expires_basis"]
          and "epoch 9" in f["established_expires_basis"] and "estab_ttl 6" in f["established_expires_basis"])
    check("the rule matches the fixture removals", all(A.last_eligible()[a] + 6 + 1 == n for n in (8, 10) for a in E[n]["basis"]["established_removed"]))
    for a, why in ((OLD, "removed (not established)"), (SEATED, "removed after a seat (seats don't refresh)"), (NEVER, "never eligible"),
                   (TRUST, "trusted grader"), (SEATONLY, "established from a seat, no eligible epoch on record")):
        x = A.established_expiry_est(a)
        check(f"null when unknown: {why}", x["established_expires_epoch_est"] is None and x["established_expires_basis"] is None)
    check("SEATONLY reads established (so the null is the unknown case, not the not-established one)", SEATONLY in A.established_set())
    db.put_blob("status", {"epochs_closed": 17}); A._cache.clear()
    check("null once the estimated close has passed while still established", A.established_expiry_est(FRESH)["established_expires_epoch_est"] is None)
    db.put_blob("status", {"epochs_closed": 11}); A._cache.clear()
    c = A.established_expiry_counts()
    check(f"counts: one Agent with an estimate, soonest close 16 ({c})", c == dict(with_estimate=1, soonest=16))
    check("note: an estimate from observed behavior, not official, seats don't refresh, no dashes",
          "Estimate from observed behavior, not an official rule" in A.STANDING_NOTE and "Grading seats don't refresh" in A.STANDING_NOTE
          and not re.search("[\u2013\u2014]", A.STANDING_NOTE))
    from poascan import start as S
    check("join prompt template_sha256 unchanged (990e681f)", S.template_sha256() == "990e681f0dada4bc9bf65c032c9e8f8b0d8b459c7fdd67276c16bde172ffd60f")
    if "--check" in sys.argv: check_dump(sys.argv[sys.argv.index("--check") + 1])
    # rendered surfaces
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
    srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(u, data=None, h=None):
        try:
            with op.open(urllib.request.Request(base + u, data, h or {}), timeout=30) as r: return r.status, r.read().decode()
        except urllib.error.HTTPError as e: return e.code, e.read().decode()
    try:
        for _ in range(100):
            try: get("/healthz"); break
            except Exception: time.sleep(0.2)
        c, j = get(f"/api/v1/address/{FRESH}/established"); d = json.loads(j)
        check(f"API established ({c}): established_expires_epoch_est 16 with basis", c == 200 and d.get("established_expires_epoch_est") == 16 and "estimate" in (d.get("established_expires_basis") or ""))
        c, j = get(f"/api/v1/address/{SEATONLY}/established"); d = json.loads(j)
        check(f"API established ({c}): null when unknown (keys present)", c == 200 and "established_expires_epoch_est" in d and d["established_expires_epoch_est"] is None and d["established_expires_basis"] is None)
        H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        c, j = get("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_address", "arguments": {"address": FRESH, "tx_limit": 5}}}).encode(), H)
        sc = json.loads(j)["result"].get("structuredContent") or {}
        check("MCP get_address carries the estimate at the top and in established_history", sc.get("established_expires_epoch_est") == 16 and "estimate" in (sc.get("established_expires_basis") or "")
              and (sc.get("established_history") or {}).get("established_expires_epoch_est") == 16)
        c, j = get("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(), H)
        ga = [t["description"] for t in json.loads(j)["result"]["tools"] if t["name"] == "get_address"][0]
        check("MCP get_address description names the field as an estimate, null when unknown", "established_expires_epoch_est" in ga and "estimate" in ga and "null when unknown" in ga)
        c, h = get(f"/address/{FRESH}")
        row = re.search(r'<div class="kv"><span>Est\. expires</span><div>(.*?)</div></div>', h, re.S)
        check(f"address page ({c}): Est. expires row reads E16 close, labelled estimate, tooltip says not official",
              c == 200 and row is not None and "E16 close" in row.group(1) and "estimate" in row.group(1) and "not an official rule" in row.group(1))
        c, h = get(f"/address/{SEATONLY}")
        check(f"address page ({c}): no Est. expires row when unknown", c == 200 and "Est. expires" not in h)
        c, h = get("/about")
        m = re.search(r'<p id="established-expiry">(.*?)</p>', h, re.S)
        check("/about#established-expiry: the methodology line, estimate, not official, L + 7, seats don't refresh", c == 200 and m is not None
              and "not an official rule" in m.group(1) and "L + 7" in m.group(1) and "Grading seats don't refresh standing" in m.group(1) and 'id="established"' in h)
        check("no em or en dashes on the new surfaces", not re.search("[\u2013\u2014]", (m.group(1) if m else "") + (row.group(1) if row else "")))
    finally:
        srv.terminate()
        try: srv.wait(10)
        except Exception: srv.kill()
    print("\n%d failure(s)" % len(fails) if fails else "\nall ok"); sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
