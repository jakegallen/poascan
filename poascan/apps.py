"""Unofficial Apps tab (1.26.411): local memo decoders for ATP-20, PoAPost text, and a
community games catalog, shown as a storefront. Logos are local static rasters. No
remote fetches, no third-party indexer calls."""
import re
from html import escape as E
from urllib.parse import urlparse
from . import db, analytics as A, kit as KIT
from .ui import agent, table, tx_link, lt, stat

# Exact disclaimer, Jake via Plus1, 2026-11-20 1:43 PM PT.
DISCLAIMER = ("Community apps built on Proof of Agent. These are third-party projects, not official "
              "Proof of Agent. Have fun, and do your own research before you interact.")

TABS = [("posts", "Posts"), ("games", "Games"), ("atp20", "ATP-20")]
TAB_SET = {k for k, _ in TABS}
DEFAULT_TAB = "posts"
LIMIT = 20
EXCERPT = 220
HIDE = frozenset()
_ACCENTS = ("var(--gold)", "var(--verd)", "var(--apps-teal)", "var(--apps-violet)", "var(--apps-magenta)")
BARS = 14
DAY = 86400

# Compact stat glyphs for catalog cards (labels live on the featured hero only).
_IC_MEMO = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="3" width="10" height="10" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M5.5 6.5h5M5.5 9h3.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>'
_IC_AGENT = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="6" r="2.1" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M3.8 12.4c.7-2 2.3-3 4.2-3s3.5 1 4.2 3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>'
_IC_TIME = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M8 5.2V8l2 1.6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>'


def _ico(paths):
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linejoin="round" stroke-linecap="round" aria-hidden="true">{paths}</svg>')


# Recurring prefixes and public LabLeak titles only. Logos and socials are from each app's public site.
GAMES = [
    dict(
        id="poa-dice",
        name="POA Dice",
        cat="Play",
        accent="var(--gold)",
        logo="apps/dice.png",
        glyph=_ico(
            '<rect x="4.5" y="4.5" width="15" height="15" rx="3"/>'
            '<circle cx="9" cy="9" r="1.15" fill="currentColor" stroke="none"/>'
            '<circle cx="15" cy="9" r="1.15" fill="currentColor" stroke="none"/>'
            '<circle cx="12" cy="12" r="1.15" fill="currentColor" stroke="none"/>'
            '<circle cx="9" cy="15" r="1.15" fill="currentColor" stroke="none"/>'
            '<circle cx="15" cy="15" r="1.15" fill="currentColor" stroke="none"/>'
        ),
        blurb="Dice bets, wins, liquidity adds and refunds written as transfer memos.",
        url="https://poadice.grok.me",
        url_label="Website",
        socials=(("GitHub", "https://github.com/maximusmaximus/poa-dice", "GitHub"),),
        prefixes=("DICE1:",),
        addrs=("poa1Cb7xuTy5QhCXvg65noJSxTebgkWwyVDTN9eqgM9h2xnd",),
        posts=(2201,),
        onchain="DICE1: prefix.",
    ),
    dict(
        id="betai",
        name="BetAI",
        cat="Markets",
        accent="var(--verd)",
        logo="apps/betai.webp",
        glyph=_ico('<path d="M5 16 9.5 11.5l3 3L19 8"/><path d="M14.5 8H19v4.5"/>'),
        blurb="A prediction market using betai memos, including payouts and refunds.",
        url="https://build-c8d9b17a1452a09b7be7b3be.emblem.build/pub/garra/betai/",
        url_label="Website",
        socials=(),
        prefixes=("betai",),
        addrs=("poa17jT76YdV7MrYVE6j4VC96fSKhUzf9xgCStptzZ42hzVE",),
        posts=(2237, 2522),
        onchain="betai prefix.",
    ),
    dict(
        id="agent-league",
        name="Agent League",
        cat="League",
        accent="var(--apps-violet)",
        logo="apps/league.webp",
        glyph=_ico('<path d="M12 4.5 18.2 7v5.1c0 3.3-2.5 5.7-6.2 7.2-3.7-1.5-6.2-3.9-6.2-7.2V7z"/>'),
        blurb="A league that includes chess matches, with ante, registration, win and refund memos.",
        url="https://build-d22ff9422a48242dc81097aa.emblem.build/pub/main/agent-league/",
        url_label="Website",
        socials=(
            ("X", "https://x.com/DCTreeofLife", "X @DCTreeofLife"),
            ("Telegram", "https://t.me/VaultGameHub", "Telegram"),
        ),
        prefixes=("al:", "al-reg:", "al-ante:"),
        addrs=("poa1EA48SCx3NNNzVp3RvFFpcfUPcoTRtqe7S47YhQZ9BRr",),
        posts=(2780,),
        onchain="al:, al-reg: and al-ante: prefixes.",
    ),
    dict(
        id="cg-trivia",
        name="CG Trivia",
        cat="Trivia",
        accent="var(--apps-teal)",
        logo="apps/trivia.png",
        glyph=_ico(
            '<circle cx="12" cy="12" r="7.5"/>'
            '<path d="M9.8 10.2c0-1.35 1.05-2.35 2.3-2.35 1.2 0 2.2.85 2.2 2.15 0 1.15-.95 1.7-2.15 2.25v.9"/>'
            '<circle cx="12" cy="16.15" r="0.9" fill="currentColor" stroke="none"/>'
        ),
        blurb="Free trivia duels. Pool and prize transfers use fixed memo text.",
        url="https://cgtrivia.creativegrace.tech/",
        url_label="Website",
        socials=(),
        prefixes=("CG Trivia pool", "CG Trivia prize"),
        addrs=("poa13Xc9g1644vzvfQoMkr4T8e7PwNfJSeMsrMW7QtSvEhEa",),
        posts=(2964, 2965, 2967),
        onchain="Exact memos CG Trivia pool and CG Trivia prize.",
    ),
    dict(
        id="proof-pit",
        name="PROOF PIT",
        cat="Arena",
        accent="var(--apps-magenta)",
        logo="",
        glyph='<span class="app-mono">P</span>',
        blurb="An arena with a live survival board. No memo prefix is attributed yet.",
        url="https://master-zomon.github.io/proof-pit/",
        url_label="Website",
        socials=(),
        prefixes=(),
        addrs=(),
        posts=(1437, 1441, 1442),
        onchain="None attributed.",
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


def _out_link(url, label=None, cls="app-go"):
    """Visible host or given label, new tab, no payment or wallet-connect affordance."""
    host = urlparse(url).netloc or url
    if host.startswith("www."):
        host = host[4:]
    text = label or host
    if not label and "lableak" in url.lower() and "#/post/" in url:
        text = "Post " + url.rsplit("/", 1)[-1]
    return (f'<a class="{E(cls)}" href="{E(url)}" target="_blank" rel="noopener noreferrer" '
            f'title="{E(url)}">{E(text)}</a>')


def _source(tab):
    if tab == "games":
        return ""
    return '<p class="pnote apps-src">POAScan decoder. Unofficial.</p>'


def _memo_hit(memo, prefixes):
    m = memo or ""
    for pfx in prefixes:
        if not pfx:
            continue
        if " " in pfx:
            if m == pfx or m.startswith(pfx):
                return True
        elif pfx[-1:].isalnum():
            if m.lower().startswith(pfx.lower()):
                return True
        elif m.startswith(pfx):
            return True
    return False


@A.cached("apps_catalog_stats", 60, light=True)
def catalog_stats():
    """Per-app memo counts, distinct senders, last activity, and a 14-day write strip."""
    rows = db.q(
        "SELECT memo, from_addr, ts FROM txs "
        "WHERE type='transfer' AND final=1 AND memo IS NOT NULL AND memo!=''"
    )
    games = {g["id"]: dict(memos=0, agents=0, last=0, addrs=set(), times=[]) for g in GAMES}
    rules = [(g["id"], g["prefixes"]) for g in GAMES if g["prefixes"]]
    for r in rows:
        memo = r["memo"] or ""
        for gid, prefixes in rules:
            if _memo_hit(memo, prefixes):
                s = games[gid]
                s["memos"] += 1
                s["addrs"].add(r["from_addr"])
                ts = int(r["ts"] or 0)
                if ts:
                    s["times"].append(ts)
                    if ts > s["last"]:
                        s["last"] = ts
                break
    asof = max((s["last"] for s in games.values()), default=0)
    start = (asof // DAY) * DAY - (BARS - 1) * DAY if asof else 0
    out = {}
    for gid, s in games.items():
        series = [0] * BARS
        if asof:
            for t in s["times"]:
                i = (t - start) // DAY
                if 0 <= i < BARS:
                    series[i] += 1
        out[gid] = dict(memos=s["memos"], agents=len(s["addrs"]), last=s["last"], series=series)
    return dict(asof=asof, games=out)


def game_stats():
    return catalog_stats()["games"]


def _ranked(stats):
    def key(g):
        s = stats.get(g["id"]) or {}
        return (-int(s.get("last") or 0), -int(s.get("memos") or 0), g["name"])
    return sorted(GAMES, key=key)


def _logo(g):
    if g.get("logo"):
        return (f'<div class="app-ico has-logo"><img src="/static/{E(g["logo"])}" alt="" '
                f'width="112" height="112"></div>')
    return f'<div class="app-ico" aria-hidden="true">{g["glyph"]}</div>'


def _bars(series):
    series = list(series or [])
    if len(series) < BARS:
        series = [0] * (BARS - len(series)) + series
    peak = max(series) if series else 0
    bits = []
    for n in series:
        h = 0 if not peak or not n else max(12, int(round(100 * n / peak)))
        bits.append(f'<i style="--h:{h}%"></i>')
    return f'<div class="app-bars" aria-hidden="true">{"".join(bits)}</div>'


def _links(g):
    bits = []
    if g.get("url"):
        bits.append(_out_link(g["url"], g.get("url_label")))
    posts = g.get("posts") or ()
    if posts:
        bits.append(_out_link(f"https://minepoa.com/lableak/#/post/{posts[0]}", f"Post {posts[0]}"))
    for _kind, href, label in g.get("socials") or ():
        bits.append(_out_link(href, label))
    return bits


def _app_card(g, names, s, asof, feat=False):
    memos = int(s.get("memos") or 0)
    agents = int(s.get("agents") or 0)
    last = s.get("last") or 0
    last_html = lt(last) if last else '<span class="na">None</span>'
    live = bool(asof and last and last >= asof - DAY)
    pulse = '<i class="app-pulse" title="Wrote in the latest day of this archive"></i>' if live else ""
    if feat:
        nums = (
            '<section class="stats three app-stats" aria-label="Onchain">'
            + stat("Memos", f'<span class="num" data-cu="{memos}">{memos:,}</span>')
            + stat("Agents", f'<span class="num" data-cu="{agents}">{agents:,}</span>')
            + stat("Last", last_html)
            + "</section>"
        )
    else:
        nums = (
            f'<ul class="app-nums">'
            f'<li title="Memos">{_IC_MEMO}<b class="num">{memos:,}</b></li>'
            f'<li title="Agents">{_IC_AGENT}<b class="num">{agents:,}</b></li>'
            f'<li title="Last">{_IC_TIME}<b class="num">{last_html}</b></li>'
            f"</ul>"
        )
    typ = "h2" if feat else "h3"
    links = "".join(_links(g))
    return (
        f'<article class="app-card{" feat" if feat else ""}" data-app="{E(g["id"])}" '
        f'data-memos="{memos}" data-live="{1 if live else 0}" style="--app:{E(g["accent"])}">'
        f'{_logo(g)}'
        f'<div class="app-body">'
        f'<div class="app-meta"><span class="app-cat">{E(g["cat"])}</span>{pulse}</div>'
        f'<{typ} class="app-name">{E(g["name"])}</{typ}>'
        f'<p class="app-blurb">{E(g["blurb"])}</p>'
        f'<p class="app-ref">{links}</p>{_bars(s.get("series"))}</div>{nums}</article>'
    )


def _tagline(bundle):
    stats = bundle.get("games") or {}
    writes = sum(int((stats.get(g["id"]) or {}).get("memos") or 0) for g in GAMES)
    n = len(GAMES)
    if writes:
        return f'{writes:,} onchain writes across {n} catalogs in this archive.'
    return f'{n} catalogs in this archive.'


def _hero(bundle):
    tag = _tagline(bundle)
    return (
        f'<section class="card benchc hpulse appshero" aria-label="Apps">'
        f'<div class="apps-wash" aria-hidden="true"></div>'
        f'<div class="apps-hero-copy"><h1>Apps</h1>'
        f'<p class="apps-tag"><i class="app-pulse" aria-hidden="true"></i>{E(tag)}</p>'
        f'<p class="apps-disc">{E(DISCLAIMER)}</p></div></section>'
    )


def _games_list(names, bundle):
    stats = bundle.get("games") or {}
    asof = int(bundle.get("asof") or 0)
    ranked = _ranked(stats)
    live = [g for g in ranked if int((stats.get(g["id"]) or {}).get("memos") or 0) > 0]
    feat = live[0] if live else ranked[0]
    rest = [g for g in ranked if g["id"] != feat["id"]]
    order = " ".join(g["id"] for g in live)
    feat_html = _app_card(feat, names, stats.get(feat["id"]) or {}, asof, feat=True)
    grid = "".join(_app_card(g, names, stats.get(g["id"]) or {}, asof, feat=False) for g in rest)
    return (
        f'<div class="app-store" data-apps-rotate data-order="{E(order)}">'
        f'<div class="app-feat-slot">{feat_html}</div>'
        f'<div class="app-grid">{grid}</div></div>'
    )


def _mint_bar(minted, maxs):
    try:
        a, b = int(minted or 0), int(maxs or 0)
    except (TypeError, ValueError):
        a, b = 0, 0
    pct = 0 if b <= 0 else min(100, max(0, 100.0 * a / b))
    return (
        f'<div class="vessel tok-bar" role="meter" aria-valuemin="0" aria-valuemax="100" '
        f'aria-valuenow="{pct:.0f}" aria-label="Minted share">'
        f'<i class="molten" style="width:{pct:.1f}%"></i></div>'
    )


def _tok_accent(tick):
    return _ACCENTS[sum(ord(c) for c in (tick or "")) % len(_ACCENTS)]


def _tok_card(r, names):
    tick = r["tick"]
    href = "/apps?tab=atp20&tick=" + E(tick)
    mono = E((tick or "?")[:1])
    minted = _qty(r.get("minted"), r.get("decimals"))
    cap = _qty(r.get("max_supply"), r.get("decimals"))
    hold = int(r.get("holder_count") or 0)
    return (
        f'<a class="tok-card" href="{href}" style="--app:{_tok_accent(tick)}">'
        f'<div class="app-ico tok-ico" aria-hidden="true"><span>{mono}</span></div>'
        f'<div class="app-body">'
        f'<h3 class="app-name">{E(tick)}</h3>'
        f'<p class="tok-fig"><span class="num">{minted}</span>'
        f'<span class="tok-of">of {cap}</span></p>'
        f'{_mint_bar(r.get("minted"), r.get("max_supply"))}'
        f'<p class="app-ref"><span class="num">{hold:,}</span> holders · '
        f'{agent(r.get("deployer"), names=names)}</p>'
        f'</div></a>'
    )


def _atp20_list(names, tick=""):
    from . import atp20 as T
    T.ensure_fresh()
    cov = T.coverage()
    cov_line = (f'<p class="pnote">{int(cov.get("tokens") or 0):,} ticks · '
                f'{int(cov.get("applied") or 0):,} applied · '
                f'order {E(str(cov.get("ordering") or ""))}</p>')
    if tick:
        tok = T.token(tick)
        if not tok:
            return cov_line + '<div class="app-empty"><p class="na">No such tick in the archive.</p></div>' + _source("atp20")
        holders, _ = T.holders_page(tick, limit=LIMIT)
        who = agent(tok.get("deployer"), names=names)
        head = (
            f'<div class="tok-hero" style="--app:{_tok_accent(tick)}">'
            f'<div class="app-ico tok-ico" aria-hidden="true"><span>{E(tick[:1])}</span></div>'
            f'<div class="app-body">'
            f'<h2 class="app-name">{E(tick)}</h2>'
            f'<p class="tok-fig"><span class="num">{_qty(tok.get("minted"), tok.get("decimals"))}</span>'
            f'<span class="tok-of">of {_qty(tok.get("max_supply"), tok.get("decimals"))}</span></p>'
            f'{_mint_bar(tok.get("minted"), tok.get("max_supply"))}'
            f'<p class="app-ref">{int(tok.get("holder_count") or 0):,} holders'
            + (f' · Deployer {who}' if tok.get("deployer") else "")
            + (f' · {tx_link(tok.get("deploy_txid"))}' if tok.get("deploy_txid") else "")
            + "</p></div></div>"
        )
        rows = [[agent(h["addr"], names=names), _qty(h.get("amount"), tok.get("decimals"))]
                for h in holders]
        tbl = table(["Holder", "Balance"], rows, cls="wrapt", pri=[0, 1])
        back = '<p class="pnote"><a href="/apps?tab=atp20">All ticks</a></p>'
        return back + head + cov_line + tbl + _source("atp20")
    page_rows, nxt = T.tokens_page(limit=LIMIT)
    if not page_rows:
        empty = (
            '<div class="app-empty app-soon">'
            '<p class="app-soon-line">Tokens arrive with the next index</p>'
            '</div>'
        )
        return empty + cov_line + _source("atp20")
    more = '<p class="pnote">More on the API.</p>' if nxt else ""
    grid = "".join(_tok_card(r, names) for r in page_rows)
    return cov_line + f'<div class="tok-grid">{grid}</div>' + more + _source("atp20")


def _posts_list(names):
    items = posts(LIMIT)
    if not items:
        body = '<div class="app-empty"><p class="na">No onchain posts in this archive yet.</p></div>'
        return body + _source("posts")
    bits = []
    for it in items:
        parts = "" if it["kind"] == "t" else f'<span>{it["have"]}/{it["parts"]}</span>'
        bits.append(
            f'<article class="post-row">'
            f'<div class="post-meta">{agent(it["addr"], names=names)}'
            f'<span class="dot" aria-hidden="true"></span>{lt(it["ts"])}'
            + (f'<span class="dot" aria-hidden="true"></span>{parts}' if parts else "")
            + f'<span class="dot" aria-hidden="true"></span>{tx_link(it["txid"])}</div>'
            f'<p class="post-text">{E(_excerpt(it["text"]))}</p>'
            f'</article>'
        )
    return f'<div class="post-feed">{"".join(bits)}</div>' + _source("posts")


def page_html(qs=None):
    from .views import page
    tab = _tab(qs)
    tick = _tick(qs) if tab == "atp20" else ""
    names = A.forum_names()
    bundle = catalog_stats() if tab in ("games", "posts", "atp20") else dict(asof=0, games={})
    if tab == "games":
        body = _games_list(names, bundle)
        title = "Apps, games"
    elif tab == "atp20":
        body = _atp20_list(names, tick)
        title = "Apps, " + tick if tick else "Apps, ATP-20"
    else:
        body = _posts_list(names)
        title = "Apps"
    head = _hero(bundle)
    tabs = [(k, "/apps" if k == DEFAULT_TAB else "/apps?tab=" + k, lab, None) for k, lab in TABS]
    mod = KIT.tabmod(tabs, tab, body, "", id="apps", label="Views")
    return page(title, head + mod, "/apps")


def page_route(qs=None):
    return page_html(qs)
