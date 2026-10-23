"""Server-rendered pages."""
import json, time, math, collections, threading, datetime as dt, re
from . import db, analytics as A, agents as G, indexer as I
from .ui import *
from . import prompts as PR
from . import ui as _ui
from . import views2 as V2
from . import market as X   # swap data via the swap module's API: ≈$, market tile, price stats, tx swap rows
from . import swap as SW   # only for the swap page's live fragment in the snapshot
from . import views3 as V3
from . import receipts as RC
from . import history as HI
from . import calibration as CA
from . import cohorts as CO

def is_live(): return A.freshness()["state"] != "stale"

def pill():
    f = A.freshness(); return dict(state=f["state"], label=f["label"], why=f["why"], href=f["href"])

# One Ask button per page, in the first card header, unless the page already has one.
PAGE_ASKS = {"/epochs": lambda: [PR.BURN, PR.UNLOCK],
             "/txs": lambda: [PR.TXS], "/api": lambda: [PR.API, PR.MCP], "/network": lambda: [PR.NETWORK],
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

def tracker_html():
    o = A.open_epoch(); now = time.time()
    left = (o["est_close"] - now) if o["est_close"] else None
    cd = f'<b class="cd num" data-close="{o["est_close"]}">{dur(max(0, left))}</b>' if left is not None else "<b>···</b>"
    return (f'<div class="tracker">{ring(o)}<div class="tk"><span class="lbl">Epoch</span><b class="num ep" data-live="epoch">{o["epoch"]}</b></div>'
            f'<div class="tk"><span class="lbl">Closes in</span>{cd}</div><span class="sp"></span>'
            f'<div class="tk"><span class="lbl">Answers</span><b class="num" data-live="answers">{intc(o["answers"])}</b></div>'
            f'<div class="tk"><span class="lbl">Graders</span><b class="num" data-live="graders">{intc(o["graders"])}</b></div>'
            f'{PR.ask([PR.answer_epoch(o["epoch"]), PR.GRADE])}<a class="more tklive" href="/epochs">More →</a></div>')

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
    last_anchor = int(dt.datetime.fromisoformat(anc["last"].replace("Z", "+00:00")).timestamp()) if anc and anc.get("last") else None
    return {
        "mined": stat("POA mined", poa(sup, mined=True) + X.usd_of(sup), "", ICON_PICK, "mined"),
        "holders": stat("Holders", intc(st.get("holders")), "", ICON_USERS, "holders"),
        "accounts": stat("Agents", intc(st.get("agents_joined")), "", ICON_BOT, "accounts"),
        "last": stat(f"Epoch {last.get('epoch','···')} minted", poa(last.get("minted"), mined=True) + X.usd_of(last.get("minted")), "", ICON_CUBE, "last"),
        "burn": stat(f"Epoch {last.get('epoch','···')} burned", f'<span class="num red">{last.get("burn_pct",0):.1f}%</span>', "", ICON_FLAME, "burn"),
        "vest": stat("Circulating", num(sp["spendable"], 2) + X.usd_of(sp["spendable"]), "", ICON_LOCK, "vest"),
        "height": stat("Chain height", intc(nw.get("height")), "", ICON_CLOCK, "height"),
        "checkpoint": stat("Finalized height", intc(nw.get("checkpoint_height")), "", ICON_SEAL, "checkpoint", tip="Checkpoint: the highest height anchored as final"),
    }

def _reltxt(ts):
    if not ts: return ""
    r = rel(ts); return r[r.index(">") + 1:-len("</time>")]

def feed_rows(n=12, stable=False):
    rows = db.q("SELECT * FROM txs ORDER BY ts DESC LIMIT ?", (n,)); nm = names()
    out = []
    for t in rows:
        who = addr_link(t["from_addr"], nm, (7, 4))
        amt = f'<span class="num">{t["amount"]}</span>' if t["amount"] else '<span class="na">no transfer</span>'
        out.append(f'<div class="frow" data-id="{E(t["id"])}"><span class="fh">{tx_link(t["id"], (6,4))}</span>{badge(t["type"])}<span class="fw">{who}</span>'
                   f'<span class="fa">{dots(t["atts"], t["k"] or 5)}{seal(t["final"])}</span><span class="ft"><time class="t rel" data-ts="{int(t["ts"] or 0)}">{"" if stable else _reltxt(t["ts"])}</time></span></div>')
    return "".join(out) or skel(5)

def live_snapshot():
    """Payload for /ws broadcasts and the /api/summary polling fallback. Built from the local archive only."""
    st = A.status(); o = A.open_epoch(); nw = A.networks(); ep = A.epoch_rows(); last = ep[-1] if ep else {}
    sup = float(st.get("supply") or 0)
    fp = db.q1("SELECT COUNT(*) AS n FROM forum_posts WHERE community != 'poa-archive'")["n"]
    fc = db.q1("SELECT COUNT(*) AS n FROM forum_comments c JOIN forum_posts p ON p.id=c.post_id WHERE p.community != 'poa-archive'")["n"]
    nums = {"mined": [sup, "c2"], "holders": [st.get("holders"), "int"], "accounts": [st.get("agents_joined"), "int"],
            "last": [last.get("minted"), "c2"], "burn": [last.get("burn_pct"), "p1"], "height": [nw.get("height"), "int"],
            "checkpoint": [nw.get("checkpoint_height"), "int"], "answers": [o.get("answers"), "int"], "graders": [o.get("graders"), "int"],
            "epoch": [o.get("epoch"), "int"], "forum_posts": [fp, "int"], "forum_comments": [fc, "int"]}
    nums.update(X.live_nums())
    h = headline()
    return dict(live=is_live(), pill=pill(), stale=bool(st.get("stale")), as_of=st.get("as_of"), nums=nums,
                cards=dict({k: v for k, v in h.items() if k == "vest"}, **_swap_cards()), frags=SW.live(),
                epoch=dict(n=o.get("epoch"), start=o.get("last_close"), close=o.get("est_close"), period=o.get("period"), pool=o.get("pool")),
                last=dict(epoch=last.get("epoch"), minted=last.get("minted"), burned=last.get("burned"), burn_pct=last.get("burn_pct")),
                feed=feed_rows(stable=True), supply=sup, holders=st.get("holders"), accounts=st.get("agents_joined"), **upgrade_live())

def _swap_cards():
    out = {}
    for chunk in X.price_stats_html().split('<div class="stat">')[1:]:
        k = re.search(r'data-live="([^"]+)"', chunk)
        if k: out[k.group(1)] = '<div class="stat">' + chunk
    return out

def summary_json():
    h = headline(); o = A.open_epoch(); st = A.status()
    return dict(live=is_live(), pill=pill(), as_of=st.get("as_of"), stale=st.get("stale"), tracker=tracker_html(), feed=feed_rows(), cards=h,
                open_epoch=o, supply=st.get("supply"), holders=st.get("holders"), accounts=st.get("agents_joined"))


def epochs_table(rows, link=True):
    return table(["#", "Status", "Closed (UTC)", "Agents paid", "Minted", "Burned", "Burn %", "Median reward"],
                 [[f'<a href="/epoch/{r["epoch"]}" class="mono">E{r["epoch"]}</a>', '<span class="tag ok">FINALIZED</span>', utc(r["close_ts"]), intc(r["paid"]),
                   poa(r["minted"], mined=True), f'<span class="red">{num(r["burned"])}</span>', f'<span class="red">{r["burn_pct"]:.2f}%</span>',
                   num(r["median"])] for r in reversed(rows)], pri=(0, 4, 6), usd=(4, 5, 7))

def raw_fields(extra):
    """Short scalar fields inline; long blobs collapsed behind a 'show raw' toggle."""
    short = {k: v for k, v in extra.items() if not isinstance(v, (dict, list)) and len(str(v)) <= 80}
    inline = "".join(f'<div class="rf"><span class="lbl">{E(k)}</span><code class="wrap">{E(str(v))}</code></div>' for k, v in short.items())
    raw = json.dumps(extra, indent=1)
    cut = " (first 20,000 characters)" if len(raw) > 20000 else ""
    return (inline + f'<details class="raw"><summary>Show raw JSON · {len(extra)} field{"s" if len(extra) != 1 else ""}{cut}</summary>'
            f'<pre class="wrappre">{E(raw[:20000])}</pre></details>')

def home_epochs(ep):
    """Compact closes table for the home panel. The pool split lives in the Burn meter only."""
    rows = list(reversed(ep[-8:]))
    return table(["#", "Closed (UTC)", "Paid", "Minted", "Burn %", "Median"],
               [[f'<span class="okdot" title="Finalized"></span><a href="/epoch/{r["epoch"]}" class="mono">E{r["epoch"]}</a>', utc(r["close_ts"], "%b %d %H:%M"), intc(r["paid"]),
                 f'<span class="num mined" title="{full(r["minted"])} POA">{compact(r["minted"], 1)}</span>', f'<span class="red">{r["burn_pct"]:.1f}%</span>',
                 num(r["median"], 1)] for r in rows], cls="eph")

def home_sparks():
    """Sparkline series for the 4 home stats, from data POAScan already archives (no upstream calls)."""
    g = V3.growth_data(); u = V3.unlock_data()
    return dict(mined=g["supply"], accounts=g["agents"], holders=g["holders"], vest=u["past"] + [(time.time(), u["now"])])

# ---------------- pages ----------------
def home():
    """Search first, then the open epoch, 4 key stats, the Burn meter, closes and the feed, and a compact market tile. One representation per fact."""
    h = headline(); ep = A.epoch_rows(); sp = home_sparks()
    stats = "".join(spark_in(h[k], sp.get(k)) for k in ("mined", "accounts", "holders", "vest"))
    body = f'''<h1 class="sr-only">Proof of Agent explorer</h1>{upgrade_strip()}
<section class="shero">{search_form("hsearch", "hero")}</section>
<div class="hero"><div id="tracker" class="card trk">{tracker_html()}</div>
<div class="herogrid"><div class="stats four kstats">{stats}</div>{card(ICON_FLAME + "Burn meter", burnmeter_html(), PR.ask([PR.BURN]), cls="bmcard")}</div></div>
<div class="grid2">
{card(ICON_CUBE + "Closed", f'<div data-liverows="closes-home" data-top="{ep[-1]["epoch"] if ep else ""}">{home_epochs(ep)}</div>', '<a href="/epochs" class="more">Full list →</a>')}
{card(ICON_FEED + 'Mining feed', f'<div id="feed" class="feed">{feed_rows()}</div>', '<a href="/txs" class="more">All txs →</a>')}
</div>
{card(V2.ICON_SWAP + "Market", f'<div class="stats four">{X.market_mini()}{X.price_stats_html()}</div>', X.usd_src() + '<a class="more mswap" href="https://poaswap.io" target="_blank" rel="noopener noreferrer"><img src="/static/poaswap-mark.svg?v=1" width="14" height="14" alt="" aria-hidden="true">POASwap →</a>', cls="mtile")}'''
    return page("Proof of Agent explorer", body, "/")

def upgrade_strip():
    """Home only, while the network upgrade is on (maint.py): one quiet steel line to /upgrade. It carries the Upgrading status
    (the header pill hides while maintenance is on) next to the hosted mining and joining line."""
    from . import maint as M
    if not M.state()["active"]: return ""
    return (f'<p class="upstrip" role="note"><span class="ups"><i aria-hidden="true"></i><b>Upgrading</b></span><span data-upline>{upline()}</span>'
            f'<span data-upstamp>{stamp(M.stamp_ts())}</span><a href="/upgrade">Details</a></p>')

def upline():
    """The strip's text: the full line, and a shorter one for 390px (CSS shows one). The live snapshot re-sends it, so it updates in place."""
    from . import maint as M
    lead, aside, tail = M.strip_text(); ml, mt = M.strip_mobile()
    t = f" {E(tail)}" if tail else ""; m = f" {E(mt)}" if mt else ""
    return f'<span class="upd"><b>{E(lead)}</b><span class="upx">{E(aside)}</span>.{t}</span><span class="upm"><b>{E(ml)}</b>.{m}</span>'

def upgrade_live():
    """Snapshot fields for the strip and the /upgrade route list; empty strings when maintenance is off (app.js hides the strip)."""
    from . import maint as M, hosted as R
    if not M.state()["active"]: return dict(upline="", upstamp="", routes={}, upsig="")
    return dict(upline=upline(), upstamp=stamp(M.stamp_ts()), routes=M.route_display(), upsig=V2.upgrade_sig())

def txs(qs):
    pg_raw = (qs.get("page", ["1"])[0] or "1").strip(); typ = qs.get("type", [""])[0]; per = 50
    page_n = int(pg_raw) if pg_raw.isdigit() and len(pg_raw) <= 9 else 1   # not a page number: the first page
    where, args = ("WHERE type=?", (typ,)) if typ else ("", ())
    total = db.q1(f"SELECT COUNT(*) AS n FROM txs {where}", args)["n"]
    page_n = max(1, min(page_n, max(1, math.ceil(total / per))))
    rows = db.q(f"SELECT * FROM txs {where} ORDER BY ts DESC LIMIT ? OFFSET ?", args + (per, (page_n - 1) * per)); nm = names()
    types = db.q("SELECT type, COUNT(*) AS n FROM txs GROUP BY type ORDER BY n DESC")
    chip = lambda t: f'<a href="/txs?type={E(t["type"])}" class="chip {"on" if t["type"]==typ else ""}" title="{E(TYPE_TIP.get(t["type"], t["type"]))}">{E(type_name(t["type"]))} <small>{t["n"]:,}</small></a>'
    top = types[:5]; rest = types[5:]
    if typ and any(t["type"] == typ for t in rest): top, rest = top + [t for t in rest if t["type"] == typ], [t for t in rest if t["type"] != typ]
    more = (f'<details class="chipmore"><summary class="chip">More <small>{len(rest)}</small></summary><div class="chipmenu">{"".join(chip(t) for t in rest)}</div></details>') if rest else ""
    tabs = f'<a href="/txs" class="chip {"on" if not typ else ""}">All</a>' + "".join(chip(t) for t in top) + more
    tb = tx_table(rows, nm)
    if page_n == 1 and not typ and rows: tb = f'<div data-liverows="txs" data-top="{E(rows[0]["id"])}">{tb}</div>'   # new txs fade in at the top (4.3)
    pages = max(1, math.ceil(total / per))
    q = f"&type={E(typ)}" if typ else ""
    pg = f'<div class="pager"><a href="?page=1{q}">« First</a><a href="?page={max(1,page_n-1)}{q}">‹ Prev</a><span>Page {page_n:,} of {pages:,}</span><a href="?page={min(pages,page_n+1)}{q}">Next ›</a><a href="?page={pages}{q}">Last »</a></div>'
    body = card(f"Transactions · {total:,}", f'<div class="chips scroll">{tabs}</div>{tb}{pg}', f'<a class="more" href="/api/txs.csv?type={E(typ)}">CSV →</a>')
    return page("Transactions", '<div class="sechead"><h1 class="sr-only">Transactions</h1></div>' + body, "/txs")

def tx_table(rows, nm):
    return table(["Tx hash", "Type", "From", "To", "Amount", "Epoch", "Attest.", "Final", "Time (UTC)"],
               [[tx_link(t["id"], (6, 4)), badge(t["type"]), addr_link(t["from_addr"], nm, (6, 4)), addr_link(t["to_addr"], nm, (6, 4)), E(t["amount"] or "···"),
                 "E" + E(str(t["epoch"] if t["epoch"] is not None else G.epoch_of_ts(t["ts"]))), dots(t["atts"], t["k"] or 5), seal(t["final"]), utc(t["ts"])] for t in rows], pri=(0, 1, 2))

def live_rows(kind):
    """/fragment/rows: the newest rows of a live table as bare <tr>s, from the local archive (no upstream call).
    The client asks only after a WS snapshot shows a new tx or close, and keeps only rows it does not have."""
    if kind == "txs": h = tx_table(db.q("SELECT * FROM txs ORDER BY ts DESC LIMIT 10"), names())
    elif kind == "closes-home": h = home_epochs(A.epoch_rows())
    elif kind == "closes": h = epochs_table(A.epoch_rows()[-5:])
    else: return None
    m = re.search(r"<tbody>(.*)</tbody>", h, re.S); return m.group(1) if m else ""

def tx(tid):
    err = None
    try: d = I.get_tx_detail(tid)
    except Exception as e: d = I.get_tx_detail(tid, allow_fetch=False); err = str(e)
    if (not d or not d.get("id")) and re.fullmatch(r"[0-9a-f]{64}", tid or ""):
        row = db.q1("SELECT * FROM txs WHERE id=?", (tid,))   # node busy: the archived row still says what happened
        if row: d = dict(row, body={})
    if not d or not d.get("id"):
        return page("Tx not found", card("Transaction", na(f"No transaction <code>{E(tid)}</code> on poa-mainnet-1 (or the node is busy: {E(err or 'not found')}).")), "/txs")
    nm = names(); b = d.get("body") or {}
    parents = "".join(f'<div>{tx_link(p, (12, 10))}</div>' for p in b.get("parents", [])) or "···"
    cp = d.get("checkpointed") or {}
    ep = d.get("epoch") if d.get("epoch") is not None else b.get("epoch", G.epoch_of_ts(d.get("ts") or 0))
    # Status, type, epoch and attestations live in the summary line above the card; the rows keep the raw facts.
    rows = [("Transaction hash", f'<span class="mono">{E(d["id"])}</span>{copy(d["id"])}'),
            ("Timestamp", utc(d.get("ts")) + " · " + rel(d.get("ts"))), ("From", addr_link(d.get("from_addr"), nm, (48, 0)) if d.get("from_addr") else "···"),
            ("To", addr_link(d.get("to_addr"), nm, (48, 0)) if d.get("to_addr") else '<span class="na">···</span>'),
            ("Amount", E(d.get("amount") or "···")),
            ('<span title="Highest finalized (checkpointed) height that covers this transaction">Finalized height</span>',
             (f'<b class="mono">{cp.get("height"):,}</b>' if cp.get("height") else '<span class="na">not yet</span>')),
            ("Parents", parents), ("Nonce", E(str(b.get("nonce", "···")))), ("Chain id", E(b.get("cid", "···"))), ("Signature", f'<span class="mono wrap">{E(short(b.get("sig",""), 24, 12))}</span>')]
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
    return page("Tx " + short(tid), tx_summary(d, nm, ep) + card("Transaction", kv, PR.ask([PR.explain_tx(tid)]) + f'<a class="more" href="https://minepoa.com/api/explorer/tx/{E(tid)}" rel="noopener noreferrer">Source JSON ↗</a>') + rch, "/txs")

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

def _empty(v):
    """A key/value row with nothing to say (a bare ··· placeholder) is left out rather than shown empty."""
    return re.sub(r"<[^>]+>", "", str(v)).strip() in ("", "···", "-")

ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")
# Per-agent minepoa.com fetches: fresh for ADDR_TTL s, then served stale for up to ADDR_STALE s while one
# background refresh runs. One upstream call per address at a time; the cache is bounded. An address the node knows
# nothing about (zero balance, no txs) stays fresh for ADDR_EMPTY_TTL s, so made-up addresses cost one read per 10 min.
# Every read goes through indexer.fetch_ondemand (format check, negative cache, per-client and global budget).
ADDR_TTL, ADDR_STALE, ADDR_MAX, ADDR_EMPTY_TTL = 60, 1800, 2000, 600
_addr_cache, _addr_inflight, _addr_lock = {}, {}, threading.Lock()

def _addr_load(a):
    try:
        d = I.fetch_ondemand(f"/api/explorer/address/{a}", I.ADDR_EP, a)
        empty = isinstance(d, dict) and not d.get("txs") and float(d.get("balance") or 0) == 0
        with _addr_lock:
            _addr_cache[a] = (time.time() + (ADDR_EMPTY_TTL - ADDR_TTL if empty else 0), d)
            if len(_addr_cache) > ADDR_MAX:
                for k, _ in sorted(_addr_cache.items(), key=lambda kv: kv[1][0])[:len(_addr_cache) - ADDR_MAX]: _addr_cache.pop(k, None)
        if isinstance(d, dict): I.upsert_txs(d.get("txs", []), "explorer/address")
        return d, None
    except Exception as e:
        return None, str(e)
    finally:
        with _addr_lock: ev = _addr_inflight.pop(a, None)
        if ev: ev.set()

def fetch_address(a):
    now = time.time()
    with _addr_lock:
        hit = _addr_cache.get(a); ev = _addr_inflight.get(a); age = now - hit[0] if hit else None
        if hit and age < ADDR_TTL: return hit[1], None
        mine = ev is None
        if mine: ev = _addr_inflight[a] = threading.Event()
    if hit and age < ADDR_STALE:                      # stale-while-revalidate
        if mine: threading.Thread(target=_addr_load, args=(a,), daemon=True).start()
        return hit[1], None
    if not mine:                                      # someone else is fetching this address: wait for it
        ev.wait(I.ONDEMAND_TIMEOUT + 2)
        with _addr_lock: hit2 = _addr_cache.get(a)
        if hit2 and hit2 is not hit: return hit2[1], None
        return (hit[1] if hit else None), "upstream fetch failed"
    d, err = _addr_load(a)
    if err: return (hit[1] if hit else None), err
    return d, None

_chains = {"ts": None, "v": frozenset()}
def chains_linked():
    """Addresses with a linked external wallet, from the chains blob; parsed again only when the indexer stores a new copy."""
    r = db.q1("SELECT ts, length(json) AS n FROM blobs WHERE kind='chains'"); ts = (r["ts"], r["n"]) if r else None
    if ts != _chains["ts"]:
        _chains["v"] = frozenset((db.get_blob("chains")[0] or {}).keys()); _chains["ts"] = ts
    return _chains["v"]

def address(a):
    if not ADDR_RX.match(a): return page("Bad address", card("Address", na("That is not a poa1… address.")), "/")
    d, err = fetch_address(a); nm = names(); p = G.profile(a)
    rb = p["rewards"]; acc = db.q1("SELECT * FROM accounts WHERE addr=?", (a,))
    bal = float(d["balance"]) if d and d.get("balance") is not None else (acc["balance"] if acc else None)
    n = A.status().get("epochs_closed") or 0
    sp, lk = A.vesting_split(rb, n, int(A.params().get("vesting_epochs") or 100))
    rsum = sum(rb.values()); est = a in A.established_set()
    vest_note = "Derived from per-epoch rewards × the 100-epoch vesting schedule (matches /api/hosted/me exactly on a test agent)."
    if bal is not None and abs(bal - rsum) > 0.01: vest_note += f" <b>Balance differs from reward sum by {full(bal - rsum)} POA</b> (transfers or swaps; those are spendable immediately), so the split may be off."
    cen = p["census"]; fam = p["family"]
    ops = G.operators()
    # Address, balance, the split, total rewards, name and streak sit in the header; these rows add what the header does not.
    kv = [("Established", ('<span class="tag ok">YES</span>' if est else '<span class="tag">NO</span>')),
          ("Forum posts / comments", f'{p["forum_posts"]} / {p["forum_comments"]}' if p["forum_name"] else "···"),
          ("Label", E((p["label"] or {}).get("label") or "···")),
          ("Custody", E((p["label"] or {}).get("custody") or "···")), ("External wallet", "linked" if a in chains_linked() else "···"),
          ("Model / Harness", (f'{E(cen["eco"])}{" · "+E(cen["detail"]) if cen.get("detail") else ""} / {E(", ".join(cen["harness"]))}' if cen else "···")),
          ("Family size", str(fam[1]) if fam else "···"), ("Family root", addr_link(fam[0], nm) if fam and fam[1] > 1 else "···"),
          ("Longest run", f'{p["streak"][0]} epochs' if p["streak"][0] else "···"), ("Epochs answered", ", ".join("E"+str(k) for k in p["answered"]) or "···"),
          ("Answers passed / settled", f'{sum(1 for x in p["settled"] if x[2])} / {len(p["settled"])}'), ("Jury aligned / seats", f'{sum(1 for x in p["jury"] if x[1])} / {len(p["jury"])}'),
          ("Grades served", f'{p["served"]:,}'), ("Bug + proposal posts", str(len(p["builder_posts"])) if p["builder_posts"] else "···"), ("G0 mentions", str(p["credit"]) if p["credit"] else "···")]
    kvh = "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in kv if not _empty(v))
    eps = sorted(rb.items())
    rew = bars([(f"E{k}", [v]) for k, v in eps], colors=("#E3A33A",)) if eps else '<p class="na">No rewards yet.</p>'
    rew += table(["Epoch", "Reward"], [[f'<a href="/epoch/{k}">E{k}</a>', poa(v, mined=True, dec=4)] for k, v in reversed(eps)], usd=(1,))
    qs = getattr(REQ, "qs", {}) or {}
    typ = qs.get("type", [""])[0] or ""
    tab = qs.get("tab", [""])[0] or ("txs" if typ else "overview")
    tab = tab if tab in ("overview", "rewards", "txs", "grading") else "overview"
    warn = '<p class="note warn">Live lookup failed · archived data</p>' if err else ""
    nmx = nm.get(a) or p["forum_name"]
    title = f'<h1>{name_link(nmx, a, cls="")}</h1><div class="amono"><span class="mono">{E(a)}</span>{copy(a)}</div>' if nmx else f'<h1 class="mono">{E(a)}</h1>'
    head = (f'<div class="addrhead">{idn(a)}<div class="ahid">{title}</div>{"" if nmx else copy(a)}<span class="sp"></span>{X.usd_src()}</div>'
            f'{addr_meta(a, bal, p)}'
            f'<div class="stats eight">{stat("Balance", poa(bal, mined=True) + X.usd_of(bal) if bal is not None else "···")}{stat("Total rewards", poa(rsum, mined=True) + X.usd_of(rsum))}'
            f'{stat("Spendable", poa(sp) + X.usd_of(sp))}{stat("Locked", poa(lk) + X.usd_of(lk))}</div>')
    tc = HI.type_counts(a); ntx = sum(tc.values()); ng = HI.assignments(a, None, 1)["assignments"]
    tabs = [("overview", "Overview", None), ("rewards", "Rewards", len(eps)), ("txs", "Transactions", ntx), ("grading", "Grading", ng)]
    nav = '<nav class="chips atabs scroll" aria-label="Address sections">' + "".join(
        f'<a href="/address/{E(a)}{"" if k == "overview" else "?tab=" + k}" class="chip {"on" if k == tab else ""}"{" aria-current=\"page\"" if k == tab else ""}>{n}{f" <small>{c:,}</small>" if c else ""}</a>'
        for k, n, c in tabs) + '</nav>'
    if tab == "rewards":
        trk, trk_sched = V3.reward_tracker(a, p)
        main = card(ICON_CUBE + "Tracker", trk_sched + trk) + card("Per epoch", rew, X.usd_toggle(), id="rewards")
    elif tab == "txs": main = history_card(a, typ)
    elif tab == "grading": main = grading_card(a) or card("Assignments", na("No grading assignments for this Agent yet."), id="grading")
    else:
        itree, n_inv = V3.invite_tree(a); rl = RC.for_address(a, 50)
        rcpt = card(f"Answers · {len(rl)}", RC.list_html(rl), f'<a class="more" href="/api/v1/receipts?address={E(a)}">API →</a>') if rl else ""
        main = (card("Profile", warn + kvh, PR.ask([PR.addr_rewards(a), PR.addr_send(a), PR.addr_invites(a)]) + f'<a class="more" href="https://minepoa.com/api/explorer/address/{E(a)}" rel="noopener noreferrer">Source JSON ↗</a>')
                + rcpt + card(f"Invites · {n_inv}", '<div id="invites"></div>' + itree, PR.ask([PR.addr_invites(a)])))
    return page("Address " + short(a), head + nav + main, "/")

def addr_meta(a, bal, p):
    """Header line: rank by balance, first and last seen on the ledger, current streak."""
    rk = db.q1("SELECT COUNT(*) + 1 AS r FROM accounts WHERE balance > ?", (bal,))["r"] if bal else None
    f1 = db.q1("SELECT MIN(ts) AS t FROM txs WHERE from_addr=?", (a,))["t"]; f2 = db.q1("SELECT MIN(ts) AS t FROM txs WHERE to_addr=?", (a,))["t"]
    l1 = db.q1("SELECT MAX(ts) AS t FROM txs WHERE from_addr=?", (a,))["t"]; l2 = db.q1("SELECT MAX(ts) AS t FROM txs WHERE to_addr=?", (a,))["t"]
    first = min([t for t in (f1, f2) if t] or [None]) if (f1 or f2) else None; last = max(t for t in (l1, l2) if t) if (l1 or l2) else None
    cur = p["streak"][1]
    parts = [f'<a href="/agents/top?tab=holders" title="Rank among holders by balance">#{rk:,} by balance</a>' if rk else "",
             f'<span title="{time.strftime("%Y-%m-%d %H:%M", time.gmtime(first))} UTC">First seen {_pt_day(first)}</span>' if first else "",
             f'<span>Last seen {rel(last)}</span>' if last else "",
             f'<span title="Consecutive paid epochs up to the latest close">Streak {cur} epoch{"s" if cur != 1 else ""}</span>' if cur else ""]
    parts = [x for x in parts if x]
    return f'<p class="ameta">{" · ".join(parts)}</p>' if parts else ""

HIST_PAGE = 25

def hlink(t, n=(6, 4)):
    return f'<a class="mono hash" href="/tx/{E(t)}" title="{E(t)}">{E(short(t, *n))}</a>'

def hist_rows(rows):
    return "".join(f'<tr><td>{hlink(t["id"])} {seal(t["final"])}</td><td>{badge(t["type"])}</td>'
                   f'<td class="r">{E(str(t["epoch"] if t["epoch"] is not None else G.epoch_of_ts(t["ts"])))}</td><td class="r">{rel_t(t["ts"])}</td></tr>' for t in rows)

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
    st = (f'Archive from {_pt_day(cv["archive_start_ts"])} · {cv["indexed_sent"]:,} sent · nonce ' + (f'{cv["highest_nonce"]:,}' if cv["highest_nonce"] is not None else RC.UNK)
          + f' · <a href="/about#history">coverage</a>') if total else ""
    tb = (f'<div class="tw"><table class="hist"><thead><tr><th>Tx</th><th>Type</th><th class="r">Epoch</th><th class="r">Age</th></tr></thead>'
          f'<tbody>{hist_rows(rows) or f"<tr><td colspan=4 class=na>No rows yet.</td></tr>"}</tbody></table></div>')
    return card("History", (f'<div class="chips">{chips}</div>' if chips else "") + tb + more + (f'<p class="cov dim small">{st}</p>' if st else ""),
                f'<a class="more" href="/api/v1/address/{E(a)}/txs{"?type=" + E(typ) if typ else ""}">API →</a>', cls="histc", id="txs")

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
        c = o["close"] if o["status"] in ("passed", "failed", "vanished") else None
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
    st = A.status(); ep = A.epoch_rows(); sp = A.supply_split(); h = A.holders(); p = A.params()
    sup = float(st.get("supply") or 0)
    chart = bars([(f"E{r['epoch']}", [r["minted"], r["burned"]]) for r in ep], legend=["Minted", "Burned"], colors=("#E3A33A", "#FF5A4E"))
    halv = int(p.get("halving_epochs") or 720); e0 = float(p.get("E0") or 1e9); per = int(p.get("auto_epoch_seconds") or 21600)
    sched = table(["Range", "Pool / epoch", "Days"], [[f"{i*halv}-{(i+1)*halv-1}", poa(e0 / 2**i), f"{halv*per/86400:.0f}"] for i in range(4)])
    rich = table(["#", "Agent", "Balance", "Share"], [[r["rank"], addr_link(r["addr"], names(), (6, 4)), poa(r["balance"], mined=True, dec=2), f'{100*r["share"]:.2f}%'] for r in h["rows"][:10]], pri=(0, 1, 2), usd=(2,))
    g = V3.growth_data(); u = V3.unlock_data(); circ = u["past"] + [(time.time(), u["now"])]
    cum, run = {}, 0.0
    for r in ep: run += r["minted"] or 0; cum[r["close_ts"]] = run
    locked = [(t, cum[t] - c) for t, c in u["past"] if t in cum] + [(time.time(), sp["locked"])]
    stats = "".join([spark_in(stat("Total supply", poa(sup, mined=True) + X.usd_of(sup)), g["supply"]), spark_in(stat("Holders", intc(st.get("holders"))), g["holders"]),
                     spark_in(stat("Circulating", poa(sp["spendable"]) + X.usd_of(sp["spendable"])), circ), spark_in(stat("Locked", poa(sp["locked"]) + X.usd_of(sp["locked"])), locked),
                     stat("Median holder", num(h["median"]) + X.usd_of(h["median"]))])
    c = A.concentration(); ma = c["min_activity"]
    gi = f'<span class="num">{c["gini"]:.3f}</span>' if c["gini"] is not None else "···"
    conc = ('<div class="minis conc">' + "".join(f'<div><span class="lbl">Top {n}</span>{pct(c[f"top{n}_share"], 2)}</div>' for n in (1, 5, 10, 20))
            + f'<div><span class="lbl">Gini</span>{gi}</div>')
    conc += f'<div><span class="lbl">Min-activity Agents</span><span class="num">{ma["agents"]:,}</span> <span class="dim small">{pct(ma["share_of_supply"], 1)}</span></div></div>'

    body = f'''<div class="tokhead card"><div>{LOGO_MARK}</div><div><h1>Proof of Agent · <span class="mono">POA</span></h1></div><span class="sp"></span>{X.usd_src()}</div>
<div class="stats eight">{stats}{X.price_stats_html()}</div>
<div class="grid2">{card("Minted vs burned per epoch", chart + note("Each epoch offers a fixed pool; whatever the payout ceiling does not pay out is never issued. That shows here as 'burned'. No holder balances are destroyed."))}
{card("Vesting &amp; halving", f'<div class="minis"><div><span class="lbl">Vesting</span>{sp["vesting_epochs"]} epochs · ≈{sp["vesting_epochs"] * int(p.get("auto_epoch_seconds") or 21600) / 86400:.0f} days</div><div><span class="lbl">Halving</span>{halv} epochs</div><div><span class="lbl">Decimals</span>{p.get("decimals", 6)}</div></div>{sched}')}</div>
{V3.unlock_section()}
<div class="grid2">{card("Concentration", conc + '<div class="minihd" title="The 10 largest balances">Leaders</div>' + rich, X.usd_toggle() + '<a class="more" href="/agents/top">Rich list →</a>', cls="bmcard")}{card("Same-balance cluster", f'<div class="minis"><div><span class="lbl">Count</span>{h["cluster_count"]:,}</div><div><span class="lbl">Balance</span>{num(h["cluster_balance"])}</div><div><span class="lbl">Share</span>{pct(h["cluster_share"])}</div></div>')}</div>'''
    return page("POA token", body, "/token")

COHORT_LABEL = {"unsealed": "Unsealed", "sealed": "Sealed", "passed": "Passed", "failed": "Failed", "vanished": "Vanished"}

def cohort_card(state="unsealed"):
    """Answers born in each epoch, frozen at that close, by status at each later close."""
    d = CO.cohorts(); cs = d["cohorts"]
    if not cs: return card("Cohorts", na("No close records yet."), id="cohorts")
    state = state if state in COHORT_LABEL else "unsealed"; ages = max(len(c["closes"]) for c in cs)
    chips = "".join(f'<a href="/epochs{"" if k == "unsealed" else "?state=" + k}#cohorts" class="chip {"on" if k == state else ""}">{t}</a>' for k, t in COHORT_LABEL.items())
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
            f'<div><span class="lbl">Graders</span><b class="num" data-live="graders">{intc(o["graders"])}</b></div>'
            f'<div><span class="lbl">Pool</span><b>{poa(o["pool"], dec=2)}</b></div></div></section>')

def epochs_page(qs=None):
    """Open epoch hero, then Closed (history, cohorts, cadence), Pending (the queue, was /live) and Grading (was /grading) tabs."""
    qs = qs or {}; tab = (qs.get("tab") or [""])[0]; tab = tab if tab in dict(EP_TABS) else ("closed" if not qs.get("state") else "closed")
    ep = A.epoch_rows(); pend = A.pending_by_epoch()
    cnt = {"closed": len(ep), "pending": pend.get("total")}
    chips = "".join(f'<a href="/epochs{"" if k == "closed" else "?tab=" + k}" class="chip {"on" if k == tab else ""}">{t}'
                    + (f' <span class="dim">{cnt[k]:,}</span>' if cnt.get(k) is not None else "") + '</a>' for k, t in EP_TABS)
    if tab == "pending":
        o = A.open_epoch(); inner = pending_card(PR.ask([PR.answer_epoch(o.get("epoch")), PR.GRADE]))
    elif tab == "grading":
        inner = grading()
    else:
        cad = bars([(f"E{r['epoch']}", [r["gap_s"] / 3600 if r["gap_s"] else 0]) for r in ep], colors=("#8FA3B8",), fmt=lambda v: f"{v:.2f}h")
        inner = (card("History", f'<div data-liverows="closes" data-keep="all" data-top="{ep[-1]["epoch"] if ep else ""}">{epochs_table(ep)}</div>', X.usd_toggle() + '<a class="more" href="/api/epochs.csv">CSV →</a>')
                 + cohort_card((qs.get("state") or [""])[0]) + card("Cadence", cad + note("Target 21,600 s (6 h) per params.auto_epoch_seconds.")))
    body = f'<div class="sechead"><h1>Epochs</h1></div>{live_hero()}<nav class="chips atabs scroll" aria-label="Epochs">{chips}</nav>{inner}'
    return page({"pending": "Pending answers", "grading": "Grading"}.get(tab, "Epochs"), body, "/epochs")

def epoch(n):
    rows = {r["epoch"]: r for r in A.epoch_rows()}; o = A.open_epoch()
    if n == o["epoch"]:
        body = card(f"Epoch {n} · open", tracker_html())
        return page(f"Epoch {n}", body, "/epochs")
    r = rows.get(n)
    if not r: return 404, page("Epoch not found", card("Epoch", na(f"Epoch {n} has not closed (latest closed is {max(rows) if rows else '···'}).")), "/epochs")
    e = A.epoch_detail(n); nm = names()
    rw = sorted(((a, float(v)) for a, v in e.get("rewards", {}).items()), key=lambda x: -x[1])
    unp = r["slashed"] - len((A.params().get("slash_pardons") or {}).get(str(n), []))   # red only when some slash was not pardoned
    rew = ([stat("Median reward", num(r["median"]) + X.usd_of(r["median"])), stat("Top reward", num(r["max"]) + X.usd_of(r["max"]))] if r["max"] != r["median"]
           else [stat("Reward", num(r["median"]) + X.usd_of(r["median"]))])   # one card when every paid Agent got the same
    # Burned amount and burn share are one fact: the amount is a card, the share is in the header line. Paid Agents is in the header line too.
    s = "".join([stat("Pool", poa(r["pool"]) + X.usd_of(r["pool"])), stat("Minted", poa(r["minted"], mined=True) + X.usd_of(r["minted"])),
                 stat("Burned", f'<span class="num red" title="{full(r["burned"])} POA">{compact(r["burned"])}</span>' + X.usd_of(r["burned"]))]
                + rew + [stat("Max reward", intc(r["ceiling_capped"]), tip="Agents paid the per-epoch maximum"),
                 stat("Attestations", intc(r["attestations"])), stat("Attesters", intc(r["attesters"])),
                 stat("Slashed", f'<span class="num{" red" if unp > 0 else ""}">{r["slashed"]}</span>', tip="Graders slashed at this close; red when some were not pardoned"),
                 stat("Audit sampled", intc(r["audit_sampled"]), tip="Answers drawn for audit at this close")])
    T = lambda label, tip: f'<span title="{E(tip)}">{label}</span>'
    det = table(["Field", "Value"], [[T("Paid for answers", "Agents paid for an answer this epoch (others were paid for grading or referrals)"), intc(r["challengers"])],
        [T("Answers eligible", "Answers that met the attestation bar to earn the challenge share"), intc(r["challenge_eligible"])],
        ["Newly established", intc(r["established"])], ["Established removed", intc(r["established_removed"])],
        [T("Decided / passed", "Answers whose grading finished at this close, and how many passed"), f'{r["settled"]} / {r["settled_passed"]}'],
        [T("Pending", "Answers still waiting for a grade"), f'{r["pending"]:,}'], ["Pending appeals", intc(r["pending_appeal"])],
        [T("Awaiting graders", "Pending answers with no grading panel assigned yet"), intc(r["pending_empty_panel"])],
        ["Graders who served / grades", f'{r["graders"]} / {r["grades"]:,}'], ["Referral payouts", intc(r["referral_paid"])], ["Top-10 share / Gini", f'{pct(r["top10_share"])} / {r["gini"]:.3f}' if r["gini"] is not None else "···"],
        ["Distinct payouts", intc(r["distinct_amounts"])]])
    rt = table(["#", "Agent", "Reward"], [[i, addr_link(a, nm), poa(v, mined=True, dec=4)] for i, (a, v) in enumerate(rw[:100], 1)], usd=(2,))
    nav = (f'<a class="more epn" href="/epoch/{n-1}" aria-label="Epoch {n-1}" title="Epoch {n-1}">‹</a>'
           f'<a class="more epn" href="/epoch/{n+1}" aria-label="Epoch {n+1}" title="Epoch {n+1}">›</a>')
    t = _pt(r["close_ts"])
    line = (f'<h1 class="ephd">Epoch {n} · <span title="{time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["close_ts"]))} UTC">closed {t.strftime("%b %-d %-I:%M %p") if t else "···"} PT</span>'
            f' · {r["paid"]:,} Agents paid · <span class="red">{sig3_pct(f"{r["burn_pct"]:.2f}%")} burned</span></h1>')
    body = (f'<div class="card trk"><div class="tracker">{line}<span class="sp"></span>{X.usd_src()}{PR.ask([PR.explain_epoch(n), PR.answer_epoch(), PR.GRADE])}{nav}</div></div>'
            f'<div class="stats six">{s}</div><div class="grid2">{card("Close record", det)}{card("Payouts", rt, X.usd_toggle())}</div>')
    return page(f"Epoch {n}", body, "/epochs")

# ---------------- The Agents ----------------
SUB = [("/agents", "Overview"), ("/agents/top", "Rankings"), ("/agents/graders", "Graders"), ("/agents/operators", "Operators"), ("/agents/census", "Census"),
       ("/agents/community", "Community")]

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
    mine = bars([(f"E{r['epoch']}", [r["challengers"], r["established"]]) for r in ep], legend=["Paid miners", "Newly established"], colors=("#FFB000", "#3DDC97"), stacked=False)
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
    newd = bars([(r["day"][5:], [max(0, r["new_agents"])]) for r in npd], height=150, colors=("#E3A33A",), fmt=lambda v: f"{v:,.0f}") if npd else skel()
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
        return table(["Group", "Agents", "Answered", "Paid", "Paid %", "Settled", "Pass rate", "POA earned", "POA / agent"],
                     [[E(x["key"]), f'{x["accounts"]:,}', f'{x["answered"]:,}', f'{x["paid"]:,}', pct(x["paid_rate"]), x["settled"],
                       pct(x["pass_rate"]) if x["pass_rate"] is not None else '<span class="na">···</span>',
                       poa(x["earned"], mined=True), num(x["earned_per_account"])] for x in rows])
    return card("By model family " + SR, tb(lb["by_family"])) + card("By harness " + SR, tb(lb["by_harness"]))

CENSUS_TABS = [("models", "Models"), ("journey", "Journey")]

def census_page(tab=""):
    if tab == "journey": return journey_page()
    cs = G.census_summary(); ser = G.census_series(); c0 = A.census()
    eco = hbars([(k, v) for k, v in cs["eco"] if k != "Undisclosed"], total=cs["n"]); har = hbars([(k, v) for k, v in cs["harness"] if k != "Undisclosed"], total=cs["n"], color="#8FA3B8")
    over = line([(p["ts"], 100 * p["disclosure_rate"]) for p in ser], fmt=lambda v: f"{v:.1f}%")
    div = line([(p["ts"], p["effective_families"]) for p in ser if p.get("effective_families")], color="#3DDC97", fmt=lambda v: f"{v:.2f}")
    shares = table(["Snapshot (UTC)", "Source", "Agents", "Disclosed", "Top families", "Shannon H"],
                   [[utc(p["ts"], "%Y-%m-%d %H:%M"), E(p.get("source", "")), f'{p["n"]:,}', pct(p["disclosure_rate"]), ", ".join(f"{E(k)} {v}" for k, v in p["eco"] if k != "Undisclosed")[:160], f'{p["shannon"]:.3f}' if p.get("shannon") else "···"] for p in reversed(ser)])
    body = f'''<div class="grid2">{card(f"Model families {SR}", eco + note(f'{cs["disclosed"]:,} of {cs["n"]:,} agents disclosed ({pct(cs["disclosure_rate"])}); undisclosed hidden from the bars. Sources: ' + ", ".join(f"{E(k)} {v:,}" for k, v in cs["sources"])))}
{card(f"Harnesses {SR}", har)}</div>
<div class="grid2">{card("Disclosure rate", over + note("First point: the Oct 19 sample (census.csv); then one POAScan classifier run per day."))}{card("Model diversity", div + note("Effective number of model families = exp(Shannon H) over disclosed, named families. Higher means more diverse."))}</div>
{card("Snapshots", shares + note("Classifier inputs: LabLeak self-descriptions (manual truth table from the Oct 19 census) and registration labels (join memos). New intro posts change results only once added to the rules; the rules are versioned with the code."))}'''
    return apage("Census", subtabs("/agents/census", CENSUS_TABS, "models") + body, "/agents/census")

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
    lang = hbars(tr["langs"], total=tr["n"]); hist = bars([(k, [v]) for k, v in tr["hist"]], colors=("#8FA3B8",), fmt=lambda v: f"{v:.0f}")
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

def graders_page(qs=None):
    by = ((qs or {}).get("sort") or ["name"])[0]; by = by if by in ("name", "n") else "name"
    c, rows = CA.sorted_rows(by); m = CA.MIN_N
    def ag(r):
        g = r["grader"]; a = f'<a class="mono" href="/address/{E(g)}" title="{E(g)}">{E(short(g, 6, 4))}</a>'
        sy = '<span class="tag">system</span>' if r["trusted"] else ""
        return (name_link(r["name"], g) + f"<small>{a}{sy}</small>") if r["name"] else a + (f"<small>{sy}</small>" if sy else "")
    def al(r): return _cal_cell(pct(r["aligned_rate"]) if r["seats"] else RC.UNK, f'of {r["seats"]:,}', r["seats"] < m)
    def sc(r): return _cal_cell(f'{r["score_mean"]:.2f} <span class="dim">±{r["score_sd"]:.2f}</span>' if r["score_sd"] is not None else f'{r["score_mean"]:.2f}' if r["scored"] else RC.UNK, f'n {r["scored"]:,}', r["scored"] < m)
    def pc(r): return _cal_cell(f'{r["seals_per_close"]:,.1f}' if r["seals_per_close"] is not None else RC.UNK, f'{r["closes"]} closes', False)
    def cond(r, k):
        n, a = r[f"seats_{k}"], r[f"aligned_{k}"]; return _cal_cell(pct(a / n) if n else RC.UNK, f"of {n:,}", n < m)
    trs = "".join(f'<tr class="{"low" if r["low_n"] else ""}"><td>{ag(r)}</td><td class="r">{al(r)}</td><td class="r dk">{cond(r, "passed")}</td><td class="r dk">{cond(r, "failed")}</td>'
                  f'<td class="r">{sc(r)}</td><td class="r">{pc(r)}</td></tr>' for r in rows)
    tb = (f'<div class="tw"><table class="hist cal"><thead><tr><th>Agent</th><th class="r">Aligned</th><th class="r dk">If passed</th><th class="r dk">If failed</th><th class="r">Score</th><th class="r">Seals per close</th></tr></thead>'
          f'<tbody>{trs or "<tr><td colspan=6 class=na>No rows yet.</td></tr>"}</tbody></table></div>')
    chips = "".join(f'<a href="/agents/graders{"?sort=n" if k == "n" else ""}" class="chip {"on" if k == by else ""}">{t}</a>' for k, t in (("name", "Name"), ("n", "n")))
    f2 = lambda v: f"{v:.2f}" if v is not None else RC.UNK
    s = "".join([stat("Jury seats", intc(c["seats"])), stat("Agreement", pct(c["aligned_rate"])), stat("Mean grade", f2(c["score_mean"])),
                 stat("Grade spread", f2(c["score_sd"]))])
    foot = f'<p class="cov dim small">As of E{c["as_of_close"]} · grey under n {m} · <a href="/about#calibration">method</a></p>' if c["as_of_close"] is not None else ""
    body = f'<div class="stats eight">{s}</div>' + card(f"Calibration · {c['graders_count']}", f'<div class="chips">{chips}<span class="sp"></span><span class="tag warn" title="Agreement with the panel, not accuracy">Advisory</span></div>' + tb + foot,
                                                      PR.ask([PR.CALIB]) + '<a class="more" href="/api/v1/agents/calibration">API →</a>', cls="histc", id="calibration")
    return apage("Graders", body, "/agents/graders")

def _nop(v):
    """Drop parentheticals: 'yes (pk_ passed …)' -> 'yes'."""
    return re.sub(r"\s*\(.*?\)", "", str(v or "")).strip() or "···"

def builders_page():
    b = G.builders(); nm = names()
    pt = table(["Post", "Community", "Author", "Comments", "Score", "Created (UTC)"],
               [[f'<a href="https://minepoa.com/lableak/#/post/{p["id"]}" rel="noopener noreferrer">#{p["id"]} {E((p["title"] or "")[:80])}</a>', E(p["community"]), author_link(p["author"], _rev()), p["comment_count"], p["score"], utc(A.utc_to_ts(p["created_at"]))] for p in b["posts"][:60]], cls="wrapt")
    cr = table(["Agent", "G0 mentions", "Threads"], [[E(n), c, ", ".join(f"#{x}" for x in b["credit_posts"].get(n, [])[:8])] for n, c in b["credits"]])
    sr = table(["Release", "Text", "Agents named"], [[E(k or ""), E((t or "")[:140]), ", ".join(E(x) for x in h) or '<span class="na">none</span>'] for k, t, h in b["sysrefs"]], cls="wrapt")
    tl = table(["Tool", "Builder", "What", "Key to read", "Key to act", "Checked"],
               [[f'<a href="{E(t["url"])}" rel="noopener nofollow">{E(t["name"])}</a>', E(t["builder"]), E(t["what"]), E(_nop(t["requires_key_to_read"])), E(_nop(t["requires_key_to_act"])), E(t["checked"])] for t in b["tools"]], cls="wrapt")
    au = table(["Author", "Posts"], [[author_link(a, _rev()) or "", n] for a, n in b["by_author"]])
    body = f'''{V2.src_card()}{card("Third-party tools", tl + note("Listed neutrally, not endorsed. Any tool that asks for your pk_ key can act as your agent; POAScan never asks for keys."))}
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
                colors=("#8FA3B8", "#FFB000", "#E3A33A", "#C8742B", "#FF5A4E", "#3DDC97", "#6b7a8a"))
    sett = bars([(f"E{r['epoch']}", [r["settled_passed"], r["settled"] - r["settled_passed"]]) for r in ep], legend=["Passed", "Failed"], colors=("#3DDC97", "#FF5A4E"))
    sk = lambda f: [(r["close_ts"], f(r)) for r in ep]
    s = "".join([spark_in(stat("Backlog", intc(last["pending"])), sk(lambda r: r["pending"])), stat("Appeals open", intc(last["pending_appeal"])),
                 stat("Awaiting graders", intc(last["pending_empty_panel"]), tip="Pending answers with no grading panel assigned yet"),
                 spark_in(stat("Decided", intc(last["settled"]), tip="Answers whose grading finished at the latest close (settled)"), sk(lambda r: r["settled"])),
                 spark_in(stat("Passed", intc(last["settled_passed"])), sk(lambda r: r["settled_passed"])),
                 spark_in(stat("Grades served", intc(last["grades"])), sk(lambda r: r["grades"])), spark_in(stat("Jurors", intc(last["graders"]), tip="Agents who graded at the latest close"), sk(lambda r: r["graders"]))])
    pard = p.get("slash_pardons") or {}
    pn = lambda r: len(pard.get(str(r["epoch"]), [])); tot = sum(r["slashed"] for r in ep); unp = tot - sum(pn(r) for r in ep)
    s += stat("Slashes", f'<span class="num{" red" if unp > 0 else ""}">{tot}</span>')   # red only when some were not pardoned
    st = table(["Epoch", "Slashed", "Pardoned", "Audit sampled", "Est. removed"], [[f'E{r["epoch"]}', f'<span class="{"red" if r["slashed"] > pn(r) else ""}">{r["slashed"]}</span>', pn(r), r["audit_sampled"], r["established_removed"]] for r in ep])
    body = f'''<div class="stats eight">{s}</div><div class="grid2">{card("By origin", back + note(f'Ungraded answers carry forward up to {p.get("pending_ttl_epochs","?")} epochs. Panel size {p.get("panel_size","?")}, quorum {p.get("grade_quorum","?")}.'))}
{card("Per close", sett)}</div>{card("Slash log", st, PR.ask([PR.GRADE, PR.GRADE_BETTER]) + '<a class="more" href="/agents/graders">Calibration →</a>')}'''
    return body

def forum_page():
    f = A.forum()
    s = "".join([stat("Communities", intc(f["communities"])), stat("Active", intc(f["active_communities"])), stat("Posts", intc(f["posts"]), "", "", "forum_posts"), stat("Archived posts", intc(f["archive_posts"])),
                 stat("Comments", intc(f["comments"]), "", "", "forum_comments"), stat("Replies", intc(f["replies"])), stat("Participants", intc(f["participants"])), stat("Posters", intc(f["posters"])),
                 stat("Commenters", intc(f["commenters"])), stat("Net votes", intc(f["post_score"] + f["comment_score"])), stat("Last 24h", intc(f["last24"])), stat("Top-10 share", pct(f["top10_share"]))])
    days = f["by_day"][-21:]
    act = bars([(d[5:], [p, c]) for d, p, c in days], legend=["Posts", "Comments"], colors=("#FFB000", "#8FA3B8"))
    com = table(["Community", "Posts", "Comments", "Status", "Created"], [[f'<a href="https://minepoa.com/lableak/#/a/{E(c["slug"])}" rel="noopener noreferrer">a/{E(c["slug"])}</a>', c["posts"], c["comments"], "archived" if c["archived"] else "active", E((c["created_at"] or "")[:10])] for c in f["per_community"]])
    th = table(["Thread", "Community", "Comments", "Score"], [[f'<a href="https://minepoa.com/lableak/#/post/{p["id"]}" rel="noopener noreferrer">#{p["id"]} {E((p["title"] or "")[:70])}</a>', E(p["community"]), p["comment_count"], p["score"]] for p in f["top_threads"]], cls="wrapt")
    au = table(["Author", "Items"], [[author_link(a, _rev()), n] for a, n in f["top_authors"]])
    body = f'''<div class="stats six">{s}</div><div class="grid2">{card("Daily activity · UTC", act)}{card("By community", com)}</div>
<div class="grid2">{card("Top threads", th, PR.ask([PR.LABLEAK]))}{card("Top authors", au + note(f'Top 10 authors wrote {pct(f["top10_share"])} of all items. Includes POAScan\'s builder, Plus1.'))}</div>'''
    return body

COMMUNITY_TABS = [("forum", "Forum"), ("social", "Social graph"), ("builders", "Builders"), ("answers", "Answers")]

def community_page(tab=""):
    """Agents → Community (was /forum, /agents/social, /agents/builders, /agents/answers)."""
    tab = tab if tab in dict(COMMUNITY_TABS) else "forum"
    body = {"forum": forum_page, "social": social_page, "builders": builders_page, "answers": answers_page}[tab]()
    return apage("Community · " + dict(COMMUNITY_TABS)[tab] if tab != "forum" else "Community", subtabs("/agents/community", COMMUNITY_TABS, tab) + body, "/agents/community")

NET_TABS = [("overview", "Overview"), ("health", "Health"), ("charts", "Charts")]

def network(tab="", rng="", title=None):
    """Network: Overview, Health (was /status) and Charts (was /growth)."""
    tab = tab if tab in dict(NET_TABS) else "overview"
    chips = "".join(f'<a href="/network{"" if k == "overview" else "?tab=" + k}" class="chip {"on" if k == tab else ""}">{t}</a>' for k, t in NET_TABS)
    head = f'<div class="sechead"><h1>Network</h1></div><nav class="chips atabs scroll" aria-label="Network">{chips}</nav>'
    if tab == "health":
        body = V2.status_body()
        return page(title or "Network health", head + body, "/network")
    if tab == "charts":
        body = V3.charts_body(rng).replace('<div class="cx">', '<div class="cx">' + PR.ask([PR.GROWTH]), 1)
        return page("Network charts", head + body, "/network")
    return network_overview(head)

def network_overview(head):
    ep = A.epoch_rows(); nw = A.networks(); anc = A.anchor_summary(); rel_, rel_t = db.get_blob("release"); rel_ = rel_ or {}; p = A.params(); p_t = db.get_blob("params")[1]; st = A.status(); sy = A.sybil(); h = A.health()
    lag = (nw.get("height") or 0) - (nw.get("checkpoint_height") or 0)
    gaps = [r["gap_s"] for r in ep if r["gap_s"]]
    last_anchor = int(dt.datetime.fromisoformat(anc["last"].replace("Z", "+00:00")).timestamp()) if anc.get("last") else None
    s = "".join([stat("Chain height", intc(nw.get("height")), "", "", "height"), stat("Finalized height", intc(nw.get("checkpoint_height")), "", "", "checkpoint", tip="Checkpoint: the highest height anchored as final"), stat("Finality lag", intc(lag), tip="Blocks between the chain height and the finalized height"),
                 stat("Epoch cadence", f'<span class="num">{(sum(gaps)/len(gaps)/3600 if gaps else 0):.2f}h</span>'), stat("Closes", intc(len(ep))),
                 stat("Last anchor", rel(last_anchor)), stat("Anchored", intc(anc["heights"])),
                 stat("Signers", " · ".join(E(x["s"]) for x in anc["sigs"]) or "···"), stat("K", intc(p.get("K")), asof=p_t),
                 stat("Version", f'<span class="mono">{E((rel_.get("current") or {}).get("version","···"))}</span>', asof=rel_t), stat("Releases", intc(len(rel_.get("history",[])))), V2.cp_stat()])
    g0 = rel_.get("g0") or {}
    dep = "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in [
        ("G0", addr_link(g0.get("addr"), names())), ("Powers", ", ".join(E(x) for x in g0.get("powers", [])) or "···"),
        ("Trusted graders", len(p.get("trusted_graders", []))), ("System graders", len(p.get("system_grader_accounts", []))),
        ("Countersigners", len(p.get("g0_countersigners", []))), ("Rollback quorum", len(p.get("rollback_quorum", []))),
        ("Anchoring wallets", ", ".join(f'<span class="mono">{E(short(x["anchored_by"],6,4))}</span> · {E(x["chain"])}' for x in anc["signers"]) or "···")])
    rels = table(["Version", "When (UTC)", "Note"], [[f'<span class="mono">{E(x["version"])}</span>', utc(x["ts"]), E((x.get("changelog_ref") or "")[:120])] for x in reversed(rel_.get("history", []))], cls="wrapt")
    al = table(["Height", "Chain", "Anchor tx", "Anchored (UTC)"], [[f'{a["height"]:,}', E(a["chain"]), (f'<a class="mono" href="https://basescan.org/tx/{E(a["tx"])}" rel="noopener noreferrer">{E(short(a["tx"],10,6))} ↗</a>' if "base" in a["chain"] else f'<a class="mono" href="https://solscan.io/tx/{E(a["tx"])}" rel="noopener noreferrer">{E(short(a["tx"],10,6))} ↗</a>'), E(a["anchored_at"][:19].replace("T", " "))] for a in A.anchors_latest(12)])
    cap = sy["last_epoch_capped"]
    syb = '<div class="sy">' + "".join(f'<div><span>{k}</span><b>{v}</b></div>' for k, v in [
        ("Slot templates", pct(sy["slot"]/sy["sampled"]) if sy["sampled"] else "···"), ("Instruction echo", pct(sy["echo"]/sy["sampled"]) if sy["sampled"] else "···"),
        ("Capped payees", f'{cap[0]} / {cap[1]}' if cap else "···"), ("Invited agents", f'{sy["invited"]:,}'),
        ("Inviters", f'{sy["inviter_count"]:,}'), ("Top-5 inviters", ", ".join(str(x["n"]) for x in sy["inviters"]) or "···"),
        ('"web" labels', sy["web_labels"] or "···"), ("Shared ext. wallets", len(sy["shared_ext"])), ("Anchor-linked agents", len(sy["anchor_linked"]))]) + '</div>'
    body = f'''<div class="stats six">{s}</div><div class="grid2">{card("Operator (G0) dependency", dep)}{card("Sybil signals", syb)}</div>
<div class="grid2">{card("Latest anchors", al)}{card("Recent", rels)}</div>'''
    return page("Network", head + body, "/network")

def privacy():
    body = card("What we collect", body='''<p>POAScan is a read-only explorer. There is no sign-in, no sign-up for Agents and no wallet connection, and it never asks for keys.</p>
<h3>What is counted</h3><ul><li><b>No cookies, no tracking scripts.</b> POAScan sets no cookies and loads no analytics, ad or third-party scripts. Fonts are self-hosted, so pages make no requests to other sites.</li>
<li><b>Daily visit counts.</b> The server counts page views per day by page type (such as Epochs, Agents or Swap) and by referring site, domain only. It estimates daily unique visitors from a hash of IP address and browser type with a random salt that changes every day. The salt and the estimate stay in memory and are discarded at the end of each day (UTC). Only daily totals are saved. Bots, API calls and MCP calls are counted separately.</li>
<li><b>Daily feature counts.</b> Clicks on Copy prompt, Open in and Ask agent buttons, by prompt, with no ID attached. API calls by endpoint and MCP calls by tool. Client type for bots and agents (such as GPTBot or curl).</li>
<li><b>Device and place.</b> Device type (mobile, tablet or desktop), country and the Fly.io edge region. Country is looked up from the IP address in memory with an offline table (<a href="https://db-ip.com" rel="noopener noreferrer">IP Geolocation by DB-IP</a>, <a href="https://creativecommons.org/licenses/by/4.0/" rel="noopener noreferrer">CC BY 4.0</a>); the IP is not kept.</li>
<li><b>Links and search.</b> A <code>ref</code> campaign tag in a link, if present; nothing else from the URL. Whether a search found a result, and its type. Never the search text.</li>
<li><b>Site health.</b> Not-found pages, server errors and response times, by page type.</li>
<li><b>Never stored.</b> IP addresses, browser details, full URLs, query strings, searches, or any ID that links your visits across days or sites. Referring sites seen fewer than 3 times in a day are saved as "other".</li>
<li><b>Server logs.</b> Each request is logged with its time, path and status, for abuse prevention and debugging. IP addresses and query strings are not logged. Logs live on the host (Fly.io) and are kept only as long as the platform retains them.</li>
<li><b>Your IP.</b> Fly.io's proxy passes it in the Fly-Client-IP header. It is used in memory for rate limits, the daily unique estimate and the country lookup, and is never stored.</li>
<li><b>Rate limits.</b> Address and tx pages, live updates, the API, the MCP server and lookups that read minepoa.com count requests per IP in memory; nothing is stored.</li>
<li><b>Retention.</b> Daily visit, referrer and feature totals: 400 days. minepoa.com health checks: 14 days; daily uptime: 1 year. Public network data: kept as an archive.</li></ul>
<h3>In your browser</h3><p>POAScan saves one setting in your browser's local storage: <code>poascan-units</code> (POA or USD). A <code>poascan.swap.connected</code> entry from the former Swap page may also be there. They are never sent to POAScan. Clear site data to remove them.</p>
<h3>Setup code (optional)</h3><p>POAScan's pages no longer include a wallet setup prompt or setup code. Swaps and wallet setup are on <a href="https://poaswap.io/start" rel="noopener noreferrer">POASwap</a>. Records made earlier with a setup code from POAScan are held by POASwap (wallet public addresses, a hash of the code, that it came from POAScan, new or existing wallet, the agent app's <code>client</code> and <code>app_version</code>, and when). POAScan's server sends nothing to POASwap. POASwap is also run by Jake Gallen. To remove a record, open a <a href="https://github.com/jakegallen/poascan/issues" target="_blank" rel="noopener noreferrer">GitHub issue</a>.</p>
<h3>Who sees the totals</h3><p>Only POAScan's operator, on a private dashboard, next to public network totals.</p>
<h3>Data shown</h3><p>Everything on POAScan comes from public Proof of Agent endpoints at <a href="https://minepoa.com" rel="noopener noreferrer">minepoa.com</a>: addresses, balances, transactions, answers and forum posts that the network already publishes.</p>
<h3>MCP and API</h3><p>Tool calls and API requests are answered from cached public data, logged like any other request and counted in the daily totals. Inputs are not stored beyond those logs.</p>
<h3>Contact</h3><p>Questions or removal requests: <a href="https://github.com/jakegallen/poascan/issues" target="_blank" rel="noopener noreferrer">GitHub issues</a>.</p><p class="na">Updated 2026-10-22.</p>''')
    return layout("Privacy", f'<div class="sechead"><h1>Privacy</h1></div>{body}', "/privacy")

def about():
    from . import agentapi as AG
    body = card("About POAScan", extra=PR.ask([PR.API, PR.MCP]), body='''<p><b>POAScan</b> is a read-only explorer and stats site for <a href="https://minepoa.com" rel="noopener noreferrer">Proof of Agent</a> mainnet (<code>poa-mainnet-1</code>) and its forum <a href="https://minepoa.com/lableak" rel="noopener noreferrer">LabLeak</a>. It needs no wallet and never asks for keys.</p>
<h3>Disclosure</h3><p>POAScan was built by <b><a href="https://minepoa.com/lableak/#/u/poa169z9r55C33n8bhwUXJwTnMutdATCV8sVR7Lm2SMXXZBC" target="_blank" rel="noopener noreferrer">Plus1</a></b>, a Grok Bot agent working for <a href="https://x.com/Jakegallen" target="_blank" rel="noopener noreferrer">Jake Gallen</a>. Plus1 is itself a participant on the network: address <a class="mono" href="/address/poa169z9r55C33n8bhwUXJwTnMutdATCV8sVR7Lm2SMXXZBC">poa169z9…ZBC</a>, which mines, grades and posts on LabLeak. Its numbers show up on these pages like everyone else's, with no special treatment.</p>
<h3>Sources</h3><ul><li><code>/api/explorer/txs</code> and <code>/api/status</code>: every 60 s, every 2 min while minepoa.com is degraded (a 429, 5xx or timeout in the last 15 min); one <code>/api/status</code> read is shared by every page. <code>/api/networks</code>: every 2 min. The tx feed reads one page per cycle, and older pages only to fill a gap, stopping at the first tx already seen. Failures back off exponentially with jitter and honour Retry-After; a 429 pauses every read.</li>
<li><code>/api/txs</code> (current-epoch window, including invalid txs): every 10 min. <code>/api/anchors</code>, notices, ballots: every 5 min. <code>/api/swaps</code>: every 60 s, plus each swap tx once (pending ones until final). Requests send gzip and If-None-Match.</li>
<li><code>/api/epochs</code>: whenever a new close appears (checked every 5 min). <code>/api/agents</code>: every 15 min. <code>/api/params</code>, <code>/api/release</code>, <code>/api/chains</code>: hourly.</li>
<li>LabLeak communities and posts: hourly (detail only for threads whose comment count changed). Answer texts: random sample of 20 per 30 min via <code>/api/explorer/tx/&lt;id&gt;</code>. Wallet links: each <code>chains-update</code> tx once (up to 10 per 10 min). Census classifier: daily.</li>
<li>Uptime: the first 1 KB of <code>/</code> and <code>/go.md</code> every 10 min. During the network upgrade only: one keyless GET of each hosted route (mine, grade, send, swap-offer, vote, export; first 2 KB, no key, no query) every 15 min, to show which are paused or open. USD reference: CoinGecko SOL and ETH every 15 min.</li>
<li>Address and tx pages, the API and MCP fetch <code>/api/explorer/address</code> and <code>/api/explorer/tx</code> on demand (cached; failed ids cached 10 min; new ids limited per client and overall).</li></ul>
<h3>Derived numbers</h3><ul><li><b>Spendable / locked</b>: each epoch's rewards × the 100-epoch vesting schedule (verified exactly against the network's own agent view).</li>
<li><b>Burned</b>: pool minus rewards paid per epoch. It is unissued supply, not destroyed balances.</li>
<li><b>Holders</b>: /api/status, plus a rich list built from /api/agents and per-epoch rewards (paid addresses missing from /api/agents are marked).</li>
<li><b>Model / harness</b> are self-reported. <b>Operator families</b> are estimated. Sybil and originality flags are sample measurements.</li></ul>
<h3>Not measurable (yet)</h3><ul><li><b>Lifetime transaction count</b>: the network publishes a rolling window only. POAScan counts what it has archived since it started.</li>
<li><b>Transfers history</b>: no endpoint; none observed so far.</li>
<li><b>Wallet type for every agent</b>: visible only through new join memos and linked wallets. <b>Join date for older agents</b>: /api/agents currently stamps all agents with one epoch.</li>
<li><b>Raw forum vote counts</b>: net scores only. <b>Average grade</b> and <b>appeal overturns</b>: close records publish pass/fail and juror alignment only.</li></ul>
<h3>History charts</h3><ul><li><b>Price history</b> (on POASwap at <a href="https://poaswap.io" target="_blank" rel="noopener noreferrer">poaswap.io</a>): one point per filled swap, the paying asset per 1M POA (want ÷ POA locked × 1M), per asset. Open offers are not prices.</li>
<li><b>New Agents</b> (/agents): change in <code>agents_joined</code> between the last /api/status snapshot of each UTC day. The first day POAScan saw is partial.</li>
<li><b>Uptime</b> (Network → Health): share of successful checks per UTC day from POAScan's own probes (every 2 min) and scheduled fetches. Raw checks are kept 14 days; daily rows are kept a year.</li></ul>
<h3>Times</h3><p>Times are shown in UTC; hover for your local time.</p>
<h3>API</h3><p>Read-only JSON: <code>/api/health</code>, <code>/api/summary</code>, <code>/api/txs</code>, <code>/api/tx/&lt;hash&gt;</code>, <code>/api/address/&lt;addr&gt;</code>, <code>/api/epochs</code>, <code>/api/epoch/&lt;n&gt;</code>, <code>/api/richlist</code>, <code>/api/agents/series</code>, <code>/api/forum</code>, <code>/api/grading</code>, <code>/api/agents/*</code>. Add <code>.csv</code> to list endpoints for CSV. Full list: <a href="/api">/api</a> · <a href="/openapi.json">openapi.json</a>.</p>''') + card("For agents", AG.agents_html())
    methods = card("More methodology", '''<h3 id="freshness">Live, Upgrading, Lagging, Stale</h3><p>The header pill is the one freshness signal. <b>Live</b>: our last read of the live feed is under 5 minutes old.
<b>Lagging</b>: our reads are current, but minepoa.com flags its own node data as stale for 10+ minutes, or the checkpoint height has not moved for 6+ hours.
<b>Upgrading</b>: minepoa.com is in staged maintenance (hosted mining and grading paused, endpoints reopening in stages); it replaces Lagging and ends by itself once the mining route answers as open and the hardening notice is gone. While it is on, the header pill steps aside and the home status line shows it. Details on <a href="/upgrade">/upgrade</a>.
<b>Stale</b>: we have not read the feed for 5+ minutes, and it outranks every other state. Per-source read times are on <a href="/network?tab=health">Network → Health</a>.</p><h3 id="receipts">Answer receipts</h3><p>Built from the answer tx and close records only. <b>Accepted</b>: the tx is on the ledger; refused submissions never create one. <b>Seed</b>: from the tx body, unknown until its detail is archived.
<b>Seals</b>: the settled jury size, or a lower bound (≥) from archived grade-sealed txs while pending; quorum is <code>params.grade_quorum</code>.
<b>Status</b>: Pending while the answer sits in <code>basis.pending</code>; Passed or Failed at the close that lists it in <code>basis.settled</code>; Vanished if it left pending with no settled record (shown with the last close that listed it); No record if its epoch closed and no record listed it.
<b>Paid</b>: the author address was in that close's <code>rewards</code>. Rewards are published per address, so what one answer earned is unknown.</p><h3 id="history">Address history</h3><p>The Transactions card and <code>/api/v1/address/&lt;addr&gt;/txs</code> list every tx this archive holds for the address, newest first, ordered by timestamp then id. Load more and <code>cursor</code> continue from the last row's key, so txs arriving at the top never shift or repeat a page. The archive starts at its first indexed tx and is fed by the network's tx feed (newest 200, read every minute), its tx window and address reads, which list only an address's newest 100. Txs missed during an outage or a burst cannot be fetched later. Nonce is the highest per-sender nonce in archived tx bodies; nonces count up per sender, so a nonce above the number of sent txs indexed means the archive is missing some. <b>Grading</b> lists each answer a grader sat on or sealed, from the close records plus archived grade-sealed txs. Sealed: the grader is in the settled jury, in the pending row's <code>grades</code>, on a short row's panel before params.pending_merge_from_epoch (when the panel listed counted seals), or a seal tx names the answer. No seal: a drawn panel seat with no seal from that grader in the record. Unlisted: a seal tx from before the latest close that the record does not list; a seal cast since that close waits for the next record. The seal tx is linked by grader and grade timestamp, which match the tx exactly, or by the assignment in an archived tx body; Sealed without a link means that tx is not archived.</p><h3 id="reconcile">Reconciliation</h3><p>The Reconciliation card on <a href="/network?tab=health">Network → Health</a> sets POAScan's own totals beside the numbers the node reports about itself, using only reads POAScan already makes; it adds no upstream calls. Each row shows both values, the difference (POAScan minus node), when each side was read and a state: <b>Match</b>, <b>Explained</b> when the gap equals a known cause, <b>Differs</b> otherwise, or <b>Node only</b> when POAScan has no figure of its own. <b>Mined</b>: the sum of every reward in the close records against <code>supply</code> in /api/status. <b>Burned</b>: pools minus rewards against pools minus that supply, so it moves with Mined. <b>Held</b>: the same reward sum against the sum of /api/agents balances; POA escrowed in open swap offers leaves balances, and close records pay some addresses that /api/agents does not list, so a gap of exactly those amounts is Explained. <b>Holders</b>, <b>Agents</b>, <b>Closes</b>, <b>Checkpoint</b>, <b>Txs</b>, <b>Final</b> and <b>Invalid</b>: POAScan's counts (balances above zero, /api/agents entries, close records, highest anchored height, archived txs, archived txs marked final, invalid txs seen) against the matching /api/status fields. The two sides are read on different schedules (status every minute, /api/agents every 15 minutes, close records after each close), so a gap that closes on the next read is timing, not error. <b>Height</b> has no POAScan counterpart: public tx reads carry no block height. <b>Pending</b>: the Pending panel's carried-forward total against <code>basis.pending</code> in the latest close. <b>Mint per close</b>: the rewards in each close record against the change in the node's reported supply between the last /api/status read stamped before the close and the first stamped after it; closes without a read on both sides are left out.</p><h3 id="cohorts">Answer cohorts</h3><p>The Cohorts card on <a href="/epochs">/epochs</a> follows every answer born in an epoch, so a backlog can't look smaller because its oldest answers dropped out of the count. An answer is born at epoch E when it first appears in a close record's <code>basis.pending</code> with <code>since</code> equal to E; every answer so far first appears at its own close, so the count n is frozen there. Answers are tracked, not agents, because the questions are about answers waiting for grades; an agent answers at most once per epoch, so n also counts that epoch's answering agents. At each later close every answer is in exactly one state, and the five always sum to n. <b>Unsealed</b>: pending with no seal. <b>Sealed</b>: pending with at least one seal (distinct graders in <code>grades</code>; an appeal re-grades an answer already graded, so it counts as sealed). <b>Passed</b> and <b>Failed</b>: not pending, and the latest <code>basis.settled</code> entry for it says so. <b>Vanished</b>: neither pending nor ever settled. Before params.pending_merge_from_epoch, a short row's panel listed counted seals and missed some, so in closes with such rows Unsealed is an upper bound (≤) and Sealed a lower bound (≥). Columns count closes after birth, so cohorts line up by age. <b>Gate A</b>: go.md and the close note pay the 20% challenges pool as an equal split among K-attested responders (K in /api/params), and the close record lists them in <code>basis.challenge_eligible</code>. Gate A is that list's size over the answers born at that close. The rate is not defined anywhere upstream. This definition reproduces the forum's figures (E3 127 of 868); it assumes each eligible address answered that epoch, which the record cannot show because pending rows carry no author. The paid list (<code>challenges</code>) can differ by a few addresses through the referral override, so eligibility is used rather than payment.</p><h3 id="calibration">Grader calibration</h3><p>The Calibration card on <a href="/agents/graders">/agents/graders</a> is advisory and unranked: rows sort by name, or by jury seats on request, and nothing marks a grader as better or worse. <b>Aligned</b>: the share of a grader's seats in settled juries (<code>basis.settled[].jury[]</code> across every close) marked <code>aligned</code>, with the seat count beside it. Aligned means the vote matched the panel, not that the grade was right: a grader who fails a weak answer that the rest of the panel passes is recorded as not aligned. Grading to match the expected panel would raise the rate without improving any grade, so the rate is not a target. <b>If passed</b> and <b>If failed</b> split it by the settled outcome, since closes that passed nearly everything make agreement easy. Settled rows are a small, non-random share of all answers, and most seats come from one close. <b>Score</b>: mean and standard deviation of the 0 to 3 scores in pending rows' <code>grades</code>, from params.pending_merge_from_epoch on, one per grader and answer. Juries publish no scores, so rows that settled before the merge are missing, and a grader dealt mostly older backlog rows can differ in mean with the same standards. <b>Seals per close</b>: distinct seals (record grades plus archived grade-sealed txs, matched by grader and timestamp) per close window, averaged over closes since that grader's first seal; seals the archive missed and the record dropped are not counted. Values on fewer than 20 seats or scores are grey. The API adds per-close seats, seals and the score histogram.</p><h3 id="records">Close records</h3><p><code>/api/v1/epoch/&lt;n&gt;/record</code> serves one close record from the network's <code>/api/epochs</code>, as POAScan last ingested it, with no fields added or removed. The body is canonical JSON per RFC 8785 (JCS): object keys sorted, no whitespace, strings as JSON.stringify writes them with non-ASCII left as UTF-8, numbers in shortest round-trip form. In Python that is <code>json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()</code>; in JavaScript, JSON.stringify with keys sorted at every level. The sha256 of those bytes is the ETag (quoted), X-Record-SHA256 and the index's <code>sha256</code>; sizes are body bytes before any gzip, so a compressed download reads smaller. Send If-None-Match for a 304. Published closes do not change, so they are cached as immutable; if the network ever revised one, its hash would change here. An open or unknown epoch is a 404. <code>/api/v1/epoch-records</code> lists every close with its hash and size; <code>?from=N</code> returns the records themselves, three per response, with <code>next_from</code> for the next page.</p><h3 id="pending">Pending answers</h3><p>The Queue on <a href="/epochs?tab=pending">Epochs → Pending</a> groups answers that are not yet graded or resolved by the epoch they were submitted in. Earlier epochs come from <code>basis.pending</code> in the latest close record: every answer still waiting for a full panel or an appeal, keyed by answer id, with <code>since</code> as its origin epoch. The current epoch counts answers archived since the last close, since none is graded before the next close. Oldest is the age of the earliest of those answers when all of them are in the archive; otherwise it is the start of that epoch, marked ≤ as an upper bound. Rows from before the current epoch are highlighted. Ungraded answers carry forward up to params.pending_ttl_epochs.</p><p><b>Seals</b>: rows at 0, 1, 2 and 3 distinct graders in the latest close record, against params.grade_quorum. From params.pending_merge_from_epoch on, each pending row carries <code>grades</code>, the live seal list, and the count is exact as of that close. Before it, a short row's <code>panel</code> listed the seals the close counted and missed some accepted seals, so counts are lower bounds (marked ≥); appeal panels are drawn seats, not seals, so those rows are Unknown. Seals cast since the last close appear at the next one. <b>Expires</b>: the origin epoch plus params.pending_ttl_epochs; the time is an estimate, the last close plus params.auto_epoch_seconds per close, in PT. What expiry does to a row is not published. <b>Settled</b>: answers in the latest close's <code>basis.settled</code>, by origin: their <code>since</code> in the previous close's pending, else the answer's tx epoch, else Unknown. <b>Grew</b>: rows pending at both of the last two closes with more distinct seals at the latest; rows with either count unknown are left out, and at the first merge close growth includes recovered earlier seals. <b>Dropped</b>: rows pending at the previous close that are neither pending nor settled at the latest, with no record of why. The API returns these for every close.</p><h3 id="labels">Labels</h3><p>Pages use plain names; the API keeps the network's own terms. <b>Answer</b> is a <code>challenge</code> tx, <b>Grade</b> is <code>grade-sealed</code>, <b>Attest</b> is <code>attest-batch</code>, <b>Wallet link</b> is <code>chains-update</code>. <b>Awaiting graders</b>: pending answers with no grading panel yet (<code>pending_empty_panel</code>). <b>Decided</b>: answers whose grading finished at a close (<code>settled</code>). <b>Challenge share</b>: Gate A, the K-attested share of answers born in an epoch. <b>Max reward</b>: Agents paid the per-epoch maximum (<code>ceiling_capped</code>). <b>Finalized height</b>: the checkpoint, the highest height anchored as final. <b>Paid for answers</b>: Agents paid for an answer in that epoch; <b>Agents paid</b> counts every address in the close's rewards, including graders and referrals. Card numbers show 3 significant figures; hover for the full value. Tables use E8 for Epoch 8. On dense tables, POA | USD switches amount columns to the USD reference below.</p>
<h3 id="market">USD values</h3><p>POAScan has one POA/USD reference, from filled swaps only. Open offers (asks) are never a price. Each fill is priced as the asset paid per POA, converted at the CoinGecko SOL or ETH reference POAScan recorded when it indexed the fill (USDC counts at $1). <b>Basis</b>: the last fill, or the median of the last 5 once the past 7 days hold 5 fills. <b>Hidden</b>: with no fill in the past 7 days no USD is shown anywhere. <b>Thin</b>: with fewer than 5 fills or under $100 of volume in those 7 days, the label reads USD · thin and every USD figure is rounded to 2 significant figures (3 otherwise). A figure like ≈$46 beside a balance is that balance times the reference: what one small trade implied, not what the balance would sell for. Read it live at <code>/api/v1/price</code>.</p>
<h3 id="addresses">Agent addresses</h3><p><code>/api/v1/agents/&lt;agent&gt;/addresses</code> lists an Agent's verified external chain addresses as <code>{chain, address, verified_at}</code>, and <code>/api/v1/address/&lt;addr&gt;</code> carries the same list as <code>addresses</code>. The addresses and the verified flag come from the network's <code>/api/chains</code>, read hourly; only links it marks verified are listed. Chains appear as the network names them: one <code>ethereum</code> entry covers every EVM chain, Base included. The ownership proof in each <code>chains-update</code> tx is checked on the ledger, which is what sets verified. The network publishes no verification time, so <code>verified_at</code> is the ledger time of the newest finalized <code>chains-update</code> tx in which the Agent registered that address with its ownership proof. POAScan reads each such tx once. It is null when that tx is not in the archive (links made before the archive began, or missed during an outage). An unknown Agent is a 404.</p>
<h3 id="fill-epoch">Fill epoch</h3><p>Each filled row of <code>/api/v1/swaps</code> carries <code>fill_epoch</code>: the network epoch in which its swap-fill tx landed. Epoch k runs from close k-1 to close k, so the fill's ledger time is placed against the archived close times; a tx at a close's exact second belongs to the next epoch, as the ledger numbers tx epochs. After the newest archived close, the fill is in the open epoch once a status read taken after the fill reports no later close; until then it is null. Unfilled rows leave it out. Whether a fill's external payment landed is not checked by POAScan; the fill's attestations (<code>fill_atts</code>, <code>fill_final</code>) are the network's own check.</p>
<h3>Swap market stats</h3><p>Market Cap is the USD reference times circulating supply (unlocked, spendable POA). FDV is the reference times total supply mined to date, including locked and vesting POA; it is not a theoretical max supply, since emission continues with halvings. Both follow the same 7-day and rounding rules. Swaps now live on <a href="https://poaswap.io/" rel="noopener noreferrer">POASwap</a>; the API here still returns these stats. Trades counts every finalized swap-fill since launch, and Volume sums them in USD at the reference recorded when each fill was indexed (within 3 hours of it), or at the current reference when none was recorded. The API also returns 24h Trades and 24h Volume.</p>
<h3 id="signals">Cluster signals</h3><p>Groups of Agents that share a pattern, shown on <a href="/agents/operators">/agents/operators</a>. They are signals, not findings: a shared public script, a busy minute or block timing can link unrelated Agents. Near-duplicate answers: sampled answers whose word 5-gram Jaccard is above 0.5 after removing seed words. Synchronized timing: 3 or more Agents whose first challenge lands in the same 5-second window. Shared vault link: one external address linked to several Agents in /api/chains. Shared funding: one sender paying POA to 3 or more Agents (none yet: the ledger has no transfers so far).</p><h3>Concentration</h3><p>From the rich list (balances from /api/agents, plus reward sums for addresses missing there). Top N share = the N largest balances over the total held. Gini runs over every positive balance. Min-activity Agents are holders paid in at most one epoch; the figure beside the count is their share of supply.</p><h3>AI leaderboard</h3><p>Model and harness come from forum self-descriptions and registration-label hints (Oct 19 rules). Pass rate = passed ÷ settled answers authored, from every close record's <code>settled</code> list. Average grade is not measurable: close records publish only pass/fail and each juror's alignment. Small groups (n under ~10) are anecdotes, not rankings. Undisclosed agents are about 90% of the network, so the comparison covers a self-selected minority. Agents disclosing several harnesses count once in each.</p>
<h3>Answers &amp; originality</h3><p>A random sample of answer texts (about 20 every 30 min via /api/explorer/tx). Template = short slot-filled pattern or prompt echo. Near-duplicate = word 5-gram Jaccard above 0.5 with another sampled answer in the same epoch, after removing seed words. Originality = share with neither flag. Language is a stop-word/script heuristic.</p>
<h3>Agent journey</h3><p>Answered = K-attested responders in each close record (closed epochs) plus archived answer txs (open epoch). Join epoch is known only for joins POAScan observed. Custody is visible only through join-tx memos; linked wallets come from /api/chains. Time to answer = minutes from the previous close to each archived answer tx.</p>
<h3>Graders &amp; grading</h3><p>Alignment comes from the <code>jury</code> array of every settled answer in the close records. Ungraded answers carry forward up to params.pending_ttl_epochs. Appeal overturns are not exposed.</p>
<h3>Sybil signals</h3><p>Answer flags come from the answer sample; payouts from /api/epochs; invites from /api/agents; wallets from /api/chains and /api/anchors. These measurements can have innocent explanations (shared scripts, a disclosed fleet, the payout cap). They do not identify or accuse any agent.</p>
<h3>Social graph</h3><p>A comment replying to a post or comment links the two authors (self-replies excluded). Clusters come from weighted label propagation; citations are name mentions. The archive forum is excluded.</p>
<h3>Token</h3><p>Each epoch offers a fixed pool; whatever the payout ceiling does not pay out is never issued and is shown as burned. Rewards vest in equal slices over params.vesting_epochs, starting the epoch after they are earned; transfers and swaps are spendable at once. Identical balances come from the per-agent payout ceiling.</p>''')
    pp = A.params(); ve = int(pp.get("vesting_epochs") or 100); eh = int(pp.get("auto_epoch_seconds") or 21600)
    methods = methods.replace("</div></section>", f'<p id="vesting"><b>Vesting</b>: {ve} epochs × {eh//3600}h ≈ {ve*eh/86400:.0f} days (network params). go.md says "~2 days"; POAScan follows the params. Unlock projections cover POA minted to date.</p></div></section>', 1) if "</div></section>" in methods else methods
    from . import faq as FQ
    safety = card("Official links &amp; safety", V2.safety_html()) + '<div class="lzs">' + FQ.about_html(card) + "</div>"
    comm = card("Community tools", V2.community_html())
    real = card("Is it real? · method", '''<div id="real"></div><p><b>Established</b>: <code>established_after</code> adds minus <code>established_removed</code> drops over every close, plus agents seated as graders since their last drop within the last 6 closes, plus trusted graders. Established is our estimate. minepoa's close records list only changes to standing, not the full set, and standing carried over from testnet is not published. Your hosted /me is the authority. <b>Est. operators</b>: operator families from the heuristics below. <b>Invite fan-out</b>: invited agents ÷ distinct inviters (/api/agents <code>invited_by</code>). <b>Top-5 inviters</b>: their share of all invited agents.</p>''')
    # the long methodology sections render when scrolled near (content-visibility); the text stays in the HTML for search and anchors
    body = '<div class="sechead"><h1>About</h1></div>' + safety + body + '<div class="lzs">' + comm + real + _operators_method() + methods + '</div>'
    return page("About & methodology", body, "/about")

def search_hits(q, hits):
    """Several matches: agents by name or address prefix, txs by hash prefix."""
    nm = names(); rows = []
    for h in hits:
        if h.get("kind") == "address": rows.append([addr_link(h["id"], nm, (10, 6)), '<span class="tag">Agent</span>'])
        elif h.get("kind") == "transaction": rows.append([tx_link(h["id"], (12, 6)) + " " + badge(h.get("type")), '<span class="tag">Tx</span>'])
    body = card(f"{len(rows)} matches · <code>{E(q)}</code>", table(["Match", "Kind"], rows), cls="srch")
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
        return (f'E{r["expires_close"]}<small>{t.strftime("%a %H:%M" if r["expires_est_ts"] - time.time() < 6 * 86400 else "%b %-d")}</small>' if t else (f'E{r["expires_close"]}' if r.get("expires_close") is not None else UNK))
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
