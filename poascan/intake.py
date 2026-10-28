"""Intake per close (1.26.189): Governance, Intake. Who could have become established at each close, the door's cap, who got in
and who was eligible but not admitted.

From the public close records only (no upstream read), replaying minepoa's engine one close at a time, the same fold as
govv2.standing_changes (genesis import, plus established_after, minus established_removed, pardons honoured):
  set       established Agents before the close
  eligible  the close's basis.challenge_eligible Agents not already established
  cap       max(floor, ceil(rate x set)): the engine's door, floor 5 and rate 0.10 (LabLeak post 1582; comment 6193 adds the
            ceil). Proposal L would set both by params (estab_intake_floor, estab_intake_rate); POAScan reads them per close
            when /api/params carries them (estab_intake_from_epoch, when given, says from which close)
  admitted  basis.established_after Agents not already established
  draw      each eligible Agent's place in sha256('intake:' + address + ':' + close) order (comment 6193). The first cap of them
            should be exactly the admitted set; Check says Match when they are, Differs when not.
Finalized close records only: no pending row, seal or score is read."""
import collections, hashlib, math
from . import analytics as A, segments as SG, scoresort as SS, estfold as EF, closepause as CPZ
from .ui import E, card, stat, intc, agent, qtip

METHOD = "/about#intake"
PAGE = 100   # Agents per page in the selected close
FLOOR, RATE = 5, 0.10
DEFAULT_BASIS = "engine: max(5, ceil(10% of the set))"
PARAM_BASIS = "params: estab_intake_floor, estab_intake_rate"
SRC = dict(post=1582, comment=6193, url="https://minepoa.com/lableak/#/post/1582")
STATES = [("admitted", "Admitted"), ("not_admitted", "Eligible, not admitted"), ("admitted_unlisted", "Admitted, not eligible")]

def _key(a, n): return hashlib.sha256(f"intake:{a}:{n}".encode()).hexdigest()

def cap_of(size, floor=FLOOR, rate=RATE): return max(int(floor), math.ceil(float(rate) * int(size) - 1e-9))

def _param_rule(p):
    """(floor, rate, from_epoch) when /api/params carries Proposal L's intake params, else None."""
    try:
        f, r = p.get("estab_intake_floor"), p.get("estab_intake_rate")
        if f is None and r is None: return None
        fe = p.get("estab_intake_from_epoch")
        return (int(f if f is not None else FLOOR), float(r if r is not None else RATE), int(fe) if fe is not None else None)
    except (TypeError, ValueError): return None

def _cap(n, size, order, adm, rule):
    """(cap, basis, draw_match) for one close. With intake params: from their from_epoch on, or, without one, whichever rule
    the draw confirms (params first)."""
    dflt = cap_of(size); m = lambda c: set(order[:c]) == adm
    if rule is None: return dflt, DEFAULT_BASIS, m(dflt)
    pc = cap_of(size, rule[0], rule[1])
    if rule[2] is not None: return (pc, PARAM_BASIS, m(pc)) if n >= rule[2] else (dflt, DEFAULT_BASIS, m(dflt))
    if m(pc): return pc, PARAM_BASIS, True
    if m(dflt): return dflt, DEFAULT_BASIS, True
    return pc, PARAM_BASIS, False

# 1.26.205: the door tracker. Proposal L's params, when /api/params first carries any of them (POAScan's hourly conditional
# read of /api/params, no extra request), are noted once with the time first seen; estab_ttl changes are noted the same way.
PROPL_KEYS = ("estab_intake_floor", "estab_intake_rate", "estab_intake_from_epoch")
PROPL_BLOB = "propl_seen"

def note_params(p, now=None):
    """Called after each stored /api/params copy. Keeps {keys: {k: {value, first_seen}}, estab_ttl: [{value, seen}]}."""
    import time as _t
    from . import db
    if not isinstance(p, dict): return
    now = int(now or _t.time()); d = db.get_blob(PROPL_BLOB)[0] or {}; ks = dict(d.get("keys") or {}); ch = False
    for k in PROPL_KEYS:
        if k in p and (k not in ks or ks[k].get("value") != p[k]):
            ks[k] = dict(value=p[k], first_seen=ks.get(k, {}).get("first_seen") or now, changed=now); ch = True
    tl = list(d.get("estab_ttl") or []); v = p.get("estab_ttl")
    if v is not None and (not tl or tl[-1].get("value") != v): tl.append(dict(value=v, seen=now)); ch = True
    if ch or not d: db.put_blob(PROPL_BLOB, dict(keys=ks, estab_ttl=tl[-20:], checked=now))

def propl_state():
    """{present, keys, first_seen, estab_ttl, checked} for the flag. present: any Proposal L key in the newest params copy."""
    from . import db
    d = db.get_blob(PROPL_BLOB)[0] or {}; p = A.params() if not SG.archived() else {}
    cur = {k: p[k] for k in PROPL_KEYS if k in p}
    seen = [v.get("first_seen") for k, v in (d.get("keys") or {}).items() if k in cur and v.get("first_seen")]
    tl = d.get("estab_ttl") or []
    return dict(present=bool(cur), keys=cur, first_seen=min(seen) if seen else None, estab_ttl=p.get("estab_ttl"),
                estab_ttl_changes=tl[1:] if len(tl) > 1 else [], watched=list(PROPL_KEYS), params_read_every_s=3600)

@A.cached("intake", 300)
def closes():
    """One dict per close of the selected segment, oldest first; each carries its Agent rows (rows)."""
    seg = SG.selected(); eps = sorted(A.segment_closes(seg), key=lambda e: int(e.get("epoch", 0)))
    p = A.params() if not SG.archived(seg) else {}
    pardons = A.params().get("slash_pardons"); rule = _param_rule(p)
    est = set(EF.imported(seg)); out = []
    for e in eps:
        n = int(e.get("epoch", 0)); b = e.get("basis") or {}; size = len(est); sl = set(b.get("slashed") or [])
        elig = [a for a in dict.fromkeys(b.get("challenge_eligible") or []) if isinstance(a, str) and a not in est]
        adm_l = [a for a in dict.fromkeys(b.get("established_after") or []) if isinstance(a, str) and a not in est]
        adm = set(adm_l); order = sorted(elig, key=lambda a: _key(a, n)); rank = {a: i + 1 for i, a in enumerate(order)}
        cap, basis, ok = _cap(n, size, order, adm, rule)
        rows = [dict(address=a, state="admitted" if a in adm else "not_admitted", draw=rank[a]) for a in order]
        rows += [dict(address=a, state="admitted_unlisted", draw=None) for a in adm_l if a not in rank]
        na = sum(1 for r in rows if r["state"] == "not_admitted")
        rem = [a for a in dict.fromkeys(b.get("established_removed") or []) if isinstance(a, str) and not EF._pardoned(pardons, n, a, sl)]
        audit = sl | set(b.get("ejected") or []) | set((b.get("audit") or {}).get("slashed") or [])
        r_ttl = sum(1 for a in rem if a not in audit)
        out.append(dict(close=n, close_ts=int(e.get("ts") or 0), established_before=size, eligible=len(elig), cap=cap, cap_basis=basis,
                        admitted=len(adm), not_admitted=na, door="binding" if len(elig) > cap else "open",
                        admit_rate=round(len(adm) / len(elig), 4) if elig else None, removed=len(rem), removed_ttl=r_ttl, removed_other=len(rem) - r_ttl,
                        net=len(adm) - len(rem),
                        check=("n/a" if not elig and not adm else "match" if ok else "differs"), **CPZ.fields_for(e), rows=rows))
        est.update(b.get("established_after") or [])
        est.difference_update(a for a in b.get("established_removed") or [] if not EF._pardoned(pardons, n, a, sl))
    return out

COLS = [SS.Col("close", "Close", "num"), SS.Col("set", "Set", "num", "r dk"), SS.Col("eligible", "Eligible", "num", "r"), SS.Col("cap", "Cap", "num", "r"),
        SS.Col("admitted", "Admitted", "num", "r"), SS.Col("not_admitted", "Not admitted", "num", "r"), SS.Col("rate", "Rate", "num", "r dk"),
        SS.Col("removed_ttl", "TTL out", "num", "r"), SS.Col("removed_other", "Other out", "num", "r dk"), SS.Col("net", "Net", "num", "r"),
        SS.Col("door", "Door", "cat", "r dk"), SS.Col("check", "Check", "cat", "r dk")]
SORTS = [(c.key, c.label) for c in COLS]
_DOOR = {"binding": 0, "open": 1}; _CHK = {"differs": 0, "match": 1, "n/a": 2}
_V = {"close": lambda r: r["close"], "set": lambda r: r["established_before"], "eligible": lambda r: r["eligible"], "cap": lambda r: r["cap"],
      "admitted": lambda r: r["admitted"], "not_admitted": lambda r: r["not_admitted"], "rate": lambda r: r["admit_rate"] if r["admit_rate"] is not None else -1,
      "removed_ttl": lambda r: r["removed_ttl"], "removed_other": lambda r: r["removed_other"], "net": lambda r: r["net"], "door": lambda r: _DOOR[r["door"]], "check": lambda r: _CHK[r["check"]]}
ACOLS = [SS.Col("name", "Agent", "text"), SS.Col("draw", "Draw", "low", "r"), SS.Col("state", "State", "cat")]
ASORTS = [(c.key, c.label) for c in ACOLS]
_SO = {k: i for i, (k, _) in enumerate(STATES)}
TIP = ("Set: established before the close. Eligible: challenge_eligible, not yet established. Cap: max(5, ceil(10% of Set)). "
       "Admitted: new in established_after. Rate: Admitted over Eligible. TTL out: in established_removed and not slashed or ejected at that close (the TTL lapse). Other out: removed with a slash or ejection. Net: Admitted minus removed. Door: Binding when Eligible exceeds Cap. Check: the first Cap Agents in the draw order are exactly the Admitted.")
DRAW_TIP = "Place in sha256('intake:' + address + ':' + close) order among the eligible. The first Cap places are admitted."

def select(by="close", d="desc"):
    return SS.sort_rows([{k: v for k, v in r.items() if k != "rows"} for r in closes()], _V.get(by, _V["close"]), SS.kind_of(COLS, by), d, tie=lambda r: -r["close"])

def agents(close, state="", by="draw", d="desc"):
    r = next((x for x in closes() if x["close"] == close), None)
    if r is None: return None
    nm = A.forum_names()
    rows = [dict(x, name=nm.get(x["address"]), profile=("https://minepoa.com/lableak/#/u/" + x["address"]) if nm.get(x["address"]) else None)
            for x in r["rows"] if not state or x["state"] == state]
    val = {"name": lambda x: SS.text_key(x["name"] or x["address"]), "state": lambda x: _SO[x["state"]], "draw": lambda x: x["draw"]}
    return SS.sort_rows(rows, val.get(by, val["draw"]), SS.kind_of(ACOLS, by), d, tie=lambda x: (x["draw"] or 1 << 30, x["address"]))

def _n(v): return f'<span class="num">{v:,}</span>' if v is not None else '<span class="dim">···</span>'
def _q(qs, k, d=""): return ((qs or {}).get(k) or [d])[0]
def _state(s):
    return {"admitted": '<span class="tag ok">Admitted</span>', "not_admitted": '<span class="tag warn">Eligible, not admitted</span>',
            "admitted_unlisted": '<span class="tag" title="In established_after without a challenge_eligible entry at this close">Admitted, not eligible</span>'}[s]
def _pct(v): return f'{v * 100:.0f}%' if v is not None else '<span class="dim">···</span>'
def _net(v): return f'<span class="num">{"+" if v > 0 else ""}{v:,}</span>'
def _propl_flag():
    """Proposal L flag: Not in params, or the keys and when POAScan first saw them."""
    st = propl_state()
    if not st["present"]:
        return stat("Proposal L params", "Not set", tip="None of estab_intake_floor, estab_intake_rate, estab_intake_from_epoch in /api/params (read hourly). The door uses the engine default.")
    from .ui import lt
    kv = ", ".join(f"{k} {v}" for k, v in st["keys"].items())
    return stat("Proposal L params", "Set", tip=f"In /api/params: {kv}. First seen by POAScan's hourly read" + (f" at {__import__('time').strftime('%Y-%m-%d %H:%M UTC', __import__('time').gmtime(st['first_seen']))}" if st["first_seen"] else ""),
                flag_html=f'<span class="tag ok">Set</span>')

def _chk(c): return {"match": '<span class="tag ok">Match</span>', "differs": '<span class="tag bad">Differs</span>', "n/a": '<span class="dim">···</span>'}[c]

def tab(qs, href, qsx):
    allc = closes()
    if not allc: return card("Intake", '<p class="na">No close record in this segment yet.</p>')
    by = SS.page_sort(qs, dict(SORTS), "close"); d = SS.page_dir(qs)
    rs = select(by, d)
    sel = _q(qs, "close"); withe = [c for c in allc if c["eligible"] or c["admitted"]]
    one = next((c for c in allc if str(c["close"]) == sel), None) or (withe[-1] if withe else allc[-1])
    st = _q(qs, "state"); st = st if st in dict(STATES) else ""
    keep = lambda **o: dict(dict(sort=by if by != "close" else "", dir="asc" if d == "asc" else "", close=str(one["close"]) if sel else "", state=st), **o)
    link = lambda k, dd: href("intake", **keep(sort=k if k != "close" else "", dir="asc" if dd == "asc" else "")) + "#intake"
    last = withe[-1] if withe else allc[-1]
    s = "".join([stat("Eligible", intc(last["eligible"]), tip=f'challenge_eligible at the E{last["close"]} close, not yet established'),
                 stat("Cap", intc(last["cap"]), tip=f'Door at E{last["close"]}: max(5, ceil(10% of {last["established_before"]:,} established))'),
                 stat("Admitted", intc(last["admitted"]), tip=f'New in established_after at E{last["close"]}'),
                 stat("Not admitted", intc(last["not_admitted"]), tip=f'Eligible at E{last["close"]} but not admitted'),
                 stat("TTL out", intc(last["removed_ttl"]), tip=f'Removed from Established at E{last["close"]} with no slash or ejection'),
                 _propl_flag()])
    T = lambda: qtip(TIP, METHOD, "About Intake", "hv")
    cols = [c._replace(tip=T()) if c.key == "cap" else c for c in COLS]
    trs = "".join(f'<tr{" class=on" if r["close"] == one["close"] else ""}><td><a href="{href("intake", **keep(close=str(r["close"]), state=""))}#intake-list">E{r["close"]}</a>{CPZ.tag(r.get("pause"))}</td>'
                  f'<td class="r dk">{_n(r["established_before"])}</td><td class="r">{_n(r["eligible"])}</td><td class="r">{_n(r["cap"])}</td><td class="r">{_n(r["admitted"])}</td>'
                  f'<td class="r">{_n(r["not_admitted"])}</td><td class="r dk">{_pct(r["admit_rate"])}</td><td class="r">{_n(r["removed_ttl"])}</td><td class="r dk">{_n(r["removed_other"])}</td>'
                  f'<td class="r">{_net(r["net"])}</td><td class="r dk">{"Binding" if r["door"] == "binding" else "<span class=dim>Open</span>"}</td><td class="r dk">{_chk(r["check"])}</td></tr>' for r in rs)
    tb = SS.select(cols, by, d, link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(cols, by, d, link)}</tr></thead><tbody>{trs}</tbody></table></div>'
    q = qsx(sort=by if by != "close" else "", dir="asc" if d == "asc" else "")
    links = f'<a class="more" href="/api/v1/governance/intake.csv{q}" download>CSV →</a><a class="more" href="/api/v1/governance/intake{q}">API →</a>'
    cov = (f'<p class="cov dim small">From the close records, replaying the engine one close at a time. Cap and draw order: '
           f'<a href="{SRC["url"]}" target="_blank" rel="noopener noreferrer">LabLeak post {SRC["post"]}</a> and comment {SRC["comment"]}. <a href="{METHOD}">Method</a></p>')
    # the selected close's Agents
    aby = _q(qs, "asort"); aby = aby if aby in dict(ASORTS) else "draw"; ad = _q(qs, "adir"); ad = ad if ad in ("desc", "asc") else "desc"
    ak = lambda **o: dict(dict(sort=by if by != "close" else "", dir="asc" if d == "asc" else "", close=str(one["close"]), state=st,
                               asort=aby if aby != "draw" else "", adir="asc" if ad == "asc" else ""), **o)
    alink = lambda k, dd: href("intake", **ak(asort=k if k != "draw" else "", adir="asc" if dd == "asc" else "")) + "#intake-list"
    ar = agents(one["close"], st, aby, ad) or []
    try: pg = max(1, int(_q(qs, "apage", "1")))
    except ValueError: pg = 1
    pages = max(1, -(-len(ar) // PAGE)); pg = min(pg, pages); cur = ar[(pg - 1) * PAGE: pg * PAGE]
    cnt = collections.Counter(r["state"] for r in one["rows"])
    chips = (f'<a href="{href("intake", **ak(state=""))}#intake-list" class="chip {"on" if not st else ""}">All <small>{len(one["rows"]):,}</small></a>'
             + "".join(f'<a href="{href("intake", **ak(state=k))}#intake-list" class="chip {"on" if k == st else ""}">{t} <small>{cnt[k]:,}</small></a>' for k, t in STATES if cnt[k] or k == st))
    acols = [c._replace(tip=qtip(DRAW_TIP, METHOD, "About Draw", "hv")) if c.key == "draw" else c for c in ACOLS]
    atr = "".join(f'<tr><td>{agent(r["address"], r["name"] or "")}</td><td class="r">{_n(r["draw"])}</td><td>{_state(r["state"])}</td></tr>' for r in cur)
    atb = (SS.select(acols, aby, ad, alink) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(acols, aby, ad, alink)}</tr></thead>'
           f'<tbody>{atr or "<tr><td colspan=3 class=na>No Agents in this view.</td></tr>"}</tbody></table></div>')
    if pages > 1:
        pl = lambda n: href("intake", **ak(apage=str(n) if n > 1 else "")) + "#intake-list"
        atb += ('<div class="chips">' + (f'<a class="chip" href="{pl(pg - 1)}">Previous</a>' if pg > 1 else "")
                + f'<span class="dim small">Page {pg} of {pages}</span>' + (f'<a class="chip" href="{pl(pg + 1)}">More</a>' if pg < pages else "") + "</div>")
    aq = qsx(close=str(one["close"]), state=st)
    alinks = f'<a class="more" href="/api/v1/governance/intake.csv{aq}" download>CSV →</a><a class="more" href="/api/v1/governance/intake{aq}">API →</a>'
    ccl = "".join(f'<a href="{href("intake", **ak(close=str(c["close"]), state=""))}#intake-list" class="chip {"on" if c["close"] == one["close"] else ""}">E{c["close"]}</a>' for c in reversed(withe))
    det = card(f'E{one["close"]} intake · {one["admitted"]:,} of {one["eligible"]:,}, cap {one["cap"]:,}',
               (f'<div class="chips scroll">{ccl}</div>' if ccl else "") + f'<div class="chips">{chips}</div>' + atb, alinks, cls="histc", id="intake-list")
    return f'<div class="stats six">{s}</div>' + card(f"Intake per close · {len(rs):,}", tb + cov, links, cls="histc", id="intake") + det

BASE = "https://poascan.io"
def api(close=None, state="", sort="close", d="desc", asort="draw", adir="desc", limit=1000, offset=0):
    seg = dict(segment=SG.selected(), archived=SG.archived())
    common = dict(seg, source="close records (challenge_eligible, established_after, established_removed; minepoa's engine fold)", definitions=TIP,
                  rule="cap = max(floor, ceil(rate x established before the close)), floor 5 and rate 0.10 unless /api/params sets estab_intake_floor and estab_intake_rate; "
                       "admitted = the first cap eligible Agents in sha256('intake:' + address + ':' + close) order",
                  sources=[dict(SRC, note="Proposal L: the hardcoded door and the params that would replace it"), dict(post=1582, comment=6193, note="the ceil and the sha256 draw order")],
                  method=BASE + METHOD, url=BASE + "/governance?tab=intake")
    if close is None:
        rs = select(sort, d)
        return dict(common, close=None, sort=sort, dir=d, proposal_l=propl_state(), total=len(rs), offset=offset, limit=limit, rows=rs[offset:offset + limit])
    c = next((x for x in closes() if x["close"] == close), None)
    if c is None: return dict(common, close=close, found=False, total=0, rows=[])
    ar = agents(close, state, asort, adir)
    return dict(common, close=close, found=True, state=state or None, summary={k: v for k, v in c.items() if k != "rows"}, sort=asort, dir=adir,
                total=len(ar), offset=offset, limit=limit, rows=ar[offset:offset + limit])
