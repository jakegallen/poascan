"""1.26.96 header merge and Governance: Home plus 4 tabs (Chain, Agents, Network, Governance), About in the footer, Chain sub-tabs
(Epochs, Transactions), Network Token tab, 301s that keep every query parameter, sitemap and llms.txt, and the Governance tabs
(Overview, At risk, Graders, Charts, Rules) against the 12-close fixture. Usage: python3 tools/govnav_test.py"""
import os, re, socket, subprocess, sys, tempfile, time, http.client, urllib.parse
os.environ.setdefault("POASCAN_SEGMENTS", "1")   # synthetic history spans the real genesis cut: one segment
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
FAILS = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or FAILS.append(name)

def unit():
    os.environ.setdefault("POASCAN_DB", os.path.join(tempfile.mkdtemp(), "u.db"))
    from poascan import server as S
    q = lambda s: urllib.parse.parse_qs(s, keep_blank_values=True)
    cases = {("/epochs", ""): "/chain", ("/epochs", "segment=1"): "/chain?segment=1", ("/epochs", "tab=pending&segment=1"): "/chain?tab=pending&segment=1",
             ("/blocks", "page=2"): "/chain?page=2", ("/txs", "type=join&page=3"): "/chain/txs?type=join&page=3", ("/transactions", ""): "/chain/txs",
             ("/token", ""): "/network?tab=token", ("/token", "tab=x&range=7d"): "/network?tab=token&range=7d",
             ("/agents/at-risk", "sort=-drop"): "/governance?tab=at-risk&sort=-drop", ("/agents/graders", "sort=n&segment=1"): "/governance?tab=graders&sort=n&segment=1",
             ("/live", ""): "/chain?tab=pending", ("/grading", ""): "/chain?tab=grading", ("/at-risk", ""): "/governance?tab=at-risk"}
    got = {k: S.moved(k[0], q(k[1])) for k in cases}
    check(f"moved(): new routes, query kept, target tab wins {[(k, v) for k, v in got.items() if v != cases[k]]}", got == cases)
    check("sitemap routes: new homes in, old list URLs out", all(p in S.STATIC_ROUTES for p in ("/chain", "/chain/txs", "/network?tab=token", "/governance", "/governance?tab=rules"))
          and not any(p in S.STATIC_ROUTES for p in ("/epochs", "/txs", "/token", "/agents/at-risk", "/agents/graders")))

def fresh():
    """Standing starts fresh in each segment: only the selected segment's own close records count."""
    from poascan import governance as GV, analytics as A, standing as SD
    recs = [{"epoch": 0, "basis": {"established_after": [], "challenge_eligible": ["poa1X"]}},
            {"epoch": 1, "basis": {"established_after": ["poa1X"], "established_removed": [], "challenge_eligible": ["poa1X", "poa1Y"], "graders_served": {"poa1S": 2}}}]
    sv = (A.segment_closes, A.params, SD._trusted)
    try:
        A.segment_closes = lambda n: recs; A.params = lambda: {"estab_ttl": 6}; SD._trusted = lambda: {"poa1S", "poa1T"}
        est, le = GV.segment_standing()
        check(f"segment standing: adds and seats from this segment only, seen system graders, last eligible per close {sorted(est)} {le}",
              est == {"poa1X", "poa1S"} and le == {"poa1X": 1, "poa1Y": 1})
        A.segment_closes = lambda n: [{"epoch": 0, "basis": {}}]
        check("segment standing: a new segment with no entries starts empty", GV.segment_standing()[0] == set())
    finally:
        A.segment_closes, A.params, SD._trusted = sv

def payout_unit():
    """Est. per Agent: median of the last 3 paid closes' per-Agent median (one segment here)."""
    from poascan import governance as GV, analytics as A
    rows = [dict(epoch=i, paid=3, median=m, max=m, pool=1e9, burn_pct=99.0) for i, m in enumerate((785568.0, 900000.0, 709920.0, 612877.0))]
    sv = A.epoch_rows
    try:
        A.epoch_rows = lambda: rows; pe = GV.payout_estimate()
        check(f"payout estimate: median of the last 3 paid closes ({pe['estimate']})", pe["estimate"] == 709920.0 and [b["epoch"] for b in pe["basis"]] == [1, 2, 3])
    finally:
        A.epoch_rows = sv

def forum_unit():
    """Forum analytics from the mirror: Live-GrokBot left out, reply rate and first reply from other authors, G0 replies."""
    from poascan import db, governance as GV, signed as SGN
    db.init(); now = time.time(); iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)); G0 = SGN.TRUSTED_G0
    db.write("INSERT OR REPLACE INTO forum_posts(id, community, title, author, author_public_id, created_at, comment_count, deleted) VALUES(?,?,?,?,?,?,?,0)",
             [(9001, "general", "a", "Alpha", "poa1" + "P" * 40, iso(now - 7200), 2), (9002, "general", "b", "Live-GrokBot", "poa1" + "Q" * 40, iso(now - 7000), 0),
              (9003, "proposals", "c", "Beta", "poa1" + "R" * 40, iso(now - 6000), 0), (9004, "poa-archive", "d", "Alpha", "poa1" + "P" * 40, iso(now - 5000), 0)], many=True)
    db.write("INSERT OR REPLACE INTO forum_comments(id, post_id, parent_id, author, author_public_id, created_at) VALUES(?,?,?,?,?,?)",
             [(8001, 9001, None, "agent_14YNP29q", G0, iso(now - 3600)), (8002, 9001, None, "Alpha", "poa1" + "P" * 40, iso(now - 3000))], many=True)
    f = GV.forum_stats.__wrapped__("7d") if hasattr(GV.forum_stats, "__wrapped__") else GV.forum_stats("7d")
    check(f"forum: posts {f['posts']}, comments {f['comments']}, reply rate {f['reply_rate']}, first reply {f['median_wait']}, operator {f['operator_replied']}",
          f["posts"] == 2 and f["comments"] == 2 and f["reply_rate"] == 0.5 and 3500 <= (f["median_wait"] or 0) <= 3700 and f["operator_replied"] == 1
          and all(r["name"] != "Live-GrokBot" for r in f["top"]) and [c[0] for c in f["communities"]] == ["general", "proposals"])

def proposals_unit():
    """Proposals: derived status (Ballot from the cited list, Discussion under 24 h, Posted), no dashes in titles, Live-GrokBot left out."""
    from poascan import db, governance as GV
    now = time.time(); iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    db.write("INSERT OR REPLACE INTO forum_posts(id, community, title, author, author_public_id, created_at, comment_count, deleted) VALUES(?,?,?,?,?,?,?,0)",
             [(1092, "proposals", "TOPIC 1 \u2014 work_source", "agent_14YNP29q", "poa1" + "G" * 40, iso(now - 9 * 86400), 4),
              (9101, "proposals", "Fresh idea", "Gamma", "poa1" + "S" * 40, iso(now - 3600), 1),
              (9102, "proposals", "Older idea", "Delta", "poa1" + "T" * 40, iso(now - 3 * 86400), 0),
              (9103, "proposals", "Bot idea", "Live-GrokBot", "poa1" + "U" * 40, iso(now - 600), 0)], many=True)
    h = GV.proposals({})
    check("proposals: Ballot, Discussion and Posted status; no dash; Live-GrokBot left out; Tally not public with post 1120",
          '<span class="tag ok">Ballot</span> <span class="mono">e66aec80</span>' in h and '<span class="tag est">Discussion</span>' in h and '<span class="tag">Posted</span>' in h
          and "\u2014" not in h and "Bot idea" not in h and "Tally not public" in h and "#/post/1120" in h and "TOPIC 1 , work_source" in h)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def live():
    port = free_port(); tmp = tempfile.mkdtemp()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "g.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
    subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=env, check=True)
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env)
    def get(u):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30); c.request("GET", u); r = c.getresponse(); b = r.read().decode("utf-8", "replace"); c.close()
        return r.status, b, dict(r.getheaders())
    try:
        for _ in range(100):
            try: get("/api/health"); break
            except Exception: time.sleep(0.2)
        # 301s over HTTP
        for old, new in (("/epochs?segment=1", "/chain?segment=1"), ("/txs?type=join", "/chain/txs?type=join"), ("/token", "/network?tab=token"),
                         ("/agents/at-risk", "/governance?tab=at-risk"), ("/agents/graders?sort=n", "/governance?tab=graders&sort=n"), ("/live", "/chain?tab=pending")):
            c, _, h = get(old); check(f"GET {old} -> 301 {h.get('Location')}", c == 301 and h.get("Location") == new)
        for u in ("/epoch/2", "/unlocks", "/agents", "/agents/top", "/about"):
            cu = get(u); check(f"GET {u} stays 200 ({cu[0]})", cu[0] == 200)
        # header: Home plus exactly 4 tabs, About in the footer
        home = get("/")[1]
        nav = home[home.index('<nav class="nav" id="nav">'):]; nav = nav[:nav.index("</nav>")]
        links = re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', nav)
        check(f"nav is Chain, Agents, Network, Governance {links}", [t for _, t in links] == ["Chain", "Agents", "Network", "Governance"]
              and [h for h, _ in links] == ["/chain", "/agents", "/network", "/governance"])
        check("About is in the footer, not the nav", 'href="/about"' not in nav and re.search(r'<footer.*href="/about"', home, re.S) is not None)
        def active(u):
            b = get(u)[1]; n = b[b.index('<nav class="nav" id="nav">'):]; n = n[:n.index("</nav>")]
            m = re.search(r'<a href="([^"]+)" class="on"', n); return m.group(1) if m else None
        act = {u: active(u) for u in ("/chain", "/chain/txs", "/chain?tab=pending", "/epoch/1", "/network?tab=token", "/unlocks", "/governance", "/governance?tab=rules", "/agents/top")}
        check(f"active tab {act}", act == {"/chain": "/chain", "/chain/txs": "/chain", "/chain?tab=pending": "/chain", "/epoch/1": "/chain", "/network?tab=token": "/network",
                                           "/unlocks": "/network", "/governance": "/governance", "/governance?tab=rules": "/governance", "/agents/top": "/agents"})
        # Chain sub-tabs
        c1, ch, _ = get("/chain"); c2, tx, _ = get("/chain/txs")
        check("Chain: Epochs and Transactions sub-tabs, the right one on", c1 == 200 and c2 == 200 and '<nav class="chips" aria-label="Chain">' in ch
              and 'href="/chain" class="chip on"' in ch and 'href="/chain/txs" class="chip "' in ch and 'href="/chain/txs" class="chip on"' in tx)
        check("Chain: epoch tabs and type chips use the new routes", 'href="/chain?tab=pending"' in ch and 'href="/epochs' not in ch and 'href="/txs' not in tx and 'href="/chain/txs?type=' in tx)
        # Network: Token tab, Overview and Health intact
        c, tk, _ = get("/network?tab=token"); ov = get("/network")[1]; hl = get("/network?tab=health")[1]
        check("Network: Token tab renders the token page under the Network chips", c == 200 and 'href="/network?tab=token" class="chip on"' in tk and "Proof of Agent" in tk
              and "Min-activity Agents" in tk and tk.count("<h1") == 1)
        check("Network: Overview keeps .stats.netov, Health keeps Feeds", 'class="stats six netov"' in ov and "Feeds</h2>" in hl)
        # Agents sub-tabs no longer carry Graders or At risk
        ag = get("/agents")[1]; check("Agents sub-tabs: no Graders or At risk", 'href="/agents/graders"' not in ag and 'href="/agents/at-risk"' not in ag)
        # Governance tabs
        tabs = {}
        for t in ("", "at-risk", "payouts", "graders", "directory", "forum", "proposals", "charts", "rules"):
            u = "/governance" + (f"?tab={t}" if t else ""); c, b, _ = get(u); tabs[t] = b
            check(f"GET {u} 200, one chip on, no em or en dash, no share button", c == 200 and b.count('class="chip on"') >= 1 and "\u2014" not in b and "\u2013" not in b
                  and "share" not in b.lower().replace("top10_share", ""))
        g = tabs[""]
        check("Governance overview: stat cards and tabs", all(f'>{x}</div>' in g or f'>{x}</span>' in g for x in ("Established", "At risk", "Watch", "Safe", "Graders"))
              and all(f'>{x}</a>' in g for x in ("Overview", "At risk", "Payouts", "Graders", "Directory", "Forum", "Proposals", "Charts", "Rules")))
        r = tabs["at-risk"]
        check("At risk: the two-close list, then every established Agent with a level and a rule link", 'id="at-risk"' in r and 'id="standing"' in r and 'tab=rules#lapse' in r and re.search(r'class="tag (warn|est|ok|)">(At risk|Watch|Safe|No record|System)<', r))
        check("At risk: level filter", get("/governance?tab=at-risk&level=safe")[0] == 200 and 'level=safe#standing" class="chip on"' in get("/governance?tab=at-risk&level=safe")[1])
        gr = tabs["graders"]; check("Graders: the calibration table, sort keeps the tab", 'id="calibration"' in gr and 'href="/governance?tab=graders&amp;sort=n"' in gr)
        check("Graders: live seals, jury seats per close and coverage stats", all(x in gr for x in ("Seals since close", "Jury seats per close", ">Coverage<", ">Queue<")) and 'class="chartbox"' in gr)
        dr = tabs["directory"]; A1 = "poa1" + "A" * 40
        check("Directory: every Agent with rewards, eligible, seals and attestations; sort and filter chips", 'id="directory"' in dr and f'href="/address/{A1}#standing"' in dr
              and all(f'>{x}</a>' in dr for x in ("Rewards", "Eligible closes", "Seals", "Attestations", "Established", "Graders", "Attesters")))
        d2 = get("/governance?tab=directory&sort=atts&filter=graders")[1]
        check("Directory: sort and filter keep each other", 'href="/governance?tab=directory&amp;sort=atts&amp;filter=graders" class="chip on">Graders' in d2
              and 'href="/governance?tab=directory&amp;sort=atts&amp;filter=graders" class="chip on">Attestations' in d2)
        pa = tabs["payouts"]
        check("Payouts: Est. per Agent labelled Estimate, last paid closes, eligible and paid chart", 'id="estimate"' in pa and '<span class="tag est">Estimate</span>' in pa
              and ">Est. per Agent<" in pa and ">Answered<" in pa and ">K-attested<" in pa and "50.00M" in pa and 'class="chartbox"' in pa)
        fo = tabs["forum"]
        check("Forum: range chips, stat cards, communities, most active, empty summary slot", all(f'>{x}</a>' in fo for x in ("24h", "7d", "30d", "All"))
              and all(x in fo for x in (">Reply rate<", ">First reply<", ">Operator replies<", "Communities</h2>", "Most active</h2>", 'id="summary"', "No summary yet.")) and "Live-GrokBot" not in fo)
        pr = tabs["proposals"]
        check("Proposals: a/proposals table and the cited ballot list", 'id="proposals"' in pr and 'id="ballots"' in pr and "e66aec80" in pr and "Tally not public" in pr)
        cs = tabs["charts"]
        check("Charts: 24h, 7d, 30d and All, four charts", all(f'>{x}</a>' in cs for x in ("24h", "7d", "30d", "All")) and cs.count('class="chartbox') >= 4)
        check("Charts: range chip on", 'range=24h" class="chip on"' in get("/governance?tab=charts&range=24h")[1])
        ru = tabs["rules"]; check("Rules: anchors for every rule link", all(f'id="{a}"' in ru for a in ("earn", "lapse", "removal", "no-record", "system", "seats", "votes", "carryover")))
        check("Governance segment chips keep the tab", 'href="/governance?tab=at-risk&amp;segment=' in r or "segs" not in r)
        # sitemap and llms.txt
        sm = get("/sitemap.xml")[1]; ll = get("/llms.txt")[1]
        locs = re.findall(r"<loc>https://poascan.io([^<]*)</loc>", sm)
        check("sitemap: /chain, /chain/txs, /network?tab=token, /governance; no old list URLs", all(x in locs for x in ("/chain", "/chain/txs", "/network?tab=token", "/governance"))
              and not any(x in locs for x in ("/epochs", "/txs", "/token", "/agents/at-risk", "/agents/graders")))
        check("llms.txt: Chain, Governance and Token pages", "/chain the open epoch" in ll and "/governance where established Agents stand" in ll and "(?tab=directory)" in ll and "(?tab=payouts)" in ll and "(?tab=forum)" in ll and "(?tab=proposals)" in ll and "(?tab=token)" in ll
              and "/epochs the" not in ll and "poascan.io/agents/at-risk" not in ll)
    finally:
        p.terminate()

if __name__ == "__main__":
    unit(); fresh(); payout_unit(); forum_unit(); proposals_unit(); live()
    print(f"{len(FAILS)} failed" if FAILS else "all passed"); sys.exit(1 if FAILS else 0)
