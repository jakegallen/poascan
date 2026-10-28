"""Sorting across POAScan. Since 1.26.117 every list table sorts by clicking its column headers (heads, select, below);
they replace the 1.26.112 chip rows. Score sorting (1.26.112): Score and its four parts as sort keys, a Top first / Bottom first toggle,
both in the URL (?sort=score&dir=asc), and one control that is a chip row at 1280 and a compact menu at 390.

dir=desc (Top first) is each sort's natural order: highest first for numbers, A to Z for names, fewest closes left first,
a category in its own order. dir=asc (Bottom first) reverses it. The header arrow shows the real order. Blanks always sort last."""
from html import escape as E

PARTS = [("score", "Score"), ("standing", "Standing"), ("grading", "Grading"), ("forum", "Forum"), ("consistency", "Consistency")]
KEYS = tuple(k for k, _ in PARTS)
SUBS = KEYS[1:]

def q(qs, k, d=""): return ((qs or {}).get(k) or [d])[0]

def page_sort(qs, allowed, default, p=""):
    """p: a parameter prefix, so two tables on one page sort apart (?esort=&edir=, 1.26.201)."""
    v = q(qs, p + "sort", default); return v if v in allowed else default

def page_dir(qs, p=""):
    v = q(qs, p + "dir", "desc"); return v if v in ("desc", "asc") else "desc"

def check(sort, allowed, d, err):
    """API and MCP: (sort, dir) or err(message) for a bad value."""
    if sort not in allowed: raise err("sort must be one of " + ", ".join(a for a in allowed if a))
    if d not in ("desc", "asc"): raise err("dir must be desc or asc")
    return sort, d

def order(rows, val, d="desc", natural_desc=True, tie=None):
    """rows sorted by val(row): natural order for d=desc (highest first when natural_desc), reversed for asc; None last."""
    tie = tie or (lambda r: 0)
    have = [r for r in rows if val(r) is not None]; none = [r for r in rows if val(r) is None]
    rev = natural_desc if d == "desc" else not natural_desc
    have.sort(key=tie); have.sort(key=val, reverse=rev)   # stable: ties keep the tie order
    return have + none

# ---- Sortable column headers (1.26.117): one component for every list table ----
# A column is Col(key, label, kind, cls, tip). key None: a plain header. kind says what dir=desc (the default, kept from
# 1.26.112 so API and MCP calls read the same) means for it, and the first click:
#   num  desc = highest first (first click)          low  desc = lowest first; first click is highest first (dir=asc)
#   text desc = A to Z (first click)                 cat  desc = the category's own order (first click)
#   rank desc = rank 1 first (first click)
# The header arrow shows the real order (up = ascending, down = descending); blanks sort last either way.
import collections as _C
Col = _C.namedtuple("Col", "key label kind cls tip", defaults=("num", "", ""))
_NAT_ASC = ("low", "text", "cat", "rank")
_WORDS = {"num": ("high to low", "low to high"), "low": ("high to low", "low to high"), "text": ("A to Z", "Z to A"),
          "cat": ("in order", "reverse order"), "rank": ("top first", "bottom first")}

def ascending(kind, d):
    """True when (kind, dir) puts the lowest value (or A, or the first category) first."""
    nat = kind in _NAT_ASC
    return nat if d == "desc" else not nat

def first_dir(kind):
    """dir for a first click: numbers highest first, text A to Z, categories and ranks in their own order."""
    return "asc" if kind == "low" else "desc"

def keys(cols): return [(c.key, c.label) for c in cols if c.key]

def kind_of(cols, key): return next((c.kind for c in cols if c.key == key), "num")

def sort_rows(rows, val, kind, d, tie=None):
    """Sort rows by val(row) for a column kind and dir; None (a blank or ···) last in either direction, then tie order."""
    return order(rows, val, d, natural_desc=kind not in _NAT_ASC, tie=tie)

def text_key(v):
    """Text sort value: case-folded, blank (None or empty) is None so it sorts last."""
    v = (v or "").strip(); return v.casefold() if v else None

def heads(cols, cur, d, link):
    """<th> cells: each sortable header is a link button (href from link(key, dir), already escaped) with aria-sort and an
    arrow; the active one shows the real direction and a click flips it, the others show a faint arrow on hover.
    A column's tip (the Score ?) sits outside the link, so opening it never sorts."""
    out = []
    if link is None: cols = [c._replace(key=None) for c in cols]   # a short preview table: plain headers
    for c in cols:
        cls = " ".join(x for x in (c.cls, "hs" if c.key else "", "on" if c.key and c.key == cur else "") if x)
        ca = f' class="{cls}"' if cls else ""
        if not c.key:
            out.append(f"<th{ca}>{c.label}{c.tip}</th>"); continue
        on = c.key == cur
        if on:
            up = ascending(c.kind, d); nd = "asc" if d == "desc" else "desc"
            aria, arrow = ("ascending" if up else "descending"), ("↑" if up else "↓")
        else:
            nd = first_dir(c.kind); aria, arrow = "none", "↕"
        nxt = _WORDS[c.kind][0 if ascending(c.kind, nd) == ascending(c.kind, first_dir(c.kind)) else 1]
        lab = E(_plain(c.label))
        out.append(f'<th{ca} aria-sort="{aria}"><a class="hsb" href="{link(c.key, nd)}" rel="nofollow" role="button" title="Sort by {lab}, {nxt}"'
                   f' aria-label="Sort by {lab}, {nxt}">{c.label}<i class="ha" aria-hidden="true">{arrow}</i></a>{c.tip}</th>')
    return "".join(out)

def _plain(s):
    import re
    return re.sub(r"<[^>]+>", "", str(s)).strip()

def select(cols, cur, d, link, label="Sort"):
    """The compact sort menu for phones (shown at 640px and below, where some columns are hidden): one native select,
    each option a link (app.js follows it on change); every sortable column in both directions."""
    opts = []
    for c in cols:
        if not c.key: continue
        f = first_dir(c.kind)
        for dd in (f, "asc" if f == "desc" else "desc"):
            up = ascending(c.kind, dd); w = _WORDS[c.kind][0 if dd == f else 1]
            sel = " selected" if c.key == cur and dd == d else ""
            opts.append(f'<option value="{link(c.key, dd)}"{sel}>{E(_plain(c.label))} {"↑" if up else "↓"} {w}</option>')
    return (f'<label class="sortsel"><span>{E(label)}</span><select data-nav="1" aria-label="{E(label)}">{"".join(opts)}</select></label>')

def link_fn(base, default, frag="", p="", **keep):
    """link(key, dir) for a page: base path plus kept query values; sort and dir dropped at their defaults (sort=default,
    dir=desc); &amp; joined; optional #fragment."""
    def link(k, dd):
        kv = [(a, b) for a, b in keep.items() if b] + [(p + "sort", k if k != default else ""), (p + "dir", "asc" if dd == "asc" else "")]
        kv = [(a, b) for a, b in kv if b]
        q = "&amp;".join(f"{a}={E(str(b))}" for a, b in kv)
        return base + (("&amp;" if "?" in base else "?") + q if q else "") + frag
    return link

def table_sort(qs, cols, items, vals, default, base, frag="", p="", keep=None, tie=None):
    """1.26.201: one call for a page table. items in their natural order; vals {key: fn(item) -> sort value or None}.
    Returns (items sorted, sort spec for ui.table(sort=...)). keep: other query values the links carry (filters, pages,
    another table's sort)."""
    k = page_sort(qs, tuple(vals), default, p); d = page_dir(qs, p)
    idx = {id(x): i for i, x in enumerate(items)}
    out = sort_rows(list(items), vals[k], kind_of(cols, k), d, tie=tie or (lambda x: idx[id(x)]))
    return out, (cols, k, d, link_fn(base, default, frag, p, **(keep or {})))
