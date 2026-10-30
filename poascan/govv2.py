"""Governance v2 (preview/gov-v2): settlement by origin epoch per close, standing changes per close, Agents never
established, and panel size plus age on the settle queue. Public data only, from close records POAScan already archives,
minepoa's grading list copy and the agent list. No new upstream reads.

Never shown: a pending grade's score or a seal's content. Pending rows are counted (panel size from the last close record's
public panel list, seals from the grading list's plain counts); the scores some close records carry on pending grades are
never read here."""
import collections
from . import db, analytics as A, segments as SG, scoresort as SS, estfold as EF, closepause as CPZ, outcome as OC
from .ui import E, card, stat, intc, agent, bars, lt, qtip

METHOD = "/about#gov-v2"

# ---------------------------------------------------------------- (a) panel size and age for the settle queue
@A.cached("govv2_panels", 120)
def panels():
    """{answer id: panel size} from the current segment's last close record (basis.pending[id].panel is a public list of
    grader addresses; only its length is used), and that close's epoch."""
    with SG.use(SG.CURRENT): eps = A.epochs_raw()
    if not eps: return {}, None
    last = max(eps, key=lambda e: int(e.get("epoch", 0)))
    pend = A.pending_of(last) or {}
    return {k: len(v.get("panel") or []) for k, v in pend.items() if isinstance(v, dict)}, int(last.get("epoch", 0))

@A.cached("govv2_seal_times", 120)
def seal_times():
    """{answer id: sorted seal times} from the current segment's last close record: the ts of each grader's first entry in
    basis.pending[id].grades (one per distinct grader). Only grader and ts are read; a grade's score is never touched."""
    with SG.use(SG.CURRENT): eps = A.epochs_raw()
    if not eps: return {}
    last = max(eps, key=lambda e: int(e.get("epoch", 0)))
    out = {}
    for k, v in (A.pending_of(last) or {}).items():
        if not isinstance(v, dict) or not isinstance(v.get("grades"), list): continue
        first = {}
        for g in v["grades"]:
            if not isinstance(g, dict): continue
            t = g.get("ts"); who = g.get("grader")
            if not isinstance(t, (int, float)) or t <= 0: continue
            if who not in first or t < first[who]: first[who] = int(t)
        out[k] = sorted(first.values())
    return out

def add_panel_age(rows, open_epoch):
    """Adds panel (size at the last close, None when the answer was not pending then), age (epochs since its origin) and,
    from the same close record, sealed_ts (its first seal), graded_ts (its latest) and seal_times (every distinct grader's
    seal time, ascending). Timestamps only; None when the record has none."""
    pm, _ = panels(); st = seal_times()
    for r in rows:
        if "panel" in r: continue
        r["panel"] = None if r.get("open") else pm.get(r.get("id"))
        o = r.get("since") if r.get("since") is not None else r.get("born")
        r["age"] = (int(open_epoch) - int(o)) if open_epoch is not None and o is not None else None
        ts = [] if r.get("open") else st.get(r.get("id")) or []
        r["seal_times"] = list(ts); r["sealed_ts"] = ts[0] if ts else None; r["graded_ts"] = ts[-1] if ts else None
    return rows

# ---------------------------------------------------------------- (e) settlement by origin epoch, per close
def _origin(aid, prev, tx_ep):
    if aid in prev: return A.since_of(aid, prev[aid])
    return tx_ep.get(aid)

@A.cached("govv2_settlement", 300)
def settlement():
    """One row per (close, origin epoch) in the selected segment: settled rows of that close (basis.settled), how many had a
    jury seat (sealed), passed, and paid (passed and the author got a challenge payout at that close), beside the rows
    still open at that close (basis.pending) and how many of those had a panel. Origin: the answer's since in the previous
    close's pending list, else its archived tx epoch, else unknown (-1)."""
    eps = sorted(A.segment_closes(SG.selected()), key=lambda e: int(e.get("epoch", 0)))
    ids = [s.get("answer") for e in eps for s in ((e.get("basis") or {}).get("settled") or []) if s.get("answer")]
    tx_ep = {}
    for i in range(0, len(ids), 500):
        ch = ids[i:i + 500]
        for r in db.q(f"SELECT id, epoch FROM txs WHERE id IN ({','.join('?' * len(ch))})", tuple(ch)):
            if r["epoch"] is not None: tx_ep[r["id"]] = int(r["epoch"])
    out = []; sp = _settle_pend()
    for i, e in enumerate(eps):
        n = int(e.get("epoch", 0)); b = e.get("basis") or {}; ts = int(e.get("ts") or 0); pin, opens = sp[i]
        paid_to = {a for a, v in (e.get("challenges") or {}).items() if _pos(v)}
        g = collections.defaultdict(lambda: dict(settled=0, sealed=0, passed=0, expired_no_jury=0, paid=0, open=0, open_panel=0))
        for s in b.get("settled") or []:
            o = pin[s.get("answer")] if s.get("answer") in pin else tx_ep.get(s.get("answer")); o = -1 if o is None else o; x = g[o]
            x["settled"] += 1; x["sealed"] += 1 if s.get("jury") else 0; x["expired_no_jury"] += 1 if OC.no_jury(s) else 0
            if s.get("passed"): x["passed"] += 1; x["paid"] += 1 if s.get("from") in paid_to else 0
        for o, (k, kp) in opens.items(): x = g[o]; x["open"] += k; x["open_panel"] += kp
        for o in sorted(g):
            out.append(_split(dict(close=n, close_ts=ts, origin=None if o == -1 else o, **g[o])))
    return out

@A.close_memo("govv2_settle_pend")
def _settle_pend():
    """settlement's reads of basis.pending, per close (1.26.235: once per close): the origin of each settled answer found in
    the previous close's pending list, and {origin: [open, open with a panel]}."""
    eps = sorted(A.segment_closes(SG.selected()), key=lambda e: int(e.get("epoch", 0)))
    out, prev = [], {}
    for e in eps:
        b = e.get("basis") or {}
        pin = {s.get("answer"): A.since_of(s.get("answer"), prev[s.get("answer")]) for s in b.get("settled") or [] if s.get("answer") in prev}
        pend = A.pending_of(e) or {}; opens = {}
        for aid, v in pend.items():
            if not isinstance(v, dict): continue
            x = opens.setdefault(A.since_of(aid, v), [0, 0]); x[0] += 1; x[1] += 1 if v.get("panel") else 0
        out.append((pin, opens))
        prev = pend if isinstance(pend, dict) else {}
    return out

def _split(x):
    """1.26.225: failed is jury failures only; not_paid is juried and not paid (the red chart segment). Expiries sit apart."""
    x["failed"] = x["settled"] - x["passed"] - x["expired_no_jury"]; x["not_paid"] = x["settled"] - x["paid"] - x["expired_no_jury"]
    return x

def _pos(v):
    try: return float(v) > 0
    except (TypeError, ValueError): return False

def settlement_closes(rows=None):
    """Per close totals (the chart and the close chips)."""
    t = collections.OrderedDict(); pz = CPZ.by_epoch()   # 1.26.192: paused when the close record flags a halt (closepause.py)
    for r in rows if rows is not None else settlement():
        x = t.setdefault(r["close"], dict(close=r["close"], close_ts=r["close_ts"], settled=0, sealed=0, passed=0, expired_no_jury=0, paid=0, open=0, open_panel=0,
                                          paused=r["close"] in pz, pause=pz.get(r["close"])))
        for k in ("settled", "sealed", "passed", "expired_no_jury", "paid", "open", "open_panel"): x[k] += r[k]
    return [_split(x) for x in t.values()]

SET_COLS = [SS.Col("close", "Close", "num"), SS.Col("origin", "Origin", "num", "r"), SS.Col("settled", "Settled", "num", "r"),
            SS.Col("sealed", "Sealed", "num", "r dk"), SS.Col("expired_no_jury", "Expired", "num", "r dk", " " + qtip("Expired, no jury: settled with no jurors. Not a failure.", "/about#expired", "About Expired", "hv")), SS.Col("paid", "Paid", "num", "r"), SS.Col("open", "Open", "num", "r"),
            SS.Col("open_panel", "Panel", "num", "r dk")]
SET_SORTS = [(c.key, c.label) for c in SET_COLS]
SET_TIP = ("Settled: rows the close settled, by the epoch the answer was born. Sealed: settled with at least one jury seat. "
           "Expired: settled with no jury, never failed. Paid: passed, and the author got a challenge payout at that close. Not paid: juried, not paid. Open: still pending at that close. Panel: open rows with a panel.")

def settlement_select(close=None, by="close", d="desc"):
    rows = [r for r in settlement() if close is None or r["close"] == close]
    tie = lambda r: (-r["close"], r["origin"] if r["origin"] is not None else 1 << 30)
    return SS.sort_rows(rows, lambda r: r[by], "num", d, tie=tie)

# ---------------------------------------------------------------- (d) standing changes per close
@A.cached("govv2_changes", 300)
def standing_changes():
    """Per close of the selected segment, minepoa's engine fold (estfold.fold) one close at a time: established before,
    added (established_after not already established), relisted (already established), removed (established_removed,
    pardons honoured), after, net. Address lists are public close record fields."""
    seg = SG.selected(); eps = sorted(A.segment_closes(seg), key=lambda e: int(e.get("epoch", 0)))
    pardons = A.params().get("slash_pardons"); est = set(EF.imported(seg)); out = []
    for e in eps:
        n = int(e.get("epoch", 0)); b = e.get("basis") or {}; before = len(est); sl = set(b.get("slashed") or [])
        add = [a for a in b.get("established_after") or [] if a not in est]; rel = [a for a in b.get("established_after") or [] if a in est]
        est.update(add)
        rem = [a for a in b.get("established_removed") or [] if a in est and not EF._pardoned(pardons, n, a, sl)]
        est.difference_update(rem)
        out.append(dict(close=n, close_ts=int(e.get("ts") or 0), before=before, added=len(add), relisted=len(rel), removed=len(rem),
                        after=len(est), net=len(est) - before, **CPZ.fields_for(e), added_list=sorted(add), removed_list=sorted(rem)))
    return out

CHG_COLS = [SS.Col("close", "Close", "num"), SS.Col("before", "Before", "num", "r dk"), SS.Col("added", "Added", "num", "r"),
            SS.Col("removed", "Removed", "num", "r"), SS.Col("net", "Net", "num", "r"), SS.Col("after", "After", "num", "r")]
CHG_SORTS = [(c.key, c.label) for c in CHG_COLS]

# ---------------------------------------------------------------- (c) Agents never established
def ever_established():
    """Every address established at any time in any segment POAScan holds (genesis imports, established_after), plus
    minepoa's current established list from the grading copy."""
    s = set()
    for sg in SG.SEGMENTS:
        n = sg.get("n") if isinstance(sg, dict) else None
        if n is None: continue
        s |= set(EF.imported(n))
        for e in A.segment_closes(n): s |= set((e.get("basis") or {}).get("established_after") or [])
    try:
        from . import grading as GR
        d = GR.current() or {}
        s |= {x if isinstance(x, str) else (x or {}).get("address") or (x or {}).get("addr") for x in d.get("established") or []}
    except Exception: pass
    s.discard(None)
    return s

@A.cached("govv2_never", 300)
def never_established():
    """Agents in the live agent list who were never established: joined, answers and last tx in the current segment's
    archive, closes paid in this segment, balance."""
    ever = ever_established(); nm = A.forum_names(); first = first_joins(); closes = {}
    accts = db.q("SELECT addr, balance, api_ts, api_joined_epoch, first_seen FROM accounts")
    ans = {r["a"]: r["n"] for r in db.q("SELECT from_addr AS a, COUNT(*) AS n FROM txs WHERE type='challenge' AND segment=? GROUP BY from_addr", (SG.CURRENT,))}
    last = {r["a"]: r["t"] for r in db.q("SELECT from_addr AS a, MAX(ts) AS t FROM txs WHERE segment=? AND from_addr IS NOT NULL GROUP BY from_addr", (SG.CURRENT,))}
    paid = collections.Counter()
    for e in A.segment_closes(SG.CURRENT):
        for a, v in (e.get("rewards") or {}).items():
            if _pos(v): paid[a] += 1
    out = []
    for r in accts:
        a = r["addr"]
        if not a or not a.startswith("poa1") or a in ever: continue
        jt, je, js = joined_of(r, first, closes)
        out.append(dict(address=a, name=nm.get(a), joined_epoch=je, joined_segment=js, joined_ts=jt,
                        answers=ans.get(a, 0), closes_paid=paid.get(a, 0), last_ts=last.get(a), balance=float(r["balance"] or 0)))
    return out

def first_joins():
    """address -> (ts, epoch, segment) of its first archived join tx, in any segment."""
    out = {}
    for r in db.q("SELECT from_addr AS a, ts AS t, epoch AS e, segment AS s FROM txs WHERE type='join' AND from_addr IS NOT NULL AND ts > 0 ORDER BY ts DESC"):
        out[r["a"]] = (int(r["t"]), r["e"], r["s"])
    return out

def epoch_at(t, closes=None):
    """(segment, epoch) open at UTC time t, from the configured segment boundaries (segments.of_ts) and that segment's
    close records: epoch k is open after close k-1 up to close k; before the first close it is the first record's epoch;
    after the last close, the last close + 1. Epoch None when the segment has no close records."""
    if not t: return None, None
    n = SG.of_ts(t)
    cl = (closes or {}).get(n) if closes is not None else None
    if cl is None:
        cl = sorted((ct, int(e["epoch"])) for e in A.segment_closes(n) for ct in [_ts(e.get("ts"))] if ct and isinstance(e.get("epoch"), (int, float)))
        if closes is not None: closes[n] = cl
    if not cl: return n, None
    k = None
    for ct, ep in cl:
        if ct <= t: k = ep + 1
        else: break
    return n, (k if k is not None else cl[0][1])

def joined_of(acc, first, closes=None):
    """(ts, epoch, segment) an Agent joined: minepoa's agent list fields, unless our own first join tx is earlier
    (1.26.166: minepoa's joined fields restart for some carried or re-registered Agents). 1.26.168: the segment always
    comes from the join time (config boundaries), never from the source; a missing epoch is worked out from the time."""
    mt = _ts(acc["api_ts"]) or acc["first_seen"]; me = acc["api_joined_epoch"]
    f = first.get(acc["addr"])
    if f and (mt is None or f[0] < mt): t, ep, seg = f[0], f[1], f[2]
    else: t, ep, seg = mt, me, None
    if not t: return t, ep, seg if seg is not None else SG.CURRENT
    dseg, dep = epoch_at(t, closes)
    seg = SG.of_ts(t) if seg is None else seg
    if ep is None and seg == dseg: ep = dep
    return t, ep, seg

def _ts(v):
    if v is None: return None
    try: return int(float(v)) if float(v) < 1e11 else int(float(v) / 1000)
    except (TypeError, ValueError):
        import datetime as dt
        try: return int(dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
        except ValueError: return None

NEV_COLS = [SS.Col("name", "Agent", "text"), SS.Col("joined", "Joined", "num", "r"), SS.Col("answers", "Answers", "num", "r"),
            SS.Col("paid", "Paid closes", "num", "r dk"), SS.Col("last", "Last tx", "num", "r dk"), SS.Col("balance", "Balance", "num", "r")]
NEV_SORTS = [(c.key, c.label) for c in NEV_COLS]
_NV = {"name": lambda r: SS.text_key(r["name"] or r["address"]), "joined": lambda r: r["joined_ts"], "answers": lambda r: r["answers"],
       "paid": lambda r: r["closes_paid"], "last": lambda r: r["last_ts"], "balance": lambda r: r["balance"]}

def never_select(by="joined", d="desc"):
    kind = "text" if by == "name" else "num"
    return SS.sort_rows(never_established(), _NV.get(by, _NV["joined"]), kind, d, tie=lambda r: r["address"])

# ---------------------------------------------------------------- pages (Governance tabs)
PAGE = 100

def _n(v): return f'<span class="num">{v:,}</span>' if v is not None else '<span class="dim">···</span>'
def _q(qs, k, dflt=""): return ((qs or {}).get(k) or [dflt])[0]
def _pg(qs, total):
    try: pg = max(1, int(_q(qs, "page", "1")))
    except ValueError: pg = 1
    pages = max(1, -(-total // PAGE)); return min(pg, pages), pages

def _nav(pg, pages, url):
    if pages < 2: return ""
    return ('<div class="chips">' + (f'<a class="chip" href="{url(pg - 1)}">Previous</a>' if pg > 1 else "")
            + f'<span class="dim small">Page {pg} of {pages}</span>' + (f'<a class="chip" href="{url(pg + 1)}">More</a>' if pg < pages else "") + "</div>")

def settlement_tab(qs, href, qsx):
    rows = settlement(); closes = settlement_closes(rows)
    if not closes: return card("Settlement", '<p class="na">No close record in this segment yet.</p>')
    cl = _q(qs, "close"); cl = int(cl) if cl.isdigit() and any(c["close"] == int(cl) for c in closes) else None
    by = SS.page_sort(qs, dict(SET_SORTS), "close"); d = SS.page_dir(qs)
    rs = settlement_select(cl, by, d)
    keep = lambda **o: dict(dict(sort=by if by != "close" else "", dir="asc" if d == "asc" else "", close=str(cl) if cl is not None else ""), **o)
    link = lambda k, dd: href("settlement", **keep(sort=k if k != "close" else "", dir="asc" if dd == "asc" else "")) + "#settlement"
    chips = (f'<a href="{href("settlement", **keep(close=""))}#settlement" class="chip {"on" if cl is None else ""}">All</a>'
             + "".join(f'<a href="{href("settlement", **keep(close=str(c["close"])))}#settlement" class="chip {"on" if c["close"] == cl else ""}">E{c["close"]}</a>' for c in reversed(closes)))
    last = closes[-1]
    s = "".join([stat("Settled", intc(last["settled"]), tip=f'At the E{last["close"]} close'), stat("Paid", intc(last["paid"]), tip="Passed, and the author got a challenge payout at that close"),
                 stat("Open", intc(last["open"]), tip=f'Still pending at the E{last["close"]} close'), stat("Panel", intc(last["open_panel"]), tip="Open rows with a panel at that close")])
    ch = bars([(f'E{c["close"]}', [c["paid"], c["not_paid"], c["expired_no_jury"]]) for c in closes], height=150, colors=("verd", "ember", "mute"), fmt=lambda z: f"{z:,.0f}",
              legend=["Paid", "Settled, not paid", "Expired, no jury"])
    org = [r for r in rows if r["close"] == (cl if cl is not None else last["close"])]
    ch2 = bars([(f'E{r["origin"]}' if r["origin"] is not None else "?", [r["settled"], r["open"]]) for r in org], height=150, colors=("gold", "steel"), fmt=lambda z: f"{z:,.0f}",
               legend=["Settled", "Open"], stacked=False)
    trs = "".join(f'<tr><td><a href="/epoch/{r["close"]}{SG.qs()}">E{r["close"]}</a>{CPZ.tag_for(r["close"])}</td><td class="r">{"E" + str(r["origin"]) if r["origin"] is not None else "<span class=dim>···</span>"}</td>'
                  f'<td class="r">{_n(r["settled"])}</td><td class="r dk">{_n(r["sealed"])}</td><td class="r dk">{_n(r["expired_no_jury"])}</td><td class="r">{_n(r["paid"])}</td><td class="r">{_n(r["open"])}</td><td class="r dk">{_n(r["open_panel"])}</td></tr>' for r in rs)
    tb = (SS.select(SET_COLS, by, d, link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(SET_COLS, by, d, link)}</tr></thead><tbody>{trs}</tbody></table></div>')
    q = qsx(sort=by if by != "close" else "", dir="asc" if d == "asc" else "", close=str(cl) if cl is not None else "")
    links = f'<a class="more" href="/api/v1/governance/settlement.csv{q}" download>CSV →</a><a class="more" href="/api/v1/governance/settlement{q}">API →</a>'
    cov = f'<p class="cov dim small">{E(SET_TIP)} From the close records. <a href="{METHOD}">Method</a></p>'
    sub = f'E{cl if cl is not None else last["close"]} by origin'
    return (f'<div class="stats four">{s}</div><div class="grid2">' + card("Paid per close", ch) + card(sub, ch2) + "</div>"
            + card(f"Settlement · {len(rs):,}", f'<div class="chips scroll">{chips}</div>' + tb + cov, links, cls="histc", id="settlement"))

def changes_tab(qs, href, qsx):
    rows = standing_changes()
    if not rows: return card("Changes", '<p class="na">No close record in this segment yet.</p>')
    by = SS.page_sort(qs, dict(CHG_SORTS), "close"); d = SS.page_dir(qs)
    rs = SS.sort_rows(list(rows), lambda r: r[by], "num", d, tie=lambda r: -r["close"])
    link = lambda k, dd: href("changes", sort=k if k != "close" else "", dir="asc" if dd == "asc" else "") + "#changes"
    last = rows[-1]
    s = "".join([stat("Established", intc(last["after"]), tip=f'After the E{last["close"]} close'), stat("Added", intc(last["added"]), tip=f'At E{last["close"]}'),
                 stat("Removed", intc(last["removed"]), tip=f'At E{last["close"]}'), stat("Net", f'<span class="num">{last["net"]:+,}</span>', tip=f'At E{last["close"]}')])
    ch = bars([(f'E{r["close"]}', [r["added"], r["removed"]]) for r in rows], height=150, colors=("verd", "ember"), fmt=lambda z: f"{z:,.0f}", legend=["Added", "Removed"], stacked=False)
    sel = _q(qs, "close"); one = next((r for r in rows if str(r["close"]) == sel), None)
    trs = "".join(f'<tr><td><a href="{href("changes", close=str(r["close"]))}#changes-list">E{r["close"]}</a>{CPZ.tag(r.get("pause"))}</td><td class="r dk">{_n(r["before"])}</td><td class="r">{_n(r["added"])}</td>'
                  f'<td class="r">{_n(r["removed"])}</td><td class="r">{r["net"]:+,}</td><td class="r">{_n(r["after"])}</td></tr>' for r in rs)
    tb = SS.select(CHG_COLS, by, d, link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(CHG_COLS, by, d, link)}</tr></thead><tbody>{trs}</tbody></table></div>'
    q = qsx(sort=by if by != "close" else "", dir="asc" if d == "asc" else "")
    links = f'<a class="more" href="/api/v1/governance/standing-changes.csv{q}" download>CSV →</a><a class="more" href="/api/v1/governance/standing-changes{q}">API →</a>'
    cov = f'<p class="cov dim small">minepoa\'s engine, one close at a time: genesis import, plus established_after, minus established_removed. Relisted rows are not counted as added. <a href="{METHOD}">Method</a></p>'
    det = ""
    if one:
        nm = A.forum_names()
        li = lambda xs: "".join(f'<li>{agent(a, nm.get(a) or "")}</li>' for a in xs) or '<li class="dim">None</li>'
        det = card(f'E{one["close"]} changes', f'<div class="grid2"><div><h3>Added · {one["added"]:,}</h3><ul class="plain">{li(one["added_list"])}</ul></div>'
                   f'<div><h3>Removed · {one["removed"]:,}</h3><ul class="plain">{li(one["removed_list"])}</ul></div></div>', id="changes-list")
    return f'<div class="stats four">{s}</div>' + card("Added and removed per close", ch) + card(f"Changes · {len(rs):,}", tb + cov, links, cls="histc", id="changes") + det

def never_tab(qs, href, qsx):
    if SG.archived(): return card("Never established", '<p class="na">Shown for the current segment only.</p>')
    rows = never_established(); by = SS.page_sort(qs, dict(NEV_SORTS), "joined"); d = SS.page_dir(qs)
    rs = never_select(by, d); pg, pages = _pg(qs, len(rs)); cur = rs[(pg - 1) * PAGE: pg * PAGE]
    keep = lambda **o: dict(dict(sort=by if by != "joined" else "", dir="asc" if d == "asc" else ""), **o)
    link = lambda k, dd: href("never", **keep(sort=k if k != "joined" else "", dir="asc" if dd == "asc" else "", page="")) + "#never"
    total = db.q1("SELECT COUNT(*) AS n FROM accounts")["n"] or 0
    s = "".join([stat("Agents", intc(total)), stat("Never established", intc(len(rows))),
                 stat("Share", f'<span class="num">{100 * len(rows) / total:.1f}%</span>' if total else "···"), stat("With answers", intc(sum(1 for r in rows if r["answers"])), tip="Answered at least once this segment")])
    by_ep = collections.Counter((r["joined_segment"] or SG.CURRENT, r["joined_epoch"]) for r in rows if r["joined_epoch"] is not None)
    ep_l = lambda k: f"E{k[1]}" if k[0] == SG.CURRENT else f"S{k[0]} E{k[1]}"
    ch = bars([(ep_l(k), [v]) for k, v in sorted(by_ep.items())[-30:]], height=150, colors=("steel",), fmt=lambda z: f"{z:,.0f}", legend=["Never established, by join epoch"]) if by_ep else ""
    trs = "".join(f'<tr><td>{agent(r["address"], r["name"] or "")}</td><td class="r">{lt(r["joined_ts"], "d") if r["joined_ts"] else "<span class=dim>···</span>"}</td>'
                  f'<td class="r">{_n(r["answers"])}</td><td class="r dk">{_n(r["closes_paid"])}</td><td class="r dk">{lt(r["last_ts"], "d") if r["last_ts"] else "<span class=dim>···</span>"}</td>'
                  f'<td class="r">{r["balance"]:,.2f}</td></tr>' for r in cur)
    tb = (SS.select(NEV_COLS, by, d, link) + f'<div class="tw"><table class="hist cal gov"><thead><tr>{SS.heads(NEV_COLS, by, d, link)}</tr></thead>'
          f'<tbody>{trs or "<tr><td colspan=6 class=na>Every Agent has been established.</td></tr>"}</tbody></table></div>')
    nav = _nav(pg, pages, lambda p: href("never", **keep(page=str(p) if p > 1 else "")) + "#never")
    q = qsx(sort=by if by != "joined" else "", dir="asc" if d == "asc" else "")
    links = f'<a class="more" href="/api/v1/governance/never-established.csv{q}" download>CSV →</a><a class="more" href="/api/v1/governance/never-established{q}">API →</a>'
    cov = (f'<p class="cov dim small">Agents in minepoa\'s agent list never in any close record\'s established_after, any genesis import or minepoa\'s current established list, '
           f'in every segment POAScan holds. <a href="{METHOD}">Method</a></p>')
    return f'<div class="stats four">{s}</div>' + (card("By join epoch", ch) if ch else "") + card(f"Never established · {len(rs):,}", tb + nav + cov, links, cls="histc", id="never")

# ---------------------------------------------------------------- API
BASE = "https://poascan.io"
def _seg(): return dict(segment=SG.selected(), archived=SG.archived())

def api_settlement(close=None, sort="close", d="desc", limit=1000, offset=0):
    rs = settlement_select(close, sort, d)
    return dict(_seg(), source="close records", close=close, sort=sort, dir=d, total=len(rs), offset=offset, limit=limit,
                closes=settlement_closes(), definitions=SET_TIP, method=BASE + METHOD, rows=rs[offset:offset + limit])

def api_changes(close=None, sort="close", d="desc"):
    rs = SS.sort_rows(list(standing_changes()), lambda r: r[sort], "num", d, tie=lambda r: -r["close"])
    if close is not None: rs = [r for r in rs if r["close"] == close]
    keep = lambda r: r if close is not None else {k: v for k, v in r.items() if not k.endswith("_list")}
    return dict(_seg(), source="close records (minepoa's engine fold)", close=close, sort=sort, dir=d, total=len(rs), method=BASE + METHOD,
                note="added excludes relisted (already established); with close= each row carries added_list and removed_list.", rows=[keep(r) for r in rs])

def api_never(sort="joined", d="desc", limit=1000, offset=0):
    rs = never_select(sort, d) if not SG.archived() else []
    return dict(_seg(), source="minepoa agent list, close records of every segment held, minepoa's established list", sort=sort, dir=d, total=len(rs),
                offset=offset, limit=limit, method=BASE + METHOD, rows=rs[offset:offset + limit])
