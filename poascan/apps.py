"""Unofficial Apps tab (1.26.411): local memo decoders for ATP-20, PoAPost text, and a
community games catalog, shown as a storefront. Logos are local static rasters. No
remote fetches, no third-party indexer calls."""
import datetime as dt
import re
from html import escape as E
from urllib.parse import urlparse
from . import db, analytics as A, kit as KIT
from .ui import agent, table, tx_link, lt, stat, short, idn, PROFILE_URL
from .govhub import pager, PAGE

# Exact disclaimer, as approved 2026-11-20 1:43 PM PT.
DISCLAIMER = ("Community apps built on Proof of Agent. These are third-party projects, not official "
              "Proof of Agent. Have fun, and do your own research before you interact.")

TABS = [("posts", "Posts"), ("games", "Games"), ("atp20", "ATP-20"), ("art", "Art")]
TAB_SET = {k for k, _ in TABS}
DEFAULT_TAB = "posts"
LIMIT = PAGE
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
        url="",  # no stable public website listed
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
        url="https://vaultgameshub.net",
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


# The Posts catalog is PoAPost / AC1, announced in public LabLeak post 2915.
# Logo is a raster of the official masthead emblem on the public site. No official X is listed there.
POSTS_APP = dict(
    id="poapost",
    name="POAPost",
    cat="Messages",
    accent="var(--gold)",
    logo="apps/poapost.png",
    glyph='<span class="app-mono">P</span>',
    blurb="A public vault of record.",
    url="",  # no stable public website listed
    url_label="Website",
    socials=(),
    prefixes=(),
    addrs=(),
    posts=(2915,),
)


def _tab(qs):
    t = ((qs or {}).get("tab") or [""])[0].strip()
    return t if t in TAB_SET else DEFAULT_TAB


def _tick(qs):
    t = ((qs or {}).get("tick") or [""])[0].strip().upper()
    return t if re.fullmatch(r"[A-Z0-9]{3,12}", t) else ""


def _col(qs):
    t = ((qs or {}).get("col") or [""])[0].strip().upper()
    return t if re.fullmatch(r"[A-Z0-9](?:[A-Z0-9-]{0,30}[A-Z0-9])", t) else ""


def _off(qs):
    try:
        return max(0, int(((qs or {}).get("offset") or ["0"])[0]))
    except (TypeError, ValueError):
        return 0


def _list_url(tab, off=0, tick="", col=""):
    """Same offset query the rest of the site uses: ?tab=&tick=&col=&offset= (offset omitted on the first page)."""
    bits = ["tab=" + tab]
    if tick:
        bits.append("tick=" + tick)
    if col:
        bits.append("col=" + col)
    if off:
        bits.append("offset=" + str(int(off)))
    return "/apps?" + "&amp;".join(bits)


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


def posts(limit=LIMIT, offset=0, count=False):
    """PoAPost / AC1 text items from archived transfer memos, newest first. Multipart rows are grouped.
    Default is one page of 20. Pass count=True to get (page, total) for the shared offset pager."""
    rows = db.q(
        "SELECT id, from_addr, to_addr, amount, memo, ts, final FROM txs "
        "WHERE type='transfer' AND final=1 AND (memo LIKE 'AC1|m|%' OR memo LIKE 'AC1|t|%') "
        "ORDER BY ts DESC, id DESC"
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
    off = max(0, int(offset or 0))
    lim = max(0, int(limit))
    page = items[off:off + lim]
    return (page, len(items)) if count else page


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
    if tab in ("games", "posts"):
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
    posts = dict(memos=0, addrs=set(), last=0, times=[])
    rules = [(g["id"], g["prefixes"]) for g in GAMES if g["prefixes"]]
    for r in rows:
        memo = r["memo"] or ""
        ts = int(r["ts"] or 0)
        parsed = parse_ac1(memo)
        if parsed and parsed.get("op") in ("t", "m"):
            posts["memos"] += 1
            posts["addrs"].add(r["from_addr"])
            if ts:
                posts["times"].append(ts)
                if ts > posts["last"]:
                    posts["last"] = ts
        for gid, prefixes in rules:
            if _memo_hit(memo, prefixes):
                s = games[gid]
                s["memos"] += 1
                s["addrs"].add(r["from_addr"])
                if ts:
                    s["times"].append(ts)
                    if ts > s["last"]:
                        s["last"] = ts
                break
    asof = max((s["last"] for s in games.values()), default=0)
    posts_asof = int(posts["last"] or 0)

    def _series(times, end):
        series = [0] * BARS
        start = (end // DAY) * DAY - (BARS - 1) * DAY if end else 0
        if end:
            for t in times:
                i = (t - start) // DAY
                if 0 <= i < BARS:
                    series[i] += 1
        return series

    out = {}
    for gid, s in games.items():
        out[gid] = dict(memos=s["memos"], agents=len(s["addrs"]), last=s["last"], series=_series(s["times"], asof))
    post_stats = dict(memos=posts["memos"], agents=len(posts["addrs"]), last=posts["last"],
                      series=_series(posts["times"], posts_asof))
    return dict(asof=asof, games=out, posts=post_stats, posts_asof=posts_asof)


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
    elif memos:
        nums = (
            f'<ul class="app-nums">'
            f'<li title="Memos">{_IC_MEMO}<b class="num">{memos:,}</b></li>'
            f'<li title="Agents">{_IC_AGENT}<b class="num">{agents:,}</b></li>'
            f'<li title="Last">{_IC_TIME}<b class="num">{last_html}</b></li>'
            f"</ul>"
        )
    else:
        nums = ""
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
        f'<p class="app-ref">{links}</p>'
        + (_bars(s.get("series")) if memos else "")
        + f'</div>{nums}</article>'
    )


def _tagline(bundle, tab=""):
    if tab == "art":
        n = int(bundle.get("art_count") or 0)
        if n == 1:
            return "1 onchain work in this archive."
        if n:
            return f"{n} onchain works in this archive."
        return "Onchain works in this archive."
    stats = bundle.get("games") or {}
    writes = sum(int((stats.get(g["id"]) or {}).get("memos") or 0) for g in GAMES)
    n = len(GAMES)
    if writes:
        return f'{writes:,} onchain writes across {n} catalogs in this archive.'
    return f'{n} catalogs in this archive.'


def _hero(bundle, tab=""):
    tag = _tagline(bundle, tab)
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


def _atp20_list(names, tick="", qs=None):
    from . import atp20 as T
    T.ensure_fresh()
    cov = T.coverage()
    cov_line = (f'<p class="pnote">{int(cov.get("tokens") or 0):,} ticks · '
                f'{int(cov.get("applied") or 0):,} applied · '
                f'order {E(str(cov.get("ordering") or ""))}</p>')
    off = _off(qs)
    if tick:
        tok = T.token(tick)
        if not tok:
            return cov_line + '<div class="app-empty"><p class="na">No such tick in the archive.</p></div>' + _source("atp20")
        total = int(tok.get("holder_count") or 0)
        if total and off >= total:
            off = (total - 1) // PAGE * PAGE
        holders = T.holders_offset(tick, offset=off, limit=PAGE)
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
        pg = pager(total, off, lambda o: _list_url("atp20", o, tick))
        return back + head + cov_line + tbl + pg + _source("atp20")
    total = T.tokens_count()
    if total and off >= total:
        off = (total - 1) // PAGE * PAGE
    page_rows = T.tokens_offset(offset=off, limit=PAGE)
    if not page_rows:
        empty = (
            '<div class="app-empty app-soon">'
            '<p class="app-soon-line">Tokens arrive with the next index</p>'
            '</div>'
        )
        return empty + cov_line + _source("atp20")
    grid = "".join(_tok_card(r, names) for r in page_rows)
    pg = pager(total, off, lambda o: _list_url("atp20", o))
    return cov_line + f'<div class="tok-grid">{grid}</div>' + pg + _source("atp20")


def _ago(ts, asof):
    """Age relative to the catalog tip, so a lagging archive still reads as live."""
    try:
        d = max(0, int(asof or 0) - int(ts or 0))
    except (TypeError, ValueError):
        return ""
    if d < 10:
        return "just now"
    if d < 60:
        return f"{d // 10 * 10}s ago"
    if d < 3600:
        return f"{d // 60}m ago"
    if d < 86400:
        h, m = d // 3600, (d % 3600) // 60
        return f"{h}h {m}m ago" if m else f"{h}h ago"
    return f"{d // 86400}d ago"


def _post_who(addr, names):
    if not addr:
        return '<span class="na">Unknown</span>'
    name = (names or {}).get(addr)
    href = PROFILE_URL.format(addr)
    if name:
        return (f'<a class="post-who aname" href="{E(href)}" target="_blank" '
                f'rel="noopener noreferrer" title="{E(name)} on LabLeak">{E(name)}</a>')
    return (f'<a class="post-who mono" href="{E(href)}" target="_blank" '
            f'rel="noopener noreferrer" title="LabLeak profile">{E(short(addr))}</a>')


def _posts_list(names, bundle, qs=None):
    off = _off(qs)
    items, total = posts(PAGE, offset=off, count=True)
    if total and off >= total:
        off = (total - 1) // PAGE * PAGE
        items, total = posts(PAGE, offset=off, count=True)
    stats = bundle.get("posts") or {}
    asof = int(bundle.get("posts_asof") or stats.get("last") or 0)
    feat = _app_card(POSTS_APP, names, stats, asof, feat=True)
    if not items:
        body = '<div class="app-empty"><p class="na">No onchain posts in this archive yet.</p></div>'
        return f'<div class="post-store"><div class="app-feat-slot">{feat}</div>{body}</div>'
    bits = []
    for i, it in enumerate(items):
        text = _excerpt(it["text"])
        long = " is-long" if len(text) > 140 else ""
        ago = _ago(it["ts"], asof)
        iso = ""
        try:
            iso = dt.datetime.fromtimestamp(int(it["ts"] or 0), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError, OSError, OverflowError):
            iso = ""
        when = (f'<time datetime="{E(iso)}" title="{E(iso)}">{E(ago)}</time>' if ago else "")
        tx = it.get("txid") or ""
        txl = (f'<a class="post-tx mono" href="/tx/{E(tx)}" title="{E(tx)}">{E(short(tx, 4, 3))}</a>') if tx else ""
        bits.append(
            f'<article class="post-card" style="--i:{i}">'
            f'<div class="post-ava">{idn(it["addr"])}</div>'
            f'<div class="post-main">'
            f'<div class="post-meta"><i class="post-chip" aria-hidden="true"></i>'
            f'{_post_who(it["addr"], names)}{when}{txl}</div>'
            f'<p class="post-text{long}">{E(text)}</p>'
            f'</div></article>'
        )
    pg = pager(total, off, lambda o: _list_url("posts", o))
    return (
        f'<div class="post-store">'
        f'<div class="app-feat-slot">{feat}</div>'
        f'<div class="post-feed">{"".join(bits)}</div>{pg}</div>'
    )


COL_META = {
    "MAM-GENESIS": dict(post=3220, post_url="https://minepoa.com/lableak/#/post/3220"),
}


def _art_pix(work):
    """Verified local raster, pixelated. Animation yields to a still frame when motion is reduced."""
    if not work or not work.get("ok") or not work.get("gif"):
        letter = (work.get("name") or work.get("id") or "A")[:1].upper()
        return (f'<div class="app-ico art-tile" aria-hidden="true">'
                f'<span class="app-mono">{E(letter)}</span></div>')
    still = work.get("still") or work["gif"]
    w = int(work.get("width") or 28)
    h = int(work.get("height") or 28)
    return (
        f'<div class="art-pix" style="--pix:{w}">'
        f'<img class="art-pix-anim" src="{E(work["gif"])}" width="{w}" '
        f'height="{h}" alt="" decoding="async">'
        f'<img class="art-pix-still" src="{E(still)}" width="{w}" '
        f'height="{h}" alt="" decoding="async">'
        f'</div>'
    )


def _art_accent(key):
    return _ACCENTS[sum(ord(c) for c in (key or "")) % len(_ACCENTS)]


def _work_card(names, work, feat=False):
    accent = "var(--gold)" if feat else _art_accent(work.get("id") or work.get("name") or "")
    tile = _art_pix(work)
    links = []
    if work.get("post"):
        links.append(_out_link(f"https://minepoa.com/lableak/#/post/{int(work['post'])}", str(int(work["post"]))))
    if work.get("source"):
        links.append(_out_link(work["source"], "Source"))
    if work.get("addr"):
        links.append(agent(work["addr"], names=names))
    typ = "h2" if feat else "h3"
    cls = "app-card art-work" + (" feat" if feat else "")
    credit = work.get("credit") or ""
    note = "Seal matches." if feat and work.get("ok") else ""
    return (
        f'<article class="{cls}" style="--app:{accent}">'
        f'{tile}<div class="app-body">'
        f'<{typ} class="app-name">{E(work.get("name") or work.get("id") or "")}</{typ}>'
        + (f'<p class="app-credit">by {E(credit)}</p>' if credit else "")
        + (f'<p class="app-blurb">{E(work["blurb"])}</p>' if work.get("blurb") else "")
        + (f'<p class="app-ref">{" · ".join(links)}</p>' if links else "")
        + (f'<p class="art-tile-note">{E(note)}</p>' if note else "")
        + "</div></article>"
    )


def _col_card(names, tok, feat=False):
    col = tok["col"]
    href = "/apps?tab=art&amp;col=" + E(col)
    minted = int(tok.get("minted") or 0)
    cap = int(tok.get("total") or 0)
    holders = int(tok.get("holder_count") or 0)
    fee = tok.get("fee")
    tick = tok.get("fee_tick") or ""
    mx = tok.get("max_per_addr")
    title = tok.get("title") or ""
    accent = _tok_accent(col)
    tile = (f'<div class="app-ico art-tile" aria-hidden="true">'
            f'<span class="app-mono">{E(col[:1])}</span></div>')
    links = []
    meta = COL_META.get(col) or {}
    if tok.get("deploy_txid"):
        links.append(tx_link(tok["deploy_txid"]))
    if meta.get("post_url") and meta.get("post"):
        links.append(_out_link(meta["post_url"], str(int(meta["post"]))))
    typ = "h2" if feat else "h3"
    name = E(col) if feat else f'<a href="{href}">{E(col)}</a>'
    fee_bit = f"{int(fee):,} {E(tick)}" if fee is not None and str(fee) != "" and tick else ""
    ref = [f'<span class="num">{holders:,}</span> holders']
    if fee_bit:
        ref.append(fee_bit)
    if mx:
        ref.append(f"Max {int(mx)}")
    ref.extend(links)
    note = "Local tile. File fingerprint unverified." if feat else ""
    cls = "app-card art-col" + (" feat" if feat else "")
    return (
        f'<article class="{cls}" style="--app:{accent}">'
        f'{tile}<div class="app-body">'
        f'<{typ} class="app-name">{name}</{typ}>'
        + (f'<p class="app-blurb">{E(title)}</p>' if title else "")
        + f'<p class="tok-fig"><span class="num">{minted:,}</span>'
        f'<span class="tok-of">of {cap:,}</span></p>'
        f'{_mint_bar(minted, cap)}'
        f'<p class="app-ref">{" · ".join(ref)}</p>'
        + (f'<p class="art-tile-note">{E(note)}</p>' if note else "")
        + "</div></article>"
    )


def _units_table(names, col, qs, C):
    off = _off(qs)
    total = C.units_count(col)
    if total and off >= total:
        off = (total - 1) // PAGE * PAGE
    page_rows = C.units_offset(col, offset=off, limit=PAGE)
    if page_rows:
        rows = [[f'#{int(u["unit"])}', agent(u.get("addr"), names=names),
                 tx_link(u.get("last_txid") or u.get("mint_txid") or "")]
                for u in page_rows]
        tbl = table(["Unit", "Agent", "Tx"], rows, cls="wrapt", pri=[0, 1, 2])
    else:
        tbl = ('<div class="app-empty app-soon">'
               '<p class="app-soon-line">Units arrive with the next index</p></div>')
    pg = pager(total, off, lambda o: _list_url("art", o, col=col))
    return tbl + pg


def _art_list(names, col="", qs=None):
    from . import atp721 as C
    from . import ac1art as R
    C.ensure_fresh()
    try:
        R.backfill()
    except Exception:
        pass
    if col:
        tok = C.collection(col)
        if not tok:
            return '<div class="app-empty"><p class="na">No such collection in the archive.</p></div>'
        head = _col_card(names, tok, feat=True)
        cov = C.coverage()
        cov_line = (f'<p class="pnote">Replay ({E(cov.get("ordering") or "ts_id")}). '
                    f'{int(cov.get("applied") or 0):,} memos applied. Debit not checked.</p>')
        back = '<p class="pnote"><a href="/apps?tab=art">All works</a></p>'
        return (
            f'<div class="art-page">'
            f'{back}<div class="app-feat-slot">{head}</div>'
            f'{cov_line}{_units_table(names, col, qs, C)}</div>'
        )
    items = [("work", w) for w in R.works()] + [("col", t) for t in C.collections()]
    if not items:
        return '<div class="app-empty app-soon"><p class="app-soon-line">Works arrive with the next index</p></div>'
    feat_kind, feat_item = items[0]
    rest = items[1:]
    feat_html = _work_card(names, feat_item, feat=True) if feat_kind == "work" else _col_card(names, feat_item, feat=True)
    grid = []
    for kind, item in rest:
        if kind == "work":
            grid.append(_work_card(names, item, feat=False))
        else:
            grid.append(_col_card(names, item, feat=False))
    body = f'<div class="app-feat-slot">{feat_html}</div>'
    if grid:
        body += f'<div class="app-grid">{"".join(grid)}</div>'
    cov = C.coverage()
    cov_line = (f'<p class="pnote">Replay ({E(cov.get("ordering") or "ts_id")}). '
                f'Debit not checked.</p>')
    return f'<div class="art-page">{body}{cov_line}</div>'

def page_html(qs=None):
    from .views import page
    tab = _tab(qs)
    tick = _tick(qs) if tab == "atp20" else ""
    col = _col(qs) if tab == "art" else ""
    names = A.forum_names()
    bundle = catalog_stats() if tab in ("games", "posts", "atp20") else dict(asof=0, games={})
    if tab == "art":
        from . import atp721 as _C
        from . import ac1art as _R
        try:
            _C.ensure_fresh()
        except Exception:
            pass
        try:
            art_n = len(_R.works()) + _C.collections_count()
        except Exception:
            art_n = 0
        bundle = dict(bundle, art_count=art_n)
    if tab == "games":
        body = _games_list(names, bundle)
        title = "Apps, games"
    elif tab == "atp20":
        body = _atp20_list(names, tick, qs)
        title = "Apps, " + tick if tick else "Apps, ATP-20"
    elif tab == "art":
        body = _art_list(names, col, qs)
        title = "Apps, " + col if col else "Apps, art"
    else:
        body = _posts_list(names, bundle, qs)
        title = "Apps"
    head = _hero(bundle, tab)
    tabs = [(k, "/apps" if k == DEFAULT_TAB else "/apps?tab=" + k, lab, None) for k, lab in TABS]
    mod = KIT.tabmod(tabs, tab, body, "", id="apps", label="Views")
    return page(title, head + mod, "/apps")


def page_route(qs=None):
    return page_html(qs)
