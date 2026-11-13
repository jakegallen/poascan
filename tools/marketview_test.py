"""Token page market view (1.26.322): last fill, open depth excluding expired offers, ask-only book
and fill history from ingested data only. Bids are never invented. At 390 px the view stays inside
the viewport. Usage: python3 tools/marketview_test.py"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "mkt.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POA_BASE"] = "http://127.0.0.1:9"
os.environ["POASCAN_MAINTENANCE"] = "0"
sys.path.insert(0, ROOT)

from poascan import db
import importlib
from poascan.swap import market as M, store as S
from poascan import swapclient as SC
SA = importlib.import_module('poascan.swap.api')

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

check("no em or en dash in this test", not any(chr(0x2013) in ln or chr(0x2014) in ln for ln in open(__file__, encoding="utf-8")))

db.init()
now = int(time.time())

def put(oid, status, poa, want, asset="SOL", chain="solana", exp=None, fill_ts=None, fill_txid=None, maker="poa1maker"):
    db.write("INSERT OR REPLACE INTO swaps(offer_id,maker,poa,chain,asset,want,expires_ts,created_ts,status,fill_ts,fill_txid,last_open_seen,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (oid, maker, poa, chain, asset, want, exp, now - 86400, status, fill_ts, fill_txid, now - 60, now))

# one live ask, one stored-as-open but already expired, one fill
put("live-ask", "open", 1_000_000, 0.2, exp=now + 3600)
put("expired-ask", "open", 5_000_000, 0.1, exp=now - 60)
put("filled", "filled", 10_000, 0.004, fill_ts=now - 120, fill_txid="f"*64)

st = M.swap_stats()
check("open depth counts only the unexpired ask (1M POA, 1 offer); the expired 5M is out",
      st["open"] == 1 and abs(st["on_offer"] - 1_000_000) < 1e-6
      and st["open_depth"]["offers"] == 1 and abs(st["open_depth"]["poa"] - 1_000_000) < 1e-6)
mk = M.swap_market()
check("swap_market.open_depth matches and last_trade is the fill",
      mk["open_depth"] == st["open_depth"] and mk["last_trade"] and mk["last_trade"]["asset"] == "SOL"
      and mk["poa_on_offer"] == st["on_offer"])
asks, last = M.book()
check("book asks are the live offer only, expired out",
      len(asks) == 1 and asks[0]["id"] == "live-ask" and all(o["id"] != "expired-ask" for o in asks))
bk = SC.book()
check("swapclient.book is ask-only: bids is an empty list, never estimated",
      bk["bids"] == [] and len(bk["asks"]) == 1 and bk["asks"][0]["id"] == "live-ask")

# list serve reapplies expiry even when the cache still holds status=open
SA._rc.clear()
stale = dict(offer_id="cached-open", status="open", expires_ts=now - 30, poa=100, want=0.001, asset="SOL", chain="solana")
SA._rc["/api/swaps"] = (time.time(), SA._version(), ([stale], True, 'W/"test"'))
rows, is_list = SA.api("/api/swaps", {})
check("cached /api/swaps row past expires_ts reads expired on serve (cache not mutated in place)",
      is_list and rows[0]["status"] == "expired" and stale["status"] == "open")
open_rows = [r for r in S.swaps_all() if r["status"] == "open"]
check("swaps_all effective() already drops the expired stored-open row from status=open",
      {r["offer_id"] for r in open_rows} == {"live-ask"})

# HTTP + 390 px screenshot path
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

tmp = tempfile.mkdtemp(); port = free_port()
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "h.db"),
           POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True, capture_output=True)
# insert the same three offers into the fixture db used by the server
import sqlite3
cx = sqlite3.connect(env["POASCAN_DB"])
cx.execute("INSERT OR REPLACE INTO swaps(offer_id,maker,poa,chain,asset,want,expires_ts,created_ts,status,fill_ts,fill_txid,last_open_seen,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
           ("live-ask", "poa1maker", 1_000_000, "solana", "SOL", 0.2, now + 3600, now - 86400, "open", None, None, now - 60, now))
cx.execute("INSERT OR REPLACE INTO swaps(offer_id,maker,poa,chain,asset,want,expires_ts,created_ts,status,fill_ts,fill_txid,last_open_seen,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
           ("expired-ask", "poa1maker", 5_000_000, "solana", "SOL", 0.1, now - 60, now - 86400, "open", None, None, now - 60, now))
cx.execute("INSERT OR REPLACE INTO swaps(offer_id,maker,poa,chain,asset,want,expires_ts,created_ts,status,fill_ts,fill_txid,last_open_seen,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
           ("filled", "poa1maker", 10_000, "solana", "SOL", 0.004, None, now - 86400, "filled", now - 120, "f"*64, now - 60, now))
cx.commit(); cx.close()

srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f"http://127.0.0.1:{port}"
try:
    for _ in range(80):
        try: urllib.request.urlopen(base + "/healthz", timeout=1); break
        except Exception: time.sleep(.25)
    else:
        check("server started", False); raise SystemExit(1)

    def get(path):
        with urllib.request.urlopen(base + path, timeout=20) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}

    class NoRedir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    opener = urllib.request.build_opener(NoRedir)
    try:
        opener.open(base + "/swaps", timeout=10)
        code, loc = 200, ""
    except urllib.error.HTTPError as e:
        code, loc = e.code, e.headers.get("Location") or e.headers.get("location") or ""
    check("/swaps still redirects to POASwap", code in (301, 302) and "poaswap.io" in (loc or ""))

    mkt, stc = {}, 0
    for _ in range(20):
        stc, body, _ = get("/api/v1/swaps/status")
        mkt = (json.loads(body).get("market") or {}) if stc == 200 else {}
        if isinstance(mkt.get("open_depth"), dict): break
        time.sleep(0.2)
    od = mkt.get("open_depth") or {}
    poa_d = float(od.get("poa") or 0)
    check("HTTP swaps/status open_depth excludes the expired 5M ask (live 1M is in, fixture asks may add)",
          stc == 200 and "poa" in od and "offers" in od
          and poa_d >= 1_000_000 - 1e-6 and abs(poa_d - 6_000_000) > 1
          and poa_d < 6_000_000 - 1)

    lst, raw, _ = get("/api/v1/swaps?status=open")
    opens = json.loads(raw)
    check("HTTP ?status=open does not include the expired stored-open offer",
          lst == 200 and {r["offer_id"] for r in opens} == {"live-ask"})

    html = get("/network?tab=token")[1].decode()
    check("Token page shows Last fill, Open depth and the market view",
          "Last fill" in html and "Open depth" in html and 'id="token-market"' in html)
    check("Token book is ask-only: No bids, and no invented bid rows",
          "No bids" in html and 'class="bid"' not in html)
    check("expired ask id is not in the open book", 'data-offer="expired-ask"' not in html)
    check("live ask and fill history are on the page", 'data-offer="live-ask"' in html and "Fill history" in html)

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        sync_playwright = None
        check("Playwright is installed in CI", not os.environ.get("CI"))
        print("skip browser checks (Playwright not installed)")

    if sync_playwright:
        shot_dir = os.path.join(tmp, "shots"); os.makedirs(shot_dir, exist_ok=True)
        with sync_playwright() as p:
            kw = {"executable_path": os.environ["PW_CHROME"]} if os.environ.get("PW_CHROME") else {}
            b = p.chromium.launch(args=["--no-sandbox"], **kw)
            for w, h in ((390, 844), (1280, 900)):
                pg = b.new_page(viewport={"width": w, "height": h})
                errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(base + "/network?tab=token", wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(400)
                visible = pg.evaluate("""() => {
                  const ids = ['token-market'];
                  const labels = [...document.querySelectorAll('.sl,.stat .sl,dt,h2')].map(e => e.textContent.trim());
                  const mkt = document.getElementById('token-market');
                  const r = mkt ? mkt.getBoundingClientRect() : null;
                  return {
                    labels,
                    hasMarket: !!mkt,
                    marketW: r ? Math.round(r.width) : 0,
                    ox: document.documentElement.scrollWidth - innerWidth,
                    noBids: (mkt && mkt.innerText.includes('No bids')) || false,
                    lastFill: labels.some(t => /Last fill/i.test(t)),
                    openDepth: labels.some(t => /Open depth/i.test(t)),
                    bidRows: document.querySelectorAll('#token-market tr.bid, #token-market .bid').length,
                    expired: !!document.querySelector('#token-market [data-offer="expired-ask"]'),
                    live: !!document.querySelector('#token-market [data-offer="live-ask"]'),
                  };
                }""")
                shot = os.path.join(shot_dir, f"token-market-{w}.png")
                pg.locator("#token-market").screenshot(path=shot) if visible["hasMarket"] else pg.screenshot(path=shot)
                check(f"{w} px screenshot path wrote {os.path.basename(shot)} ({os.path.getsize(shot)} bytes)",
                      os.path.isfile(shot) and os.path.getsize(shot) > 1000)
                check(f"{w} px: Last fill, Open depth and the market view are on the page",
                      visible["lastFill"] and visible["openDepth"] and visible["hasMarket"])
                check(f"{w} px: No bids, no invented bid rows, expired ask out, live ask in",
                      visible["noBids"] and visible["bidRows"] == 0 and not visible["expired"] and visible["live"])
                check(f"{w} px: no horizontal overflow (ox={visible['ox']})", visible["ox"] <= 0)
                check(f"{w} px: no page errors {errs[:2]}", not errs)
                pg.close()
            b.close()
finally:
    srv.terminate()
    try: srv.wait(timeout=10)
    except Exception: srv.kill()

print("\n" + ("all passed" if not fails else f"{len(fails)} failed: {fails}"))
sys.exit(1 if fails else 0)
