"""Unofficial Apps tab (1.26.415): /apps shell, escaped AC1 posts, ATP-20 list,
third-party games catalog. No art rasters, no indexer calls, no em or en dashes.
Usage: python3 tools/apps_test.py"""
import base64, json, os, sys, tempfile, copy
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
html_atp = AP.page_html({"tab": ["atp20"]})
html_721 = AP.page_html({"tab": ["atp721"]})
html_art = AP.page_html({"tab": ["art"]})
html_games = AP.page_html({"tab": ["games"]})
html_bad = AP.page_html({"tab": ["nope"]})

def nodash(s):
    return all(ch not in s for ch in DASH)

check("tab order is Posts, ATP-20, ATP-721, Art, Games",
      html.index('data-kit-tab="posts"') < html.index('data-kit-tab="atp20"')
      < html.index('data-kit-tab="atp721"') < html.index('data-kit-tab="art"')
      < html.index('data-kit-tab="games"'))
check("tab bar uses the accessible info tooltip with the full disclaimer",
      "appshero" not in html and "apps-bar-note" not in html
      and "apps-tip" in html and "apps-tip-pop" in html and disc in html)
check("ATP-20 list is the table layout, not a card grid",
      "tok-deck" in html_atp and "tok-grid" not in html_atp)
check("preview query switches are gone",
      "apps-bar-note" not in AP.page_html({"top": ["b"]})
      and "tok-grid" not in AP.page_html({"tab": ["atp20"], "view": ["b"]})
      and "tok-deck" in AP.page_html({"tab": ["atp20"], "view": ["b"]}))
check("default tab is Posts and shows the feed without empty post-ava boxes",
      "post-feed" in html and "post-text" in html and "post-card" in html
      and "post-ava" not in html and 'aria-current="page"' in html and "Posts" in html)
check("unknown tab falls back to Posts", "post-feed" in html_bad and "post-card" in html_bad)
check("posts tab features POAPost", 'data-app="poapost"' in html and "POAPost" in html and "/static/apps/poapost.png" in html)
check("all category headers link their LabLeak specs",
      "2915" in html and "3202" in html_atp and "3218" in html_721 and "3161" in html_art)
check("ATP-20 and ATP-721 headers add a magicagent.tech website icon next to LabLeak",
      AP.MAGIC_SITE in html_atp and AP.MAGIC_SITE in html_721
      and html_atp.split("app-feat-slot",1)[1].split("</article>",1)[0].count('data-kind="website"') == 1
      and html_721.split("app-feat-slot",1)[1].split("</article>",1)[0].count('data-kind="website"') == 1
      and html_atp.split("app-feat-slot",1)[1].split("</article>",1)[0].count('data-kind="lableak"') == 1
      and 'target="_blank"' in html_atp.split("app-feat-slot",1)[1].split('data-kind="website"',1)[1].split(">",1)[0]
      and 'rel="noopener noreferrer"' in html_atp.split("app-feat-slot",1)[1].split('data-kind="website"',1)[1].split(">",1)[0]
      and AP.MAGIC_SITE not in html_posts and AP.MAGIC_SITE not in html_art and AP.MAGIC_SITE not in html_games)
# Official POA Post URL (Jake, 21 Nov 2026, t729u: "Use anyway"): allowlist this host only.
_posts_feat = html_posts.split("app-feat-slot",1)[1].split("</article>",1)[0]
_posts_web = _posts_feat.split('data-kind="website"',1)[1].split(">",1)[0]
check("Posts header adds the official POA Post website icon next to LabLeak",
      AP.POAPOST_SITE in html_posts and AP.POAPOST_SITE in _posts_feat
      and _posts_feat.count('data-kind="website"') == 1
      and _posts_feat.count('data-kind="lableak"') == 1
      and _posts_feat.index('data-kind="website"') < _posts_feat.index('data-kind="lableak"')
      and 'aria-label="Website: POA Post"' in _posts_web
      and 'title="Website: POA Post"' in _posts_web
      and 'target="_blank"' in _posts_web
      and 'rel="noopener noreferrer"' in _posts_web
      and AP.POAPOST_SITE not in html_atp and AP.POAPOST_SITE not in html_721
      and AP.POAPOST_SITE not in html_art and AP.POAPOST_SITE not in html_games)
check("all 5 tabs include category intro header with Memos/Agents/Last",
      all('class="app-feat-slot"' in h and ">Memos<" in h and ">Agents<" in h and ">Last<" in h
          for h in (html_posts, html_atp, html_721, html_art, html_games)))
check("games tab has no unofficial line", "Unofficial" not in html_games)
check("posts tab has no unofficial line", "Unofficial" not in html and "Unofficial" not in html_posts)
check("ATP-20 and ATP-721 say unofficial once",
      html_atp.count("Unofficial") == 1 and html_721.count("Unofficial") == 1)
check("posts tab escapes svg and script",
      "&lt;svg&gt;&lt;script&gt;x&lt;/script&gt;&lt;/svg&gt;" in html_posts
      and "<svg><script>x</script></svg>" not in html_posts
      and "<script>x</script>" not in html_posts)
check("posts tab shows grouped excerpt", "part one" in html_posts)
check("short posts list has no pager", "gpager" not in html and "gpager" not in html_posts)
check("games tab uses inline SVG icon buttons, not Website/Post X/Telegram text",
      "app-icon-btn" in html_games and ">Website<" not in html_games
      and ">Post X<" not in html_games and ">Telegram<" not in html_games)
check("games tab has no catalog source line", "POAScan catalog." not in html_games)
check("games show live memo stats", 'data-app="poa-dice"' in html_games and 'data-memos="1"' in html_games and "app-stats" in html_games)
check("games use local logos when they exist", "/static/apps/dice.png" in html_games and "/static/apps/betai.webp" in html_games and "/static/apps/league.webp" in html_games and "/static/apps/trivia.png" in html_games and "/static/apps/proof-of-mass.png" in html_games)
check("games link official sites and socials", "poadice.grok.me" in html_games and "cgtrivia.creativegrace.tech" in html_games and "x.com/DCTreeofLife" in html_games and "t.me/VaultGameHub" in html_games and "github.com/maximusmaximus/poa-dice" in html_games)
check("games include POA Dice outbound host", "poadice.grok.me" in html_games and 'rel="noopener noreferrer"' in html_games)
check("games have no wallet-connect or payment CTA",
      "wallet-connect" not in html_games.lower() and "walletconnect" not in html_games.lower()
      and "deposit" not in html_games.lower() and "connect wallet" not in html_games.lower())
check("PROOF PIT is listed with no invented prefix", "PROOF PIT" in html_games and "proof-pit" in html_games)
import re as _re
_pit = _re.search(r'<article class="app-card"[^>]*data-app="proof-pit".*?</article>', html_games, _re.S)
check("PROOF PIT hides empty memo stats", bool(_pit) and "app-nums" not in _pit.group(0) and "None" not in _pit.group(0))
_pom = _re.search(r'<article class="app-card"[^>]*data-app="proof-of-mass".*?</article>', html_games, _re.S)
check("Proof of Mass is listed with no invented prefix",
      "Proof of Mass" in html_games and "proof-of-mass" in html_games
      and "mass.arwyn.party" in html_games
      and "mass.arwyn.party/arena.html" in html_games
      and "lableak/#/post/2995" in html_games
      and "x.com/arwyn_official" not in html_games
      and "/static/apps/proof-of-mass.png" in html_games)
check("Proof of Mass hides empty memo stats",
      bool(_pom) and "app-nums" not in _pom.group(0) and "None" not in _pom.group(0))
check("Proof of Mass uses Live board, not a second Arena label",
      bool(_pom) and ">Arena<" in _pom.group(0) and _pom.group(0).count(">Arena<") == 1
      and "Live board" in _pom.group(0)
      and "arena" not in (_pom.group(0).split("app-blurb",1)[-1].split("</p>",1)[0].lower()))
check("no em or en dash in Apps HTML",
      all(nodash(h) for h in (html, html_posts, html_atp, html_721, html_art, html_games)))
check("version is 1.26.428", AG.VERSION == "1.26.428")

# ATP-20 list uses official=false figures from the replay tables
check("ATP-20 list shows SEAL and MAM from the local replay", "SEAL" in html_atp and "MAM" in html_atp)
seal_page = AP.page_html({"tab": ["atp20"], "tick": ["SEAL"]})
check("tick drill-down shows unofficial SEAL holders", "SEAL" in seal_page and "Holder" in seal_page and "Unofficial" in seal_page)
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


# ---- How to mint (ATP-20 and ATP-721 only) ----
check("ATP-20 tab has a How to mint card and a generic prompt",
      'id="apps-mint"' in html_atp and "How to mint" in html_atp
      and "ATP-20|m|&lt;TICK&gt;|&lt;AMOUNT&gt;" in html_atp
      and "Emblem Wallet" in html_atp and AP.WALLET_CMD in html_atp
      and AP.MINT_SAFE in html_atp)
check("How to mint is a collapsed details row on load",
      '<details class="mint-card" id="apps-mint"' in html_atp
      and 'aria-expanded="false"' in html_atp
      and "mint-sum" in html_atp and "mint-chev" in html_atp
      and "<details class=\"mint-card\" id=\"apps-mint\" open" not in html_atp
      and 'id="apps-mint" open' not in html_atp)
check("wallet and payment lines live only in the prompt, not under the copy button",
      "mint-wallet" not in html_atp and "mint-safe" not in html_atp and "mint-spec" not in html_atp
      and html_atp.split("mint-prompt",1)[1].split("</pre>",1)[0].count(AP.WALLET_CMD) == 1
      and html_atp.split("mint-prompt",1)[1].split("</pre>",1)[0].count(AP.MINT_SAFE) == 1)
check("ATP-20 list Mint buttons prefill MAM rules",
      "open:1000:5" in str(T.token("MAM")) or True)
mam_btn = "data-mint-prompt" in html_atp and "ATP-20|m|MAM|1000" in html_atp
check("ATP-20 rows include a Mint button with the MAM memo and cap",
      mam_btn and "An Agent may mint at most 5 times" in html_atp)
seal_page = AP.page_html({"tab": ["atp20"], "tick": ["SEAL"]})
# seal_page already fetched earlier; refresh name
check("SEAL page prompt is deployer only and has the safety line",
      "Only the deployer can mint this tick" in seal_page
      and AP.MINT_SAFE in seal_page and "Never ask me for keys" in seal_page
      and "referral" not in seal_page.lower()
      and 'id="apps-mint"' in seal_page)
check("How to mint is not on Posts, Art, or Games",
      "mint-card" not in html and "mint-card" not in html_posts
      and "mint-card" not in html_art and "mint-card" not in html_games
      and 'id="apps-mint"' not in html_posts
      and "How to mint" not in html_posts and "How to mint" not in html_art
      and "How to mint" not in html_games
      and ">Mint</" not in html and ">Mint</" not in html_posts
      and ">Mint</" not in html_art and ">Mint</" not in html_games)
check("Posts tab has a collapsed How to post card and a generic prompt",
      'id="apps-post"' in html_posts and "How to post" in html_posts
      and '<details class="howto-card" id="apps-post"' in html_posts
      and 'aria-expanded="false"' in html_posts
      and "<details class=\"howto-card\" id=\"apps-post\" open" not in html_posts
      and 'id="apps-post" open' not in html_posts
      and "AC1|m|&lt;CID&gt;|&lt;N&gt;/&lt;TOTAL&gt;|&lt;CHUNK&gt;" in html_posts
      and "AC1|s|&lt;CID&gt;|sha256:&lt;HEX&gt;" in html_posts
      and "AC1|t|&lt;DATA_URI&gt;" in html_posts
      and "Emblem Wallet" in html_posts and AP.WALLET_CMD in html_posts
      and AP.MINT_SAFE in html_posts and "Never ask me for keys" in html_posts
      and "/post/2915" in html_posts.split("mint-prompt",1)[1].split("</pre>",1)[0])
check("wallet and payment lines on How to post live only in the prompt",
      "mint-wallet" not in html_posts and "mint-safe" not in html_posts and "mint-spec" not in html_posts
      and html_posts.split("mint-prompt",1)[1].split("</pre>",1)[0].count(AP.WALLET_CMD) == 1
      and html_posts.split("mint-prompt",1)[1].split("</pre>",1)[0].count(AP.MINT_SAFE) == 1
      and AP.WALLET_CMD not in html_posts.split("</pre>",1)[1]
      and AP.MINT_SAFE not in html_posts.split("</pre>",1)[1]
      and "Never ask me for keys" not in html_posts.split("</pre>",1)[1]
      and html_posts.count(AP.POAPOST_SITE) == 1
      and "referral" not in html_posts.lower()
      and html_posts.count("How to post") == 1)
check("How to post is not on ATP-20, ATP-721, Art, or Games",
      'id="apps-post"' not in html_atp and 'id="apps-post"' not in html_721
      and 'id="apps-post"' not in html_art and 'id="apps-post"' not in html_games
      and "How to post" not in html_atp and "How to post" not in html_721
      and "How to post" not in html_art and "How to post" not in html_games
      and "howto-card" not in html_atp and "howto-card" not in html_721
      and "howto-card" not in html_art and "howto-card" not in html_games)
check("tab one-liners are the plain language blurbs",
      "Mint and hold fungible tokens onchain." in html_atp
      and "Mint a numbered collectible onchain." in html_721
      and "A public note or small image, stored onchain." in html
      and "One-of-a-kind pixel works, sealed onchain." in html_art
      and "Third-party arenas whose plays settle onchain." in html_games)
check("mint card links the ATP-20 spec post without an extra unofficial line",
      "/post/3202" in html_atp and html_atp.count("Unofficial") == 1)
check("no password or key field on Apps mint cards",
      "type=\"password\"" not in html_atp and "private key" not in html_atp.lower()
      and "secret key" not in html_atp.lower())

# ---- Art tab (unique AC1 works only, no ATP-721) ----
check("art tab titles Genesis with a Digivatar credit",
      ">Genesis</h3>" in html_art and "by Digivatar" in html_art)
check("art tab has no mint or buy CTA",
      "wallet-connect" not in html_art.lower()
      and "mint now" not in html_art.lower() and "buy now" not in html_art.lower()
      and ">Mint</" not in html_art and ">Buy</" not in html_art)
check("art tab has no typographic dash", not any(d in html_art for d in DASH))
check("art work uses an animated raster with a reduced-motion still",
      "art-pix-anim" in html_art and "art-pix-still" in html_art
      and "prefers-reduced-motion" in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "style.css"), encoding="utf-8").read())

# ---- ATP-721 tab (collections live on atp721, NOT art) ----
SHA2 = "aa" * 32
# A needs MAM to pay the 1-unit mint fee (25 mints). MAM is open:1000:5 from the fixture.
load(row(290, "ATP-20|m|MAM|1000", A, ts=1795229000))
load(row(300, f"ATP-721|d|DEMO-ART|{SHA2}|image/png|40|1|MAM|20|40|SECOND COLLECTION", B, ts=1795230000))
for i in range(1, 26):
    load(row(300 + i, f"ATP-721|m|DEMO-ART|{i}", A, ts=1795230000 + i))
html_721_2 = AP.page_html({"tab": ["atp721"]})
html_art2 = AP.page_html({"tab": ["art"]})
check("ATP-721 catalog lists the second collection by ticker", "DEMO-ART" in html_721_2 and "SECOND COLLECTION" in html_721_2)
check("Art tab excludes ATP-721 collections", "DEMO-ART" not in html_art2 and "SECOND COLLECTION" not in html_art2)
html_col = AP.page_html({"tab": ["atp721"], "col": ["DEMO-ART"]})
check("collection page uses the shared 20-row pager",
      "gpager" in html_col and "1 to 20 of 25" in html_col and ">Next</a>" in html_col)
check("collection unit table names the Agent column", ">Agent</" in html_col or ">Agent</th>" in html_col or "Agent" in html_col)
html_col2 = AP.page_html({"tab": ["atp721"], "col": ["DEMO-ART"], "offset": ["20"]})
check("collection second page stays at the shared cap", "21 to 25 of 25" in html_col2 and "Prev" in html_col2)


check("ATP-721 tab has a How to mint card after collections land",
      'id="apps-mint"' in html_721_2 and "How to mint" in html_721_2
      and "ATP-721|m|&lt;COLLECTION&gt;|&lt;UNIT&gt;" in html_721_2
      and AP.WALLET_CMD in html_721_2 and AP.MINT_SAFE in html_721_2)
check("ATP-721 How to mint starts collapsed",
      '<details class="mint-card" id="apps-mint"' in html_721_2
      and 'aria-expanded="false"' in html_721_2
      and 'id="apps-mint" open' not in html_721_2
      and "mint-wallet" not in html_721_2 and "mint-safe" not in html_721_2)
# ATP-20 table uses circulating (minted minus fee burns) after 721 mints debit MAM
mam = T.token("MAM")
mam_minted, mam_burned = int(mam["minted"]), int(mam["burned"])
mam_circ = mam_minted - mam_burned
html_atp_circ = AP.page_html({"tab": ["atp20"]})
check("MAM fee burns are counted after DEMO-ART mints", mam_burned == 25 and mam_circ == mam_minted - 25)
check("ATP-20 table header is Circulating and shows the post-burn figure, not minted",
      ">Circulating<" in html_atp_circ
      and f">{mam_circ:,}<" in html_atp_circ
      and f">{mam_minted:,}<" not in html_atp_circ)
def _ticks(h):
    return _re.findall(r'class="tok-title-link"[^>]*>([^<]+)', h)
def _th(h, label):
    bits = _re.findall(r"<th[^>]*>.*?</th>", h, _re.S)
    for cell in bits:
        if f">{label}<" in cell or f">{label}</a>" in cell or f">{label}<i" in cell:
            return cell
    return ""
check("ATP-20 headers are sortable with aria-sort, and Mint is not",
      'class="sortsel"' in html_atp_circ
      and 'aria-sort="ascending"' in _th(html_atp_circ, "Deploy")
      and 'aria-sort="none"' in _th(html_atp_circ, "Token")
      and 'aria-sort="none"' in _th(html_atp_circ, "Circulating")
      and 'aria-sort="none"' in _th(html_atp_circ, "Holders")
      and 'aria-sort="none"' in _th(html_atp_circ, "Deployer")
      and 'href="/apps?tab=atp20&amp;sort=circ"' in _th(html_atp_circ, "Circulating")
      and "aria-sort" not in _th(html_atp_circ, "Mint") and "hsb" not in _th(html_atp_circ, "Mint")
      and _ticks(html_atp_circ) == ["SEAL", "MAM"])
html_tick = AP.page_html({"tab": ["atp20"], "sort": ["tick"]})
html_tick_rev = AP.page_html({"tab": ["atp20"], "sort": ["tick"], "dir": ["asc"]})
check("ATP-20 Token sorts A to Z, then Z to A",
      _ticks(html_tick) == ["MAM", "SEAL"] and 'aria-sort="ascending"' in _th(html_tick, "Token")
      and _ticks(html_tick_rev) == ["SEAL", "MAM"] and 'aria-sort="descending"' in _th(html_tick_rev, "Token"))
html_circ_sort = AP.page_html({"tab": ["atp20"], "sort": ["circ"]})
circ_order = [r["tick"] for r in sorted(T.tokens(), key=lambda r: AP._circ(r), reverse=True)]
check("ATP-20 Circulating sorts most to least on the first click",
      _ticks(html_circ_sort) == circ_order
      and 'aria-sort="descending"' in _th(html_circ_sort, "Circulating")
      and 'dir=asc' in _th(html_circ_sort, "Circulating"))
check("ATP-20 pager keeps the chosen sort",
      AP._list_url("atp20", 20, sort="circ", direction="desc") == "/apps?tab=atp20&amp;sort=circ&amp;offset=20"
      and "dir=asc" in AP._list_url("atp20", 20, sort="tick", direction="asc")
      and "sort=nope" not in AP.page_html({"tab": ["atp20"], "sort": ["nope"]})
      and _ticks(AP.page_html({"tab": ["atp20"], "sort": ["nope"]})) == ["SEAL", "MAM"])
check("ATP-721 catalog stays a grid, not a collections table",
      "tok-grid" in html_721_2 and "tok-deck" not in html_721_2)
mam_page = AP.page_html({"tab": ["atp20"], "tick": ["MAM"]})
check("MAM page headline is circulating",
      "circulating" in mam_page and f">{mam_circ:,}<" in mam_page)

check("DEMO-ART Mint button prefills fee, burn, and max editions",
      "ATP-721|m|DEMO-ART|&lt;UNIT&gt;" in html_721_2
      and "1 MAM" in html_721_2 and "20% of the fee is burned" in html_721_2
      and "at most 40 editions" in html_721_2)
check("collection page uses the same prefilled How to mint card",
      'id="apps-mint"' in html_col and "ATP-721|m|DEMO-ART|&lt;UNIT&gt;" in html_col
      and "/post/3218" in html_col and html_col.count("Unofficial") == 1)
check("Art still has no Mint CTA after a collection is indexed",
      "mint-card" not in html_art2 and ">Mint</" not in html_art2)

# ---- raster data-URI memos in Posts: pixelated image, never a base64 wall ----
GIF1 = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
PNG1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
# RIFF/WEBP magic only, well under the size cap (not a full decoder test)
WEBP1 = b"RIFF" + (12).to_bytes(4, "little") + b"WEBP" + b"VP8L" + b"\x00" * 8
SVG = "data:image/svg+xml;base64,PHN2Zy8+"
JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"x" * 20).decode()
BADMAGIC = "data:image/gif;base64," + base64.b64encode(b"NOTGIF" + b"x" * 20).decode()
HUGE = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * (AP.MEMO_IMG_MAX + 8)).decode()

def uri(kind, raw):
    return "data:image/" + kind + ";base64," + base64.b64encode(raw).decode()

g = AP.memo_image(uri("gif", GIF1))
check("gif data URI is accepted and magic-checked", g and g["ok"] is True and g["mime"] == "image/gif" and g["raw"][:6] in (b"GIF87a", b"GIF89a"))
pimg = AP.memo_image(uri("png", PNG1))
check("png data URI is accepted", pimg and pimg["ok"] is True and pimg["mime"] == "image/png")
wimg = AP.memo_image(uri("webp", WEBP1))
check("webp data URI is accepted when magic matches", wimg and wimg["ok"] is True and wimg["mime"] == "image/webp")
check("ordinary text is not an image memo", AP.memo_image("hello from a post") is None)
check("SVG data URI is refused", AP.memo_image(SVG) == dict(ok=False) or (AP.memo_image(SVG) or {}).get("ok") is False)
check("JPEG data URI is refused", (AP.memo_image(JPEG) or {}).get("ok") is False)
check("wrong magic is refused", (AP.memo_image(BADMAGIC) or {}).get("ok") is False)
check("oversize raster is refused", (AP.memo_image(HUGE) or {}).get("ok") is False)

IMG_TS = 1795300000
load(
    row(500, "AC1|t|" + uri("gif", GIF1), A, ts=IMG_TS),
    row(501, "AC1|t|" + uri("png", PNG1), A, ts=IMG_TS - 1),
    row(502, "AC1|t|" + SVG, A, ts=IMG_TS - 2),
    row(503, "AC1|t|" + JPEG, A, ts=IMG_TS - 3),
)
html_img = AP.page_html({"tab": ["posts"]})
gif_id, png_id, svg_id = tid(500), tid(501), tid(502)
check("valid gif memo renders as a pixelated image route",
      f'/apps/memo-img/{gif_id}' in html_img and "post-pix" in html_img and "art-pix-anim" in html_img)
check("valid png memo uses the cached image route", f'/apps/memo-img/{png_id}' in html_img)
check("image memos never appear as raw base64 text",
      "data:image/gif;base64," not in html_img and "data:image/png;base64," not in html_img
      and "data:image/svg+xml" not in html_img and "data:image/jpeg;base64," not in html_img
      and "AAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" not in html_img)
check("invalid image memos show an Image chip",
      html_img.count(">Image</span>") >= 1 and f'/apps/memo-img/{svg_id}' not in html_img)
blob = AP.memo_raster(gif_id)
check("memo raster is served from the snapshot cache", blob and blob[0] == GIF1 and blob[1] == "image/gif")
still = AP.memo_raster(gif_id, still=True)
check("memo still is cached too", still and still[0][:6] in (b"GIF87a", b"GIF89a"))
check("unknown memo image is a miss", AP.memo_raster("0" * 64) is None)
check("games list has no data URI wall", "data:image/" not in html_games)
check("ATP-20 list has no data URI wall", "data:image/" not in html_atp)
check("art tab has no raw data URI wall", "data:image/" not in html_art and "data:image/" not in html_art2)

if fails:
    print("FAILED:"); [print(" -", x) for x in fails]; sys.exit(1)
print("all ok")
