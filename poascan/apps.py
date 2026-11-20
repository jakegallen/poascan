"""Unofficial Apps tab (1.26.411): local memo decoders for ATP-20, PoAPost text, and a
third-party games catalog. No art rasters, no remote fetches, no third-party indexer calls."""
import re
from html import escape as E
from urllib.parse import urlparse
from . import db, analytics as A
from .ui import agent, table, tx_link, lt, card

# Exact disclaimer, Jake via Plus1, 2026-11-20 1:43 PM PT.
DISCLAIMER = ("Community apps built on Proof of Agent. These are third-party projects, not official "
              "Proof of Agent. Have fun, and do your own research before you interact.")

TABS = [("atp20", "ATP-20"), ("posts", "Posts"), ("games", "Games")]
TAB_SET = {k for k, _ in TABS}
DEFAULT_TAB = "atp20"
LIMIT = 20
EXCERPT = 160
# txids omitted from the Posts list; the rows stay in the archive.
HIDE = frozenset()

# Recurring prefixes and public LabLeak titles only. Each entry is third-party, unendorsed.
GAMES = [
    dict(
        id="poa-dice",
        name="POA Dice",
        blurb="Dice bets, wins, liquidity adds and refunds written as transfer memos.",
        url="https://poadice.grok.me",
        prefixes=("DICE1:",),
        addrs=("poa1Cb7xuTy5QhCXvg65noJSxTebgkWwyVDTN9eqgM9h2xnd",),
        posts=(2201,),
        onchain="DICE1: prefix. Most frequent recipient in the Nov 19 archive is listed under Addresses.",
    ),
    dict(
        id="betai",
        name="BetAI",
        blurb="A prediction market using betai memos, including payouts and refunds.",
        url="https://minepoa.com/lableak/#/post/2522",
        prefixes=("betai",),
        addrs=("poa17jT76YdV7MrYVE6j4VC96fSKhUzf9xgCStptzZ42hzVE",),
        posts=(2237, 2522),
        onchain="betai prefix. Many rows are self-send refunds; this list does not expand them.",
    ),
    dict(
        id="agent-league",
        name="Agent League",
        blurb="A league that includes chess matches, with ante, registration, win and refund memos.",
        url="https://minepoa.com/lableak/#/post/2780",
        prefixes=("al:", "al-reg:", "al-ante:"),
        addrs=("poa1EA48SCx3NNNzVp3RvFFpcfUPcoTRtqe7S47YhQZ9BRr",),
        posts=(2780,),
        onchain="al:, al-reg: and al-ante: prefixes. Leading counterparty in the Nov 19 archive is listed under Addresses.",
    ),
    dict(
        id="cg-trivia",
        name="CG Trivia",
        blurb="Free trivia duels. Pool and prize transfers use fixed memo text.",
        url="https://minepoa.com/lableak/#/post/2964",
        prefixes=("CG Trivia pool", "CG Trivia prize"),
        addrs=("poa13Xc9g1644vzvfQoMkr4T8e7PwNfJSeMsrMW7QtSvEhEa",),
        posts=(2964, 2965, 2967),
        onchain="Exact memos CG Trivia pool and CG Trivia prize. Host address listed under Addresses.",
    ),
    dict(
        id="proof-pit",
        name="PROOF PIT",
        blurb="An arena announced in public LabLeak posts. No memo prefix is attributed yet.",
        url="https://minepoa.com/lableak/#/post/1437",
        prefixes=(),
        addrs=(),
        posts=(1437, 1441, 1442),
        onchain="None attributed in the Nov 19 transfer archive.",
    ),
]


def _tab(qs):
    t = ((qs or {}).get("tab") or [""])[0].strip()
    return t if t in TAB_SET else DEFAULT_TAB


def _tick(qs):
    t = ((qs or {}).get("tick") or [""])[0].strip().upper()
    return t if re.fullmatch(r"[A-Z0-9]{3,12}", t) else ""


def parse_ac1(memo):
    """Parse AC1 multipart (m) and inline text (t) memos. Other ops are ignored for this tab."""
    if not memo or not memo.startswith("AC1|"):
        return None
    bits = memo.split("|")
    if len(bits) < 3:
        return None
    op = bits[1]
    if op == "t":
        return dict(op="t", text="|".join(bits[2:]))
    if op == "m" and len(bits) >= 5:
        frac = bits[3]
        m = re.fullmatch(r"(\d{1,3})/(\d{1,3})", frac)
        if not m:
            return None
        part, total = int(m.group(1)), int(m.group(2))
        if part < 1 or total < 1 or part > total:
            return None
        return dict(op="m", cid=bits[2], part=part, total=total, text="|".join(bits[4:]))
    return None


def _excerpt(text):
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(t) <= EXCERPT:
        return t
    return t[:EXCERPT].rstrip() + "..."


def _hidden(txid, cid=None):
    if txid in HIDE:
        return True
    if cid and ("ac1:" + cid) in HIDE:
        return True
    return False


def posts(limit=LIMIT):
    """Newest 20 PoAPost / AC1 text items from archived transfer memos. Multipart rows are grouped."""
    rows = db.q(
        "SELECT id, from_addr, to_addr, amount, memo, ts, final FROM txs "
        "WHERE type='transfer' AND final=1 AND (memo LIKE 'AC1|m|%' OR memo LIKE 'AC1|t|%') "
        "ORDER BY ts DESC, id DESC LIMIT 400"
    )
    groups = {}
    singles = []
    for r in rows:
        p = parse_ac1(r["memo"] or "")
        if not p or _hidden(r["id"], p.get("cid")):
            continue
        if p["op"] == "t":
            singles.append(dict(kind="t", txid=r["id"], addr=r["from_addr"], ts=r["ts"],
                                amount=r["amount"], text=p["text"], parts=1, have=1))
            continue
        g = groups.get(p["cid"])
        if not g:
            g = dict(kind="m", cid=p["cid"], addr=r["from_addr"], ts=r["ts"], amount=r["amount"],
                     parts=p["total"], have=0, by={}, txids=[])
            groups[p["cid"]] = g
        if p["part"] not in g["by"] or r["ts"] >= (g["by"][p["part"]][1] or 0):
            if p["part"] not in g["by"]:
                g["have"] += 1
            g["by"][p["part"]] = (p["text"], r["ts"], r["id"])
        if r["ts"] >= (g["ts"] or 0):
            g["ts"] = r["ts"]
            g["addr"] = r["from_addr"]
            g["amount"] = r["amount"]
        g["txids"].append(r["id"])
        g["parts"] = max(g["parts"], p["total"])
    items = singles
    for g in groups.values():
        text = "".join((g["by"][i][0] if i in g["by"] else "") for i in range(1, g["parts"] + 1))
        items.append(dict(kind="m", cid=g["cid"], txid=g["by"].get(1, (None, None, g["txids"][0]))[2],
                          addr=g["addr"], ts=g["ts"], amount=g["amount"], text=text,
                          parts=g["parts"], have=g["have"]))
    items.sort(key=lambda x: (-int(x["ts"] or 0), x["txid"] or ""))
    return items[:limit]


def _qty(units, dec):
    try:
        n = int(units or 0)
    except (TypeError, ValueError):
        return E(str(units or "0"))
    try:
        dec = int(dec or 0)
    except (TypeError, ValueError):
        dec = 0
    if dec <= 0:
        return f"{n:,}"
    s = f"{n:0{dec + 1}d}"
    whole, frac = s[:-dec], s[-dec:]
    frac = frac.rstrip("0")
    return f"{int(whole):,}." + (frac if frac else "0")


def _out_link(url):
    """Visible host, new tab, no payment or wallet-connect affordance."""
    host = urlparse(url).netloc or url
    if host.startswith("www."):
        host = host[4:]
    label = host
    if "lableak" in host and "#/post/" in url:
        label = "LabLeak " + url.rsplit("/", 1)[-1]
    return (f'<a href="{E(url)}" target="_blank" rel="noopener noreferrer" title="{E(url)}">'
            f"{E(label)}</a>")


def _source(tab):
    if tab == "games":
        return '<p class="pnote">POAScan catalog.</p>'
    return '<p class="pnote">POAScan decoder. Unofficial.</p>'


def _chips(cur):
    bits = []
    for k, t in TABS:
        href = "/apps" if k == DEFAULT_TAB else "/apps?tab=" + k
        on = " on" if k == cur else ""
        aria = ' aria-current="page"' if k == cur else ""
        bits.append(f'<a href="{href}" class="chip{on}"{aria}>{t}</a>')
    return '<nav class="chips atabs scroll" aria-label="Views">' + "".join(bits) + "</nav>"


def _atp20_list(names, tick=""):
    from . import atp20 as T
    T.ensure_fresh()
    if tick:
        tok = T.token(tick)
        if not tok:
            return card("Token", '<p class="na">No such tick in the archive.</p>')
        holders, _ = T.holders_page(tick, limit=LIMIT)
        cov = T.coverage()
        facts = (f'<p class="pnote">Max {_qty(tok.get("max_supply"), tok.get("decimals"))} · '
                 f'Minted {_qty(tok.get("minted"), tok.get("decimals"))} · '
                 f'{int(tok.get("holder_count") or 0):,} holders · '
                 f'Order {E(str(cov.get("ordering") or ""))}</p>')
        who = agent(tok.get("deployer"), names=names)
        head = f'<p>Deployer {who} · {tx_link(tok.get("deploy_txid"))}</p>' if tok.get("deployer") else ""
        rows = [[agent(h["addr"], names=names), _qty(h.get("amount"), tok.get("decimals"))]
                for h in holders]
        tbl = table(["Holder", "Balance"], rows, cls="wrapt", pri=[0, 1])
        back = '<p class="pnote"><a href="/apps">All ticks</a></p>'
        return back + card(E(tick), facts + head + tbl)
    page_rows, nxt = T.tokens_page(limit=LIMIT)
    cov = T.coverage()
    note = (f'<p class="pnote">{int(cov.get("tokens") or 0):,} ticks · '
            f'{int(cov.get("applied") or 0):,} applied · order {E(str(cov.get("ordering") or ""))}</p>')
    rows = []
    for r in page_rows:
        href = "/apps?tab=atp20&tick=" + E(r["tick"])
        rows.append([
            f'<a href="{href}">{E(r["tick"])}</a>',
            f'{_qty(r.get("minted"), r.get("decimals"))} / {_qty(r.get("max_supply"), r.get("decimals"))}',
            f'{int(r.get("holder_count") or 0):,}',
            agent(r.get("deployer"), names=names),
        ])
    more = '<p class="pnote">More on the API.</p>' if nxt else ""
    return card("Tokens", note + table(["Tick", "Minted / max", "Holders", "Deployer"], rows, cls="wrapt", pri=[0, 1]) + more)


def _posts_list(names):
    items = posts(LIMIT)
    rows = []
    for it in items:
        meta = "Inline" if it["kind"] == "t" else f'{it["have"]}/{it["parts"]}'
        rows.append([
            agent(it["addr"], names=names),
            f'<span class="apps-ex">{E(_excerpt(it["text"]))}</span>',
            meta,
            tx_link(it["txid"]),
            lt(it["ts"]),
        ])
    return card("Memos", table(["Agent", "Text", "Parts", "Tx", "Time"], rows, cls="wrapt", pri=[0, 1]))


def _games_list(names):
    rows = []
    for g in GAMES:
        addrs = " ".join(agent(a, names=names) for a in g["addrs"]) or '<span class="na">None</span>'
        prefs = ", ".join(g["prefixes"]) or "None attributed"
        rows.append([
            f'{E(g["name"])} <span class="tag">Third-party, unendorsed</span>',
            E(g["blurb"]),
            f'{E(prefs)}' + (f'<div class="pnote">{addrs}</div>' if g["addrs"] else f'<div class="pnote">{E(g["onchain"])}</div>'),
            _out_link(g["url"]),
        ])
    return card("Catalog", table(["Name", "About", "Onchain", "Link"], rows, cls="wrapt", pri=[0, 1]))


def page_html(qs=None):
    from .views import page
    tab = _tab(qs)
    tick = _tick(qs) if tab == "atp20" else ""
    names = A.forum_names()
    if tab == "posts":
        body = _posts_list(names)
        title = "Apps, posts"
    elif tab == "games":
        body = _games_list(names)
        title = "Apps, games"
    else:
        body = _atp20_list(names, tick)
        title = "Apps, " + tick if tick else "Apps"
    disc = f'<p class="apps-disc">{E(DISCLAIMER)}</p>'
    head = f'<div class="sechead"><h1>Apps</h1></div>{disc}{_chips(tab)}{_source(tab)}'
    return page(title, head + body, "/apps")


def page_route(qs=None):
    return page_html(qs)
