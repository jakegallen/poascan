"""Batch 3: unlock calendar + circulating supply, address reward tracker, /growth."""
import time, json, collections, datetime as dt
from . import market as _X
from html import escape as E
from . import segments as _SG
from . import db, analytics as A, agents as G
from .ui import *
from . import prompts as PR
from .ui import _ic

def page(*a):
    from . import views
    return views.page(*a)

DAY = 86400

def _vest(): return int(A.params().get("vesting_epochs") or 100)
def vest_days(): return f'≈{_vest() * int(A.params().get("auto_epoch_seconds") or 21600) / 86400:.0f} days'

def _minted_by_epoch():
    out = collections.Counter()
    for a, r in A.rewards_by_addr().items():
        for k, v in A.confirmed(r).items(): out[k] += v   # 1.26.122: the vesting basis is confirmed rewards
    return dict(out)

def _close_ts(j):
    """Estimated close time of epoch j (j >= open epoch); past epochs use the real close."""
    o = A.open_epoch(); n = o["epoch"]
    for r in A.epoch_rows():
        if r["epoch"] == j: return r["close_ts"]
    if o["est_close"] is None: return None
    return o["est_close"] + (j - n) * o["period"]

@A.cached("unlocks", 60)
def unlock_data():
    # R is keyed by lifetime close number (segments.gkey): vesting counts closes across the genesis cut. fut keeps the
    # current segment's own epoch number for labels.
    vest = _vest(); R = _minted_by_epoch(); o = A.open_epoch(); n = o["epoch"]; tot = sum(R.values())
    off = _SG.offset(_SG.CURRENT); ng = off + n
    full = _SG.carry_unlocked() is True   # 1.26.123: carried rewards spendable since the cut (segments config)
    def circ(j):  # circulating right after lifetime close j (open = j+1)
        return sum(v * (1.0 if full and k < off else min(1.0, max(0, j + 1 - k) / vest)) for k, v in R.items())
    past = []
    for m in _SG.NUMBERS:
        with _SG.use(m): past += [(r["close_ts"], circ(_SG.gkey(r["epoch"], m))) for r in A.epoch_rows()]
    last_k = max(R) if R else ng
    fut = []
    for jg in range(ng, last_k + vest):
        t = _close_ts(jg - off)
        if t: fut.append((jg - off, t, circ(jg), circ(jg) - circ(jg - 1)))
    now_c = circ(ng - 1)
    hit = {}
    for p in (.25, .5, 1.0):
        hit[p] = next(((j, t) for j, t, c, _ in fut if c >= p * tot - 1e-6), None) if now_c < p * tot - 1e-6 else ("done", None)
    return dict(vest=vest, total=tot, now=now_c, past=past, fut=fut, hit=hit, period=o["period"], open=n,
                next=fut[0] if fut else None)

def _days(t):
    if not t: return '<span class="na">···</span>'
    d = (t - time.time()) / DAY
    return f'<span class="num">{d:,.1f}</span> <span class="unit">days</span>'

def unlock_stats():
    u = unlock_data(); nx = u["next"]
    def th(p):
        h = u["hit"][p]
        return '<span class="tag ok">REACHED</span>' if h and h[0] == "done" else (_days(h[1]) if h else '<span class="na">···</span>')
    return "".join([
        stat("Circulating", poa(u["now"]) + _X.usd_of(u["now"]), "", ICON_LOCK, "vest", flag_html=A.carry_flag("circ")),
        stat("Circulating %", pct(u["now"] / u["total"]) if u["total"] else "···", flag_html=A.carry_flag("circ")),
        stat("Next unlock", (poa(nx[3]) + f' <span class="dim small">· E{nx[0]} close</span>') if nx else "···"),
        stat("Next unlock in", f'<span class="xcd num" data-close="{int(nx[1])}"></span>' if nx else "···"),
        stat("To 25%", th(.25)), stat("To 50%", th(.5)), stat("To 100%", th(1.0)),
        stat("Vesting", f'<span class="num">{u["vest"]}</span> <span class="unit">epochs · {vest_days()}</span>')])

def unlock_chart():
    u = unlock_data(); now = time.time()
    pts = u["past"] + [(t, c) for _, t, c, _ in u["fut"]]
    if pts and pts[0][1] > 0: pts = [(pts[0][0] - u["period"], 0.0)] + pts
    marks = [(h[1], f"{int(p*100)}%") for p, h in u["hit"].items() if h and h[0] != "done" and h[1]]
    return line(pts, height=200, color="gold", fmt=compact, xk="d", xfmt=lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%b %-d"),
                marks=marks, proj_from=now, y0=0)

def unlock_calendar(nrows=12):
    # 1.26.201: sorts by header (soonest close first by default)
    from . import scoresort as SS, views as _V
    u = unlock_data(); tot = u["total"] or 1
    cols = [SS.Col("close", "At close", "low"), SS.Col(None, f"Time ({TZ})"), SS.Col("unlocks", "Unlocks"), SS.Col("circ", "Circulating"), SS.Col(None, "%")]
    vals = {"close": lambda x: x[0], "unlocks": lambda x: x[3], "circ": lambda x: x[2]}
    base = "/unlocks" if getattr(_V.REQ, "path", "") == "/unlocks" else "/network?tab=token"   # /unlocks and the Token tab share it
    items, spec = SS.table_sort(getattr(_V.REQ, "qs", None) or {}, cols, list(u["fut"][:nrows]), vals, "close", base, "#calendar")
    rows = [[f'E{j}', utc(t, "%m-%d %H:%M"), poa(d), poa(c), pct(c / tot)] for j, t, c, d in items]
    return table([], rows, pri=(0, 2, 3), usd=(2, 3), sort=spec)

def unlock_section():
    return (f'<div id="unlocks"></div>{card(ICON_LOCK + "Circulating supply · minted to date", unlock_chart(), PR.ask([PR.UNLOCK, PR.SPENDABLE]), cls="")}'
            f'<div class="stats eight">{unlock_stats()}</div>'
            f'{card("Unlock calendar", unlock_calendar(), _X.usd_toggle() + "<a class=\'more\' href=\'/api/unlocks.csv\'>CSV →</a>", id="calendar")}')

def unlocks_api():
    u = unlock_data()
    b = _SG.carry_basis()
    return [dict(epoch_close=j, ts=int(t), unlocks=round(d, 6), circulating=round(c, 6), pct=round(c / u["total"], 6) if u["total"] else None, basis=b) for j, t, c, d in u["fut"]]

# ---------------- address reward tracker ----------------
def reward_tracker(a, p):
    # one key space: lifetime close numbers (segments.gkey), so segment 1 rewards keep vesting across the genesis cut
    vest = _vest(); o = A.open_epoch(); off = _SG.offset(_SG.CURRENT); n = off + o["epoch"]; rb = p["rewards"]
    sett = collections.defaultdict(lambda: [0, 0, 0])   # passed, juried, expired with no jury (not a failure)
    for e, _, ok, oc in p["settled"]:
        if oc == "expired_no_jury": sett[off + e][2] += 1
        else: sett[off + e][1] += 1; sett[off + e][0] += 1 if ok else 0
    answered = {off + k for k in p["answered"]}
    eps = sorted(answered | set(rb) | set(sett))
    if not eps: return '<p class="na">No answers yet.</p>', ""
    rows = []
    for k in reversed(eps):
        sub = k in answered
        if k >= n: gr, gs = ("open", "cur")
        elif sett.get(k) and sett[k][1]: gr, gs = (f'{sett[k][0]}/{sett[k][1]} pass', "ok" if sett[k][0] else "bad")
        elif sett.get(k): gr, gs = ('<span title="Expired, no jury">expired</span>', "dimx")
        elif sub: gr, gs = ("unsettled", "dimx")
        else: gr, gs = ("···", "off")
        r = rb.get(k)
        if k >= n: pd, ps = ("at close", "cur")
        elif r: pd, ps = (poa(r, dec=2), "ok")
        else: pd, ps = ("0", "off" if not sub else "bad")
        if r:
            f = 1.0 if (_SG.carry_unlocked() is True and k < off) else min(1.0, max(0, n - k) / vest); done_t = _close_ts(k + vest - 1 - off)
            vs = (f'<span class="vbar"><i style="width:{f*100:.1f}%"></i></span><span class="num">{f*100:.0f}%</span>'
                  + (f' <span class="dim small">full {utc(done_t, "%m-%d")}</span>' if f < 1 else ""))
            vss = "ok" if f >= 1 else "cur"
        else: vs, vss = ("···", "off")
        step = lambda st, lab, val: f'<div class="rs {st}"><i></i><b>{lab}</b><span>{val}</span></div>'
        rows.append(f'<div class="rtr"><a class="rte" href="{_SG.ep_href(k)}">{_SG.ep_label(k)}</a><div class="rsteps">'
                    + step("ok" if sub else ("off" if k < n else "cur"), "Submitted", "yes" if sub else (("grader only" if r else "···") if k < n else "…"))
                    + step(gs, "Graded", gr) + step(ps, "Paid", pd) + step(vss, "Vesting", vs) + '</div></div>')
    # schedule
    nxt = sum(v / vest for k, v in rb.items() if k <= n - 1 and n + 1 - k <= vest)
    full_t = _close_ts(max(rb) + vest - 1 - off) if rb else None
    tot = sum(rb.values()); unl = sum(v * min(1.0, max(0, n - k) / vest) for k, v in rb.items())
    t_next = o["est_close"]
    sched = "".join([stat("Unlocked", pct(unl / tot) if tot else "···"), stat("Next unlock", poa(nxt) if rb else "···"),
                     stat("Next in", f'<span class="xcd num" data-close="{int(t_next)}"></span>' if t_next and rb else "···"),
                     stat("Fully vested", utc(full_t, "%m-%d %H:%M") if full_t else "···")])
    return f'<div class="rtrack">{"".join(rows)}</div>', f'<div class="stats eight">{sched}</div>'

def invite_tree(a, depth=2, cap=40):
    acc = G.accounts_all(); kids = collections.defaultdict(list)
    for x, r in acc.items():
        if r["invited_by"]: kids[r["invited_by"]].append(x)
    rb = A.rewards_by_addr(); nm = A.forum_names()
    def node(x, d):
        ch = kids.get(x, [])
        earned = sum(rb.get(x, {}).values())
        lab = f'{addr_link(x, nm)} <span class="dim small">{compact(earned)} POA · {len(ch)} inv</span>'
        if not ch or d >= depth: return f'<li>{lab}</li>'
        inner = "".join(node(c, d + 1) for c in sorted(ch, key=lambda c: -sum(rb.get(c, {}).values()))[:cap])
        more = f'<li class="dim small">+{len(ch)-cap} more</li>' if len(ch) > cap else ""
        return f'<li><details{" open" if d == 0 else ""}><summary>{lab}</summary><ul>{inner}{more}</ul></details></li>'
    up = acc.get(a, {}).get("invited_by") if acc.get(a) else None
    upline = f'<div class="small dim">Invited by {addr_link(up, nm)}</div>' if up else ""
    n_inv = len(kids.get(a, []))
    return upline + (f'<ul class="itree">{node(a, 0)}</ul>' if n_inv else '<p class="na">No invites yet.</p>'), n_inv

# ---------------- growth ----------------
def _ep_rows(n):
    with _SG.use(n): return A.epoch_rows()

@A.cached("growth", 120)
def growth_data():
    s = A.accounts_series()
    agents = [(t, a) for t, a, h, sup, tx in s if a]
    holders = [(t, h) for t, a, h, sup, tx in s if h]
    supply = [(t, sup) for t, a, h, sup, tx in s if sup]
    day = db.q("SELECT (ts/86400)*86400 AS d, COUNT(*) AS n FROM txs WHERE ts IS NOT NULL GROUP BY d ORDER BY d")
    hour = db.q("SELECT (ts/3600)*3600 AS h, COUNT(*) AS n FROM txs WHERE ts IS NOT NULL GROUP BY h ORDER BY h")
    # 1.26.91: closes from every segment, keyed by lifetime close number (epoch numbers restart at a genesis cut), so the
    # charts run on across the cut; labels read E3 in the current segment and S1 E3 in an archived one (segments.py)
    per_ep, rows = [], []
    for n in _SG.NUMBERS:
        with _SG.use(n):
            ans = G.answerers(); rs = A.epoch_rows(); paid = {r["epoch"]: r["paid"] for r in rs}
            per_ep += [(_SG.gkey(k, n), len(ans.get(k, ())), paid.get(k, 0)) for k in sorted(set(ans) | set(paid))]
            rows += [dict(r, g=_SG.gkey(r["epoch"], n)) for r in rs]
    ms = []
    for th in (500, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 7500, 10000):
        hit = next((t for t, a in agents if a >= th), None)
        if hit and agents[0][1] < th: ms.append((hit, f"{th//1000}k" if th % 1000 == 0 else f"{th/1000:g}k", "agents"))
    for r in rows: ms.append((r["close_ts"], _SG.ep_label(r["g"]), "close"))
    c = _SG.cut()
    if c: ms.append((c["ts"], c["label"], "cut"))   # chart markers for the cut come from milestones.py (every chart); kept here for callers of ms
    t1 = _X.first_offer_ts()   # from /api/v1/swaps
    if t1: ms.append((t1, "1st swap", "swap"))
    return dict(agents=agents, holders=holders, supply=supply, day=day, hour=hour, per_ep=per_ep, ms=sorted(ms))

RANGES = [("24h", "24h", DAY), ("7d", "7d", 7 * DAY), ("30d", "30d", 30 * DAY), ("all", "All", None)]   # 1.26.121: 30d, from our own DB

def charts_body(rng=""):
    """Network → Charts (was /growth): small multiples over one shared range. Home shows the same series as sparklines."""
    rng = rng if rng in [k for k, _, _ in RANGES] else "7d"
    span = dict((k, v) for k, _, v in RANGES)[rng]; now = time.time(); t0 = now - span if span else 0
    g = growth_data(); cut = lambda pts: [(t, v) for t, v in pts if t >= t0]
    xf = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%m-%d %H:%M")
    from . import milestones as MS   # each chart carries only the milestones that affect its data (milestones.json), grouped so they stay readable at 390px
    mk = lambda key, pts: MS.group([e for e in MS.events(key) if e["ts"] >= t0], pts[0][0], pts[-1][0]) if len(pts) > 1 else []
    am = [(t, l) for t, l, k in g["ms"] if k == "agents" and t >= t0] + mk("agents", cut(g["agents"]))   # Agent count thresholds, then joining milestones
    em = mk("holders", cut(g["holders"]))
    n24 = A.joins_between(now - DAY, now)   # joins summed within each segment: the cut is neither a drop nor a rise
    tday = g["day"][-1]["n"] if g["day"] else None
    pe = g["per_ep"]; closes = {_SG.gkey(r["epoch"], n): r["close_ts"] for n in _SG.NUMBERS for r in _ep_rows(n)}
    pe_r = [x for x in pe if (closes.get(x[0]) or now) >= t0]
    st = "".join([stat("New · 24h", f'<span class="num">+{n24:,}</span>' if n24 is not None else "···", tip="Agents joined in the last 24 hours"),
                  stat("Today (UTC)", intc(tday), tip="Txs indexed since 00:00 UTC"),
                  stat("Answerers", intc(pe[-2][1] if len(pe) > 1 else (pe[-1][1] if pe else None)), tip="Agents who answered in the last closed epoch")])
    H = 140
    ac = line(cut(g["agents"]), height=H, color="gold", fmt=lambda v: f"{v:,.0f}", xfmt=xf, marks=am)
    hc = line(cut(g["holders"]), height=H, color="gold", fmt=lambda v: f"{v:,.0f}", xfmt=xf, marks=em)
    up = [e for e in MS.events() if e["ts"] >= t0]; sp = cut(g["supply"])   # up: every event, for the Milestones table
    um = mk("supply", sp)
    sc = line(sp, height=H, color="gold", fmt=compact, xfmt=xf, y0=0, marks=um)
    end = lambda h, m: h.replace('<div class="chartbox', '<div class="chartbox end', 1) if m else h   # 390px: a marked chart opens at its newest end
    ac, hc, sc = end(ac, any(len(x) > 2 for x in am)), end(hc, em), end(sc, um)
    tp = [(r["h"], r["n"]) for r in g["hour"][:-1] if r["h"] >= t0]
    tm = mk("txs", tp); th = None if rng == "all" else end(line(tp, height=H, color="gold", fmt=lambda v: f"{v:,.0f}", xfmt=xf, y0=0, marks=tm), tm)
    ec = bars([(_SG.ep_label(k), [a, max(0, p)]) for k, a, p in pe_r], height=H, colors=("gold", "steel"), fmt=lambda v: f"{v:,.0f}", stacked=False, legend=["Answered", "Paid"])
    tc = th or bars([(dt.datetime.fromtimestamp(r["d"], dt.timezone.utc).strftime("%b %-d"), [r["n"]]) for r in g["day"] if r["d"] + DAY > t0], height=H, colors=("gold",), fmt=lambda v: f"{v:,.0f}")
    from . import signed as SG   # notice milestones link their G0-signed tx: badge from signed.py
    sb = lambda u: (f'<span class="sigl">{h}</span>' if (h := SG.badge_tx(u[4:])) else "") if u and u.startswith("/tx/") else ""
    lk = lambda e: (f'<a href="{E(e["url"])}"' + (' target="_blank" rel="noopener noreferrer"' if e["url"].startswith("http") else "") + f'>{E(e["label"])}</a>{sb(e["url"])}') if e["url"] else E(e["label"])
    rows = [(t, 0, E({"agents": f"{l} agents", "close": f"{l} closed", "swap": "First swap offer"}[k])) for t, l, k in g["ms"] if t >= t0 and k != "cut"] + [(e["ts"], 1, lk(e)) for e in up]
    ml = table([f"Time ({TZ})", "Milestone"], [[utc(t, "%m-%d %H:%M"), x] for t, _, x in sorted(rows, key=lambda r: (r[0], r[1]), reverse=True)])
    chips = "".join(f'<a href="/network?tab=charts{"" if k == "7d" else "&amp;range=" + k}" class="chip {"on" if k == rng else ""}">{t}</a>' for k, t, _ in RANGES)
    pc = lambda title, name, key, body: card(title, f'<div class="cpw" data-chart="{key}" data-chart-range="{rng}">{body}</div>', pop_btn(key, name))   # click or Expand: the pop-out
    tn = "Txs" + (" / day" if rng == "all" else " / hour")
    return f'''<div class="stats three">{st}</div><div class="chips rng" role="group" aria-label="Range">{chips}</div>
<div class="grid3 smalls">{pc(ICON_BOT + "Agents", "Agents", "agents", ac)}{pc(ICON_USERS + "Holders", "Holders", "holders", hc)}{pc("Supply", "Supply", "supply", sc)}{pc(tn, tn, "txs", tc)}{pc(ICON_CUBE + "Answers / epoch", "Answers / epoch", "answers", ec)}{card("Milestones", ml, cls="mls")}</div>'''
