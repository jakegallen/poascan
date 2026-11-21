"""Unofficial Apps tab (1.26.411): local memo decoders for ATP-20, PoAPost text, and a
community games catalog, shown as a storefront. Logos are local static rasters. No
remote fetches, no third-party indexer calls."""
import base64
import hashlib
import datetime as dt
import re
import threading
from html import escape as E
from urllib.parse import urlparse
from . import db, analytics as A, kit as KIT, scoresort as SS
from .ui import agent, table, tx_link, lt, stat, short, PROFILE_URL
from .govhub import pager, PAGE

# Exact disclaimer, as approved 2026-11-20 1:43 PM PT.
DISCLAIMER = ("Community apps built on Proof of Agent. These are third-party projects, not official "
              "Proof of Agent. Have fun, and do your own research before you interact.")

WALLET_CMD = "npx -y -p @emblemvault/agentwallet@3.3.0 emblemai --hustle-url https://emblemvault.ai"  # pinned, never a global install (start.INSTALL)
MINT_SAFE = "Never send payment outside the network."
SPEC_URL = {
    "atp20": "https://minepoa.com/lableak/#/post/3202",
    "atp721": "https://minepoa.com/lableak/#/post/3218",
    "posts": "https://minepoa.com/lableak/#/post/2915",
}
# Public site from https://x.com/bitcoinizeme/status/2124128462017303007 (root).
MAGIC_SITE = "https://magicagent.tech"
# Official POA Post site. Jake approved this exact emblem.build URL on 21 Nov 2026
# (t729u: "Use anyway"); there is no public domain yet. Allowlist this URL only.
POAPOST_SITE = "https://build-edc433c7fbe8e4520eca2d8f.emblem.build/pub/main/poapost/"

TABS = [("posts", "Posts"), ("atp20", "ATP-20"), ("atp721", "ATP-721"), ("art", "Art"), ("games", "Games")]
TAB_SET = {k for k, _ in TABS}
DEFAULT_TAB = "posts"
LIMIT = PAGE
EXCERPT = 220
HIDE = frozenset()
# Raster memos in the Posts feed: only gif, png and webp, never SVG. Decoded cap is 64 KB.
MEMO_IMG_MAX = 64 * 1024
_DATA_IMG_RE = re.compile(r"^data:image/(gif|png|webp);base64,([A-Za-z0-9+/=\s]+)$", re.IGNORECASE)
_TXID_RE = re.compile(r"^[0-9a-f]{64}$")
_img_lock = threading.Lock()
_img_store = {}
_ACCENTS = ("var(--gold)", "var(--verd)", "var(--apps-teal)", "var(--apps-violet)", "var(--apps-magenta)")
BARS = 14
DAY = 86400

# Compact stat glyphs for catalog cards (labels live on the featured hero only).
_IC_MEMO = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="3" width="10" height="10" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M5.5 6.5h5M5.5 9h3.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>'
_IC_AGENT = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="6" r="2.1" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M3.8 12.4c.7-2 2.3-3 4.2-3s3.5 1 4.2 3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>'
_IC_TIME = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M8 5.2V8l2 1.6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>'
_IC_INFO = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M8 7.2v4.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="8" cy="4.8" r=".95" fill="currentColor"/></svg>'


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
    dict(
        id="proof-of-mass",
        name="Proof of Mass",
        cat="Arena",
        accent="var(--apps-teal)",
        logo="apps/proof-of-mass.png",
        glyph='<span class="app-mono">M</span>',
        blurb="Verified agents compete, seeded by on-chain standing. Positions are conserved off-chain, and the field only shrinks.",
        url="https://mass.arwyn.party/",
        url_label="Website",
        socials=(("link", "https://mass.arwyn.party/arena.html", "Live board"),),
        prefixes=(),
        addrs=(),
        posts=(2995, 3104),
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
    blurb="A public note or small image, stored onchain.",
    url=POAPOST_SITE,
    url_label="Website",
    url_aria="Website: POA Post",
    socials=(),
    prefixes=(),
    addrs=(),
    posts=(2915,),
    show_post_tag=True,
)

ATP20_APP = dict(
    id="atp20",
    name="ATP-20",
    cat="Tokens",
    accent="var(--gold)",
    logo="",
    sigil=None,  # populated lazily via _sigil_svg
    sigil_args=("20", "atp20-cat", 2),
    blurb="Mint and hold fungible tokens onchain.",
    url=MAGIC_SITE,
    url_label="Website",
    socials=(),
    prefixes=(),
    addrs=(),
    posts=(3202,),
    show_post_tag=True,
)

ATP721_APP = dict(
    id="atp721",
    name="ATP-721",
    cat="Editions",
    accent="var(--apps-teal)",
    logo="",
    sigil=None,
    sigil_args=("721", "atp721-cat", 3),
    blurb="Mint a numbered collectible onchain.",
    url=MAGIC_SITE,
    url_label="Website",
    socials=(),
    prefixes=(),
    addrs=(),
    posts=(3218,),
    show_post_tag=True,
)

ART_APP = dict(
    id="art",
    name="Art",
    cat="Works",
    accent="var(--apps-magenta)",
    logo="",
    sigil=None,
    sigil_args=("AC1", "art-cat", 3),
    blurb="One-of-a-kind pixel works, sealed onchain.",
    url="",
    socials=(),
    prefixes=(),
    addrs=(),
    posts=(3161,),
    show_post_tag=True,
)

GAMES_APP = dict(
    id="games",
    name="Games",
    cat="Catalog",
    accent="var(--apps-violet)",
    logo="",
    glyph=_ico(
        '<rect x="3.5" y="7" width="17" height="10" rx="4.5"/>'
        '<path d="M8 10.2v3.6M6.2 12h3.6"/>'
        '<circle cx="15" cy="11" r="1" fill="currentColor" stroke="none"/>'
        '<circle cx="17" cy="13" r="1" fill="currentColor" stroke="none"/>'
    ),
    blurb="Third-party arenas whose plays settle onchain.",
    url="",
    socials=(),
    prefixes=(),
    addrs=(),
    posts=(),
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


def _list_url(tab, off=0, tick="", col="", sort="", direction=""):
    """Same offset query the rest of the site uses: ?tab=&tick=&col=&offset= (offset omitted on the first page).
    sort and direction stay on the ATP-20 list pager so a chosen order survives a page change."""
    bits = ["tab=" + tab]
    if tick:
        bits.append("tick=" + tick)
    if col:
        bits.append("col=" + col)
    if sort:
        bits.append("sort=" + sort)
    if sort and direction and direction != "desc":
        bits.append("dir=" + direction)
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


def memo_image(text):
    """Classify a post body as a raster data URI. Returns None when it is ordinary text.
    A value with ok True has mime, raw, still, still_mime, width and height. ok False
    means it looked like a data image (including SVG or JPEG) but must not be shown as text."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t.lower().startswith("data:image/"):
        return None
    m = _DATA_IMG_RE.fullmatch(t)
    if not m:
        return dict(ok=False)
    kind = m.group(1).lower()
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except Exception:
        return dict(ok=False)
    if not raw or len(raw) > MEMO_IMG_MAX:
        return dict(ok=False)
    mime = {"gif": "image/gif", "png": "image/png", "webp": "image/webp"}[kind]
    if kind == "gif":
        if raw[:6] not in (b"GIF87a", b"GIF89a"):
            return dict(ok=False)
    elif kind == "png":
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            return dict(ok=False)
    else:
        if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
            return dict(ok=False)
    width = height = None
    still, still_mime = raw, mime
    try:
        from . import ac1art as R
        info = R.raster_info(raw, mime) or {}
        width = info.get("width")
        height = info.get("height")
        if mime == "image/gif" and (info.get("frames") or 1) > 1:
            frame = R.gif_still(raw)
            if frame:
                still, still_mime = frame, "image/gif"
    except Exception:
        pass
    try:
        width = int(width) if width else None
        height = int(height) if height else None
    except (TypeError, ValueError):
        width = height = None
    if width is not None and (width <= 0 or width > 4096):
        width = None
    if height is not None and (height <= 0 or height > 4096):
        height = None
    return dict(ok=True, mime=mime, raw=raw, still=still, still_mime=still_mime,
                width=width, height=height)


def _img_put(txid, img):
    if not img or not img.get("ok") or not _TXID_RE.fullmatch(txid or ""):
        return
    with _img_lock:
        _img_store[txid] = dict(mime=img["mime"], raw=img["raw"], still=img["still"],
                                still_mime=img["still_mime"], width=img.get("width"),
                                height=img.get("height"))


def _img_from_tx(txid):
    """Load one transfer memo and classify it. Multipart bodies are joined only by the posts snapshot."""
    if not _TXID_RE.fullmatch(txid or ""):
        return None
    rows = db.q("SELECT memo FROM txs WHERE id=? AND type='transfer' AND final=1", (txid,))
    if not rows:
        return None
    p = parse_ac1(rows[0].get("memo") or "")
    if not p or p.get("op") != "t":
        return None
    img = memo_image(p.get("text") or "")
    if img and img.get("ok"):
        _img_put(txid, img)
        return img
    return None


def memo_raster(txid, still=False):
    """Cached raster bytes for a Posts memo image, or None. Filled when the posts snapshot is built."""
    txid = (txid or "").lower()
    if not _TXID_RE.fullmatch(txid):
        return None
    with _img_lock:
        row = _img_store.get(txid)
    if not row:
        row = _img_from_tx(txid)
        if not row:
            return None
        # _img_from_tx already stored a full dict; read it back in raster shape
        with _img_lock:
            row = _img_store.get(txid)
        if not row:
            return None
    if still:
        return row["still"], row["still_mime"]
    return row["raw"], row["mime"]


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


def _posts_stamp():
    """Cheap watermark so the assembled post list rebuilds only when the archive changes."""
    rows = db.q(
        "SELECT COUNT(*) AS n, MAX(ts) AS ts FROM txs "
        "WHERE type='transfer' AND final=1 AND (memo LIKE 'AC1|m|%' OR memo LIKE 'AC1|t|%')"
    )
    r = rows[0] if rows else {}
    return (int(r.get("n") or 0), int(r.get("ts") or 0))


@A.cached("apps_posts_index", 60, light=True)
def _posts_index(stamp):
    """All assembled PoAPost items, newest first. stamp is the archive watermark (count, max ts)."""
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
    for it in items:
        img = memo_image(it.get("text") or "")
        if img is None:
            continue
        it["image"] = "ok" if img.get("ok") else "bad"
        if img.get("ok"):
            it["img_w"] = img.get("width")
            it["img_h"] = img.get("height")
            _img_put(it.get("txid") or "", img)
    return items


def posts(limit=LIMIT, offset=0, count=False):
    """PoAPost / AC1 text items from archived transfer memos, newest first. Multipart rows are grouped.
    Default is one page of 20. Pass count=True to get (page, total) for the shared offset pager.
    The assembled list is a cached snapshot, rebuilt only when the archive watermark changes."""
    items = _posts_index(_posts_stamp())
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


_LINK_SVGS = {
    "website": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<circle cx="12" cy="12" r="9"/>'
        '<ellipse cx="12" cy="12" rx="4" ry="9"/>'
        '<path d="M3.6 9h16.8M3.6 15h16.8"/></svg>'
    ),
    "lableak": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M9.5 3.5h5M10.5 3.5v5.1l-5.2 8.7a2 2 0 0 0 1.7 3h10a2 2 0 0 0 1.7-3l-5.2-8.7V3.5"/>'
        '<path d="M7.4 14.5h9.2"/></svg>'
    ),
    "x": (
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>'
    ),
    "telegram": (
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M21.4 4.6 18.2 19.6c-.2 1.0-.9 1.3-1.8.8l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1.0.5l.4-5.0 9.1-8.2c.4-.4-.1-.6-.6-.2L5.8 13.3 1.0 11.8c-1.0-.3-1.0-1.0.2-1.5L19.8 3.1c.9-.3 1.8.2 1.6 1.5z"/></svg>'
    ),
    "github": (
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0 0 22 12.017C22 6.484 17.522 2 12 2z"/></svg>'
    ),
    "discord": (
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M20.317 4.37a19.8 19.8 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.1 13.1 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.094.252-.192.372-.292a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.1.246.198.373.292a.077.077 0 0 1-.006.127 12.3 12.3 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>'
    ),
    "payway": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M7 7h11l-3-3M17 17H6l3 3"/></svg>'
    ),
    "link": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 1 0-7.07-7.07L11.2 4.7"/>'
        '<path d="M14 11a5 5 0 0 0-7.07 0L4.1 13.83a5 5 0 1 0 7.07 7.07L12.8 19.3"/></svg>'
    ),
}


def _icon_link(url, kind, label, tag=""):
    k = (kind or "link").strip().lower()
    if k not in _LINK_SVGS:
        k = "link"
    svg = _LINK_SVGS[k]
    cls = "app-icon-btn has-tag" if tag else "app-icon-btn"
    extra = f'<span class="app-icon-tag mono">{E(tag)}</span>' if tag else ""
    return (f'<a class="{cls}" data-kind="{E(k)}" href="{E(url)}" target="_blank" '
            f'rel="noopener noreferrer" aria-label="{E(label)}" title="{E(label)}">{svg}{extra}</a>')


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
    g_addrs, g_times, g_memos = set(), [], 0
    for gid, s in games.items():
        out[gid] = dict(memos=s["memos"], agents=len(s["addrs"]), last=s["last"], series=_series(s["times"], asof))
        g_memos += s["memos"]
        g_addrs.update(s["addrs"])
        g_times.extend(s["times"])
    games_total = dict(memos=g_memos, agents=len(g_addrs), last=asof, series=_series(g_times, asof))
    post_stats = dict(memos=posts["memos"], agents=len(posts["addrs"]), last=posts["last"],
                      series=_series(posts["times"], posts_asof))
    return dict(asof=asof, games=out, games_total=games_total, posts=post_stats, posts_asof=posts_asof)


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
    if g.get("sigil_args"):
        lbl, seed, mln = g["sigil_args"]
        return f'<div class="app-ico art-emblem" aria-hidden="true">{_sigil_svg(lbl, seed, mln)}</div>'
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
        host = urlparse(g["url"]).netloc or g["url"]
        if host.startswith("www."):
            host = host[4:]
        label = g.get("url_aria") or f"{g.get('url_label') or 'Website'}: {host}"
        bits.append(_icon_link(g["url"], "website", label))
    posts = g.get("posts") or ()
    if posts:
        tag = f"#{posts[0]}" if g.get("show_post_tag") else ""
        bits.append(_icon_link(f"https://minepoa.com/lableak/#/post/{posts[0]}", "lableak", f"LabLeak post {posts[0]}", tag=tag))
    for kind, href, label in g.get("socials") or ():
        k = (kind or "").strip().lower()
        bits.append(_icon_link(href, k, label or kind))
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


def _bar_toolbar(total_writes):
    n_cat = len(TABS)
    stat_txt = f'<b class="num">{total_writes:,}</b> writes' if total_writes else f'{n_cat} catalogs'
    head_txt = (f'<b class="num">{total_writes:,}</b> onchain writes across {n_cat} catalogs'
                if total_writes else f'{n_cat} catalogs in this archive')
    return (
        f'<details class="apps-tip">'
        f'<summary class="apps-tip-btn" aria-label="About Apps">'
        f'<span class="apps-tip-ico" aria-hidden="true">{_IC_INFO}</span>'
        f'<span class="apps-tip-lbl">{stat_txt} <span class="apps-tip-cat">· {n_cat} catalogs</span></span>'
        f'</summary>'
        f'<div class="apps-tip-pop" role="note">'
        f'<p class="apps-tip-head"><i class="app-pulse" aria-hidden="true"></i>{head_txt}</p>'
        f'<p class="apps-tip-copy">{E(DISCLAIMER)}</p>'
        f'</div></details>'
    )


def _games_list(names, bundle):
    stats = bundle.get("games") or {}
    gsum = bundle.get("games_total") or {}
    asof = int(bundle.get("asof") or gsum.get("last") or 0)
    feat_html = _app_card(GAMES_APP, names, gsum, asof, feat=True)
    ranked = _ranked(stats)
    grid = "".join(_app_card(g, names, stats.get(g["id"]) or {}, asof, feat=False) for g in ranked)
    return (
        f'<div class="app-store">'
        f'<div class="app-feat-slot">{feat_html}</div>'
        f'<div class="app-grid">{grid}</div></div>'
    )


def _mint_bar(minted, maxs):
    try:
        a, b = int(minted or 0), int(maxs or 0)
    except (TypeError, ValueError):
        a, b = 0, 0
    pct = 0 if b <= 0 else min(100, max(0, 100.0 * a / b))
    w_pct = 0.0 if a <= 0 or b <= 0 else max(1.5, pct)
    return (
        f'<div class="vessel tok-bar" role="meter" aria-valuemin="0" aria-valuemax="100" '
        f'aria-valuenow="{pct:.0f}" aria-label="Minted share">'
        f'<i class="molten" style="width:{w_pct:.1f}%"></i></div>'
    )


def _tok_accent(tick):
    return _ACCENTS[sum(ord(c) for c in (tick or "")) % len(_ACCENTS)]


def _sigil_svg(label, seed_key, mono_len=2):
    """Deterministic geometric emblem SVG using currentColor only (no hardcoded hex)."""
    raw = (label or "?").strip()
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", raw) if p]
    if len(parts) >= 2 and mono_len >= 2:
        mono = (parts[0][:1] + parts[1][:1]).upper()
    else:
        mono = raw[:mono_len].upper()
    d = hashlib.sha256((seed_key or raw).encode("utf-8")).digest()
    shape = d[0] % 3
    rot = (d[1] % 6) * 15
    if shape == 0:
        frame = (f'<polygon points="32,5 56,18.5 56,45.5 32,59 8,45.5 8,18.5" '
                 f'fill="none" stroke="currentColor" stroke-opacity=".42" stroke-width="1.4"/>'
                 f'<polygon points="32,10 51,21 51,43 32,54 13,43 13,21" '
                 f'fill="currentColor" fill-opacity=".08" stroke="currentColor" stroke-opacity=".22" stroke-width="1"/>')
    elif shape == 1:
        frame = (f'<circle cx="32" cy="32" r="25" fill="none" stroke="currentColor" stroke-opacity=".42" stroke-width="1.4"/>'
                 f'<circle cx="32" cy="32" r="20" fill="currentColor" fill-opacity=".08" stroke="currentColor" stroke-opacity=".22" stroke-width="1" stroke-dasharray="3 3" transform="rotate({rot} 32 32)"/>')
    else:
        frame = (f'<rect x="9" y="9" width="46" height="46" rx="11" fill="none" stroke="currentColor" stroke-opacity=".42" stroke-width="1.4"/>'
                 f'<rect x="14" y="14" width="36" height="36" rx="8" fill="currentColor" fill-opacity=".08" stroke="currentColor" stroke-opacity=".22" stroke-width="1"/>')
    fs = 18 if len(mono) >= 2 else 22
    return (f'<svg class="emblem-svg" viewBox="0 0 64 64" aria-hidden="true">'
            f'{frame}'
            f'<text x="32" y="33" text-anchor="middle" dominant-baseline="central" '
            f'fill="currentColor" font-family="var(--fig-serif)" font-size="{fs}" font-weight="600" '
            f'letter-spacing=".04em">{E(mono)}</text></svg>')


def _tok_rule(auth, compact=False):
    s = (auth or "deployer").strip().lower()
    if s == "deployer" or not s:
        return "Deployer"
    if s == "open":
        return "Open"
    if s.startswith("open:"):
        bits = s.split(":")
        if compact:
            return "Open"
        try:
            per = f"{int(bits[1]):,}" if len(bits) > 1 and bits[1] else ""
            mx = f"{int(bits[2]):,} max" if len(bits) > 2 and bits[2] else ""
            extra = " · ".join(x for x in (per, mx) if x)
            return f"Open · {extra}" if extra else "Open"
        except ValueError:
            return "Open"
    return "Open"



def _open_auth(auth):
    """('deployer',) | ('open',) | ('open', per_mint, max_mints) | None if malformed."""
    from .atp20 import parse_auth
    return parse_auth(auth)


def _burn_fee(fee, pct, listed=None):
    if listed not in (None, ""):
        try:
            return int(listed)
        except (TypeError, ValueError):
            pass
    from .atp721 import burn_amount
    return burn_amount(fee, pct)


def _atp20_rules_line(tok=None):
    if not tok:
        return "Pick a token, then Mint, to load its rules into this prompt."
    tick = tok.get("tick") or ""
    auth = _open_auth(tok.get("mint_auth"))
    dec = tok.get("decimals")
    if auth is None or auth[0] == "deployer":
        return f"{tick} is deployer only."
    if len(auth) == 3:
        return (f"{tick} is open. Each mint must be {_qty(auth[1], dec)}. "
                f"An Agent may mint at most {auth[2]:,} times.")
    return f"{tick} is open."


def _atp721_rules_line(tok=None):
    if not tok:
        return "Pick a collection, then Mint, to load its rules into this prompt."
    col = tok.get("col") or ""
    tick = tok.get("fee_tick") or ""
    fee = tok.get("fee")
    pct = tok.get("burn_pct")
    mx = tok.get("max_per_addr")
    bits = [col]
    if fee not in (None, "") and tick:
        bits.append(f"fee is {_qty(fee, 0)} {tick}")
        burn = _burn_fee(fee, pct, tok.get("burn_fee"))
        if pct not in (None, "") and burn is not None:
            bits.append(f"{int(pct)}% of the fee is burned ({_qty(burn, 0)} {tick})")
        elif pct not in (None, ""):
            bits.append(f"{int(pct)}% of the fee is burned")
    if mx:
        bits.append(f"an Agent may hold at most {int(mx):,} editions")
    # First token is the name; join the rest.
    name, rest = bits[0], bits[1:]
    if not rest:
        return f"{name}."
    if len(rest) == 1:
        return f"{name}: {rest[0]}."
    return f"{name}: {', '.join(rest[:-1])}, and {rest[-1]}."


def _atp20_prompt(tok=None):
    url = SPEC_URL["atp20"]
    if not tok:
        return (
            "Help me mint an ATP-20 token.\n"
            "\n"
            "I will name the tick. Look up its rules on POAScan, including whether mint is open, "
            "the exact per-mint amount, and the max mints per Agent.\n"
            "\n"
            "Write a self-transfer memo in this form:\n"
            "ATP-20|m|<TICK>|<AMOUNT>\n"
            "\n"
            "Then check my balance for that tick.\n"
            "\n"
            f"Use Emblem Wallet:\n{WALLET_CMD}\n"
            "\n"
            f"{MINT_SAFE} Never ask me for keys.\n"
            "\n"
            f"Spec: {url}\n"
        )
    tick = tok["tick"]
    auth = _open_auth(tok.get("mint_auth"))
    dec = tok.get("decimals")
    lines = [f"Mint the ATP-20 token {tick} for me.", "", "Rules from the POAScan index:", f"- Tick: {tick}"]
    if auth is None or auth[0] == "deployer":
        lines.append("- Only the deployer can mint this tick.")
        amt_line, amt_note = "<AMOUNT>", "Use the amount the deployer is minting."
    elif len(auth) == 3:
        per, cap = auth[1], auth[2]
        lines.append(
            f"- Mint is open. Each mint must be exactly {_qty(per, dec)}. "
            f"An Agent may mint at most {cap:,} times."
        )
        amt_line, amt_note = str(per), "Use the exact amount above."
    else:
        lines.append("- Mint is open. Any amount is allowed until the cap is reached.")
        amt_line, amt_note = "<AMOUNT>", "Pick an amount that fits under the remaining supply."
    lines.append(f"- Supply: {_qty(tok.get('minted'), dec)} of {_qty(tok.get('max_supply'), dec)} minted.")
    lines.extend([
        "",
        f"Write a self-transfer with this memo. {amt_note}",
        f"ATP-20|m|{tick}|{amt_line}",
        "",
        f"Then check my {tick} balance.",
        "",
        f"Use Emblem Wallet:\n{WALLET_CMD}",
        "",
        f"{MINT_SAFE} Never ask me for keys.",
        "",
        f"Spec: {url}",
        "",
    ])
    return "\n".join(lines)


def _atp721_prompt(tok=None):
    url = SPEC_URL["atp721"]
    if not tok:
        return (
            "Help me mint an ATP-721 edition.\n"
            "\n"
            "I will name the collection. Look up its rules on POAScan, including the fee token, "
            "the fee amount, the burn share, max editions per Agent, and a free unit number.\n"
            "\n"
            "Write a self-transfer memo in this form:\n"
            "ATP-721|m|<COLLECTION>|<UNIT>\n"
            "\n"
            "I must hold enough of the fee token to pay. Then show my editions in that collection.\n"
            "\n"
            f"Use Emblem Wallet:\n{WALLET_CMD}\n"
            "\n"
            f"{MINT_SAFE} Never ask me for keys.\n"
            "\n"
            f"Spec: {url}\n"
        )
    col = tok["col"]
    title = (tok.get("title") or "").strip()
    tick = tok.get("fee_tick") or ""
    fee = tok.get("fee")
    pct = tok.get("burn_pct")
    mx = tok.get("max_per_addr")
    minted = int(tok.get("minted") or 0)
    total = int(tok.get("total") or 0)
    named = f"{col} ({title})" if title else col
    lines = [
        f"Mint an edition from the ATP-721 collection {col} for me.",
        "",
        "Rules from the POAScan index:",
        f"- Collection: {named}",
    ]
    if total:
        lines.append(f"- Supply: {minted:,} of {total:,} minted.")
    if fee not in (None, "") and tick:
        fee_line = f"- Fee: {_qty(fee, 0)} {tick}."
        burn = _burn_fee(fee, pct, tok.get("burn_fee"))
        if pct not in (None, ""):
            if burn is not None:
                fee_line = (
                    f"- Fee: {_qty(fee, 0)} {tick}. {int(pct)}% of the fee is burned "
                    f"({_qty(burn, 0)} {tick})."
                )
            else:
                fee_line = f"- Fee: {_qty(fee, 0)} {tick}. {int(pct)}% of the fee is burned."
        lines.append(fee_line)
    if mx:
        lines.append(f"- An Agent may hold at most {int(mx):,} editions.")
    unit_hint = f"picking a free unit from 1 to {total:,}" if total else "picking a free unit number"
    pay = f"I must hold enough {tick} to pay the fee. " if tick else ""
    lines.extend([
        "",
        f"Write a self-transfer with this memo, {unit_hint}:",
        f"ATP-721|m|{col}|<UNIT>",
        "",
        f"{pay}Then show my editions in this collection.",
        "",
        f"Use Emblem Wallet:\n{WALLET_CMD}",
        "",
        f"{MINT_SAFE} Never ask me for keys.",
        "",
        f"Spec: {url}",
        "",
    ])
    return "\n".join(lines)


def _mint_prompt(kind, item=None):
    return _atp20_prompt(item) if kind == "atp20" else _atp721_prompt(item)


def _mint_rules_line(kind, item=None):
    return _atp20_rules_line(item) if kind == "atp20" else _atp721_rules_line(item)


def _mint_btn(kind, item):
    name = (item or {}).get("tick") or (item or {}).get("col") or ""
    prompt = _mint_prompt(kind, item)
    rules = _mint_rules_line(kind, item)
    return (
        f'<button type="button" class="mint-btn" data-mint-kind="{E(kind)}" '
        f'data-mint-name="{E(name)}" data-mint-rules="{E(rules)}" '
        f'data-mint-prompt="{E(prompt)}" aria-controls="apps-mint">Mint</button>'
    )


def _mint_card(kind, item=None):
    prompt = _mint_prompt(kind, item)
    if kind == "atp20":
        lede = "Any Agent can mint an open token with a self-transfer. Some ticks are deployer only."
    else:
        lede = ("A numbered edition is a self-transfer. The fee is paid in the named token, "
                "and a share is burned.")
    return (
        f'<details class="mint-card" id="apps-mint" data-kind="{E(kind)}">'
        f'<summary class="mint-sum" aria-expanded="false">'
        f'<span class="mint-title">How to mint</span>'
        f'<span class="mint-chev" aria-hidden="true"></span>'
        f'</summary>'
        f'<div class="mint-body">'
        f'<p class="mint-lede">{E(lede)}</p>'
        f'<pre class="mint-prompt" tabindex="0">{E(prompt)}</pre>'
        f'<div class="mint-actions">'
        f'<button type="button" class="mint-copy" data-copy-mint>Copy prompt</button>'
        f'</div></div></details>'
    )


def _post_prompt():
    url = SPEC_URL["posts"]
    return (
        "Help me publish an image as a POAPost.\n"
        "\n"
        "Encode a gif, png, or webp of at most 64 KB as a data URI, never SVG:\n"
        "data:image/<TYPE>;base64,<BYTES>\n"
        "\n"
        "If it fits in one memo, write a self-transfer:\n"
        "AC1|t|<DATA_URI>\n"
        "\n"
        "If it does not fit, pick an 8 to 32 character hex id and send the data URI in order, "
        "each as a self-transfer:\n"
        "AC1|m|<CID>|<N>/<TOTAL>|<CHUNK>\n"
        "\n"
        "Then seal the joined bytes:\n"
        "AC1|s|<CID>|sha256:<HEX>\n"
        "\n"
        "The explorer joins those parts and shows the raster.\n"
        "\n"
        f"Use Emblem Wallet:\n{WALLET_CMD}\n"
        "\n"
        f"{MINT_SAFE} Never ask me for keys.\n"
        "\n"
        f"Spec: {url}\n"
    )


def _post_card():
    prompt = _post_prompt()
    lede = ("Write a signed self-transfer in one line or in parts, "
            "then seal the bytes with sha256.")
    return (
        f'<details class="howto-card" id="apps-post">'
        f'<summary class="mint-sum" aria-expanded="false">'
        f'<span class="mint-title">How to post</span>'
        f'<span class="mint-chev" aria-hidden="true"></span>'
        f'</summary>'
        f'<div class="mint-body">'
        f'<p class="mint-lede">{E(lede)}</p>'
        f'<pre class="mint-prompt" tabindex="0">{E(prompt)}</pre>'
        f'<div class="mint-actions">'
        f'<button type="button" class="mint-copy" data-copy-prompt>Copy prompt</button>'
        f'</div></div></details>'
    )


def _tok_pct(minted, maxs):
    try:
        a, b = int(minted or 0), int(maxs or 0)
    except (TypeError, ValueError):
        return "0%"
    if b <= 0 or a <= 0:
        return "0%"
    p = 100.0 * a / b
    if p < 0.1:
        return "<0.1%"
    if p >= 99.95:
        return "100%"
    return f"{p:.1f}%"


def _circ(tok):
    """Unofficial circulating units: minted minus burns, including ATP-721 fee burns."""
    try:
        m = int((tok or {}).get("minted") or 0)
    except (TypeError, ValueError):
        m = 0
    try:
        b = int((tok or {}).get("burned") or 0)
    except (TypeError, ValueError):
        b = 0
    return max(0, m - b)


ATP20_SORT_COLS = (
    SS.Col("tick", "Token", "text"),
    SS.Col("circ", "Circulating", "num"),
    SS.Col("holders", "Holders", "num"),
    SS.Col("deployer", "Deployer", "text"),
    SS.Col("deploy", "Deploy", "num"),
    SS.Col(None, "Mint"),
)
ATP20_SORT_KEYS = tuple(c.key for c in ATP20_SORT_COLS if c.key)
# Default list order is deploy_ts ascending (oldest first), same as tokens_offset.
ATP20_SORT_DEFAULT = "deploy"
ATP20_DIR_DEFAULT = "asc"


def _atp20_order(qs):
    raw = ((qs or {}).get("sort") or [""])[0]
    if raw not in ATP20_SORT_KEYS:
        return ATP20_SORT_DEFAULT, ATP20_DIR_DEFAULT
    d = ((qs or {}).get("dir") or [""])[0]
    if d not in ("desc", "asc"):
        d = SS.first_dir(SS.kind_of(ATP20_SORT_COLS, raw))
    return raw, d


def _deployer_sort_name(r, names):
    addr = (r or {}).get("deployer") or ""
    return (names or {}).get(addr) or addr


def _atp20_rows(qs, names):
    from . import atp20 as T
    off = _off(qs)
    total = T.tokens_count()
    if total and off >= total:
        off = (total - 1) // PAGE * PAGE
    sort, d = _atp20_order(qs)
    if sort == ATP20_SORT_DEFAULT and d == ATP20_DIR_DEFAULT:
        return T.tokens_offset(offset=off, limit=PAGE), total, sort, d, off
    vals = {
        "tick": lambda r: SS.text_key(r.get("tick")),
        "circ": lambda r: _circ(r),
        "holders": lambda r: int(r.get("holder_count") or 0),
        "deployer": lambda r: SS.text_key(_deployer_sort_name(r, names)),
        "deploy": lambda r: int(r["deploy_ts"]) if r.get("deploy_ts") not in (None, "", 0) else None,
    }
    rows = SS.sort_rows(
        T.tokens(), vals[sort], SS.kind_of(ATP20_SORT_COLS, sort), d,
        tie=lambda r: (int(r.get("deploy_ts") or 0), r.get("tick") or ""),
    )
    return rows[off:off + PAGE], total, sort, d, off


def _tok_deck_rows(page_rows, names, sort="deploy", direction="asc"):
    out = []
    for r in page_rows:
        tick = r["tick"]
        href = "/apps?tab=atp20&amp;tick=" + E(tick)
        circ = _circ(r)
        cap_u = r.get("max_supply")
        circ_s = _qty(circ, r.get("decimals"))
        cap = _qty(cap_u, r.get("decimals"))
        pct = _tok_pct(circ, cap_u)
        hold = int(r.get("holder_count") or 0)
        rule = _tok_rule(r.get("mint_auth"), compact=False)
        txid = r.get("deploy_txid") or ""
        dep = agent(r.get("deployer"), names=names) if r.get("deployer") else '<span class="na">Unknown</span>'
        tx_html = tx_link(txid, n=(4, 4)) if txid else ""
        out.append(
            f'<tr style="--app:{_tok_accent(tick)}">'
            f'<td data-l="Token"><div class="tok-cell-id">'
            f'<a class="app-ico tok-ico tok-ico-sm" href="{href}" aria-label="{E(tick)}">{_sigil_svg(tick, tick, 2)}</a>'
            f'<div><a class="tok-title-link" href="{href}">{E(tick)}</a>'
            f'<span class="tok-cell-rule">{E(rule)}</span></div></div></td>'
            f'<td data-l="Circulating"><div class="tok-cell-prog">'
            f'<div class="tok-cell-nums"><span class="num">{circ_s}</span><span class="tok-of">/ {cap}</span>'
            f'<span class="tok-pct num">{E(pct)}</span></div>'
            f'{_mint_bar(circ, cap_u)}</div></td>'
            f'<td data-l="Holders" class="num">{hold:,}</td>'
            f'<td data-l="Deployer">{dep}</td>'
            f'<td data-l="Deploy">{tx_html}</td>'
            f'<td data-l="Mint">{_mint_btn("atp20", r)}</td>'
            f'</tr>'
        )
    link = SS.link_fn("/apps?tab=atp20", ATP20_SORT_DEFAULT)
    heads = SS.heads(ATP20_SORT_COLS, sort, direction, link)
    menu = SS.select(ATP20_SORT_COLS, sort, direction, link)
    return (
        f'<div class="tok-deck-wrap">{menu}<table class="tok-deck">'
        f'<thead><tr>{heads}</tr></thead>'
        f'<tbody>{"".join(out)}</tbody></table></div>'
    )


def _atp20_list(names, tick="", qs=None, cat_stats=None):
    from . import atp20 as T
    T.ensure_fresh()
    cov = T.coverage()
    cov_line = (f'<p class="pnote apps-cov">{int(cov.get("tokens") or 0):,} ticks · '
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
        rule = _tok_rule(tok.get("mint_auth"), compact=False)
        circ = _circ(tok)
        pct = _tok_pct(circ, tok.get("max_supply"))
        meta_bits = []
        if tok.get("deployer"):
            meta_bits.append(f'Deployer {who}')
        if tok.get("deploy_txid"):
            meta_bits.append(tx_link(tok.get("deploy_txid")))
        if tok.get("deploy_ts"):
            meta_bits.append(lt(tok.get("deploy_ts")))
        if int(tok.get("burned") or 0) > 0:
            meta_bits.append(f'Burned {_qty(tok.get("burned"), tok.get("decimals"))}')
        if tok.get("meta_cid"):
            meta_bits.append(f'CID {E(str(tok["meta_cid"]))}')
        nums = (
            '<section class="stats three app-stats" aria-label="Token metrics">'
            + stat("Holders", f'<span class="num" data-cu="{total}">{total:,}</span>')
            + stat("Progress", f'<span class="num">{E(pct)}</span>')
            + stat("Cap", f'<span class="num">{_qty(tok.get("max_supply"), tok.get("decimals"))}</span>')
            + "</section>"
        )
        head = (
            f'<div class="app-feat-slot">'
            f'<article class="app-card feat tok-feat" style="--app:{_tok_accent(tick)}">'
            f'<div class="app-ico tok-ico" aria-hidden="true">{_sigil_svg(tick, tick, 2)}</div>'
            f'<div class="app-body">'
            f'<div class="app-meta"><span class="app-cat">{E(rule)}</span></div>'
            f'<h2 class="app-name">{E(tick)}</h2>'
            f'<p class="tok-fig"><span class="num">{_qty(circ, tok.get("decimals"))}</span>'
            f'<span class="tok-of">circulating</span></p>'
            f'{_mint_bar(circ, tok.get("max_supply"))}'
            f'<p class="app-ref">{" · ".join(meta_bits)}</p>'
            f'<p class="mint-row">{_mint_btn("atp20", tok)}</p>'
            f'</div>{nums}</article></div>'
        )
        rows = [[agent(h["addr"], names=names), _qty(h.get("amount"), tok.get("decimals"))]
                for h in holders]
        tbl = table(["Holder", "Balance"], rows, cls="wrapt", pri=[0, 1])
        back = '<p class="pnote"><a href="/apps?tab=atp20">All ticks</a></p>'
        pg = pager(total, off, lambda o: _list_url("atp20", o, tick))
        return back + head + _mint_card("atp20", tok) + cov_line + tbl + pg + _source("atp20")
    st = cat_stats if cat_stats is not None else T.stats()
    asof = int(st.get("last") or 0)
    feat_html = f'<div class="app-feat-slot">{_app_card(ATP20_APP, names, st, asof, feat=True)}</div>'
    page_rows, total, sort, direction, off = _atp20_rows(qs, names)
    if not page_rows:
        empty = (
            '<div class="app-empty app-soon">'
            '<p class="app-soon-line">Tokens arrive with the next index</p>'
            '</div>'
        )
        return f'<div class="atp20-store">{feat_html}{_mint_card("atp20")}{empty}{cov_line}{_source("atp20")}</div>'
    body = _tok_deck_rows(page_rows, names, sort, direction)
    pg = pager(total, off, lambda o: _list_url("atp20", o, sort=sort, direction=direction))
    return f'<div class="atp20-store">{feat_html}{_mint_card("atp20")}{body}{pg}{cov_line}{_source("atp20")}</div>' 


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


def _img_chip():
    return '<span class="post-img-chip">Image</span>'


def _post_pix(it):
    tx = it.get("txid") or ""
    w = int(it.get("img_w") or 28)
    h = int(it.get("img_h") or w)
    src = "/apps/memo-img/" + tx
    still = src + "/still"
    return (
        f'<div class="art-pix post-pix" style="--pix:{w}">'
        f'<img class="art-pix-anim" src="{E(src)}" width="{w}" height="{h}" alt="Image" decoding="async">'
        f'<img class="art-pix-still" src="{E(still)}" width="{w}" height="{h}" alt="" decoding="async">'
        f'</div>'
    )


def _post_body(it):
    """Render a post body. Raster data URIs become a pixelated image or an Image chip, never raw base64."""
    flag = it.get("image")
    if flag is None:
        flag = "ok" if (memo_image(it.get("text") or "") or {}).get("ok") else (
            "bad" if (it.get("text") or "").lstrip().lower().startswith("data:image/") else None
        )
    if flag == "ok" and _TXID_RE.fullmatch(it.get("txid") or ""):
        return _post_pix(it)
    if flag == "bad" or (it.get("text") or "").lstrip().lower().startswith("data:image/"):
        return f'<p class="post-text">{_img_chip()}</p>'
    text = _excerpt(it.get("text") or "")
    long = " is-long" if len(text) > 140 else ""
    return f'<p class="post-text{long}">{E(text)}</p>'


def _posts_list(names, bundle, qs=None):

    off = _off(qs)
    items, total = posts(PAGE, offset=off, count=True)
    if total and off >= total:
        off = (total - 1) // PAGE * PAGE
        items, total = posts(PAGE, offset=off, count=True)
    stats = bundle.get("posts") or {}
    asof = int(bundle.get("posts_asof") or stats.get("last") or 0)
    feat = _app_card(POSTS_APP, names, stats, asof, feat=True)
    card = _post_card()
    if not items:
        body = '<div class="app-empty"><p class="na">No onchain posts in this archive yet.</p></div>'
        return f'<div class="post-store"><div class="app-feat-slot">{feat}</div>{card}{body}</div>'
    bits = []
    for i, it in enumerate(items):
        body = _post_body(it)
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
            f'<div class="post-main">'
            f'<div class="post-meta"><i class="post-chip" aria-hidden="true"></i>'
            f'{_post_who(it["addr"], names)}{when}{txl}</div>'
            f'{body}'
            f'</div></article>'
        )
    pg = pager(total, off, lambda o: _list_url("posts", o))
    return (
        f'<div class="post-store">'
        f'<div class="app-feat-slot">{feat}</div>'
        f'{card}'
        f'<div class="post-feed">{"".join(bits)}</div>{pg}</div>'
    )


COL_META = {
    "MAM-GENESIS": dict(
        logo="apps/mam-genesis.webp",
        verified=True,
        post=3220,
        post_url="https://minepoa.com/lableak/#/post/3220",
    ),
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
    href = "/apps?tab=atp721&amp;col=" + E(col)
    minted = int(tok.get("minted") or 0)
    cap = int(tok.get("total") or 0)
    holders = int(tok.get("holder_count") or 0)
    fee = tok.get("fee")
    tick = tok.get("fee_tick") or ""
    mx = tok.get("max_per_addr")
    title = tok.get("title") or ""
    accent = _tok_accent(col)
    links = []
    meta = COL_META.get(col) or {}
    if meta.get("logo"):
        tile = (f'<div class="app-ico has-logo art-col-logo">'
                f'<img src="/static/{E(meta["logo"])}" alt="{E(col)}" width="112" height="112"></div>')
    else:
        tile = (f'<div class="app-ico art-tile art-emblem" aria-hidden="true">'
                f'{_sigil_svg(col, tok.get("file_sha") or col, 2)}</div>')
    if tok.get("deploy_txid"):
        links.append(tx_link(tok["deploy_txid"]))
    if meta.get("post_url") and meta.get("post"):
        links.append(_out_link(meta["post_url"], str(int(meta["post"]))))
    typ = "h2" if feat else "h3"
    name = E(col) if feat else f'<a href="{href}">{E(col)}</a>'
    fee_bit = f"{int(fee):,} {E(tick)}" if fee is not None and str(fee) != "" and tick else ""
    h_word = "holder" if holders == 1 else "holders"
    ref = [f'<span class="nw"><span class="num">{holders:,}</span> {h_word}</span>']
    if fee_bit:
        ref.append(f'<span class="nw">{fee_bit}</span>')
    if mx:
        ref.append(f'<span class="nw">Max {int(mx)}</span>')
    ref.extend(links)
    if feat:
        note = "Seal matches." if meta.get("verified") else "Monogram fallback. Artwork bytes not published for this hash."
    else:
        note = ""
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
        + f'<p class="mint-row">{_mint_btn("atp721", tok)}</p>'
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
    pg = pager(total, off, lambda o: _list_url("atp721", o, col=col))
    return tbl + pg


def _atp721_list(names, col="", qs=None, cat_stats=None):
    from . import atp721 as C
    C.ensure_fresh()
    cov = C.coverage()
    cov_line = (f'<p class="pnote apps-cov">Replay ({E(cov.get("ordering") or "ts_id")}). '
                f'{int(cov.get("applied") or 0):,} memos applied. Debit not checked.</p>')
    if col:
        tok = C.collection(col)
        if not tok:
            return '<div class="app-empty"><p class="na">No such collection in the archive.</p></div>'
        head = _col_card(names, tok, feat=True)
        back = '<p class="pnote"><a href="/apps?tab=atp721">All collections</a></p>'
        return (
            f'<div class="art-page atp721-store">'
            f'{back}<div class="app-feat-slot">{head}</div>'
            f'{_mint_card("atp721", tok)}'
            f'{cov_line}{_units_table(names, col, qs, C)}{_source("atp721")}</div>'
        )
    st = cat_stats if cat_stats is not None else C.stats()
    asof = int(st.get("last") or 0)
    feat_html = f'<div class="app-feat-slot">{_app_card(ATP721_APP, names, st, asof, feat=True)}</div>'
    off = _off(qs)
    total = C.collections_count()
    if total and off >= total:
        off = (total - 1) // PAGE * PAGE
    cols = C.collections_offset(offset=off, limit=PAGE)
    if not cols:
        empty = (
            '<div class="app-empty app-soon">'
            '<p class="app-soon-line">Collections arrive with the next index</p>'
            '</div>'
        )
        return f'<div class="art-page atp721-store">{feat_html}{_mint_card("atp721")}{empty}{cov_line}{_source("atp721")}</div>'
    grid = "".join(_col_card(names, t, feat=False) for t in cols)
    pg = pager(total, off, lambda o: _list_url("atp721", o))
    return f'<div class="art-page atp721-store">{feat_html}{_mint_card("atp721")}<div class="tok-grid">{grid}</div>{pg}{cov_line}{_source("atp721")}</div>'


def _art_stats(works):
    memos = sum(int(w.get("parts") or 0) + (1 if w.get("seal_ts") else 0) for w in works)
    addrs = {w.get("addr") for w in works if w.get("addr")}
    times = [int(w.get("seal_ts") or 0) for w in works if w.get("seal_ts")]
    last = max(times, default=0)
    series = [0] * BARS
    if last:
        start = (last // DAY) * DAY - (BARS - 1) * DAY
        for t in times:
            i = (t - start) // DAY
            if 0 <= i < BARS:
                series[i] += 1
    return dict(memos=memos, agents=len(addrs), last=last, series=series)


def _art_list(names, qs=None, works=None):
    if works is None:
        from . import ac1art as R
        works = R.works()
    st = _art_stats(works)
    asof = int(st.get("last") or 0)
    feat_html = f'<div class="app-feat-slot">{_app_card(ART_APP, names, st, asof, feat=True)}</div>'
    if not works:
        empty = '<div class="app-empty app-soon"><p class="app-soon-line">Works arrive with the next index</p></div>'
        return f'<div class="art-page">{feat_html}{empty}{_source("art")}</div>'
    off = _off(qs)
    total = len(works)
    if total and off >= total:
        off = (total - 1) // PAGE * PAGE
    page_rows = works[off:off + PAGE]
    grid = "".join(_work_card(names, w, feat=False) for w in page_rows)
    pg = pager(total, off, lambda o: _list_url("art", o))
    return f'<div class="art-page">{feat_html}<div class="app-grid">{grid}</div>{pg}{_source("art")}</div>'

def warm_urls():
    """Collection, tick, and first pager pages the background warmer should keep, besides the tab roots in WARM.
    Capped so one warmer pass stays inside the existing loop. Deeper pager pages pin on first render."""
    urls, seen = [], set()

    def add(u):
        if u and u not in seen:
            seen.add(u); urls.append(u)

    try:
        from . import atp721 as C
        C.ensure_fresh()
        for tok in C.collections():
            col = tok.get("col")
            if not col:
                continue
            add("/apps?tab=atp721&col=" + col)
            try:
                total = C.units_count(col)
            except Exception:
                total = int(tok.get("minted") or 0)
            pages = min((max(int(total or 0), 0) + PAGE - 1) // PAGE, 5)
            for i in range(1, pages):
                add(f"/apps?tab=atp721&col={col}&offset={i * PAGE}")
    except Exception:
        pass
    try:
        _n = posts(1, 0, count=True)[1]
        pages = min((max(int(_n or 0), 0) + PAGE - 1) // PAGE, 5)
        for i in range(1, pages):
            add(f"/apps?tab=posts&offset={i * PAGE}")
    except Exception:
        pass
    try:
        from . import atp20 as T
        n = T.tokens_count()
        pages = min((max(int(n or 0), 0) + PAGE - 1) // PAGE, 5)
        for i in range(1, pages):
            add(f"/apps?tab=atp20&offset={i * PAGE}")
        for tok in T.tokens_offset(0, PAGE):
            tick = tok.get("tick")
            if tick:
                add("/apps?tab=atp20&tick=" + tick)
    except Exception:
        pass
    return urls


def page_html(qs=None):

    from .views import page
    from . import atp20 as _T, atp721 as _C, ac1art as _R
    tab = _tab(qs)
    tick = _tick(qs) if tab == "atp20" else ""
    col = _col(qs) if tab == "atp721" else ""
    names = A.forum_names()
    bundle = catalog_stats()
    try:
        st20 = _T.stats()
    except Exception:
        st20 = dict(memos=0, agents=0, last=0, series=[0] * BARS)
    try:
        st721 = _C.stats()
    except Exception:
        st721 = dict(memos=0, agents=0, last=0, series=[0] * BARS)
    try:
        works = _R.works()
    except Exception:
        works = []
    art_st = _art_stats(works)
    total_writes = (
        int((bundle.get("posts") or {}).get("memos") or 0)
        + int((bundle.get("games_total") or {}).get("memos") or 0)
        + int(st20.get("memos") or 0)
        + int(st721.get("memos") or 0)
        + int(art_st.get("memos") or 0)
    )
    if tab == "games":
        body = _games_list(names, bundle)
        title = "Apps, games"
    elif tab == "atp20":
        body = _atp20_list(names, tick, qs, cat_stats=st20)
        title = "Apps, " + tick if tick else "Apps, ATP-20"
    elif tab == "atp721":
        body = _atp721_list(names, col, qs, cat_stats=st721)
        title = "Apps, " + col if col else "Apps, ATP-721"
    elif tab == "art":
        body = _art_list(names, qs, works=works)
        title = "Apps, art"
    else:
        body = _posts_list(names, bundle, qs)
        title = "Apps"
    tabs = [(k, "/apps" if k == DEFAULT_TAB else "/apps?tab=" + k, lab, None) for k, lab in TABS]
    toolbar = _bar_toolbar(total_writes)
    mod = KIT.tabmod(tabs, tab, body, toolbar, id="apps", label="Views")
    return page(title, '<h1 class="sr-only">Apps</h1>' + mod, "/apps")


def page_route(qs=None):
    return page_html(qs)
