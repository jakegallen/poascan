"""Sortable column headers (1.26.117): one shared component (scoresort.heads, select, sort_rows) on every list table.
Clicking a header sorts by it server side (?sort=&dir= in the URL, CSV and API links); the active header shows an arrow
(up ascending, down descending) and a second click flips it; numbers first sort highest first, text A to Z, categories in
their own order; blanks last either way with a stable tiebreak. Temp database, no network. Usage: python3 tools/headersort_test.py"""
import os, re, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_SEGMENTS", "1")
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "h.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

from poascan import db
db.init()
from poascan import scoresort as SS, governance as GV, views as V, views4 as V4, ui as UI

# ---- the component
check("ascending(): num desc is high to low; text, cat, rank desc are A to Z / in order; low desc is lowest first",
      SS.ascending("num", "desc") is False and SS.ascending("num", "asc") is True and SS.ascending("text", "desc") is True
      and SS.ascending("cat", "desc") is True and SS.ascending("rank", "desc") is True and SS.ascending("low", "desc") is True)
check("first click: numbers highest first, text A to Z (low columns use dir=asc for highest first)",
      SS.first_dir("num") == "desc" and SS.first_dir("text") == "desc" and SS.first_dir("low") == "asc" and not SS.ascending("low", SS.first_dir("low")))
rows = [dict(n="b", v=2), dict(n="a", v=None), dict(n="c", v=2), dict(n="d", v=5), dict(n="", v=1)]
hi = SS.sort_rows(rows, lambda r: r["v"], "num", "desc", tie=lambda r: r["n"]); lo = SS.sort_rows(rows, lambda r: r["v"], "num", "asc", tie=lambda r: r["n"])
check(f"numbers: highest first, ties in tie order, blank last ({[r['n'] for r in hi]})", [r["n"] for r in hi] == ["d", "b", "c", "", "a"])
check(f"numbers ascending: blank still last, ties keep the tie order ({[r['n'] for r in lo]})", [r["n"] for r in lo] == ["", "b", "c", "d", "a"])
az = SS.sort_rows(rows, lambda r: SS.text_key(r["n"]), "text", "desc", tie=lambda r: r["v"] or 0); za = SS.sort_rows(rows, lambda r: SS.text_key(r["n"]), "text", "asc", tie=lambda r: r["v"] or 0)
check(f"text: A to Z, Z to A, blank names last both ways ({[r['n'] for r in az]} / {[r['n'] for r in za]})",
      [r["n"] for r in az] == ["a", "b", "c", "d", ""] and [r["n"] for r in za] == ["d", "c", "b", "a", ""])
check("text_key: case folded, blank is None", SS.text_key(" Bee ") == "bee" and SS.text_key("") is None and SS.text_key(None) is None)
cols = [SS.Col("name", "Agent", "text"), SS.Col("score", "Score", "num", "r", '<details class="qtip"><summary>?</summary></details>'), SS.Col("left", "Left", "low", "r"), SS.Col(None, "Rule")]
link = SS.link_fn("/governance?tab=established", "score", "#established", filter="safe")
h = SS.heads(cols, "score", "desc", link)
th = re.findall(r"<th[^>]*>.*?</th>", h)
check("heads: one th per column; plain header for a column without a key", len(th) == 4 and th[3] == "<th>Rule</th>")
check("active header: aria-sort descending, down arrow, amber (on), link flips to dir=asc and keeps the filter",
      'class="r hs on" aria-sort="descending"' in th[1] and "↓</i>" in th[1] and 'href="/governance?tab=established&amp;filter=safe&amp;dir=asc#established"' in th[1])
check("Score ? sits outside the sort link (opening it never sorts)", re.search(r"</a><details class=\"qtip\">", th[1]) is not None)
check("inactive headers: aria-sort none, faint neutral arrow, first click A to Z for text and highest first for Left",
      'aria-sort="none"' in th[0] and "↕</i>" in th[0] and "sort=name#established" in th[0] and "Sort by Agent, A to Z" in th[0]
      and "sort=left&amp;dir=asc#established" in th[2] and "Sort by Left, high to low" in th[2])
check("headers are focusable link buttons with labels (keyboard: Enter follows, app.js adds Space)", th[0].count('<a class="hsb" href=') == 1 and 'role="button"' in th[0] and 'aria-label="Sort by Agent' in th[0])
h2 = SS.heads(cols, "name", "asc", link)
check("text column active and reversed: ascending false, up arrow off (Z to A shows down)", 'aria-sort="descending"' in re.findall(r"<th[^>]*>.*?</th>", h2)[0] and "↓</i>" in h2)
check("no link: plain headers (preview tables)", "hsb" not in SS.heads(cols, "score", "desc", None))
sel = SS.select(cols, "left", "asc", link)
check("phone sort menu: one native select, every sortable column both ways, current option selected",
      sel.count("<option") == 6 and '<select data-nav="1"' in sel and re.search(r'<option value="[^"]*sort=left&amp;dir=asc#established" selected>Left ↓ high to low</option>', sel) is not None)
src = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read(); css = open(os.path.join(ROOT, "static", "style.css"), encoding="utf-8").read()
check("app.js: Space on a header, the phone menu follows its option", 'e.key===" "' in src and "select[data-nav]" in src and "location.href=v" in src)
check("style.css: faint arrow on hover, amber active header, phone menu only at 640px and below",
      "th.hs .hsb:hover .ha" in css and "th.hs.on" in css and "@media (max-width:640px){.sortsel{display:flex}" in css and ".sortsel{display:none" in css)

# ---- Established: every column sorts, blanks last
est = [dict(address="poa1" + c * 40, name=n, level=lv, since=since, held=h, eligible=e, seals=s, left=left, seats=0, score=sc, standing=sc, grading=1, forum=0, consistency=0)
       for c, n, lv, since, h, e, s, left, sc in (("A", "Zed", "safe", 1, 3, 1, 114, 6, 53), ("B", None, "risk", None, 2, 1, 330, 1, 49),
                                                   ("C", "alpha", "norecord", 2, 2, 0, 244, None, 47), ("D", "Mid", "watch", 1, 5, 2, 192, 3, 44))]
sv = GV.established_rows
GV.established_rows = lambda: (est, {"open_epoch": 3})
try:
    o = lambda by, d: [r["address"][4] for r in GV.established_select(by, "", d)[0]]
    check(f"seals desc then asc ({o('seals', 'desc')} / {o('seals', 'asc')})", o("seals", "desc") == list("BCDA") and o("seals", "asc") == list("ADCB"))
    check(f"name A to Z / Z to A, unnamed last ({o('name', 'desc')} / {o('name', 'asc')})", o("name", "desc") == list("CDAB") and o("name", "asc") == list("ADCB"))
    check(f"level in its order (At risk, Watch, Safe, No record, System) and reversed ({o('level', 'desc')})", o("level", "desc") == list("BDAC") and o("level", "asc") == list("CADB"))
    check(f"added: highest epoch first, blank last both ways ({o('added', 'desc')} / {o('added', 'asc')})", o("added", "desc")[-1] == "B" and o("added", "asc")[-1] == "B" and o("added", "desc")[0] == "C")
    check(f"left: blank (···) last both ways ({o('left', 'asc')} / {o('left', 'desc')})", o("left", "asc") == list("ADBC") and o("left", "desc") == list("BDAC"))
    check("held ties keep the name tiebreak (alpha before unnamed)", o("held", "desc") == list("DACB"))
    for k, _ in GV.EST_SORTS: GV.established_select(k, "", "desc"); GV.established_select(k, "", "asc")
    check("every Established sort key runs both ways", True)
    check("Established columns: Agent, Score, 4 parts, Level, Added, Held, Eligible, Seals, Left; all sortable",
          [c.label for c in GV.est_cols()] == ["Agent", "Score", "Standing", "Grading", "Forum", "Consistency", "Level", "Added", "Held", "Eligible", "Seals", "Left"]
          and all(c.key for c in GV.est_cols()) and {c.key for c in GV.est_cols()} <= {k for k, _ in GV.EST_SORTS})
finally:
    GV.established_rows = sv

# ---- other tables: each header key is a server sort key (so API, CSV and pages agree)
check("At risk, Graders, Directory, Forum headers are all server sort keys",
      all({c.key for c in cs if c.key} <= {k for k, _ in sorts} for cs, sorts in ((GV.risk_cols(), GV.RISK_SORTS), (GV.grader_cols(), GV.GRADER_SORTS),
                                                                             (GV.dir_cols(), GV.DIR_SORTS), (GV.forum_cols(), GV.FORUM_SORTS))))
for tab in V4.COLS:
    ks = {c.key for c in V4.cols(tab) if c.key}
    check(f"Rankings {tab}: every header sorts server side (Load more keeps it)", ks <= set(V4.sorts(tab)) | {"rank"})
sv = (V4._rows, V4._scores)
V4._rows = lambda tab: [dict(addr="poa1" + c * 40, name=n, lifetime=v, last_epoch=1.0, epochs_paid=p, balance=b, rank=i) for i, (c, n, v, p, b) in
                        enumerate((("A", "zed", 9.0, 2, None), ("B", "", 7.0, 5, 3.0), ("C", "Amy", 8.0, 2, 1.0)), 1)]
V4._scores = lambda: {}
try:
    r = lambda so, d: [x["addr"][4] for x in V4.rows("richlist", so, d)]
    check(f"Rankings: name A to Z with unnamed last ({r('name', 'desc')})", r("name", "desc") == list("CAB"))
    check(f"Rankings: balance high to low, blank last both ways ({r('balance', 'desc')} / {r('balance', 'asc')})", r("balance", "desc") == list("BCA") and r("balance", "asc") == list("CBA"))
    check("Rankings: # renumbered after a sort", [x["rank"] for x in V4.rows("richlist", "epochs_paid", "desc")] == [1, 2, 3])
    tb, _ = V4.table_html("richlist", 50, "balance", "desc", lambda k, d: f"/agents/top?tab=richlist&amp;sort={k}&amp;dir={d}")
    check("Rankings table: header sort, no client-side sortable table", 'aria-sort="descending"' in tb and 'class="sortable' not in tb and "data-sort=" not in tb)
finally:
    V4._rows, V4._scores = sv

# ---- Epochs and Payouts tables, through ui.table(sort=...)
ep = [dict(epoch=i, close_ts=1000 + i, paid=p, minted=m, burned=1.0, burn_pct=b, median=md) for i, p, m, b, md in ((0, 0, 0.0, 100.0, None), (1, 116, 82.8, 91.7, 763.4), (2, 50, 40.0, None, 500.0))]
t = V.epochs_table(ep, qs={"sort": ["paid"]}, base="/chain")
check("Epochs: sort by Agents paid, highest first, link flips to dir=asc", re.findall(r'href="/epoch/(\d+)"', t) == ["1", "2", "0"] and 'href="/chain?sort=paid&amp;dir=asc#history"' in t)
t = V.epochs_table(ep, qs={"sort": ["burn_pct"], "dir": ["asc"]}, base="/chain")
check("Epochs: blank burn % last when ascending", re.findall(r'href="/epoch/(\d+)"', t) == ["1", "0", "2"])
t = V.epochs_table(ep, qs={}, base="/chain")
check("Epochs default: newest first, # active", re.findall(r'href="/epoch/(\d+)"', t) == ["2", "1", "0"] and re.search(r'<th class="p hs on" aria-sort="descending"><a class="hsb" href="/chain\?dir=asc#history"', t) is not None)
check("Epochs: bad sort falls back to the default", re.findall(r'href="/epoch/(\d+)"', V.epochs_table(ep, qs={"sort": ["x"]}, base="/chain")) == ["2", "1", "0"])
check("Epochs elsewhere (no base): plain headers", "hsb" not in V.epochs_table(ep))
t = UI.table([], [["1", "x"], ["2", "y"]], sort=([SS.Col("a", "A"), SS.Col(None, "B")], "a", "desc", lambda k, d: f"/p?sort={k}&amp;dir={d}"), pri=(0,))
check("ui.table(sort=...): pri and usd classes kept on sortable headers, phone menu above", '<th class="p hs on"' in t and t.startswith('<label class="sortsel">'))

allsrc = "".join(open(os.path.join(ROOT, f), encoding="utf-8").read() for f in ("poascan/scoresort.py", "static/style.css", "tools/headersort_test.py"))
check("no em or en dash in the new code", "\u2014" not in allsrc and "\u2013" not in allsrc)
print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
