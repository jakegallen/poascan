"""Network upgrade, recovery phase: the checkpoint moved on, hosted routes reopen in stages.
Seeds the public facts of 2026-10-22 (checkpoint 33463, supply unchanged, hardening notice active, every hosted route paused),
then opens mining, then clears the notice, and checks the home strip (desktop and 390px line), /upgrade, the API and the
live snapshot follow by themselves. Also the route check itself: classification, fixed paths, no key, the 10 minute floor.
Usage: python3 tools/recovery_test.py"""
import json, os, re as _re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
tmp = tempfile.mkdtemp(); DBP = os.path.join(tmp, "rec.db")
os.environ.update(POASCAN_DB=DBP, POASCAN_MAINTENANCE="1", POA_BASE="http://127.0.0.1:9"); os.environ.pop("POASCAN_JOIN_OPEN", None)
sys.path.insert(0, ROOT)
from poascan import db, hosted as R, maint as M
fails = []
def check(n, c): print(("ok   " if c else "FAIL ") + n); c or fails.append(n)

ROOTHASH = "f77320b999ac91e10c89aba31e570c9186f4a2a0a2471a9e4975c3271dbccdbf"
def seed(routes, notice=True, mining=None):
    now = int(time.time())
    db.put_blob("status", {"network": "PoA prototype", "K": 5, "supply": "1234828243.783275", "txs": 1, "final": 0, "invalid": 0, "agents_joined": 3673,
                           "epochs_closed": 10, "holders": 629, "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 60)),
                           "checkpoint_height": 33463, "state_root": ROOTHASH})
    db.put_blob("notices", {"active": [{"id": "2026-10-21-hardening", "severity": "action", "issued_ts": 1792614261, "expires_ts": now + 86400}] if notice else []})
    db.put_blob("ballots", {"ballots": []})
    db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,fails,next_at,bytes) VALUES('/api/explorer/txs',?,0,0,1)", (now,))
    rr = {k: {"state": routes.get(k, "paused"), "since": now - 600, "checked": now - 120} for k, _, _ in R.ROUTES}
    if mining: rr["mining"].update(mining)
    db.put_blob(R.BLOB, {"routes": rr, "ts": now - 120})
def reset_official():
    db.write("DELETE FROM forum_comments"); db.write("DELETE FROM forum_posts"); db.write("DELETE FROM blobs WHERE kind IN (?, ?)", (M.OFFICIAL_BLOB, "mining_back"))

# ---- the route check, in process
db.init()
check("classify: 503 with the halt text is paused; a keyless JSON 401/400/405 is open; an HTML edge page is not; 404, 429, 502 and a bare 503 are unknown",
      R.classify(503, b'{"error":"endpoint temporarily halted - API hardening in progress"}') == "paused" and all(R.classify(c, b'{"error":"missing key"}') == "open" for c in (200, 400, 401, 405))
      and R.classify(403, b"<!DOCTYPE html><title>Just a moment</title>") is None and R.classify(401, b"") is None
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
check("a clear read older than an hour keeps its state and time (flagged stale), never turns unknown", R.current()["mining"]["state"] == "paused"
      and R.current()["mining"]["stale"] is True and R.current()["mining"]["since"] == 1 and R.current()["grading"]["state"] == "unknown")
# unknown reads (timeout, network error, odd status) never change the shown state, its since or its checked time
t0 = int(time.time()); db.put_blob(R.BLOB, {"routes": {"mining": {"state": "open", "since": t0 - 5000, "checked": t0 - 4000, "code": 401, "streak": 3}}, "ts": t0 - 4000})
def boom(path): raise TimeoutError("timed out")
R.job(now=t0, get=boom); a = R.current()["mining"]
R.job(now=t0 + R.EVERY, get=lambda p: (404, b"<html>")); b = R.current()["mining"]
R.job(now=t0 + 2 * R.EVERY, get=lambda p: (200, b"<html>maintenance</html>")); c = R.current()["mining"]
check("unknown reads keep the last known state: timeout, 404 and an HTML 200 leave mining open with its since and checked",
      all(x["state"] == "open" and x["since"] == t0 - 5000 and x["checked"] == t0 - 4000 and x["streak"] == 3 for x in (a, b, c)) and c["tried"] == t0 + 2 * R.EVERY)
R.job(now=t0 + 3 * R.EVERY, get=fake); d1 = R.current()["mining"]; R.job(now=t0 + 4 * R.EVERY, get=fake); d2 = R.current()["mining"]
R.job(now=t0 + 5 * R.EVERY, get=boom); d3 = R.current()["mining"]
check("a timeout marks the route slow and keeps its last state; a clear read clears slow", a["slow"] and a["state"] == "open" and not d1["slow"] and d3["slow"])
check("unknown reads that do answer (404, HTML 200) are not slow, and keep the state", not b["slow"] and not c["slow"] and b["state"] == "open")
check("clear halted reads change it and count in a row; an unknown read in between neither resets nor adds",
      (d1["state"], d1["streak"], d2["streak"], d3["streak"], d3["state"]) == ("paused", 1, 2, 2, "paused"))

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
check(f"probe open but nothing official: {s['headline']!r} / {s['headline_short']!r}; never 'reopened', route reads Responding, still paused in the API, still active",
      s["headline"] == "Mining endpoint responding: some endpoints are back. Grading still paused." and s["headline_short"] == "Mining endpoint responding. Grading paused."
      and "reopened" not in s["headline"] + s["headline_short"] and s["hosted_routes_display"]["mining"] == "responding" and s["hosted_routes"]["mining"] == "open"
      and s["hosted_mining"] == "paused" and "hosted_mining" in s["paused"] and s["active"] and s["official"]["mining"] is False and s["cleared_by"] is None)
seed({"grading": "open"}); check("grading probe open: Grading endpoint responding: some endpoints are back. Mining still paused.", M.state()["headline"] == "Grading endpoint responding: some endpoints are back. Mining still paused.")
# official signal 2: the post 1357 author says mining is back (from the forum mirror); hedged or other authors never count
OP = "e02b5ebb251437fb20134e00"
db.write("INSERT OR REPLACE INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
         (M.POST_ID, "poa", "Network hardening in progress", "agent_" + OP, OP, "2026-10-21 19:00:51", 6, 3, 0, 1, int(time.time()),
          "Expect mining to be mostly unavailable during this window. Mining is back once the surface is cleared."))
def comment(i, who, body): db.write("INSERT OR REPLACE INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body) VALUES(?,?,?,?,?,?,?,?)",
                                    (i, M.POST_ID, None, "agent_" + who, who, "2026-10-22 22:40:00", 0, body))
comment(9001, "someoneelse0000000000000", "Mining is back! Just mined.")
comment(9002, OP, "Mining will be back soon. Mining is not back yet.")
seed({"mining": "open"}); s = M.state()
check("hedged operator words, other authors and the hedged post body are not official", s["official"]["mining"] is False and s["headline"].startswith("Mining endpoint responding"))
comment(9003, OP, "Update: hosted mining is now re-enabled. Grading follows.")
s = M.state()
check(f"operator comment on 1357 says mining is re-enabled: official (post), headline {s['headline']!r}, route reads Open, maintenance stays on during the grace",
      {k: s["official"][k] for k in ("mining", "routes", "source")} == {"mining": True, "routes": False, "source": "post"} and s["official"]["mining_at"]
      and s["headline"] == "Mining reopened: some endpoints are back. Grading still paused."
      and s["headline_short"] == "Mining reopened. Grading paused." and s["hosted_routes_display"]["mining"] == "open" and s["active"] and s["mining_back_at"])
back0 = M.state()["mining_back_at"]; oat = M.official()["mining_at"]
seed({}, mining={"state": "unknown"}); db.put_blob(R.BLOB, {"routes": {}, "ts": 1}); s = M.state()
check("official, then the mining route reads unknown: still Mining reopened, mining_back_at unchanged", s["headline"].startswith("Mining reopened") and s["mining_back_at"] == back0)
db.write("DELETE FROM forum_comments"); db.write("DELETE FROM forum_posts"); s = M.state()
check("official persisted: a gap in the forum mirror does not clear it", s["official"]["mining"] is True and s["headline"].startswith("Mining reopened") and s["mining_back_at"] == back0)
def fresh(code):
    """Run code in a new process on the same database: a restart or deploy."""
    r = subprocess.run([sys.executable, "-c", "import sys, json; sys.path.insert(0, %r)\nfrom poascan import db, maint as M, hosted as R\n" % ROOT + code],
                       capture_output=True, text=True, env=dict(os.environ), timeout=60)
    return json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {"err": r.stderr[-400:]}
seed({"mining": "unknown"}); db.put_blob(R.BLOB, {"routes": {}, "ts": 1})
rs = fresh("s = M.state(); print(json.dumps(dict(o=s['official']['mining'], at=s['mining_back_at'], h=s['headline'], hm=s['hosted_mining'])))")
check(f"restart: the official signal and mining_back_at come back from the database, with no forum post and no route read ({rs})",
      rs.get("o") is True and rs.get("at") == back0 and rs.get("h", "").startswith("Mining reopened") and rs.get("hm") == "back")
saved = db.get_blob("mining_back")[0]
db.write("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?,?,?)", ("mining_back", M.BUG_CLEARED_TS, "{}"))
db.write("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?,?,?)", (M.OFFICIAL_BLOB, M.BUG_CLEARED_TS + 600, json.dumps({"mining_at": M.BUG_CLEARED_TS + 600, "source": "post"})))
rs = fresh("print(json.dumps(dict(at=M.state()['mining_back_at'])))")
check(f"the empty blob 1.26.17 left at 00:16:36Z is restored to 23:45:49Z ({rs})", rs.get("at") == "2026-10-22T23:45:49Z")
db.write("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?,?,?)", ("mining_back", M.BUG_CLEARED_TS + 1, "{}"))
rs = fresh("print(json.dumps(dict(at=M.state()['mining_back_at'])))")
check("any other empty blob starts a fresh clock, never the restored time", rs.get("at") not in (None, "2026-10-22T23:45:49Z"))
db.put_blob("mining_back", saved); db.put_blob(M.OFFICIAL_BLOB, {"mining_at": oat, "source": "post"})
seed({}); s = M.state()
check("a halted read from before the official time does not undo it", s["headline"].startswith("Mining reopened") and s["mining_back_at"] == back0)
seed({}, mining={"since": oat + 5, "streak": 1}); s = M.state()
check("one clear halted read after the official time: still Mining reopened", s["headline"].startswith("Mining reopened") and s["mining_back_at"] == back0)
seed({}, mining={"since": oat + 5, "streak": 2}); s = M.state()
check(f"two clear halted reads in a row after the official time: {s['headline']!r} / {s['headline_short']!r}, not back",
      s["headline"] == "Mining paused again. Grading still paused." and db.get_blob("mining_back")[0].get("ended") and s["headline_short"] == "Mining paused again. Grading paused."
      and s["mining_back_at"] is None and s["hosted_mining"] == "paused" and "reopened" not in s["headline"])
seed({"mining": "open"}); s = M.state()
check("an open read after that: Mining reopened again, a new mining_back_at", s["headline"].startswith("Mining reopened") and s["mining_back_at"] and not db.get_blob("mining_back")[0].get("ended"))
# the live case of 00:24Z: mining and send time out (no answer at all), grading halted, the other three answering
nw = int(time.time())
db.put_blob(R.BLOB, {"routes": {"mining": {"state": "open", "since": nw - 9000, "checked": nw - 5000, "slow_since": nw - 3000},
                                "send": {"state": "open", "since": nw - 9000, "checked": nw - 5000, "slow_since": nw - 3000},
                                "grading": {"state": "paused", "since": nw - 9000, "checked": nw - 200},
                                **{k: {"state": "open", "since": nw - 9000, "checked": nw - 200} for k in ("swap_offer", "vote", "export")}}, "ts": nw - 200})
s = M.state(); from poascan import views2 as V2; uv = V2.upgrade_view()
check(f"slow routes: {s['headline']!r} / {s['headline_short']!r}, mining and send Slow, grading Paused",
      s["headline"] == "Mining reopened: some endpoints are slow. Grading still paused." and s["headline_short"] == "Mining reopened. Grading paused."
      and s["hosted_routes_display"]["mining"] == "slow" and s["hosted_routes_display"]["send"] == "slow" and s["hosted_routes_display"]["grading"] == "paused"
      and s["hosted_mining"] == "back" and s["mining_back_at"])
paused_grp = uv.split('data-grp="paused"')[1].split("</div>")[0] if 'data-grp="paused"' in uv else ""
check("/upgrade with slow routes: Slow tags with last answered, never Checking or offline, Still paused holds only Grading, meter counts 3 of 6 answering",
      uv.count('<em class="tag warn slow">Slow</em>') == 2 and "Last answered" in uv and "Checking" not in uv and "offline" not in uv.lower()
      and "Grading" in paused_grp and "Mining" not in paused_grp and "Send" not in paused_grp and 'data-grp="slow"' in uv
      and '<span class="green">3</span> of 6' in uv)
reset_official()
seed({"send": "open", "export": "open"}); s = M.state()
check(f"two of six open, not mining or grading: {s['headline']!r}", s["headline"] == "Recovery in progress: about a third of endpoints are back. Mining and grading reopen in stages."
      and s["headline_short"] == "Recovering. Mining still paused.")
seed({"send": "open", "export": "open", "vote": "open"}); check("three of six: about half", M.state()["headline"].startswith("Recovery in progress: about half of endpoints are back."))
seed({}); db.put_blob(R.BLOB, {}); check("no route read at all: 'some endpoints are back', never a measured fraction", M.state()["headline"] == "Recovery in progress: some endpoints are back. Mining and grading reopen in stages.")
seed({"mining": "open", "grading": "open"}); check("both probe open, nothing official: Mining and grading endpoints responding: about a third of endpoints are back.",
      M.state()["headline"] == "Mining and grading endpoints responding: about a third of endpoints are back. Other routes reopen in stages.")
seed({"mining": "open", "grading": "open"}, notice=False); s = M.state()
check(f"official signal 1, notice gone: {s['headline']!r}, routes Open, source notice", s["headline"] == "Mining and grading reopened: about a third of endpoints are back. Other routes reopen in stages."
      and s["official"]["source"] == "notice" and s["hosted_routes_display"]["grading"] == "open" and s["active"] and "grading" not in s["paused"])
db.put_blob("mining_back", {"at": int(time.time()) - M.BACK_GRACE_S - 60})
check("6 hours after the official signal, maintenance ends (cleared_by mining_back)", M.state()["active"] is False and M.state()["cleared_by"] == "mining_back")
reset_official(); seed({}, notice=False); s = M.state()
check("notice gone (official) with one old halted read: mining reopened, a fresh grace clock, still on", s["active"] is True and s["mining_back_at"] and s["headline"].startswith("Mining reopened"))
seed({}, notice=False, mining={"since": M.official()["mining_at"] + 5, "streak": 2}); s = M.state()
check("notice gone but mining clearly halted twice since: paused again, stays on, the grace clock ends", s["active"] is True and s["mining_back_at"] is None
      and s["headline"].startswith("Mining paused again"))
reset_official()
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
          '<span class="upm"><b>Recovering</b>. Mining still paused.</span></span><span data-upstamp><span class="upts">Updated <time data-upts="' in hm
          and _re.search(r'<span data-upstamp><span class="upts">Updated <time data-upts="\d+" datetime="[0-9T:-]+Z">\d\d:\d\dZ</time></span></span><a href="/upgrade">Details</a>', hm))
    check(f"home main: no em dash, no 'Accounts', no outside docs {clean(main)}", not clean(main))
    c, up = get("/upgrade"); card = up[up.index("<main"):up.index("</main>")]
    hero = card[card.index('class="uph"'):card.index('class="stats four uptiles"')]
    check("/upgrade: 200, own layout: hero first, no Network tab strip, no Health panels, one small link to Health",
          c == 200 and card.index('class="uph"') < card.index("uptiles") < card.index('class="updet"') and "atabs" not in card and "Latency p50" not in card
          and "Uptime · 7d" not in card and "Incidents" not in card and card.count('<a href="/network?tab=health">Uptime and latency on Health</a>') == 1)
    check("/upgrade hero: Recovery in progress, Updated stamp, sub-line, routes meter 0 of 6 with six Paused segments",
          '<h1 class="uph-t" id="uph-t">Recovery in progress</h1>' in hero and _re.search(r'<span class="upts">Updated <time data-upts="\d+"[^>]*>\d\d:\d\dZ</time></span>', hero)
          and '<p class="uph-s">Mining and grading reopen in stages.</p>' in hero and '<span class="lbl">Endpoints responding</span><b class="mtr-n"><span class="green">0</span> of 6</b>' in hero
          and all(f'<li class="seg" data-hroute="{k}" data-st="paused"><i></i><span><b>{l}</b><em class="tag warn">Paused</em></span></li>' in hero for k, l in
                  (("mining", "Mining"), ("grading", "Grading"), ("send", "Send"), ("swap_offer", "Swap offers"), ("vote", "Voting"), ("export", "Export"))))
    wk = hero[hero.index('data-grp="working"'):]; wk = wk[:wk.index("</ul>")]; wt = hero[hero.index('data-grp="paused"'):]; wt = wt[:wt.index("</ul>")]
    check("/upgrade groups: Working has balances, supply, checkpoint, explorer, self-custody; Still paused has the six routes",
          all(f"<span>{t}</span>" in wk for t in ("Balances intact", "Supply unchanged", "Checkpoint 33,463", "Explorer live", "Self-custody mining"))
          and all(f"<span>{t}</span>" in wt for t in ("Mining", "Grading", "Send", "Swap offers", "Voting", "Export")))
    tl = card[card.index("uptiles"):card.index('class="updet"')]
    check("/upgrade tiles: Checkpoint 24,371 to 33,463, Supply unchanged 1.23B, Answers 1h, Epochs closed 10; no sub-lines",
          '<span class="from">24,371 →</span> <span class="num">33,463</span>' in tl and ">Supply unchanged<" in tl and "1.23B" in tl and ">Answers · 1h<" in tl
          and ">Epochs closed<" in tl and ">10<" in tl and 'class="asof"' not in tl)
    dtl = card[card.index('<details class="updet"'):]
    check("/upgrade details (collapsed): full state root, notice active, /api/status fresh with stamp and counters, how we check, Agents guidance, prompt",
          "<details" in dtl and "<details open" not in dtl and f'<code class="sr">{ROOTHASH}</code>' in dtl and "<code>2026-10-21-hardening</code> active" in dtl
          and 'Fresh, <span class="upts">as of <time data-upts=' in dtl and "Tx counters restarted at the new checkpoint: 1 tx, 0 final." in dtl
          and '<span class="upts">at <time data-upts=' in dtl and "Check once an hour at a random minute. No retry loops." in dtl and "Pending grades keep 16 epochs." in dtl
          and dtl.count('class="pbox"') == 1)
    check("/upgrade: no reopen time, no 24 to 72, never 'reopened' while nothing is official", "24 to 72" not in card and "reopened" not in card and " hours" not in card.split('class="upa"')[0])
    check(f"/upgrade: clean {clean(card)}", not clean(card))
    c, stp = get("/start")
    check("/start: the live status strip carries the Updated stamp", '<p class="upstrip stup" role="status" data-live>' in stp and '<span class="upts">Updated <time data-upts=' in stp.split('class="upstrip stup"')[1][:1500])
    c, hl = get("/network?tab=health")
    check("Health: one compact recovery line with the headline and stamp, links /upgrade; no hero, groups or route meter",
          hl.count('class="uphl"') == 1 and "Recovery in progress: new checkpoint 33,463, balances intact." in hl and '<a href="/upgrade">Recovery details</a>' in hl
          and 'class="uph"' not in hl and "data-grp" not in hl and 'class="seg"' not in hl)
    c, fr = get("/fragment/upgrade")
    check("/fragment/upgrade serves the live view with its signature; the snapshot carries upsig", c == 200 and fr.startswith('<div data-upview data-sig="') and 'class="uph"' in fr)
    m = json.loads(get("/api/v1/status")[1] or "{}").get("meta", {}).get("maintenance") or {}
    check("API: meta.maintenance carries phase, headline, hosted_routes, notice and recovery",
          m.get("phase") == "recovery" and m.get("headline") == HL and m.get("hosted_routes", {}).get("export") == "paused"
          and (m.get("notice") or {}).get("active") is True and (m.get("recovery") or {}).get("checkpoint") == 33463)
    sm = json.loads(urllib.request.urlopen(base + "/api/v1/summary", timeout=20).read())
    check("summary pill: Upgrading, why carries the headline", sm.get("pill", {}).get("state") == "up")
    # mining reopens: nothing restarts, the pages follow
    seed({"mining": "open"})
    c, hm = get("/"); c, up = get("/upgrade")
    check("probe open, not official: strip reads Mining endpoint responding (desktop and 390px), /upgrade shows Mining Responding and Grading Paused, never reopened",
          "<b>Mining endpoint responding</b><span class=\"upx\">: some endpoints are back</span>. Grading still paused.</span>" in hm and '<span class="upm"><b>Mining endpoint responding</b>. Grading paused.</span>' in hm
          and '<li class="seg" data-hroute="mining" data-st="responding">' in up and ">Responding<" in up and "<span>Mining responding</span>" in up
          and '<h1 class="uph-t" id="uph-t">Mining endpoint responding</h1>' in up and '<p class="uph-s">Some endpoints are back. Grading still paused.</p>' in up
          and '<span class="green">1</span> of 6' in up and "reopened" not in hm[hm.index("<main"):] and "reopened" not in up[up.index("<main"):])
    js = open(os.path.join(ROOT, "static", "app.js")).read(); css = open(os.path.join(ROOT, "static", "style.css")).read()
    check("client: snapshot updates the strip line and the route tags in place; 390px shows the short line",
          'var ul=$("[data-upline]")' in js and "s.upline" in js and "s.upstamp" in js and 'timeZoneName:"short"' in js and '" \\u00b7 "' in js and "[data-hroute]" in js and ".upstrip .upd{display:none}.upstrip .upm{display:inline}" in css)
    # notice cleared with mining open: maintenance ends by itself
    seed({"mining": "open"}, notice=False); db.put_blob("mining_back", {"at": int(time.time()) - M.BACK_GRACE_S - 60})
    import http.client
    c, hm = get("/"); hc = http.client.HTTPConnection("127.0.0.1", port, timeout=20); hc.request("GET", "/upgrade"); rr = hc.getresponse(); c2 = rr.status; rr.read(); hc.close()
    check(f"mining back and notice gone: no strip, /upgrade redirects to Health ({c2}, strip {'class=\"upstrip\"' in hm})", 'class="upstrip"' not in hm and c2 == 302)
finally:
    p.terminate(); p.wait(10)
print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
