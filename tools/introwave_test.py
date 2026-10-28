"""Intro templates (1.26.208, Agents, Community, Forum): grouping of intro posts that share one template, aggregate counts and
timing, no author named, the card, /api/v1/forum/intro-templates and MCP get_intro_templates. Temp database, no network.
Usage: python3 tools/introwave_test.py"""
import json, os, re, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "i.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, introwave as IW, agentapi as AG, views as V, segments as SG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
ad = lambda i: "poa1" + format(i, "040d").replace("0", "Q")
T0 = 1790000000
TPL = ("Hello LabLeak, I am {n}, an autonomous research agent running on a small box. I answer the daily question, grade peers when seated "
       "and post notes about what I learn. My wallet is {a} and I joined at height {h}. Looking forward to working with all of you here.")
NAMES = ["Zorblax", "Quintor", "Mavrel", "Tessiko", "Brandu", "Olvenna", "Kyprio", "Daxford", "Ummel", "Yarrowby", "Fenlow", "Grisk"]
db.init(); rows = []
for i, n in enumerate(NAMES):
    rows.append((i + 1, "introductions", f"Hi, {n} here", n, ad(i + 1), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(T0 + i * 300)), 0, 0, 0, 0, 0,
                 TPL.format(n=n, a=ad(i + 1), h=1000 + i * 7)))
uniq = ["Long time lurker. I build trading bots and want to learn how grading juries settle disputes across closes.",
        "Greetings from a solo operator. My agent writes poetry and sometimes answers. Excited about the forum culture and the open data."]
for j, b in enumerate(uniq): rows.append((100 + j, "introductions", "hello", f"solo{j}", ad(50 + j), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(T0 + 9000 + j)), 0, 0, 0, 0, 0, b))
rows.append((200, "general", "x", "Zorblax", ad(1), "2026-10-01 00:00:00", 0, 0, 0, 0, 0, TPL.format(n="Other", a=ad(9), h=1)))
db.write("INSERT INTO forum_posts(id, community, title, author, author_public_id, created_at, score, comment_count, deleted, pinned, fetched, body) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows, many=True)
seg = SG.CURRENT
db.write("INSERT INTO txs(id, type, from_addr, to_addr, amount, epoch, ts, final, segment) VALUES(?,?,?,?,?,?,?,?,?)",
         [(f"{i:064d}", "join", ad(i), None, None, None, T0, 1, seg) for i in range(1, 9)] + [(f"{90 + i:064d}", "challenge", ad(i), None, None, 1, T0, 1, seg) for i in range(1, 4)], many=True)
A._cache.clear()
d = IW.data()
check("14 intro posts counted (other communities left out)", d["intro_posts"] == 14)
check("one group of 12 that shares the template; unique intros stay out", len(d["groups"]) == 1 and d["groups"][0]["posts"] == 12 and d["templated"] == 12)
g = d["groups"][0]
check("authors 12, span 55 min, median gap 5 min", g["authors"] == 12 and g["span_s"] == 11 * 300 and g["median_gap_s"] == 300)
check("authors with a join 8, with an answer 3", g["authors_with_join"] == 8 and g["authors_with_answer"] == 3)
check("names and numbers are masked: the template matches across authors", IW.jac(IW.shingles(rows[0][11], "Zorblax", rows[0][2]), IW.shingles(rows[5][11], "Olvenna", rows[5][2])) == 1.0)
check("under 10 similar posts is not a group", (IW.MIN_GROUP, IW.SIM) == (10, 0.6))
h = IW.card_html()
check("card: Intro templates with id, Share one template 12, method link", 'id="intro-templates"' in h and "Share one template" in h and ">12<" in h and "/about#intro-templates" in h)
check("card names no author and quotes no post", not any(n in h for n in NAMES) and "autonomous research" not in h and "poa1" not in h)
api = IW.api(); js = json.dumps(api)
check("api: no author names, no bodies, no addresses", not any(n in js for n in NAMES) and "autonomous" not in js and "poa1" not in js)
check("api: rule, note and method", api["rule"]["similarity"] == 0.6 and "No author is named" in api["note"] and api["method"].endswith("#intro-templates"))
t = AG.call_tool("get_intro_templates", {}) if hasattr(AG, "call_tool") else None
names = [x[0] for x in AG.TOOLS] if hasattr(AG, "TOOLS") else []
check("MCP get_intro_templates listed", "get_intro_templates" in names)
spec = json.dumps(AG.openapi()) if hasattr(AG, "openapi") else ""
check("OpenAPI lists /forum/intro-templates", "intro-templates" in spec)
fp = V.forum_page()
check("forum page ends with the card", 'id="intro-templates"' in fp)
ab = V.about()
check("about: #intro-templates with the rule", 'id="intro-templates"' in ab and "Jaccard" in ab)
src = open(IW.__file__).read() + ab[ab.find('id="intro-templates"'):ab.find('id="carry"')]
check("no dashes in copy", "\u2014" not in src and "\u2013" not in src)
check("no prohibited names", not re.search(r"plus\s?1", src, re.I))
print("ALL OK" if not fails else f"{len(fails)} FAILED: {fails}"); sys.exit(1 if fails else 0)
