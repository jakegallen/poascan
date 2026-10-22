"""Every main route renders (HTTP 200) with maintenance on, joining paused (derived) and swap rows present (open and filled,
with events, attestations and verified chain links). Usage: python3 tools/routes_test.py"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROUTES = ["/", "/start", "/upgrade", "/epochs", "/txs", "/agents", "/token", "/network", "/about", "/swaps", "/status",
          "/network?tab=health", "/api/v1/swaps", "/api/v1/swaps.csv", "/api/v1/swaps/status", "/api/v1/status", "/api/v1/summary"]

def seed(path):
    os.environ["POASCAN_DB"] = path
    import fixture; fixture.seed()
    from poascan import db
    now = int(time.time()); A1, A2 = "poa1" + "A" * 40, "poa1" + "B" * 40; O1, F1, O2 = "a1" * 32, "f1" * 32, "a2" * 32
    cols = "offer_id,maker,poa,chain,asset,want,pay_to,expires_ts,created_ts,status,taker,fill_txid,fill_ts,fee_bp,updated"
    db.write(f"INSERT OR REPLACE INTO swaps({cols}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             [(O1, A1, 10000, "solana", "SOL", 0.01, "So1Pay", now + 3600, now - 900, "filled", A2, F1, now - 300, 100, now),
              (O2, A2, 5000, "base", "ETH", 0.002, "0xpay", now + 3600, now - 600, "open", None, None, None, 100, now)], many=True)
    db.write("INSERT OR REPLACE INTO swap_events VALUES(?,?,?,?,?,?)",
             [(O1, O1, "swap-offer", A1, now - 900, "{}"), (F1, O1, "swap-fill", A2, now - 300, "{}"), (O2, O2, "swap-offer", A2, now - 600, "{}")], many=True)
    db.write("INSERT OR REPLACE INTO txs(id,type,from_addr,ts,atts,final) VALUES(?,?,?,?,?,?)",
             [(F1, "swap-fill", A2, now - 300, 5, 1), ("e0" * 32, "join", A2, now - 3 * 3600, 9, 1)], many=True)
    db.write("DELETE FROM txs WHERE type='join' AND ts > ?", (now - 3 * 3600,))   # last join 3 h ago: joining reads paused
    db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,fails,next_at,bytes) VALUES('/api/explorer/txs',?,0,0,1)", (now,))
    db.put_blob("chains", {A1: {"solana": {"addr": "So1Maker", "verified": True}}, A2: {"ethereum": {"addr": "0xabc", "verified": True}}})
    db.put_blob("fx", {"SOL": 150.0, "ETH": 3000.0, "src": "CoinGecko"})

def main():
    tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp, "r.db")
    subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {os.path.dirname(os.path.abspath(__file__))!r}); import routes_test as R; R.seed({dbp!r})"], check=True, cwd=ROOT)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=dbp, POASCAN_INDEXER="0", POASCAN_MAINTENANCE="1")
    env.pop("POASCAN_JOIN_OPEN", None)
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env)
    fails = []
    try:
        for _ in range(100):
            try: urllib.request.urlopen(base + "/healthz", timeout=2); break
            except Exception: time.sleep(0.2)
        st = json.loads(urllib.request.urlopen(base + "/api/v1/status", timeout=20).read()).get("meta", {}).get("maintenance") or {}
        ok = st.get("active") and st.get("join_state") == "paused" and st.get("join_open") is True
        print(("ok   " if ok else "FAIL ") + f"state: maintenance active, joining paused ({st.get('active')}, {st.get('join_state')})"); ok or fails.append("state")
        for r in ROUTES:
            try: c = urllib.request.urlopen(base + r, timeout=30).status
            except urllib.error.HTTPError as e: c = e.code
            except Exception as e: c = type(e).__name__
            print(("ok   " if c == 200 else "FAIL ") + f"GET {r} -> {c}"); c == 200 or fails.append(r)
        st_html = urllib.request.urlopen(base + "/start", timeout=20).read().decode()
        home = urllib.request.urlopen(base + "/", timeout=20).read().decode()
        llms = urllib.request.urlopen(base + "/llms-full.txt", timeout=20).read().decode()
        import re as _re
        upg = urllib.request.urlopen(base + "/upgrade", timeout=20).read().decode(); hl = urllib.request.urlopen(base + "/network?tab=health", timeout=20).read().decode()
        pr = lambda h: _re.search(r"<dt>Paused</dt><dd>([^<]*)</dd>", h)
        ok = ("Hosted mining and joining paused" in home and "Joining is paused during the upgrade. Your agent may need to retry later." in st_html
              and all(pr(h) and "joining" in pr(h).group(1).lower() and "<dt>Delayed</dt>" not in h for h in (upg, hl))
              and not any("delayed" in t.lower() for t in (home, st_html, upg, hl)))
        print(("ok   " if ok else "FAIL ") + "joining reads paused on home, /start, /upgrade and health; no delayed wording"); ok or fails.append("paused wording")
        bad = [x for x in ("Show me the api_key", "save it offline", "two warnings", "to save offline", "Save the key offline") for t in (st_html, home, llms) if x.lower() in t.lower()]
        ok = not bad and "LAST4" in st_html and "secret store" in st_html and "Ignore any step that shows the key" in st_html and "LAST4" in llms
        print(("ok   " if ok else "FAIL ") + f"key rule: never shown, stored in a secret store, confirmed as LAST4 {bad}"); ok or fails.append("key rule")
        d = json.loads(urllib.request.urlopen(base + "/api/v1/swaps", timeout=20).read())
        rows = d if isinstance(d, list) else d.get("rows") or d.get("data") or []
        f = next((x for x in rows if x.get("status") == "filled"), {})
        ok = [e["event"] for e in f.get("timeline", [])] == ["offered", "filled"] and f.get("fill_final") is True and f.get("fill_atts") == 5 \
            and f.get("maker_chains") == {"solana": "So1Maker"} and f.get("taker_chains") == {"ethereum": "0xabc"} and f.get("fee_poa") == 100.0
        print(("ok   " if ok else "FAIL ") + "swap rows carry timeline, chains, fee_poa, fill_atts, fill_final"); ok or fails.append("swap fields")
        o = next((x for x in rows if x.get("status") == "open"), {})
        ok = "fill_final" not in o and "fee_poa" not in o and "taker_chains" not in o
        print(("ok   " if ok else "FAIL ") + "open offers leave fill-only fields out"); ok or fails.append("open fields")
    finally:
        p.terminate()
    print(f"{len(fails)} failed" if fails else "all passed"); sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
