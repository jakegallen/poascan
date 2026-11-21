"""Unofficial Apps tab (1.26.413): /apps shell, escaped AC1 posts, ATP-20 list,
third-party games catalog. No art rasters, no indexer calls, no em or en dashes.
Usage: python3 tools/apps_test.py"""
import json, os, sys, tempfile, copy
from html import escape as E
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, apps as AP, atp20 as T, indexer as IX, agentapi as AG

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

DASH = ("\u2014", "\u2013")
db.init()
FIX = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "atp20_fixture.json")))
DEP = FIX["deployer"]

def tid(n):
    return format(n, "064x")

def row(i, memo, fr, to=None, ts=1795179000, final=1, typ="transfer", amt="0.000001"):
    return dict(id=tid(i) if isinstance(i, int) else i, type=typ, from_addr=fr, to_addr=to if to is not None else fr,
                amount=amt, memo=memo, ts=ts, final=final)

def load(*rows, source="test"):
    IX.upsert_txs([copy.deepcopy(r) for r in rows], source)

# ---- AC1 parse ----
p = AP.parse_ac1("AC1|t|hello <script>alert(1)</script>")
check("inline t keeps raw text for later escape", p and p["op"] == "t" and "<script>" in p["text"])
p = AP.parse_ac1("AC1|m|abcd1234|01/02|part one")
check("multipart m parses part and id", p and p["op"] == "m" and p["cid"] == "abcd1234" and p["part"] == 1 and p["total"] == 2)
check("unknown AC1 op is ignored", AP.parse_ac1("AC1|s|abcd|sha256:ff") is None)
check("non AC1 is ignored", AP.parse_ac1("DICE1:BET:under:1:x") is None)
check("bad part fraction is ignored", AP.parse_ac1("AC1|m|ab|x/y|text") is None)

# ---- fixtures: posts + a script-bearing memo + ATP-20 ----
A = "poa1ANByoh2aHiEjE6KS5UoXtQLbx1Eh9ejy89VwyNbQFVzT"
B = DEP
load(
    row(1, "AC1|t|<svg><script>x</script></svg>", A, ts=1795181000),
    row(2, "AC1|m|p1test03|01/03|Alpha part one. ", B, ts=1795180900),
    row(3, "AC1|m|p1test03|02/03|Part two, still going. ", B, ts=1795180910),
    row(4, "AC1|m|p1test03|03/03|Part three done.", B, ts=1795180920),
    row(5, "AC1|t|pending only", A, ts=1795181100, final=0),
    row(6, "DICE1:BET:under:1:x", A, ts=1795181200),
    *FIX["txs"],
)
items = AP.posts(20)
kinds = {(it["kind"], it.get("cid") or "t") for it in items}
check("multipart is grouped into one row", sum(1 for it in items if it.get("cid") == "p1test03") == 1)
g = next(it for it in items if it.get("cid") == "p1test03")
check("grouped text is in part order", "part one" in g["text"] and g["text"].endswith("Part three done.") and g["have"] == 3 and g["parts"] == 3)
check("pending memo is not listed", all(it["txid"] != tid(5) for it in items))
check("inline svg memo is present as text, not dropped", any("<svg>" in (it["text"] or "") for it in items))

# ---- pages ----
disc = AP.DISCLAIMER
html = AP.page_html({})
html_posts = AP.page_html({"tab": ["posts"]})
html_games = AP.page_html({"tab": ["games"]})
html_atp = AP.page_html({"tab": ["atp20"]})
html_bad = AP.page_html({"tab": ["nope"]})

def nodash(s):
    return all(ch not in s for ch in DASH)

check("default tab is Posts and shows the feed", "post-feed" in html and "post-text" in html and "post-card" in html and 'aria-current="page"' in html and "Posts" in html)
check("unknown tab falls back to Posts", "post-feed" in html_bad and "post-card" in html_bad)
check("posts tab features POAPost", 'data-app="poapost"' in html and "POAPost" in html and "/static/apps/poapost.png" in html)
check("posts tab links the LabLeak post", "2915" in html)
check("disclaimer appears once on each tab", html.count(E(disc)) == 1 and html_posts.count(E(disc)) == 1 and html_games.count(E(disc)) == 1)
check("disclaimer is exact", disc in html.replace("&amp;", "&") or E(disc) in html)
# The disclaimer has no chars that need escape except maybe none. It's plain ASCII.
check("disclaimer raw exact on the page", disc in html)
check("games tab has no unofficial line", "Unofficial" not in html_games.split(disc, 1)[1])
check("posts tab has no unofficial line", "Unofficial" not in html.split(disc, 1)[1] and "Unofficial" not in html_posts.split(disc, 1)[1])
check("ATP-20 source says unofficial once", "Unofficial" not in disc and html_atp.split(disc, 1)[1].count("Unofficial") == 1)
check("posts tab escapes svg and script",
      "&lt;svg&gt;&lt;script&gt;x&lt;/script&gt;&lt;/svg&gt;" in html_posts
      and "<svg><script>x</script></svg>" not in html_posts
      and "<script>x</script>" not in html_posts)
check("posts tab shows grouped excerpt", "part one" in html_posts)
check("short posts list has no pager", "gpager" not in html and "gpager" not in html_posts)
check("games tab has no unendorsed or third-party tag", "Unendorsed" not in html_games and "Third-party" not in html_games.split(disc, 1)[-1])
check("games tab has no catalog source line", "POAScan catalog." not in html_games)
check("games show live memo stats", 'data-app="poa-dice"' in html_games and 'data-memos="1"' in html_games and "app-stats" in html_games)
check("games use local logos when they exist", "/static/apps/dice.png" in html_games and "/static/apps/betai.webp" in html_games and "/static/apps/league.webp" in html_games and "/static/apps/trivia.png" in html_games)
check("games link official sites and socials", "poadice.grok.me" in html_games and "cgtrivia.creativegrace.tech" in html_games and "x.com/DCTreeofLife" in html_games and "t.me/VaultGameHub" in html_games and "github.com/maximusmaximus/poa-dice" in html_games)
check("games include POA Dice outbound host", "poadice.grok.me" in html_games and "rel=\"noopener noreferrer\"" in html_games)
check("games have no wallet-connect or payment CTA",
      "wallet-connect" not in html_games.lower() and "walletconnect" not in html_games.lower()
      and "deposit" not in html_games.lower() and "connect wallet" not in html_games.lower())
check("PROOF PIT is listed with no invented prefix", "PROOF PIT" in html_games and "proof-pit" in html_games)
import re as _re
_pit = _re.search(r'<article class="app-card"[^>]*data-app="proof-pit".*?</article>', html_games, _re.S)
check("PROOF PIT hides empty memo stats", bool(_pit) and "app-nums" not in _pit.group(0) and "None" not in _pit.group(0))
check("no em or en dash in Apps HTML", nodash(html) and nodash(html_posts) and nodash(html_games) and nodash(html_atp))
check("version is 1.26.414", AG.VERSION == "1.26.414")

# ATP-20 list uses official=false figures from the replay tables
check("ATP-20 list shows SEAL and MAM from the local replay", "SEAL" in html_atp and "MAM" in html_atp)
seal_page = AP.page_html({"tab": ["atp20"], "tick": ["SEAL"]})
check("tick drill-down shows unofficial SEAL holders", "SEAL" in seal_page and "Holder" in seal_page and disc in seal_page)
check("20-row cap constant", AP.LIMIT == 20)

# flood of inline posts stays capped and pages with the shared 20-row offset pager
load(*[row(100 + i, f"AC1|t|note {i}", A, ts=1795182000 + i) for i in range(40)])
check("posts list caps at 20", len(AP.posts(20)) == 20)
page, total = AP.posts(AP.LIMIT, offset=0, count=True)
check("posts count includes the flood", total >= 40 and len(page) == 20)
html_p1 = AP.page_html({})
html_p2 = AP.page_html({"offset": ["20"]})
check("first posts page uses the shared pager", "gpager" in html_p1 and "pager2" in html_p1 and "1 to 20 of" in html_p1 and ">Next</a>" in html_p1)
check("first posts page has no Prev", "Prev" not in html_p1)
check("first posts page is 20 rows", html_p1.count("post-card") == 20)
check("Next uses the offset param", "offset=20" in html_p1)
check("second posts page has Prev and the range", "Prev" in html_p2 and "21 to 40 of" in html_p2 and "offset=40" in html_p2)
check("second posts page stays at 20 rows", html_p2.count("post-card") == 20)
check("a short list has no pager", "gpager" not in html_games)

# no raw svg path even if someone put svg in a game blurb (catalog is escaped)
check("game blurbs are escaped in HTML", all(E(g["blurb"]) in html_games or g["blurb"] in html_games for g in AP.GAMES))

# ---- Art tab ----
html_art = AP.page_html({"tab": ["art"]})
check("art tab titles Genesis with a Digivatar credit",
      ">Genesis</h2>" in html_art and "by Digivatar" in html_art)
check("art tab tagline counts works, not game catalogs",
      "onchain work" in html_art and "catalogs in this archive" not in html_art)
check("art tab has no mint or buy CTA",
      "wallet-connect" not in html_art.lower()
      and "mint now" not in html_art.lower() and "buy now" not in html_art.lower()
      and ">Mint</" not in html_art and ">Buy</" not in html_art)
check("art tab does not repeat the unofficial decoder footer",
      html_art.count("POAScan decoder. Unofficial.") == 0)
check("art tab has no typographic dash", not any(d in html_art for d in DASH))
check("featured work uses an animated raster with a reduced-motion still",
      "art-pix-anim" in html_art and "art-pix-still" in html_art
      and "prefers-reduced-motion" in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "style.css"), encoding="utf-8").read())

# second synthetic collection appears without per-collection UI code; unit list pages 20 at a time
SHA2 = "aa" * 32
load(row(300, f"ATP-721|d|DEMO-ART|{SHA2}|image/png|40|1|MAM|20|40|SECOND COLLECTION", B, ts=1795230000))
for i in range(1, 26):
    load(row(300 + i, f"ATP-721|m|DEMO-ART|{i}", A, ts=1795230000 + i))
html_art2 = AP.page_html({"tab": ["art"]})
check("art catalog lists the second collection by ticker", "DEMO-ART" in html_art2 and "SECOND COLLECTION" in html_art2)
html_col = AP.page_html({"tab": ["art"], "col": ["DEMO-ART"]})
check("collection page uses the shared 20-row pager",
      "gpager" in html_col and "1 to 20 of 25" in html_col and ">Next</a>" in html_col)
check("collection unit table names the Agent column", ">Agent</" in html_col or ">Agent</th>" in html_col or "Agent" in html_col)
html_col2 = AP.page_html({"tab": ["art"], "col": ["DEMO-ART"], "offset": ["20"]})
check("collection second page stays at the shared cap", "21 to 25 of 25" in html_col2 and "Prev" in html_col2)


if fails:
    print("FAILED:"); [print(" -", x) for x in fails]; sys.exit(1)
print("all ok")
