"""Established standing expiry estimate (analytics.established_expiry_est): L is the Agent's last challenge_eligible epoch;
standing is expected to drop at close L + estab_ttl + 1 (L + 7 today). An estimate from observed behavior, labelled so on
every surface, null when unknown (not established, trusted grader, no eligible epoch on record, or the close already passed).
Grading seats don't refresh it. Checks the address page Established card, /api/v1/address/<a>/established, MCP get_address,
/about#established-expiry and that the join prompt is untouched.
Usage: python3 tools/standing_test.py            (temp database, no network)
       python3 tools/standing_test.py --check FILE  (also checks every established_removed entry at E8+ in a saved /api/epochs dump)"""
import hashlib, json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
os.environ.setdefault("POASCAN_SEGMENTS", "1")   # synthetic history is relative to now and spans the real genesis cut: one segment (segments.py)
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
    db.put_blob("params", {"estab_ttl": 6, "K": 5, "auto_epoch_seconds": 21600, "trusted_graders": [TRUST]})
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
    check("basis names minepoa's engine rule with L and estab_ttl (1.26.140)", "engine rule" in f["established_expires_basis"] and "estimate" in f["established_expires_basis"]
          and "close 9" in f["established_expires_basis"] and "estab_ttl 6" in f["established_expires_basis"])
    check("closes left counts the open epoch's close as 1 (6)", f["established_expires_closes_left"] == 6)
    o = A.open_epoch()
    check("estimated time is the open close plus a period per later close", o.get("est_close") and f["established_expires_ts_est"] == int(o["est_close"] + 5 * 21600))
    check("closes left and time are null when unknown", A.established_expiry_est(NEVER)["established_expires_closes_left"] is None and A.established_expiry_est(NEVER)["established_expires_ts_est"] is None)
    check("the rule matches the fixture removals", all(A.last_eligible()[a] + 6 + 1 == n for n in (8, 10) for a in E[n]["basis"]["established_removed"]))
    for a, why in ((OLD, "removed (not established)"), (SEATED, "removed after a seat (seats don't refresh)"), (NEVER, "never eligible"),
                   (TRUST, "trusted grader, never added (not established)"), (SEATONLY, "a seat alone is not standing (not established)")):
        x = A.established_expiry_est(a)
        check(f"null when unknown: {why}", x["established_expires_epoch_est"] is None and x["established_expires_basis"] is None)
    check("engine rule: seats and trusted graders are not established (1.26.140)", SEATONLY not in A.established_set() and TRUST not in A.established_set())
    db.put_blob("status", {"epochs_closed": 17}); A._cache.clear()
    check("null once the estimated close has passed while still established", A.established_expiry_est(FRESH)["established_expires_epoch_est"] is None)
    db.put_blob("status", {"epochs_closed": 11}); A._cache.clear()
    c = A.established_expiry_counts()
    check(f"counts: one Agent with an estimate, soonest close 16 ({c})", c == dict(with_estimate=1, soonest=16))
    check("note: minepoa's engine rule, L -1 when none, seats don't keep standing, no dashes",
          "minepoa's engine removes" in A.STANDING_NOTE and "-1 when none" in A.STANDING_NOTE and "don't keep standing" in A.STANDING_NOTE
          and not re.search("[\u2013\u2014]", A.STANDING_NOTE))
    from poascan import start as S
    check("join prompt template_sha256 unchanged (410e5ee6, v2.9.1)", S.template_sha256() == "410e5ee62626a008f66bc4b0fae9f783d06453c25b9777aff8312a651dd63be8")
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
        check("MCP get_address adds closes left and the estimated time", sc.get("established_expires_closes_left") == 6 and isinstance(sc.get("established_expires_ts_est"), int))
        c, j = get(f"/api/v1/address/{FRESH}/established"); d = json.loads(j)
        check("API established: closes left 6 and an estimated time", d.get("established_expires_closes_left") == 6 and isinstance(d.get("established_expires_ts_est"), int))
        c, j = get("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(), H)
        ga = [t["description"] for t in json.loads(j)["result"]["tools"] if t["name"] == "get_address"][0]
        check("MCP get_address description names the field as an estimate, null when unknown", "established_expires_epoch_est" in ga and "estimate" in ga and "null when unknown" in ga)
        c, h = get(f"/address/{FRESH}")
        row = re.search(r'<div class="kv"><span>Est\. expires</span><div>(.*?)</div></div>', h, re.S)
        check(f"address page ({c}): Est. expires row reads E16 close, labelled estimate, tooltip says not official",
              c == 200 and row is not None and "E16 close" in row.group(1) and "estimate" in row.group(1) and "engine removes" in row.group(1))
        check("address page: Est. expires gives closes left and an estimated time (tooltip from data-ts)", row is not None and "in 6 closes, " in row.group(1)
              and re.search(r'<time class="t" data-ts="\d+">~(3[0-9]|2[0-9])h</time>', row.group(1)) is not None)
        check("no em or en dashes on the Est. expires row", row is not None and not re.search("[\u2013\u2014]", row.group(1)))
        check("address page: a future close is plain text, not a link to a missing epoch page", row is not None and "/epoch/16" not in row.group(1))
        lc = re.search(r'<div class="kv"><span>Last cleared</span><div>(.*?)</div></div>', h, re.S)
        check("address page: Last cleared row names the last challenge_eligible epoch (E9) and the K=5 bar (LabLeak 1357 c3553)",
              lc is not None and '<a href="/epoch/9">E9</a>' in lc.group(1) and "cleared K=5 attestations at the close" in lc.group(1))
        check("address page: Est. expires says last cleared + 7 and links the method", row is not None and "last cleared + 7" in row.group(1) and 'href="/about#established-expiry"' in row.group(1)
              and h.index("<span>Last cleared</span>") < h.index("<span>Est. expires</span>"))
        from poascan import views as VV
        h3 = VV.established_card(OLD); lc3 = re.search(r'<div class="kv"><span>Last cleared</span><div>(.*?)</div></div>', h3, re.S)
        check("Established card: Last cleared shows even with no expiry estimate (removed Agent, E3)", lc3 is not None and ">E3<" in lc3.group(1) and "Est. expires" not in h3)
        check("Last cleared reads Never for an Agent that answered but no close lists", VV._last_cleared({"last_challenge_eligible_epoch": None, "answers": 4}).startswith("Never")
              and VV._last_cleared({"last_challenge_eligible_epoch": None, "answers": 0}) == "···")
        check("no em or en dashes on the Last cleared row", lc is not None and not re.search("[\u2013\u2014]", lc.group(1)))
        db.put_blob("status", {"epochs_closed": 16}); A._cache.clear(); time.sleep(16)   # the server's epoch caches expire
        c, h = get(f"/address/{FRESH}"); row2 = re.search(r'<div class="kv"><span>Est\. expires</span><div>(.*?)</div></div>', h, re.S)
        check("address page: the close links once that epoch has a page (open epoch)", row2 is not None and '<a href="/epoch/16">E16</a> close' in row2.group(1))
        db.put_blob("status", {"epochs_closed": 11})
        c, h = get(f"/address/{SEATONLY}")
        check(f"address page ({c}): no Est. expires row when unknown", c == 200 and "Est. expires" not in h)
        c, h = get("/about")
        m = re.search(r'<p id="established-expiry">(.*?)</p>', h, re.S)
        check("/about#established-expiry: the engine decay rule, L + 7, -1 drops at E6, seats don't keep standing", c == 200 and m is not None
              and "decay rule" in m.group(1) and "L + 7" in m.group(1) and "seats don\'t" in m.group(1) and "E6 close" in m.group(1) and 'id="established"' in h)
        check("no em or en dashes on the new surfaces", not re.search("[\u2013\u2014]", (m.group(1) if m else "") + (row.group(1) if row else "")))
    finally:
        srv.terminate()
        try: srv.wait(10)
        except Exception: srv.kill()
    print("\n%d failure(s)" % len(fails) if fails else "\nall ok"); sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
