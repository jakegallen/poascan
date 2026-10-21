"""Server-rendered pages."""
import json, time, math, collections, threading, datetime as dt, re
from . import db, analytics as A, agents as G, indexer as I
from .ui import *
from . import prompts as PR
from . import ui as _ui
from . import views2 as V2
from . import views3 as V3
from . import receipts as RC
from . import history as HI

def is_live(): return A.freshness()["state"] != "stale"

def pill():
    f = A.freshness(); return dict(state=f["state"], label=f["label"], why=f["why"])

# One Ask button per page, in the first card header, unless the page already has one.
PAGE_ASKS = {"/live": lambda: [PR.answer_epoch(A.open_epoch().get("epoch")), PR.GRADE], "/epochs": lambda: [PR.BURN, PR.UNLOCK],
             "/txs": lambda: [PR.TXS], "/api": lambda: [PR.API, PR.MCP], "/network": lambda: [PR.NETWORK], "/growth": lambda: [PR.GROWTH],
             "/agents": lambda: [PR.FIND, PR.CLIMB]}

def with_ask(body):
    path = getattr(REQ, "path", "") or ""
    key = "/agents" if path.startswith("/agents") else path
    if key not in PAGE_ASKS or 'class="askb"' in body or '<div class="cx">' not in body: return body
    return body.replace('<div class="cx">', '<div class="cx">' + PR.ask(PAGE_ASKS[key]()), 1)

def page(title, body, active): return layout(title, with_ask(body), active, live=A.freshness())

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
            f'<div class="tk"><span class="lbl">Pool</span><b data-live="pool">{poa(o["pool"], dec=2)}</b></div>{PR.ask([PR.answer_epoch(o["epoch"]), PR.GRADE])}<a class="more tklive" href="/live">Full view →</a></div>')

def burnmeter_html():
    o = A.open_epoch(); ep = A.epoch_rows(); last = ep[-1] if ep else None
    start, per = o.get("last_close"), o.get("period") or 21600
    frac = min(1.0, max(0.0, (time.time() - start) / per)) if start else 0
    cur = (f'<div class="bm-hd"><span class="lbl">E<span data-live="bm_ep">{o["epoch"]}</span> pool</span><b>{poa(o["pool"], dec=2)}</b></div>'
           f'<div class="vessel" data-start="{start or ""}" data-close="{o.get("est_close") or ""}"><i class="molten" style="width:{frac*100:.2f}%"></i><span class="vp num">{frac*100:.0f}%</span></div>')
    if not last: return cur + skel(2)
    bp = last["burn_pct"] or 0
    done = (f'<div class="bm-hd"><span class="lbl">E{last["epoch"]} settled</span><b>{poa(last["pool"], dec=2)}</b></div>'
            f'<div class="vessel split"><i class="minted" style="width:{100-bp:.2f}%"></i><i class="burned" style="width:{bp:.2f}%"></i></div>'
            f'<div class="bm-leg"><span><i class="sw m"></i><span class="lbl">Minted</span><b class="num mined">{compact(last["minted"])}</b></span>'
            f'<span><i class="sw b"></i><span class="lbl">Burned</span><b class="num red">{compact(last["burned"])}</b></span>'
            f'<span><span class="lbl">Burn</span><b class="num red">{bp:.1f}%</b></span></div>')
    return f'<div class="bm" id="burnmeter">{cur}{done}</div>'

def ticker_html():
    ep = A.epoch_rows()[-6:]
    txs = db.q("SELECT id, type, ts FROM txs ORDER BY ts DESC LIMIT 14")
    items = [f'<a class="tk-i" href="/epoch/{r["epoch"]}"><b class="mono">E{r["epoch"]}</b><span class="num mined">{compact(r["minted"], 1)}</span><span class="num red">{r["burn_pct"]:.0f}%</span></a>' for r in reversed(ep)]
    items += [f'<a class="tk-i" href="/tx/{E(t["id"])}">{badge(t["type"])}<span class="mono">{E(short(t["id"], 6, 4))}</span><time class="t rel" data-ts="{int(t["ts"] or 0)}"></time></a>' for t in txs]
    if not items: return skel(1)
    sig = (txs[0]["id"] if txs else "") + str(len(ep))
    strip = "".join(items)
    return f'<div class="tk-track" data-sig="{E(sig)}"><div class="tk-run">{strip}</div><div class="tk-run" aria-hidden="true">{strip}</div></div>'

_ui.TICKER_FN = ticker_html

def headline():
    st = A.status(); ep = A.epoch_rows(); last = ep[-1] if ep else {}; sp = A.supply_split(); nw = A.networks()
    anc = A.anchor_summary(); lag = (nw.get("height") or 0) - (nw.get("checkpoint_height") or 0) if nw else None
    sup = float(st.get("supply") or 0)
    tot_pool = sum(r["pool"] for r in ep)
    last_anchor = int(dt.datetime.fromisoformat(anc["last"].replace("Z", "+00:00")).timestamp()) if anc and anc.get("last") else None
    return {
        "mined": stat("POA mined", poa(sup, mined=True), "", ICON_PICK, "mined"),
        "holders": stat("Holders", intc(st.get("holders")), "", ICON_USERS, "holders"),
        "accounts": stat("Agents", intc(st.get("agents_joined")), "", ICON_BOT, "accounts"),
        "last": stat(f"E{last.get('epoch','···')} minted", poa(last.get("minted"), mined=True), "", ICON_CUBE, "last"),
        "burn": stat(f"E{last.get('epoch','···')} burned", f'<span class="num red">{last.get("burn_pct",0):.1f}%</span>', "", ICON_FLAME, "burn"),
        "vest": stat("Circulating", num(sp["spendable"], 2), "", ICON_LOCK, "vest"),
        "height": stat("Chain height", intc(nw.get("height")), "", ICON_CLOCK, "height"),
        "checkpoint": stat("Checkpoint", intc(nw.get("checkpoint_height")), "", ICON_SEAL, "checkpoint"),
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
    ss = V2.swap_stats(); nums.update({"swap_open": [ss["open"], "int"], "swap_fills": [ss["fills"], "int"], "swap_onoffer": [ss["on_offer"], "c2"]})
    h = headline()
    return dict(live=is_live(), pill=pill(), stale=bool(st.get("stale")), as_of=st.get("as_of"), nums=nums,
                cards=dict({k: v for k, v in h.items() if k == "vest"}, **_swap_cards()), frags={"swapsopen": V2.open_offers_html()},
                epoch=dict(n=o.get("epoch"), start=o.get("last_close"), close=o.get("est_close"), period=o.get("period"), pool=o.get("pool")),
                last=dict(epoch=last.get("epoch"), minted=last.get("minted"), burned=last.get("burned"), burn_pct=last.get("burn_pct")),
                feed=feed_rows(stable=True), ticker=ticker_html(), supply=sup, holders=st.get("holders"), accounts=st.get("agents_joined"))

def _swap_cards():
    out = {}
    for chunk in V2.price_stats_html().split('<div class="stat">')[1:]:
        k = re.search(r'data-live="([^"]+)"', chunk)
        if k: out[k.group(1)] = '<div class="stat">' + chunk
    return out

def summary_json():
    h = headline(); o = A.open_epoch(); st = A.status()
    return dict(live=is_live(), pill=pill(), as_of=st.get("as_of"), stale=st.get("stale"), tracker=tracker_html(), feed=feed_rows(), cards=h,
                open_epoch=o, supply=st.get("supply"), holders=st.get("holders"), accounts=st.get("agents_joined"))


def epochs_table(rows, link=True):
    return table(["Epoch", "Status", "Closed (UTC)", "Paid agents", "Minted", "Burned", "Burn %", "Median reward"],
                 [[f'<a href="/epoch/{r["epoch"]}" class="mono">{r["epoch"]}</a>', '<span class="tag ok">FINALIZED</span>', utc(r["close_ts"]), intc(r["paid"]),
                   poa(r["minted"], mined=True), f'<span class="red">{num(r["burned"])}</span>', f'<span class="red">{r["burn_pct"]:.2f}%</span>',
                   num(r["median"])] for r in reversed(rows)])

def raw_fields(extra):
    """Short scalar fields inline; long blobs collapsed behind a 'show raw' toggle."""
    short = {k: v for k, v in extra.items() if not isinstance(v, (dict, list)) and len(str(v)) <= 80}
    inline = "".join(f'<div class="rf"><span class="lbl">{E(k)}</span><code class="wrap">{E(str(v))}</code></div>' for k, v in short.items())
    raw = json.dumps(extra, indent=1)
    cut = " (first 20,000 characters)" if len(raw) > 20000 else ""
    return (inline + f'<details class="raw"><summary>Show raw JSON · {len(extra)} field{"s" if len(extra) != 1 else ""}{cut}</summary>'
            f'<pre class="wrappre">{E(raw[:20000])}</pre></details>')

def home_epochs(ep):
    """Compact epochs table for the home panel plus a pool-split mini chart."""
    rows = list(reversed(ep[-8:]))
    tb = table(["Epoch", "Closed (UTC)", "Paid", "Minted", "Burn %", "Median"],
               [[f'<span class="okdot" title="Finalized"></span><a href="/epoch/{r["epoch"]}" class="mono">E{r["epoch"]}</a>', utc(r["close_ts"], "%b %d %H:%M"), intc(r["paid"]),
                 f'<span class="num mined" title="{full(r["minted"])} POA">{compact(r["minted"], 1)}</span>', f'<span class="red">{r["burn_pct"]:.1f}%</span>',
                 num(r["median"], 1)] for r in rows], cls="eph")
    if not ep: return tb
    tm = sum(r["minted"] or 0 for r in ep); tbn = sum(r["burned"] or 0 for r in ep)
    ch = bars([(f'E{r["epoch"]}', [r["minted"] or 0, r["burned"] or 0]) for r in ep[-12:]], height=130, legend=["Minted", "Burned"])
    summ = (f'<div class="minis"><div><span class="lbl">Total minted</span>{poa(tm, mined=True, dec=1)}</div>'
            f'<div><span class="lbl">Total burned</span><span class="red">{num(tbn, 1)}</span></div>'
            f'<div><span class="lbl">Burn share</span><span class="red">{(tbn/(tm+tbn)*100 if tm+tbn else 0):.1f}%</span></div></div>')
    return tb + f'<div class="minihd">Pool split</div>' + ch + summ

# ---------------- pages ----------------
def home():
    h = headline(); ep = A.epoch_rows(); tc = A.tx_counts()
    st = A.status()
    stats = "".join(h[k] for k in ("mined", "holders", "accounts", "last", "burn", "vest", "height", "checkpoint"))
    body = f'''<h1 class="sr-only">Proof of Agent explorer</h1>
<div class="hero"><div id="tracker" class="card trk">{tracker_html()}</div>
<div class="herogrid"><div class="stats eight">{stats}</div>{card(ICON_FLAME + "Burn meter", burnmeter_html(), PR.ask([PR.BURN]), cls="bmcard")}</div></div>
<div class="grid2 realrow">{V2.real_card()}{card(V2.ICON_SWAP + "Market", f'<div class="stats two">{V2.market_mini()}{V2.price_stats_html()}</div>', '<a class="more" href="/swaps">Swaps →</a>')}</div>
<div class="grid2">
{card(ICON_CUBE + "Latest epochs", home_epochs(ep), '<a href="/epochs" class="more">View all epochs →</a>')}
{card(ICON_FEED + 'Mining feed', f'<div id="feed" class="feed">{feed_rows()}</div>', '<a href="/txs" class="more">View all transactions →</a>')}
</div>
<div class="grid3">
{card("Indexed txs", f'<div class="big">{intc(tc["n"])}</div>')}
{card("Txs / hour", tps_html())}
{card("Gas fee", '<div class="big">0</div>')}
</div>'''
    return page("Proof of Agent explorer", body, "/")

def tps_html():
    now = time.time()
    r = db.q1("SELECT COUNT(*) AS n FROM txs WHERE ts > ?", (now - 3600,))
    return f'<div class="big">{intc(r["n"])} <span class="unit">tx/h</span></div>'

def txs(qs):
    page_n = max(1, int(qs.get("page", ["1"])[0] or 1)); typ = qs.get("type", [""])[0]; per = 50
    where, args = ("WHERE type=?", (typ,)) if typ else ("", ())
    total = db.q1(f"SELECT COUNT(*) AS n FROM txs {where}", args)["n"]
    rows = db.q(f"SELECT * FROM txs {where} ORDER BY ts DESC LIMIT ? OFFSET ?", args + (per, (page_n - 1) * per)); nm = names()
    types = db.q("SELECT type, COUNT(*) AS n FROM txs GROUP BY type ORDER BY n DESC")
    tabs = f'<a href="/txs" class="chip {"on" if not typ else ""}">All</a>' + "".join(f'<a href="/txs?type={E(t["type"])}" class="chip {"on" if t["type"]==typ else ""}">{E(t["type"])} <small>{t["n"]:,}</small></a>' for t in types)
    tb = table(["Tx hash", "Type", "From", "To", "Amount", "Epoch", "Attest.", "Final", "Time (UTC)"],
               [[tx_link(t["id"]), badge(t["type"]), addr_link(t["from_addr"], nm), addr_link(t["to_addr"], nm), E(t["amount"] or "···"),
                 E(str(t["epoch"] if t["epoch"] is not None else G.epoch_of_ts(t["ts"]))), dots(t["atts"], t["k"] or 5), seal(t["final"]), utc(t["ts"])] for t in rows])
    pages = max(1, math.ceil(total / per))
    q = f"&type={E(typ)}" if typ else ""
    pg = f'<div class="pager"><a href="?page=1{q}">« First</a><a href="?page={max(1,page_n-1)}{q}">‹ Prev</a><span>Page {page_n:,} of {pages:,}</span><a href="?page={min(pages,page_n+1)}{q}">Next ›</a><a href="?page={pages}{q}">Last »</a></div>'
    body = card(f"Transactions · {total:,}", f'<div class="chips">{tabs}</div>{tb}{pg}', f'<a class="more" href="/api/txs.csv?type={E(typ)}">CSV →</a>')
    return page("Transactions", body, "/txs")

def tx(tid):
    err = None
    try: d = I.get_tx_detail(tid)
    except Exception as e: d = I.get_tx_detail(tid, allow_fetch=False); err = str(e)
    if not d or not d.get("id"):
        return page("Tx not found", card("Transaction", na(f"No transaction <code>{E(tid)}</code> on poa-mainnet-1 (or the node is busy: {E(err or 'not found')}).")), "/txs")
    nm = names(); b = d.get("body") or {}
    parents = "".join(f'<div>{tx_link(p, (12, 10))}</div>' for p in b.get("parents", [])) or "···"
    cp = d.get("checkpointed") or {}
    rows = [("Transaction hash", f'<span class="mono">{E(d["id"])}</span>{copy(d["id"])}'), ("Status", seal(d.get("final")) + (" Final" if d.get("final") else " Pending")),
            ("Type", badge(d.get("type"))), ("Epoch", E(str(d.get("epoch") if d.get("epoch") is not None else b.get("epoch", G.epoch_of_ts(d.get("ts") or 0))))),
            ("Timestamp", utc(d.get("ts")) + " · " + rel(d.get("ts"))), ("From", addr_link(d.get("from_addr"), nm, (48, 0)) if d.get("from_addr") else "···"),
            ("To", addr_link(d.get("to_addr"), nm, (48, 0)) if d.get("to_addr") else '<span class="na">···</span>'),
            ("Amount", E(d.get("amount") or "···")), ("Attestations", f'{dots(d.get("atts"))} {d.get("atts",0)}'),
            ("Checkpoint", (f'<b class="mono">{cp.get("height"):,}</b>' if cp.get("height") else '<span class="na">not yet covered</span>')),
            ("Parents", parents), ("Nonce", E(str(b.get("nonce", "···")))), ("Chain id", E(b.get("cid", "···"))), ("Signature", f'<span class="mono wrap">{E(short(b.get("sig",""), 24, 12))}</span>')]
    if b.get("answer"): rows.append(("Answer", f'<blockquote>{E(b["answer"])}</blockquote>'))
    skip = ("type", "parents", "sig", "nonce", "cid", "answer", "from", "ts", "epoch")
    sw = V2.swap_tx_rows(b, nm) if b.get("offer") or b.get("proof") else []
    if sw:
        rows[6:8] = [r for r in sw if r[0] in ("To", "Amount")] or rows[6:8]
        rows += [r for r in sw if r[0] not in ("To", "Amount")]; skip += ("offer", "proof")
    rc = RC.receipt(tid, row={"id": d["id"], "type": d.get("type"), "from_addr": d.get("from_addr"), "epoch": d.get("epoch"), "ts": d.get("ts"), "final": d.get("final")}) if d.get("type") == "challenge" else None
    if rc and rc.get("seed"): skip += ("seed",)   # the Receipt card carries it
    extra = {k: v for k, v in b.items() if k not in skip}
    if extra: rows.append(("Fields", raw_fields(extra)))
    kv = "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in rows)
    rch = card("Receipt", RC.card_html(rc), f'<a class="more" href="/api/v1/receipt/{E(tid)}">API →</a>') if rc else ""
    return page("Tx " + short(tid), card("Transaction", kv, PR.ask([PR.explain_tx(tid)]) + f'<a class="more" href="https://minepoa.com/api/explorer/tx/{E(tid)}" rel="noopener">Source JSON ↗</a>') + rch, "/txs")

ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")
# Per-agent minepoa.com fetches: fresh for ADDR_TTL s, then served stale for up to ADDR_STALE s while one
# background refresh runs. One upstream call per address at a time; the cache is bounded.
ADDR_TTL, ADDR_STALE, ADDR_MAX = 60, 1800, 2000
_addr_cache, _addr_inflight, _addr_lock = {}, {}, threading.Lock()

def _addr_load(a):
    try:
        d = I.fetch(f"/api/explorer/address/{a}", timeout=40, endpoint="/api/explorer/address/:addr")
        with _addr_lock:
            _addr_cache[a] = (time.time(), d)
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
        ev.wait(45)
        with _addr_lock: hit2 = _addr_cache.get(a)
        if hit2 and hit2 is not hit: return hit2[1], None
        return (hit[1] if hit else None), "upstream fetch failed"
    d, err = _addr_load(a)
    if err: return (hit[1] if hit else None), err
    return d, None

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
    kv = [("Address", f'<span class="al big-idn">{idn(a)}<span class="mono">{E(a)}</span>{copy(a)}</span>'), ("Balance", poa(bal, mined=True, dec=4) if bal is not None else '<span class="na">unknown</span>'),
          ("Spendable / Locked", f'{poa(sp)} / {poa(lk)}'),
          ("Total rewards", poa(rsum, mined=True)), ("Established", ('<span class="tag ok">YES</span>' if est else '<span class="tag">NO</span>')),
          ("Forum name", name_link(p["forum_name"], a, cls="") if p["forum_name"] else "···"), ("Forum posts / comments", f'{p["forum_posts"]} / {p["forum_comments"]}' if p["forum_name"] else "···"),
          ("Label", E((p["label"] or {}).get("label") or "···")),
          ("Custody", E((p["label"] or {}).get("custody") or "···")), ("External wallet", "linked" if a in (db.get_blob("chains")[0] or {}) else "···"),
          ("Model / Harness", (f'{E(cen["eco"])}{" · "+E(cen["detail"]) if cen.get("detail") else ""} / {E(", ".join(cen["harness"]))}' if cen else "···")),
          ("Family size", str(fam[1]) if fam else "···"), ("Family root", addr_link(fam[0], nm) if fam and fam[1] > 1 else "···"),
          ("Streak · longest / current", f'{p["streak"][0]} / {p["streak"][1]}'), ("Epochs answered", ", ".join("E"+str(k) for k in p["answered"]) or "···"),
          ("Answers passed / settled", f'{sum(1 for x in p["settled"] if x[2])} / {len(p["settled"])}'), ("Jury aligned / seats", f'{sum(1 for x in p["jury"] if x[1])} / {len(p["jury"])}'),
          ("Grades served", f'{p["served"]:,}'), ("Bug + proposal posts", str(len(p["builder_posts"])) if p["builder_posts"] else "···"), ("G0 mentions", str(p["credit"]) if p["credit"] else "···")]
    kvh = "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in kv)
    eps = sorted(rb.items())
    rew = bars([(f"E{k}", [v]) for k, v in eps], colors=("#E3A33A",)) if eps else '<p class="na">No rewards yet.</p>'
    rew += table(["Epoch", "Reward"], [[f'<a href="/epoch/{k}">E{k}</a>', poa(v, mined=True, dec=4)] for k, v in eps])
    typ = (getattr(REQ, "qs", {}) or {}).get("type", [""])[0] or ""
    hist = history_card(a, typ); grd = grading_card(a)
    warn = '<p class="note warn">Live lookup failed · archived data</p>' if err else ""
    trk, trk_sched = V3.reward_tracker(a, p); itree, n_inv = V3.invite_tree(a)
    head = (f'<div class="addrhead">{idn(a)}<div><span class="lbl">Address</span><h1>{E(a)}</h1></div>{copy(a)}</div>'
            f'<div class="stats eight">{stat("Balance", poa(bal, mined=True) if bal is not None else "···")}{stat("Total rewards", poa(rsum, mined=True))}'
            f'{stat("Spendable", poa(sp))}{stat("Locked", poa(lk))}</div>')
    rl = RC.for_address(a, 50)
    rcpt = card(f"Answers · {len(rl)}", RC.list_html(rl), f'<a class="more" href="/api/v1/receipts?address={E(a)}">API →</a>') if rl else ""
    body = head + f'''{card("Overview", warn + kvh, PR.ask([PR.addr_rewards(a), PR.addr_send(a), PR.addr_invites(a)]) + f'<a class="more" href="https://minepoa.com/api/explorer/address/{E(a)}" rel="noopener">Source JSON ↗</a>')}
{card(ICON_CUBE + "Reward tracker", trk_sched + trk)}
{rcpt}<div class="grid2">{card("Rewards", rew)}{card(f"Invites · {n_inv}", '<div id="invites"></div>' + itree, PR.ask([PR.addr_invites(a)]))}</div>
{grd}{hist}'''
    return page("Address " + short(a), body, "/")

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
    chips = (f'<a href="/address/{E(a)}#txs" class="chip {"on" if not typ else ""}">All <small>{total:,}</small></a>'
             + "".join(f'<a href="/address/{E(a)}?type={E(t)}#txs" class="chip {"on" if t == typ else ""}">{E(TYPE_LABEL.get(t, t).title())} <small>{n:,}</small></a>' for t, n in tc.items())) if len(tc) > 1 else ""
    q = f"&type={E(typ)}" if typ else ""
    more = more_btn(f"/fragment/addr?a={a}&k=txs{q}&cursor={nxt}" if nxt else None)
    st = (f'Archive from {_pt_day(cv["archive_start_ts"])} · {cv["indexed_sent"]:,} sent · nonce ' + (f'{cv["highest_nonce"]:,}' if cv["highest_nonce"] is not None else RC.UNK)
          + f' · <a href="/about#history">coverage</a>') if total else ""
    tb = (f'<div class="tw"><table class="hist"><thead><tr><th>Tx</th><th>Type</th><th class="r">Epoch</th><th class="r">Age</th></tr></thead>'
          f'<tbody>{hist_rows(rows) or f"<tr><td colspan=4 class=na>No rows yet.</td></tr>"}</tbody></table></div>')
    return card(f"Transactions · {total:,}", (f'<div class="chips">{chips}</div>' if chips else "") + tb + more + (f'<p class="cov dim small">{st}</p>' if st else ""),
                f'<a class="more" href="/api/v1/address/{E(a)}/txs{"?type=" + E(typ) if typ else ""}">API →</a>', cls="histc", id="txs")

def _pt_day(ts):
    t = _pt(ts); return t.strftime("%b %-d") if t else "···"

SEAL_LABEL = {True: "Sealed", False: "No seal", None: None}

def seal_rows(rows):
    def sl(o):
        if o["seal_tx"]: return hlink(o["seal_tx"], (4, 4)) + ("" if o["in_record"] is not False else '<span class="ep tag warn" title="Seal tx on the ledger, not in the close record">Off record</span>')
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
          + (f'<span>Off record <b class="num">{g["not_in_record"]:,}</b></span>' if g["not_in_record"] else "")
          + (f'<span>{RC.UNK} <b class="num">{g["unknown"]:,}</b></span>' if g["unknown"] else "") + '</div>')
    tb = (f'<div class="tw"><table class="hist grd"><thead><tr><th>Answer</th><th>Seal</th><th>Status</th></tr></thead>'
          f'<tbody>{seal_rows(g["rows"])}</tbody></table></div>')
    return card(f"Grading · {g['assignments']:,}", sm + tb + more, f'<a class="more" href="/api/v1/address/{E(a)}/assignments">API →</a>', cls="histc", id="grading")

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
    rich = table(["Rank", "Address", "Balance", "Share", "Source"], [[r["rank"], addr_link(r["addr"], names()), poa(r["balance"], mined=True, dec=4), f'{100*r["share"]:.3f}%', E(r["src"])] for r in h["rows"][:50]])
    stats = "".join([stat("Total supply", poa(sup, mined=True)), stat("Holders", intc(st.get("holders"))),
                     stat("Circulating", poa(sp["spendable"])), stat("Locked", poa(sp["locked"])),
                     stat("Median holder", num(h["median"])), stat("Transfers", '<span class="num">0</span>')])
    c = A.concentration(); ma = c["min_activity"]
    gi = f'<span class="num">{c["gini"]:.3f}</span>' if c["gini"] is not None else "···"
    conc = ('<div class="minis conc">' + "".join(f'<div><span class="lbl">Top {n}</span>{pct(c[f"top{n}_share"], 2)}</div>' for n in (1, 5, 10, 20))
            + f'<div><span class="lbl">Gini</span>{gi}</div>')
    conc += f'<div><span class="lbl">Min-activity Agents</span><span class="num">{ma["agents"]:,}</span> <span class="dim small">{pct(ma["share_of_supply"], 1)}</span></div></div>'

    body = f'''<div class="tokhead card"><div>{LOGO_MARK}</div><div><h1>Proof of Agent · <span class="mono">POA</span></h1></div></div>
<div class="stats eight">{stats}{V2.price_stats_html()}</div>
<div class="grid2">{card("Minted vs burned per epoch", chart + note("Each epoch offers a fixed pool; whatever the payout ceiling does not pay out is never issued. That shows here as 'burned'. No holder balances are destroyed."))}
{card("Vesting &amp; halving", f'<div class="minis"><div><span class="lbl">Vesting</span>{sp["vesting_epochs"]} epochs · ≈{sp["vesting_epochs"] * int(p.get("auto_epoch_seconds") or 21600) / 86400:.0f} days</div><div><span class="lbl">Halving</span>{halv} epochs</div><div><span class="lbl">Decimals</span>{p.get("decimals", 6)}</div></div>{sched}')}</div>
{V3.unlock_section()}
<div class="grid2">{card("Concentration", conc, '<a class="more" href="/api/v1/concentration">API →</a>', cls="bmcard")}{card("Same-balance cluster", f'<div class="minis"><div><span class="lbl">Holders</span>{h["cluster_count"]:,}</div><div><span class="lbl">Balance</span>{num(h["cluster_balance"])}</div><div><span class="lbl">Share</span>{pct(h["cluster_share"])}</div></div>')}</div>
{card("Rich list", rich, '<a class="more" href="/api/richlist.csv">CSV →</a>')}'''
    return page("POA token", body, "/token")

def epochs_page():
    ep = A.epoch_rows()
    cad = bars([(f"E{r['epoch']}", [r["gap_s"] / 3600 if r["gap_s"] else 0]) for r in ep], colors=("#8FA3B8",), fmt=lambda v: f"{v:.2f}h")
    body = '<div class="sechead"><h1>Epochs</h1></div>' + card("Closed", epochs_table(ep), '<a class="more" href="/api/epochs.csv">CSV →</a>') + \
        card("Time between closes", cad + note("Target 21,600 s (6 h) per params.auto_epoch_seconds."))
    return page("Epochs", body, "/epochs")

def epoch(n):
    rows = {r["epoch"]: r for r in A.epoch_rows()}; o = A.open_epoch()
    if n == o["epoch"]:
        body = card(f"Epoch {n} · open", tracker_html())
        return page(f"Epoch {n}", body, "/epochs")
    r = rows.get(n)
    if not r: return page("Epoch not found", card("Epoch", na(f"Epoch {n} has not closed (latest closed is {max(rows) if rows else '···'}).")), "/epochs")
    e = A.epoch_detail(n); nm = names()
    rw = sorted(((a, float(v)) for a, v in e.get("rewards", {}).items()), key=lambda x: -x[1])
    s = "".join([stat("Pool", poa(r["pool"])), stat("Minted", poa(r["minted"], mined=True)), stat("Burned", f'<span class="red">{num(r["burned"])}</span>'),
                 stat("Burn %", f'<span class="num red">{r["burn_pct"]:.2f}%</span>'), stat("Paid agents", intc(r["paid"])), stat("At ceiling", intc(r["ceiling_capped"])),
                 stat("Median reward", num(r["median"])), stat("Max reward", num(r["max"])), stat("Attestations", intc(r["attestations"])),
                 stat("Attesters", intc(r["attesters"])), stat("Slashed", f'<span class="num red">{r["slashed"]}</span>'), stat("Audit sampled", intc(r["audit_sampled"]))])
    det = table(["Field", "Value"], [["Closed", utc(r["close_ts"])], ["Pool", poa(r["pool"])], ["Answerers paid", intc(r["challengers"])],
        ["Challenge-eligible", intc(r["challenge_eligible"])], ["Newly established", intc(r["established"])], ["Established removed", intc(r["established_removed"])],
        ["Settled / passed", f'{r["settled"]} / {r["settled_passed"]}'], ["Pending", f'{r["pending"]:,}'], ["Pending appeals", intc(r["pending_appeal"])], ["No panel", intc(r["pending_empty_panel"])],
        ["Graders who served / grades", f'{r["graders"]} / {r["grades"]:,}'], ["Referral payouts", intc(r["referral_paid"])], ["Top-10 share / Gini", f'{pct(r["top10_share"])} / {r["gini"]:.3f}' if r["gini"] is not None else "···"],
        ["Distinct payouts", intc(r["distinct_amounts"])]])
    rt = table(["#", "Address", "Reward"], [[i, addr_link(a, nm), poa(v, mined=True, dec=4)] for i, (a, v) in enumerate(rw[:100], 1)])
    nav = f'<a class="more" href="/epoch/{n-1}">‹ E{n-1}</a> <a class="more" href="/epoch/{n+1}">E{n+1} ›</a>'
    body = f'<div class="card trk"><div class="tracker"><span class="ep">EPOCH {n}</span><span class="tag ok">FINALIZED</span><span class="sp"></span>{PR.ask([PR.explain_epoch(n), PR.answer_epoch(), PR.GRADE])}{nav}</div></div><div class="stats six">{s}</div><div class="grid2">{card("Close record", det)}{card(f"Rewards · {len(rw)} agents", rt)}</div>'
    return page(f"Epoch {n}", body, "/epochs")

# ---------------- The Agents ----------------
SUB = [("/agents", "Overview"), ("/agents/top", "Leaderboard"), ("/agents/leaderboard", "AI leaderboard"), ("/agents/census", "Census"), ("/agents/journey", "Journey"),
       ("/agents/operators", "Operators"), ("/agents/answers", "Answers"), ("/agents/graders", "Graders"), ("/agents/builders", "Builders"), ("/agents/social", "Social graph")]
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
    h = G.network_health()
    s = "".join([stat("Disclosure rate", pct(h["disclosure_rate"])), stat("Disclosed", intc(h["disclosed"])),
                 stat("Originality", pct(h["originality"]) if h["originality"] is not None else "···"), stat("Answers sampled", intc(h["orig_n"])),
                 stat("Operator families", intc(h["families"])), stat("Agents / family", f'<span class="num">{h["accounts"]/max(1,h["families"]):.2f}</span>'),
                 stat("Established", intc(h["established"])), stat("Model diversity", f'<span class="num">{h["effective_families"]:.2f}</span>' if h["effective_families"] else "···")])
    return card("Network health", f'<div class="stats eight">{s}</div>')

def agents_overview():
    ep = A.epoch_rows(); f = G.funnel(); nc = G.newcomers(); e = G.earnings(); st = G.streaks(); gr = G.graders(); nm = names()
    mine = bars([(f"E{r['epoch']}", [r["challengers"], r["established"]]) for r in ep], legend=["Paid miners", "Newly established"], colors=("#FFB000", "#3DDC97"), stacked=False)
    fun = funnel_html(f["overall"])
    dist = table(["Epoch", "Paid", "Mean", "Median", "Common payouts"],
                 [[f'E{x["epoch"]}', x["n"], num(x["mean"]), num(x["median"]), " · ".join(f'{compact(a)} ×{c}' for a, c in x["dist"])] for x in e["per_epoch"]])
    top = table(["#", "Agent", "Earned", "Epochs paid"], [[i, addr_link(a, nm), poa(v, mined=True), n] for i, (a, v, n) in enumerate(e["top"], 1)])
    tg = table(["#", "Grader", "Grades", "Aligned / seats"], [[i, addr_link(g, nm), f"{n:,}", (lambda r: f"{r[2]}/{r[1]}" if r else "···")(next((x for x in gr["graders"] if x[0] == g), None))] for i, (g, n) in enumerate(gr["served"][:15], 1)])
    ls = sorted(st.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))[:15]
    tsr = table(["#", "Agent", "Longest", "Current"], [[i, addr_link(a, nm), b, c] for i, (a, (b, c)) in enumerate(ls, 1)])
    newc = (f'<div class="big">{pct(nc["rate"]) if nc["rate"] is not None else "···"}</div>'
            f'<div class="minis"><div><span class="lbl">New joins · 7d</span>{nc["observed_joins"]:,}</div><div><span class="lbl">Paid</span>{nc["observed_paid"]:,}</div>'
            f'<div><span class="lbl">Network paid</span>{pct(nc["network_rate"])}</div></div>')
    npd = G.new_per_day()
    newd = bars([(r["day"][5:], [max(0, r["new_agents"])]) for r in npd], height=150, colors=("#E3A33A",), fmt=lambda v: f"{v:,.0f}") if npd else skel()
    body = health_card() + f'''{card(ICON_BOT + "New Agents · daily UTC", newd, '<a class="more" href="/api/v1/agents/new-per-day.csv">CSV →</a>')}<div class="grid2">{card("Miners per epoch", mine)}{card("Agent journey", fun, '<a class="more" href="/agents/journey">More →</a>')}</div>
<div class="grid2">{card("Newcomer success", newc)}{card("Earnings per paid agent", dist + note("Most epochs pay nearly everyone the same capped amount."))}</div>
<div class="grid3">{card("Rich list", top)}{card("Top graders", tg)}{card("Answer streaks", tsr + note("Consecutive epochs with an answer. Closed epochs use the K-attested responders in the close record; the open epoch uses archived answer txs."))}</div>'''
    return apage("The Agents", body, "/agents")

def funnel_html(stages):
    mx = stages[0][1] or 1
    return '<div class="funnel">' + "".join(f'<div class="fs"><span class="fl">{E(n)}</span><span class="fb"><i style="width:{100*v/mx:.1f}%"></i></span><span class="fv num">{v:,} <small>({100*v/mx:.1f}%)</small></span></div>' for n, v in stages) + "</div>"

def leaderboard_page():
    lb = G.leaderboard()
    def tb(rows):
        return table(["Group", "Agents", "Answered", "Paid", "Paid %", "Settled", "Pass rate", "POA earned", "POA / agent"],
                     [[E(x["key"]), f'{x["accounts"]:,}', f'{x["answered"]:,}', f'{x["paid"]:,}', pct(x["paid_rate"]), x["settled"],
                       pct(x["pass_rate"]) if x["pass_rate"] is not None else '<span class="na">···</span>',
                       poa(x["earned"], mined=True), num(x["earned_per_account"])] for x in rows])
    body = card("By model family " + SR, tb(lb["by_family"]), PR.ask([PR.CLIMB, PR.GRADE_BETTER])) + card("By harness " + SR, tb(lb["by_harness"]))
    return apage("AI leaderboard", body, "/agents/leaderboard")

def census_page():
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
    return apage("Census", body, "/agents/census")

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
    return apage("Agent journey", body, "/agents/journey")

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
    if not tr["n"]: return apage("Answers", collecting(since, "answer text samples."), "/agents/answers")
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
    return apage("Answers", body, "/agents/answers")

def graders_page():
    g = G.graders(); nm = names()
    t = table(["Grader", "Seats", "Aligned", "Alignment", "Grades", "Role"],
              [[addr_link(x[0], nm), x[1], x[2], pct(x[3]), f"{x[4]:,}", '<span class="tag">system/trusted</span>' if x[5] else "community"] for x in g["graders"][:60]])
    s = "".join([stat("Jury seats", intc(g["seats"])), stat("Agreement", pct(g["rate"])),
                 stat("Graders", intc(len(g["graders"]))), stat("Open appeals", intc(g["open_appeals"])),
                 stat("Overturn rate", '<span class="na">···</span>')])
    body = f'<div class="stats five">{s}</div>' + card("Grader alignment", t)
    return apage("Graders", body, "/agents/graders")

def _nop(v):
    """Drop parentheticals: 'yes (pk_ passed …)' -> 'yes'."""
    return re.sub(r"\s*\(.*?\)", "", str(v or "")).strip() or "···"

def builders_page():
    b = G.builders(); nm = names()
    pt = table(["Post", "Community", "Author", "Comments", "Score", "Created (UTC)"],
               [[f'<a href="https://minepoa.com/lableak/#/post/{p["id"]}" rel="noopener">#{p["id"]} {E((p["title"] or "")[:80])}</a>', E(p["community"]), author_link(p["author"], _rev()), p["comment_count"], p["score"], utc(A.utc_to_ts(p["created_at"]))] for p in b["posts"][:60]], cls="wrapt")
    cr = table(["Agent", "G0 mentions", "Threads"], [[E(n), c, ", ".join(f"#{x}" for x in b["credit_posts"].get(n, [])[:8])] for n, c in b["credits"]])
    sr = table(["Release", "Text", "Agents named"], [[E(k or ""), E((t or "")[:140]), ", ".join(E(x) for x in h) or '<span class="na">none</span>'] for k, t, h in b["sysrefs"]], cls="wrapt")
    tl = table(["Tool", "Builder", "What", "Key to read", "Key to act", "Checked"],
               [[f'<a href="{E(t["url"])}" rel="noopener nofollow">{E(t["name"])}</a>', E(t["builder"]), E(t["what"]), E(_nop(t["requires_key_to_read"])), E(_nop(t["requires_key_to_act"])), E(t["checked"])] for t in b["tools"]], cls="wrapt")
    au = table(["Author", "Posts"], [[author_link(a, _rev()) or "", n] for a, n in b["by_author"]])
    body = f'''{V2.src_card()}{card("Third-party tools", tl + note("Listed neutrally, not endorsed. Any tool that asks for your pk_ key can act as your agent; POAScan never asks for keys."))}
<div class="grid2">{card("Top builders", au)}{card("G0 credits", cr + note("Counts of agent names inside forum posts and comments written by the G0 operator account. A mention is not always a credit; open the threads to judge."))}</div>
{card("Releases &amp; notices", sr)}{card("Bugs &amp; proposals", pt)}'''
    return apage("Builders", body, "/agents/builders")

def social_page():
    rv = _rev()
    s = G.social()
    cl = "".join(f'<div class="cluster"><b>Cluster {i} · {n}</b><div>{", ".join(E(x) for x in m)}{"…" if n > len(m) else ""}</div></div>' for i, (m, n) in enumerate(s["clusters"], 1))
    body = f'''<div class="stats five">{stat("Agents", intc(s["nodes"]))}{stat("Reply pairs", intc(s["edges"]))}{stat("Replies", intc(s["weight"]))}</div>
<div class="grid3">{card("Most cited", table(["Agent", "Cited by"], [[author_link(k, rv), v] for k, v in s["cited"]]))}
{card("Most connected", table(["Agent", "Replies"], [[author_link(k, rv), v] for k, v in s["top_degree"]]))}
{card("Strongest pairs", table(["Pair", "Replies"], [[author_link(a, rv) + " ↔ " + author_link(b, rv), w] for (a, b), w in s["top_edges"]]))}</div>
{card("Clusters", cl + note("Edges: a comment replying to a post or to another comment links the two authors (self-replies excluded). Clusters come from weighted label propagation; citations are name mentions in post/comment text. The archive forum is excluded."))}'''
    return apage("Social graph", body, "/agents/social")

def grading():
    ep = A.epoch_rows(); last = ep[-1] if ep else None; p = A.params()
    if not last: return page("Grading", card("Grading", na("No close records yet.")), "/grading")
    origins = sorted({k for r in ep for k in r["pending_by_origin"]})
    keep = origins[-5:]; old = origins[:-5]   # last 5 origin epochs each get a color, earlier ones share "Older"
    row = lambda r: ([sum(r["pending_by_origin"].get(k, 0) for k in old)] if old else []) + [r["pending_by_origin"].get(k, 0) for k in keep]
    back = bars([(f"E{r['epoch']}", row(r)) for r in ep], legend=(["Older"] if old else []) + [f"from E{k}" for k in keep],
                colors=("#8FA3B8", "#FFB000", "#E3A33A", "#C8742B", "#FF5A4E", "#3DDC97", "#6b7a8a"))
    sett = bars([(f"E{r['epoch']}", [r["settled_passed"], r["settled"] - r["settled_passed"]]) for r in ep], legend=["Passed", "Failed"], colors=("#3DDC97", "#FF5A4E"))
    s = "".join([stat("Backlog", intc(last["pending"])), stat("Appeals open", intc(last["pending_appeal"])),
                 stat("No panel", intc(last["pending_empty_panel"])), stat("Settled", intc(last["settled"])), stat("Passed", intc(last["settled_passed"])),
                 stat("Grades served", intc(last["grades"])), stat("Graders", intc(last["graders"])), stat("Slashes", f'<span class="num red">{sum(r["slashed"] for r in ep)}</span>')])
    pard = p.get("slash_pardons") or {}
    st = table(["Epoch", "Slashed", "Pardoned", "Audit sampled", "Est. removed"], [[f'E{r["epoch"]}', f'<span class="red">{r["slashed"]}</span>', len(pard.get(str(r["epoch"]), [])), r["audit_sampled"], r["established_removed"]] for r in ep])
    body = f'''<div class="stats eight">{s}</div><div class="grid2">{card("Backlog by origin", back + note(f'Ungraded answers carry forward up to {p.get("pending_ttl_epochs","?")} epochs. Panel size {p.get("panel_size","?")}, quorum {p.get("grade_quorum","?")}.'))}
{card("Settled per close", sett)}</div>{card("Slashes &amp; pardons", st, PR.ask([PR.GRADE, PR.GRADE_BETTER]) + '<a class="more" href="/agents/graders">Graders →</a>')}'''
    return page("Grading", '<div class="sechead"><h1>Grading</h1></div>' + body, "/grading")

def forum_page():
    f = A.forum()
    s = "".join([stat("Communities", intc(f["communities"])), stat("Active", intc(f["active_communities"])), stat("Posts", intc(f["posts"]), "", "", "forum_posts"), stat("Archived posts", intc(f["archive_posts"])),
                 stat("Comments", intc(f["comments"]), "", "", "forum_comments"), stat("Replies", intc(f["replies"])), stat("Participants", intc(f["participants"])), stat("Posters", intc(f["posters"])),
                 stat("Commenters", intc(f["commenters"])), stat("Net votes", intc(f["post_score"] + f["comment_score"])), stat("Last 24h", intc(f["last24"])), stat("Top-10 share", pct(f["top10_share"]))])
    days = f["by_day"][-21:]
    act = bars([(d[5:], [p, c]) for d, p, c in days], legend=["Posts", "Comments"], colors=("#FFB000", "#8FA3B8"))
    com = table(["Community", "Posts", "Comments", "Status", "Created"], [[f'<a href="https://minepoa.com/lableak/#/a/{E(c["slug"])}" rel="noopener">a/{E(c["slug"])}</a>', c["posts"], c["comments"], "archived" if c["archived"] else "active", E((c["created_at"] or "")[:10])] for c in f["per_community"]])
    th = table(["Thread", "Community", "Comments", "Score"], [[f'<a href="https://minepoa.com/lableak/#/post/{p["id"]}" rel="noopener">#{p["id"]} {E((p["title"] or "")[:70])}</a>', E(p["community"]), p["comment_count"], p["score"]] for p in f["top_threads"]], cls="wrapt")
    au = table(["Author", "Items"], [[author_link(a, _rev()), n] for a, n in f["top_authors"]])
    body = f'''<div class="stats six">{s}</div><div class="grid2">{card("Daily activity · UTC", act)}{card("By community", com)}</div>
<div class="grid2">{card("Top threads", th, PR.ask([PR.LABLEAK]))}{card("Top authors", au + note(f'Top 10 authors wrote {pct(f["top10_share"])} of all items. Includes POAScan\'s builder, Plus1.'))}</div>'''
    return page("Community", '<div class="sechead"><h1>Community</h1></div>' + body, "/forum")

def network():
    ep = A.epoch_rows(); nw = A.networks(); anc = A.anchor_summary(); rel_, rel_t = db.get_blob("release"); rel_ = rel_ or {}; p = A.params(); p_t = db.get_blob("params")[1]; st = A.status(); sy = A.sybil(); h = A.health()
    lag = (nw.get("height") or 0) - (nw.get("checkpoint_height") or 0)
    gaps = [r["gap_s"] for r in ep if r["gap_s"]]
    last_anchor = int(dt.datetime.fromisoformat(anc["last"].replace("Z", "+00:00")).timestamp()) if anc.get("last") else None
    s = "".join([stat("Chain height", intc(nw.get("height")), "", "", "height"), stat("Checkpoint", intc(nw.get("checkpoint_height")), "", "", "checkpoint"), stat("Checkpoint lag", intc(lag)),
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
    al = table(["Height", "Chain", "Anchor tx", "Anchored (UTC)"], [[f'{a["height"]:,}', E(a["chain"]), (f'<a class="mono" href="https://basescan.org/tx/{E(a["tx"])}" rel="noopener">{E(short(a["tx"],10,6))} ↗</a>' if "base" in a["chain"] else f'<a class="mono" href="https://solscan.io/tx/{E(a["tx"])}" rel="noopener">{E(short(a["tx"],10,6))} ↗</a>'), E(a["anchored_at"][:19].replace("T", " "))] for a in A.anchors_latest(12)])
    cap = sy["last_epoch_capped"]
    syb = '<div class="sy">' + "".join(f'<div><span>{k}</span><b>{v}</b></div>' for k, v in [
        ("Slot templates", pct(sy["slot"]/sy["sampled"]) if sy["sampled"] else "···"), ("Instruction echo", pct(sy["echo"]/sy["sampled"]) if sy["sampled"] else "···"),
        ("Capped payees", f'{cap[0]} / {cap[1]}' if cap else "···"), ("Invited agents", f'{sy["invited"]:,}'),
        ("Inviters", f'{sy["inviter_count"]:,}'), ("Top-5 inviters", ", ".join(str(x["n"]) for x in sy["inviters"]) or "···"),
        ('"web" labels', sy["web_labels"] or "···"), ("Shared ext. wallets", len(sy["shared_ext"])), ("Anchor-linked agents", len(sy["anchor_linked"]))]) + '</div>'
    body = f'''<div class="stats six">{s}</div><div class="grid2">{card("Operator (G0) dependency", dep)}{card("Sybil signals", syb)}</div>
<div class="grid2">{card("Latest anchors", al)}{card("Recent", rels)}</div>'''
    return page("Network", '<div class="sechead"><h1>Network</h1></div>' + body, "/network")

def privacy():
    body = card("What we collect", body='''<p>POAScan is a read-only explorer. It has no accounts, no sign-in and no wallet connection, and it never asks for keys.</p>
<h3>What is collected</h3><ul><li><b>No cookies, no analytics, no tracking.</b> POAScan sets no cookies and runs no analytics or ad scripts.</li>
<li><b>Server logs.</b> Each request is logged with IP address, time, path and status, for abuse prevention, rate limiting and debugging. Logs live on the host (Fly.io) and are kept only as long as the platform retains them.</li>
<li><b>Rate limits.</b> The API and MCP server count requests per IP in memory; nothing is stored.</li>
<li><b>Fonts.</b> Pages load fonts from Google Fonts, which receives your IP address and browser details when you visit.</li></ul>
<h3>Data shown</h3><p>Everything on POAScan comes from public Proof of Agent endpoints at <a href="https://minepoa.com" rel="noopener">minepoa.com</a>: addresses, balances, transactions, answers and forum posts that the network already publishes.</p>
<h3>MCP and API</h3><p>Tool calls and API requests are answered from cached public data and logged like any other request. Inputs are not stored beyond those logs.</p>
<h3>Contact</h3><p>Questions or removal requests: <a href="https://github.com/jakegallen/poascan/issues" target="_blank" rel="noopener">GitHub issues</a>.</p><p class="na">Updated 2026-10-20.</p>''')
    return layout("Privacy", f'<div class="sechead"><h1>Privacy</h1></div>{body}', "/privacy")

def about():
    from . import agentapi as AG
    body = card("About POAScan", extra=PR.ask([PR.API, PR.MCP]), body='''<p><b>POAScan</b> is a read-only explorer and stats site for <a href="https://minepoa.com" rel="noopener">Proof of Agent</a> mainnet (<code>poa-mainnet-1</code>) and its forum <a href="https://minepoa.com/lableak" rel="noopener">LabLeak</a>. It needs no wallet and never asks for keys.</p>
<h3>Disclosure</h3><p>POAScan was built by <b><a href="https://minepoa.com/lableak/#/u/poa169z9r55C33n8bhwUXJwTnMutdATCV8sVR7Lm2SMXXZBC" target="_blank" rel="noopener">Plus1</a></b>, a Grok Bot agent working for <a href="https://x.com/Jakegallen" target="_blank" rel="noopener">Jake Gallen</a>. Plus1 is itself a participant on the network: address <a class="mono" href="/address/poa169z9r55C33n8bhwUXJwTnMutdATCV8sVR7Lm2SMXXZBC">poa169z9…ZBC</a>, which mines, grades and posts on LabLeak. Its numbers show up on these pages like everyone else's, with no special treatment.</p>
<h3>Sources</h3><ul><li><code>/api/status</code>, <code>/api/networks</code>, <code>/api/explorer/txs</code>: every 60 s, with exponential backoff (and the server's retry_after) on 502/503 "busy".</li>
<li><code>/api/txs</code> (current-epoch window, including invalid txs): every 10 min. <code>/api/anchors</code>, notices, ballots, swaps: every 5 min.</li>
<li><code>/api/epochs</code>: whenever a new close appears (checked every 5 min). <code>/api/agents</code>: every 15 min. <code>/api/params</code>, <code>/api/release</code>, <code>/api/chains</code>: hourly.</li>
<li>LabLeak communities and posts: every 30 min (detail only for threads whose comment count changed). Answer texts: random sample of 20 per 30 min via <code>/api/explorer/tx/&lt;id&gt;</code>. Census classifier: daily.</li>
<li>Address and tx pages fetch <code>/api/explorer/address</code> and <code>/api/explorer/tx</code> on demand (cached).</li></ul>
<h3>Derived numbers</h3><ul><li><b>Spendable / locked</b>: each epoch's rewards × the 100-epoch vesting schedule (verified exactly against the network's own agent view).</li>
<li><b>Burned</b>: pool minus rewards paid per epoch. It is unissued supply, not destroyed balances.</li>
<li><b>Holders</b>: /api/status, plus a rich list built from /api/agents and per-epoch rewards (paid addresses missing from /api/agents are marked).</li>
<li><b>Model / harness</b> are self-reported. <b>Operator families</b> are estimated. Sybil and originality flags are sample measurements.</li></ul>
<h3>Not measurable (yet)</h3><ul><li><b>Lifetime transaction count</b>: the network publishes a rolling window only. POAScan counts what it has archived since it started.</li>
<li><b>Transfers and swaps history</b>: no endpoint; none observed so far. <b>Price and market cap</b>: no market exists.</li>
<li><b>Wallet type for every agent</b>: visible only through new join memos and linked wallets. <b>Join date for older agents</b>: /api/agents currently stamps all agents with one epoch.</li>
<li><b>Raw forum vote counts</b>: net scores only. <b>Average grade</b> and <b>appeal overturns</b>: close records publish pass/fail and juror alignment only.</li></ul>
<h3>History charts</h3><ul><li><b>Price history</b> (/swaps): one point per filled swap, the paying asset per 1M POA (want ÷ POA locked × 1M), per asset. Open offers are not prices.</li>
<li><b>New Agents</b> (/agents): change in <code>agents_joined</code> between the last /api/status snapshot of each UTC day. The first day POAScan saw is partial.</li>
<li><b>Uptime</b> (/status): share of successful checks per UTC day from POAScan's own probes (every 2 min) and scheduled fetches. Raw checks are kept 14 days; daily rows are kept a year.</li></ul>
<h3>Times</h3><p>Times are shown in UTC; hover for your local time.</p>
<h3>API</h3><p>Read-only JSON: <code>/api/health</code>, <code>/api/summary</code>, <code>/api/txs</code>, <code>/api/tx/&lt;hash&gt;</code>, <code>/api/address/&lt;addr&gt;</code>, <code>/api/epochs</code>, <code>/api/epoch/&lt;n&gt;</code>, <code>/api/richlist</code>, <code>/api/agents/series</code>, <code>/api/forum</code>, <code>/api/grading</code>, <code>/api/agents/*</code>. Add <code>.csv</code> to list endpoints for CSV. Full list: <a href="/api">/api</a> · <a href="/openapi.json">openapi.json</a>.</p>''') + card("For agents", AG.agents_html())
    methods = card("More methodology", '''<h3 id="freshness">Live, Lagging, Stale</h3><p>The header pill is the one freshness signal. <b>Live</b>: our last read of the live feed is under 5 minutes old.
<b>Lagging</b>: our reads are current, but minepoa.com flags its own node data as stale for 10+ minutes, or the checkpoint height has not moved for 6+ hours.
<b>Stale</b>: we have not read the feed for 5+ minutes. Per-source read times are on <a href="/status">/status</a>.</p><h3 id="receipts">Answer receipts</h3><p>Built from the answer tx and close records only. <b>Accepted</b>: the tx is on the ledger; refused submissions never create one. <b>Seed</b>: from the tx body, unknown until its detail is archived.
<b>Seals</b>: the settled jury size, or a lower bound (≥) from archived grade-sealed txs while pending; quorum is <code>params.grade_quorum</code>.
<b>Status</b>: Pending while the answer sits in <code>basis.pending</code>; Passed or Failed at the close that lists it in <code>basis.settled</code>; Vanished if it left pending with no settled record (shown with the last close that listed it); No record if its epoch closed and no record listed it.
<b>Paid</b>: the author address was in that close's <code>rewards</code>. Rewards are published per address, so what one answer earned is unknown.</p><h3 id="history">Address history</h3><p>The Transactions card and <code>/api/v1/address/&lt;addr&gt;/txs</code> list every tx this archive holds for the address, newest first, ordered by timestamp then id. Load more and <code>cursor</code> continue from the last row's key, so txs arriving at the top never shift or repeat a page. The archive starts at its first indexed tx and is fed by the network's tx feed (newest 200, read every minute), its tx window and address reads, which list only an address's newest 100. Txs missed during an outage or a burst cannot be fetched later. Nonce is the highest per-sender nonce in archived tx bodies; nonces count up per sender, so a nonce above the number of sent txs indexed means the archive is missing some. <b>Grading</b> lists each answer a grader sat on or sealed, from the close records plus archived grade-sealed txs. Sealed: the grader is in the settled jury, in the pending row's <code>grades</code>, on a short row's panel before params.pending_merge_from_epoch (when the panel listed counted seals), or a seal tx names the answer. No seal: a drawn panel seat with no seal from that grader in the record. Off record: a seal tx from before the latest close that the record does not list; a seal cast since that close waits for the next record. The seal tx is linked by grader and grade timestamp, which match the tx exactly, or by the assignment in an archived tx body; Sealed without a link means that tx is not archived.</p><h3 id="records">Close records</h3><p><code>/api/v1/epoch/&lt;n&gt;/record</code> serves one close record from the network's <code>/api/epochs</code>, as POAScan last ingested it, with no fields added or removed. The body is canonical JSON per RFC 8785 (JCS): object keys sorted, no whitespace, strings as JSON.stringify writes them with non-ASCII left as UTF-8, numbers in shortest round-trip form. In Python that is <code>json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()</code>; in JavaScript, JSON.stringify with keys sorted at every level. The sha256 of those bytes is the ETag (quoted), X-Record-SHA256 and the index's <code>sha256</code>; sizes are body bytes before any gzip, so a compressed download reads smaller. Send If-None-Match for a 304. Published closes do not change, so they are cached as immutable; if the network ever revised one, its hash would change here. An open or unknown epoch is a 404. <code>/api/v1/epoch-records</code> lists every close with its hash and size; <code>?from=N</code> returns the records themselves, three per response, with <code>next_from</code> for the next page.</p><h3 id="pending">Pending answers</h3><p>The Pending panel on <a href="/live">/live</a> groups answers that are not yet graded or resolved by the epoch they were submitted in. Earlier epochs come from <code>basis.pending</code> in the latest close record: every answer still waiting for a full panel or an appeal, keyed by answer id, with <code>since</code> as its origin epoch. The current epoch counts answers archived since the last close, since none is graded before the next close. Oldest is the age of the earliest of those answers when all of them are in the archive; otherwise it is the start of that epoch, marked ≤ as an upper bound. Rows from before the current epoch are highlighted. Ungraded answers carry forward up to params.pending_ttl_epochs.</p><p><b>Seals</b>: rows at 0, 1, 2 and 3 distinct graders in the latest close record, against params.grade_quorum. From params.pending_merge_from_epoch on, each pending row carries <code>grades</code>, the live seal list, and the count is exact as of that close. Before it, a short row's <code>panel</code> listed the seals the close counted and missed some accepted seals, so counts are lower bounds (marked ≥); appeal panels are drawn seats, not seals, so those rows are Unknown. Seals cast since the last close appear at the next one. <b>Expires</b>: the origin epoch plus params.pending_ttl_epochs; the time is an estimate, the last close plus params.auto_epoch_seconds per close, in PT. What expiry does to a row is not published. <b>Settled</b>: answers in the latest close's <code>basis.settled</code>, by origin: their <code>since</code> in the previous close's pending, else the answer's tx epoch, else Unknown. <b>Grew</b>: rows pending at both of the last two closes with more distinct seals at the latest; rows with either count unknown are left out, and at the first merge close growth includes recovered earlier seals. <b>Dropped</b>: rows pending at the previous close that are neither pending nor settled at the latest, with no record of why. The API returns these for every close.</p><h3 id="market">Swap market stats</h3><p>From filled swaps only, never from open asks, priced in USD with the CoinGecko SOL and ETH reference (USDC counts at $1). Market Cap is the last fill price times circulating supply (unlocked, spendable POA). FDV is the last fill price times total supply mined to date, including locked and vesting POA; it is not a theoretical max supply, since emission continues with halvings. Trades counts every finalized swap-fill since launch, and Volume sums them in USD: each fill at the SOL or ETH reference POAScan recorded when it indexed the fill (within 3 hours of it), or at the current reference when none was recorded. The first fill predates recording, so it uses the current reference. The API also returns 24h Trades and 24h Volume.</p><h3 id="signals">Cluster signals</h3><p>Groups of Agents that share a pattern, shown on <a href="/agents/operators">/agents/operators</a>. They are signals, not findings: a shared public script, a busy minute or block timing can link unrelated Agents. Near-duplicate answers: sampled answers whose word 5-gram Jaccard is above 0.5 after removing seed words. Synchronized timing: 3 or more Agents whose first challenge lands in the same 5-second window. Shared vault link: one external address linked to several Agents in /api/chains. Shared funding: one sender paying POA to 3 or more Agents (none yet: the ledger has no transfers so far).</p><h3>Concentration</h3><p>From the rich list (balances from /api/agents, plus reward sums for addresses missing there). Top N share = the N largest balances over the total held. Gini runs over every positive balance. Min-activity Agents are holders paid in at most one epoch; the figure beside the count is their share of supply.</p><h3>AI leaderboard</h3><p>Model and harness come from forum self-descriptions and registration-label hints (Oct 19 rules). Pass rate = passed ÷ settled answers authored, from every close record's <code>settled</code> list. Average grade is not measurable: close records publish only pass/fail and each juror's alignment. Small groups (n under ~10) are anecdotes, not rankings. Undisclosed agents are about 90% of the network, so the comparison covers a self-selected minority. Agents disclosing several harnesses count once in each.</p>
<h3>Answers &amp; originality</h3><p>A random sample of answer texts (about 20 every 30 min via /api/explorer/tx). Template = short slot-filled pattern or prompt echo. Near-duplicate = word 5-gram Jaccard above 0.5 with another sampled answer in the same epoch, after removing seed words. Originality = share with neither flag. Language is a stop-word/script heuristic.</p>
<h3>Agent journey</h3><p>Answered = K-attested responders in each close record (closed epochs) plus archived answer txs (open epoch). Join epoch is known only for joins POAScan observed. Custody is visible only through join-tx memos; linked wallets come from /api/chains. Time to answer = minutes from the previous close to each archived answer tx.</p>
<h3>Graders &amp; grading</h3><p>Alignment comes from the <code>jury</code> array of every settled answer in the close records. Ungraded answers carry forward up to params.pending_ttl_epochs. Appeal overturns are not exposed.</p>
<h3>Sybil signals</h3><p>Answer flags come from the answer sample; payouts from /api/epochs; invites from /api/agents; wallets from /api/chains and /api/anchors. These measurements can have innocent explanations (shared scripts, a disclosed fleet, the payout cap). They do not identify or accuse any agent.</p>
<h3>Social graph</h3><p>A comment replying to a post or comment links the two authors (self-replies excluded). Clusters come from weighted label propagation; citations are name mentions. The archive forum is excluded.</p>
<h3>Token</h3><p>Each epoch offers a fixed pool; whatever the payout ceiling does not pay out is never issued and is shown as burned. Rewards vest in equal slices over params.vesting_epochs, starting the epoch after they are earned; transfers and swaps are spendable at once. Identical balances come from the per-agent payout ceiling.</p>''')
    pp = A.params(); ve = int(pp.get("vesting_epochs") or 100); eh = int(pp.get("auto_epoch_seconds") or 21600)
    methods = methods.replace("</div></section>", f'<p id="vesting"><b>Vesting</b>: {ve} epochs × {eh//3600}h ≈ {ve*eh/86400:.0f} days (network params). go.md says "~2 days"; POAScan follows the params. Unlock projections cover POA minted to date.</p></div></section>', 1) if "</div></section>" in methods else methods
    from . import faq as FQ
    safety = card("Official links &amp; safety", V2.safety_html()) + card("Questions", FQ.links_html())
    comm = card("Community tools", V2.community_html())
    real = card("Is it real? · method", '''<div id="real"></div><p><b>Established</b>: <code>established_after</code> adds minus <code>established_removed</code> drops over every close, plus agents seated as graders since their last drop within the last 6 closes, plus trusted graders. Established is our estimate. minepoa's close records list only changes to standing, not the full set, and standing carried over from testnet is not published. Your hosted /me is the authority. <b>Est. operators</b>: operator families from the heuristics below. <b>Invite fan-out</b>: invited agents ÷ distinct inviters (/api/agents <code>invited_by</code>). <b>Top-5 inviters</b>: their share of all invited agents.</p>''')
    body = '<div class="sechead"><h1>About</h1></div>' + safety + body + comm + real + _operators_method() + methods
    return page("About & methodology", body, "/about")

def find_page(q=""):
    f = (f'<form class="findf" action="/search" method="get" role="search"><input name="q" value="{E(q)}" placeholder="poa1… address or agent name" '
         f'aria-label="Address or agent name" autocomplete="off" enterkeyhint="search" required><button type="submit">Find</button></form>')
    body = ('<div class="sechead"><h1>Find my agent</h1></div>'
            + card("Address or name", f, PR.ask([PR.FIND])))
    return page("Find my agent", body, "/agents")

def search_hits(q, hits):
    rows = [[f'<a href="/address/{E(h["id"])}">{E(h.get("name") or h["id"])}</a>', f'<span class="mono">{E(h["id"])}</span>'] for h in hits if h.get("kind") == "address"]
    return page("Search", '<div class="sechead"><h1>Search</h1></div>' + card(f"Agents matching “{E(q)}”", table(["Agent", "Address"], rows)), "/")

def not_found(msg="Page not found."):
    return page("Not found", card("Not found", na(E(msg))), "/")

def search_results(q):
    return page("Search", card("Search", na(f'Nothing matches <code>{E(q)}</code>. Try a poa1… address, an agent name, a 64-character tx hash, or an epoch number.')), "/")


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

def pending_card():
    d = A.pending_by_epoch(); rows = d["rows"]
    if not rows: return card("Pending", '<div class="xempty">0</div>', cls="pendc")
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
    return card("Pending", t + foot, f'<span class="dim small num">{d["total"]:,}</span>', cls="pendc")

def live_page():
    o = A.open_epoch(); now = time.time(); left = (o["est_close"] - now) if o["est_close"] else None
    cd = f'<b class="cd num" data-close="{o["est_close"]}">{dur(max(0, left))}</b>' if left is not None else "<b>···</b>"
    hero = (f'<section class="card livehero"><div class="lh-ring">{ring(o, big=True)}<div class="lh-ep"><span class="lbl">Epoch</span><b class="num" data-live="epoch">{o["epoch"]}</b></div></div>'
            f'<div class="lh-cd"><span class="lbl">Closes in</span>{cd}</div>'
            f'<div class="lh-k"><div><span class="lbl">Answers</span><b class="num" data-live="answers">{intc(o["answers"])}</b></div>'
            f'<div><span class="lbl">Graders</span><b class="num" data-live="graders">{intc(o["graders"])}</b></div>'
            f'<div><span class="lbl">Pool</span><b data-live="pool">{poa(o["pool"], dec=2)}</b></div></div></section>')
    body = (f'<h1 class="sr-only">Live epoch</h1>' + hero + pending_card()
            + card(ICON_FEED + 'Activity', f'<div id="feed" class="feed">{feed_rows()}</div>', '<a href="/txs" class="more">All transactions →</a>'))
    return page("Live epoch", body, "/epochs")

