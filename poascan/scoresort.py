"""Score sorting across POAScan (1.26.112): Score and its four parts as sort keys, a Top first / Bottom first toggle,
both in the URL (?sort=score&dir=asc), and one control that is a chip row at 1280 and a compact menu at 390.

dir=desc (Top first) is each sort's natural order: highest first for numbers, A to Z for names, fewest closes left first.
dir=asc (Bottom first) reverses it. Rows without a value always sort last."""
from html import escape as E

PARTS = [("score", "Score"), ("standing", "Standing"), ("grading", "Grading"), ("forum", "Forum"), ("consistency", "Consistency")]
KEYS = tuple(k for k, _ in PARTS)
SUBS = KEYS[1:]
DIRS = [("desc", "Top first"), ("asc", "Bottom first")]

def q(qs, k, d=""): return ((qs or {}).get(k) or [d])[0]

def page_sort(qs, allowed, default):
    v = q(qs, "sort", default); return v if v in allowed else default

def page_dir(qs):
    v = q(qs, "dir", "desc"); return v if v in ("desc", "asc") else "desc"

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

def controls(link, sorts, cur, d, label="Sort"):
    """link(sort, dir) gives an href (already HTML escaped). A chip row (wide screens) and a details menu (390)."""
    chips = lambda: "".join(f'<a href="{link(k, d)}" class="chip {"on" if k == cur else ""}"{" aria-current=\"true\"" if k == cur else ""}>{E(t)}</a>' for k, t in sorts)
    dirs = lambda: "".join(f'<a href="{link(cur, k)}" class="chip dir {"on" if k == d else ""}"{" aria-current=\"true\"" if k == d else ""}>{t}</a>' for k, t in DIRS)
    now = dict(sorts).get(cur, cur)
    return (f'<div class="chips sortchips" role="group" aria-label="{E(label)}">{chips()}<span class="sortsep" aria-hidden="true"></span>{dirs()}</div>'
            f'<details class="sortmenu"><summary>{E(label)}: {E(now)} · {dict(DIRS)[d]}</summary><div class="chips">{chips()}</div><div class="chips">{dirs()}</div></details>')
