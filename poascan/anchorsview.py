"""Anchor timeline (Network > Anchors, /api/v1/anchors/timeline, MCP get_anchor_timeline): every checkpoint anchored to Base
and Solana in this segment, the gap between anchors, and a state root check per height.

Rows come from POAScan's copy of minepoa's /api/anchors, cross checked against the fast index's anchor list when it is
configured (fastindex.py). A height whose non-empty state roots differ (Base against Solana, minepoa against the fast
index, or the anchor against minepoa's /api/status root at that checkpoint) is a mismatch. No upstream read here."""
import statistics, time
from html import escape as E
from . import db, segments as SG, scoresort as SS
from .ui import card, stat, table, line, lt, rel, short, copy, flag, qtip, iso_ts, TZ

DAY = 86400
RANGES = [("24h", "24h", DAY), ("7d", "7d", 7 * DAY), ("30d", "30d", 30 * DAY), ("all", "All", None)]
RANGE_KEYS = tuple(k for k, _, _ in RANGES)
EXPL = {"base": "https://basescan.org/tx/", "solana": "https://solscan.io/tx/"}
METHOD = "/about#anchors"
COLS = [SS.Col("height", "Height", "num"), SS.Col("ts", f"Anchored ({TZ})", "num"), SS.Col("gap", "Gap", "num"), SS.Col("txs", "Txs", "num"),
        SS.Col(None, "Base"), SS.Col(None, "Solana"), SS.Col(None, "State root"), SS.Col("check", "Check", "cat")]
SORTS = ("height", "ts", "gap", "txs", "check")
CHECK_ORDER = {"mismatch": 0, "single": 1, "match": 2, "none": 3}

def _chain(c):
    c = (c or "").lower()
    return "base" if "base" in c else "solana" if "sol" in c else c or "other"

def merged(seg=None):
    """[{height, ts, base_tx, solana_tx, state_root, roots, check, sources}] oldest first, one row per anchored height."""
    seg = seg or SG.CURRENT; by = {}
    def add(h, chain, tx, root, ts, src):
        r = by.setdefault(int(h), dict(height=int(h), ts=None, base_tx=None, solana_tx=None, roots=[], sources=set()))
        ch = _chain(chain)
        if ch in ("base", "solana") and tx and not r[ch + "_tx"]: r[ch + "_tx"] = tx
        if root: r["roots"].append(dict(chain=ch, source=src, state_root=str(root).lower()))
        if ts and (r["ts"] is None or ts < r["ts"]): r["ts"] = ts
        r["sources"].add(src)
    for a in db.q("SELECT height, chain, tx, state_root, anchored_at FROM anchors WHERE segment=?", (seg,)):
        add(a["height"], a["chain"], a["tx"], a["state_root"], iso_ts(a["anchored_at"]), "minepoa")
    try:
        for a in db.q("SELECT height, chain, tx, state_root, ts FROM fx_anchors WHERE segment=?", (seg,)):
            add(a["height"], a["chain"], a["tx"], a["state_root"], a["ts"], "fast index")
    except Exception: pass   # the table exists once the fast index has run
    st = db.get_blob("status")[0] or {}
    if seg == SG.CURRENT and isinstance(st.get("checkpoint_height"), int) and st.get("state_root") and st["checkpoint_height"] in by:
        by[st["checkpoint_height"]]["roots"].append(dict(chain="checkpoint", source="minepoa status", state_root=str(st["state_root"]).lower()))
    rows = sorted(by.values(), key=lambda r: (r["ts"] or 0, r["height"]))
    prev = None
    for r in rows:
        roots = {x["state_root"] for x in r["roots"]}
        chains = {x["chain"] for x in r["roots"] if x["chain"] in ("base", "solana")} | {c for c in ("base", "solana") if r[c + "_tx"]}
        r["check"] = "mismatch" if len(roots) > 1 else "none" if not roots else "single" if len(chains) < 2 else "match"
        r["state_root"] = next(iter(roots)) if len(roots) == 1 else None
        r["gap_s"] = (r["ts"] - prev["ts"]) if prev and r["ts"] and prev["ts"] else None
        r["txs"] = (r["height"] - prev["height"]) if prev else None
        r["sources"] = sorted(r["sources"]); prev = r
    return rows

def timeline(rng="7d", sort="height", d="desc", limit=200, now=None, seg=None):
    rng = rng if rng in RANGE_KEYS else "7d"
    now = now or time.time(); span = dict((k, v) for k, _, v in RANGES)[rng]
    allr = merged(seg); rows = [r for r in allr if not span or (r["ts"] or 0) >= now - span]
    gaps = [r["gap_s"] for r in rows if r["gap_s"] is not None]
    mism = [r for r in allr if r["check"] == "mismatch"]
    stats = dict(heights=len(rows), last_ts=max((r["ts"] or 0 for r in allr), default=None) or None, last_height=max((r["height"] for r in allr), default=None),
                 median_gap_s=int(statistics.median(gaps)) if gaps else None, max_gap_s=max(gaps) if gaps else None,
                 mismatches=len([r for r in rows if r["check"] == "mismatch"]), mismatches_all=len(mism), single_chain=len([r for r in rows if r["check"] == "single"]),
                 cross_checked=any("fast index" in r["sources"] for r in allr))
    val = {"height": lambda r: r["height"], "ts": lambda r: r["ts"], "gap": lambda r: r["gap_s"], "txs": lambda r: r["txs"],
           "check": lambda r: CHECK_ORDER.get(r["check"], 9)}[sort if sort in SORTS else "height"]
    kind = next((c.kind for c in COLS if c.key == sort), "num")
    out = SS.sort_rows(list(rows), val, kind, d, tie=lambda r: -r["height"])
    return dict(segment=seg or SG.CURRENT, range=rng, sort=sort, dir=d, stats=stats, points=[(r["ts"], r["gap_s"]) for r in rows if r["gap_s"] is not None and r["ts"]],
                rows=out[:limit], total=len(out), mismatch_heights=[r["height"] for r in mism])

def api(rng="7d", sort="height", d="desc", limit=500):
    t = timeline(rng, sort, d, limit)
    keep = ("height", "ts", "gap_s", "txs", "base_tx", "solana_tx", "state_root", "check", "roots", "sources")
    return dict(segment=t["segment"], range=t["range"], sort=t["sort"], dir=t["dir"], stats=t["stats"], total=t["total"],
                mismatch_heights=t["mismatch_heights"], rows=[{k: r[k] for k in keep} for r in t["rows"]],
                explorers=EXPL, method="https://poascan.io" + METHOD)

def _mins(s):
    if s is None: return '<span class="na">···</span>'
    s = int(s); return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{max(1, round(s / 60))}m"

def _txlink(ch, tx):
    if not tx: return '<span class="na">···</span>'
    return f'<a class="mono" href="{EXPL[ch]}{E(tx)}" target="_blank" rel="noopener noreferrer" title="{E(tx)}">{E(short(tx, 8, 6))} ↗</a>'

def _check(r):
    if r["check"] == "match": return '<span class="tag ok">Match</span>'
    if r["check"] == "single":
        return f'<span class="tag" title="Anchored on one chain only">{"Base" if r["base_tx"] else "Solana"} only</span>'
    if r["check"] == "mismatch":
        det = "; ".join(f'{x["chain"]} ({x["source"]}) {x["state_root"][:12]}' for x in r["roots"])
        return flag("Mismatch", "State roots differ: " + det, tone="bad")
    return '<span class="na">···</span>'

def body(qs=None):
    qs = qs or {}
    rng = SS.q(qs, "range", "7d"); rng = rng if rng in RANGE_KEYS else "7d"
    srt = SS.page_sort(qs, SORTS, "height"); d = SS.page_dir(qs)
    t = timeline(rng, srt, d); s = t["stats"]
    mm = s["mismatches"]
    mtag = flag("Mismatch", f'{s["mismatches_all"]} anchored heights with differing state roots', tone="bad") if s["mismatches_all"] else ""
    st = "".join([stat("Anchored heights", f'<span class="num">{s["heights"]:,}</span>', tip="Checkpoint heights anchored in this range"),
                  stat("Last anchor", rel(s["last_ts"]) if s["last_ts"] else "···", tip=f'Height {s["last_height"]:,}' if s["last_height"] is not None else None),
                  stat("Median gap", _mins(s["median_gap_s"]), tip="Median time between consecutive anchored heights"),
                  stat("Longest gap", _mins(s["max_gap_s"]), tip="Longest time between consecutive anchored heights"),
                  stat("Root mismatches", f'<span class="num {"red" if mm else ""}">{mm:,}</span>', flag_html=mtag,
                       tip="Heights whose Base, Solana, minepoa and fast index state roots are not all equal")])
    chips = "".join(f'<a href="/network?tab=anchors{"" if k == "7d" else "&amp;range=" + k}" class="chip {"on" if k == rng else ""}">{n}</a>' for k, n, _ in RANGES)
    ch = line(t["points"], height=170, color="gold", fmt=lambda v: f"{v / 60:,.0f}m", y0=0)
    link = SS.link_fn("/network?tab=anchors", "height", "#anchor-list", range=rng if rng != "7d" else "")
    rows = [[f'<span class="num">{r["height"]:,}</span>', lt(r["ts"]) if r["ts"] else '<span class="na">···</span>', _mins(r["gap_s"]),
             f'{r["txs"]:,}' if r["txs"] is not None else '<span class="na">···</span>', _txlink("base", r["base_tx"]), _txlink("solana", r["solana_tx"]),
             (f'<span class="mono" title="{E(r["state_root"])}">{E(short(r["state_root"], 8, 6))}</span>{copy(r["state_root"])}' if r["state_root"] else '<span class="na">···</span>'),
             _check(r)] for r in t["rows"]]
    tb = table([], rows, cls="anct", pri=(0, 1, 2, 7), sort=(COLS, srt, d, link))
    more = f'<a class="more" href="/api/v1/anchors/timeline?range={rng}">API →</a>'
    return (f'<div class="stats five">{st}</div><div class="chips rng" role="group" aria-label="Range">{chips}</div>'
            + card("Gap between anchors", ch, qtip("Minutes from one anchored checkpoint to the next, Base and Solana together.", METHOD, "About the gap", "hv"))
            + card(f'Anchors · {t["total"]:,}', tb, more, id="anchor-list"))
