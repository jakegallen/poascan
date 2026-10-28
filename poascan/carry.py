"""Genesis cut carry (1.26.209): Governance, Established. Per address, how Established standing crossed the genesis cut, from
public records only: the segment 2 genesis import (established.json, pinned by sha256) and the close records of both
segments, folded by the engine rule (estfold.py). Neutral labels, no ranking and no commentary. No upstream read.

Rows: every Agent flagged Established in the segment 2 genesis import, plus every Agent Established at the last segment 1
close by the fold. Fields: carried (flagged in the import), s1_established_last (Established at the last segment 1 close),
s1_last_eligible (the last segment 1 close listing it in challenge_eligible), s1_change (the fold's latest change: added or
removed, and at which close), s2_admitted (the first segment 2 close listing it in established_after), s2_established_now,
s2_rewards and s2_paid_closes (segment 2 rewards in the close records)."""
from . import analytics as A, estfold as EF, scoresort as SS
from .ui import E, card, intc, qtip

METHOD = "/about#carry"
FILTERS = [("", "All"), ("carried", "Carried"), ("not_carried", "Not carried")]

def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0

@A.cached("genesis_carry", 900)
def data():
    s1 = sorted(A.segment_closes(1), key=lambda e: int(e.get("epoch", 0))); s2 = sorted(A.segment_closes(2), key=lambda e: int(e.get("epoch", 0)))
    pard = A.params().get("slash_pardons")
    est1, le1, why1 = EF.fold(s1, EF.imported(1), pard)
    imp = EF.imported(2); est2, _, _ = EF.fold(s2, imp, pard)
    adm, rw, pc = {}, {}, {}
    for e in s2:
        n = int(e.get("epoch", 0))
        for a in (e.get("basis") or {}).get("established_after") or []: adm.setdefault(a, n)
        for a, v in (e.get("rewards") or {}).items():
            if _f(v) > 0: rw[a] = rw.get(a, 0.0) + _f(v); pc[a] = pc.get(a, 0) + 1
    rows = []   # addresses only: no display names in this view
    for a in sorted(set(imp) | est1):
        how, at = why1.get(a, (None, None))
        rows.append(dict(address=a, carried=a in imp, s1_established_last=a in est1, s1_last_eligible=le1.get(a),
                         s1_change=how if how in ("added", "removed") else None, s1_change_close=at,
                         s2_admitted=None if a in imp else adm.get(a), s2_established_now=a in est2,
                         s2_rewards=round(rw.get(a, 0.0), 6), s2_paid_closes=pc.get(a, 0)))
    info = EF.import_info(2) or {}
    return dict(rows=rows, counts=dict(rows=len(rows), carried=sum(r["carried"] for r in rows), s1_established_last=sum(r["s1_established_last"] for r in rows),
                                       both=sum(r["carried"] and r["s1_established_last"] for r in rows),
                                       carried_only=sum(r["carried"] and not r["s1_established_last"] for r in rows),
                                       s1_only=sum(r["s1_established_last"] and not r["carried"] for r in rows)),
                import_=dict(url=info.get("url"), sha256=info.get("sha256"), established_count=info.get("established_count"), final_checkpoint_height=info.get("final_checkpoint_height")),
                s1_last_close=int(s1[-1]["epoch"]) if s1 else None)

COLS = [SS.Col("name", "Address", "text"), SS.Col("carried", "Carried", "cat", "r"), SS.Col("s1", "S1 last close", "cat", "r"), SS.Col("s1_le", "S1 last eligible", "num", "r dk"),
        SS.Col("s2_adm", "S2 admitted", "num", "r dk"), SS.Col("s2_now", "S2 now", "cat", "r"), SS.Col("s2_rw", "S2 rewards", "num", "r")]
_V = {"name": lambda r: SS.text_key(r["address"]), "carried": lambda r: 1 if r["carried"] else 0, "s1": lambda r: 1 if r["s1_established_last"] else 0,
      "s1_le": lambda r: r["s1_last_eligible"] if r["s1_last_eligible"] is not None else -1, "s2_adm": lambda r: r["s2_admitted"] if r["s2_admitted"] is not None else -1,
      "s2_now": lambda r: 1 if r["s2_established_now"] else 0, "s2_rw": lambda r: r["s2_rewards"]}
TIP = ("Carried: flagged Established in the segment 2 genesis import. S1 last close: Established at the last segment 1 close by the engine fold of the close records. "
       "S1 last eligible: the last segment 1 close listing it in challenge_eligible. S2 admitted: the first segment 2 close listing it in established_after. "
       "S2 now: Established after the latest close. S2 rewards: segment 2 rewards in the close records.")

def select(f="", by="name", d="asc"):
    rs = data()["rows"]
    if f == "carried": rs = [r for r in rs if r["carried"]]
    elif f == "not_carried": rs = [r for r in rs if not r["carried"]]
    return SS.sort_rows(list(rs), _V.get(by, _V["name"]), SS.kind_of(COLS, by), d, tie=lambda r: r["address"])

def _yn(v): return '<span class="tag ok">Yes</span>' if v else '<span class="dim">No</span>'
def _e(n): return f"E{n}" if n is not None else '<span class="dim">···</span>'

def card_html(qs, href):
    d = data(); c = d["counts"]
    if not d["rows"]: return ""
    q1 = lambda k, dflt="": ((qs or {}).get(k) or [dflt])[0]
    f = q1("carry"); f = f if f in dict(FILTERS) else ""
    by = q1("csort") or "name"; by = by if by in _V else "name"; dr = q1("cdir") or ("asc" if by == "name" else "desc"); dr = dr if dr in ("asc", "desc") else "desc"
    keep = lambda **o: dict(dict(carry=f, csort=by if by != "name" else "", cdir=dr if dr != ("asc" if by == "name" else "desc") else ""), **o)
    link = lambda k, dd: href("established", **keep(csort=k if k != "name" else "", cdir=dd)) + "#carry"
    rs = select(f, by, dr)
    cnt = {"": c["rows"], "carried": c["carried"], "not_carried": c["rows"] - c["carried"]}
    chips = "".join(f'<a href="{href("established", **keep(carry=k))}#carry" class="chip {"on" if k == f else ""}">{t} <small>{cnt[k]:,}</small></a>' for k, t in FILTERS)
    trs = "".join(f'<tr><td><a class="mono" href="/address/{E(r["address"])}">{E(r["address"][:8])}…{E(r["address"][-4:])}</a></td><td class="r">{_yn(r["carried"])}</td><td class="r">{_yn(r["s1_established_last"])}</td>'
                  f'<td class="r dk">{_e(r["s1_last_eligible"])}</td><td class="r dk">{_e(r["s2_admitted"])}</td><td class="r">{_yn(r["s2_established_now"])}</td>'
                  f'<td class="r">{intc(round(r["s2_rewards"]))}</td></tr>' for r in rs)
    cols = [x._replace(tip=qtip(TIP, METHOD, "About these columns", "hv")) if x.key == "carried" else x for x in COLS]
    tb = (SS.select(cols, by, dr, link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(cols, by, dr, link)}</tr></thead><tbody>{trs}</tbody></table></div>')
    im = d["import_"]
    foot = (f'<p class="cov dim small">{c["carried"]:,} flagged in the import · {c["s1_established_last"]:,} Established at the last segment 1 close (E{d["s1_last_close"]}) · '
            f'{c["both"]:,} both · {c["carried_only"]:,} import only · {c["s1_only"]:,} close records only · Import sha256 {E((im.get("sha256") or "")[:12])}… · '
            f'<a href="{METHOD}">Method</a></p>')
    links = '<a class="more" href="/api/v1/governance/genesis-carry">API →</a>'
    return card(f"Genesis cut carry · {len(rs):,}", f'<div class="chips">{chips}</div>' + tb + foot, links, cls="histc", id="carry")

def api(address=None, f=""):
    d = data(); rs = select(f)
    if address: rs = [r for r in d["rows"] if r["address"] == address]
    return dict(counts=d["counts"], genesis_import=d["import_"], s1_last_close=d["s1_last_close"], filter=f or None, address=address, total=len(rs), rows=rs,
                definitions=TIP, method="https://poascan.io" + METHOD, url="https://poascan.io/governance?tab=established#carry")
