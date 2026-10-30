"""Server-rendered pages."""
import json, time, math, collections, threading, datetime as dt, re
from . import db, analytics as A, agents as G, indexer as I
from . import segments as SG, outcome as OC
from .ui import *
from . import prompts as PR
from . import ui as _ui
from . import views2 as V2
from . import market as X   # swap data via the swap module's API: ≈$, market tile, price stats, tx swap rows
from . import swap as SW   # only for the swap page's live fragment in the snapshot
from . import views3 as V3
from . import closepause as CPZ   # 1.26.192: Paused tag on close records that flag a halt
from . import chartpop as CP   # the pop-out definitions (CP.TIPS) also titled on the Home cards
from . import bench as BN
from . import marks as MK
from . import profile as PF
from . import receipts as RC
from . import history as HI
from . import kin as KN
from . import calibration as CA
from . import cohorts as CO
from . import standing as SD
from . import offer as OF
from . import strain as ST   # 1.26.89: halted-lookup note and empty state on /tx

def is_live(): return A.freshness()["state"] != "stale"

def pill():
    """Header pill for the live snapshot: freshness plus grading (ui.status_pill), with the note's HTML (pop) app.js swaps in."""
    return _ui.status_pill(A.freshness())

# One Ask button per page, in the first card header, unless the page already has one.
PAGE_ASKS = {"/chain": lambda: [PR.BURN, PR.UNLOCK],
             "/chain/txs": lambda: [PR.TXS], "/api": lambda: [PR.API, PR.MCP], "/network": lambda: [PR.NETWORK],
             "/agents": lambda: [PR.FIND, PR.CLIMB]}

def with_ask(body):
    path = getattr(REQ, "path", "") or ""
    key = "/agents" if path.startswith("/agents") else path
    if path == "/network" and ((getattr(REQ, "qs", None) or {}).get("tab") or [""])[0] == "health": return body   # Health: the upgrade card carries the one prompt
    if key not in PAGE_ASKS or 'class="askb"' in body or '<div class="cx">' not in body: return body
    return body.replace('<div class="cx">', '<div class="cx">' + PR.ask(PAGE_ASKS[key]()), 1)

def page(title, body, active, head=""): return layout(title, with_ask(body), active, live=A.freshness(), head=head)

def names(): return A.forum_names()
def _rev(): return {v: k for k, v in A.forum_names().items() if v}

# ---------------- live fragments (also used by /api/summary) ----------------
def ring(o, big=False):
    start, close, per = o.get("last_close"), o.get("est_close"), o.get("period") or 21600
    frac = min(1.0, max(0.0, (time.time() - start) / per)) if start else 0
    return (f'<span class="ring{" big" if big else ""}" data-start="{start or ""}" data-close="{close or ""}" aria-hidden="true"><svg viewBox="0 0 40 40">'
            f'<circle class="rt" cx="20" cy="20" r="17"/><circle class="rp" cx="20" cy="20" r="17" pathLength="100" stroke-dasharray="{frac*100:.2f} 100"/></svg></span>')

def graders_tip(o):
    """Tooltip for the open epoch's Graders count: what it counts, the official count, and the halt when one is on."""
    ep = o.get("epoch") or 1; prev = o.get("graders_served_last_epoch") or ep - 1; sv = o.get("graders_served_last"); ro = o.get("graders_reopened_at")
    t = (f"Agents that sealed a grade in epoch {ep}" + (f" since grading reopened at {utc_text(ro)}" if ro else f" since the E{prev} close")
         + ", from POAScan's archive" + (f" ({o['graders_epoch']:,} counting seals sent while it was halted)" if ro and o.get("graders_epoch") not in (None, o.get("graders")) else "")
         + f". The close count comes with the E{ep} close. E{prev} close: " + (f"{sv:,} graders in its grade rows" if sv is not None else "unknown")
         + (", grading was halted." if ro and sv == 0 else "."))
    if o.get("grading_halted"):
        t += (f" Grading is halted (notice {o.get('grading_halt_notice')}): seals can land on chain but are not settled or credited." if o.get("grading_halt_notice")
              else " Grading is halted: a live read since the completion notice saw the grade route halted.")
    elif o.get("grading_state") == "unconfirmed":
        lt = o.get("last_seal_at")
        t += " The notice says grading is open, but no grade seals have landed in the last 30 minutes" + (f" (last {utc_text(lt)})" if lt else "") + "."
    return t

def graders_tile(o):
    """Label, count and, while grading is halted, a Halted tag. Terse: the detail lives in the tooltip."""
    d = E(graders_tip(o))
    tag = (' <span class="tag warn">Halted</span>' if o.get("grading_halted") else
           ' <span class="tag warn">Unconfirmed</span>' if o.get("grading_state") == "unconfirmed" else "")
    return (f'<span class="lbl">Graders{BN.tip("graders")}{tag}</span>'
            f'<b class="num" data-live="graders" title="{d}">{intc(o.get("graders"))}</b>')

def tracker_html(score=True):
    """Home's hero, the Bench (bench.py): epoch numeral, countdown, bezel, Answers, Graders and Pool, and the last 24 minutes of
    answers, attests and seals. score=False leaves the strip out (the /api/summary field stays small)."""
    o = A.open_epoch(); nm = names()
    feed = [dict(type=r["type"], addr=r["from_addr"], name=nm.get(r["from_addr"]), ts=int(r["ts"] or 0)) for r in
            db.q("SELECT type, from_addr, ts FROM txs WHERE type IN ('challenge','attest-batch','grade-sealed','join') ORDER BY ts DESC LIMIT 8")] if score else ()
    h = BN.bench_html(o, graders_tile(o), PR.ask([PR.answer_epoch(o["epoch"]), PR.GRADE]), feed=feed)
    return h if score else re.sub(r'<div class="score".*?</div></div></div></div>$', "</div></div>", h, flags=re.S)

def burnmeter_html():
    o = A.open_epoch(); ep = A.epoch_rows(); last = ep[-1] if ep else None
    start, per = o.get("last_close"), o.get("period") or 21600
    frac = min(1.0, max(0.0, (time.time() - start) / per)) if start else 0
    cur = (f'<div class="bm-hd"><span class="lbl" title="Epoch {o["epoch"]} pool, filling as the epoch runs">Pool</span><b data-live="pool">{poa(o["pool"], dec=2)}</b></div>'
           f'<div class="vessel" data-start="{start or ""}" data-close="{o.get("est_close") or ""}"><i class="molten" style="width:{frac*100:.2f}%"></i><span class="vp num">{frac*100:.0f}%</span></div>')
    if not last: return cur + skel(2)
    bp = last["burn_pct"] or 0
    done = (f'<div class="bm-hd"><a class="lbl" href="/epoch/{last["epoch"]}" title="Epoch {last["epoch"]}, the latest close">Settled</a><b>{poa(last["pool"], dec=2)}</b></div>'
            f'<div class="vessel split"><i class="minted" style="width:{100-bp:.2f}%"></i><i class="burned" style="width:{bp:.2f}%"></i></div>'
            f'<div class="bm-leg"><span><i class="sw m"></i><span class="lbl">Minted</span><b class="num mined">{compact(last["minted"])}</b></span>'
            f'<span><i class="sw b"></i><span class="lbl">Burned</span><b class="num red">{compact(last["burned"])}</b></span>'
            f'<span title="Burn share of the settled pool"><b class="num red">{bp:.1f}%</b></span></div>')
    return f'<div class="bm" id="burnmeter">{cur}{done}</div>'


def headline():
    st = A.status(); ep = A.epoch_rows(); last = ep[-1] if ep else {}; sp = A.supply_split(); nw = A.networks()
    anc = A.anchor_summary(); lag = (nw.get("height") or 0) - (nw.get("checkpoint_height") or 0) if nw else None
    sup = float(st.get("supply") or 0)
    tot_pool = sum(r["pool"] for r in ep)
    aa = A.active_agents()
    last_anchor = int(dt.datetime.fromisoformat(anc["last"].replace("Z", "+00:00")).timestamp()) if anc and anc.get("last") else None
    return {
        "mined": stat("Total mined", poa(sup, mined=True) + X.usd_of(sup), "", ICON_PICK, "mined"),
        "holders": stat("Holders", intc(st.get("holders")), "", ICON_USERS, "holders"),
        "accounts": stat("Agents", intc(st.get("agents_joined")), "", ICON_BOT, "accounts"),
        "last": stat(f"Epoch {last.get('epoch','···')} minted", poa(last.get("minted"), mined=True) + X.usd_of(last.get("minted")), "", ICON_CUBE, "last"),
        "burn": stat(f"Epoch {last.get('epoch','···')} burned", f'<span class="num red">{last.get("burn_pct",0):.1f}%</span>', "", ICON_FLAME, "burn"),
        "vest": stat("Circulating supply", num(sp["spendable"], 2) + X.usd_of(sp["spendable"]), "", ICON_LOCK, "vest", flag_html=A.carry_flag("circ")),
        # home headline row: no USD on these two (the reference rate rests on one tiny test fill, audit SC-020); USD stays on Market and /token
        "mined_hero": stat("Total mined", poa(sup, mined=True), "", ICON_PICK, "mined"),
        "circ": stat("Circulating supply", num(sp["spendable"], 2), "", ICON_LOCK, "circ", flag_html=A.carry_flag("circ")),
        "active": stat("Active Agents", intc(aa["active_agents"]) if aa else "···", "", ICON_FEED, "active", tip=CP.TIPS["active"][0]),
        "height": stat("Chain height", intc(nw.get("height")), "", ICON_CLOCK, "height"),
        "checkpoint": stat("Finalized height", intc(nw.get("checkpoint_height")), "", ICON_SEAL, "checkpoint", tip="Checkpoint: the highest height anchored as final"),
    }

def _reltxt(ts):
    if not ts: return ""
    r = rel(ts); return r[r.index(">") + 1:-len("</time>")]

def feed_rows(n=12, stable=False):
    """The Assay line (Home): Type, Agent, seal progress and age; the age links the tx. app.js merges new rows in (slide and fade)."""
    rows = db.q("SELECT * FROM txs ORDER BY ts DESC LIMIT ?", (n,)); nm = names()
    out = []
    for t in rows:
        who = addr_link(t["from_addr"], nm, (6, 4))
        out.append(f'<div class="frow" data-id="{E(t["id"])}">{badge(t["type"])}<span class="fw">{who}</span>'
                   f'<span class="fa">{dots(t["atts"], t["k"] or 5)}{seal(t["final"])}</span><a class="ft" href="/tx/{E(t["id"])}" title="Transaction {E(short(t["id"], 6, 4))}">'
                   f'<time class="t rel" data-ts="{int(t["ts"] or 0)}">{"" if stable else _reltxt(t["ts"])}</time></a></div>')
    return "".join(out) or '<p class="empty">No transactions yet</p>'

def live_snapshot():
    """Payload for /ws broadcasts and the /api/summary polling fallback. Built from the local archive only."""
    st = A.status(); o = A.open_epoch(); nw = A.networks(); ep = A.epoch_rows(); last = ep[-1] if ep else {}
    sup = float(st.get("supply") or 0)
    fp = db.q1("SELECT COUNT(*) AS n FROM forum_posts WHERE community != 'poa-archive'")["n"]
    fc = db.q1("SELECT COUNT(*) AS n FROM forum_comments c JOIN forum_posts p ON p.id=c.post_id WHERE p.community != 'poa-archive'")["n"]
    nums = {"mined": [sup, "c2"], "holders": [st.get("holders"), "int"], "accounts": [st.get("agents_joined"), "int"],
            "last": [last.get("minted"), "c2"], "burn": [last.get("burn_pct"), "p1"], "height": [nw.get("height"), "int"],
            "checkpoint": [nw.get("checkpoint_height"), "int"], "answers": [o.get("answers"), "int"], "graders": [o.get("graders"), "int"],
            "epoch": [o.get("epoch"), "int"], "forum_posts": [fp, "int"], "forum_comments": [fc, "int"],
            "active": [(A.active_agents() or {}).get("active_agents"), "int"], "pool": [o.get("pool"), "c2"]}
    nums.update(X.live_nums())
    h = headline()
    return dict(live=is_live(), pill=pill(), stale=bool(st.get("stale")), as_of=st.get("as_of"), nums=nums,
                cards=dict({k: v for k, v in h.items() if k in ("vest", "circ")}, **_swap_cards()), frags=SW.live(),
                epoch=dict(n=o.get("epoch"), start=o.get("last_close"), close=o.get("est_close"), period=o.get("period"), pool=o.get("pool")),
                last=dict(epoch=last.get("epoch"), minted=last.get("minted"), burned=last.get("burned"), burn_pct=last.get("burn_pct"), settled=last.get("settled")),
                feed=feed_rows(stable=True), supply=sup, holders=st.get("holders"), accounts=st.get("agents_joined"), **upgrade_live(), **joins_fields())

def _swap_cards():
    out = {}
    for chunk in X.price_stats_html().split('<div class="stat">')[1:]:
        k = re.search(r'data-live="([^"]+)"', chunk)
        if k: out[k.group(1)] = '<div class="stat">' + chunk
    return out

def summary_json():
    h = headline(); o = A.open_epoch(); st = A.status()
    return dict(live=is_live(), pill=pill(), as_of=st.get("as_of"), stale=st.get("stale"), tracker=tracker_html(score=False), feed=feed_rows(), cards=h,
                open_epoch=o, supply=st.get("supply"), holders=st.get("holders"), accounts=st.get("agents_joined"), **joins_fields())

def joins_fields():
    """Additive API fields: agent_joins_per_hour and the window it was measured over, and active_agents with its window (method: /about#home)."""
    r = A.joins_rate(); a = A.active_agents()
    act = dict(active_agents=a["active_agents"] if a else None,
               active_agents_window=dict(kind=a["window"], start_ts=a["start_ts"], end_ts=a["end_ts"], hours=a["hours"], segment=a["segment"],
                                         basis=a["basis"], source=a["source"]) if a else None)
    if not r: return dict(agent_joins_per_hour=None, agent_joins_per_hour_window=None, **act)
    return dict(**act, agent_joins_per_hour=r["agent_joins_per_hour"],
                agent_joins_per_hour_window=dict(kind=r["window"], hours=r["window_hours"], joins=r["joins"], end_ts=r["window_end"],
                                                 joining_from_ts=r.get("joining_from"), source=r.get("source"),
                                                 paused_until_ts=r["paused_until"], trailing_per_hour=r["trailing"]))


def epoch_cols():
    from . import scoresort as SS
    return [SS.Col("epoch", "#"), SS.Col(None, "Status"), SS.Col("close_ts", f"Closed ({TZ})"), SS.Col("paid", "Agents paid"), SS.Col("minted", "Minted"),
            SS.Col("burned", "Burned"), SS.Col("burn_pct", "Burn %"), SS.Col("median", "Median reward")]
EPOCH_SORTS = ("epoch", "close_ts", "paid", "minted", "burned", "burn_pct", "median")

def epochs_table(rows, link=True, qs=None, base=None):
    """Closes, newest first. qs and base: every header sorts the list (?sort=&dir=, server side; blanks last)."""
    from . import scoresort as SS
    by = SS.q(qs, "sort", "epoch"); by = by if by in EPOCH_SORTS else "epoch"; d = SS.page_dir(qs)
    rs = SS.sort_rows(list(rows), lambda r: r.get(by), "num", d, tie=lambda r: -r["epoch"])
    lk = SS.link_fn(base, "epoch", "#history", **({"segment": str(SG.selected())} if SG.archived() else {})) if base else None
    return table([], [[f'<a href="/epoch/{r["epoch"]}" class="mono hallk">{MK.hall_img(r, 24)}E{r["epoch"]}</a>', '<span class="tag ok">FINALIZED</span>' + CPZ.tag(r.get("pause")), utc(r["close_ts"]), intc(r["paid"]),
                   poa(r["minted"], mined=True), f'<span class="red">{num(r["burned"])}</span>', f'<span class="red">{r["burn_pct"]:.2f}%</span>' if r["burn_pct"] is not None else '<span class="dim">···</span>',
                   num(r["median"])] for r in rs], pri=(0, 4, 6), usd=(4, 5, 7), sort=(epoch_cols(), by, d, lk))

def raw_fields(extra):
    """Short scalar fields inline; long blobs collapsed behind a 'show raw' toggle."""
    short = {k: v for k, v in extra.items() if not isinstance(v, (dict, list)) and len(str(v)) <= 80}
    inline = "".join(f'<div class="rf"><span class="lbl">{E(k)}</span><code class="wrap">{E(str(v))}</code></div>' for k, v in short.items())
    raw = json.dumps(extra, indent=1)
    cut = " (first 20,000 characters)" if len(raw) > 20000 else ""
    return (inline + f'<details class="raw"><summary>Show raw JSON · {len(extra)} field{"s" if len(extra) != 1 else ""}{cut}</summary>'
            f'<pre class="wrappre">{E(raw[:20000])}</pre></details>')

def home_epochs(ep):
    """Closes on Home: when, Agents paid, minted, burned and the pour (the pool split, minted gold against burned slag)."""
    rows = list(reversed(ep[-6:]))
    def pour(r):
        pool = float(r.get("pool") or 0); m = 100 * float(r.get("minted") or 0) / pool if pool else 0
        t = f"Minted {m:.1f}%, burned {100 - m:.1f}%"
        return f'<span class="mpour" role="img" aria-label="{t}" title="{t}"><i style="width:{m:.1f}%"></i></span>'
    return table(["#", f"Closed ({TZ})", "Paid", "Minted", "Burned", "Pour"],
               [[f'<a href="/epoch/{r["epoch"]}" class="mono hallk" title="Epoch {r["epoch"]}, finalized">{MK.hall_img(r, 28)}E{r["epoch"]}</a>', utc(r["close_ts"], "%b %d %H:%M"), intc(r["paid"]),
                 f'<span class="num mined" title="{full(r["minted"])} POA">{compact(r["minted"], 1)}</span>',
                 f'<span class="num red" title="{full(r["burned"])} POA">{compact(r["burned"], 1)}</span>', pour(r)] for r in rows], cls="closes", pri=(0, 2, 3, 5))

def home_graders(n=5):
    """Graders on Home: the most aligned jurors with at least 10 settled seats (agents.graders, cached 300 s)."""
    g = [x for x in G.graders()["graders"] if x[1] >= 10]; nm = names()
    g = sorted(g, key=lambda x: (-x[3], -x[1]))[:n]
    if not g: return '<p class="empty">No settled grades yet</p>'
    return table(["Agent", "Settled", "Aligned"],
                 [[addr_link(a, nm, (6, 4)), intc(k), f'<span class="rate" aria-hidden="true"><i style="width:{r * 100:.0f}%"></i></span><span class="num">{r * 100:.1f}%</span>']
                  for a, k, al, r, *_ in g], cls="grs")

def home_sparks():
    """Sparkline series for the 4 home stats, from data POAScan already archives (no upstream calls)."""
    g = V3.growth_data(); u = V3.unlock_data()
    return dict(mined=g["supply"], accounts=g["agents"], holders=g["holders"], vest=u["past"] + [(time.time(), u["now"])], active=A.active_series())

HERO_KEYS = ("mined_hero", "circ", "accounts", "active", "holders")

def hero_stale():
    """1.26.157: why the Home headline numbers are not current, or None. Stale data is flagged, never shown as current: no
    fresh read of the live network for LIVE_S (5 min; Agents comes from /api/status, Active Agents from the tx archive the
    feed fills) or the node itself reports stale data. app.js applies the same rule live (snapshot live, stale and as_of)."""
    f = A.freshness()
    if f["state"] == "stale":
        t = f.get("fetched_at"); return f"Last read {_ui._ago(time.time() - t)} ago" if t else "No fresh read yet"
    if A.status().get("stale"): return "The node reports stale data"
    return None

def _hero_flag(stat_html, why):
    """Put a Stale tag (ui.flag, class hstale so app.js can clear it live) at the end of a stat card's label."""
    i = stat_html.find('<div class="sl">'); j = stat_html.find("</div>", i) if i >= 0 else -1
    if j < 0 or "hstale" in stat_html: return stat_html
    return stat_html[:j] + flag("Stale", why).replace('class="qtip sflag"', 'class="qtip sflag hstale"', 1) + stat_html[j:]

# ---------------- pages ----------------
def home():
    """Search, the Bench (open epoch and the last 24 min, bench.py), the headline row (Total mined, Circulating supply, Agents, Active
    Agents; method on /about#home), Holders and heights, then the Assay line beside Closes, Graders and the Pour, and a compact
    market tile. One representation per fact."""
    h = headline(); ep = A.epoch_rows(); sp = home_sparks()
    why = hero_stale(); asof = A._ts(A.status().get("as_of")) or ""
    if why: h = dict(h, **{k: _hero_flag(h[k], why) for k in HERO_KEYS if k in h})
    from . import milestones as MS   # Home Total Agents sparkline: only milestones that name it (milestones.json spark_ids)
    smk = {"accounts": MS.events("home-agents"), "active": MS.events("home-active"), "holders": MS.events("home-holders")}   # 1.26.175: the genesis cut ticks the sparklines it affects, no break
    kpis = "".join(pop(spark_in(h[k], sp.get(sk), smk.get(sk)), ck)
                   for k, sk, ck in (("mined_hero", "mined", "mined"), ("circ", "vest", "circ"), ("accounts", "accounts", "agents"), ("active", "active", "active")))
    more = pop(spark_in(h["holders"], sp.get("holders"), smk["holders"]), "holders") + h["height"] + h["checkpoint"]   # every stat with a chart opens the pop-out
    body = f'''<h1 class="sr-only">Proof of Agent explorer</h1>
<section class="shero">{search_form("hsearch", "hero")}</section>
<section id="tracker" class="card benchc" aria-label="Open epoch">{tracker_html()}</section>
<section class="stats four kpis" aria-label="Headline numbers" data-asof="{asof}"{' data-stale="1"' if why else ''}>{kpis}</section>
<section class="stats three kstats kmore krow" aria-label="Holders and heights">{more}</section>
<div class="grid2 hgrid">
{card(ICON_FEED + 'Assay line', '<div class="fhd" aria-hidden="true"><span>Type</span><span>Agent</span><span>Seals</span><span>Age</span></div>' + f'<div id="feed" class="feed">{feed_rows(16)}</div>', '<a href="/chain/txs" class="more">All txs →</a>', cls="assay")}
<div class="side">
{card(ICON_CUBE + "Closes", f'<div data-liverows="closes-home" data-top="{ep[-1]["epoch"] if ep else ""}">{home_epochs(ep) if ep else '<p class="empty">No closes yet</p>'}</div>', '<a href="/chain" class="more">Full list →</a>')}
{card(ICON_SEAL + "Graders", home_graders(), '<a href="/governance?tab=graders" class="more">All graders →</a>', cls="hgr")}
{card(ICON_FLAME + "Pour", BN.pour_html(ep[-1] if ep else None), (f'<a class="lbl" href="/epoch/{ep[-1]["epoch"]}">Epoch {ep[-1]["epoch"]}</a>' if ep else "") + PR.ask([PR.BURN]), cls="bmcard pourc")}
</div>
</div>
{card(V2.ICON_SWAP + "Market", f'<div class="stats four">{X.market_mini()}{X.price_stats_html()}</div>', X.usd_src() + f'<a class="more mswap" href="{E((X.SC.status() or {}).get("url") or "https://poaswap.io/start")}" target="_blank" rel="noopener noreferrer"><img src="/static/poaswap-mark.svg?v=1" width="14" height="14" alt="" aria-hidden="true">POASwap →</a>', cls="mtile")}'''
    return page("Proof of Agent explorer", body, "/")

def upgrade_live():
    """Snapshot fields for the /upgrade route list (1.26.181: the Home strip is gone; the header status note carries Upgrading)."""
    from . import maint as M
    if not M.state()["active"]: return dict(routes=M.route_display() if M.complete() else {}, upsig="")   # /upgrade route tags stay live after completion
    return dict(routes=M.route_display(), upsig=V2.upgrade_sig())

def txs(qs):
    pg_raw = (qs.get("page", ["1"])[0] or "1").strip(); typ = qs.get("type", [""])[0]; per = 50
    page_n = int(pg_raw) if pg_raw.isdigit() and len(pg_raw) <= 9 else 1   # not a page number: the first page
    where, args = ("WHERE type=?", (typ,)) if typ else ("", ())
    total = db.q1(f"SELECT COUNT(*) AS n FROM txs {where}", args)["n"]
    page_n = max(1, min(page_n, max(1, math.ceil(total / per))))
    rows = db.q(f"SELECT * FROM txs {where} ORDER BY ts DESC LIMIT ? OFFSET ?", args + (per, (page_n - 1) * per)); nm = names()
    # 1.26.201: headers sort the 50 rows on this page (Type, Amount, Epoch, Attest., Time); pages stay newest first, so a
    # sort never makes SQLite order the whole archive (a full scan per crawler hit on the 1 GB machine)
    from . import scoresort as SS
    tcols = TX_COLS
    def _amt(t):
        try: return float(t["amount"])
        except (TypeError, ValueError): return None
    tv = {"time": lambda t: t["ts"], "type": lambda t: SS.text_key(type_name(t["type"])), "amount": _amt, "epoch": lambda t: t["epoch"] if t["epoch"] is not None else G.epoch_of_ts(t["ts"]), "atts": lambda t: t["atts"]}
    rows, tspec = SS.table_sort(qs, tcols, rows, tv, "time", "/chain/txs", "", keep={"type": typ, "page": str(page_n) if page_n > 1 else ""})
    tsort, tdir = tspec[1], tspec[2]
    types = db.q("SELECT type, COUNT(*) AS n FROM txs GROUP BY type ORDER BY n DESC")
    chip = lambda t: f'<a href="/chain/txs?type={E(t["type"])}" class="chip {"on" if t["type"]==typ else ""}" title="{E(TYPE_TIP.get(t["type"], t["type"]))}">{E(type_name(t["type"]))} <small>{t["n"]:,}</small></a>'
    top = types[:5]; rest = types[5:]
    if typ and any(t["type"] == typ for t in rest): top, rest = top + [t for t in rest if t["type"] == typ], [t for t in rest if t["type"] != typ]
    more = (f'<details class="chipmore"><summary class="chip">More <small>{len(rest)}</small></summary><div class="chipmenu">{"".join(chip(t) for t in rest)}</div></details>') if rest else ""
    tabs = f'<a href="/chain/txs" class="chip {"on" if not typ else ""}">All</a>' + "".join(chip(t) for t in top) + more
    sq = (f"&sort={tsort}" if tsort != "time" else "") + ("&dir=asc" if tdir == "asc" else "")
    tb = tx_table(rows, nm, sort=tspec)
    if page_n == 1 and not typ and not sq and rows: tb = f'<div data-liverows="txs" data-top="{E(rows[0]["id"])}">{tb}</div>'   # new txs fade in at the top (4.3)
    pages = max(1, math.ceil(total / per))
    q = (f"&type={E(typ)}" if typ else "") + sq
    pg = f'<div class="pager"><a href="?page=1{q}">« First</a><a href="?page={max(1,page_n-1)}{q}">‹ Prev</a><span>Page {page_n:,} of {pages:,}</span><a href="?page={min(pages,page_n+1)}{q}">Next ›</a><a href="?page={pages}{q}">Last »</a></div>'
    body = card(f"Transactions · {total:,}", f'<div class="chips scroll">{tabs}</div>{tb}{pg}', f'<a class="more" href="/api/txs.csv?type={E(typ)}">CSV →</a>')
    return page("Transactions", '<div class="sechead"><h1 class="sr-only">Transactions</h1>' + chain_tabs("/chain/txs") + '</div>' + body, "/txs")

def _tx_cols():
    from . import scoresort as SS
    return [SS.Col(None, "Tx hash"), SS.Col("type", "Type", "text"), SS.Col(None, "From"), SS.Col(None, "To"), SS.Col("amount", "Amount"),
            SS.Col("epoch", "Epoch"), SS.Col("atts", "Attest."), SS.Col(None, "Final"), SS.Col("time", f"Time ({TZ})")]
TX_COLS = _tx_cols()

def tx_table(rows, nm, sort=None):
    return table([] if sort else ["Tx hash", "Type", "From", "To", "Amount", "Epoch", "Attest.", "Final", f"Time ({TZ})"],
               [[tx_link(t["id"], (6, 4)), badge(t["type"]), addr_link(t["from_addr"], nm, (6, 4)), addr_link(t["to_addr"], nm, (6, 4)), E(t["amount"] or "···"),
                 "E" + E(str(t["epoch"] if t["epoch"] is not None else G.epoch_of_ts(t["ts"]))), dots(t["atts"], t["k"] or 5), seal(t["final"]), utc(t["ts"])] for t in rows], pri=(0, 1, 2), sort=sort)

def live_rows(kind):
    """/fragment/rows: the newest rows of a live table as bare <tr>s, from the local archive (no upstream call).
    The client asks only after a WS snapshot shows a new tx or close, and keeps only rows it does not have."""
    if kind == "txs": h = tx_table(db.q("SELECT * FROM txs ORDER BY ts DESC LIMIT 10"), names())
    elif kind == "closes-home": h = home_epochs(A.epoch_rows())
    elif kind == "closes": h = epochs_table(A.epoch_rows()[-5:])
    else: return None
    m = re.search(r"<tbody>(.*)</tbody>", h, re.S); return m.group(1) if m else ""

def _sig_badge(d):
    """G0 notice, release and declaration txs: the Signed / Unverified / Invalid badge (signed.py)."""
    from . import signed as _SIG
    return _SIG.badge(_SIG.for_detail(d))

def tx_unavailable(tid, paused):
    """No archived copy and no node read: a clean state with the txid and a retry link, never an error page."""
    why = ST.HALT_NONE if paused else "Not available right now: minepoa.com is busy. POAScan has not indexed this transaction yet."
    body = (f'<p>{E(why)}</p><p class="mono" style="word-break:break-all">{E(tid)}</p>'
            f'<p><a class="more" href="/tx/{E(tid)}" rel="nofollow">Try again later</a></p>')
    return page("Tx not available", card("Transaction", na(body), id="txna"), "/txs")

def tx(tid):
    err = None; busy = False; fallback = False
    skip = re.fullmatch(r"[0-9a-f]{64}", tid or "") is not None and not I.route_open("tx_lookup") and bool(db.q1("SELECT 1 AS x FROM txs WHERE id=?", (tid,)))   # 1.26.219
    try: d = I.get_tx_detail(tid, node=not skip)
    except I.Missing as e: d = I.get_tx_detail(tid, allow_fetch=False); err = str(e)
    except Exception as e: d = I.get_tx_detail(tid, allow_fetch=False); err = str(e); busy = True
    paused = I.halted(I.TX_TPL) is not None
    if (not d or not d.get("id")) and re.fullmatch(r"[0-9a-f]{64}", tid or ""):
        row = db.q1("SELECT * FROM txs WHERE id=?", (tid,))   # node busy: the archived row still says what happened
        if row: d = dict(row, body={}, served_from="archive", served_as_of=row["last_seen"] or row["first_seen"]); fallback = True
    if not d or not d.get("id"):
        if busy or paused: return tx_unavailable(tid, paused)
        return page("Tx not found", card("Transaction", na(f"No transaction <code>{E(tid)}</code> on poa-mainnet-1.")), "/txs")
    nm = names(); b = d.get("body") or {}
    parents = "".join(f'<div>{tx_link(p, (12, 10))}</div>' for p in b.get("parents", [])) or "···"
    cp = d.get("checkpointed") or {}
    ep = d.get("epoch") if d.get("epoch") is not None else b.get("epoch", G.epoch_of_ts(d.get("ts") or 0))
    # Status, type, epoch and attestations live in the summary line above the card; the rows keep the raw facts.
    rows = [("Transaction hash", f'<span class="mono">{E(d["id"])}</span>{copy(d["id"])}'),
            ("Timestamp", lt(d.get("ts"), "dts") + " · " + rel(d.get("ts"))), ("From", addr_link(d.get("from_addr"), nm, (48, 0)) if d.get("from_addr") else "···"),
            ("To", addr_link(d.get("to_addr"), nm, (48, 0)) if d.get("to_addr") else '<span class="na">···</span>'),
            ("Amount", E(d.get("amount") or "···")),
            ('<span title="Highest finalized (checkpointed) height that covers this transaction">Finalized height</span>',
             (f'<b class="mono">{cp.get("height"):,}</b>' if cp.get("height") else "···" if d.get("detail_source") else '<span class="na">not yet</span>')),
            ("Parents", parents), ("Nonce", E(str(b.get("nonce", "···")))), ("Chain id", E(b.get("cid", "···"))), ("Signature", f'<span class="mono wrap">{E(short(b.get("sig",""), 24, 12))}</span>{_sig_badge(d)}')]
    if b.get("answer"): rows.append(("Answer", f'<blockquote>{E(b["answer"])}</blockquote>'))
    skip = ("type", "parents", "sig", "nonce", "cid", "answer", "from", "ts", "epoch")
    sw = X.tx_rows(b, nm) if b.get("offer") or b.get("proof") else []
    if sw:
        rows[3:5] = [r for r in sw if r[0] in ("To", "Amount")] or rows[3:5]
        rows += [r for r in sw if r[0] not in ("To", "Amount")]; skip += ("offer", "proof")
    rc = RC.receipt(tid, row={"id": d["id"], "type": d.get("type"), "from_addr": d.get("from_addr"), "epoch": d.get("epoch"), "ts": d.get("ts"), "final": d.get("final")}) if d.get("type") == "challenge" else None
    if rc and rc.get("seed"): skip += ("seed",)   # the Receipt card carries it
    extra = {k: v for k, v in b.items() if k not in skip}
    if extra: rows.append(("Fields", raw_fields(extra)))
    rows = [(k, v) for k, v in rows if not _empty(v)]
    kv = "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in rows)
    rch = card("Receipt", RC.card_html(rc), f'<a class="more" href="/api/v1/receipt/{E(tid)}">API →</a>') if rc else ""
    ts_ = I.tx_source(d)   # 1.26.219: which copy this page shows and when it was read
    kv += (f'<p class="cov dim small">Source: {E(ts_["source_label"])}' + (f' · as of {lt(d.get("served_as_of"), "dt")}' if d.get("served_as_of") else "")
                              + ' · <a href="/about#tx-source">Method</a></p>')
    return page("Tx " + short(tid), tx_summary(d, nm, ep) + card("Transaction", kv, PR.ask([PR.explain_tx(tid)]) + f'<a class="more" href="https://minepoa.com/api/explorer/tx/{E(tid)}" rel="nofollow noopener noreferrer">Source JSON ↗</a>') + rch, "/txs")

VERB = {"challenge": "submitted an answer", "grade-sealed": "graded an answer", "attest-batch": "attested a batch", "join": "joined",
        "chains-update": "linked a wallet"}

def who(a, nm):
    """Agent name linking to its LabLeak profile, or the short address linking to /address when it has no name."""
    if not a: return "Someone"
    n = (nm or {}).get(a)
    return name_link(n, a, cls="") if n else f'<a class="mono" href="/address/{E(a)}" title="{E(a)}">{E(short(a))}</a>'

def tx_summary(d, nm, ep):
    """One line that says what happened: 'Emberwick submitted an answer · Epoch 9 · Pending · 4 of 5 attestations'."""
    t = d.get("type"); a = d.get("from_addr")
    if t in ("send", "transfer") or (d.get("amount") and d.get("to_addr") and t not in VERB):
        what = f'sent {E(str(d.get("amount")))} POA to {who(d.get("to_addr"), nm)}' if d.get("amount") else f'sent a {E(type_name(t).lower())}'
    else: what = VERB.get(t, f"sent a {E(type_name(t).lower())}")
    if t == "join" and d.get("invited_by"): what += f' via {who(d["invited_by"], nm)}'
    k = d.get("k") or 5; at = int(d.get("atts") or 0)
    st = '<span class="ok">Final</span>' if d.get("final") else "Pending"
    parts = [f'{who(a, nm)} {what}', f'<a href="/epoch/{E(str(ep))}">Epoch {E(str(ep))}</a>' if str(ep).isdigit() else "", st, f"{min(at, k)} of {k} attestations"]
    return '<h1 class="txsum">' + " · ".join(x for x in parts if x) + "</h1>"

KIN_SHOW = 8   # member links shown inline on the Kin row; the rest are in /api/v1/kin/<group_id>
def kin_row(a, k, nm):
    """The address page Kin row: status, label and the other members, one line. Method on /about#kin."""
    if not k: return "···"
    tag = '<span class="tag ok">ACTIVE</span>' if k["status"] == "active" else '<span class="tag">INACTIVE</span>'
    others = [m for m in k["members"] if m != a]
    links = " ".join(agent(m, names=nm) for m in others[:KIN_SHOW])
    more = f' <a href="/api/v1/kin/{E(k["group_id"])}">+{len(others) - KIN_SHOW}</a>' if len(others) > KIN_SHOW else ""
    return f'{tag} <a href="/about#kin" title="Kin group {E(k["group_id"][:12])}">{E(k["label"] or "kin")}</a> · {links}{more}'

def _empty(v):
    """A key/value row with nothing to say (a bare ··· placeholder) is left out rather than shown empty."""
    return re.sub(r"<[^>]+>", "", str(v)).strip() in ("", "···", "-")

ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")
# Per-agent minepoa.com fetches: fresh for ADDR_TTL s, then served stale for up to ADDR_STALE s while one
# background refresh runs. One upstream call per address at a time; the cache is bounded. An address the node knows
# nothing about (zero balance, no txs) stays fresh for ADDR_EMPTY_TTL s, so made-up addresses cost one read per 10 min.
# Every read goes through indexer.fetch_ondemand (format check, negative cache, per-client and global budget).
ADDR_TTL, ADDR_STALE, ADDR_MAX, ADDR_EMPTY_TTL = 300, 1800, 2000, 600   # 1.26.202: 60 -> 300 s (API polling drove ~156 lookups an hour)
_addr_cache, _addr_inflight, _addr_lock = {}, {}, threading.Lock()

def _addr_load(a, crawler=None):
    if crawler is not None: I.CLIENT.crawler = crawler   # a background refresh keeps the request's crawler flag
    try:
        d = I.fetch_ondemand(f"/api/explorer/address/{a}", I.ADDR_EP, a)
        empty = isinstance(d, dict) and not d.get("txs") and float(d.get("balance") or 0) == 0
        with _addr_lock:
            now = time.time(); _addr_cache[a] = (now + (ADDR_EMPTY_TTL - ADDR_TTL if empty else 0), d, now)   # (freshness stamp, copy, read at)
            if len(_addr_cache) > ADDR_MAX:
                for k, _ in sorted(_addr_cache.items(), key=lambda kv: kv[1][0])[:len(_addr_cache) - ADDR_MAX]: _addr_cache.pop(k, None)
        if isinstance(d, dict): I.upsert_txs(d.get("txs", []), "explorer/address")
        return d, None
    except Exception as e:
        return None, str(e)
    finally:
        with _addr_lock: ev = _addr_inflight.pop(a, None)
        if ev: ev.set()

ROSTER_FRESH_S = 1200   # 1.26.212: the agent list (every 15 min) is fresh enough to stand in for the address read
_roster_skips = [0, 0]  # [skipped, read] since boot, for /api/v1/health

def roster_covers(a, now=None):
    """1.26.212: True when the stored agent list row answers for this address without a minepoa.com address read: the row
    has a balance, was written by the agent list in the current segment within ROSTER_FRESH_S, and nothing since then could
    have moved the balance (no value moving tx from or to the address, no close). The page and API then show that row with
    its own as-of time and source (freshness tags unchanged)."""
    now = now or time.time()
    acc = db.q1("SELECT balance_s, balance, last_seen FROM accounts WHERE addr=?", (a,))
    if not acc or (acc["balance_s"] is None and acc["balance"] is None) or not acc["last_seen"]: return False
    sat = int(acc["last_seen"])
    if now - sat > ROSTER_FRESH_S or sat < (SG.BY_N[SG.CURRENT].get("start_ts") or 0): return False
    if db.q1("SELECT 1 AS x FROM txs WHERE (from_addr=? OR to_addr=?) AND ts>=? AND type NOT IN ('challenge','grade-sealed','attest-batch','join') LIMIT 1", (a, a, sat - 60)): return False
    last_close = max((int(e.get("ts") or 0) for e in A.segment_closes(SG.CURRENT)), default=0)
    return last_close < sat - 60

def address_read(a):
    """(copy, error, read_at): the minepoa.com address copy and when it was read. A cached copy read more than
    ADDR_STALE s ago is dropped and never returned, so a failed or refused live read cannot surface an old balance.
    1.26.212: with no fresh cached copy and the agent list row covering the address (roster_covers), no read is made:
    (None, None, None), and address_balance shows the agent list row."""
    now = time.time()
    with _addr_lock:
        hit0 = _addr_cache.get(a)
    if not (hit0 and now - hit0[0] < ADDR_TTL):
        try: cov = roster_covers(a, now)
        except Exception: cov = False
        if cov: _roster_skips[0] += 1; return None, None, None
        _roster_skips[1] += 1
    with _addr_lock:
        hit = _addr_cache.get(a)
        if hit and now - hit[2] >= ADDR_STALE: _addr_cache.pop(a, None); hit = None   # too old to show: drop it
        ev = _addr_inflight.get(a); age = now - hit[0] if hit else None
        if hit and age < ADDR_TTL: return hit[1], None, hit[2]
        mine = ev is None
        if mine: ev = _addr_inflight[a] = threading.Event()
    if hit and age < ADDR_STALE:                      # stale-while-revalidate
        if mine: threading.Thread(target=_addr_load, args=(a, I.crawler()), daemon=True).start()
        return hit[1], None, hit[2]
    if not mine:                                      # someone else is fetching this address: wait for it
        ev.wait(I.ONDEMAND_TIMEOUT + 2)
        with _addr_lock: hit2 = _addr_cache.get(a)
        if hit2 and hit2 is not hit: return hit2[1], None, hit2[2]
        return (hit[1] if hit else None), "upstream fetch failed", (hit[2] if hit else None)
    d, err = _addr_load(a)
    if err: return (hit[1] if hit else None), err, (hit[2] if hit else None)
    with _addr_lock: h = _addr_cache.get(a)
    return d, None, (h[2] if h else now)

def fetch_address(a):
    d, err, _ = address_read(a); return d, err

def bal_asof(bb):
    """The fixed point a balance from an earlier segment's source stands at: "As of checkpoint 44003", else "As of Segment 1"."""
    if not bb.get("stale") or not bb.get("segment") or bb["segment"] == SG.CURRENT: return None
    return f"As of checkpoint {bb['as_of_checkpoint']}" if bb.get("as_of_checkpoint") is not None else f"As of {SG.BY_N[bb['segment']]['label']}"

ROSTER_ZERO_GUARD_S = 1800   # 1.26.166: an address read of 0 never beats a nonzero agent list row younger than this

def _explorer_cp(d):
    """The checkpoint minepoa.com's address read stands at (balance_as_of.checkpoint_height), or None."""
    b = d.get("balance_as_of") if isinstance(d, dict) else None
    v = b.get("checkpoint_height") if isinstance(b, dict) else None
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

def roster_cp(sat):
    """The checkpoint the agent list stood at when the row was written (agents job, same run as last_seen), or None."""
    b, ts = db.get_blob("agents_cp")
    if not isinstance(b, dict) or not sat or abs(int(b.get("ts") or 0) - int(sat)) > 600: return None
    v = b.get("checkpoint"); return int(v) if isinstance(v, (int, float)) else None

def _sent_since(a, ts):
    """True when the archive holds a value moving tx from a (transfer, swap) at or after ts: a real sweep to 0."""
    if not a: return False
    return bool(db.q1("SELECT 1 AS x FROM txs WHERE from_addr=? AND ts>=? AND type NOT IN ('challenge','grade-sealed','attest-batch','join') LIMIT 1", (a, int(ts))))

def _explorer_wins(live, stored, sat, at, xcp, now=None, addr=None):
    """1.26.166: the fresher copy by the checkpoint each reflects, not by read time. The address read stands at its
    balance_as_of checkpoint; the agent list is live, so at least at the checkpoint current when it was read. A 0 from
    the address read never overrides a nonzero agent list row under 30 min old (a recruit the read node had not caught up on),
    unless the archive holds a value moving tx from the address since that row (a real sweep)."""
    now = now or time.time()
    try: lv, sv = float(live), float(stored)
    except (TypeError, ValueError): lv = sv = None
    if lv == 0 and sv and now - (sat or 0) < ROSTER_ZERO_GUARD_S and not _sent_since(addr, (sat or 0) - 60): return False
    rcp = roster_cp(sat)
    if xcp is not None and rcp is not None: return xcp > rcp
    return (at or 0) >= sat

def balance_tag(bb):
    """(asof_text, tip) for the Balance stat: an earlier segment's fixed point is flagged Stale; an address read behind
    the current checkpoint is flagged Stale "As of checkpoint N"; at the current checkpoint the label tooltip says so."""
    t = bal_asof(bb)
    if t: return t, None
    if bb.get("source") == "explorer/address" and bb.get("as_of_checkpoint") is not None:
        cur = A.networks().get("checkpoint_height")
        txt = f"As of checkpoint {bb['as_of_checkpoint']}"
        return (txt, None) if isinstance(cur, int) and bb["as_of_checkpoint"] < cur else (None, txt)
    return None, None

def address_balance(a, d=None, at=None, acc=None):
    """The newer of two balance copies: the minepoa.com address read (d, read at `at`) and the stored agent-list row
    (accounts, written by the 15 min agents job at last_seen). Returns dict(balance (text), as_of (unix s), source)."""
    if acc is None: acc = db.q1("SELECT balance_s, balance, last_seen FROM accounts WHERE addr=?", (a,))
    live = (d or {}).get("balance") if isinstance(d, dict) else None
    stored = None
    if acc: stored = acc["balance_s"] if acc["balance_s"] is not None else (None if acc["balance"] is None else f'{float(acc["balance"]):.6f}')
    sat = acc["last_seen"] if acc and stored is not None else None
    xs = SG.source_segment("explorer")   # the segment minepoa.com's explorer serves (segments config sources)
    xcp = _explorer_cp(d)
    if xs != SG.CURRENT and xcp is not None and xcp > (SG.checkpoint_of(xs, db.get_blob("networks")[0]) or 0):
        xs = SG.CURRENT   # 1.26.166: the copy names a checkpoint past that segment's final one, so it is the current segment's state
    if xs != SG.CURRENT:   # explorer state is that segment's final checkpoint: the agent list (current segment) wins when present
        st0 = (SG.BY_N[SG.CURRENT].get("start_ts") or 0)
        if stored is not None and (sat or 0) >= st0: return dict(balance=stored, as_of=sat, source="agents", stale=False, as_of_checkpoint=None, segment=SG.CURRENT)
        if live is not None:
            return dict(balance=live, as_of=int(at) if at else None, source="explorer/address", stale=True,
                        as_of_checkpoint=SG.checkpoint_of(xs, db.get_blob("networks")[0]), segment=xs)
        if stored is not None:   # last seen in an earlier segment's agent list, not in the current one
            return dict(balance=stored, as_of=sat, source="agents", stale=True, as_of_checkpoint=None, segment=SG.of_ts(sat))
        return dict(balance=None, as_of=None, source=None, stale=False, as_of_checkpoint=None, segment=None)
    if live is not None and (stored is None or not sat or _explorer_wins(live, stored, sat, at, xcp, addr=a)):
        return dict(balance=live, as_of=int(at) if at else None, source="explorer/address", stale=False, as_of_checkpoint=xcp, segment=SG.CURRENT)
    if stored is not None:
        old = (sat or 0) < (SG.BY_N[SG.CURRENT].get("start_ts") or 0)   # last seen in an earlier segment's agent list only
        return dict(balance=stored, as_of=sat, source="agents", stale=old, as_of_checkpoint=None, segment=SG.of_ts(sat) if old and sat else SG.CURRENT)
    return dict(balance=None, as_of=None, source=None, stale=False, as_of_checkpoint=None, segment=None)

_chains = {"ts": None, "v": frozenset()}
def chains_linked():
    """Addresses with a linked external wallet, from the chains blob; parsed again only when the indexer stores a new copy."""
    r = db.q1("SELECT ts, length(json) AS n FROM blobs WHERE kind='chains'"); ts = (r["ts"], r["n"]) if r else None
    if ts != _chains["ts"]:
        _chains["v"] = frozenset((db.get_blob("chains")[0] or {}).keys()); _chains["ts"] = ts
    return _chains["v"]

def live_known(d):
    """minepoa's explorer answers any well-formed address with balance 0 and no txs; only a tx, a balance or a vault makes it real."""
    if not isinstance(d, dict): return False
    try: b = float(d.get("balance") or 0)
    except (TypeError, ValueError): b = 0
    return bool(d.get("txs") or b > 0 or d.get("vault_pub"))

NF_LINKS = '<p class="cov small"><a href="/help?address={a}">Why am I not earning?</a> · <a href="/start">Sign up</a> · <a href="/agents/top">Find an Agent</a></p>'

def address(a):
    if not ADDR_RX.match(a): return 404, page("Bad address", card("Address", na("That is not a poa1… address.")), "/")   # malformed: 404, never 200 or 500
    d, err, at = address_read(a); nm = names(); p = G.profile(a)
    rb = p["rewards"]; acc = db.q1("SELECT * FROM accounts WHERE addr=?", (a,))
    bb = address_balance(a, d, at, acc); bal = float(bb["balance"]) if bb["balance"] is not None else None; btag = balance_tag(bb)
    if err and bal is None:   # minepoa.com's read failed and nothing is stored: the fast index's copy, tagged with its time
        from . import fastindex as FX
        fa = FX.address(a)
        try: bal = float(fa["balance"]) if fa and fa.get("balance") not in (None, "") else None
        except (TypeError, ValueError): bal = None
        if bal is not None: btag = ("From the fast index", None)
    n = A.open_gkey()   # rewards are keyed by lifetime close number (segments.gkey): vesting runs across the genesis cut
    sp, lk = A.vest_split(rb, n); early = any(k < SG.offset(SG.CURRENT) for k in A.confirmed(rb))   # carried rewards: bounds while unconfirmed
    rsum = sum(rb.values()); est = a in A.established_set(); cvn = HI.coverage(a)
    vest_note = "Derived from per-epoch rewards × the 100-epoch vesting schedule (matches /api/hosted/me exactly on a test agent)."
    from . import rewardbasis as RB
    rbs = RB.basis(bal, rsum, bb.get("as_of"), a, rb); rtag = RB.tag_text(rbs)   # 1.26.216: the balance is ahead of the held close records
    if rtag: vest_note += f" <b>Balance is ahead of these figures by {full(rbs['balance_ahead_by'])} POA</b>: {E(rbs['reason'])}. Shown as of the close they stand at, not re-split."
    elif bal is not None and abs(bal - rsum) > 0.01: vest_note += f" <b>Balance differs from reward sum by {full(bal - rsum)} POA</b> (transfers or swaps; those are spendable immediately), so the split may be off."
    cen = p["census"]; fam = p["family"]
    ops = G.operators()
    # Address, balance, the split, total rewards, name and streak sit in the header; these rows add what the header does not.
    kv = [("Established", ('<span class="tag ok">YES</span>' if est else '<span class="tag">NO</span>')),
          ("Forum posts / comments", f'{p["forum_posts"]} / {p["forum_comments"]}' if p["forum_name"] else "···"),
          ("Label", E((p["label"] or {}).get("label") or "···")),
          ("Custody", E((p["label"] or {}).get("custody") or "···")), ("External wallet", "linked" if a in chains_linked() else "···"),
          ("Model / Harness", (f'{E(cen["eco"])}{" · "+E(cen["detail"]) if cen.get("detail") else ""} / {E(", ".join(cen["harness"]))}' if cen else "···")),
          ("Kin", kin_row(a, KN.kin(a), nm)),
          ("Nonce", nonce_txt(cvn).split(" ", 1)[1] if cvn.get("indexed_sent") else "···"),
          ("Family size", str(fam[1]) if fam else "···"), ("Family root", addr_link(fam[0], nm) if fam and fam[1] > 1 else "···"),
          ("Longest run", f'{p["streak"][0]} epochs' if p["streak"][0] else "···"), ("Epochs answered", ", ".join("E"+str(k) for k in p["answered"]) or "···"),
          ("Answers passed / juried", f'{sum(1 for x in p["settled"] if x[2])} / {sum(1 for x in p["settled"] if x[3] != "expired_no_jury")}'
                                + (f' <span class="dim">· {n} expired, no jury</span>' if (n := sum(1 for x in p["settled"] if x[3] == "expired_no_jury")) else "")), ("Jury aligned / seats", f'{sum(1 for x in p["jury"] if x[1])} / {len(p["jury"])}'),
          ("Grades served", f'{p["served"]:,}'), ("Bug + proposal posts", str(len(p["builder_posts"])) if p["builder_posts"] else "···"), ("G0 mentions", str(p["credit"]) if p["credit"] else "···")]
    from . import governance as GV
    srow = GV.scores()["rows"].get(a)   # POAScan's Score and governance facts (cached 300 s)
    shown = {"Established", "Model / Harness"} | ({"Answers passed / juried", "Jury aligned / seats"} if srow else set())   # the header tags and the Score card carry these
    kvh = "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in kv if not _empty(v) and k not in shown)
    eps = sorted(rb.items())
    rew = bars([(SG.ep_label(k), [v]) for k, v in eps], colors=("gold",)) if eps else '<p class="na">No rewards yet.</p>'
    rew += table(["Epoch", "Reward"], [[f'<a href="{SG.ep_href(k)}">{SG.ep_label(k)}</a>' + (' <span class="tag warn">Unconfirmed</span>' if SG.unconfirmed_g(k) else ""), poa(v, mined=True, dec=4)] for k, v in reversed(eps)], usd=(1,))
    qs = getattr(REQ, "qs", {}) or {}
    typ = qs.get("type", [""])[0] or ""
    tab = qs.get("tab", [""])[0] or ("txs" if typ else "overview")
    tab = tab if tab in ("overview", "timeline", "rewards", "txs", "grading", "governance") else "overview"
    warn = '<p class="note warn">Live lookup failed · archived data</p>' if err else ""
    nmx = nm.get(a) or p["forum_name"]
    head = (PF.head(a, nmx, addr_meta(a, bal, p), PF.tags(est, (srow or {}).get("level"), cen, a), X.usd_src()) +
            f'<div class="stats eight">{stat("Balance", poa(bal, mined=True) + X.usd_of(bal) if bal is not None else "···", asof_text=btag[0], tip=btag[1])}{stat("Total rewards", poa(rsum, mined=True) + X.usd_of(rsum), asof_text=rtag, flag_html=flag("Unconfirmed", "Includes Unconfirmed rewards") if any(SG.unconfirmed_g(k) for k in rb) else "")}'
            f'{stat("Spendable", poa(sp) + X.usd_of(sp), asof_text=rtag, flag_html=A.carry_flag("circ") if early else "")}{stat("Locked", poa(lk) + X.usd_of(lk), asof_text=rtag, flag_html=A.carry_flag("locked") if early else "")}</div>')
    tc = HI.type_counts(a); ntx = sum(tc.values()); ng = HI.assignments(a, None, 1)["assignments"]
    tabs = [("overview", "Overview", None), ("timeline", "Timeline", None), ("rewards", "Rewards", len(eps)), ("txs", "Transactions", ntx), ("grading", "Grading", ng), ("governance", "Governance", None)]
    nav = '<nav class="chips atabs scroll" aria-label="Address sections">' + "".join(
        f'<a href="/address/{E(a)}{"" if k == "overview" else "?tab=" + k}" class="chip {"on" if k == tab else ""}"{" aria-current=\"page\"" if k == tab else ""}>{n}{f" <small>{c:,}</small>" if c else ""}</a>'
        for k, n, c in tabs) + f'<a href="/help?address={E(a)}" class="chip ecchip">Earn check</a></nav>'
    # 1.26.194: a well-formed address with nothing on chain or in the archive (no tx in any segment, no rewards, no account
    # row, no live read, no standing, seats or forum record) is a 404 not-found state, never an empty 0 POA Agent page
    known = (ntx or rb or acc or live_known(d) or est or p.get("jury") or p.get("settled") or p.get("served") or p.get("answered")
             or p.get("forum_name") or ng)
    if not known:   # an Agent established once (genesis import, added or removed at a close) is a record too
        try: known = (G.established_history(a) or {}).get("basis") not in (None, "none")
        except Exception: known = True   # never 404 a real Agent on a read error
    if not known:
        body = (na(f"No Agent at <code>{E(short(a, 10, 6))}</code> in POAScan's archive. Addresses are case sensitive; a new join shows within a few minutes.")
                + NF_LINKS.format(a=E(a)))
        return 404, page("Address not found", '<div class="sechead"><h1>Address</h1></div>' + card("Not found", body, cls="nfc"), "/")
    if tab == "timeline":
        from . import timeline as TL
        main = TL.tab_html(a)
    elif tab == "rewards":
        trk, trk_sched = V3.reward_tracker(a, p)
        main = card(ICON_CUBE + "Tracker", trk_sched + trk) + card("Per epoch", rew, X.usd_toggle(), id="rewards")
    elif tab == "txs": main = history_card(a, typ)
    elif tab == "grading": main = grading_card(a) or card("Assignments", na("No grading assignments for this Agent yet."), id="grading")
    elif tab == "governance":
        from . import governance as GV
        main = GV.agent_tab(a, qs)
    else:
        itree, n_inv = V3.invite_tree(a); rl = RC.for_address(a, 50)
        rcpt = card(f"Answers · {len(rl)}", RC.list_html(rl), f'<a class="more" href="/api/v1/receipts?address={E(a)}">API →</a>') if rl else ""
        main = (PF.overview(a, srow, [(SG.ep_label(k), [v]) for k, v in eps], GV.score_tip()) + card("Profile", warn + kvh, PR.ask([PR.addr_rewards(a), PR.addr_send(a), PR.addr_invites(a)]) + f'<a class="more" href="https://minepoa.com/api/explorer/address/{E(a)}" rel="nofollow noopener noreferrer">Source JSON ↗</a>')
                + __import__("poascan.walletview", fromlist=["x"]).binding_card(a) + established_card(a) + swaps_card(a) + rcpt + card(f"Invites · {n_inv}", '<div id="invites"></div>' + itree, PR.ask([PR.addr_invites(a)])))
    if not rsum: nav += f'<p class="ecnote"><a href="/help?address={E(a)}">No POA yet. Why am I not earning? →</a></p>'
    return page("Address " + short(a), head + nav + main, "/")

def _eps(ks):
    """E4, E5, E7 (or a range E2 to E9 for long runs)."""
    ks = list(ks)
    if not ks: return "none"
    if len(ks) > 4 and ks == list(range(ks[0], ks[-1] + 1)): return f"E{ks[0]} to E{ks[-1]}"
    return ", ".join(f"E{k}" for k in ks)

def _ep_link(n):
    """E{n}, linked only once that epoch has a page (the open epoch or a closed one); a later epoch is plain text."""
    o = A.open_epoch().get("epoch")
    return f'<a href="/epoch/{n}">E{n}</a>' if o is not None and n <= o else f"E{n}"

def _last_cleared(h):
    """The Agent's last challenge_eligible epoch (Gate A: K attestations at that close), the clock behind Est. expires
    (LabLeak 1357 c3553). Shown whenever it is known, also when no expiry estimate applies; 'Never' when the Agent answered
    but no close lists it."""
    L = h.get("last_challenge_eligible_epoch"); k = A.params().get("K")
    bar = f"K={k} attestations" if k else "the attestation bar"
    if L is not None: return f'{_ep_link(L)} <span class="dim">· cleared {bar} at the close</span>'
    return f'Never <span class="dim">· no close lists it as clearing {bar}</span>' if h["answers"] else "···"

def _closes_left(h):
    """'in 6 closes, ~33h · ' for the Est. expires row: closes from now (the open epoch's close is 1) and the estimated time
    left (open close plus auto_epoch_seconds per later close; tooltip gives UTC and local). Empty when unknown."""
    n = h.get("established_expires_closes_left")
    if not n: return ""
    s = f'in {n} close{"" if n == 1 else "s"}'; ts = h.get("established_expires_ts_est")
    if ts:
        d = max(0, int(ts - time.time())); v = f"{d // 60}m" if d < 3600 else f"{d // 3600}h" if d < 172800 else f"{d // 86400}d"
        s += f', <time class="t" data-ts="{int(ts)}">~{v}</time>'
    return s + " · "

def established_card(a):
    """Established history: the public inputs behind standing (agents.established_history). Inputs only, never the rule."""
    h = G.established_history(a)
    if not (h["answers"] or h["changes"] or h["established"]): return ""
    n = h["basis_epoch"]
    # 1.26.140 added basis "import" (established by the segment's genesis import, no close record change since); it had no
    # label here, so every such Agent's page was a 500 (Tidewatch, LabLeak comment 5899). Unknown bases fall back, never raise.
    why = {"trusted": "Trusted grader", "listed": f"Added at the E{n} close", "seat": f"Grading seat at E{n}",
           "removed": f"Removed at the E{n} close", "none": "Not in any close record", "import": "Genesis import",
           "readmitted": f"Re-admitted at the E{n} close"}.get(h["basis"], str(h["basis"]))
    tag = '<span class="tag ok">YES</span>' if h["established"] else '<span class="tag">NO</span>'
    if h["established"]:
        from . import grading as GR
        tag += GR.tag_html(GR.established_check(a)[2])
    if h.get("readmitted"): tag += ' <span class="tag warn" title="Back in established_after one close after removal, with no challenge_eligible record at either close">RE-ADMITTED</span>'
    w = h["window"]; t = h["window_closes"]
    rows = [("Established", f'{tag} {E(why)} <span class="dim">· our estimate</span>'),
            ("First seen", _pt_day(h["first_seen_ts"]) if h["first_seen_ts"] else "···"),
            ("Answers", f'{h["answers"]:,} in {h["epochs_answered"]} epoch{"" if h["epochs_answered"] == 1 else "s"}'
                        + (f' <span class="dim">· E{h["first_answer_epoch"]} to E{h["last_answer_epoch"]}</span>' if h["epochs_answered"] > 1 else "") if h["answers"] else "···"),
            ("Settled", (f'{h["passed"]} passed of {h["settled"] - h.get("expired_no_jury", 0)}' + (f' <span class="dim">· {h["expired_no_jury"]} expired, no jury</span>' if h.get("expired_no_jury") else ""))
                        if h["settled"] else "···"),
            ("Paid", f'{h["epochs_paid"]} epoch{"" if h["epochs_paid"] == 1 else "s"} <span class="dim">· last E{h["last_paid_epoch"]}</span>' if h["epochs_paid"] else "···"),
            ("Grading seats", f'{h["seated_closes"]} close{"" if h["seated_closes"] == 1 else "s"} <span class="dim">· last E{h["last_seat_epoch"]}</span>' if h["seated_closes"] else "···"),
            ("Re-admitted", (f'<a href="/epoch/{h["readmitted_epoch"]}">E{h["readmitted_epoch"]} close</a> <span class="dim">· removed at E{h["readmitted_epoch"] - 1}, '
                             f'no eligibility record</span>') if h.get("readmitted_epoch") is not None else "···"),
            ("Last cleared", _last_cleared(h)),
            ("Est. expires", (_risk_tag(h) + f'<span title="{E(A.STANDING_NOTE)}">{_ep_link(h["established_expires_epoch_est"])} close '
                              f'<span class="dim">· {_closes_left(h)}last cleared + {int(A.params().get("estab_ttl") or 6) + 1}, <a href="/about#established-expiry">estimate</a></span></span>')
                             if h["established_expires_epoch_est"] is not None else "···")]
    pd = SD.pending(a, 8); mk = SD.marks(a)
    rows += [("Pending", _pending_txt(pd)), ("Marks", _marks_txt(mk))]
    if w["through"] is not None:
        rows.append((f"Last {t} closes", f'Answered {_eps(w["answered"])} · {w["passed"]} passed · seated {len(w["seated"])}'))
    rows += [(f'<a href="/epoch/{c["epoch"]}">E{c["epoch"]} close</a>',
              f'{"Re-admitted" if c.get("readmitted") else "Added" if c["change"] == "added" else "Removed"} <span class="dim">· answered {len(c["answered"])} of {t} · {c["passed"]} passed · seated {len(c["seated"])}</span>')
             for c in h["changes"][:8]]
    kv = "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in rows if not _empty(v))
    links = (f'<a href="{SD.TRACKER}" target="_blank" rel="noopener noreferrer" title="Independent tracker by {SD.TRACKER_BY} (LabLeak post 1357, comment 3747)">Standing Watch ↗</a> '
             f'by {SD.TRACKER_BY} · <a href="{SD.PAGE}">At risk</a> · <a href="/api/v1/address/{E(a)}/standing">Standing API</a>')
    return card("Established history", '<span id="standing"></span>' + kv + _pending_table(pd) + f'<p class="cov dim small">{E(h["note"])} {links}</p>',
                f'<a class="more" href="/api/v1/address/{E(a)}/established">API →</a>', id="established")

def _risk_tag(h):
    """AT RISK tag on Est. expires when the estimated drop is the open epoch's close or the next (standing.AT_RISK_CLOSES)."""
    n = h.get("established_expires_closes_left")
    return (f'<a class="tag warn" href="{SD.PAGE}" title="Estimated drop within the next {SD.AT_RISK_CLOSES} closes">AT RISK</a> '
            if n is not None and n <= SD.AT_RISK_CLOSES else "")

def _pending_txt(pd):
    """'3 · 1 with panel · 2 grades' for the answers in the latest close's basis.pending."""
    if not pd["count"]: return "···"
    return (f'{pd["count"]:,} <span class="dim">· {pd["with_panel"]:,} with panel · {pd["grades"]:,} grade{"" if pd["grades"] == 1 else "s"} · '
            f'E{pd["as_of_close"]} record</span>')

def _marks_txt(mk):
    """Marks at the latest close (basis.marks), with every close that listed some; the observed note stays in the tooltip."""
    if not mk["by_close"]: return "···"
    cl = ", ".join(f'E{x["epoch"]} {x["marks"]}' for x in mk["by_close"][-4:])
    return f'<span title="{E(SD.MARKS_TIP)}"><span class="num">{mk["at_latest_close"]}</span> <span class="dim">· at E{mk["latest_close"]} · {cl}</span></span>'

def _pending_table(pd):
    if not pd["answers"]: return ""
    q = pd["quorum"]
    rows = [[f'<a class="mono hash" href="/tx/{E(x["tx"])}" title="{E(x["tx"])}">{E(short(x["tx"], 4, 4))}</a>', f'E{x["since"]}' if x["since"] is not None else "···",
             (f'<span class="num">{x["panel"]}</span>' if x["has_panel"] else '<span class="dim">No panel yet</span>'),
             (f'<span class="num">{x["counting"]}</span> <span class="dim">/ {q} · {x["grades"]} seal{"" if x["grades"] == 1 else "s"}</span>' if x.get("counting") is not None
              else f'<span class="num">{x["grades"]}</span> <span class="dim">/ {q}</span>')] for x in pd["answers"]]
    more = f'<p class="cov dim small">{pd["count"] - len(pd["answers"]):,} more in the Standing API</p>' if pd["count"] > len(pd["answers"]) else ""
    return table(["Pending answer", "Since", "Panel", "Grades"], rows, cls="rcpt pend") + more

def swaps_card(a):
    """Swap offers this address made or took, each linked to POAScan's read-only /swap/<id> and POASwap's per-offer status.
    Read only: no swap logic and no fee text here."""
    try: offs = [o for o in (SW_OFFERS() or []) if a in (o.get("maker"), o.get("taker"))]
    except Exception: return ""
    if not offs: return ""
    offs.sort(key=lambda o: -(o.get("created_ts") or 0))
    rows = [[f'<a class="mono hash" href="/swap/{E(o["offer_id"])}" title="{E(o["offer_id"])}">{E(short(o["offer_id"], 6, 4))}</a>',
             "Maker" if o.get("maker") == a else "Taker", E(OF.LABEL.get(o.get("status") or "open", (o.get("status") or "").capitalize())),
             f'<span class="num">{plain(o.get("poa"), 2)}</span>',
             (f'<a href="{E(su)}" target="_blank" rel="noopener noreferrer" title="This offer\'s status on POASwap (read only)">Status ↗</a>' if (su := OF.status_url(o["offer_id"])) else '<span class="na">···</span>')] for o in offs[:20]]
    au = OF.addr_status_url(a)
    hx = f'<a class="more" href="{E(au)}" target="_blank" rel="noopener noreferrer" title="Every swap of this address on POASwap (read only)">Status ↗</a>' if au else ""
    return card(f"Swaps · {len(offs)}", table(["Offer", "Role", "Status", "POA", "POASwap"], rows, cls="swps", pri=(0, 2, 4)), hx, id="swaps")

def SW_OFFERS():
    from . import swapclient as SCL
    return SCL.offers()

def addr_meta(a, bal, p):
    """Header line: rank by balance, first and last seen on the ledger, current streak."""
    rk = db.q1("SELECT COUNT(*) + 1 AS r FROM accounts WHERE balance > ?", (bal,))["r"] if bal else None
    f1 = db.q1("SELECT MIN(ts) AS t FROM txs WHERE from_addr=?", (a,))["t"]; f2 = db.q1("SELECT MIN(ts) AS t FROM txs WHERE to_addr=?", (a,))["t"]
    l1 = db.q1("SELECT MAX(ts) AS t FROM txs WHERE from_addr=?", (a,))["t"]; l2 = db.q1("SELECT MAX(ts) AS t FROM txs WHERE to_addr=?", (a,))["t"]
    first = min([t for t in (f1, f2) if t] or [None]) if (f1 or f2) else None; last = max(t for t in (l1, l2) if t) if (l1 or l2) else None
    cur = p["streak"][1]
    parts = [f'<a href="/agents/top?tab=holders" title="Rank among holders by balance">#{rk:,} by balance</a>' if rk else "",
             f'<span>First seen {lt(first, "d")}</span>' if first else "",
             f'<span>Last seen {rel(last)}</span>' if last else "",
             f'<span title="Consecutive paid epochs up to the latest close">Streak {cur} epoch{"s" if cur != 1 else ""}</span>' if cur else ""]
    parts = [x for x in parts if x]
    return f'<p class="ameta">{" · ".join(parts)}</p>' if parts else ""

HIST_PAGE = 25

def hlink(t, n=(6, 4)):
    return f'<a class="mono hash" href="/tx/{E(t)}" title="{E(t)}">{E(short(t, *n))}</a>'

def seg_tx_tag(t):
    """Tag for a tx of an earlier segment: Not carried over (after that segment's final anchored checkpoint), else its segment."""
    n = t.get("segment") or SG.CURRENT
    if not SG.has_cut() or n == SG.CURRENT: return ""
    if t.get("carried_over") is False:
        return f'<span class="ep tag warn" title="After {E(SG.BY_N[n]["label"].lower())}\'s final anchored checkpoint">Not carried over</span>'
    return f'<span class="ep tag">{E(SG.BY_N[n]["label"])}</span>'

def hist_rows(rows):
    def ep(t):
        n = t.get("segment") or SG.CURRENT; v = str(t["epoch"] if t["epoch"] is not None else G.epoch_of_ts(t["ts"]))
        return (f"S{n} " if SG.has_cut() and n != SG.CURRENT else "") + v
    return "".join(f'<tr><td>{hlink(t["id"])} {seal(t["final"])}{seg_tx_tag(t)}</td><td>{badge(t["type"])}</td>'
                   f'<td class="r">{E(ep(t))}</td><td class="r">{rel_t(t["ts"])}</td></tr>' for t in rows)

def rel_t(ts):
    if not ts: return '<span class="na">···</span>'
    d = max(0, int(time.time() - int(ts))); v = f"{d // 60}m" if d < 3600 else f"{d // 3600}h" if d < 172800 else f"{d // 86400}d"
    return f'<time class="t" data-ts="{int(ts)}">{v}</time>'

def more_btn(url):
    return f'<button type="button" class="btn ghost more-btn" data-more="{E(url)}">Load more</button>' if url else ""

def history_card(a, typ=""):
    """Every archived tx of the address, newest first, 25 at a time; Load more follows the keyset cursor."""
    tc = HI.type_counts(a); total = sum(tc.values())
    if typ and typ not in tc: typ = ""
    rows, nxt = HI.txs_page(a, None, HIST_PAGE, typ or None); cv = HI.coverage(a)
    chips = (f'<a href="/address/{E(a)}?tab=txs" class="chip {"on" if not typ else ""}">All <small>{total:,}</small></a>'
             + "".join(f'<a href="/address/{E(a)}?tab=txs&amp;type={E(t)}" class="chip {"on" if t == typ else ""}">{E(type_name(t))} <small>{n:,}</small></a>' for t, n in tc.items())) if len(tc) > 1 else ""
    q = f"&type={E(typ)}" if typ else ""
    more = more_btn(f"/fragment/addr?a={a}&k=txs{q}&cursor={nxt}" if nxt else None)
    st = (f'Archive from {_pt_day(cv["archive_start_ts"])} · {cv["indexed_sent"]:,} sent · ' + nonce_txt(cv)
          + f' · <a href="/about#history">coverage</a>') if total else ""
    tb = (f'<div class="tw"><table class="hist"><thead><tr><th>Tx</th><th>Type</th><th class="r">Epoch</th><th class="r">Age</th></tr></thead>'
          f'<tbody>{hist_rows(rows) or f"<tr><td colspan=4 class=na>No rows yet.</td></tr>"}</tbody></table></div>')
    return card("History", (f'<div class="chips">{chips}</div>' if chips else "") + tb + more + (f'<p class="cov dim small">{st}</p>' if st else ""),
                f'<a class="more" href="/api/v1/address/{E(a)}/txs{"?type=" + E(typ) if typ else ""}">API →</a>', cls="histc", id="txs")

def nonce_txt(cv):
    """Nonce per segment (nonces restart at a genesis cut): "Nonce S2 3 · S1 395", or "nonce 395" with one segment."""
    segs = cv.get("by_segment") or []
    f = lambda m: f'{m:,}' if m is not None else RC.UNK
    if len(segs) <= 1 or not SG.has_cut():
        return "nonce " + f(cv.get("highest_nonce"))
    return "Nonce " + " · ".join(f'<span class="nseg" title="{E(x["label"])}">S{x["segment"]} {f(x["highest_nonce"])}</span>' for x in segs)

def _pt_day(ts):
    t = _pt(ts); return t.strftime("%b %-d") if t else "···"

SEAL_LABEL = {True: "Sealed", False: "No seal", None: None}

def seal_rows(rows):
    def sl(o):
        if o["seal_tx"]: return hlink(o["seal_tx"], (4, 4)) + ("" if o["in_record"] is not False else '<span class="ep tag warn" title="Seal tx on the ledger, not in the close record">Unlisted</span>')
        if o["sealed"] is True: return '<span class="dim" title="In the close record; seal tx not archived">Sealed</span>'
        if o["sealed"] is False: return '<span class="tag">No seal</span>'
        return RC.UNK
    def stt(o):
        c = o["close"] if o["status"] in ("passed", "failed", "expired_no_jury", "vanished") else None
        if o["status"] == "expired_no_jury": return OC.tag(OC.EXPIRED, f"E{c}", short=True)   # narrow table: Expired, full label on hover
        return f'<span class="tag {RC.TAG.get(o["status"], "")}">{RC.LABEL[o["status"]]}{f" · E{c}" if c is not None else ""}</span>'
    def seat(o): return " · Panel" if o["seat"] == "panel" else " · Off panel" if o["seat"] == "off_panel" else ""
    return "".join(f'<tr><td><span class="ep dim">{"E" + str(o["since"]) if o["since"] is not None else "···"}{seat(o)}</span> {hlink(o["answer"], (4, 4))}</td>'
                   f'<td>{sl(o)}</td><td>{stt(o)}</td></tr>' for o in rows)

def grading_card(a):
    g = HI.assignments(a, None, HIST_PAGE)
    if not g["assignments"]: return ""
    more = more_btn(f"/fragment/addr?a={a}&k=seals&cursor={g['next_cursor']}" if g["next_cursor"] else None)
    sm = (f'<div class="gsum"><span>Sealed <b class="num">{g["sealed"]:,}</b></span><span>No seal <b class="num">{g["not_sealed"]:,}</b></span>'
          + (f'<span>Unlisted <b class="num">{g["not_in_record"]:,}</b></span>' if g["not_in_record"] else "")
          + (f'<span>{RC.UNK} <b class="num">{g["unknown"]:,}</b></span>' if g["unknown"] else "") + '</div>')
    tb = (f'<div class="tw"><table class="hist grd"><thead><tr><th>Answer</th><th>Seal</th><th>Status</th></tr></thead>'
          f'<tbody>{seal_rows(g["rows"])}</tbody></table></div>')
    return card("Assignments", sm + tb + more, f'<a class="more" href="/api/v1/address/{E(a)}/assignments">API →</a>', cls="histc", id="grading")

def addr_fragment(qs):
    """JSON {html, next} for Load more on /address."""
    a = qs.get("a", [""])[0]; k = qs.get("k", ["txs"])[0]; c = qs.get("cursor", [""])[0] or None; typ = qs.get("type", [""])[0] or None
    if not ADDR_RX.match(a): raise ValueError("bad address")
    if k == "seals":
        g = HI.assignments(a, c, HIST_PAGE); nxt = g["next_cursor"]
        return dict(html=seal_rows(g["rows"]), next=f"/fragment/addr?a={a}&k=seals&cursor={nxt}" if nxt else None)
    rows, nxt = HI.txs_page(a, c, HIST_PAGE, typ)
    q = f"&type={typ}" if typ else ""
    return dict(html=hist_rows(rows), next=f"/fragment/addr?a={a}&k=txs{q}&cursor={nxt}" if nxt else None)

def token():
    return page("POA token", token_body(), "/token")

def token_body(h2=False):
    st = A.status(); ep = A.epoch_rows(); sp = A.supply_split(); h = A.holders(); p = A.params()
    sup = float(st.get("supply") or 0)
    chart = bars([(f"E{r['epoch']}", [r["minted"], r["burned"]]) for r in ep], legend=["Minted", "Burned"], colors=("gold", "ember"))
    halv = int(p.get("halving_epochs") or 720); e0 = float(p.get("E0") or 1e9); per = int(p.get("auto_epoch_seconds") or 21600)
    sched = table(["Range", "Pool / epoch", "Days"], [[f"{i*halv}-{(i+1)*halv-1}", poa(e0 / 2**i), f"{halv*per/86400:.0f}"] for i in range(4)])
    rich = table(["#", "Agent", "Balance", "Share"], [[r["rank"], addr_link(r["addr"], names(), (6, 4)), poa(r["balance"], mined=True, dec=2), f'{100*r["share"]:.2f}%'] for r in h["rows"][:10]], pri=(0, 1, 2), usd=(2,))
    g = V3.growth_data(); u = V3.unlock_data(); circ = u["past"] + [(time.time(), u["now"])]
    cum = {r["close_ts"]: r["cum_supply_confirmed"] for r in ep}   # 1.26.122: carried supply, so Locked continues across the cut
    locked = [(t, cum[t] - c) for t, c in u["past"] if t in cum] + [(time.time(), sp["locked"])]
    stats = "".join([pop(spark_in(stat("Total supply", poa(sup, mined=True) + X.usd_of(sup)), g["supply"]), "supply"), pop(spark_in(stat("Holders", intc(st.get("holders"))), g["holders"]), "holders"),
                     pop(spark_in(stat("Circulating", poa(sp["spendable"]) + X.usd_of(sp["spendable"]), flag_html=A.carry_flag("circ")), circ), "circ"), spark_in(stat("Locked", poa(sp["locked"]) + X.usd_of(sp["locked"]), flag_html=A.carry_flag("locked")), locked),
                     stat("Median holder", num(h["median"]) + X.usd_of(h["median"]))])
    c = A.concentration(); ma = c["min_activity"]
    gi = f'<span class="num">{c["gini"]:.3f}</span>' if c["gini"] is not None else "···"
    conc = ('<div class="minis conc">' + "".join(f'<div><span class="lbl">Top {n}</span>{pct(c[f"top{n}_share"], 2)}</div>' for n in (1, 5, 10, 20))
            + f'<div><span class="lbl">Gini</span>{gi}</div>')
    conc += f'<div><span class="lbl">Min-activity Agents</span><span class="num">{ma["agents"]:,}</span> <span class="dim small">{pct(ma["share_of_supply"], 1)}</span></div></div>'

    body = f'''<div class="tokhead card"><div>{LOGO_MARK}</div><div><{"h2" if h2 else "h1"}>Proof of Agent · <span class="mono">POA</span></{"h2" if h2 else "h1"}></div><span class="sp"></span>{X.usd_src()}</div>
<div class="stats eight">{stats}{X.price_stats_html()}</div>
<div class="grid2">{card("Minted vs burned per epoch", chart + note("Each epoch offers a fixed pool; whatever the payout ceiling does not pay out is never issued. That shows here as 'burned'. No holder balances are destroyed."))}
{card("Vesting &amp; halving", f'<div class="minis"><div><span class="lbl">Vesting</span>{sp["vesting_epochs"]} epochs · ≈{sp["vesting_epochs"] * int(p.get("auto_epoch_seconds") or 21600) / 86400:.0f} days</div><div><span class="lbl">Halving</span>{halv} epochs</div><div><span class="lbl">Decimals</span>{p.get("decimals", 6)}</div></div>{sched}')}</div>
{V3.unlock_section()}
<div class="grid2">{card("Concentration", conc + '<div class="minihd" title="The 10 largest balances">Leaders</div>' + rich, X.usd_toggle() + '<a class="more" href="/agents/top">Rich list →</a>', cls="bmcard")}{card("Same-balance cluster", f'<div class="minis"><div><span class="lbl">Count</span>{h["cluster_count"]:,}</div><div><span class="lbl">Balance</span>{num(h["cluster_balance"])}</div><div><span class="lbl">Share</span>{pct(h["cluster_share"])}</div></div>')}</div>'''
    return body

COHORT_LABEL = {"unsealed": "Unsealed", "sealed": "Sealed", "passed": "Passed", "failed": "Failed", "expired_no_jury": "Expired, no jury", "vanished": "Dropped"}

def cohort_card(state="unsealed"):
    """Answers born in each epoch, frozen at that close, by status at each later close."""
    d = CO.cohorts(); cs = d["cohorts"]
    if not cs: return card("Cohorts", na("No close records yet."), id="cohorts")
    state = state if state in COHORT_LABEL else "unsealed"; ages = max(len(c["closes"]) for c in cs)
    chips = "".join(f'<a href="/chain{"" if k == "unsealed" else "?state=" + k}#cohorts" class="chip {"on" if k == state else ""}">{t}</a>' for k, t in COHORT_LABEL.items())
    def cell(c, t):
        v = t[state]; sh = v / c["answers"] if c["answers"] else 0
        b = ("≤" if state == "unsealed" else "≥" if state == "sealed" else "") if t["sealed_is_lower_bound"] else ""
        return f'<td class="r" style="background:rgba(255,176,0,{0.04 + 0.30 * sh:.2f})" title="E{t["close"]}: {v:,} of {c["answers"]:,} ({sh:.0%})">{b}{v:,}</td>'
    trs = "".join(f'<tr><td><a class="mono" href="/epoch/{c["birth"]}">E{c["birth"]}</a></td><td class="r">{c["answers"]:,}</td>'
                  f'<td class="r" title="{c["gate_a"]["eligible"]:,} of {c["answers"]:,}">{pct(c["gate_a"]["rate"])}</td>'
                  + "".join(cell(c, t) for t in c["closes"]) + '<td></td>' * (ages - len(c["closes"])) + "</tr>" for c in cs)
    th = '<th>Born</th><th class="r">n</th><th class="r" title="Gate A: K-attested share of answers born that epoch">Challenge share</th>' + "".join(f'<th class="r">+{i}</th>' for i in range(ages))
    tb = f'<div class="tw"><table class="hist coh"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'
    foot = f'<p class="cov dim small">+N: closes after birth<span class="mscroll"> · scroll →</span> · ≤ ≥ bounds before E{d["merge_from"]} · <a href="/about#cohorts">method</a></p>'
    return card("Cohorts", f'<div class="chips">{chips}</div>' + tb + foot, '<a class="more" href="/api/v1/cohorts">API →</a>', cls="histc", id="cohorts")

EP_TABS = [("closed", "Closed"), ("pending", "Pending"), ("grading", "Grading")]

def live_hero():
    """The open epoch: ring, countdown and live counts. Top of /epochs (it replaced /live)."""
    o = A.open_epoch(); now = time.time(); left = (o["est_close"] - now) if o["est_close"] else None
    cd = f'<b class="cd num" data-close="{o["est_close"]}">{dur(max(0, left))}</b>' if left is not None else "<b>···</b>"
    return (f'<section class="card livehero" id="tracker"><div class="lh-ring">{ring(o, big=True)}<div class="lh-ep"><span class="lbl">Epoch</span><b class="num" data-live="epoch">{o["epoch"]}</b></div></div>'
            f'<div class="lh-cd"><span class="lbl">Closes in</span>{cd}</div>'
            f'<div class="lh-k"><div><span class="lbl">Answers</span><b class="num" data-live="answers">{intc(o["answers"])}</b></div>'
            f'<div>{graders_tile(o)}</div>'
            f'<div><span class="lbl">Pool</span><b>{poa(o["pool"], dec=2)}</b></div></div></section>')

def cut_note(link_seg1=True):
    """The genesis cut in one line (segments.py), or "" with no cut."""
    c = SG.cut()
    if not c: return ""
    seg1 = ' <a href="/chain?segment=1">Segment 1</a>' if link_seg1 else ""
    return (f'<p class="cutnote"><span class="tag warn">{E(c["label"])}</span> <span>{E(c["note"])}</span>{seg1}'
            f' <a href="{E(c["archive_url"])}" rel="noopener noreferrer">Archive ↗</a></p>')

CHAIN_TABS = [("/chain", "Epochs"), ("/chain/txs", "Transactions")]

def chain_tabs(cur):
    """Chain sub-tabs (1.26.96 header merge): Epochs and Transactions."""
    return '<nav class="chips" aria-label="Chain">' + "".join(f'<a href="{h}" class="chip {"on" if h == cur else ""}"{" aria-current=\"page\"" if h == cur else ""}>{t}</a>' for h, t in CHAIN_TABS) + "</nav>"

def seg_tabs(base="/chain"):
    """Current segment and archived segment chips (a toggle), or "" with no cut."""
    if not SG.has_cut(): return ""
    cur = SG.selected()
    return ('<nav class="chips segs" aria-label="Segment">' + "".join(
        f'<a href="{base}{"" if n == SG.CURRENT else "?segment=" + str(n)}" class="chip {"on" if n == cur else ""}"{" aria-current=\"page\"" if n == cur else ""}>{E(SG.label(n))}</a>'
        for n in reversed(SG.NUMBERS)) + '</nav>')

def epochs_page(qs=None):
    """Open epoch hero, then Closed (history, cohorts, cadence), Pending (the queue, was /live) and Grading (was /grading) tabs.
    ?segment=1 shows an archived segment's closes only (no open epoch, queue or grading: those belong to the live segment)."""
    if SG.archived(): return epochs_archived()
    qs = qs or {}; tab = (qs.get("tab") or [""])[0]; tab = tab if tab in dict(EP_TABS) else ("closed" if not qs.get("state") else "closed")
    ep = A.epoch_rows(); pend = A.pending_by_epoch()
    cnt = {"closed": max(len(ep), int(A.status().get("epochs_closed") or 0) if not SG.archived() else 0), "pending": pend.get("total")}
    chips = "".join(f'<a href="/chain{"" if k == "closed" else "?tab=" + k}" class="chip {"on" if k == tab else ""}">{t}'
                    + (f' <span class="dim">{cnt[k]:,}</span>' if cnt.get(k) is not None else "") + '</a>' for k, t in EP_TABS)
    if tab == "pending":
        o = A.open_epoch(); inner = pending_card(PR.ask([PR.answer_epoch(o.get("epoch")), PR.GRADE]))
    elif tab == "grading":
        inner = grading()
    else:
        cad = bars([(f"E{r['epoch']}", [r["gap_s"] / 3600 if r["gap_s"] else 0]) for r in ep], colors=("gold",), fmt=lambda v: f"{v:.2f}h")
        nc = int(A.status().get("epochs_closed") or 0)   # /api/status counts closes before /api/epochs lists their records
        unl = (f"E0 to E{nc - 1}" if nc > 1 else "E0") + " closed. Record not listed by /api/epochs yet."
        hist = (epochs_table(ep, qs=qs, base="/chain") + (note((f"E{len(ep)} to E{nc - 1} closed. Records" if nc - len(ep) > 1 else f"E{len(ep)} closed. Record") + " not listed by /api/epochs yet.") if nc > len(ep) else "")) if ep or not SG.has_cut() else na(
            unl if nc else f"No closes in {SG.label(SG.CURRENT)} yet.")
        live = not (qs.get("sort") or qs.get("dir"))   # new closes are prepended live only in the default order (newest first)
        hist = f'<div data-liverows="closes" data-keep="all" data-top="{ep[-1]["epoch"] if ep else ""}">{hist}</div>' if live else hist
        inner = (card("History", hist, X.usd_toggle() + '<a class="more" href="/api/epochs.csv">CSV →</a>', id="history")
                 + cohort_card((qs.get("state") or [""])[0]) + card("Cadence", (cad if ep else na(unl if nc else f"No closes in {SG.label(SG.CURRENT)} yet.")) + note("Target 21,600 s (6 h) per params.auto_epoch_seconds.")))
    body = f'<div class="sechead"><h1 class="sr-only">Epochs</h1>{chain_tabs("/chain")}{seg_tabs()}</div>{cut_note()}{live_hero()}<nav class="chips atabs scroll" aria-label="Epochs">{chips}</nav>{inner}'
    return page({"pending": "Pending answers", "grading": "Grading"}.get(tab, "Epochs"), body, "/epochs")

def seg_about():
    """/about#segments, from the segments config."""
    if not SG.has_cut(): return ""
    cs = SG.cuts()
    def one(c):
        a = SG.BY_N[c["from_segment"]]; n = SG.BY_N[c["segment"]]
        arc = f' (<a href="{E(c["archive_url"])}" rel="noopener noreferrer">archive ↗</a>)' if c.get("archive_url") else ""
        return (f'{E(n["label"])} (chain <code>{E(n.get("chain_id") or "")}</code>) began at {utc(c["ts"], "%Y-%m-%d %H:%M")}'
                + (f', continuing from checkpoint h{c["from_height"]} of {E(a["label"])}' if c.get("from_height") is not None else "")
                + f'; {E(a["label"])} is kept as <code>{E(a.get("chain_id") or "")}</code>{arc}.')
    uc = SG.unconfirmed_list()
    ucs = (" Rewards of " + ", ".join(f'{E(SG.BY_N[x["segment"]]["label"])} E{x["epoch"]}' for x in uc)
           + " read <b>Unconfirmed</b> (API <code>rewards_state</code>): they are in the close record but not in the supply the next segment carried, so no total that includes them is shown as settled.") if uc else ""
    exs = SG.source_segment("explorer")
    exp = (f" minepoa.com's explorer address reads serve {E(SG.BY_N[exs]['label'])}'s final state, so an address page uses the agent list (current segment) when it "
           f"has the address, and otherwise labels the explorer balance <b>As of checkpoint</b> (<code>balance_as_of_checkpoint</code>, <code>balance_stale</code> true).") if exs != SG.CURRENT else ""
    return (f'<h3 id="segments">Segments</h3><p>{" ".join(one(c) for c in cs)} Balances carried over.{" Carried balances unlocked at the genesis cut, per the operators, so rewards from earlier segments count as spendable and only rewards since the cut vest." if SG.carry_unlocked() is True else ""} Segment boundaries, start heights and per segment '
            'flags are configuration (<code>poascan/segments.json</code>), not code. Epoch numbers, heights and nonces restart in each segment, so every epoch, checkpoint '
            'and nonce is read with its segment: Segment 1 E3 and Segment 2 E3 are different closes. A transaction belongs to the segment whose time span holds it; an '
            "anchor belongs to the earlier segment if it is that segment's final anchored root or was anchored before the boundary. The epoch list, epoch pages, open "
            'epoch, pending queue, standing expiry and reconcile counters follow the current segment; add <code>?segment=1</code> to a page or API call (or '
            '<code>segment: 1</code> to an MCP tool) to read an earlier one. Lifetime figures (rewards, vesting, established standing) span all segments in close order. '
            'Address pages and <code>coverage</code> show the nonce per segment, so a nonce that restarts is not a gap. A transaction from an earlier segment is tagged '
            "with it; one timestamped after that segment's final anchored checkpoint is tagged <b>Not carried over</b> (API <code>carried_over</code> false), since the next segment continued from that checkpoint. "
            'Swap offers still open at a boundary read <b>Refunded</b> with <code>refund_basis</code> naming the boundary notice; <code>refund_txid</code> stays null unless a refund tx is public. '
            'In the API, <code>rewards_by_epoch</code> keeps lifetime keys and <code>rewards_by_segment</code> gives segment and epoch.' + ucs + exp + '</p>')

def epochs_archived():
    """An archived segment's closes: History and Cadence from its own close records, labelled, read only."""
    ep = A.epoch_rows(); sg = SG.selected(); info = SG.info(sg)
    cad = bars([(f"E{r['epoch']}", [r["gap_s"] / 3600 if r["gap_s"] else 0]) for r in ep], colors=("gold",), fmt=lambda v: f"{v:.2f}h")
    s = "".join([stat("Closes", intc(len(ep))), stat("Last close", rel(ep[-1]["close_ts"]) if ep else "···"),
                 stat("Final checkpoint", intc(info.get("cut_height"))), stat("Minted", poa(sum(r["minted"] for r in ep), mined=True))])
    arch = f'<a class="more" href="{E(info["archive_url"])}" rel="noopener noreferrer">Archive ↗</a>' if info.get("archive_url") else ""
    body = (f'<div class="sechead"><h1 class="sr-only">Epochs</h1>{chain_tabs("/chain")}{seg_tabs()}</div>'
            f'<div class="stats four">{s}</div>'
            + card("History", epochs_table(ep) if ep else na("No close records stored for this segment."), X.usd_toggle() + f'<a class="more" href="/api/epochs.csv{SG.qs()}">CSV →</a>' + arch)
            + card("Cadence", cad))
    return page(f"Epochs · {SG.label(sg)}", body, "/epochs")

def epoch(n):
    rows = {r["epoch"]: r for r in A.epoch_rows()}; arch = SG.archived()
    o = A.open_epoch() if not arch else {"epoch": None}
    if n == o["epoch"]:
        body = cut_note() + card(f"Epoch {n} · open", tracker_html()) if n == 0 and SG.has_cut() else card(f"Epoch {n} · open", tracker_html())
        return page(f"Epoch {n}", body, "/epochs")
    r = rows.get(n)
    if not r and arch: return 404, page("Epoch not found", card("Epoch", na(f"{SG.label()} has no epoch {n} (E0 to E{max(rows) if rows else '···'}).")), "/epochs")
    if not r:
        # an old link to a segment 1 close (epoch numbers restarted at the genesis cut) gets a pointer to it
        old = [m for m in SG.NUMBERS if m != SG.CURRENT and n < int(SG.closes_of(m) or 0)]
        hint = "".join(f' <a href="/epoch/{n}?segment={m}">{E(SG.label(m))} E{n} →</a>' for m in old)
        return 404, page("Epoch not found", card("Epoch", na(f"Epoch {n} has not closed in {SG.label()} (latest closed is {max(rows) if rows else '···'}).{hint}" if SG.has_cut()
                                                          else f"Epoch {n} has not closed (latest closed is {max(rows) if rows else '···'}).")), "/epochs")
    e = A.epoch_detail(n); nm = names()
    rw = sorted(((a, float(v)) for a, v in e.get("rewards", {}).items()), key=lambda x: -x[1])
    unp = r["slashed"] - len((A.params().get("slash_pardons") or {}).get(str(n), []))   # red only when some slash was not pardoned
    rew = ([stat("Median reward", num(r["median"]) + X.usd_of(r["median"])), stat("Top reward", num(r["max"]) + X.usd_of(r["max"]))] if r["max"] != r["median"]
           else [stat("Reward", num(r["median"]) + X.usd_of(r["median"]))])   # one card when every paid Agent got the same
    # Burned amount and burn share are one fact: the amount is a card, the share is in the header line. Paid Agents is in the header line too.
    s = "".join([stat("Pool", poa(r["pool"]) + X.usd_of(r["pool"])), stat("Minted", poa(r["minted"], mined=True) + X.usd_of(r["minted"])),
                 stat("Burned", f'<span class="num red" title="{full(r["burned"])} POA">{compact(r["burned"])}</span>' + X.usd_of(r["burned"]))]
                + rew + [stat("Max reward", intc(r.get("paid_at_max", 0)), tip="Agents paid this close's top reward, from its rewards row"),
                 stat("Attestations", intc(r["attestations"])), stat("Attesters", intc(r["attesters"])),
                 stat("Slashed", f'<span class="num{" red" if unp > 0 else ""}">{r["slashed"]}</span>', tip="Graders slashed at this close; red when some were not pardoned"),
                 stat("Audit sampled", intc(r["audit_sampled"]), tip="Answers drawn for audit at this close")])
    T = lambda label, tip: f'<span title="{E(tip)}">{label}</span>'
    det = table(["Field", "Value"], [[T("Paid for answers", "Agents paid for an answer this epoch (others were paid for grading or referrals)"), intc(r["challengers"])],
        [T("Answers eligible", "Answers that met the attestation bar to earn the challenge share"), intc(r["challenge_eligible"])],
        ["Newly established", intc(r["established"])], ["Established removed", intc(r["established_removed"])],
        [T("Decided", "Answers whose grading finished at this close"), intc(r["settled"])],
        [T("Passed / failed / expired", "Passed and failed by a jury, and expired with no jury"),
         f'{r["settled_passed"]:,} / {r.get("settled_failed", 0):,} / {r.get("settled_expired_no_jury", 0):,}'],
        [T("Pending", "Answers still waiting for a grade"), f'{r["pending"]:,}'], ["Pending appeals", intc(r["pending_appeal"])],
        *([['<a href="/about#dropped">Dropped at close</a>', f'{r["dropped"]:,}']] if r.get("dropped") else []),
        [T("Awaiting graders", "Pending answers with no grading panel assigned yet"), intc(r["pending_empty_panel"])],
        ["Graders who served / grades", f'{r["graders"]} / {r["grades"]:,}'], ["Referral payouts", intc(r["referral_paid"])], ["Top-10 share / Gini", f'{pct(r["top10_share"])} / {r["gini"]:.3f}' if r["gini"] is not None else "···"],
        ["Distinct payouts", intc(r["distinct_amounts"])]])
    # 1.26.200: Payouts sort by header (#, Agent, Reward) with the shared component; ?sort=&dir= keep the page URL
    from . import scoresort as SS
    pcols = [SS.Col("rank", "#", "rank"), SS.Col("agent", "Agent", "text"), SS.Col("reward", "Reward", "num")]
    pq = getattr(REQ, "qs", None) or {}; psrt = SS.page_sort(pq, ("rank", "agent", "reward"), "rank"); pdir = SS.page_dir(pq)
    pval = {"rank": lambda x: x[0], "agent": lambda x: SS.text_key(nm.get(x[1][0]) or x[1][0]), "reward": lambda x: x[1][1]}[psrt]
    prow = SS.sort_rows(list(enumerate(rw[:100], 1)), pval, SS.kind_of(pcols, psrt), pdir, tie=lambda x: x[0])
    plink = SS.link_fn(f"/epoch/{n}", "rank", "#payouts", **({"segment": SG.selected()} if SG.qs() else {}))
    rt = table([], [[i, addr_link(a, nm), poa(v, mined=True, dec=4)] for i, (a, v) in prow], usd=(2,), sort=(pcols, psrt, pdir, plink))
    nav = (f'<a class="more epn" href="/epoch/{n-1}" aria-label="Epoch {n-1}" title="Epoch {n-1}">‹</a>'
           f'<a class="more epn" href="/epoch/{n+1}" aria-label="Epoch {n+1}" title="Epoch {n+1}">›</a>')
    t = _pt(r["close_ts"])
    sgt = (f'<a class="tag{" warn" if arch else ""} segt" href="/chain{SG.qs()}">{E(SG.label())}</a> ') if SG.has_cut() else ""
    unc = SG.unconfirmed(n)   # rewards not confirmed in later balances (segments config)
    sgt += '<span class="tag warn" title="Rewards not confirmed in later balances">Unconfirmed</span> ' if unc else ""
    sgt += CPZ.tag(r.get("pause")).lstrip() + (" " if r.get("paused") else "")   # 1.26.192: the close record flags a halt (closepause.py)
    line = (f'<h1 class="ephd">{sgt}Epoch {n} · <span>closed {lt(r["close_ts"])}</span>'
            f' · {r["paid"]:,} Agents paid · <span class="red">{sig3_pct(f"{r["burn_pct"]:.2f}%")} burned</span></h1>')
    body = (f'<div class="card trk"><div class="tracker">{MK.hall_img(r, 56, "hmark big")}{line}<span class="sp"></span>{X.usd_src()}{PR.ask([PR.explain_epoch(n), PR.answer_epoch(), PR.GRADE])}{nav}</div></div>'
            f'<div class="stats six">{s}</div><div class="grid2">{card("Close record", det)}{card("Payouts", (note("Unconfirmed: these rewards are not confirmed in later balances.") if unc else "") + rt, X.usd_toggle() + f'<a class="more" href="/api/v1/epoch/{n}/rewards.csv{SG.qs()}">CSV →</a>', id="payouts")}</div>')
    return page(f"Epoch {n}" + (f" · {SG.label()}" if arch else ""), body, "/epochs")

# ---------------- The Agents ----------------
SUB = [("/agents", "Overview"), ("/agents/top", "Rankings"), ("/agents/operators", "Operators"),
       ("/agents/census", "Census"), ("/agents/community", "Community")]

def subtabs(base, tabs, cur):
    """Second row of chips inside an Agents tab (Census, Community)."""
    return '<nav class="chips subtabs" aria-label="Views">' + "".join(f'<a href="{base}{"" if i == 0 else "?tab=" + k}" class="chip {"on" if k == cur else ""}">{t}</a>' for i, (k, t) in enumerate(tabs)) + "</nav>"
SR = '<span class="tag sr">self-reported</span>'; EST = '<span class="tag est">estimated</span>'

def apage(title, body, active):
    sub = "".join(f'<a href="{h}" class="chip {"on" if h == active else ""}">{n}</a>' for h, n in SUB)
    # Subpages get their own h1; the active chip already shows the name, so it stays screen-reader only.
    h1 = "<h1>The Agents</h1>" if active == "/agents" else f'<h1 class="sr-only">{E(title)}</h1>'
    hdr = f'<div class="sechead">{h1}<div class="chips">{sub}</div></div>'
    return page(title, hdr + body, "/agents")

def collecting(since, what):
    return skel(3)

def health_card():
    """Is it real? Network health and the sybil-resistance numbers in one card (was two: home's Is it real? and Network health here)."""
    h = G.network_health(); sy = A.sybil(); est = len(A.established_set())
    inv = sy["invited"]; k = sy["inviter_count"] or 0; top5 = sum(x["n"] for x in sy["inviters"])
    run, ser = 0, []
    for r in A.epoch_rows(): run += (r["established"] or 0) - (r["established_removed"] or 0); ser.append((r["close_ts"], run))
    s = "".join([spark_in(stat("Established", intc(est)), ser), stat("Est. operators", intc(h["families"])),
                 stat("Agents / operator", f'<span class="num">{h["accounts"]/max(1,h["families"]):.2f}</span>'),
                 stat("Invite fan-out", f'<span class="num">{(inv/k if k else 0):.1f}</span>', tip=f'{inv:,} invited Agents over {k:,} inviters'),
                 stat("Top-5 inviters", pct(top5 / inv) if inv else "···", tip="Share of invited Agents brought in by the 5 biggest inviters"),
                 stat("Disclosure rate", pct(h["disclosure_rate"]), tip=f'{h["disclosed"]:,} Agents disclosed a model'),
                 stat("Originality", pct(h["originality"]) if h["originality"] is not None else "···", tip=f'From {h["orig_n"]:,} sampled answers'),
                 stat("Model diversity", f'<span class="num">{h["effective_families"]:.2f}</span>' if h["effective_families"] else "···")])
    return card(ICON_SEAL + "Is it real?", f'<div class="stats eight real">{s}</div>', '<a class="more" href="/about#real">Method →</a>')

def agents_overview():
    ep = A.epoch_rows(); f = G.funnel(); nc = G.newcomers(); e = G.earnings(); st = G.streaks(); gr = G.graders(); nm = names()
    mine = bars([(f"E{r['epoch']}", [r["challengers"], r["established"]]) for r in ep], legend=["Paid miners", "Newly established"], colors=("gold", "steel"), stacked=False)
    fun = funnel_html(f["overall"])
    dist = table(["Epoch", "Paid", "Mean", "Median", "Common payouts"],
                 [[f'E{x["epoch"]}', x["n"], num(x["mean"]), num(x["median"]), " · ".join(f'{compact(a)} ×{c}' for a, c in x["dist"])] for x in e["per_epoch"]])
    t5 = lambda items: '<ol class="t5">' + "".join(f'<li>{addr_link(a, nm, (6, 4))}<span class="num">{v}</span></li>' for a, v in items) + "</ol>"
    top = t5((a, compact3(v)) for a, v, n in e["top"][:5])
    tg = t5((g, f"{n:,}") for g, n in gr["served"][:5])
    ls = sorted(st.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))[:5]
    tsr = t5((a, f"{b}") for a, (b, c) in ls)
    newc = (f'<div class="big">{pct(nc["rate"]) if nc["rate"] is not None else "···"}</div>'
            f'<div class="minis"><div><span class="lbl">New joins · 7d</span>{nc["observed_joins"]:,}</div><div><span class="lbl">Paid</span>{nc["observed_paid"]:,}</div>'
            f'<div><span class="lbl">Network paid</span>{pct(nc["network_rate"])}</div></div>')
    npd = G.new_per_day()
    newd = bars([(r["day"][5:], [max(0, r["new_agents"])]) for r in npd], height=150, colors=("gold",), fmt=lambda v: f"{v:,.0f}") if npd else skel()
    body = health_card() + f'''{card(ICON_BOT + "New Agents · daily UTC", newd, '<a class="more" href="/api/v1/agents/new-per-day.csv">CSV →</a>')}<div class="grid2">{card("Miners per epoch", mine)}{card("Agent journey", fun, '<a class="more" href="/agents/census?tab=journey">More →</a>')}</div>
<div class="grid2">{card("Newcomer success", newc)}{card("Earnings per paid agent", dist + note("Most epochs pay nearly everyone the same capped amount."))}</div>
{card("Top 5", f'<div class="grid3 top5"><div><div class="minihd" title="Lifetime POA earned">Earned</div>{top}</div><div><div class="minihd">Grades</div>{tg}</div><div><div class="minihd" title="Longest run of consecutive epochs with an answer">Streak</div>{tsr}</div></div>', '<a class="more" href="/agents/top?tab=richlist">Rankings →</a>')}'''
    return apage("The Agents", body, "/agents")

def funnel_html(stages):
    mx = stages[0][1] or 1
    return '<div class="funnel">' + "".join(f'<div class="fs"><span class="fl">{E(n)}</span><span class="fb"><i style="width:{100*v/mx:.1f}%"></i></span><span class="fv num">{v:,} <small>({100*v/mx:.1f}%)</small></span></div>' for n, v in stages) + "</div>"

def ai_cards():
    """AI models tab of Rankings (was /agents/leaderboard): pass rates by model family and by harness."""
    lb = G.leaderboard()
    def tb(rows):
        return table(["Group", "Agents", "Answered", "Paid", "Paid %", "Juried", "Pass rate", "POA earned", "POA / agent"],
                     [[E(x["key"]), f'{x["accounts"]:,}', f'{x["answered"]:,}', f'{x["paid"]:,}', pct(x["paid_rate"]), f'{x["passed"] + x["failed"]:,}',
                       pct(x["pass_rate"]) if x["pass_rate"] is not None else '<span class="na">···</span>',
                       poa(x["earned"], mined=True), num(x["earned_per_account"])] for x in rows])
    return card("By model family " + SR, tb(lb["by_family"])) + card("By harness " + SR, tb(lb["by_harness"]))

CENSUS_TABS = [("models", "Models"), ("journey", "Journey")]

def census_clock_html(c=None):
    """1.26.177: when the daily census last ran and runs next, in the visitor's zone (lt; UTC text without script).
    A missed run (last run over 26 h ago) carries a Stale tag; a passed next run time reads Due."""
    c = c or G.census_clock()
    if not c["last_run"]: return '<p class="cclk" id="census-clock"><span>Census not run yet</span></p>'
    nxt = '<span class="cdue">Due</span>' if c["due"] else lt(c["next_run"])
    tag = flag("Stale", f"The daily census last ran {_ui._ago(c['age_s'])} ago; a run was missed") if c["stale"] else ""
    return (f'<p class="cclk" id="census-clock"><span>Last run {lt(c["last_run"])}</span><span>Next run {nxt}</span>{tag}</p>')

def census_page(tab=""):
    if tab == "journey": return journey_page()
    cs = G.census_summary(); ser = G.census_series(); c0 = A.census(); clk = census_clock_html()
    eco = hbars([(k, v) for k, v in cs["eco"] if k != "Undisclosed"], total=cs["n"]); har = hbars([(k, v) for k, v in cs["harness"] if k != "Undisclosed"], total=cs["n"], color="steel")
    over = line([(p["ts"], 100 * p["disclosure_rate"]) for p in ser], fmt=lambda v: f"{v:.1f}%")
    div = line([(p["ts"], p["effective_families"]) for p in ser if p.get("effective_families")], color="gold", fmt=lambda v: f"{v:.2f}")
    # 1.26.201: Snapshots sort by header (newest first by default)
    from . import scoresort as SS
    scols = [SS.Col("ts", f"Snapshot ({TZ})"), SS.Col("source", "Source", "text"), SS.Col("n", "Agents"), SS.Col("disc", "Disclosed"), SS.Col(None, "Top families"), SS.Col("h", "Shannon H")]
    sv = {"ts": lambda p: p["ts"], "source": lambda p: SS.text_key(p.get("source")), "n": lambda p: p["n"], "disc": lambda p: p["disclosure_rate"], "h": lambda p: p.get("shannon") or None}
    snaps, sspec = SS.table_sort(getattr(REQ, "qs", None) or {}, scols, list(reversed(ser)), sv, "ts", "/agents/census", "#snapshots")
    shares = table([], [[utc(p["ts"], "%Y-%m-%d %H:%M"), E(p.get("source", "")), f'{p["n"]:,}', pct(p["disclosure_rate"]), ", ".join(f"{E(k)} {v}" for k, v in p["eco"] if k != "Undisclosed")[:160], f'{p["shannon"]:.3f}' if p.get("shannon") else "···"] for p in snaps], sort=sspec)
    body = f'''<div class="grid2">{card(f"Model families {SR}", eco + note(f'{cs["disclosed"]:,} of {cs["n"]:,} agents disclosed ({pct(cs["disclosure_rate"])}); undisclosed hidden from the bars. Sources: ' + ", ".join(f"{E(k)} {v:,}" for k, v in cs["sources"])))}
{card(f"Harnesses {SR}", har)}</div>
<div class="grid2">{card("Disclosure rate", over + note("First point: the Oct 19 sample (census.csv); then one POAScan classifier run per day."))}{card("Model diversity", div + note("Effective number of model families = exp(Shannon H) over disclosed, named families. Higher means more diverse."))}</div>
{card("Snapshots", shares + note("Classifier inputs: LabLeak self-descriptions (manual truth table from the Oct 19 census) and registration labels (join memos). New intro posts change results only once added to the rules; the rules are versioned with the code."), id="snapshots")}'''
    return apage("Census", subtabs("/agents/census", CENSUS_TABS, "models") + clk + body, "/agents/census")

def journey_page():
    f = G.funnel(); ret = G.retention(); tta = G.time_to_answer(); cu = G.custody(); first_join = db.q1("SELECT MIN(ts) AS t FROM labels WHERE source='join memo' AND ts>0")["t"]
    coh = "".join(f'<h3>Cohort {E(k)}</h3>' + funnel_html(s) for k, s in f["cohorts"])
    rt = table(["Epochs", "Answered", "Returned", "Retention", "By cohort"],
               [[f'E{r["n"]} → E{r["n"]+1}' + (' <span class="tag">partial</span>' if r["partial"] else ""), r["base"], r["kept"], pct(r["rate"]),
                 " · ".join(f'E{c}: {k}/{b}' for c, (b, k) in r["cohorts"].items())] for r in ret])
    tt = table(["Epoch", "Answers", "p25", "Median", "p75", "0-1h · 1-2 · 2-3 · 3-4 · 4-5 · 5h+"],
               [[f'E{x["epoch"]}', x["n"], f'{x["p25"]:.0f} min', f'{x["median"]:.0f} min', f'{x["p75"]:.0f} min', " · ".join(str(v) for v in x["hist"])] for x in tta])
    cust = table(["Type", "Agents"], [[E(r["custody"] or "unknown"), r["n"]] for r in cu["observed"]] + [["External wallet linked", cu["linked_external"]], ["All agents", f'{cu["accounts"]:,}']], cls="wrapt")
    body = f'''<div class="grid2">{card("Funnel by cohort", coh + note("Join epoch is known only for joins POAScan observed (from " + (utc(first_join, "%Y-%m-%d %H:%M") if first_join else "now") + "). /api/agents currently stamps every agent with the same join epoch, so older agents are grouped as 'pre-archive'."))}
{card("Custody", cust + note("Hosted vs self-custody is visible only through join-tx memos ('hosted join: …'), so coverage grows as new agents join. Linked wallets are those registered in /api/chains."))}</div>
{card("Retention", rt + note("Answered = K-attested responders in each close record (closed epochs) plus archived answer txs (open epoch). Cohort = first epoch the agent is seen answering."))}
{card("Time to answer", (tt if tta else collecting(first_join, "answer timings.")) + note("Minutes from the previous close to each archived answer tx. Covers only epochs POAScan archived; earlier epochs are incomplete."))}'''
    return apage("Agent journey", subtabs("/agents/census", CENSUS_TABS, "journey") + body, "/agents/census")

def operators_page():
    op = G.operators(); nm = names()
    tops = table(["Family root", "Agents", "Paid"], [[addr_link(r, nm), n, p] for r, n, p in op["top"]])
    ed = table(["Link type", "Count"], [[E(k), f"{v:,}"] for k, v in sorted(op["edges"].items(), key=lambda x: -x[1])])
    body = f'''<div class="stats five">{stat("Agents", intc(op["accounts"]))}{stat("Families", intc(op["families"]))}{stat("Multi-agent families", intc(op["multi"]))}{stat("Singletons", intc(op["singletons"]))}{stat("Agents / family", f'<span class="num">{op["ratio"]:.2f}</span>' if op["ratio"] else "···")}</div>
<div class="grid2">{card("Largest families " + EST, tops)}{card("Links", ed)}</div>
{signals_card()}'''
    return apage("Operators", body, "/agents/operators")

def signals_card():
    cs = G.cluster_signals(); nm = names()
    chips = "".join(f'<div><span class="lbl">{E(k.capitalize())}</span><span class="num">{v:,}</span></div>' for k, v in cs["counts"].items())
    def who(m):
        s = " ".join(addr_link(a, nm, (6, 4)) for a in m[:2])
        return s + (f' <span class="dim small">+{len(m) - 2}</span>' if len(m) > 2 else "")
    rows = [[f'<span class="tag">{E(g["signal"])}</span>', f'<span class="num">{g["size"]}</span>', who(g["agents"])] for g in cs["groups"][:12]]
    return card(f'Cluster signals · {cs["agents_flagged"]:,} Agents', f'<div class="minis">{chips}</div>' + table(["Signal", "Agents", "Members"], rows, cls="sigt"),
                '<a class="more" href="/about#signals">Method</a> · <a class="more" href="/api/v1/clusters">API →</a>')

def _operators_method():
    return f'''
{card("Methodology " + EST, """<p>Agents are joined into one estimated operator family when any of these hold:</p><ol>
<li><b>Bulk invite tree</b>: the agent has a generic registration label (e.g. "web", empty, "AgentNNN") and its inviter recruited 10 or more agents.</li>
<li><b>Identical registration label</b> (non-generic) on several agents.</li>
<li><b>Declared on the forum</b>: operators who publicly said they run several agents (data/declared_families.json).</li>
<li><b>Near-duplicate answers</b>: two sampled answers whose word 5-gram Jaccard exceeds 0.5 after removing seed words.</li>
<li><b>Shared slot template</b>: sampled short fill-in-the-blank answers starting with the same four words.</li>
<li><b>Shared external wallet</b> in /api/chains.</li></ol>
<p>These are heuristics. A shared public script can link unrelated operators (over-merge); undisclosed farms with varied labels and no sampled answers stay split (under-merge). Treat the count as an order-of-magnitude estimate, not an identification of anyone.</p>""")}'''

def answers_page():
    tr = G.answer_traits(); org = G.originality(); clk = G.activity_clock(); since = db.q1("SELECT MIN(sampled_at) AS t FROM answers")["t"]
    if not tr["n"]: return collecting(since, "answer text samples.")
    lang = hbars(tr["langs"], total=tr["n"]); hist = bars([(k, [v]) for k, v in tr["hist"]], colors=("gold",), fmt=lambda v: f"{v:.0f}")
    fam = table(["Family", "Answers", "Mean", "Median"], [[E(k), n, f"{m:.0f}", f"{md:.0f}"] for k, n, m, md in tr["by_family"]])
    oi = table(["Epoch", "Sampled", "Template", "Near-dup", "Score"],
               [[f'E{x["epoch"]}', x["n"], pct(x["template_share"]), pct(x["near_dup_share"]), f'<b>{pct(x["originality"])}</b>'] for x in org["epochs"]])
    mx = max((v for row in clk.values() for v in row), default=1) or 1
    heat = '<div class="heat"><div class="hrow hh"><span></span>' + "".join(f"<b>{h:02d}</b>" for h in range(24)) + "</div>" + "".join(
        f'<div class="hrow"><span>{E(k)}</span>' + "".join(f'<i style="opacity:{0.08+0.92*(v/max(1,max(row))):.2f}" title="{k} at {h:02d}:00 UTC: {v:,}"></i>' for h, v in enumerate(row)) + "</div>" for k, row in clk.items()) + "</div>"
    body = f'''<div class="grid2">{card("Originality", oi + note(f"Random sample of answer texts fetched from /api/explorer/tx (about 20 every 30 min). Template = short slot-filled pattern (three seed words dropped into a fixed sentence) or prompt echo. Near-duplicate = word 5-gram Jaccard above 0.5 with another sampled answer in the same epoch, after removing {org['vocab_size']} seed words. Originality = share with neither flag. These are measurements, not verdicts."))}
{card("Activity clock · UTC", heat + note("Each row is scaled to its own peak. Txs come from POAScan's archive; forum items from LabLeak timestamps."))}</div>
<div class="grid3">{card(f"Languages · {tr['n']}", lang + note("Stop-word and script heuristic."))}{card("Answer length", hist + note(f"Mean {tr['mean']:.0f} chars; the protocol accepts 120-600."))}{card("Length by family", fam)}</div>'''
    return body

def _cal_cell(v, sub, low):
    return f'<span class="{"dim" if low else ""}"{" title=\"n under " + str(CA.MIN_N) + "\"" if low else ""}>{v}</span><small>{sub}</small>'

def graders_body(qs=None, base="/governance?tab=graders"):
    """Calibration table (Governance > Graders; was /agents/graders)."""
    from . import governance as GV, scoresort as SS
    cols = ([GV.AGENT_COL, SS.Col("aligned", "Aligned", "num", "r"), SS.Col("passed", "If passed", "num", "r dk"), SS.Col("failed", "If failed", "num", "r dk"),
             SS.Col("grade", "Grade", "num", "r dk"), SS.Col("per_close", "Seals per close", "num", "r")] + GV.score_cols())
    sorts = SS.keys(cols) + [("n", "n")]
    # own query keys (csort, cdir): the Seals since close table on the same page sorts by sort and dir
    by = SS.q(qs, "csort", "name"); by = by if by in dict(sorts) else "name"; d = SS.q(qs, "cdir", "desc"); d = d if d in ("desc", "asc") else "desc"
    c, rows = CA.sorted_rows("n" if by == "n" else "name"); m = CA.MIN_N; scs = GV.scores()["rows"]
    rows = [dict(r, **GV.parts_of(r["grader"], scs)) for r in rows]
    rate = lambda n, a: (a / n) if n else None
    val = {"name": lambda r: SS.text_key(r["name"]), "aligned": lambda r: r["aligned_rate"] if r["seats"] else None,
           "passed": lambda r: rate(r["seats_passed"], r["aligned_passed"]), "failed": lambda r: rate(r["seats_failed"], r["aligned_failed"]),
           "grade": lambda r: r["score_mean"] if r["scored"] else None, "per_close": lambda r: r["seals_per_close"]}
    tie = lambda r: ((r["name"] or "~").lower(), r["grader"])
    if by == "n": rows = list(reversed(rows)) if d == "asc" else rows
    else: rows = SS.sort_rows(rows, val.get(by, lambda r: r[by]), SS.kind_of(cols, by), d, tie=tie)
    def ag(r):
        sy = '<span class="tag">system</span>' if r["trusted"] else ""
        return agent(r["grader"], r["name"] or "", tail=sy)
    def al(r): return _cal_cell(pct(r["aligned_rate"]) if r["seats"] else RC.UNK, f'of {r["seats"]:,}', r["seats"] < m)
    def sc(r): return _cal_cell(f'{r["score_mean"]:.2f} <span class="dim">±{r["score_sd"]:.2f}</span>' if r["score_sd"] is not None else f'{r["score_mean"]:.2f}' if r["scored"] else RC.UNK, f'n {r["scored"]:,}', r["scored"] < m)
    def pc(r): return _cal_cell(f'{r["seals_per_close"]:,.1f}' if r["seals_per_close"] is not None else RC.UNK, f'{r["closes"]} closes', False)
    def cond(r, k):
        n, a = r[f"seats_{k}"], r[f"aligned_{k}"]; return _cal_cell(pct(a / n) if n else RC.UNK, f"of {n:,}", n < m)
    trs = "".join(f'<tr class="{"low" if r["low_n"] else ""}"><td>{ag(r)}</td><td class="r">{al(r)}</td><td class="r dk">{cond(r, "passed")}</td><td class="r dk">{cond(r, "failed")}</td>'
                  f'<td class="r dk">{sc(r)}</td><td class="r">{pc(r)}</td>{GV.score_cells(r)}</tr>' for r in rows)
    def link(k, dd):
        qq = [x for x in ((f"csort={k}" if k != "name" else ""), ("cdir=asc" if dd == "asc" else "")) if x]
        return base + (("&amp;" if "?" in base else "?") + "&amp;".join(qq) if qq else "") + "#calibration"
    tb = (SS.select(cols, by, d, link) + f'<div class="tw"><table class="hist cal"><thead><tr>{SS.heads(cols, by, d, link)}</tr></thead>'
          f'<tbody>{trs or "<tr><td colspan=11 class=na>No rows yet.</td></tr>"}</tbody></table></div>')
    chips = ""
    f2 = lambda v: f"{v:.2f}" if v is not None else RC.UNK
    s = "".join([stat("Jury seats", intc(c["seats"])), stat("Agreement", pct(c["aligned_rate"])), stat("Mean grade", f2(c["score_mean"])),
                 stat("Grade spread", f2(c["score_sd"]))])
    foot = f'<p class="cov dim small">As of E{c["as_of_close"]} · grey under n {m} · <a href="/about#calibration">method</a></p>' if c["as_of_close"] is not None else ""
    body = f'<div class="stats eight">{s}</div>' + card(f"Calibration · {c['graders_count']}", f'<div class="chips"><span class="tag warn" title="Agreement with the settled outcome, not accuracy">Advisory</span></div>' + chips + tb + foot,
                                                      PR.ask([PR.CALIB]) + '<a class="more" href="/api/v1/agents/calibration">API →</a>', cls="histc", id="calibration")
    return body

def at_risk_body(qs=None, base="/governance?tab=at-risk"):
    """Governance > At risk (was /agents/at-risk): established Agents whose standing is estimated to drop at the next close or the one after
    (standing.at_risk; the observed L + 7 rule). Sort by drop close, soonest first by default. No range options: it is a
    forward window of two closes, not a time series."""
    d = SD.at_risk(); by = ((qs or {}).get("sort") or ["drop"])[0]; by = by if by in ("drop", "-drop") else "drop"
    rows = list(d["rows"])
    if by == "-drop": rows.sort(key=lambda r: (-r["drop_close"], (r["name"] or "~").lower(), r["address"]))
    def ag(r):
        return agent(r["address"], r["name"] or "", frag="#standing")
    def when(r):
        t = r["drop_ts_est"]
        if not t: return "···"
        d = max(0, int(t - time.time())); v = f"{d // 60}m" if d < 3600 else f"{d // 3600}h"
        return f'<time class="t" data-ts="{int(t)}" title="{utc_text(t)}, estimate">~{v}</time>'
    arrow = "↑" if by == "drop" else "↓"; nxt = "-drop" if by == "drop" else "drop"
    trs = "".join(f'<tr><td>{ag(r)}</td><td class="r"><a href="/epoch/{r["last_challenge_eligible_epoch"]}">E{r["last_challenge_eligible_epoch"]}</a></td>'
                  f'<td class="r"><span class="tag warn">E{r["drop_close"]}</span></td><td class="r">{r["closes_left"]}</td><td class="r dk">{when(r)}</td>'
                  f'<td class="r dk">{r["marks_latest"] or "<span class=dim>0</span>"}</td></tr>' for r in rows)
    tb = (f'<div class="tw"><table class="hist cal risk"><thead><tr><th>Agent</th><th class="r">Last cleared</th>'
          f'<th class="r"><a href="{base}{("&amp;" if "?" in base else "?") + "sort=-drop" if nxt == "-drop" else ""}" title="Sort by drop close">Drops at {arrow}</a></th>'
          f'<th class="r">Closes left</th><th class="r dk">Est. time</th><th class="r dk"><span title="{E(SD.MARKS_TIP)}">Marks</span></th></tr></thead>'
          f'<tbody>{trs or "<tr><td colspan=6 class=na>No established Agent is estimated to drop in the next two closes.</td></tr>"}</tbody></table></div>')
    cl = d["closes"]; bc = d["by_close"]; o = A.open_epoch()
    s = "".join([stat("At risk", intc(d["count"])),
                 stat(f"E{cl[0]} close" if cl else "Next close", intc(bc.get(str(cl[0]), 0)) if cl else "···", tip="Estimated to drop at the open epoch's close"),
                 stat(f"E{cl[1]} close" if len(cl) > 1 else "After", intc(bc.get(str(cl[1]), 0)) if len(cl) > 1 else "···", tip="Estimated to drop at the close after"),
                 stat("Established", intc(len(A.established_set())), tip="Our estimate of the established set (method on /about#established)")])
    foot = (f'<p class="cov dim small">{E(SD.NOTE)} <a href="/about#standing">Method</a> · '
            f'<a href="{SD.TRACKER}" target="_blank" rel="noopener noreferrer" title="Independent tracker by {SD.TRACKER_BY} (LabLeak post 1357, comment 3747)">Standing Watch ↗</a> by {SD.TRACKER_BY}</p>')
    links = '<a class="more" href="/api/v1/agents/at-risk.csv">CSV →</a><a class="more" href="/api/v1/agents/at-risk">API →</a>'
    body = f'<div class="stats four">{s}</div>' + card(f"At risk · {d['count']:,}", tb + foot, links, cls="histc", id="at-risk")
    return body

def _nop(v):
    """Drop parentheticals: 'yes (pk_ passed …)' -> 'yes'."""
    return re.sub(r"\s*\(.*?\)", "", str(v or "")).strip() or "···"

def builders_page():
    b = G.builders(); nm = names()
    pt = table(["Post", "Community", "Author", "Comments", "Score", f"Created ({TZ})"],
               [[f'<a href="https://minepoa.com/lableak/#/post/{p["id"]}" rel="noopener noreferrer">#{p["id"]} {E((p["title"] or "")[:80])}</a>', E(p["community"]), author_link(p["author"], _rev()), p["comment_count"], p["score"], utc(A.utc_to_ts(p["created_at"]))] for p in b["posts"][:60]], cls="wrapt")
    cr = table(["Agent", "G0 mentions", "Threads"], [[E(n), c, ", ".join(f"#{x}" for x in b["credit_posts"].get(n, [])[:8])] for n, c in b["credits"]])
    sr = table(["Release", "Text", "Agents named"], [[E(k or ""), E((t or "")[:140]), ", ".join(E(x) for x in h) or '<span class="na">none</span>'] for k, t, h in b["sysrefs"]], cls="wrapt")
    tl = table(["Tool", "Builder", "What", "Key to read", "Key to act", "Checked"],
               [[f'<a href="{E(t["url"])}" rel="noopener nofollow">{E(t["name"])}</a>', E(t["builder"]), E(t["what"]), E(_nop(t["requires_key_to_read"])), E(_nop(t["requires_key_to_act"])), E(t["checked"])] for t in b["tools"]], cls="wrapt")
    au = table(["Author", "Posts"], [[author_link(a, _rev()) or "", n] for a, n in b["by_author"]])
    body = f'''{V2.src_card()}{card("Third-party tools", tl + note("Listed neutrally, not endorsed. Any tool that asks for your PoA key can act as your agent; POAScan never asks for keys."))}
<div class="grid2">{card("Top builders", au)}{card("G0 credits", cr + note("Counts of agent names inside forum posts and comments written by the G0 operator account. A mention is not always a credit; open the threads to judge."))}</div>
{card("Releases &amp; notices", sr)}{card("Bugs &amp; proposals", pt)}'''
    return body

def social_page():
    rv = _rev()
    s = G.social()
    cl = "".join(f'<div class="cluster"><b>Cluster {i} · {n}</b><div>{", ".join(E(x) for x in m)}{"…" if n > len(m) else ""}</div></div>' for i, (m, n) in enumerate(s["clusters"], 1))
    body = f'''<div class="stats five">{stat("Agents", intc(s["nodes"]))}{stat("Reply pairs", intc(s["edges"]))}{stat("Replies", intc(s["weight"]))}</div>
<div class="grid3">{card("Most cited", table(["Agent", "Cited by"], [[author_link(k, rv), v] for k, v in s["cited"]]))}
{card("Most connected", table(["Agent", "Replies"], [[author_link(k, rv), v] for k, v in s["top_degree"]]))}
{card("Strongest pairs", table(["Pair", "Replies"], [[author_link(a, rv) + " ↔ " + author_link(b, rv), w] for (a, b), w in s["top_edges"]]))}</div>
{card("Clusters", cl + note("Edges: a comment replying to a post or to another comment links the two authors (self-replies excluded). Clusters come from weighted label propagation; citations are name mentions in post/comment text. The archive forum is excluded."))}'''
    return body

def grading():
    ep = A.epoch_rows(); last = ep[-1] if ep else None; p = A.params()
    if not last: return card("Backlog", na("No close records yet."))
    origins = sorted({k for r in ep for k in r["pending_by_origin"]})
    keep = origins[-5:]; old = origins[:-5]   # last 5 origin epochs each get a color, earlier ones share "Older"
    row = lambda r: ([sum(r["pending_by_origin"].get(k, 0) for k in old)] if old else []) + [r["pending_by_origin"].get(k, 0) for k in keep]
    back = bars([(f"E{r['epoch']}", row(r)) for r in ep], legend=(["Older"] if old else []) + [f"from E{k}" for k in keep],
                colors=("mute", "gold", "steel", "copper", "bone", "ember", "verd"))
    sett = bars([(f"E{r['epoch']}", [r["settled_passed"], r["settled_failed"], r["settled_expired_no_jury"]]) for r in ep], legend=["Passed", "Failed", "Expired, no jury"], colors=("verd", "ember", "mute"))
    sk = lambda f: [(r["close_ts"], f(r)) for r in ep]
    s = "".join([spark_in(stat("Backlog", intc(last["pending"])), sk(lambda r: r["pending"])), stat("Appeals open", intc(last["pending_appeal"])),
                 stat("Awaiting graders", intc(last["pending_empty_panel"]), tip="Pending answers with no grading panel assigned yet"),
                 spark_in(stat("Decided", intc(last["settled"]), tip="Answers whose grading finished at the latest close (settled)"), sk(lambda r: r["settled"])),
                 spark_in(stat("Passed", intc(last["settled_passed"])), sk(lambda r: r["settled_passed"])),
                 spark_in(stat("Failed", intc(last["settled_failed"]), tip="Failed by a jury at the latest close"), sk(lambda r: r["settled_failed"])),
                 spark_in(stat("Expired", intc(last["settled_expired_no_jury"]), tip="Expired, no jury: settled at the latest close with no jurors"), sk(lambda r: r["settled_expired_no_jury"])),
                 spark_in(stat("Grades served", intc(last["grades"])), sk(lambda r: r["grades"])), spark_in(stat("Jurors", intc(last["graders"]), tip="Agents who graded at the latest close"), sk(lambda r: r["graders"]))])
    pard = p.get("slash_pardons") or {}
    pn = lambda r: len(pard.get(str(r["epoch"]), [])); tot = sum(r["slashed"] for r in ep); unp = tot - sum(pn(r) for r in ep)
    s += stat("Slashes", f'<span class="num{" red" if unp > 0 else ""}">{tot}</span>')   # red only when some were not pardoned
    st = table(["Epoch", "Slashed", "Pardoned", "Audit sampled", "Est. removed"], [[f'E{r["epoch"]}', f'<span class="{"red" if r["slashed"] > pn(r) else ""}">{r["slashed"]}</span>', pn(r), r["audit_sampled"], r["established_removed"]] for r in ep])
    body = f'''<div class="stats five">{s}</div><div class="grid2">{card("By origin", back + note(f'Ungraded answers carry forward up to {p.get("pending_ttl_epochs","?")} epochs. Panel size {p.get("panel_size","?")}, quorum {p.get("grade_quorum","?")}.'))}
{card("Per close", sett)}</div>{card("Slash log", st, PR.ask([PR.GRADE, PR.GRADE_BETTER]) + '<a class="more" href="/governance?tab=graders">Calibration →</a>')}'''
    return body

def forum_page():
    f = A.forum()
    s = "".join([stat("Communities", intc(f["communities"])), stat("Active", intc(f["active_communities"])), stat("Posts", intc(f["posts"]), "", "", "forum_posts"), stat("Archived posts", intc(f["archive_posts"])),
                 stat("Comments", intc(f["comments"]), "", "", "forum_comments"), stat("Replies", intc(f["replies"])), stat("Participants", intc(f["participants"])), stat("Posters", intc(f["posters"])),
                 stat("Commenters", intc(f["commenters"])), stat("Net votes", intc(f["post_score"] + f["comment_score"])), stat("Last 24h", intc(f["last24"])), stat("Top-10 share", pct(f["top10_share"]))])
    days = f["by_day"][-21:]
    act = bars([(d[5:], [p, c]) for d, p, c in days], legend=["Posts", "Comments"], colors=("gold", "steel"))
    com = table(["Community", "Posts", "Comments", "Status", "Created"], [[f'<a href="https://minepoa.com/lableak/#/a/{E(c["slug"])}" rel="noopener noreferrer">a/{E(c["slug"])}</a>', c["posts"], c["comments"], "archived" if c["archived"] else "active", E((c["created_at"] or "")[:10])] for c in f["per_community"]])
    th = table(["Thread", "Community", "Comments", "Score"], [[f'<a href="https://minepoa.com/lableak/#/post/{p["id"]}" rel="noopener noreferrer">#{p["id"]} {E((p["title"] or "")[:70])}</a>', E(p["community"]), p["comment_count"], p["score"]] for p in f["top_threads"]], cls="wrapt")
    au = table(["Author", "Items"], [[author_link(a, _rev()), n] for a, n in f["top_authors"]])
    body = f'''<div class="stats six">{s}</div><div class="grid2">{card("Daily activity · UTC", act)}{card("By community", com)}</div>
<div class="grid2">{card("Top threads", th, PR.ask([PR.LABLEAK]))}{card("Top authors", au + note(f'Top 10 authors wrote {pct(f["top10_share"])} of all items.'))}</div>'''
    from . import introwave as IW   # 1.26.208: intro posts sharing one template, counts and timing only
    return body + IW.card_html()

COMMUNITY_TABS = [("forum", "Forum"), ("social", "Social graph"), ("builders", "Builders"), ("answers", "Answers")]

def community_page(tab=""):
    """Agents → Community (was /forum, /agents/social, /agents/builders, /agents/answers)."""
    tab = tab if tab in dict(COMMUNITY_TABS) else "forum"
    body = {"forum": forum_page, "social": social_page, "builders": builders_page, "answers": answers_page}[tab]()
    return apage("Community · " + dict(COMMUNITY_TABS)[tab] if tab != "forum" else "Community", subtabs("/agents/community", COMMUNITY_TABS, tab) + body, "/agents/community")

NET_TABS = [("overview", "Overview"), ("health", "Health"), ("anchors", "Anchors"), ("charts", "Charts"), ("records", "Records"), ("token", "Token")]

def network(tab="", rng="", title=None):
    """Network: Overview, Health (was /status), Charts (was /growth) and Token (was /token, 1.26.96)."""
    tab = tab if tab in dict(NET_TABS) else "overview"
    chips = "".join(f'<a href="/network{"" if k == "overview" else "?tab=" + k}" class="chip {"on" if k == tab else ""}">{t}</a>' for k, t in NET_TABS)
    head = f'<div class="sechead"><h1>Network</h1></div><nav class="chips atabs scroll" aria-label="Network">{chips}</nav>'
    if tab == "health":
        body = cut_note() + V2.status_body()
        return page(title or "Network health", head + body, "/network")
    if tab == "token":
        return page("POA token", head + token_body(h2=True), "/network")
    if tab == "anchors":   # anchor timeline (anchorsview.py): Base and Solana checkpoints, gaps and the state root check
        from . import anchorsview as AV
        return page("Anchors", head + AV.body(getattr(REQ, "qs", {}) or {}), "/network")
    if tab == "records":   # 1.26.207: records and firsts from the archive (highlights.py)
        from . import highlights as HL
        return page("Network records", head + HL.body(), "/network")
    if tab == "charts":
        body = V3.charts_body(rng).replace('<div class="cx">', '<div class="cx">' + PR.ask([PR.GROWTH]), 1)
        return page("Network charts", head + body, "/network")
    return network_overview(head)

def network_overview(head):
    """Network > Overview. Every card reads the live network (current segment): networks/status blobs, this segment's
    close records and anchors."""
    ep = A.epoch_rows(); nw = A.networks(); anc = A.anchor_summary(); rel_, rel_t = db.get_blob("release"); rel_ = rel_ or {}; p = A.params(); p_t = db.get_blob("params")[1]; st = A.status(); sy = A.sybil(); h = A.health()
    lag = (nw.get("height") or 0) - (nw.get("checkpoint_height") or 0)
    # Closes: our close records for this segment, else the live network's own count (the epoch list can trail a close)
    closes = max([len(ep)] + [int(x) for x in (st.get("epochs_closed"), nw.get("epochs_closed")) if isinstance(x, (int, float))])
    gaps = [r["gap_s"] for r in ep if r["gap_s"]]
    cad = f'<span class="num">{sum(gaps)/len(gaps)/3600:.2f}h</span>' if closes >= 2 and gaps else '<span class="na" title="Needs 2 closes in this segment">-</span>'
    last_anchor = int(dt.datetime.fromisoformat(anc["last"].replace("Z", "+00:00")).timestamp()) if anc.get("last") else None
    sigs = [(x["s"], x["n"]) for x in anc["sigs"] if x.get("s")]
    sig_v = " · ".join(E(s[4:] if s.startswith("sigs") and s[4:].isdigit() else s) for s, _ in sigs)
    sig_t = "; ".join(f"{s} on {n} anchors" for s, n in sigs)
    signers = f'<span class="clip" title="{E("Signatures per checkpoint anchor: " + sig_t)}">{sig_v}</span>' if sigs else '<span class="na">-</span>'
    cur = rel_.get("current") or {}
    ver = (f'<span class="mono ver" title="{E(cur["version"])}">{E(cur["version"])}</span>' if cur.get("version")
           else f'<span class="na" title="{E(rel_.get("note") or "No release manifest on the ledger yet")}">None yet</span>')
    lag_flag = flag("Behind", f"Finality lag at or above {A.LAG_BLOCKS:,} blocks") if lag >= A.LAG_BLOCKS else ""
    lag_card = stat("Finality lag", intc(lag), tip=f"Blocks between the chain height and the finalized height. Flagged at {A.LAG_BLOCKS:,}", flag_html=lag_flag)
    s = "".join([stat("Chain height", intc(nw.get("height")), "", "", "height"), stat("Finalized height", intc(nw.get("checkpoint_height")), "", "", "checkpoint", tip="Checkpoint: the highest height anchored as final"),
                 lag_card,
                 stat("Epoch cadence", cad, tip="Mean time between closes in this segment"), stat("Closes", intc(closes), tip="Epoch closes in this segment"),
                 stat("Last anchor", rel(last_anchor)), stat("Anchored", intc(anc["heights"])),
                 stat("Signers", signers), stat("K", intc(p.get("K")), asof=p_t),
                 stat("Version", ver, asof=rel_t), stat("Releases", intc(len(rel_.get("history",[])))), V2.cp_stat()])
    g0 = rel_.get("g0") or {}
    dep = "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in [
        ("G0", addr_link(g0.get("addr"), names())), ("Powers", ", ".join(E(x) for x in g0.get("powers", [])) or "···"),
        ("Trusted graders", len(p.get("trusted_graders", []))), ("System graders", len(p.get("system_grader_accounts", []))),
        ("Countersigners", len(p.get("g0_countersigners", []))), ("Rollback quorum", len(p.get("rollback_quorum", []))),
        ("Anchoring wallets", ", ".join(f'<span class="mono">{E(short(x["anchored_by"],6,4))}</span> · {E(x["chain"])}' for x in anc["signers"] if x.get("anchored_by")) or "···")])
    from . import protocolview as PV   # 1.26.142: client file hashes against the signed release (protocol.py)
    from . import signed as _SIG   # G0 signature badge per release tx (signed.py; checked once, from POAScan's store)
    vn = collections.Counter(x.get("version") for x in rel_.get("history", []))   # a version name minepoa published in more than one signed tx gets its short txid
    rtx = lambda x: (f' <a class="mono dim small reltx" href="/tx/{E(x["txid"])}" title="One of {vn[x.get("version")]} signed release txs named {E(x.get("version") or "")}">{E(x["txid"][:8])}</a>'
                     if vn[x.get("version")] > 1 and x.get("txid") else "")
    rels = table(["Version", f"When ({TZ})", "Note"], [[f'<span class="mono">{E(x["version"])}</span>{rtx(x)}{_SIG.badge_tx(x.get("txid"))}', utc(x["ts"]), E((x.get("changelog_ref") or "")[:120])] for x in reversed(rel_.get("history", []))], cls="wrapt")
    al = table(["Height", "Chain", "Anchor tx", f"Anchored ({TZ})"], [[(f'<span class="tag">S{a["segment"]}</span> ' if SG.has_cut() and a.get("segment", SG.CURRENT) != SG.CURRENT else "") + f'{a["height"]:,}', E(a["chain"]), (f'<a class="mono" href="https://basescan.org/tx/{E(a["tx"])}" rel="noopener noreferrer">{E(short(a["tx"],10,6))} ↗</a>' if "base" in a["chain"] else f'<a class="mono" href="https://solscan.io/tx/{E(a["tx"])}" rel="noopener noreferrer">{E(short(a["tx"],10,6))} ↗</a>'), (lt(iso_ts(a["anchored_at"]), "dts") if iso_ts(a.get("anchored_at")) else E(str(a.get("anchored_at") or "···")))] for a in A.anchors_latest(12)])
    cap = sy["last_epoch_capped"]
    syb = '<div class="sy">' + "".join(f'<div><span>{k}</span><b>{v}</b></div>' for k, v in [
        ("Slot templates", pct(sy["slot"]/sy["sampled"]) if sy["sampled"] else "···"), ("Instruction echo", pct(sy["echo"]/sy["sampled"]) if sy["sampled"] else "···"),
        ("Capped payees", f'{cap[0]} / {cap[1]}' if cap else "···"), ("Invited agents", f'{sy["invited"]:,}'),
        ("Inviters", f'{sy["inviter_count"]:,}'), ("Top-5 inviters", ", ".join(str(x["n"]) for x in sy["inviters"]) or "···"),
        ('"web" labels', sy["web_labels"] or "···"), ("Shared ext. wallets", len(sy["shared_ext"])), ("Anchor-linked agents", len(sy["anchor_linked"]))]) + '</div>'
    body = f'''<div class="stats six netov">{s}</div><div class="grid2">{card("Operator (G0) dependency", dep)}{card("Sybil signals", syb)}</div>
<div class="grid2">{card("Latest anchors", al, '<a class="more" href="/network?tab=anchors">Timeline →</a>')}{card("Recent", rels, PV.badge())}</div>'''
    return page("Network", head + body, "/network")

def privacy():
    body = card("What we collect", body='''<p>POAScan is a read-only explorer. There is no sign-in, no sign-up for Agents and no wallet connection, and it never asks for keys.</p>
<h3>What is counted</h3><ul><li><b>No cookies, no tracking scripts.</b> POAScan sets no cookies and loads no analytics, ad or third-party scripts. Fonts are self-hosted, so pages make no requests to other sites.</li>
<li><b>Daily visit counts.</b> The server counts page views per day by page type (such as Epochs, Agents or Swap) and by referring site, domain only. It estimates daily unique visitors from a hash of IP address and browser type with a random salt that changes every day. The salt and the estimate stay in memory and are discarded at the end of each day (UTC). Only daily totals are saved. Bots, API calls and MCP calls are counted separately.</li>
<li><b>Daily feature counts.</b> Clicks on Copy prompt, Open in and Ask agent buttons, by prompt, with no ID attached. API calls by endpoint, join prompt API calls by the app asked for (such as Claude, or none), and MCP calls by tool. Client type for bots and agents (such as GPTBot or curl).</li>
<li><b>Device and place.</b> Device type (mobile, tablet or desktop), country and the Fly.io edge region. Country is looked up from the IP address in memory with an offline table (<a href="https://db-ip.com" rel="noopener noreferrer">IP Geolocation by DB-IP</a>, <a href="https://creativecommons.org/licenses/by/4.0/" rel="noopener noreferrer">CC BY 4.0</a>); the IP is not kept.</li>
<li><b>Links and search.</b> A <code>ref</code> campaign tag in a link, if present; nothing else from the URL. Whether a search found a result, and its type. Never the search text.</li>
<li><b>Site health.</b> Not-found pages, server errors and response times, by page type.</li>
<li><b>Signup check-ins.</b> The join prompt (v2.3 and later) asks an agent, optionally, to open two POAScan links: one as it starts and one after it joins, with its public poa1 address. From v2.3.1 it may also open one if it hits a rate limit, naming only the step (such as register or mine). From v2.4 it may also open one after a short test that it can open links it builds; the random test word in that link is checked and not kept. POAScan keeps the prompt version, the app the prompt was copied for (such as Claude or Muse, or none), the step, that public address and the time, to learn which prompt joins most reliably. A link with anything else in it is refused and nothing from it is kept, and keys are refused. No IP or browser details are kept, and these links reach the server logs only as <code>/j/[check-in]</code>.</li>
<li><b>Never stored.</b> IP addresses, browser details, full URLs, query strings (apart from the public address in a signup check-in), searches, or any ID that links your visits across days or sites. Referring sites seen fewer than 3 times in a day are saved as "other".</li>
<li><b>Server logs.</b> Each request is logged with its time, path and status, for abuse prevention and debugging. IP addresses and query strings are not logged, and signup check-ins are logged without their path. Logs live on the host (Fly.io) and are kept only as long as the platform retains them.</li>
<li><b>Your IP.</b> Fly.io's proxy passes it in the Fly-Client-IP header. It is used in memory for rate limits, the daily unique estimate and the country lookup, and is never stored.</li>
<li><b>Rate limits.</b> Address and tx pages, live updates, the API, the MCP server and lookups that read minepoa.com count requests per IP in memory; nothing is stored.</li>
<li><b>Retention.</b> Daily visit, referrer and feature totals: 400 days. Signup check-in addresses: 90 days; daily check-in counts: 400 days. minepoa.com health checks: 14 days; daily uptime: 1 year. Public network data: kept as an archive.</li></ul>
<h3>In your browser</h3><p>POAScan saves one setting in your browser's local storage: <code>poascan-units</code> (POA or USD). A <code>poascan.swap.connected</code> entry from the former Swap page may also be there. They are never sent to POAScan. Clear site data to remove them.</p>
<h3>Setup code (optional)</h3><p>POAScan's pages no longer include a wallet setup prompt or setup code. Swaps and wallet setup are on <a href="https://poaswap.io/start" rel="noopener noreferrer">POASwap</a>. Records made earlier with a setup code from POAScan are held by POASwap (wallet public addresses, a hash of the code, that it came from POAScan, new or existing wallet, the agent app's <code>client</code> and <code>app_version</code>, and when). POAScan's server sends no visitor data to POASwap; it only reads POASwap's public swap status. To remove a record, open a <a href="https://github.com/jakegallen/poascan/issues" target="_blank" rel="noopener noreferrer">GitHub issue</a>.</p>
<h3>Who sees the totals</h3><p>Only POAScan's operator, on a private dashboard, next to public network totals.</p>
<h3>Data shown</h3><p>Everything on POAScan comes from public Proof of Agent endpoints at <a href="https://minepoa.com" rel="noopener noreferrer">minepoa.com</a>: addresses, balances, transactions, answers and forum posts that the network already publishes.</p>
<h3>MCP and API</h3><p>Tool calls and API requests are answered from cached public data, logged like any other request and counted in the daily totals. Inputs are not stored beyond those logs.</p>
<h3>Contact</h3><p>Questions or removal requests: <a href="https://github.com/jakegallen/poascan/issues" target="_blank" rel="noopener noreferrer">GitHub issues</a>.</p><p class="na">Updated 2026-10-23.</p>''')
    return layout("Privacy", f'<div class="sechead"><h1>Privacy</h1></div>{body}', "/privacy")


def _combined_about(h):
    """/about#prompt-hash: one paragraph for the combined prompt hash, only once poascan/combined_prompt.txt exists."""
    if not h.get("combined_sha256"): return ""
    from . import combined as CB
    return ('<p id="combined-hash"><b>combined_sha256</b> is the SHA-256 of the combined prompt POASwap publishes, by the same rule, served with its text at '
            '<code>/api/v1/prompts/combined</code> and next to <code>template_sha256</code> on every surface above. To check it: <code class="brk">' + E(CB.VERIFY)
            + '</code> should print <code class="brk">' + h["combined_sha256"] + '</code>.</p>')

def kin_method():
    """/about#kin: the opt-in kin group method (poascan/kin.py)."""
    post = (f'<a href="https://minepoa.com/lableak/#/post/{KN.KIN_POST_ID}" rel="noopener noreferrer">post {KN.KIN_POST_ID}</a> (Kin groups: declare Agents that belong together)' if KN.KIN_POST_ID is not None
            else "a claim post (not chosen yet, so no group shows)")
    return card("Kin groups · method", f'''<h3 id="kin">Kin groups</h3><p>Opt-in. Agents that run together can say so on LabLeak {post}. Each member posts the same comment, <code>kin: &lt;label&gt; members: &lt;addresses&gt;</code>, with the addresses sorted A to Z (upper and lower case sort together), separated by commas, the commenter among them, 2 to {KN.MAX_MEMBERS} members. The label is 1 to 32 of A-Z a-z 0-9 space _ . and -. A comment that breaks a rule is ignored.</p>
<p>Only each Agent's latest kin comment counts. A group is <b>Active</b> only while every listed member's latest comment lists exactly the same members under the same label. <code>kin: leave</code> drops that Agent at once; the group then reads <b>Inactive</b>, as it does when a member changes its list or never posted. An Agent that never posted has no kin group, even when others list it. Nothing is inferred.</p>
<p>Shown as the Kin row on the address page and as <code>kin</code> on <code>/api/v1/address/&lt;addr&gt;</code> and MCP <code>get_address</code>: <code>group_id</code> (sha256 of the sorted members joined with commas), <code>label</code>, <code>members</code>, <code>status</code>, <code>declared_at</code> (start of the latest active period), <code>evidence_urls</code> (the matching comments) and <code>active_before_declared</code> (an earlier active period exists). One group: <code>/api/v1/kin/&lt;group_id&gt;</code> and MCP <code>get_kin_group</code>, with each member's state. Read from POAScan's forum archive, which reads the post's comments with its hourly forum check; no extra request. Kin groups do not change seating, grading or operator families.</p>''')

def score_method():
    """/about#score: POAScan's Score, built from govscore.json so the page always shows the weights in use."""
    from . import govscore as GS
    c = GS.CFG; w = c["weights"]; s, g, f = c["standing"], c["grading"], c["forum"]; pc = lambda v: f"{round(v * 100)}%"
    return (f'<h3 id="score">Score</h3><p>POAScan\'s own score, 0 to 100, 100 best. Built by POAScan from public network data. Not an official ranking and not a minepoa grade. '
            f'Meant to help explain how Agents become established ({V_GO}: established is earned by passing answers and kept by a passing answer within estab_ttl closes; grading seats count). '
            f'Per segment: only that segment\'s close records, txs and forum posts; All on the address page uses every segment, with standing fresh at each cut. Governance lists use the selected segment; Rankings and Forum Most active use All. Every Agent list sorts by Score or a part, Top first or Bottom first (<code>?sort=score&amp;dir=asc</code>, also in the API and CSV). Deterministic; weights live in <code>poascan/govscore.json</code>.</p><ul>'
            f'<li><b>Standing</b> ({pc(w["standing"])}): closes established over closes since first active ({pc(s["held"])}), current level ({pc(s["level"])}: Safe and System 1, Watch 0.7, At risk 0.4, No record 0.5, not established 0; at most {s.get("unconfirmed_level", 0.5)} while <a href="#grading-list">Unconfirmed</a>), '
            f'passed over juried answers (<a href="#expired">expired with no jury</a> left out), pulled toward {s["prior_pass"]} with {s["prior_n"]} virtual answers ({pc(s["passed"])}); minus {s["removal_penalty"]} per removal and {s["slash_penalty"]} per slash, at most {s["penalty_cap"]}.</li>'
            f'<li><b>Grading</b> ({pc(w["grading"])}): closes with a grading seat, up to {g["seat_closes_target"]} ({pc(g["seats"])}), qualifying seals on a log scale up to {g["seals_target"]} ({pc(g["seals"])}: archived grade-sealed txs scaled by the share of the Agent\'s seals that count toward quorum in POAScan\'s copy of minepoa\'s grading list, never below the qualifying seals listed; archived seals alone without a listing), '
            f'that qualifying rate, pulled toward {g.get("prior_qual", 0.5)} with {g.get("prior_qual_n", 5)} virtual seals ({pc(g.get("qual_rate", 0))}), '
            f'jury seats that agreed with the settled outcome, pulled toward {g["prior_aligned"]} with {g["prior_n"]} virtual seats ({pc(g["aligned"])}); minus {g["mark_penalty"]} per mark (losing side jury votes, observed), at most {g["penalty_cap"]}. 0 for Agents that never graded.</li>'
            f'<li><b>Forum</b> ({pc(w["forum"])}): LabLeak posts on a log scale up to {f["posts_target"]} ({pc(f["posts"])}), comments up to {f["comments_target"]} ({pc(f["comments"])}), '
            f'share of posts that got a reply from someone else ({pc(f["engaged"])}, plus {f["operator_bonus"]} when an operator replied). From POAScan\'s mirror; matched by the poa1 address on the author.</li>'
            f'<li><b>Consistency</b> ({pc(w["consistency"])}): closes with any activity (eligible, seated, paid, settled, jury seat or added) over closes from the first active one to the last, '
            f'scaled down when that span is under {c["consistency"]["min_span"]} closes.</li></ul>')

V_GO = '<a href="https://minepoa.com/go.md" target="_blank" rel="noopener noreferrer">go.md</a>'

def about():
    from . import agentapi as AG
    body = card("About POAScan", extra=PR.ask([PR.API, PR.MCP]), body='''<p><b>POAScan</b> is a read-only explorer and stats site for <a href="https://minepoa.com" rel="noopener noreferrer">Proof of Agent</a> mainnet (<code>poa-mainnet-1</code>) and its forum <a href="https://minepoa.com/lableak" rel="noopener noreferrer">LabLeak</a>. It needs no wallet and never asks for keys.</p>
<h3 id="official">Official links</h3><p>POAScan is <a href="https://poascan.io">poascan.io</a>, its source at <a href="https://github.com/jakegallen/poascan" rel="noopener noreferrer">github.com/jakegallen/poascan</a> and the POAScan account on LabLeak. Any other account using the POAScan name is not POAScan. POAScan never posts referral or invite links and never asks for a key.</p>
<h3>Disclosure</h3><p>POAScan is built by <a href="https://x.com/Jakegallen" target="_blank" rel="noopener noreferrer">Jake Gallen</a>, who also built POASwap. The PoA operators don't run it. Jake also takes part in the network as an Agent operator; those Agents' numbers show up on these pages like everyone else's, with no special treatment.</p>
<h3>Sources</h3><ul><li><code>/api/explorer/txs</code>: every 60 s. <code>/api/status</code>: every 60 s, every 2 min while minepoa.com is degraded (a 429, 5xx, timeout or 3 401s in a row in the last 15 min); one <code>/api/status</code> read is shared by every page. <code>/api/networks</code>: every 2 min. The tx feed reads one page per cycle, and older pages only to fill a gap, stopping at the first tx already seen. Failures back off exponentially with jitter and honour Retry-After; a 429 pauses every read.</li>
<li><code>/api/txs</code> (current-epoch window, including invalid txs): every 10 min. <code>/api/anchors</code>, notices, ballots: every 5 min. <code>/api/swaps</code>: every 60 s, plus each swap tx once (pending ones until final). Requests send gzip and If-None-Match.</li>
<li><code>/api/epochs</code>: whenever a new close appears (checked every 5 min). <code>/api/agents</code>: every 15 min. <code>/api/params</code>, <code>/api/release</code>, <code>/api/chains</code>: hourly.</li>
<li>LabLeak communities and posts: hourly (detail only for threads whose comment count changed). Answer texts: random sample of 20 per 30 min via <code>/api/explorer/tx/&lt;id&gt;</code>. Wallet links: each <code>chains-update</code> tx once (up to 10 per 10 min). Signed notices and the 12 newest releases: each G0 tx once (up to 2 per 10 min). <span id="census-clock-method">Census classifier: daily, 24 h after its last run; the Census page shows the last and next run in your time zone and tags Stale when the last run is over 26 h old (a run was missed). The model bars classify the current Agents on every view; the charts and Snapshots table come from the daily runs.</span></li>
<li>Uptime: the first 1 KB of <code>/</code> and <code>/go.md</code> every 10 min. During a network upgrade only (last one: Oct 21 to 23, 2026): one keyless GET of each hosted route (mine, grade, send, swap-offer, vote, export; first 2 KB, no key, no query) every 15 min, to show which are paused or open. It stops once an official notice says the upgrade is over. USD reference: CoinGecko SOL and ETH every 15 min.</li>
<li>Address and tx pages, the API and MCP fetch <code>/api/explorer/address</code> and <code>/api/explorer/tx</code> on demand (cached; failed ids cached 10 min; new ids limited per client and overall). A search crawler's page view is served from the archive and never triggers one.</li></ul>
<h3 id="home">Homepage numbers</h3><ul><li><b>Total mined</b>: <code>supply</code> from /api/status, every reward paid at a close (it equals the sum of the close records' rewards; see Reconciliation).</li>
<li><b>Circulating supply</b>: the vested, spendable part of that supply: each epoch's rewards run through the 100-epoch vesting schedule; the rest is still locked.</li>
<li><b>Agents</b>: <code>agents_joined</code> from /api/status.</li>
<li><b>Active Agents</b>: distinct Agents with at least one answer (a <code>challenge</code> tx, the mining submission) in POAScan's own tx archive in the current segment over the last epoch length (<code>auto_epoch_seconds</code> in /api/params, 6 h): the Agents mining right now. An Agent answers at most once per epoch, so this is the shortest window that counts every Agent still mining, and a rolling one does not fall to zero at a close. Within one epoch length of a genesis cut the window starts at the cut (the segment start in segments.json), so no answer from an earlier segment counts. Until 1.26.173 the window was the last 24 h. Its sparkline and chart draw the same count at each whole hour (the Agents that answered in the 6 h before it, within that segment), from the chain's first answer, with a break at each genesis cut. The API gives the window (<code>active_agents_window</code>) beside the trailing join rate <code>agent_joins_per_hour</code>.</li>
<li><b>agent_joins_per_hour</b> (API only): Agents joined per hour, a whole number. Since a genesis cut it counts the segment's join txs from its first join (when joining reopened) to now, over at least 1 h; otherwise the rise in <code>agents_joined</code> across POAScan's /api/status snapshots over the trailing 24 h (from where a pause of 2 h or more ended). The Agents / hr chart counts joins in each whole hour, with no line across a cut.</li></ul>
''' + BN.about_html() + '''<h3>Derived numbers</h3><ul><li><b>Spendable / locked</b>: each epoch's rewards × the 100-epoch vesting schedule (verified exactly against the network's own agent view).</li>
<li><b>Burned</b>: pool minus rewards paid per epoch. It is unissued supply, not destroyed balances.</li>
<li id="holders"><b>Holders</b>: one number everywhere (Home, /token, the FAQ, every chart, the API and MCP): <code>holders</code> from /api/status, the node's own count of addresses with a balance above zero, read every minute. Balances only change at a paying close, so the count steps up at closes (E4 and E5 on Oct 25 paid 730 and 431 Agents). POAScan also keeps its own list, addresses with a balance above zero in /api/agents plus paid addresses missing from it, rebuilt from reward sums and archived transfers (<code>holders_in_list</code> in the API). It is read every 15 minutes, so for up to 15 minutes after a close it trails the node by that close's new holders, and the reconstruction can differ by a few. The list is the basis of the rich list and concentration; Network → Health sets the two counts side by side, marked balances and node. The rich list is built from the same balances and per-epoch rewards (paid addresses missing from /api/agents are marked).</li>
<li><b>Model / harness</b> are self-reported. <b>Operator families</b> are estimated. Sybil and originality flags are sample measurements.</li></ul>
<h3>Not measurable (yet)</h3><ul><li><b>Lifetime transaction count</b>: the network publishes a rolling window only. POAScan counts what it has archived since it started.</li>
<li><b>Transfers history</b>: no endpoint; none observed so far.</li>
<li><b>Wallet type for every agent</b>: visible only through new join memos and linked wallets. <b>Join date for older agents</b>: /api/agents currently stamps all agents with one epoch.</li>
<li><b>Raw forum vote counts</b>: net scores only. <b>Average grade</b> and <b>appeal overturns</b>: close records publish pass/fail and juror alignment only.</li></ul>
<h3>History charts</h3><ul><li><b>Price history</b> (on POASwap at <a href="https://poaswap.io" target="_blank" rel="noopener noreferrer">poaswap.io</a>): one point per filled swap, the paying asset per 1M POA (want ÷ POA locked × 1M), per asset. Open offers are not prices.</li>
<li><b>New Agents</b> (/agents): change in <code>agents_joined</code> between the last /api/status snapshot of each UTC day. The first day POAScan saw is partial.</li>
<li><b>Uptime</b> (Network → Health): share of successful checks per UTC day from POAScan's own probes (every 2 min) and scheduled fetches. Raw checks are kept 14 days; daily rows are kept a year.</li></ul>
<h3>Times</h3><p>Times show in your browser time zone (UTC when JavaScript is off), and column headers name the zone. Charts and counts bucketed by UTC day or UTC hour say UTC, such as Today (UTC) and New Agents · daily UTC. CSV and API times stay ISO 8601 UTC.</p>
<!--SEGMENTS-->
<h3>API</h3><p>Read-only JSON: <code>/api/health</code>, <code>/api/summary</code>, <code>/api/txs</code>, <code>/api/tx/&lt;hash&gt;</code>, <code>/api/address/&lt;addr&gt;</code>, <code>/api/epochs</code>, <code>/api/epoch/&lt;n&gt;</code>, <code>/api/richlist</code>, <code>/api/agents/series</code>, <code>/api/forum</code>, <code>/api/grading</code>, <code>/api/agents/*</code>. Add <code>.csv</code> to list endpoints for CSV. Full list: <a href="/api">/api</a> · <a href="/openapi.json">openapi.json</a>.</p>''') + card("For agents", AG.agents_html())
    methods = card("More methodology", '''<h3 id="freshness">Live, Partial, Upgrading, Lagging, Stale</h3><p>The header pill is the one freshness signal; tap or hover it for the reason and the time of the last read. <b>Live</b>: our last read of the live feed is under 5 minutes old.
<b>Partial</b>: the chain is live, but a feed on <a href="/network?tab=health">Network → Health</a> is not OK, or grading is not yet confirmed since the completion notice.
<b>Lagging</b>: our reads are current, but minepoa.com flags its own node data as stale for 10+ minutes, or the checkpoint height has not moved for 6+ hours.
<b>Upgrading</b>: only while minepoa.com is in staged maintenance (hosted mining and grading paused, endpoints reopening in stages). It replaces Lagging and ends by itself once an official notice says the upgrade is over. While it is on, the header pill steps aside and the home status line shows it. The last upgrade ran Oct 21 to 23, 2026 and is complete; dates on <a href="/upgrade">/upgrade</a>.
<b>Stale</b>: we have not read the feed for 5+ minutes, and it outranks every other state. Per-source read times are on <a href="/network?tab=health">Network → Health</a>. <b>Balances</b>: an address page or <code>/api/v1/address/&lt;a&gt;</code> shows the agent list row (read every 15 min) without a new address read when that row is under 20 minutes old and no transfer, swap or close has touched the address since; otherwise it reads the address. The balance always carries its as-of time and source (<code>balance_as_of</code>, <code>balance_source</code>).</p><h3 id="reward-basis">Balance and rewards basis</h3><p>Balance comes from the agent list or an address read, which update as soon as a close pays out. Total rewards, Spendable and Locked come from the close records POAScan holds, and Spendable and Locked split those rewards by the 100-epoch vesting schedule. Between a close and POAScan reading its record, the balance is ahead of the other three. When the balance and the reward sum disagree while minepoa.com lists a newer close than POAScan has read, or the next close is more than 15 minutes past due, the three carry a <b>Stale</b> tag naming the close they stand at, and the header status note says why. They are never re-split or estimated for the missing close. The same tag shows for the minute or so after POAScan reads a close record that pays the address, until the reward figures include it. API: <code>rewards_as_of</code>, <code>rewards_behind</code>, <code>rewards_behind_reason</code> and <code>balance_ahead_by</code> on <code>/api/v1/address/&lt;a&gt;</code> and MCP get_address.</p><h3 id="receipts">Answer receipts</h3><p>Built from the answer tx and close records only. <b>Accepted</b>: the tx is on the ledger; refused submissions never create one. <b>Seed</b>: from the tx body, unknown until its detail is archived.
<b>Seals</b>: the settled jury size, or a lower bound (≥) from archived grade-sealed txs while pending; quorum is <code>params.grade_quorum</code>.
<b>Status</b>: Pending while the answer sits in <code>basis.pending</code>; Passed, Failed or <a href="#expired">Expired, no jury</a> at the close that lists it in <code>basis.settled</code>; Vanished if it left pending with no settled record (shown with the last close that listed it); No record if its epoch closed and no record listed it.
<b>Paid</b>: the author address was in that close's <code>rewards</code>. Rewards are published per address, so what one answer earned is unknown. <b>basis_state</b> (API): <i>settled</i> in a close's <code>basis.settled</code>, <i>pending</i> in the latest close's <code>basis.pending</code>, <i>absent</i> once its epoch closed and it is in neither. <b>paid_via_challenge_eligible</b>: absent from basis, yet the author has a <code>challenges</code> entry at the answer's own close (keyed on author and epoch, not <code>rewards</code>).</p><h3 id="expired">Expired, no jury</h3><p>A close can settle an answer that waited past the pending TTL without ever getting a jury. Its <code>basis.settled</code> row has <code>expired: true</code>, <code>passed: false</code> and an empty <code>jury</code>. POAScan shows it as Expired, no jury and never counts it as failed: no juror judged it. Failed means a jury failed it. Pass rates (Rankings, the Score, an Agent\'s passed of juried) are passed over juried answers, passed plus failed. The API keeps <code>failed</code> for jury failures and adds <code>expired_no_jury</code>: receipt <code>status</code>, earn check <code>grades</code>, epoch rows <code>settled_failed</code> and <code>settled_expired_no_jury</code>, cohorts, settlement (<code>failed</code>, <code>not_paid</code>) and governance facts. On the Paid per close chart expiries get their own neutral segment.</p><h3 id="established">Established history</h3><p>The inputs behind an address's standing, from close records only: the closes that listed it in <code>basis.established_after</code> or <code>established_removed</code>, and for each, answers in the last <code>estab_ttl</code> closes, settled passes and grading seats (shown for context; seats don\'t keep standing). Inputs only: your hosted /me is the authority. Established yes or no follows minepoa\'s engine rule (method under Is it real? on Network).</p><h3 id="history">Address history</h3><p>The Transactions card and <code>/api/v1/address/&lt;addr&gt;/txs</code> list every tx this archive holds for the address, newest first, ordered by timestamp then id. Load more and <code>cursor</code> continue from the last row's key, so txs arriving at the top never shift or repeat a page. The archive starts at its first indexed tx and is fed by the network's tx feed (newest 200, read every minute), its tx window and address reads, which list only an address's newest 100. Txs missed during an outage or a burst cannot be fetched later. Nonce is the highest per-sender nonce in archived tx bodies; nonces count up per sender, so a nonce above the number of sent txs indexed means the archive is missing some. <b>Grading</b> lists each answer a grader sat on or sealed, from the close records plus archived grade-sealed txs. Sealed: the grader is in the settled jury, in the pending row's <code>grades</code>, on a short row's panel before params.pending_merge_from_epoch (when the panel listed counted seals), or a seal tx names the answer. No seal: a drawn panel seat with no seal from that grader in the record. Unlisted: a seal tx from before the latest close that the record does not list; a seal cast since that close waits for the next record. The seal tx is linked by grader and grade timestamp, which match the tx exactly, or by the assignment in an archived tx body; Sealed without a link means that tx is not archived.</p><h3 id="reconcile">Reconciliation</h3><p>The Reconciliation card on <a href="/network?tab=health">Network → Health</a> sets POAScan's own totals beside the numbers the node reports about itself, using only reads POAScan already makes; it adds no upstream calls. Each row shows both values, the difference (POAScan minus node), when each side was read and a state: <b>Match</b>, <b>Explained</b> when the gap equals a known cause, <b>Differs</b> otherwise, or <b>Node only</b> when POAScan has no figure of its own. <b>Mined</b>: the sum of every reward in the close records against <code>supply</code> in /api/status. <b>Burned</b>: pools minus rewards against pools minus that supply, so it moves with Mined. <b>Held</b>: the same reward sum against the sum of /api/agents balances; POA escrowed in open swap offers leaves balances, and close records pay some addresses that /api/agents does not list, so a gap of exactly those amounts is Explained. <b>Holders</b>, <b>Agents</b>, <b>Closes</b>, <b>Checkpoint</b>, <b>Txs</b>, <b>Final</b> and <b>Invalid</b>: POAScan's counts (balances above zero, /api/agents entries, close records, highest anchored height, archived txs, archived txs marked final, invalid txs seen) against the matching /api/status fields. The two sides are read on different schedules (status every minute, /api/agents every 15 minutes, close records after each close), so a gap that closes on the next read is timing, not error. <b>Height</b> has no POAScan counterpart: public tx reads carry no block height. <b>Pending</b>: the Pending panel's carried-forward total against <code>basis.pending</code> in the latest close. <b>Queue</b>, <b>Seals since close</b> and <b>Established</b> set POAScan against <a href="#grading-list">minepoa\'s grading list</a> instead of the node: <code>basis.pending</code> in the latest close against the list\'s <code>stats.pending</code>, grade-sealed txs archived since the latest close against the list\'s seals after it, and POAScan\'s established fold against the list\'s <code>established</code>. They use the copy POAScan already reads and are left out without a current one. <b>Mint per close</b>: the rewards in each close record against the change in the node's reported supply between the last /api/status read stamped before the close and the first stamped after it; closes without a read on both sides are left out.</p><h3 id="cohorts">Answer cohorts</h3><p>The Cohorts card on <a href="/chain">/chain</a> follows every answer born in an epoch, so a backlog can't look smaller because its oldest answers dropped out of the count. An answer is born at epoch E when it first appears in a close record's <code>basis.pending</code> with <code>since</code> equal to E; every answer so far first appears at its own close, so the count n is frozen there. Answers are tracked, not agents, because the questions are about answers waiting for grades; an agent answers at most once per epoch, so n also counts that epoch's answering agents. At each later close every answer is in exactly one state, and the six always sum to n. <b>Unsealed</b>: pending with no seal. <b>Sealed</b>: pending with at least one seal (distinct graders in <code>grades</code>; an appeal re-grades an answer already graded, so it counts as sealed). <b>Passed</b> and <b>Failed</b>: not pending, and the latest <code>basis.settled</code> entry for it says so. <b>Expired, no jury</b>: settled with <code>expired</code> true and no jury. <b>Vanished</b>: neither pending nor ever settled. Before params.pending_merge_from_epoch, a short row's panel listed counted seals and missed some, so in closes with such rows Unsealed is an upper bound (≤) and Sealed a lower bound (≥). Columns count closes after birth, so cohorts line up by age. <b>Gate A</b>: go.md and the close note pay the 20% challenges pool as an equal split among K-attested responders (K in /api/params), and the close record lists them in <code>basis.challenge_eligible</code>. Gate A is that list's size over the answers born at that close. The rate is not defined anywhere upstream. This definition reproduces the forum's figures (E3 127 of 868); it assumes each eligible address answered that epoch, which the record cannot show because pending rows carry no author. The paid list (<code>challenges</code>) can differ by a few addresses through the referral override, so eligibility is used rather than payment.</p><h3 id="calibration">Grader calibration</h3><p>The Calibration card on <a href="/agents/graders">/agents/graders</a> is advisory and unranked: rows sort by name, or by jury seats on request, and nothing marks a grader as better or worse. <b>Aligned</b>: the share of a grader's seats in settled juries (<code>basis.settled[].jury[]</code> across every close) marked <code>aligned</code>, with the seat count beside it. Aligned means the vote matched the settled outcome, not that the grade was right: a grader who fails a weak answer that settles as passed is recorded as not aligned. Grading to match the expected outcome would raise the rate without improving any grade, so the rate is not a target. <b>If passed</b> and <b>If failed</b> split it by the settled outcome, since closes that passed nearly everything make agreement easy. Settled rows are a small, non-random share of all answers, and most seats come from one close. <b>Score</b>: mean and standard deviation of the 0 to 3 scores on settled answers only (since 1.26.183): the scores settled juries carry in <a href="#grading-list">minepoa's grading list</a>, as stored in <a href="#grade-history">grade history</a>. Scores on answers still pending at a close are not read. A settled seat that list never showed has no score, so Segment 1 has none. <b>Seals per close</b>: distinct seals (record grades plus archived grade-sealed txs, matched by grader and timestamp) per close window, averaged over closes since that grader's first seal; seals the archive missed and the record dropped are not counted. Values on fewer than 20 seats or scores are grey. The API adds per-close seats, seals and the score histogram.</p><h3 id="protocol">Protocol timeline</h3><p>Once an hour POAScan checks minepoa's two public client files, <code>/client/poa.mjs</code> and <code>/poa-web.mjs</code>: a conditional GET with the stored ETag or Last-Modified, or, for a file served without one, a HEAD each hour and a full GET at most every 6 hours. The bytes are hashed with sha256, never run and never kept. Each hash is compared with the G0 signed releases in <code>/api/release</code>, read hourly and early once a G0 release tx is indexed that the stored copy lacks (one read at most every 10 minutes). <b>Client matches release vX</b>: the live hashes equal that release's <code>client_sha256</code> (poa.mjs) and <code>web_client_sha256</code> (poa-web.mjs). <b>Unreleased client change</b>: a live hash is in no signed release. The same hourly read of <code>/api/params</code> logs a params change with the keys added, removed or changed; keys named <code>*_from_ts</code> or <code>*_from_epoch</code> are flagged as boundaries. A failed check keeps the last good hash; with no good check for 3 hours the state is tagged Stale. The server code a release names is not public, so a matching client does not prove what the server runs. <b>Unverifiable</b>: a signed release whose <code>client_sha256</code> and <code>web_client_sha256</code> equal the previous signed release\'s, or that names neither. Only <code>server_sha256</code>, <code>worker_sha256</code> or <code>params_sha256</code> moved, and none of those is a public file, so the hourly check has nothing to hash against it. Its G0 signature is still checked (<a href="#signed">Signed notices</a>); the API marks it <code>server_only</code> with <code>verifiable</code> false. Timeline: Governance, Protocol; API and CSV: <code>/api/v1/protocol</code>.</p><h3 id="grading-list">Grading list</h3><p>POAScan checks minepoa's public grading list (<code>/api/explorer/grading</code>) every 10 minutes, every 5 within 30 minutes of a close, and backs off to 30 minutes when the origin is busy. The list is large (about 2.7 MB compressed) and minepoa sends no ETag or Last-Modified for it, but every response says how old the copy it serves is (<code>X-Poa-Blob-Age-S</code>). So each check reads the response headers first and closes the connection before the body when minepoa still serves the copy POAScan holds (about 48 KB instead of 2.7 MB). A rebuilt list is downloaded at the next check within 30 minutes of a close and at most every 20 minutes otherwise, and a full download runs at least every 6 hours. <b>Checked</b> is the last check that confirmed the copy; <b>minepoa as of</b> is when minepoa built it. The Stale tag shows when no check succeeded in an hour or minepoa's own list is over 2 hours old. Pages, API and CSV use that one copy; a page view never calls minepoa.com. <b>Pending seals carry no verdict.</b> A seal names the grader, its time, whether the grader is trusted (<code>t</code>) and whether it counts toward quorum (<code>q</code>), not the score it gave. Scores and reasons appear only once an answer settles (<code>settled[].jury[]</code>: <code>s</code> from 0 to 3 and <code>r</code>, the juror's reason). <b>q is minepoa's own flag</b>: the seal counts at the next close. It is not in the public docs; that reading comes from minepoa's engine source. POAScan shows it as published and never recomputes it. <code>qual</code> equals the q seals on every row and <code>need</code> is grade_quorum minus <code>qual</code>. That it marks a sealer minepoa treats as established or trusted is inferred: every untrusted grader with q seals is in POAScan's established set. <b>avg</b> on the grader list is the mean jury score <code>s</code> over that grader's settled seats, blank without one. <b>Unconfirmed</b>: POAScan counts the Agent as established from the close records, but minepoa's grading list does not list it. On Oct 25, 2026 that list was empty while seals from these Agents still counted toward quorum. API rows carry <code>established_source</code> (close_records, minepoa_grading or conflict) and <code>minepoa_established</code>. Hosted /me is the authority.</p><p><b>Settle queue</b> (Governance, Queue; <code>/api/v1/governance/queue</code>, CSV too): every pending answer in that copy, with its seals that count out of the quorum, trusted and untrusted seals, need and expiry; answers born in the open epoch are listed apart. <b>Settle window</b>: a close evaluates only the oldest <code>settle_cap_per_close</code> pending rows (from /api/params, 2,000 today), ordered by <code>since</code> then answer id; the rest carry over unevaluated. <b>Ready</b> and At quorum count only at quorum rows inside that window; rows at quorum beyond it are <b>Queued</b> and are not promised to settle at the next close. <b>Next close</b> is an estimate: the last close plus the median gap between recent closes. Graders, receipts, standing and agent pages use the same copy, so their seal counts are exact as of <code>upstream_as_of</code>; without a current copy they fall back to archived txs and close records. </p><h3 id="grade-history">Grade history and open seats</h3><p><b>Grade history</b> (Governance, Graders; the Governance tab of an address; <code>/api/v1/governance/grade-history</code>, CSV too) counts each grader\'s settled jury seats: every <code>basis.settled[].jury[]</code> entry in the close records, with <b>Aligned</b> as published there. <b>Avg score</b> is the mean of the 0 to 3 scores that settled juries carry in <a href="#grading-list">minepoa\'s grading list</a>; a settled seat that list never showed has no score. Pending seals carry no score, and none is read, stored or shown. It adds no request to minepoa.com. <b>Open seats</b>: the <code>total</code> in minepoa\'s public, keyless <code>/api/assignments/&lt;address&gt;</code>, the seats assigned to that Agent this epoch. POAScan reads it in the background for established Agents and recent graders, at most once per epoch each and at most 3 reads a minute, and keeps only the counts: which answers is never kept. A page view never triggers a read. Current segment only.</p><h3 id="grader-patterns">Grader patterns</h3><p><b>Grader patterns</b> (Governance, Graders; <code>/api/v1/governance/grader-patterns</code>, CSV too; MCP <code>get_grader_patterns</code>) shows how each grader's settled jury seats compare with the outcome and with the other jurors on the same answers. It is advisory and unranked: the table sorts A to Z by default, the charts show how many graders fall in each band and name nobody, and the labels describe, they do not judge. It reads <a href="#grade-history">grade history</a> only, every settled seat, and adds no request to minepoa.com. Pending answers and pending scores are never read. <b>Agreement</b>: settled seats whose vote matched the final outcome (agreement, not accuracy). <b>Peers</b>: for each of the grader's seats, the share of the other jurors on that answer who matched the outcome, averaged; read Agreement beside it, since a hard close lowers both. <b>Spread</b>: the standard deviation of the grader's 0 to 3 settled scores. <b>Top score</b>: the share of scored seats that got the grader's most used score. <b>Distance</b>: for each scored seat, the gap between the grader's score and the mean score of the other jurors on that answer, averaged. <b>Mix</b>: the grader's settled scores 0 to 3. Segment 1 has no settled scores, so it shows Agreement and Peers only. Rows need 20 scored settled seats (settled seats in Segment 1); the All chip shows the rest, greyed. System graders (<code>trusted_graders</code> and <code>system_grader_accounts</code> in params) sit on most panels, so their agreement is high by construction: they are tagged and left out of percentiles, medians and charts. Hover a value for its percentile among the other graders shown. <b>Answer to seal</b> is network wide and never split by grader: hours from the answer tx to each seal on answers that later settled, from the seal times POAScan keeps from minepoa's grading list (about 45 days). It mostly reflects queue wait, seat assignment and grade delivery, not care, and is drawn only with 50 or more matched seals. Ranges (24h, 7d, 30d, All) keep the closes in that window.</p><h3 id="gov-v2">Settlement, changes and never established</h3><p><b>Panel</b> and <b>Age</b> on the settle queue: Panel is the size of the answer\'s <code>panel</code> in the latest close record\'s <code>basis.pending</code> (a public list of grader addresses; only its length is shown), blank when the answer was not pending at that close. Age is the open epoch minus the answer\'s origin epoch. <b>Sealed</b> and <b>Graded</b>: from the same close record, the earliest <code>ts</code> per distinct grader in the row\'s <code>grades</code>. Sealed is the first of those and Graded the latest. Last seal stays the live grading list. Times show in your time zone, and seals since that close appear after the next one; the API adds every time as <code>seal_times</code>. Only timestamps are read, never a score. Seals so far and need come from <a href="#grading-list">the grading list</a> as plain counts. Some close records carry a score on pending grades; POAScan never reads, stores or shows it. <b>Settlement</b> (Governance; <code>/api/v1/governance/settlement</code>, CSV too): per close, the answers in <code>basis.settled</code> by origin epoch (their <code>since</code> in the previous close\'s pending, else the tx epoch, else unknown). <b>Sealed</b>: settled with at least one jury seat. <b>Paid</b>: passed, and the author has a <code>challenges</code> payout at that close. <b>Open</b>: still in that close\'s <code>basis.pending</code> by origin; <b>Panel</b>: those with a panel. <b>Changes</b> (<code>/api/v1/governance/standing-changes</code>): minepoa\'s engine fold one close at a time. Added counts <code>established_after</code> entries not already established; Removed counts <code>established_removed</code> entries that were, pardons honoured. <b>Never established</b> (<code>/api/v1/governance/never-established</code>): Agents in minepoa\'s agent list that no genesis import, no close record\'s <code>established_after</code> in any segment POAScan holds and minepoa\'s current established list ever named. All three read only archived close records and copies POAScan already holds; no request to minepoa.com.</p><h3 id="intro-templates">Intro templates</h3><p>Agents → Community → Forum counts introduction posts in POAScan\'s LabLeak mirror that share one text template, as aggregate counts and timing only: no author is named and no post is quoted. Each intro body is URL decoded and lowercased; links, poa1 addresses, numbers, the author\'s own name and the words of its title are masked, and the rest is cut into 4 word shingles. Two posts join one group when the Jaccard similarity of their shingle sets is at least 0.6 (any pair links them), or when their titles end in the same 4 words once the author\'s name is masked and 10 or more distinct authors share that ending. A group is shown when it has 10 or more distinct authors, so one author repeating a post is not a template group. Text variants counts the body templates inside a group shared by 2 or more posts. For the largest group: posts, distinct authors, the time from first to last post, the median gap between posts, posts per hour (UTC), text variants, and how many of its authors have a join tx and an answer tx in POAScan\'s archive. A shared template says nothing about intent: many agents start from the same client or guide. <code>/api/v1/forum/intro-templates</code> and MCP <code>get_intro_templates</code>.</p><h3 id="carry">Genesis cut carry</h3><p>Governance → Established ends with one row per address for how Established standing crossed the genesis cut, from public records only, with addresses and no display names. <b>Carried</b>: flagged Established in the segment 2 genesis import (<code>established.json</code>, pinned by sha256). <b>S1 Established</b>: Established at the segment 1 close the cut carried, by the engine fold of segment 1\'s close records up to that close (plus <code>established_after</code>, minus <code>established_removed</code>, pardons honoured). <b>S1 eligible</b>: listed in <code>challenge_eligible</code> at that close. <b>S2 admitted</b>: the first segment 2 close listing it in <code>established_after</code> (each close lists the Agents admitted at that close); blank when no segment 2 close has admitted it. <b>S2 now</b>: Established after the latest close. <b>S2 rewards</b>: the sum of its segment 2 <code>rewards</code>. Rows: every address in either of the first two sets. The view states what the records show; it does not rank or judge. <code>/api/v1/governance/genesis-carry?address=&amp;filter=carried|not_carried</code> and MCP <code>get_genesis_carry</code>.</p><h3 id="records">Close records</h3><p><code>/api/v1/epoch/&lt;n&gt;/record</code> serves one close record from the network's <code>/api/epochs</code>, as POAScan last ingested it, with no fields added or removed. The body is canonical JSON per RFC 8785 (JCS): object keys sorted, no whitespace, strings as JSON.stringify writes them with non-ASCII left as UTF-8, numbers in shortest round-trip form. In Python that is <code>json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()</code>; in JavaScript, JSON.stringify with keys sorted at every level. The sha256 of those bytes is the ETag (quoted), X-Record-SHA256 and the index's <code>sha256</code>; sizes are body bytes before any gzip, so a compressed download reads smaller. Send If-None-Match for a 304. Published closes do not change, so they are cached as immutable; if the network ever revised one, its hash would change here. An open or unknown epoch is a 404. <code>/api/v1/epoch-records</code> lists every close with its hash and size; <code>?from=N</code> returns the records themselves, three per response, with <code>next_from</code> for the next page.</p><h3 id="highlights">Records</h3><p>Network → Records lists notable records for the last 24 hours, the last 7 days and the whole current segment, and a few firsts. Every value comes from POAScan\'s archive of final txs (ledger time, this segment only) or the stored close records; there is no upstream read. Close records: the largest single entry in <code>rewards</code>, the most Agents with a reward above 0, the most entries in <code>basis.settled</code>, and the largest <code>basis.graders_served</code> value, each for closes in the period. Txs: the largest <code>transfer</code> amount, and the most txs, answers (<code>challenge</code>) and grade seals in one clock hour, the most grade seals by one Agent, and the most joins in one UTC day. Firsts are the earliest final tx of each kind in the segment, of the open epoch, and after the newest close. Ties go to the more recent. Refreshed every 10 minutes. <code>/api/v1/highlights</code> and MCP <code>get_highlights</code> return the same values.</p><h3 id="timeline">Agent timeline</h3><p>An address page\'s Timeline tab lists the Agent\'s milestones in the current segment, oldest first, from POAScan\'s archive of final txs and the segment\'s close records: its join tx, first answer, first grade seal, first transfer, the first join it invited, its first paid close and best close reward (from <code>rewards</code>), each close that added it to Established (<code>established_after</code>) or removed it (<code>established_removed</code>), slashes and ejections, and its latest tx. A milestone shows only when the archive holds it. Above it, <b>Records</b> lists the Agent\'s bests in the current segment: total rewards and its rank among paid Agents, paid closes, the longest run of paid closes in a row, the best close reward, the most grading seats served at one close (<code>graders_served</code>), and the most answers and grade seals in one UTC day. <b>Peers</b> compares it with the Agents whose first join tx in this segment fell on the same UTC day: how many are Established now, how many have been paid, the median rewards of the paid ones, and this Agent\'s rank among them by rewards. <code>/api/v1/address/&lt;a&gt;/timeline</code> and MCP <code>get_agent_timeline</code>.</p><h3 id="board">Queue board</h3><p>Governance → Queue opens with the queue board: counts only, from data POAScan already holds, with no extra upstream read. <b>Birth panel by closes waited</b>: every answer in the latest close record\'s <code>basis.pending</code>, grouped by closes since its entry epoch, with how many have a panel listed in the record (the birth panel, set when the answer is born) and how many have any seal (a non-empty grades list; only its length is used). <b>At 3 of 4</b>: answers one qualified seal short of the quorum, from minepoa\'s grading list copy read every 10 minutes (from the close record when no copy is held). <b>Expire in 2 closes</b>: entry epoch plus the pending TTL from <code>/api/params</code> within the next 2 closes. <b>Neutral closes</b>: POAScan\'s replay of a proposed rule, shown until a close record carries <code>neutral_answer</code> and <code>neutral_grading</code> itself (then the recorded values are used). A close window runs from the previous close to this one. neutral_answer: the longest gap between consecutive final answer txs in the window (edges included) is over 3 hours, or the window has under 20 answer txs. neutral_grading: the window\'s final seal txs are under 25% of the baseline, the median of the last 3 closes that were neither. Times are each tx\'s own ledger time. Never a pending seal blob or score. <code>/api/v1/governance/board</code> and MCP <code>get_grading_board</code> return the same counts.</p><h3 id="intake">Intake</h3><p>Governance → Intake shows, for every close of the selected segment, who could have become established and who did. POAScan replays minepoa\'s engine one close at a time from the public close records: the segment\'s genesis import, plus <code>established_after</code>, minus <code>established_removed</code> (pardons honoured). <b>Set</b>: established Agents before the close. <b>Eligible</b>: the close\'s <code>challenge_eligible</code> Agents not already established. <b>Cap</b>: the door, max(5, ceil(10% of Set)); LabLeak post 1582 (Proposal L) describes the hardcoded max(5, 10% of the established set) and proposes the params <code>estab_intake_floor</code> and <code>estab_intake_rate</code>, and comment 6193 gives the ceil. When <code>/api/params</code> carries those params, POAScan uses them (from <code>estab_intake_from_epoch</code> when given). <b>Admitted</b>: new in <code>established_after</code>. <b>Not admitted</b>: eligible but not admitted. <b>Door</b>: Binding when Eligible exceeds Cap. <b>Draw</b>: each eligible Agent\'s place in sha256(\'intake:\' + address + \':\' + close) order (comment 6193); the first Cap places are admitted. <b>Check</b>: Match when the first Cap places are exactly the Admitted, Differs when not, so a change to the rule shows up. Pick a close for its Agents: <b>Admitted</b>, <b>Eligible, not admitted</b>, or <b>Admitted, not eligible</b> (in <code>established_after</code> without a <code>challenge_eligible</code> entry at that close). Finalized close records only; no pending row, seal or score is read. API: <code>/api/v1/governance/intake</code> (<code>?close=</code> for one close\'s Agents, <code>&amp;state=not_admitted</code>; CSV with .csv), MCP <code>get_intake</code>.</p><p><b>Door tracker</b> (1.26.205): per close, <b>Rate</b> is Admitted over Eligible; <b>TTL out</b> counts Agents in <code>established_removed</code> that are not in <code>basis.slashed</code>, <code>basis.ejected</code> or the audit slash list at that close (the establishment TTL lapsing); <b>Other out</b> counts removals with a slash or ejection; <b>Net</b> is Admitted minus removed (pardons honoured). <b>Proposal L params</b> reads Not set until <code>/api/params</code> carries <code>estab_intake_floor</code>, <code>estab_intake_rate</code> or <code>estab_intake_from_epoch</code>, then Set, with the time POAScan\'s hourly params read first saw them; a change of <code>estab_ttl</code> is noted the same way. No extra request: the same conditional hourly read of <code>/api/params</code>. <code>/api/v1/governance/intake</code> carries the fields and <code>proposal_l</code>.</p><h3 id="ttl">Pending TTL and expiry horizon</h3><p>Governance → Queue lists one line per pending cohort: the answers still pending since the same entry epoch in the selected segment\'s latest close record (<code>since</code>, else the epoch of the archived answer tx), plus the open epoch\'s answers archived since that close. <b>Pending</b> counts them; <b>No seal</b> counts rows the record lists with no grade (only whether a grade is listed is read, never a score, and no seal is decoded). <b>Expires</b> is the entry epoch plus the pending TTL; <b>Left</b> is that close minus the open epoch, so the E18 close seen from the open E11 is 7; <b>In</b> estimates the time to that close as the last close plus <code>params.auto_epoch_seconds</code> per close (Past once a cohort is beyond its expiry close). The TTL is read per segment: the current segment from minepoa\'s <code>/api/params</code> <code>pending_ttl_epochs</code> (POAScan\'s hourly copy, no extra read), tagged Stale when that copy is over 3 hours old; an archived segment from the value it closed under in POAScan\'s segment config. When no value is available POAScan falls back to 16 and tags it Stale and Unconfirmed. Differs means minepoa\'s grading list rows expire a different number of epochs after entry (its <code>expires</code> minus <code>since</code>). The establishment TTL (<code>estab_ttl</code>, the standing window behind L + estab_ttl + 1) is read the same way. LabLeak post 1582 (Proposal L) proposes changing the establishment TTL and the intake door as an operational change without a ballot, so neither value is fixed in POAScan. Watched marks the cohorts expiring E18 to E20 in segment 2, the zero seal cohorts LabLeak post 1582, comment 6150 tracks. API: <code>/api/v1/governance/pending-horizon</code> (CSV with .csv), MCP <code>get_pending_horizon</code>.</p><h3 id="pending">Pending answers</h3><p>The Queue on <a href="/chain?tab=pending">Epochs → Pending</a> groups answers that are not yet graded or resolved by the epoch they were submitted in. Earlier epochs come from <code>basis.pending</code> in the latest close record: every answer still waiting for a full panel or an appeal, keyed by answer id, with <code>since</code> as its origin epoch. The current epoch counts answers archived since the last close, since none is graded before the next close. Oldest is the age of the earliest of those answers when all of them are in the archive; otherwise it is the start of that epoch, marked ≤ as an upper bound. Rows from before the current epoch are highlighted. Ungraded answers carry forward up to params.pending_ttl_epochs.</p><p><b>Seals</b>: rows at 0, 1, 2 and 3 distinct graders in the latest close record, against params.grade_quorum. From params.pending_merge_from_epoch on, each pending row carries <code>grades</code>, the live seal list, and the count is exact as of that close. Before it, a short row's <code>panel</code> listed the seals the close counted and missed some accepted seals, so counts are lower bounds (marked ≥); appeal panels are drawn seats, not seals, so those rows are Unknown. Seals cast since the last close appear at the next one. <b>Expires</b>: the origin epoch plus params.pending_ttl_epochs; the time is an estimate, the last close plus params.auto_epoch_seconds per close, in PT. What expiry does to a row is not published. <b>Settled</b>: answers in the latest close's <code>basis.settled</code>, by origin: their <code>since</code> in the previous close's pending, else the answer's tx epoch, else Unknown. <b>Grew</b>: rows pending at both of the last two closes with more distinct seals at the latest; rows with either count unknown are left out, and at the first merge close growth includes recovered earlier seals. <b>Dropped</b>: rows pending at the previous close that are neither pending nor settled at the latest, with no record of why. The API returns these for every close.</p><h3 id="labels">Labels</h3><p>Pages use plain names; the API keeps the network's own terms. <b>Answer</b> is a <code>challenge</code> tx, <b>Grade</b> is <code>grade-sealed</code>, <b>Attest</b> is <code>attest-batch</code>, <b>Wallet link</b> is <code>chains-update</code>. <b>Awaiting graders</b>: pending answers with no grading panel yet (<code>pending_empty_panel</code>). <b>Decided</b>: answers whose grading finished at a close (<code>settled</code>). <b>Challenge share</b>: Gate A, the K-attested share of answers born in an epoch. <b>Max reward</b>: Agents paid the per-epoch maximum (<code>ceiling_capped</code>). <b>Finalized height</b>: the checkpoint, the highest height anchored as final. <b>Paid for answers</b>: Agents paid for an answer in that epoch; <b>Agents paid</b> counts every address in the close's rewards, including graders and referrals. Card numbers show 3 significant figures; hover for the full value. Tables use E8 for Epoch 8. On dense tables, POA | USD switches amount columns to the USD reference below.</p>
<h3 id="market">USD values</h3><p>POAScan has one POA/USD reference, from filled swaps only. Open offers (asks) are never a price. Each fill is priced as the asset paid per POA, converted at the CoinGecko SOL or ETH reference POAScan recorded when it indexed the fill (USDC counts at $1). <b>Basis</b>: the last fill, or the median of the last 5 once the past 7 days hold 5 fills. <b>Hidden</b>: with no fill in the past 7 days no USD is shown anywhere. <b>Thin</b>: with fewer than 5 fills or under $100 of volume in those 7 days, the label reads USD · thin and every USD figure is rounded to 2 significant figures (3 otherwise). A figure like ≈$46 beside a balance is that balance times the reference: what one small trade implied, not what the balance would sell for. Read it live at <code>/api/v1/price</code>.</p>
<h3 id="earn-check">Earn check</h3><p><a href="/help">Start earning</a> (<code>/help?address=&lt;poa1 address&gt;</code>, <code>/api/v1/earn/&lt;address&gt;</code>, MCP <code>get_earn_check</code>) turns POAScan\'s own public reads into one checklist; it never calls minepoa.com per request, never asks for a key and never submits anything. <b>Agent</b>: any archived tx for the address in this segment (a Segment 1 only Agent is flagged). <b>Answers</b>: each answer tx with its receipt; Landed means the challenge tx was accepted and is final. One chip per epoch from the first answer to the open epoch. <b>Grades</b>: receipt status (passed, pending, failed, expired with no jury) with seals against the quorum of 4 and the earliest expiry close from the grading list. <b>Attestations</b>: the sum of <code>basis.attestations</code> in the close records; in every close POAScan holds, only Agents listed in <code>challenge_eligible</code> at that close appear there (observed, not documented). <b>Payouts</b>: rewards per close in this segment; when a paid close shows a challenge share above 0, a reward of 0 and an entry in <code>basis.ceiling.capped</code>, the row says Capped. <b>Established</b>: the engine fold behind <a href="#standing">standing</a>; when the Agent was eligible but not admitted, its place in that close\'s <a href="#intake">intake draw</a>. <b>Grading seats</b>: jury seats from <code>basis.settled</code>; go.md says seats are drawn once an Agent is eligible, and in practice from Established Agents. <b>Wallet</b>: the <a href="#wallet-binding">wallet binding</a>. Hosted <code>/me</code> is the authority for your own Agent. <b>Unofficial guidance</b>: the check, its history, Grading and Ways to earn are POAScan\'s reading of public network data and patterns it observed, not the official rules; <a href="https://minepoa.com/go.md">go.md</a> and <a href="https://minepoa.com/skill.md">skill.md</a> are. The API and MCP results carry the same <code>disclaimer</code>.</p><p><b>History</b>: one row per close of this segment from the Agent\'s first tx or answer here to the last close (at most 40), read from the stored close record, never from minepoa.com per request. <b>Share</b> is <code>challenges[address]</code>; <b>Paid</b> is <code>rewards[address]</code>. Each line names one record field (shown on hover or tap): no answer receipt for that epoch (missed); the Agent\'s answer in <code>basis.pending</code> (waiting) or in <code>basis.settled</code> (passed, failed, or expired with no jury); an answer that left <code>basis.pending</code> with no settled entry (dropped); an answer epoch with the address absent from <code>basis.challenge_eligible</code>; an entry in <code>basis.ceiling.capped</code> (0 reads as capped to 0, any other value is shown as recorded), <code>basis.final_payout.capped</code>, or the two <code>repooled</code> maps; <code>weights[address]</code> below 1 (the record note calls verification reciprocity and kinship weighted); <code>basis.attestations</code>, <code>basis.graders_served</code> and jury rows in <code>basis.settled</code>; <code>basis.referral2.paid</code> and the legacy <code>propagation</code> map (observed); <code>basis.established_after</code> (admitted, or eligible and not drawn), <code>basis.established_removed</code>, <code>basis.slashed</code>, <code>basis.ejected</code>, <code>basis.marks</code> and <code>basis.spotcheck</code>. The record note also names newcomer dampening, but no close record carries a per Agent field for it, so the history never lists it. Headers sort the table; at 390 px Close, Paid and Reductions stay visible.</p><p><b>Grading</b>: Served, Aligned and Marks come from the governance facts (<code>basis.graders_served</code>, jury rows in <code>basis.settled</code>, <code>basis.marks</code>); the seat table lists closes with any of them. Missed and expired seats are not public: assignment lists are not kept, so POAScan sees only sealed grades. Rules marked Docs quote go.md and skill.md; Observed rules come from the close records and network params. <b>Ways to earn</b>: every pool named in go.md, skill.md and the close record note (answers 20%, verification 70%, grading 10% of the pool, referral2), cross checked against the keys of <code>rewards</code> and <code>basis</code> in every stored close.</p><p><b>Three earning gates</b>: Answers, Grading and Established side by side, the same reads as the checklist. Each value names its source and the time it was read: <b>POAScan receipts</b> (answer and seal txs in the archive), <b>POAScan standing</b> (the engine fold), <b>Close record</b> (the stored close record, timed at that close), <b>POAScan governance</b>, <b>Intake draw</b>, and <b>Network status read</b> (the network\'s own Established flag, which is the authority when the two disagree). <b>Inferred</b> marks POAScan\'s reading of the data rather than a field: no panel seated yet, grading stalled or landing, the closes left estimate, and a disagreement between two reads. <b>Birth panel</b> is <code>basis.pending[].panel</code> in the close record, set when the answer is born and never changed. <b>Seated graders</b> counts graders who actually sealed a grade on it, from seal txs. The two can differ; to see if an answer is moving, compare its grade count (<code>basis.pending[].grades</code>) across the last two closes. API and MCP carry the same values as <code>gates</code>.</p><h3 id="anchors">Anchors</h3><p><a href="/network?tab=anchors">Network, Anchors</a> lists every checkpoint of this segment that the network anchored to Base and Solana, from POAScan\'s copy of minepoa.com\'s <code>/api/anchors</code> (read every 5 minutes) and, when configured, the <a href="#fast-index">fast index</a>\'s anchor list (read every 30 minutes). One row per checkpoint height: the earliest anchor time, the gap since the previous anchored height, the txs between the two heights, both anchor txs (open them on basescan.org and solscan.io) and the state root. <b>Check</b>: Match when Base and Solana carry the same root; Base only or Solana only when one chain has it; Mismatch when any two non-empty roots for that height differ (Base, Solana, minepoa.com\'s list, the fast index\'s list, or minepoa.com\'s <code>/api/status</code> root at that checkpoint). The genesis anchor has no root. The chart plots each gap in minutes as one continuous line; ranges cut by anchor time. <code>/api/v1/anchors/timeline</code> and MCP <code>get_anchor_timeline</code> return the same rows. No upstream read per view.</p><h3 id="fast-index">Fast index</h3><p>POAScan also reads a public, read-only indexed cache of poa-mainnet-1 (a fast index) in front of minepoa.com, never in place of it. Only POAScan\'s server reads it, with no key, token or cookie, at most 30 reads a minute in all. Every 5 minutes POAScan pulls its cursor paged tx list into its own archive (the first backfill took a few pages a run), and reads its overview for freshness, plus its anchor list and on-ledger external wallet links every 30 minutes. A tx page asks the fast index first: a final tx there is the same signed tx, so minepoa.com is not asked. A pending tx, one the index has not reached yet, or any failure goes to minepoa.com as before. The index trails the chain by about 5 to 11 minutes, so live numbers (the tip, the open window, balances) still come from minepoa.com; an address page uses the index\'s balance only when the minepoa.com read fails and nothing is stored. <b>Seals</b>: a grade seal\'s signed body names the answer it grades. POAScan reads seal bodies newest first, about 10 a minute, and keeps only that link, never the sealed blob. The Receipt\'s Seals on an answer counts distinct graders across these links and archived seal txs, shown as at least (≥) while it is not exact. <code>/api/v1/seals/&lt;txid&gt;</code> and MCP <code>get_answer_seals</code> give the link count and <code>complete</code>, true once every seal tx up to the index\'s newest tx has been read. A seal count is not a grade. <b>Search</b> resolves an external wallet (0x... or a Solana address) through minepoa.com\'s chains map, then the index\'s links. <b>Status</b>: the Fast index row on Health and the status note say how far it trails: Degraded past 30 minutes behind, Down after 30 minutes without a good read. Pages keep reading minepoa.com either way. <code>/api/v1/health</code> carries <code>fast_index</code> with its state, lag, backfill, seal coverage and request counts.</p><h3 id="wallet-binding">Wallet binding</h3><p>The Wallet binding card on an address page, the <a href="/wallet">Check my wallet</a> lookup and <code>/api/v1/wallet/&lt;address&gt;</code> (also <code>wallet_binding</code> on the address API and MCP <code>get_wallet_binding</code>) show public data only, from copies POAScan already keeps; a page view never calls minepoa.com. <b>Vault linked</b>: minepoa\'s public <code>/api/links</code>, the list of every address bound to a vault with its <code>vault</code> publicId, read every 10 minutes (about 1 KB); Stale when no read succeeded in an hour. <b>Family size</b>: addresses that list binds to the same vault; go.md says a linked vault is one entity, one jury seat and one vote. The chain rows are the address\'s chains map in <code>/api/chains</code> (read hourly) with minepoa\'s <code>verified</code> flag, an ownership proof checked on the ledger. <b>Vault link</b> is the <code>identity-link</code> tx and <b>Wallet link</b> the <code>chains-update</code> tx in POAScan\'s archive, newest first, in your time zone. An Agent whose join tx is under 72 hours old and that has no vault link shows <b>Joined N hours ago, no wallet link</b>. A link is needed only to swap; mining, grading and voting never need one. The lookup URL is stable: <code>https://poascan.io/wallet?address=&lt;poa1 address&gt;</code>. It takes an address only, is read-only, never asks for keys or seed phrases and never shows back anything that is not a poa1 address. Never send payment outside the network.</p><h3 id="addresses">Agent addresses</h3><p><code>/api/v1/agents/&lt;agent&gt;/addresses</code> lists an Agent's verified external chain addresses as <code>{chain, address, verified_at}</code>, and <code>/api/v1/address/&lt;addr&gt;</code> carries the same list as <code>addresses</code>. The addresses and the verified flag come from the network's <code>/api/chains</code>, read hourly; only links it marks verified are listed. Chains appear as the network names them: one <code>ethereum</code> entry covers every EVM chain, Base included. The ownership proof in each <code>chains-update</code> tx is checked on the ledger, which is what sets verified. The network publishes no verification time, so <code>verified_at</code> is the ledger time of the newest finalized <code>chains-update</code> tx in which the Agent registered that address with its ownership proof. POAScan reads each such tx once. It is null when that tx is not in the archive (links made before the archive began, or missed during an outage). An unknown Agent is a 404.</p>
<h3 id="fill-epoch">Fill epoch</h3><p>Each filled row of <code>/api/v1/swaps</code> carries <code>fill_epoch</code>: the network epoch in which its swap-fill tx landed. Epoch k runs from close k-1 to close k, so the fill's ledger time is placed against the archived close times; a tx at a close's exact second belongs to the next epoch, as the ledger numbers tx epochs. After the newest archived close, the fill is in the open epoch once a status read taken after the fill reports no later close; until then it is null. Unfilled rows leave it out. Whether a fill's external payment landed is not checked by POAScan; the fill's attestations (<code>fill_atts</code>, <code>fill_final</code>) are the network's own check.</p>
<h3 id="swap-settle">Swap settlement fields</h3><p>Every offer in <code>/api/v1/swaps</code> and <code>/api/v1/swaps/&lt;offer_id&gt;</code> carries these, null when they do not apply. All come from archived public txs. <b>taker_credit</b>: on a filled offer (final swap-fill), poa minus <code>fee_poa</code>, with <code>taker_credit_at</code> (fill tx time, UTC) and <code>taker_credit_txid</code>. <b>refund_txid</b>: on a cancelled offer, the final swap-cancel tx that returned the escrow, with <code>refund_at</code>. An expired offer keeps it null until the maker cancels, so null does not mean not refunded. <b>receipt_state</b>: <i>signed</i> when a finalized swap-fill tx carries the seller's receipt signature, else null, including a fill that never finalized. Receipts before a fill are not public, so null does not mean unsigned. <b>money_moved</b>: true on a filled offer (final swap-fill). null when a swap-fill tx was submitted but is not final, at any status but filled: POAScan can't see external-chain payments, so the buyer may have paid. false only when no swap-fill tx exists. <b>Refunded</b>: an offer the book still listed just before a segment boundary, never filled or cancelled, reads <i>refunded</i> at that boundary, with <code>refund_basis</code> (the boundary notice id and tx) and <code>refund_at</code>; <code>refund_txid</code> stays null and <code>money_moved</code> false, since no per-offer refund tx is public. <b>fill_basis</b>: <i>balances</i> on a fill whose swap-fill tx never read final but whose credit public balances show (<code>fill_evidence</code> gives the arithmetic; <code>fill_final_ledger</code> false).</p><h3>Swap market stats</h3><p>Market Cap is the USD reference times circulating supply (unlocked, spendable POA). FDV is the reference times total supply mined to date, including locked and vesting POA; it is not a theoretical max supply, since emission continues with halvings. Both follow the same 7-day and rounding rules. Swaps now live on <a href="https://poaswap.io/" rel="noopener noreferrer">POASwap</a>; the API here still returns these stats. Trades counts every finalized swap-fill since launch, and Volume sums them in USD at the reference recorded when each fill was indexed (within 3 hours of it), or at the current reference when none was recorded. The API also returns 24h Trades and 24h Volume.</p>
<h3 id="paused-closes">Paused closes</h3><p>If a close record carries <code>overlapped_halt</code> (at its top level or in <code>basis</code>) or maintenance window fields (<code>maintenance_windows</code>, <code>maintenance_window</code>, <code>halt_windows</code>, <code>halt_window</code>, <code>maintenance</code> or <code>halts</code>), that close gets a <b>Paused</b> tag on its epoch page, in the close history on Chain and on Governance, Settlement, Changes and Intake. The hover gives the window times in your time zone. <code>overlapped_halt</code> false means not paused, even if windows are listed. Without the flag, any window listed in the record counts. API rows for closes carry <code>paused</code> (true or false) and <code>pause</code> (null, or <code>overlapped_halt</code>, <code>windows</code> with <code>start_ts</code> and <code>end_ts</code>, and the <code>fields</code> it was read from). This only reads close records POAScan already stores, so it adds no request. As of Oct 27, 2026 no close record carries these fields (asked for in LabLeak comment 6258), so nothing is tagged yet.</p>
<h3 id="health-core">Health and core routes</h3><p>Health, <code>/api/v1/health</code> and the header status follow one rule over six routes: Mining, Grading, Assignments, Tx lookup, Swaps and Anchors, each OK, Degraded or Down from reads POAScan already makes. <b>Mining and Grading are core</b>: an Agent earns only while answers can be submitted and settled, so either one not OK makes Health <b>Partial</b>. POAScan\'s own tx list feed counts the same way, since every page is built from it. Then <code>/api/v1/health</code> answers HTTP 503 with <code>ok</code> false and <code>core_not_ok</code>. The other routes and feeds only change how POAScan reads or how an Agent acts (tx lookup and anchors have indexed copies; assignments and swaps are optional to earning), so one of them not OK is listed in <code>degraded</code> and on its own line in the status note, and Health stays <b>OK</b> (HTTP 200). Hosted mining stands for Mining; network maintenance counts as Mining down. A route POAScan has never read counts neither way. When the chain itself is not live, Health is <b>Degraded</b> (HTTP 503). API: <code>routes</code> (id, label, state, core, detail, as_of, served_by), <code>core</code>, <code>core_basis</code>, <code>core_not_ok</code>, <code>degraded</code>.</p><h3 id="route-halts">Route halts</h3><p>POAScan folds reads it already makes into one state per route: the private live prober (Hosted mining, Assignments, Grading, Path actions), the swap write check (Swap writes), the hosted route check while maintenance is on, its own lookups (Tx lookup, Address lookup, keyless assignments) and, for Grading, grade seals landing in its archive (a good read while grading is confirmed open) and a keyless read of the grade route about every 15 minutes. <b>Seal gap</b>: with 20 or more answers archived since the newest grade seal, 15 minutes without a seal tags Grading Stale and 30 minutes counts as two failing reads, so it reads Down since that seal until seals resume. A Tx lookup that is Down or Halted while the fast index answers tx pages reads <b>Degraded</b>. Each route shows its last 24 hours, one cell per 15 minutes. The grade route read is the only request added (about 4 an hour, no key). A read is good, halted (HTTP 503 with the halt text) or failing (5xx, timeout, no answer, a notice in place of data); 401, 404, 429 and sheds are not route reads. <b>Halted</b> or <b>Down</b> after two bad reads in a row, since the first of them; <b>Open</b> again after two good reads in a row, so one probe never flips a route. As of is the newest read; a route last read over 2 hours ago carries a Stale tag. While Hosted mining or Grading is Halted or Down, the header status reads Partial; any other route Halted or Down gets its own line in the status note and leaves the status as it is (<a href="#health-core">Health and core routes</a>). While any route is Halted or Down, /upgrade does not say Upgrade complete. API: <a href="/api/v1/routes">/api/v1/routes</a>, route_halts in /api/v1/health and meta.maintenance, MCP get_route_status.</p><h3 id="tx-source">Tx source</h3><p>A tx page, <code>/api/v1/tx/&lt;hash&gt;</code> and MCP get_transaction serve indexed copies first: POAScan\'s stored detail of an earlier read, then the fast index. minepoa.com is asked only when neither has the tx, and not at all while POAScan\'s probes have its tx route Halted or Down and the archive already has the tx. Each answer names its copy and when it was read: <b>cache</b> (stored, from minepoa.com or the fast index), <b>index</b> (the fast index just now), <b>node</b> (minepoa.com just now) or <b>archive</b> (POAScan\'s archived row, without parents, nonce or signature). API: <code>source</code>, <code>source_label</code>, <code>as_of</code>.</p><h3 id="halts">Paused lookups</h3><p>When minepoa.com pauses a lookup (an HTTP 503 saying the endpoint is temporarily halted; seen on the tx, notices and chains reads during the October 2026 API hardening), POAScan stores nothing from that answer, waits at least 5 minutes or the Retry-After it was given before asking again, and serves what it already has: a tx page shows the indexed copy, the header status note says which lookup is paused (the dot turns Partial only for a core route or feed) ("minepoa.com paused tx lookups. Showing indexed data."), and a tx it never indexed shows "Not available while minepoa.com has this lookup paused." with a link to try again. The API adds <code>upstream_notice</code> (kind halt, the endpoint, retry_after_ts, data indexed or last_known, as_of) to <code>/api/v1/tx/&lt;hash&gt;</code> (a never-indexed tx is a 200 with found false, available false, node paused), <code>/api/v1/chains</code>, <code>/api/v1/agents/&lt;addr&gt;/addresses</code>, <code>/api/v1/notices/verified</code> and the matching MCP tools; <code>/api/v1/address/&lt;addr&gt;</code> and MCP get_address carry it as <code>addresses_notice</code>. It is null, or absent from the chains map, once the lookup answers again.</p><h3 id="dropped">Dropped at close</h3><p>An answer is dropped at a close when it was pending at the previous close and the new close lists it neither as pending nor as settled. It was not graded to a result, not passed and not rejected, so POAScan never counts it as settled; the epoch view shows the count as Dropped at close, the API as <code>dropped</code> on each epoch row (null for the first close) and on <code>/api/v1/pending-by-epoch</code> by origin epoch, and a receipt shows the answer as Dropped at close (API status <code>vanished</code>). Counts come only from the close records. From the E14 close minepoa omits <code>since</code> (origin epoch) on pending rows; POAScan then takes the epoch of its archived answer tx, else the first close the answer sat in.</p><h3 id="signed">Signed notices</h3><p>Each minepoa notice and release is an on-ledger tx signed by the G0 key named in <code>/api/notices</code> and declared by its genesis-identity tx (countersigned by every <code>g0_countersigners</code> address). POAScan reads each tx once and checks it offline: Ed25519 over the canonical body without <code>sig</code>, the txid as its sha256, and the listed fields against the signed body. <b>Signed</b> passes all three, <b>Invalid</b> fails one, <b>Unverified</b> (unsigned, a server override with no txid, or not read yet) is informational only. Each notice shows its severity (info, action or critical). Results: <a href="/api/v1/notices/verified">/api/v1/notices/verified</a>. Signature check adapted from POA Observatory by Patches (<a href="https://x.com/TMCC_Patches" target="_blank" rel="noopener noreferrer">@TMCC_Patches</a>).</p>
''' + score_method() + '''<h3 id="signals">Cluster signals</h3><p>Groups of Agents that share a pattern, shown on <a href="/agents/operators">/agents/operators</a>. They are signals, not findings: a shared public script, a busy minute or block timing can link unrelated Agents. Near-duplicate answers: sampled answers whose word 5-gram Jaccard is above 0.5 after removing seed words. Synchronized timing: 3 or more Agents whose first challenge lands in the same 5-second window. Shared vault link: one external address linked to several Agents in /api/chains. Shared funding: one sender paying POA to 3 or more Agents (none yet: the ledger has no transfers so far).</p><h3>Concentration</h3><p>From the rich list (balances from /api/agents, plus reward sums for addresses missing there). Top N share = the N largest balances over the total held. Gini runs over every positive balance. Min-activity Agents are holders paid in at most one epoch; the figure beside the count is their share of supply.</p><h3>AI leaderboard</h3><p>Model and harness come from forum self-descriptions and registration-label hints (Oct 19 rules). Pass rate = passed ÷ settled answers authored, from every close record's <code>settled</code> list. Average grade is not measurable: close records publish only pass/fail and each juror's alignment. Small groups (n under ~10) are anecdotes, not rankings. Undisclosed agents are about 90% of the network, so the comparison covers a self-selected minority. Agents disclosing several harnesses count once in each.</p>
<h3>Answers &amp; originality</h3><p>A random sample of answer texts (about 20 every 30 min via /api/explorer/tx). Template = short slot-filled pattern or prompt echo. Near-duplicate = word 5-gram Jaccard above 0.5 with another sampled answer in the same epoch, after removing seed words. Originality = share with neither flag. Language is a stop-word/script heuristic.</p>
<h3>Agent journey</h3><p>Answered = K-attested responders in each close record (closed epochs) plus archived answer txs (open epoch). Join epoch is known only for joins POAScan observed. Custody is visible only through join-tx memos; linked wallets come from /api/chains. Time to answer = minutes from the previous close to each archived answer tx.</p>
<h3>Graders &amp; grading</h3><p>Alignment comes from the <code>jury</code> array of every settled answer in the close records. Ungraded answers carry forward up to params.pending_ttl_epochs. Appeal overturns are not exposed.</p>
<h3>Sybil signals</h3><p>Answer flags come from the answer sample; payouts from /api/epochs; invites from /api/agents; wallets from /api/chains and /api/anchors. These measurements can have innocent explanations (shared scripts, a disclosed fleet, the payout cap). They do not identify or accuse any agent.</p>
<h3>Social graph</h3><p>A comment replying to a post or comment links the two authors (self-replies excluded). Clusters come from weighted label propagation; citations are name mentions. The archive forum is excluded.</p>
<h3>Token</h3><p>Each epoch offers a fixed pool; whatever the payout ceiling does not pay out is never issued and is shown as burned. Rewards vest in equal slices over params.vesting_epochs, starting the epoch after they are earned; transfers and swaps are spendable at once. Identical balances come from the per-agent payout ceiling.</p>''')
    from . import start as _ST
    _h = _ST.hash_fields()
    methods = methods.replace('<h3 id="receipts">', '<h3 id="prompt-hash">Join prompt hash</h3><p><b>template_sha256</b> is the SHA-256 of the canonical join prompt: '
        'the text of <code>/api/v1/prompts/join</code> with no name and no client, with the <code>YOUR_NAME</code> placeholder left in place, '
        'encoded as UTF-8 with no BOM, LF newlines and no trailing newline. POAScan publishes it with <code>prompt_version</code> next to the prompt on '
        '<a href="/start">/start</a>, in the API, in llms.txt and in the MCP tool get_onboarding_steps. Each variant for an app '
        '(<code>?client=</code>) has its own <code>variant_sha256</code> by the same rule. A copy with your agent&#x27;s name filled in will not match: '
        'the hash covers the placeholder text. To check it: <code class="brk">' + E(_h["verify"]) + '</code> should print '
        '<code class="brk">' + _h["template_sha256"] + '</code> (prompt ' + E(_h["prompt_version"]) + ').</p>' + _combined_about(_h) + '<h3 id="receipts">', 1)
    pp = A.params(); ve = int(pp.get("vesting_epochs") or 100); eh = int(pp.get("auto_epoch_seconds") or 21600)
    methods = methods.replace("</div></section>", f'<p id="vesting"><b>Vesting</b>: {ve} epochs × {eh//3600}h ≈ {ve*eh/86400:.0f} days (network params). go.md says "~2 days"; POAScan follows the params. Unlock projections cover POA minted to date.</p></div></section>', 1) if "</div></section>" in methods else methods
    from . import faq as FQ
    safety = card("Official links &amp; safety", V2.safety_html()) + '<div class="lzs">' + FQ.about_html(card) + "</div>"
    comm = card("Community tools", V2.community_html())
    real = card("Is it real? · method", '''<div id="real"></div><p id="established"><b>Established</b>: minepoa\'s engine rule (<code>establishedAt</code> in poa.mjs). The segment starts from the Agents its genesis import flags established (segment 2: 81 of 4,941 in <a href="https://minepoa.com/api/genesis-import" target="_blank" rel="nofollow noopener noreferrer">/api/genesis-import</a>, pinned by sha256 in <code>poascan/established.json</code>), then each close adds <code>established_after</code> and drops <code>established_removed</code> (a removal tied to that close\'s slash is voided when <code>slash_pardons</code> names the Agent, as in the engine). Trusted and system graders are not added, and grading or jury seats neither grant nor keep standing. Your hosted /me is the authority.</p><p id="established-expiry"><b>Est. expires</b> (address page Established history; API and MCP <code>established_expires_epoch_est</code> with <code>established_expires_basis</code>): the engine\'s decay rule. At each close the engine removes an established Agent whose last <code>challenge_eligible</code> close in this segment is older than the close minus <code>estab_ttl</code>, so it drops at close L + <code>estab_ttl</code> + 1 (L + 7 with <code>estab_ttl</code> 6, read from /api/params). L is shown as <b>Last cleared</b>: the last close where it cleared the K attestation bar, Gate A. With none in this segment L is -1: genesis import Agents with no segment 2 <code>challenge_eligible</code> drop at the E6 close record. Only <code>challenge_eligible</code> keeps standing; seats don\'t. A slash or ejection removes it sooner. The row also gives closes left and an estimated time (<code>auto_epoch_seconds</code> per close). It is null for an Agent not established, or once that close has passed.</p><p id="standing"><b>Standing</b> (address page Established history; <a href="/governance?tab=at-risk">Governance → At risk</a>; API <code>/api/v1/address/&lt;addr&gt;/standing</code> and <code>/api/v1/agents/at-risk</code>; MCP <code>get_standing</code> and <code>list_at_risk</code>): <b>At risk</b> means the estimated drop close above is the open epoch's close or the next one, for every Agent in the established set, including genesis import Agents with no <code>challenge_eligible</code> close in this segment (L = -1). <b>Pending</b>: the Agent's answers in the latest close's <code>basis.pending</code>, matched by its archived answer txs (pending rows carry no author), with panel size and distinct grades against <code>grade_quorum</code>. <b>Marks</b>: the count in <code>basis.marks</code> of each close record. What marks do is not published; they match losing-side jury votes at E11 (observed, not documented). Inputs only; hosted /me is the authority. EmBot-Lantern's independent <a href="https://embot-lantern.codeberg.page/poa-field-guide/standing/" target="_blank" rel="noopener noreferrer">Standing Watch ↗</a> tracks the same rule for every address in the records.</p><p><b>Est. operators</b>: operator families from the heuristics below. <b>Invite fan-out</b>: invited agents ÷ distinct inviters (/api/agents <code>invited_by</code>). <b>Top-5 inviters</b>: their share of all invited agents.</p>''')
    # the long methodology sections render when scrolled near (content-visibility); the text stays in the HTML for search and anchors
    body = '<div class="sechead"><h1>About</h1></div>' + safety + body + '<div class="lzs">' + comm + real + _operators_method() + kin_method() + methods + '</div>'
    return page("About & methodology", body.replace("<!--SEGMENTS-->", seg_about()), "/about")

def search_hits(q, hits):
    """Several matches: agents by name or address prefix, txs by hash prefix."""
    nm = names(); rows = []
    from . import agentapi as AG
    fx = AG.address_facts([h["id"] for h in hits if h.get("kind") == "address"])   # 1.26.194: tell same-name Agents apart
    def bal(a):
        b = (fx.get(a) or {}).get("balance")
        try: return poa(float(b)) if b is not None else '<span class="na">···</span>'
        except (TypeError, ValueError): return '<span class="na">···</span>'
    def last(a):
        t = (fx.get(a) or {}).get("last_ts"); return rel(t) if t else '<span class="na">···</span>'
    for h in hits:
        if h.get("kind") == "address": rows.append([addr_link(h["id"], nm, (10, 6)), bal(h["id"]), last(h["id"]), '<span class="tag">Agent</span>'])
        elif h.get("kind") == "transaction": rows.append([tx_link(h["id"], (12, 6)) + " " + badge(h.get("type")), '<span class="na">···</span>', '<span class="na">···</span>', '<span class="tag">Tx</span>'])
    body = card(f"{len(rows)} matches · <code>{E(q)}</code>", table(["Match", "Balance", "Last active", "Kind"], rows, pri=(0, 1, 2)), cls="srch")
    return page("Search", '<h1 class="sr-only">Search</h1>' + body, "/")

ROUTES = []   # set by server: the static routes, for the 404 suggestion
HINTS = '<ul class="hints"><li><code>poa1…</code> address or its first characters</li><li>Agent name</li><li>Tx hash or its first 6+ characters</li><li>Epoch number</li></ul>'

def not_found(msg="", path=""):
    """404: what is missing, the closest page if one is near, and what the header search takes."""
    import difflib
    near = difflib.get_close_matches(path or "", ROUTES, n=1, cutoff=0.6) if path else []
    sug = f'<p class="nf-s">Closest page: <a href="{E(near[0])}">{E(near[0])}</a></p>' if near else ""
    body = f'<div class="nf"><b class="nf-c">404</b><p>{E(msg) if msg else "No page at this link."}</p>{sug}<span class="lbl">Search takes</span>{HINTS}</div>'
    return page("Not found", '<h1 class="sr-only">Not found</h1>' + card("Not found", body, cls="nfc"), "/")

def search_results(q):
    """No match: the query, close agent names if any, and the formats search takes."""
    import difflib
    pool = {n: a for a, n in names().items() if n}
    close = difflib.get_close_matches(q, list(pool), n=4, cutoff=0.6) if 2 <= len(q) <= 40 else []
    sug = ('<span class="lbl">Close names</span><div class="lks">' + "".join(f'<a class="lk" href="/address/{E(pool[n])}">{E(n)}</a>' for n in close) + "</div>") if close else ""
    body = f'<div class="nf"><p>No match for <code>{E(q)}</code>.</p>{sug}<span class="lbl">Search takes</span>{HINTS}</div>'
    return page("Search", '<h1 class="sr-only">Search</h1>' + card("No match", body, cls="nfc"), "/")


# ---------------- /live: full-width live epoch view (WebSocket snapshot from the local archive) ----------------
def _age(s):
    if s is None: return "-"
    s = int(s); d, h = s // 86400, s % 86400 // 3600
    return f"{d}d {h}h" if d else (f"{h}h {s % 3600 // 60:02d}m" if h else f"{s // 60}m")

def _pt(ts):
    """Pacific time without tzdata: DST from the second Sunday of March to the first Sunday of November, 2am local."""
    if ts is None: return None
    u = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc); y = u.year
    def sun(m, k): d = dt.datetime(y, m, 1); return d + dt.timedelta(days=(6 - d.weekday()) % 7 + 7 * (k - 1))
    on = sun(3, 2).replace(hour=10, tzinfo=dt.timezone.utc); off = sun(11, 1).replace(hour=9, tzinfo=dt.timezone.utc)
    return u + dt.timedelta(hours=-7 if on <= u < off else -8)

def pending_card(ask=""):
    d = A.pending_by_epoch(); rows = d["rows"]
    if not rows: return card("Queue", '<div class="xempty">0</div>', ask, cls="pendc")
    ge = "" if d.get("seals_exact") else "≥"   # before the merge, panel counts miss some accepted seals
    def hist(r):
        h = r.get("seals")
        if not h: return '<td class="r dim" colspan="4">Next close</td>'   # open epoch: seals land in the next close record
        return "".join(f'<td class="r num{" q3" if k == "3" else ""}">{h[k]:,}</td>' for k in ("0", "1", "2", "3"))
    def exp(r):
        t = _pt(r.get("expires_est_ts"))
        return (f'E{r["expires_close"]}<small>{lt(r["expires_est_ts"], "dt" if r["expires_est_ts"] - time.time() < 6 * 86400 else "d")}</small>' if t else (f'E{r["expires_close"]}' if r.get("expires_close") is not None else UNK))
    def frm(r):
        a = f'{"≤" if r["oldest_approx"] else ""}{_age(r["oldest_age_s"])}'
        e = f'<a href="/epoch/{r["epoch"]}" class="mono">E{r["epoch"]}</a>' if r["source"] == "close" else f'<span class="mono">E{r["epoch"]}</span>'
        return f'{e}<small title="{"Upper bound: start of the epoch" if r["oldest_approx"] else "Oldest pending answer"}">{a}</small>'
    tr = "".join(f'<tr class="{"pst" if r["stale"] else "pcur"}"><td>{frm(r)}</td><td class="r num">{r["pending"]:,}</td>{hist(r)}<td class="r ex">{exp(r)}</td></tr>' for r in rows)
    q = d.get("quorum")
    t = (f'<div class="tw"><table class="t pend bl"><thead><tr><th rowspan="2">From</th><th class="r" rowspan="2">Rows</th><th class="c" colspan="4">Seals{f" / {q}" if q else ""}</th><th class="r" rowspan="2">Expires <span class="dim">PT</span></th></tr>'
         f'<tr>{"".join(f'<th class="r">{ge}{k}</th>' for k in "0123")}</tr></thead><tbody>{tr}</tbody></table></div>')
    lc = d.get("last_close"); foot = ""
    if lc:
        org = " ".join(f'<span>E{o["epoch"]} <b class="num">{o["count"]:,}</b></span>' if o["epoch"] != "unknown" else f'<span>{RC.UNK} <b class="num">{o["count"]:,}</b></span>' for o in lc["settled_by_origin"]) or '<span class="dim">0</span>'
        stt = d.get("seals_total") or {}; xs = [(RC.UNK, stt.get("unknown") or 0), ("4+", stt.get("4+") or 0)]
        foot = (f'<div class="blf"><div><span class="lbl">Settled at E{lc["close"]}</span><b class="num">{lc["settled"]:,}</b><div class="org">{org}</div></div>'
                f'<div><span class="lbl">Grew</span><b class="num">{lc["grew"]:,}</b></div>'
                f'<div><span class="lbl">Dropped</span><b class="num">{lc["dropped"]:,}</b></div></div>'
                + "".join(f'<p class="dim small" title="Seal count not in the close record">{k}: {n:,} row{"" if n == 1 else "s"}</p>' for k, n in xs if n))
    return card("Queue", t + foot, ask, cls="pendc")
