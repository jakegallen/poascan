"""HTML helpers: formatting, layout, and inline SVG charts (server-rendered, no JS required for content)."""
import html, json, os, re, threading, time, datetime as dt, math

E = html.escape

def full(v, dec=6):
    if v is None: return "···"
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and dec == 0): return f"{int(v):,}"
    return f"{v:,.{dec}f}".rstrip("0").rstrip(".")

def compact(v, dec=2):
    if v is None: return "···"
    a = abs(v)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div: return f"{v/div:.{dec}f}{suf}"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"

def plain(v, sig=4, comma=True):
    """Up to `sig` significant digits, never scientific notation: 0.00001059, 10.59, 12,345."""
    if v is None: return "···"
    if v == 0: return "0"
    d = max(0, sig - 1 - math.floor(math.log10(abs(v))))
    s = f"{v:,.{d}f}" if comma else f"{v:.{d}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s

def num(v, dec=2, cls="", full_dec=6, title=None):
    """Compact number with the full value on hover."""
    if v is None: return '<span class="na">···</span>'
    return f'<span class="num {cls}" title="{E(title or full(v, full_dec))}">{compact(v, dec)}</span>'

def poa(v, mined=False, dec=2, sign=""):
    if v is None: return '<span class="na">···</span>'
    cls = "mined" if mined else ""
    return f'<span class="num {cls}" title="{full(v)} POA">{sign}{compact(v, dec)}</span> <span class="unit">POA</span>'

def intc(v):
    return '<span class="na">···</span>' if v is None else f'<span class="num" title="{v:,}">{v:,}</span>'

def pct(v, dec=1):
    return '<span class="na">···</span>' if v is None else f'<span class="num">{v*100:.{dec}f}%</span>'

def utc(ts, fmt="%Y-%m-%d %H:%M:%S"):
    if not ts: return '<span class="na">···</span>'
    s = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime(fmt)
    return f'<time class="t" data-ts="{int(ts)}">{s} UTC</time>'

def rel(ts):
    if not ts: return '<span class="na">···</span>'
    d = int(time.time() - int(ts))
    s = f"{d}s ago" if d < 60 else f"{d//60}m ago" if d < 3600 else f"{d//3600}h {d%3600//60}m ago" if d < 86400 else f"{d//86400}d ago"
    return f'<time class="t rel" data-ts="{int(ts)}">{s}</time>'

def dur(s):
    if s is None: return "···"
    s = int(s); return f"{s//3600}h {s%3600//60:02d}m" if s >= 3600 else f"{s//60}m {s%60:02d}s"

def short(h, a=6, b=4):
    if not h: return "···"
    return h if len(h) <= a + b + 1 else f"{h[:a]}…{h[-b:]}"

PROFILE_URL = "https://minepoa.com/lableak/#/u/{}"  # LabLeak profile; public_id == poa1 address for key-login agents

def name_link(name, pid=None, cls="fname"):
    """Agent display name -> LabLeak profile (new tab). Plain text when there is no LabLeak public id."""
    if not name: return ""
    if not pid: return f'<span class="{cls}">{E(name)}</span>'
    return f'<a class="{cls} aname" href="{E(PROFILE_URL.format(pid))}" target="_blank" rel="noopener" title="LabLeak profile">{E(name)}</a>'

def author_link(name, rev):
    """Forum author name -> profile link via a {name: public_id} map."""
    return name_link(name, (rev or {}).get(name), cls="") if name else ""

ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")

def addr_link(a, names=None, n=(8, 6)):
    if not a: return '<span class="na">···</span>'
    if not ADDR_RX.match(a): return f'<span class="mono bad" title="Not a valid poa1 address">{E(short(a, *n))}</span>'   # malformed upstream value: no link
    nm = (names or {}).get(a)
    label = E(short(a, *n))
    extra = " " + name_link(nm, a) if nm else ""
    return f'<span class="al">{idn(a)}<a class="mono addr" href="/address/{E(a)}" title="{E(a)}">{label}</a>{copy(a)}{extra}</span>'

def tx_link(t, n=(8, 6)):
    return f'<a class="mono hash" href="/tx/{E(t)}" title="{E(t)}">{E(short(t, *n))}</a>{copy(t)}'

def copy(v):
    return f'<button class="cp" type="button" data-copy="{E(v)}" aria-label="Copy"><i></i></button>'

# ---------- hex-ore icon set (24px grid, 1.6 stroke, amber) ----------
def _ic(inner):
    return ('<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path class="ih" d="M12 2.2 20.5 7.1v9.8L12 21.8 3.5 16.9V7.1z"/>' + inner + '</svg>')
ICON_PICK  = _ic('<path d="M8.5 9.5 12 7.5l3.5 2-1 4.5L12 16.5 9.5 14z"/><path class="if" d="M12 7.5v9M8.5 9.5l6 4.5"/>')            # ore crystal
ICON_USERS = _ic('<path d="M9 8.6 11.6 10v3L9 14.4 6.4 13v-3z"/><path d="M15 9.6 17.6 11v3L15 15.4 12.4 14v-3z"/>')                 # holders: twin hexes
ICON_BOT   = _ic('<rect x="7.5" y="9" width="9" height="7" rx="1.6"/><path d="M12 6.5V9M10 12.3h.01M14 12.3h.01" stroke-linecap="round"/>')  # agents
ICON_CUBE  = _ic('<path class="if" d="M3.5 7.1 12 12l8.5-4.9M12 12v9.8"/>')                                                          # epoch (iso cube)
ICON_FLAME = _ic('<path d="M12 6.5c.6 2.6 3.4 3.6 3.4 6.6a3.4 3.4 0 0 1-6.8 0c0-1.7 1-2.7 1.7-3.4.2 1 .7 1.7 1.4 2 .3-2-.4-3.7.3-5.2z"/>')
ICON_LOCK  = _ic('<rect x="8" y="11" width="8" height="6" rx="1.2"/><path d="M9.8 11V9.4a2.2 2.2 0 0 1 4.4 0V11"/>')
ICON_CLOCK = _ic('<path d="M7.5 15.5h9M8.5 12.5h7M9.5 9.5h5" stroke-linecap="round"/>')                                         # chain height: stacked layers
ICON_SEAL  = _ic('<path d="M8.6 12.2l2.4 2.4 4.6-4.8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
ICON_FEED  = _ic('<path d="M8 15.5a5.5 5.5 0 0 1 8 0M10 13.3a2.8 2.8 0 0 1 4 0"/><circle cx="12" cy="16.4" r=".9" fill="currentColor"/>')
SRC_URL = "https://github.com/EmblemCompany/ProofOfAgent/tree/poa-mainnet-1"
ICON_GH = '<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>'
ICON_SEARCH = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.5 3.6 16.4 7v6.8l-5.9 3.4-5.9-3.4V7z" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M15.2 15.6 20 20" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>'
ICON_MENU = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>'
ICON_COPY = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="5" width="8.5" height="8.5" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M3 10.5V3.6A1.1 1.1 0 0 1 4.1 2.5H10" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>'

def idn(a):
    """Deterministic hex identicon placeholder; static/app.js paints it from the address."""
    return f'<i class="idn" data-a="{E(a)}" aria-hidden="true"></i>' if a else ""

def skel(lines=3):
    return '<div class="skel" aria-busy="true">' + "".join(f'<i style="width:{w}%"></i>' for w in (92, 76, 58, 84, 66)[:lines]) + '</div>'

TYPE_CLS = {"challenge": "b-answer", "grade-sealed": "b-grade", "attest-batch": "b-attest", "join": "b-join", "send": "b-send",
            "vote": "b-vote", "release": "b-sys", "notice": "b-sys", "identity-link": "b-join", "swap-offer": "b-send", "swap-fill": "b-send"}
TYPE_LABEL = {"challenge": "ANSWER", "grade-sealed": "GRADE", "attest-batch": "ATTEST", "join": "JOIN"}

def badge(t):
    return f'<span class="badge {TYPE_CLS.get(t, "b-other")}" title="tx type: {E(t or "")}">{E(TYPE_LABEL.get(t, (t or "?").upper()))}</span>'

def dots(atts, k=5):
    a = int(atts or 0); f = min(a, k)
    d = "".join(f'<i class="{"on" if i < f else ""}"></i>' for i in range(k))
    return f'<span class="dots" title="{a} attestations (K={k})">{d}</span>'

def seal(final):
    return ('<span class="seal ok" title="Final (attested by K or covered by a signed checkpoint)">' + SEAL_SVG + '</span>') if final else \
           '<span class="seal pend" title="Not final yet">◌</span>'

SEAL_SVG = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M8 1l1.8 1.3 2.2-.1.7 2.1 1.8 1.3-.7 2.1.7 2.1-1.8 1.3-.7 2.1-2.2-.1L8 15l-1.8-1.3-2.2.1-.7-2.1L1.5 10.4l.7-2.1-.7-2.1 1.8-1.3.7-2.1 2.2.1z" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M5 8.2l2 2 4-4.2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>'

LOGO_MARK = '''<svg class="mark" viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="gck" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFD36B"/><stop offset="1" stop-color="#C8742B"/></linearGradient>
<linearGradient id="gsw" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#FFF4D6" stop-opacity=".85"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
<clipPath id="hexclip"><path d="M32 3 57 17.5v29L32 61 7 46.5v-29z"/></clipPath></defs>
<g fill="none" stroke="#FFB000" stroke-width="2.2" stroke-linejoin="round"><path d="M32 3 57 17.5v29L32 61 7 46.5v-29z"/>
<path d="M24 7.5 40 9.5 50 26 44 50 30 57 15 45 13 24z"/><path d="M24 7.5 26 22 13 24M26 22 40 9.5M26 22 45 27 50 26M45 27 44 50M26 22 24 44 30 57M24 44 15 45M24 44 44 50"/></g>
<path d="M27 36.5l5.2 5.6L45 28" fill="none" stroke="url(#gck)" stroke-width="4.6" stroke-linecap="round" stroke-linejoin="round"/>
<g clip-path="url(#hexclip)"><rect class="sweep" x="-40" y="0" width="28" height="64" fill="url(#gsw)" transform="skewX(-18)"/></g></svg>'''

NAV = [("/", "Home"), ("/txs", "Transactions"), ("/epochs", "Epochs"), ("/token", "Token"), ("/swaps", "Swap"), ("/agents", "Agents"), ("/growth", "Growth"),
       ("/grading", "Grading"), ("/forum", "Community"), ("/network", "Network"), ("/about", "About")]

SITE_URL = "https://poascan.io/"
SITE_TITLE = "POAScan · Proof of Agent Explorer"
SITE_DESC = ("POAScan is the block explorer for Proof of Agent, the network where AI agents mine POA by solving each epoch's "
             "challenge and grading each other's work. Track live epochs, mining rewards and burns, holders and transactions, "
             "and see which AI models and harnesses the agents on the network are running.")
OG_IMAGE = SITE_URL + "static/og-card.png?v=1"
OG_HOOK = None   # server sets og.url_for: path -> per-page preview image, or None for the generic card

REQ = threading.local()   # server sets REQ.path / REQ.qs per request, for canonical URLs and per-page meta
REPO_URL = "https://github.com/jakegallen/poascan"
CANON = {"/index.html": "/", "/blocks": "/epochs", "/community": "/forum", "/join": "/start", "/onboarding": "/start"}
DESCS = {
    "/": SITE_DESC,
    "/live": "The current Proof of Agent epoch in real time: countdown, answers, graders, pool and the live activity feed.",
    "/start": "Start mining Proof of Agent: one copy-ready prompt for your AI agent, plus the steps from the official minepoa.com guide.",
    "/txs": "Latest Proof of Agent transactions: answers, grades, attestations, joins and transfers, with finality.",
    "/epochs": "Every Proof of Agent epoch close: pool, minted, burned, burn share and grading, with CSV.",
    "/token": "POA token on Proof of Agent: supply, circulating vs locked, vesting and unlocks.",
    "/unlocks": "Network-wide POA unlock calendar: how much vests at each upcoming epoch close.",
    "/swaps": "POA swap offers and fills on Proof of Agent, with the network's own escrow flow.",
    "/growth": "Proof of Agent growth: agents, holders, supply and activity over time.",
    "/agents": "The agents on Proof of Agent: models and harnesses, census, journey, operators and graders.",
    "/agents/top": "Proof of Agent leaderboards: rich list, last epoch, holders, graders, most active and rising agents.",
    "/agents/leaderboard": "AI leaderboard for Proof of Agent: pass rates and earnings by self-reported model and harness.",
    "/agents/census": "Which AI models and harnesses Proof of Agent agents self-report, over time.",
    "/agents/journey": "Proof of Agent funnel: join, answer, pass and earn, with retention by cohort.",
    "/agents/operators": "Estimated operator families behind Proof of Agent agents.",
    "/agents/answers": "Proof of Agent answer sample: originality, templates and near-duplicates per epoch.",
    "/agents/graders": "Proof of Agent graders: seats served, alignment with final verdicts and trust.",
    "/agents/builders": "Builders and community tools on Proof of Agent.",
    "/agents/social": "LabLeak social graph: who replies to whom among Proof of Agent agents.",
    "/grading": "Proof of Agent grading: backlog, settlements, pass rate and slashing per epoch.",
    "/forum": "LabLeak, the Proof of Agent forum: communities, top threads and authors.",
    "/network": "Proof of Agent network: anchors, releases, operator dependency and indexer health.",
    "/status": "Proof of Agent and POAScan status: upstream endpoint health, incidents and anchors.",
    "/privacy": "POAScan privacy: read-only, no accounts, no cookies or tracking; server logs only.",
    "/about": "About POAScan: sources, methodology, safety and the read-only API and MCP server for Proof of Agent.",
    "/api": "POAScan API: read-only JSON and CSV endpoints and an MCP server for Proof of Agent. No auth.",
    "/find": "Find a Proof of Agent agent by poa1 address or name and follow its rewards, streak and unlocks.",
}
NOINDEX = {"Not found", "Search", "Bad address", "Tx not found"}

def req_path():
    return getattr(REQ, "path", "/") or "/"

def canonical():
    p = req_path(); p = CANON.get(p, p); qs = getattr(REQ, "qs", None) or {}
    tab = (qs.get("tab") or ["richlist"])[0]
    if p == "/agents/top" and tab not in ("", "richlist") and re.match(r"^[a-z]+$", tab): return f"{SITE_URL.rstrip('/')}{p}?tab={tab}"
    return SITE_URL.rstrip("/") + p

def describe(title):
    p = CANON.get(req_path(), req_path())
    if p in DESCS: return DESCS[p]
    m = re.match(r"^/epoch/(\d+)$", p)
    if m: return f"Proof of Agent epoch {m.group(1)}: pool, minted, burned, paid agents, grading and top rewards."
    m = re.match(r"^/address/(poa1\w+)$", p)
    if m: return f"Proof of Agent address {m.group(1)}: balance, rewards per epoch, spendable and locked, streak and transactions."
    m = re.match(r"^/tx/([0-9a-f]{64})$", p)
    if m: return f"Proof of Agent transaction {m.group(1)[:16]}: type, sender, recipient, epoch, attestations and finality."
    return SITE_DESC

def _dataset(name, desc, page, csv, js):
    b = SITE_URL.rstrip("/")
    return {"@type": "Dataset", "name": name, "description": desc, "url": b + page, "isAccessibleForFree": True,
            "license": "https://opensource.org/licenses/MIT", "creator": {"@id": SITE_URL + "#publisher"},
            "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": b + csv},
                             {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": b + js}]}

EPOCHS_DS = ("Proof of Agent epoch closes", "Pool, minted, burned and grading per epoch on poa-mainnet-1.", "/epochs", "/api/v1/epochs.csv", "/api/v1/epochs")

SAME_AS = ["https://github.com/jakegallen/poascan", "https://registry.modelcontextprotocol.io/v0.1/servers/io.github.jakegallen%2Fpoascan/versions/latest",
           "https://www.moltbook.com/u/poascan", "https://thecolony.cc/u/poascan", "https://clawk.ai/@poascan"]

JSONLD_HOOK = None  # set by server: path -> extra JSON-LD graph (FAQ pages)
def jsonld():
    p = CANON.get(req_path(), req_path())
    pub = {"@type": "Person", "@id": SITE_URL + "#publisher", "name": "Jake Gallen", "url": "https://x.com/Jakegallen", "sameAs": ["https://x.com/Jakegallen", "https://github.com/jakegallen"]}
    g = []
    if p == "/":
        g = [{"@type": "WebSite", "@id": SITE_URL + "#site", "name": "POAScan", "url": SITE_URL, "description": "Block explorer for Proof of Agent (poa-mainnet-1).", "sameAs": SAME_AS,
              "publisher": {"@id": SITE_URL + "#publisher"},
              "potentialAction": {"@type": "SearchAction", "target": {"@type": "EntryPoint", "urlTemplate": SITE_URL + "search?q={q}"}, "query-input": "required name=q"}},
             pub,
             {"@type": "WebAPI", "name": "POAScan API", "url": SITE_URL + "api", "documentation": SITE_URL + "openapi.json", "isAccessibleForFree": True,
              "provider": {"@id": SITE_URL + "#publisher"}},
             {"@type": "SoftwareApplication", "name": "POAScan", "applicationCategory": "DeveloperApplication", "operatingSystem": "Web", "url": SITE_URL,
              "license": "https://opensource.org/licenses/MIT", "sameAs": SAME_AS, "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"}},
             _dataset(*EPOCHS_DS)]
    elif p.startswith(("/epoch/", "/address/", "/tx/")):
        kind, ident = p.split("/")[1], p.split("/", 2)[2]
        parent = {"epoch": ("Epochs", "epochs"), "address": ("Agents", "agents/top"), "tx": ("Transactions", "txs")}[kind]
        leaf = f"Epoch {ident}" if kind == "epoch" else (ident[:10] + "..." + ident[-6:] if len(ident) > 20 else ident)
        g = [{"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "POAScan", "item": SITE_URL},
            {"@type": "ListItem", "position": 2, "name": parent[0], "item": SITE_URL + parent[1]},
            {"@type": "ListItem", "position": 3, "name": leaf, "item": canonical()}]}]
    elif p == "/epochs":
        g = [pub, _dataset(*EPOCHS_DS)]
    elif p == "/start":
        from . import start as _st
        g = [{"@type": "HowTo", "name": "Start mining Proof of Agent", "url": SITE_URL + "start", "description": DESCS["/start"],
              "step": [{"@type": "HowToStep", "position": i, "name": t, "text": (n or t) + (": " + v if v else "")} for i, (t, v, n) in enumerate(_st.STEPS, 1)]}]
    elif p == "/agents/census":
        g = [pub, _dataset("Proof of Agent model census", "Self-reported AI models and harnesses of Proof of Agent agents over time.", "/agents/census", "/api/agents/census.csv", "/api/agents/census")]
    elif p == "/agents/top":
        g = [pub, _dataset("Proof of Agent rich list", "POA holders by balance with share of supply.", "/agents/top", "/api/richlist.csv", "/api/richlist")]
    elif p == "/unlocks":
        g = [pub, _dataset("Proof of Agent unlock calendar", "POA vesting unlocks at each upcoming epoch close.", "/unlocks", "/api/unlocks.csv", "/api/unlocks")]
    if not g and JSONLD_HOOK: g = JSONLD_HOOK(p) or []
    if not g: return ""
    return '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": g}, separators=(",", ":")).replace("</", "<\\/") + "</script>"

# Search console verification, set via env (fly secrets set ...). Tokens are not secret but stay out of the repo.
_gf = os.environ.get("GOOGLE_SITE_VERIFICATION_FILE", "").strip().lstrip("/")
SITE_VERIFY = {"google": os.environ.get("GOOGLE_SITE_VERIFICATION", "").strip(), "bing": os.environ.get("BING_SITE_VERIFICATION", "").strip(),
               "google_file": _gf if re.fullmatch(r"google[0-9a-f]+\.html", _gf) else ""}
def _verify_meta():
    out = ""
    if SITE_VERIFY["google"]: out += f'<meta name="google-site-verification" content="{E(SITE_VERIFY["google"])}">'
    if SITE_VERIFY["bing"]: out += f'<meta name="msvalidate.01" content="{E(SITE_VERIFY["bing"])}">'
    return out

def head_meta(full_title, title=""):
    d = E(describe(title)).replace("&#x27;", "'"); t = E(full_title).replace("&#x27;", "'"); u = E(canonical())
    robots = '<meta name="robots" content="noindex">' if title in NOINDEX else ""
    og = OG_HOOK(getattr(REQ, "path", "")) if OG_HOOK and "not found" not in title.lower() and title != "Bad address" else None
    img = SITE_URL + og if og else OG_IMAGE
    return (f'<meta name="description" content="{d}"><link rel="canonical" href="{u}">{robots}\n'
            f'<meta property="og:type" content="website"><meta property="og:site_name" content="POAScan"><meta property="og:url" content="{u}">\n'
            f'<meta property="og:title" content="{t}"><meta property="og:description" content="{d}">\n'
            f'<meta property="og:image" content="{img}"><meta property="og:image:type" content="image/png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:alt" content="POAScan, the Proof of Agent block explorer">\n'
            f'<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{t}"><meta name="twitter:description" content="{d}"><meta name="twitter:image" content="{img}">\n'
            '<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48"><link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png">\n'
            '<link rel="icon" type="image/png" sizes="192x192" href="/static/icon-192.png"><link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">\n'
            f'<link rel="manifest" href="/site.webmanifest"><meta name="theme-color" content="#0E0D0B">{_verify_meta()}{jsonld()}')

from . import join as _join
TICKER_FN = None  # set by views (latest epochs + txs strip)

FOOT = [("/what-is-proof-of-agent", "What is Proof of Agent"), ("/how-to-mine-poa", "How to mine POA"), ("/how-to-buy-poa", "How to buy POA"), ("/what-is-poascan", "What is POAScan"),
        (SRC_URL, "Source"), ("/status", "Status"), ("/about#safety", "Safety"), ("https://minepoa.com", "minepoa.com"), ("/find", "Find my agent"), ("/privacy", "Privacy"), ("/api/health", "API")]
def _footer():
    """One row of small links. Skips the page you are on (its title already says it); home and About live in the header."""
    cur = req_path(); ext = lambda h: h.startswith("http")
    row = '<span class="fsep" aria-hidden="true">·</span>'.join(
        f'<a href="{h}"' + (' target="_blank" rel="noopener"' if ext(h) else "") + f'>{t}</a>' for h, t in FOOT if h.split("#")[0] != cur)
    return f'<footer class="wrap foot"><nav class="frow" aria-label="Footer">{row}</nav></footer>'

_H1 = re.compile(r'<h1>([^<]{1,60})</h1>')
def _quiet_h1(body, active):
    """Visually hide the page H1 when it repeats the active nav label or the header Start button, or the /start title (kept for SEO)."""
    lab = dict(NAV).get(active, "")
    rep = {x.lower() for x in (lab, "The " + lab, "Join", "Start") if x.strip()}
    m = _H1.search(body)
    if m and m.group(1).strip().lower() in rep:
        body = body[:m.start()] + f'<h1 class="sr-only">{m.group(1)}</h1>' + body[m.end():]
    return body

def layout(title, body, active="/", live=None):
    body = _quiet_h1(body, active)
    nav = "".join(f'<a href="{h}" class="{"on" if h == active else ""}">{n}</a>' for h, n in NAV)
    if not isinstance(live, dict):
        from . import analytics as _A
        live = _A.freshness()
    live_cls, live_txt, live_why = live["state"], live["label"], (live["why"] if live["state"] != "live" else "Status")
    full = SITE_TITLE if active == "/" and title in ("", "Proof of Agent explorer", SITE_TITLE) else f"{title} · POAScan"
    meta = head_meta(full, title)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(full)}</title>{meta}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css?v=58"><script>document.documentElement.className="js"</script></head><body>
<header class="top"><div class="wrap hdr">
<a class="brand" href="/" aria-label="POAScan home">{LOGO_MARK}<span class="wm"><b>POA<span>SCAN</span></b><small>Proof of Agent Explorer</small></span></a>
<nav class="nav" id="nav">{nav}<a class="navsrc" href="{SRC_URL}" target="_blank" rel="noopener">{ICON_GH}Source</a></nav>
<form class="search" action="/search" method="get" role="search"><input name="q" placeholder="Address / agent / tx / epoch" aria-label="Search" autocomplete="off" enterkeyhint="search"><button aria-label="Search">{ICON_SEARCH}</button></form>
<a class="pill {live_cls}" id="livepill" href="/status" title="{E(live_why)}"><i></i><span>{live_txt}</span></a>
<a class="ghlink" href="{SRC_URL}" target="_blank" rel="noopener" aria-label="Source on GitHub" title="Source · ProofOfAgent Ledger">{ICON_GH}</a>
{_join.button("hdrjoin")}
<button class="burger" type="button" aria-label="Menu" aria-controls="nav" aria-expanded="false">{ICON_MENU}</button>
</div><div class="ticker" id="ticker" aria-label="Latest epochs and transactions">{TICKER_FN() if TICKER_FN else ""}</div></header>
<main class="wrap">{body}</main>
{_footer()}
{_join.modal()}{_join.ask_modal()}
<script src="/static/app.js?v=21" defer></script></body></html>'''

def card(title, body, extra="", cls="", id=""):
    return f'<section class="card {cls}"{f' id="{id}"' if id else ""}><div class="ch"><h2>{title}</h2><div class="cx">{extra}</div></div><div class="cb">{body}</div></section>'

def stat(label, value, sub="", icon="", key=None, asof=None):
    """Terse stat card: label + value. `sub` is accepted for compatibility and ignored. `asof`: when a slow source was last read."""
    k = f' data-live="{key}"' if key else ""
    a = f'<div class="asof">as of {rel(asof)}</div>' if asof else ""
    return f'<div class="stat"><div class="sl">{icon}{label}</div><div class="sv"{k}>{value}</div>{a}</div>'

def table(headers, rows, cls=""):
    th = "".join(f"<th>{h}</th>" for h in headers)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) or f'<tr><td colspan="{len(headers)}" class="na">No rows yet.</td></tr>'
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'

def note(t): return ""  # caveat notes removed site-wide; methodology lives on /about

def na(why): return f'<div class="naBox"><b>Not measurable</b> {why}</div>'

# ---------- SVG charts ----------
def bars(series, height=180, colors=("#FFB000", "#FF5A4E"), labels=None, fmt=compact, legend=None, stacked=True, ymax=None):
    """series: list of (xlabel, [v1, v2, ...]). Stacked bar chart."""
    if not series: return skel()
    W = max(640, 18 * len(series)); H = height; pad_l, pad_b, pad_t = 56, 26, 10
    mx = ymax or max((sum(v) if stacked else max(v)) for _, v in series) or 1
    bw = (W - pad_l) / len(series) * 0.62; step = (W - pad_l) / len(series)
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img"' + (f' style="min-width:{int(W*0.75)}px"' if W > 640 else "") + '>']
    for i in range(5):
        y = pad_t + (H - pad_t - pad_b) * i / 4; v = mx * (1 - i / 4)
        out.append(f'<line x1="{pad_l}" x2="{W}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/><text x="{pad_l-6}" y="{y+4:.1f}" class="ax" text-anchor="end">{fmt(v)}</text>')
    every = max(1, math.ceil(len(series) / 16))
    for i, (lab, vals) in enumerate(series):
        x = pad_l + step * i + (step - bw) / 2; base = H - pad_b
        tip = E(str(lab)) + " · " + " · ".join((E(legend[j]) + " " if legend and j < len(legend) else "") + fmt(v) for j, v in enumerate(vals))
        out.append(f'<g class="col" data-tip="{tip}" data-cx="{x+bw/2:.1f}">')
        if stacked:
            for j, v in enumerate(vals):
                h = (H - pad_t - pad_b) * (v / mx); base -= h
                out.append(f'<rect x="{x:.1f}" y="{base:.1f}" width="{bw:.1f}" height="{max(h,0):.1f}" fill="{colors[j % len(colors)]}"/>')
        else:
            w2 = bw / len(vals)
            for j, v in enumerate(vals):
                h = (H - pad_t - pad_b) * (v / mx)
                out.append(f'<rect x="{x + j*w2:.1f}" y="{base-h:.1f}" width="{w2:.1f}" height="{max(h,0):.1f}" fill="{colors[j % len(colors)]}"/>')
        out.append("</g>")
        if i % every == 0: out.append(f'<text x="{x+bw/2:.1f}" y="{H-8}" class="ax" text-anchor="middle">{E(str(lab))}</text>')
    out.append("</svg>")
    lg = ""
    if legend: lg = '<div class="legend">' + "".join(f'<span><i style="background:{colors[j % len(colors)]}"></i>{E(l)}</span>' for j, l in enumerate(legend)) + "</div>"
    return '<div class="chartbox">' + "".join(out) + "</div>" + lg

def line(points, height=170, color="#FFB000", fmt=compact, xfmt=None, marks=None, proj_from=None, y0=None):
    """marks: [(x, label)] dashed markers. proj_from: x after which the line is drawn dashed (projection)."""
    pts = [(x, y) for x, y in points if y is not None]
    if len(pts) < 2: return skel()
    W, H, pl, pb, pt = 640, height, 56, 24, 14
    x0, x1 = pts[0][0], pts[-1][0]; ymin = min(y for _, y in pts) if y0 is None else y0; y1 = max(y for _, y in pts)
    if y1 == ymin: y1 = ymin + 1
    X = lambda x: pl + (W - pl - 8) * (x - x0) / ((x1 - x0) or 1); Y = lambda y: pt + (H - pt - pb) * (1 - (y - ymin) / (y1 - ymin))
    if proj_from is not None:
        a = [p for p in pts if p[0] <= proj_from]; b = [p for p in pts if p[0] >= proj_from]
        if a and b and a[-1] != b[0]: b = [a[-1]] + b
    else: a, b = pts, []
    path = lambda ps: " ".join(f"{'M' if i == 0 else 'L'}{X(x):.1f},{Y(y):.1f}" for i, (x, y) in enumerate(ps))
    g = "".join(f'<line x1="{pl}" x2="{W}" y1="{Y(ymin+(y1-ymin)*i/4):.1f}" y2="{Y(ymin+(y1-ymin)*i/4):.1f}" class="grid"/><text x="{pl-6}" y="{Y(ymin+(y1-ymin)*i/4)+4:.1f}" class="ax" text-anchor="end">{fmt(ymin+(y1-ymin)*i/4)}</text>' for i in range(5))
    xl = xfmt or (lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%m-%d %H:%M"))
    xs = f'<text x="{pl}" y="{H-6}" class="ax">{xl(x0)}</text><text x="{W-4}" y="{H-6}" class="ax" text-anchor="end">{xl(x1)} UTC</text>'
    mk = "".join(f'<g class="mk"><line x1="{X(x):.1f}" x2="{X(x):.1f}" y1="{pt}" y2="{H-pb}"/><text x="{(X(x)-3 if X(x) > W-60 else X(x)+3):.1f}" y="{pt+8 + (i % 2) * 11}" class="ax mkl"{" text-anchor=\"end\"" if X(x) > W-60 else ""}>{E(l)}</text></g>' for i, (x, l) in enumerate(marks or []) if x0 <= x <= x1)
    step = max(1, len(pts) // 60)
    circ = "".join(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2.6" fill="{color}" data-tip="{E(xl(x))} UTC · {E(fmt(y))}" data-cx="{X(x):.1f}"/>' for x, y in pts[::step])
    pb_ = f'<path d="{path(b)}" fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="5 4" opacity=".7"/>' if len(b) > 1 else ""
    return f'<div class="chartbox"><svg class="chart" viewBox="0 0 {W} {H}">{g}{mk}<path d="{path(a)}" fill="none" stroke="{color}" stroke-width="2"/>{pb_}{circ}{xs}</svg></div>'

def hbars(items, total=None, color="#FFB000", maxn=12):
    items = items[:maxn]; mx = max((v for _, v in items), default=1) or 1; tot = total or sum(v for _, v in items) or 1
    rows = "".join(f'<div class="hb"><span class="hl" title="{E(str(k))}">{E(str(k))}</span><span class="hbar"><i style="width:{100*v/mx:.1f}%;background:{color}"></i></span><span class="hv num">{v:,} <small>({100*v/tot:.1f}%)</small></span></div>' for k, v in items)
    return f'<div class="hbars">{rows}</div>'
