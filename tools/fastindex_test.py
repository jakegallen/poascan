"""Fast index (fastindex.py, anchorsview.py): a local fake index on 127.0.0.1, a temp database, no network.
Checks: off without FAST_INDEX_URL; the cursor sync stores segment rows into txs (backfill pages, then one page a run),
never an invalid tx; a final tx detail comes from the index with no minepoa.com read, a pending one goes to minepoa.com
and the index copy is the fallback; seal links from bodies (never the blob) and per answer counts with coverage; the
per minute caps and the 429 hold; external wallet resolution in search and /api/v1/resolve; the anchor timeline (gaps,
mismatch flag, sortable headers, ranges, watermark chart, no gaps); the Fast index feed row and status note line;
/api/v1/health fast_index never carries the URL; OpenAPI, llms.txt, MCP tools, /about; and no build host name in the repo.
Usage: python3 tools/fastindex_test.py"""
import os, sys, tempfile, time, json, re, threading, http.server, urllib.parse, socketserver
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["POA_BASE"] = "http://127.0.0.1:9"   # minepoa.com unreachable: any read we did not expect fails loudly
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

NOW = int(time.time())
H = lambda c, i=0: (c * 63 + format(i % 16, "x"))[:64]
A1, A2, A3 = ("poa1" + c * 40 for c in "ABC")
START = 1792875660   # segment 2 start (segments.json)
ANS = H("a", 1); ANS2 = H("a", 2)
TXS = []
for i in range(25):   # 25 rows: 2 pages of 10 then 5
    TXS.append(dict(id=H("1", i)[:-2] + format(i, "02x"), type="challenge" if i % 5 == 0 else "grade-sealed", from_addr=A1 if i % 2 else A2, to_addr="", amount="",
                    epoch=1 if i % 5 == 0 else None, ts=NOW - 7200 + i * 60, memo="", atts=8, final=1))
TXS.append(dict(id=H("e", 0), type="transfer", from_addr=A1, to_addr=A2, amount="5.000000", epoch=None, ts=NOW - 3000, memo="", atts=8, final=1))
TXS.append(dict(id=H("f", 0), type="genesis-identity", from_addr=A1, to_addr="", amount="", epoch=None, ts=START - 20, memo="", atts=0, final=1))   # before the segment start
TXS.append(dict(id=H("9", 9), type="transfer", from_addr=A1, to_addr=A2, amount="1", epoch=None, ts=NOW - 2900, memo="", atts=8, final=1))       # minepoa refused it
TXS.sort(key=lambda r: (r["ts"], r["id"]))
SEALS = [r for r in TXS if r["type"] == "grade-sealed"]
BODIES = {r["id"]: dict(r, body=dict(type="grade-sealed", assignment=ANS if j % 3 else ANS2, blob="SEALEDBLOB" + str(j), ts=r["ts"], sig="s")) for j, r in enumerate(SEALS)}
FINAL_TX = dict(id=H("c", 0), type="transfer", from_addr=A1, to_addr=A2, amount="2.5", epoch=None, ts=NOW - 4000, atts=8, final=1, memo="",
                body=dict(type="transfer", to=A2, amount="2.5", nonce=3, parents=[H("d", 0)], cid="poa-mainnet-1", sig="SIG", ts=NOW - 4000))
PEND_TX = dict(FINAL_TX, id=H("c", 1), final=0, atts=2)
ANCH = [dict(height=0, chain="base-mainnet", tx="0x" + "0" * 64, state_root="", ts="2026-10-24T21:12:30.000Z"),
        dict(height=0, chain="solana-mainnet", tx="S0", state_root="", ts="2026-10-24T21:12:30.000Z")]
for k, h in enumerate((100, 200, 300)):
    t = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(NOW - 7200 + k * 1800))
    ANCH += [dict(height=h, chain="base-mainnet", tx="0x" + format(h, "064x"), state_root=format(h, "064x"), ts=t),
             dict(height=h, chain="solana-mainnet", tx="SOL" + str(h), state_root=format(h, "064x") if h != 300 else "f" * 64, ts=t)]
EXT = [dict(address="0xAbCdEf0000000000000000000000000000000001", network="ethereum", poa_address=A3, verified=1),
       dict(address="7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU", network="solana", poa_address=A2, verified=1)]
STATE = dict(mode="ok", hits=[], ua=[], hdrs=[])

class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query); p = u.path
        STATE["hits"].append(p.rsplit("/", 1)[-1]); STATE["ua"].append(self.headers.get("User-Agent")); STATE["hdrs"].append(dict(self.headers))
        if STATE["mode"] == "429": return self._send(429, {"error": "slow"}, {"Retry-After": "120"})
        if STATE["mode"] == "down": return self._send(503, {"error": "down"})
        if not p.startswith("/x/api/"): return self._send(404, {"error": "not found"})
        ep = p[len("/x/api/"):]
        if ep == "overview": return self._send(200, dict(rows=[dict(txs=len(TXS), identities=3, addresses=2, anchors=len(ANCH), chain="poa-mainnet-1", max_synced_ts=str(NOW - 400), synced_at=str(NOW - 300), newest_tx_ts=NOW - 400)], ok=True))
        if ep == "txs":
            lim = int(q.get("limit", ["1000"])[0]); lim = min(lim, 10); cur = q.get("cursor", [None])[0]
            rows = TXS
            if cur:
                ts, i = cur.split(":"); rows = [r for r in TXS if (r["ts"], r["id"]) > (int(ts), i)]
            rows = rows[:lim]
            d = dict(rows=rows, ok=True)
            if rows: d["next_cursor"] = f'{rows[-1]["ts"]}:{rows[-1]["id"]}'
            return self._send(200, d)
        if ep == "tx":
            t = q.get("q", [""])[0]
            r = BODIES.get(t) or (FINAL_TX if t == FINAL_TX["id"] else PEND_TX if t == PEND_TX["id"] else None)
            return self._send(200, dict(rows=[r] if r else [], ok=True))
        if ep == "anchors": return self._send(200, dict(rows=ANCH, ok=True))
        if ep == "ext-addresses": return self._send(200, dict(rows=EXT, ok=True))
        if ep == "address": return self._send(200, dict(rows=[dict(poa_address=A1, balance="42.000000", invited_by="", tx_count=3, external="")], history=[], ok=True))
        if ep == "resolve":
            t = q.get("q", [""])[0]
            return self._send(200, dict(rows=[dict(kind="external:solana", poa=A1)] if t == "So1anaWa11etAddre55xxxxxxxxxxxxxxxxxxxx1" else [], ok=True))
        return self._send(404, {"error": "not found"})
    def _send(self, code, d, hd=None):
        b = json.dumps(d).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        for k, v in (hd or {}).items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

class TS(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True

def main():
    from poascan import fastindex as FX0
    check("off without FAST_INDEX_URL: no feed row, no reads, no line", not FX0.enabled() and FX0.feed() is None and FX0.pill_line() is None and FX0.tx_detail(H("c", 0)) is None and FX0.public_state() == {"enabled": False})
    srv = TS(("127.0.0.1", 0), Fake); threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/x"
    os.environ["FAST_INDEX_URL"] = base
    import importlib
    from poascan import db, fastindex as FX
    FX = importlib.reload(FX)
    FX.LIMIT = 10; FX.PAGES = 2; FX.PAGE_GAP_S = 0; FX.BODIES_PER_MIN = 4
    from poascan import indexer as I
    I._FX = FX
    from poascan import server as SV, agentapi as AG, views as V, analytics as A, anchorsview as AV, ui as UI
    AG._FX = FX; SV.FX = FX
    db.init(); FX.init()
    db.write("INSERT INTO invalid_txs(txid, error, first_seen) VALUES(?,?,?)", (H("9", 9), "bad sig", NOW))
    db.put_blob("status", {"checkpoint_height": 200, "state_root": format(200, "064x"), "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW))})
    check("enabled with FAST_INDEX_URL", FX.enabled())

    # ---- sync: backfill pages, then one page a run
    STATE["hits"].clear()
    FX.sync(sleep=lambda s: None)
    n1 = db.q1("SELECT COUNT(*) AS n FROM txs WHERE source='fast-index'")["n"]
    check(f"first run: overview plus PAGES=2 tx pages ({STATE['hits']})", STATE["hits"][:3] == ["overview", "txs", "txs"])
    check(f"backfill stores 19 rows, the pre-segment row skipped ({n1})", n1 == 19)
    for _ in range(3): FX.sync(sleep=lambda s: None)
    n2 = db.q1("SELECT COUNT(*) AS n FROM txs WHERE source='fast-index'")["n"]
    check(f"caught up: every segment row stored ({n2}), the pre-segment row and the refused tx never", n2 == len(TXS) - 2
          and not db.q1("SELECT 1 AS x FROM txs WHERE id=?", (H("f", 0),)) and not db.q1("SELECT 1 AS x FROM txs WHERE id=?", (H("9", 9),)))
    st = FX._state(); cur = db.get_blob("fx:cursor:s2")[0]
    check("cursor and caught_up stored per segment", cur["caught_up"] and cur["cursor"].endswith(TXS[-1]["id"]) and st["segment"] == 2)
    STATE["hits"].clear(); FX.sync(sleep=lambda s: None)
    check(f"steady state: overview plus one tx page ({STATE['hits']})", STATE["hits"][:2] == ["overview", "txs"] and STATE["hits"].count("txs") == 1)
    check("anchors and external links stored on the slow clock", db.q1("SELECT COUNT(*) AS n FROM fx_anchors")["n"] == 8 and db.q1("SELECT COUNT(*) AS n FROM fx_ext")["n"] == 2)
    check("every request plain: our User-Agent, no Authorization or Cookie", all(u == FX.UA for u in STATE["ua"]) and not any("Authorization" in h or "Cookie" in h for h in STATE["hdrs"]))
    check("new_to_archive counts rows minepoa had not given us, by type", st.get("new_to_archive") == len(TXS) - 2 and st["new_by_type"].get("transfer") == 1)

    # ---- tx detail: final from the index, no minepoa read; pending goes to minepoa and falls back to the index copy
    up0 = sum(I._counts.values()) if hasattr(I, "_counts") else None
    d = I.get_tx_detail(FINAL_TX["id"])
    check("final tx from the index (signed body, detail_source), stored for good", d and d["body"]["sig"] == "SIG" and d["detail_source"] == "indexed cache"
          and db.q1("SELECT final FROM tx_detail WHERE id=?", (FINAL_TX["id"],))["final"] == 1)
    h0 = len(STATE["hits"]); d2 = I.get_tx_detail(FINAL_TX["id"])
    check("a stored final tx is never read again", d2["id"] == FINAL_TX["id"] and len(STATE["hits"]) == h0)
    p = I.get_tx_detail(PEND_TX["id"])
    check("pending tx: minepoa.com tried (unreachable here), the index copy shown, not stored as final", p and p["final"] is False and not (db.q1("SELECT final FROM tx_detail WHERE id=?", (PEND_TX["id"],)) or {}).get("final"))
    html = V.tx(FINAL_TX["id"]); html = html[1] if isinstance(html, tuple) else html
    check("tx page renders the index copy without a 'not yet' finalized height", "SIG"[:2] in html and "not yet" not in html)

    # ---- seal bodies and counts
    FX._win.clear(); FX._vwin.clear()
    STATE["hits"].clear(); got = FX.bodies(sleep=lambda s: None)
    check(f"bodies: at most BODIES_PER_MIN reads a run ({got})", got == 4 and STATE["hits"].count("tx") == 4)
    for _ in range(6): FX._win.clear(); FX.bodies(sleep=lambda s: None)
    nl = db.q1("SELECT COUNT(*) AS n FROM seal_links")["n"]
    check(f"every seal linked ({nl} of {len(SEALS)})", nl == len(SEALS))
    check("the sealed blob is never stored", not db.q1("SELECT 1 AS x FROM tx_detail WHERE json LIKE '%SEALEDBLOB%'") and "SEALEDBLOB" not in json.dumps(db.q("SELECT * FROM seal_links")))
    db.write("INSERT OR IGNORE INTO txs(id, type, from_addr, ts, final, segment) VALUES(?,?,?,?,1,2)", (ANS, "challenge", A3, NOW - 9000))
    FX._cov["v"] = None
    sc = FX.seals_for(ANS)
    want = sum(1 for j, _ in enumerate(SEALS) if j % 3)
    check(f"seal count per answer ({sc['seals']} == {want}) and complete", sc["seals"] == want and sc["complete"] and sc["counted_through_ts"] == NOW - 400)
    code, body = None, None
    j, lst = SV.api("/api/seals/" + ANS, {})
    check("/api/v1/seals/<answer> returns the count only", j["seals"] == want and set(j) >= {"answer", "seals", "complete", "counted_through_ts"} and "blob" not in json.dumps(j))
    from poascan import receipts as RC
    gr = {r["from_addr"] for j, r in enumerate(SEALS) if j % 3}
    check(f"the Receipt's Seals counts distinct graders from the links ({RC.index()['seals'].get(ANS)} == {len(gr)})", RC.index()["seals"].get(ANS) == len(gr))
    r = AG.call_tool("get_answer_seals", {"txid": ANS}) if hasattr(AG, "call_tool") else AG.TOOL_FN["get_answer_seals"]({"txid": ANS})
    check("MCP get_answer_seals", (r.get("seals") if isinstance(r, dict) else None) == want)
    db.write("INSERT OR IGNORE INTO txs(id, type, from_addr, ts, final, segment) VALUES(?,?,?,?,1,2)", (H("b", 7), "grade-sealed", A1, NOW - 8000))
    FX._cov["v"] = None
    check("an unread seal newer than the answer makes the count Partial", not FX.seals_for(ANS)["complete"])

    # ---- budget and 429
    FX._win.clear(); FX._vwin.clear()
    FX.VISITOR_PER_MIN = 2
    hits = len(STATE["hits"]); [FX.tx_detail(H("7", i)) for i in range(5)]
    check("visitor lookups capped per minute (fallback to minepoa.com beyond)", len(STATE["hits"]) - hits == 2)
    FX.VISITOR_PER_MIN = 20; FX._win.clear(); FX._vwin.clear()
    STATE["mode"] = "429"
    try: FX._get("overview", "overview"); ok = False
    except FX.Unavailable: ok = True
    hits = len(STATE["hits"]); FX.tx_detail(H("6", 1)); FX.sync(sleep=lambda s: None)
    check("429 with Retry-After holds every read", ok and len(STATE["hits"]) == hits and FX._hold[0] > time.time() + 60)
    STATE["mode"] = "ok"; FX._hold[0] = 0; FX._fails[0] = 0

    # ---- search and resolve
    out = AG.t_search({"query": "0xabcdef0000000000000000000000000000000001"})["results"]
    check("search: an EVM wallet resolves from stored links (case-insensitive)", [o["id"] for o in out] == [A3] and out[0]["via"]["network"] == "ethereum")
    out = AG.t_search({"query": "So1anaWa11etAddre55xxxxxxxxxxxxxxxxxxxx1"})["results"]
    check("search: an unknown wallet asks the index resolve once", [o["id"] for o in out] == [A1])
    check("a hex tx prefix is never taken for a wallet", not FX.is_external("abcdef1234567890abcdef1234567890ab") and FX.is_external("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"))
    r, _ = SV.api("/api/resolve", {"q": ["7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"]})
    check("/api/v1/resolve external wallet", r["results"][0]["id"] == A2 and r["results"][0]["kind"] == "address")
    try: SV.api("/api/resolve", {"q": ["x"], "key": ["y"]}); ok = False
    except SV.BadRequest: ok = True
    check("/api/v1/resolve takes q only", ok)

    # ---- anchor timeline
    t = AV.timeline("all")
    rows = {x["height"]: x for x in t["rows"]}
    check("timeline: one row per height, Base and Solana txs", set(rows) == {0, 100, 200, 300} and rows[100]["base_tx"] and rows[100]["solana_tx"] == "SOL100")
    check("checks: match, mismatch (Base vs Solana), none for genesis", rows[100]["check"] == "match" and rows[300]["check"] == "mismatch" and rows[0]["check"] == "none")
    check("gap and txs from the previous height", rows[200]["gap_s"] == 1800 and rows[200]["txs"] == 100)
    db.write("INSERT OR REPLACE INTO anchors(height, chain, tx, state_root, anchored_at, segment) VALUES(?,?,?,?,?,2)", (100, "base-mainnet", "0x" + format(100, "064x"), "e" * 64, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 7200))))
    check("a minepoa copy that disagrees with the index is a mismatch", {x["height"]: x for x in AV.timeline("all")["rows"]}[100]["check"] == "mismatch")
    db.put_blob("status", {"checkpoint_height": 200, "state_root": "d" * 64})
    check("minepoa's /api/status root at a checkpoint is cross checked", {x["height"]: x for x in AV.timeline("all")["rows"]}[200]["check"] == "mismatch")
    a, _ = SV.api("/api/anchors/timeline", {"range": ["all"], "sort": ["gap"]})
    check("API: stats, rows, mismatch heights, explorers", a["stats"]["mismatches"] == 3 and sorted(a["mismatch_heights"]) == [100, 200, 300] and a["explorers"]["base"].startswith("https://basescan.org"))
    try: SV.api("/api/anchors/timeline", {"range": ["1y"]}); ok = False
    except SV.BadRequest: ok = True
    check("API: a bad range is a 400", ok)
    b = AV.body({"range": ["all"]})
    check("page: range chips 24h, 7d, 30d, All", all(f'>{n}</a>' in b for n in ("24h", "7d", "30d", "All")))
    check("page: sortable headers with aria-sort", 'aria-sort=' in b and 'class="hsb"' in b and "sortsel" in b)
    check("page: Mismatch flag, explorer links, chart in a chartbox (watermark) with one path", "Mismatch" in b and "https://solscan.io/tx/SOL100" in b and 'class="chartbox"' in b and b.count('class="ln s-gold"') == 1)
    check("page: no share button, no em or en dash", "share" not in b.lower() and "\u2014" not in b and "\u2013" not in b)
    c = V.network("anchors"); c = c[1] if isinstance(c, tuple) else c
    check("Network has an Anchors tab", 'href="/network?tab=anchors" class="chip on"' in c)
    r = AG.TOOL_FN["get_anchor_timeline"]({"range": "all"})
    check("MCP get_anchor_timeline", r["stats"]["heights"] == 4)

    # ---- feed row, status note, health
    f = FX.feed()
    check(f"feed row OK while the index is close behind ({f})", f and f["state"] == "OK" and f["label"] == "Fast index")
    fd = A.feeds(); check("Fast index is a row in the feeds", any(x["label"] == "Fast index" for x in fd["feeds"]))
    st = FX._state(); st["newest_tx_ts"] = NOW - 4000; db.put_blob("fx:state", st)
    check("Degraded when more than 30 min behind", FX.feed()["state"] == "Degraded")
    st["ok_at"] = NOW - 7200; db.put_blob("fx:state", st); FX._last["ok"] = None
    check("Down after 30 min without a good read", FX.feed()["state"] == "Down")
    pl = FX.pill_line(); check("status note line names the fallback", pl and "minepoa.com" in pl[0])
    pop = UI.status_pill(dict(state="partial", label="Partial", why="Chain live. Not OK: Fast index"))
    check("the line is in the status note", any("Fast index" in r for r in pop["reasons"]))
    h, _ = SV.api("/api/health", {})
    hs = json.dumps(h)
    check("/api/health fast_index: state, lag, backfill, seals, requests", h["fast_index"]["enabled"] and {"state", "lag_s", "backfill", "seals", "requests"} <= set(h["fast_index"]))
    check("/api/health never carries the index URL", base not in hs and "127.0.0.1" not in hs)

    # ---- docs
    spec = AG.openapi(); llms = AG.llms_txt() if hasattr(AG, "llms_txt") else ""
    check("OpenAPI: anchors timeline, seals, resolve", all(p in spec["paths"] for p in ("/api/v1/anchors/timeline", "/api/v1/seals/{txid}", "/api/v1/resolve")))
    check("llms.txt names the anchor timeline, seals and the fast index", all(x in llms for x in ("anchors/timeline", "/seals/", "Fast index")))
    ab = V.about(); ab = ab[1] if isinstance(ab, tuple) else ab
    check("/about#anchors and #fast-index", 'id="anchors"' in ab and 'id="fast-index"' in ab and "Receipt\\'s Seals" not in ab and "Receipt's Seals" in ab)
    check("MCP tools listed", {"get_anchor_timeline", "get_answer_seals"} <= set(AG.TOOL_FN))

    # ---- privacy: no build host in public code or docs
    host = "emblem" + ".build"; bad = []
    real = ""   # the configured host, read locally when present, never printed
    try: real = urllib.parse.urlparse(open(os.environ.get("FAST_INDEX_URL_FILE", "/workspace/poa/dbexplorer1027/fast_index_url")).read().strip()).hostname or ""
    except OSError: pass
    for dp, dn, fn in os.walk(ROOT):
        if ".git" in dp.split(os.sep) or "node_modules" in dp: continue
        for f in fn:
            if f.endswith((".py", ".md", ".json", ".js", ".css", ".html", ".txt", ".toml", ".yml", ".svg")):
                try: s = open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read()
                except OSError: continue
                if host in s or (real and real in s): bad.append(f)
    check(f"no build host name anywhere in the repo ({bad})", not bad)
    for f in ("poascan/fastindex.py", "poascan/anchorsview.py", "tools/fastindex_test.py"):
        s = open(os.path.join(ROOT, f), encoding="utf-8").read()
        check(f"{f}: no em or en dash", "\u2014" not in s and "\u2013" not in s)
    srv.shutdown()
    print(f"\n{len(fails)} failed" if fails else "\nall passed"); sys.exit(1 if fails else 0)

main()
