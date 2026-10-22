"""Network upgrade, recovery phase: the checkpoint moved on, hosted routes reopen in stages.
Seeds the public facts of 2026-10-22 (checkpoint 33463, supply unchanged, hardening notice active, every hosted route paused),
then opens mining, then clears the notice, and checks the home strip (desktop and 390px line), /upgrade, the API and the
live snapshot follow by themselves. Also the route check itself: classification, fixed paths, no key, the 10 minute floor.
Usage: python3 tools/recovery_test.py"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
tmp = tempfile.mkdtemp(); DBP = os.path.join(tmp, "rec.db")
os.environ.update(POASCAN_DB=DBP, POASCAN_MAINTENANCE="1", POA_BASE="http://127.0.0.1:9"); os.environ.pop("POASCAN_JOIN_OPEN", None)
sys.path.insert(0, ROOT)
from poascan import db, hosted as R, maint as M
fails = []
def check(n, c): print(("ok   " if c else "FAIL ") + n); c or fails.append(n)

ROOTHASH = "f77320b999ac91e10c89aba31e570c9186f4a2a0a2471a9e4975c3271dbccdbf"
def seed(routes, notice=True):
    now = int(time.time())
    db.put_blob("status", {"network": "PoA prototype", "K": 5, "supply": "1234828243.783275", "txs": 1, "final": 0, "invalid": 0, "agents_joined": 3673,
                           "epochs_closed": 10, "holders": 629, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 60)),
                           "checkpoint_height": 33463, "state_root": ROOTHASH})
    db.put_blob("notices", {"active": [{"id": "2026-10-21-hardening", "severity": "action", "issued_ts": 1792614261, "expires_ts": now + 86400}] if notice else []})
    db.put_blob("ballots", {"ballots": []})
    db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,fails,next_at,bytes) VALUES('/api/explorer/txs',?,0,0,1)", (now,))
    db.put_blob(R.BLOB, {"routes": {k: {"state": routes.get(k, "paused"), "since": now - 600, "checked": now - 120} for k, _, _ in R.ROUTES}, "ts": now - 120})

# ---- the route check, in process
db.init()
check("classify: 503 with the halt text is paused; keyless 401/400/405 is open; 404, 429, 502 and a bare 503 are unknown",
      R.classify(503, b'{"error":"endpoint temporarily halted - API hardening in progress"}') == "paused" and all(R.classify(c) == "open" for c in (200, 400, 401, 405))
      and all(R.classify(c, b"x") is None for c in (404, 429, 502, 503)))
check("route list: the six hosted routes, fixed paths, no query string, no key",
      [k for k, _, _ in R.ROUTES] == ["mining", "grading", "send", "swap_offer", "vote", "export"]
      and all(p.startswith("/api/hosted/") and "?" not in p and "key" not in p for _, _, p in R.ROUTES))
try: R._get("/api/hosted/register"); off_list = False
except ValueError: off_list = True
check("route check refuses any path off its list", off_list)
calls = []
def fake(path):
    calls.append(path); return (503, b'{"error":"endpoint temporarily halted"}') if "mine" in path else (401, b"{}")
db.put_blob(R.BLOB, {}); R.job(now=time.time(), get=fake)
cur = R.current()
check("job: one GET per route, states stored", calls == [p for _, _, p in R.ROUTES] and cur["mining"]["state"] == "paused" and cur["grading"]["state"] == "open")
calls.clear(); R.job(now=time.time() + 300, get=fake)
check("job: never more than one round per 10 minutes, restarts included (floor kept in the database)", calls == [])
calls.clear(); R.job(now=time.time() + R.EVERY, get=lambda p: (calls.append(p), (429, b""))[1])
check("job: a 429 ends the round at once and keeps the last states", len(calls) == 1 and R.current()["grading"]["state"] == "open")
calls.clear(); R.job(now=time.time() + R.EVERY + 700, get=fake)
check("job: the round after trouble is skipped", calls == [])
m0 = M.MAINTENANCE; M.MAINTENANCE = False; calls.clear(); db.put_blob(R.BLOB, {}); R.job(now=time.time(), get=fake); M.MAINTENANCE = m0
check("job: no requests at all with the maintenance switch off", calls == [])
db.put_blob(R.BLOB, {"routes": {"mining": {"state": "paused", "since": 1, "checked": time.time() - 7200}}, "ts": 1})
check("a route read older than an hour reads as unknown (Checking), not paused", R.current()["mining"]["state"] == "unknown")

# ---- copy and live states, in process
seed({})
st = M.strip_text(); mb = M.strip_mobile(); s = M.state()
HL = "Recovery in progress: new checkpoint 33,463, balances intact. Mining and grading reopen in stages."
check(f"headline: {s['headline']!r}", s["headline"] == HL and st == ("Recovery in progress", ": new checkpoint 33,463, balances intact", "Mining and grading reopen in stages."))
check(f"headline at 390px is short: {s['headline_short']!r}", s["headline_short"] == "Recovering. Mining still paused." and len(s["headline_short"]) <= 36)
check("state: active, recovery phase, every route paused, notice active, supply intact, status fresh",
      s["active"] and s["phase"] == "recovery" and set(s["hosted_routes"].values()) == {"paused"} and s["notice"]["active"] is True
      and s["recovery"]["supply_intact"] and s["recovery"]["status_fresh"] and s["recovery"]["state_root"] == ROOTHASH and s["recovery"]["open_ballots"] == 0)
seed({"mining": "open"}); s = M.state()
check(f"mining open: {s['headline']!r} / {s['headline_short']!r}, still active while the notice is up",
      s["headline"] == "Mining reopened. Grading still paused." and s["headline_short"] == "Mining reopened. Grading paused." and s["active"] and "hosted_mining" not in s["paused"])
seed({"grading": "open"}); check("grading open: Grading reopened. Mining still paused.", M.state()["headline"] == "Grading reopened. Mining still paused.")
seed({"mining": "open", "grading": "open"}); check("both open: Mining and grading reopened. Other routes reopen in stages.",
      M.state()["headline"] == "Mining and grading reopened. Other routes reopen in stages." and "grading" not in M.state()["paused"])
seed({"mining": "open"}, notice=False); s = M.state()
check("mining open and the notice gone: maintenance clears itself (cleared_by mining_back)", s["active"] is False and s["cleared_by"] == "mining_back")
seed({}, notice=False); check("notice gone but mining still paused: stays on", M.state()["active"] is True)
# /api/status answering without checkpoint_height, state_root and as_of: the newest snapshot that had them carries on
seed({})
db.add_snap("status", {"checkpoint_height": 33463, "state_root": ROOTHASH, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 90))})
db.put_blob("status", {"supply": "1234828243.783275", "txs": 1, "final": 0, "epochs_closed": 10})
db.put_blob("status", dict(db.get_blob("status")[0], stale=True, stale_age_s=108, as_of=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 108))))
check("minepoa's stale flag on a 2 minute old read still reads fresh (same rule as the pill); 15 minutes old does not",
      M.recovery()["status_fresh"] and M.recovery()["status_stale_flag"])
db.put_blob("status", dict(db.get_blob("status")[0], as_of=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 900))))
check("a 15 minute old /api/status reads not fresh", M.recovery()["status_fresh"] is False)
db.put_blob("status", {"supply": "1234828243.783275", "txs": 1, "final": 0, "epochs_closed": 10})
r = M.recovery()
check("lean /api/status answer: checkpoint, state root and as_of come from our newest snapshot, the headline holds",
      r["moved"] and r["checkpoint"] == 33463 and r["state_root"] == ROOTHASH and r["status_fresh"] and M.strip_text()[0] == "Recovery in progress")
BAD = ("\u2014", "emblem.build", "Accounts", "vulnerab")
def clean(t): return [b for b in BAD if b in t]

# ---- end to end: server reads the same DB, pages and snapshot follow
seed({})
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_INDEXER="0")
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env)
def get(u):
    try: r = urllib.request.urlopen(urllib.request.Request(base + u, headers={"Accept": "text/html"}), timeout=30); return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, ""
try:
    for _ in range(100):
        try: urllib.request.urlopen(base + "/healthz", timeout=2); break
        except Exception: time.sleep(0.2)
    c, hm = get("/"); main = hm[hm.index("<main"):hm.index("</main>")]
    check("home strip: desktop line and the 390px line, Details to /upgrade, live hook",
          hm.count('class="upstrip"') == 1 and '<span data-upline><span class="upd"><b>Recovery in progress</b><span class="upx">: new checkpoint 33,463, balances intact</span>. Mining and grading reopen in stages.</span>'
          '<span class="upm"><b>Recovering</b>. Mining still paused.</span></span><a href="/upgrade">Details</a>' in hm)
    check(f"home main: no em dash, no 'Accounts', no outside docs {clean(main)}", not clean(main))
    c, up = get("/upgrade"); card = up[up.index('id="upgrade"'):]; card = card[:card.index("</section>")]
    dts = ["Now", "Routes", "Checkpoint", "Supply", "Status", "Epochs", "Notice", "Joining", "Working", "Safe", "Agents", "Last hour"]
    check("/upgrade: 200, rows in order", c == 200 and all(f"<dt>{k}</dt>" in card for k in dts) and [card.index(f"<dt>{k}</dt>") for k in dts] == sorted(card.index(f"<dt>{k}</dt>") for k in dts))
    check("/upgrade: route list Mining, Grading, Send, Swap offers, Voting, Export, all Paused, with live hooks",
          all(f'<li data-hroute="{k}"><span>{l}</span><span class="tag warn">Paused</span></li>' in card for k, l in
              (("mining", "Mining"), ("grading", "Grading"), ("send", "Send"), ("swap_offer", "Swap offers"), ("vote", "Voting"), ("export", "Export"))))
    check("/upgrade: checkpoint 33,463 up from 24,371 with the state root, supply to the decimal and intact",
          '<span class="num">33,463</span>, up from <span class="num">24,371</span>.' in card and f'title="{ROOTHASH}">f77320b999ac…1dbccdbf</code>' in card
          and '<span class="num">1,234,828,243.783275</span> POA, unchanged across the checkpoint. Balances intact.' in card)
    check("/upgrade: status fresh, counters restarted, 10 epochs closed, no open ballots, notice active",
          "<code>/api/status</code> is fresh, as of" in card and 'Tx counters restarted at the new checkpoint: <span class="num">1</span> tx, <span class="num">0</span> final.' in card
          and '<span class="num">10</span> closed. No open ballots.' in card and "<code>2026-10-21-hardening</code> active." in card)
    check("/upgrade: stages and health, hourly at a random minute, no retry loops, 16 epoch TTL; no reopen time, no 24 to 72",
          "Operators bring hosted endpoints back in stages while they watch system health." in card and "Check once an hour at a random minute. No retry loops." in card
          and "Pending grades keep 16 epochs." in card and "24 to 72" not in card and "hours" not in card.split('class="upa"')[0])
    check(f"/upgrade card: clean {clean(card)}", not clean(card))
    m = json.loads(get("/api/v1/status")[1] or "{}").get("meta", {}).get("maintenance") or {}
    check("API: meta.maintenance carries phase, headline, hosted_routes, notice and recovery",
          m.get("phase") == "recovery" and m.get("headline") == HL and m.get("hosted_routes", {}).get("export") == "paused"
          and (m.get("notice") or {}).get("active") is True and (m.get("recovery") or {}).get("checkpoint") == 33463)
    sm = json.loads(urllib.request.urlopen(base + "/api/v1/summary", timeout=20).read())
    check("summary pill: Upgrading, why carries the headline", sm.get("pill", {}).get("state") == "up")
    # mining reopens: nothing restarts, the pages follow
    seed({"mining": "open"})
    c, hm = get("/"); c, up = get("/upgrade")
    check("mining open: strip reads Mining reopened (desktop and 390px), /upgrade shows Mining Open and Grading Paused",
          "<b>Mining reopened</b><span class=\"upx\"></span>. Grading still paused.</span>" in hm and '<span class="upm"><b>Mining reopened</b>. Grading paused.</span>' in hm
          and '<li data-hroute="mining"><span>Mining</span><span class="tag ok">Open</span></li>' in up and '<li data-hroute="grading"><span>Grading</span><span class="tag warn">Paused</span></li>' in up
          and "Mining reopened. Grading still paused. Operators bring" in up)
    js = open(os.path.join(ROOT, "static", "app.js")).read(); css = open(os.path.join(ROOT, "static", "style.css")).read()
    check("client: snapshot updates the strip line and the route tags in place; 390px shows the short line",
          'var ul=$("[data-upline]")' in js and "s.upline" in js and "[data-hroute]" in js and ".upstrip .upd{display:none}.upstrip .upm{display:inline}" in css)
    # notice cleared with mining open: maintenance ends by itself
    seed({"mining": "open"}, notice=False)
    import http.client
    c, hm = get("/"); hc = http.client.HTTPConnection("127.0.0.1", port, timeout=20); hc.request("GET", "/upgrade"); rr = hc.getresponse(); c2 = rr.status; rr.read(); hc.close()
    check(f"mining back and notice gone: no strip, /upgrade redirects to Health ({c2}, strip {'class=\"upstrip\"' in hm})", 'class="upstrip"' not in hm and c2 == 302)
finally:
    p.terminate(); p.wait(10)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
