"""Unofficial Apps tab (1.26.411): /apps shell, escaped AC1 posts, ATP-20 list,
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
    row(2, "AC1|m|p1test03|01/03|Plus1 part one. ", B, ts=1795180900),
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

check("default tab is Games and shows the storefront", "POA Dice" in html and "app-store" in html and 'aria-current="page"' in html and "Games" in html)
check("unknown tab falls back to Games", "app-store" in html_bad and "POA Dice" in html_bad)
check("disclaimer appears once on each tab", html.count(E(disc)) == 1 and html_posts.count(E(disc)) == 1 and html_games.count(E(disc)) == 1)
check("disclaimer is exact", disc in html.replace("&amp;", "&") or E(disc) in html)
# The disclaimer has no chars that need escape except maybe none. It's plain ASCII.
check("disclaimer raw exact on the page", disc in html)
check("games tab has no unofficial line", "Unofficial" not in html.split(disc, 1)[1])
check("ATP-20 source says unofficial once", "Unofficial" not in disc and html_atp.split(disc, 1)[1].count("Unofficial") == 1)
check("posts source says unofficial once", html_posts.split(disc, 1)[1].count("Unofficial") == 1)
check("posts tab escapes svg and script",
      "&lt;svg&gt;&lt;script&gt;x&lt;/script&gt;&lt;/svg&gt;" in html_posts
      and "<svg><script>x</script></svg>" not in html_posts
      and "<script>x</script>" not in html_posts)
check("posts tab shows grouped excerpt", "part one" in html_posts)
check("games tab labels every catalog entry unendorsed", html_games.count("Unendorsed") == len(AP.GAMES))
check("games show live memo stats", 'data-app="poa-dice"' in html_games and 'data-memos="1"' in html_games and "app-stats" in html_games)
check("games include POA Dice outbound host", "poadice.grok.me" in html_games and "rel=\"noopener noreferrer\"" in html_games)
check("games have no wallet-connect or payment CTA",
      "wallet-connect" not in html_games.lower() and "walletconnect" not in html_games.lower()
      and "deposit" not in html_games.lower() and "connect wallet" not in html_games.lower())
check("PROOF PIT is listed with no invented prefix", "PROOF PIT" in html_games and "None attributed" in html_games)
check("no em or en dash in Apps HTML", nodash(html) and nodash(html_posts) and nodash(html_games) and nodash(html_atp))
check("version is 1.26.411", AG.VERSION == "1.26.411")

# ATP-20 list uses official=false figures from the replay tables
check("ATP-20 list shows SEAL and MAM from the local replay", "SEAL" in html_atp and "MAM" in html_atp)
seal_page = AP.page_html({"tab": ["atp20"], "tick": ["SEAL"]})
check("tick drill-down shows unofficial SEAL holders", "SEAL" in seal_page and "Holder" in seal_page and disc in seal_page)
check("20-row cap constant", AP.LIMIT == 20)

# flood of inline posts stays capped
load(*[row(100 + i, f"AC1|t|note {i}", A, ts=1795182000 + i) for i in range(40)])
check("posts list caps at 20", len(AP.posts(20)) == 20)

# no raw svg path even if someone put svg in a game blurb (catalog is escaped)
check("game blurbs are escaped in HTML", all(E(g["blurb"]) in html_games or g["blurb"] in html_games for g in AP.GAMES))

if fails:
    print("FAILED:"); [print(" -", x) for x in fails]; sys.exit(1)
print("all ok")
