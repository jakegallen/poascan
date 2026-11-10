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

def compact3(v):
    """Card format: 3 significant figures with K/M/B (977M, 22.8M, 1.22B, 419K); the full value lives in the title."""
    if v is None: return "···"
    units = ((1e9, "B"), (1e6, "M"), (1e3, "K"))
    for i, (div, suf) in enumerate(units):
        if abs(v) >= div or (i < 2 and abs(v) >= div * 0.9995):
            x = v / div
            d = 2 if abs(x) < 9.995 else 1 if abs(x) < 99.95 else 0
            if abs(round(x, d)) >= 1000 and i > 0: x, suf, d = v / units[i - 1][0], units[i - 1][1], 2
            return f"{x:.{d}f}{suf}"
    return compact(v)

def sig3_pct(t):
    """'97.72%' -> '97.7%', '4.8%' stays, '100.0%' -> '100%' (3 significant figures, no padded zeros)."""
    try: v = float(t[:-1])
    except ValueError: return t
    if v == 0: return "0%"
    d = max(0, 2 - math.floor(math.log10(abs(v))))
    t = f"{v:.{d}f}"
    return (t.rstrip("0").rstrip(".") if "." in t else t) + "%"

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

# ---------- Times (1.26.122): one format, in the visitor's own zone ----------
# The server writes <time datetime="ISO UTC" data-f=kind> with UTC text (the no-JS fallback); app.js lt() rewrites it with
# Intl.DateTimeFormat in the browser's zone and hour cycle: "Oct 25, 8:48 AM", the year only when it is not this year.
# kinds: dt (date and time), dts (with seconds), d (date), t (time). CSV and API keep ISO UTC.
TZ = '<span class="tzn">UTC</span>'   # in a header that names the zone: app.js puts the reader's short zone name ("PDT")

def _kind(fmt):
    hm = "%H" in fmt or "%I" in fmt; day = any(k in fmt for k in ("%d", "%b", "%-d", "%m"))
    return "dt" if hm and day else "t" if hm else "d"

def utc_text(ts, kind="dt"):
    """The UTC fallback in the one format: 'Oct 25, 15:48 UTC', 'Oct 25, 2025, 15:48 UTC', 'Oct 25', '15:48 UTC'."""
    u = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc); now = dt.datetime.now(dt.timezone.utc)
    d = f"{u:%b} {u.day}" + (f", {u.year}" if u.year != now.year else "")
    t = f"{u:%H:%M}" + (f":{u:%S}" if kind == "dts" else "")
    return d if kind == "d" else f"{t} UTC" if kind == "t" else f"{d}, {t} UTC"

def lt(ts, kind="dt", cls=""):
    """A time in the visitor's zone (app.js), UTC text without script."""
    if not ts: return '<span class="na">···</span>'
    ts = int(ts); iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
    return f'<time class="t lt{(" " + cls) if cls else ""}" datetime="{iso}" data-ts="{ts}" data-f="{kind}">{utc_text(ts, kind)}</time>'

def iso_ts(s):
    """'2026-10-25T15:47:11Z' or '2026-10-25 15:47:11' (UTC) to unix seconds; None when unreadable."""
    try: d = dt.datetime.fromisoformat(str(s).strip().replace("Z", "+00:00").replace(" ", "T"))
    except (TypeError, ValueError): return None
    return int((d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp())

def utc(ts, fmt="%Y-%m-%d %H:%M:%S"):
    """Kept for callers: now a visitor-local time (lt) whose kind follows fmt (date, time, or both)."""
    return lt(ts, _kind(fmt))

def rel(ts):
    if not ts: return '<span class="na">···</span>'
    d = int(time.time() - int(ts))
    d = max(0, d)   # under a minute reads in 10 s steps, as app.js does, so a feed is not ticking every second
    s = "just now" if d < 10 else f"{d // 10 * 10}s ago" if d < 60 else f"{d//60}m ago" if d < 3600 else f"{d//3600}h {d%3600//60}m ago" if d < 86400 else f"{d//86400}d ago"
    return f'<time class="t rel" data-ts="{int(ts)}">{s}</time>'

def stamp(ts, word="Updated"):
    """Visible time for upgrade and status lines: UTC on the server ('Updated 22:35Z'); app.js adds the reader's local time
    with a short zone name ('Updated 3:35 PM PDT · 22:35Z'). Empty without a time."""
    if not ts: return ""
    z = time.strftime("%H:%MZ", time.gmtime(int(ts))); iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts)))
    return f'<span class="upts">{word} <time data-upts="{int(ts)}" datetime="{iso}">{z}</time></span>'

def dur(s):
    if s is None: return "···"
    s = int(s); return f"{s//3600}h {s%3600//60:02d}m" if s >= 3600 else f"{s//60}m {s%60:02d}s"

def short(h, a=6, b=4):
    if not h: return "···"
    return h if len(h) <= a + b + 1 else f"{h[:a]}…{h[-b:]}"

PROFILE_URL = "https://minepoa.com/lableak/#/u/{}"  # LabLeak profile; public_id == poa1 address for key-login agents

def qtip(text, method_href, label, cls=""):
    """A tap, click and keyboard tooltip (details/summary, no hover only): a ? button that opens a short note with a Method link.
    The note is fixed to the viewport so table scroll boxes never clip it; app.js closes it on Escape or an outside tap.
    cls "hv" also opens it on a mouse hover; leaving closes what the hover opened, a click pins it."""
    # 1.26.290 (UI/UX P2): no "?" icons anywhere. Methodology lives on /about (each note's Method link pointed there), so a
    # tip renders nothing; callers keep passing their text so the notes stay greppable next to the numbers they explain.
    return ""

def name_link(name, pid=None, cls="fname"):
    """Agent display name -> LabLeak profile (new tab). Plain text when there is no LabLeak public id."""
    if not name: return ""
    if not pid: return f'<span class="{cls}">{E(name)}</span>'
    return f'<a class="{cls} aname" href="{E(PROFILE_URL.format(pid))}" target="_blank" rel="noopener noreferrer" title="LabLeak profile">{E(name)}</a>'

def author_link(name, rev):
    """Forum author name -> profile link via a {name: public_id} map, in the shared Agent cell (agent()) when the id is a poa1 address."""
    if not name: return ""
    pid = (rev or {}).get(name)
    if pid and ADDR_RX.match(pid): return agent(pid, name)
    return f'<span class="al ag">{name_link(name, pid, cls="agn")}</span>'

ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")

def agent(a, name=None, names=None, frag="", tail="", n=(6, 4)):
    """The one Agent cell (1.26.152), used by every table and list that names an Agent: identicon, then the name linking to its
    LabLeak profile when it has one, otherwise the short address linking to /address; the copy button right after it, then any
    tail (a tag). One line; the label ends in an ellipsis when the column is narrow (style.css .ag), so nothing spills into the
    next cell. A named Agent's identicon links to its POAScan address page. frag: a fragment for the address links (#standing)."""
    if not a: return '<span class="na">···</span>'
    if not ADDR_RX.match(a): return f'<span class="mono bad" title="Not a valid poa1 address">{E(short(a, *n))}</span>'
    if name is None and names: name = names.get(a)
    href = f"/address/{E(a)}{E(frag)}"
    if name:
        ic = f'<a class="agi" href="{href}" title="{E(a)}" aria-label="Address page of {E(name)}">{idn(a)}</a>'
        lab = f'<a class="agn aname" href="{E(PROFILE_URL.format(a))}" target="_blank" rel="noopener noreferrer" title="{E(name)} · LabLeak profile">{E(name)}</a>'
    else:
        ic, lab = idn(a), f'<a class="agn mono addr" href="{href}" title="{E(a)}">{E(short(a, *n))}</a>'
    return f'<span class="al ag" data-a="{E(a)}">{ic}{lab}{copy(a)}{tail}</span>'

def addr_link(a, names=None, n=(8, 6)):
    """An address in a table or list is the shared Agent cell (agent()); the full address (n of 48, key/value rows) keeps its name after it."""
    if not a: return '<span class="na">···</span>'
    if not ADDR_RX.match(a): return f'<span class="mono bad" title="Not a valid poa1 address">{E(short(a, *n))}</span>'   # malformed upstream value: no link
    if n[0] < 40: return agent(a, names=names)   # every Agent cell uses the same 6 + 4 short address (1.26.154)
    nm = (names or {}).get(a)
    label = E(short(a, *n))
    extra = " " + name_link(nm, a, cls="fname agn") if nm else ""
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

def idn(a):
    """Deterministic hex identicon placeholder; static/app.js paints it from the address."""
    return f'<i class="idn" data-a="{E(a)}" aria-hidden="true"></i>' if a else ""

def chart_skel(w=640, h=170, why=""):
    """Placeholder sized to the chart it stands for (same aspect ratio as the SVG viewBox), so nothing moves when data lands."""
    t = f'<span>{why}</span>' if why else ""
    return f'<div class="skel cskel" aria-busy="true" style="aspect-ratio:{w}/{h}"><i></i>{t}</div>'

def skel(lines=3):
    return '<div class="skel" aria-busy="true">' + "".join(f'<i style="width:{w}%"></i>' for w in (92, 76, 58, 84, 66)[:lines]) + '</div>'

TYPE_CLS = {"challenge": "b-answer", "grade-sealed": "b-grade", "attest-batch": "b-attest", "join": "b-join", "send": "b-send",
            "vote": "b-vote", "release": "b-sys", "notice": "b-sys", "identity-link": "b-join", "swap-offer": "b-send", "swap-fill": "b-send"}
TYPE_LABEL = {"challenge": "ANSWER", "grade-sealed": "GRADE", "attest-batch": "ATTEST", "join": "JOIN", "chains-update": "WALLET LINK"}
TYPE_TIP = {"challenge": "An Agent's answer to the epoch challenge", "grade-sealed": "A sealed grade on another Agent's answer",
            "attest-batch": "Attestations confirming a batch of transactions", "join": "A new Agent joining the network",
            "chains-update": "Links or updates an external wallet for swaps"}

def type_name(t):
    """Plain UI name for a tx type (API keeps the raw type): Answer, Grade, Attest, Wallet link."""
    return TYPE_LABEL.get(t, (t or "?").replace("-", " ").upper()).capitalize()

def badge(t):
    return f'<span class="badge {TYPE_CLS.get(t, "b-other")}" title="{E(TYPE_TIP.get(t, ""))} ({E(t or "")})">{E(TYPE_LABEL.get(t, (t or "?").upper()))}</span>'

def dots(atts, k=5):
    a = int(atts or 0); f = min(a, k)
    d = "".join(f'<i class="{"on" if i < f else ""}"></i>' for i in range(k))
    return f'<span class="dots" title="{a} attestations (K={k})">{d}</span>'

def seal(final):
    return ('<span class="seal ok" title="Final (attested by K or covered by a signed checkpoint)">' + SEAL_SVG + '</span>') if final else \
           '<span class="seal pend" title="Not final yet">◌</span>'

SEAL_SVG = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M8 1l1.8 1.3 2.2-.1.7 2.1 1.8 1.3-.7 2.1.7 2.1-1.8 1.3-.7 2.1-2.2-.1L8 15l-1.8-1.3-2.2.1-.7-2.1L1.5 10.4l.7-2.1-.7-2.1 1.8-1.3.7-2.1 2.2.1z" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M5 8.2l2 2 4-4.2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>'

LOGO_MARK = '''<svg class="mark" viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="gck" x1="0" y1="0" x2="1" y2="1"><stop offset="0" style="stop-color:var(--mark-hi)"/><stop offset="1" style="stop-color:var(--copper)"/></linearGradient>
<linearGradient id="gsw" x1="0" y1="0" x2="1" y2="0"><stop offset="0" style="stop-color:var(--white)" stop-opacity="0"/><stop offset=".5" style="stop-color:var(--mark-glint)" stop-opacity=".85"/><stop offset="1" style="stop-color:var(--white)" stop-opacity="0"/></linearGradient>
<clipPath id="hexclip"><path d="M32 3 57 17.5v29L32 61 7 46.5v-29z"/></clipPath></defs>
<g fill="none" style="stroke:var(--gold)" stroke-width="2.2" stroke-linejoin="round"><path d="M32 3 57 17.5v29L32 61 7 46.5v-29z"/>
<path d="M24 7.5 40 9.5 50 26 44 50 30 57 15 45 13 24z"/><path d="M24 7.5 26 22 13 24M26 22 40 9.5M26 22 45 27 50 26M45 27 44 50M26 22 24 44 30 57M24 44 15 45M24 44 44 50"/></g>
<path d="M27 36.5l5.2 5.6L45 28" fill="none" stroke="url(#gck)" stroke-width="4.6" stroke-linecap="round" stroke-linejoin="round"/>
<g clip-path="url(#hexclip)"><rect class="sweep" x="-40" y="0" width="28" height="64" fill="url(#gsw)" transform="skewX(-18)"/></g></svg>'''

NAV = [("/chain", "Chain"), ("/agents", "Agents"), ("/network", "Network"), ("/governance", "Governance"), ("/api", "API")]   # Home is the logo; About and Source are in the footer; swaps live on POASwap (header button)
# Pages that live under a header tab: the tab that shows as active for them (1.26.96 header merge)
NAV_OF = {"/api/reference": "/api", "/epochs": "/chain", "/txs": "/chain", "/token": "/network", "/unlocks": "/network"}

SITE_URL = "https://poascan.io/"
SITE_TITLE = "POAScan · Proof of Agent Explorer"
SITE_DESC = ("POAScan is the block explorer for Proof of Agent, the network where AI agents mine POA by solving each epoch's "
             "challenge and grading each other's work. Track live epochs, mining rewards and burns, holders and transactions, "
             "and see which AI models and harnesses the agents on the network are running.")
OG_IMAGE = SITE_URL + "static/og-card.png?v=1"
OG_HOOK = None   # server sets og.url_for: path -> per-page preview image, or None for the generic card

REQ = threading.local()   # server sets REQ.path / REQ.qs per request, for canonical URLs and per-page meta
CANON = {"/index.html": "/", "/blocks": "/chain", "/epochs": "/chain", "/txs": "/chain/txs", "/community": "/forum", "/join": "/start", "/onboarding": "/start"}
DESCS = {
    "/": SITE_DESC,
    "/live": "The current Proof of Agent epoch in real time: countdown, answers, graders, pool and the live activity feed.",
    "/start": "Start mining Proof of Agent: one copy-ready prompt for your AI agent, plus the steps from the official minepoa.com guide.",
    "/chain/txs": "Latest Proof of Agent transactions: answers, grades, attestations, joins and transfers, with finality.",
    "/chain": "Proof of Agent epochs: the open epoch live, every close (pool, minted, burned, cohorts), the pending queue and grading, with CSV.",
    "/governance": "Proof of Agent governance: established Agents, standing at risk, graders, payouts per close and how established works.",
    "/txs": "Latest Proof of Agent transactions: answers, grades, attestations, joins and transfers, with finality.",
    "/epochs": "Proof of Agent epochs: the open epoch live, every close (pool, minted, burned, cohorts), the pending queue and grading, with CSV.",
    "/token": "POA token on Proof of Agent: supply, circulating vs locked, vesting and unlocks.",
    "/unlocks": "Network-wide POA unlock calendar: how much vests at each upcoming epoch close.",
    "/swaps": "POA swap offers and fills on Proof of Agent, with the network's own escrow flow.",
    "/growth": "Proof of Agent growth: agents, holders, supply and activity over time.",
    "/agents": "The agents on Proof of Agent: models and harnesses, census, journey, operators and graders.",
    "/agents/top": "Proof of Agent rankings: rich list, lifetime and last-epoch earners, streaks, graders, referrals and AI models.",
    "/agents/leaderboard": "AI leaderboard for Proof of Agent: pass rates and earnings by self-reported model and harness.",
    "/agents/census": "Which AI models and harnesses Proof of Agent agents self-report, over time.",
    "/agents/journey": "Proof of Agent funnel: join, answer, pass and earn, with retention by cohort.",
    "/agents/operators": "Estimated operator families behind Proof of Agent agents.",
    "/agents/answers": "Proof of Agent answer sample: originality, templates and near-duplicates per epoch.",
    "/agents/graders": "Proof of Agent grader calibration, advisory and unranked: jury agreement, score mean and spread, seals per close, with sample sizes.",
    "/agents/builders": "Builders and community tools on Proof of Agent.",
    "/agents/social": "LabLeak social graph: who replies to whom among Proof of Agent agents.",
    "/grading": "Proof of Agent grading: backlog, settlements, pass rate and slashing per epoch.",
    "/forum": "LabLeak, the Proof of Agent forum: communities, top threads and authors.",
    "/network": "Proof of Agent network: anchors, releases, operator dependency, upstream health and growth charts.",
    "/agents/community": "Proof of Agent community: LabLeak forum activity, the social graph, builders and the answer sample.",
    "/status": "Proof of Agent and POAScan status: upstream endpoint health, incidents and anchors.",
    "/privacy": "POAScan privacy: read-only, no sign-in, no cookies or tracking scripts; daily visit totals and server logs only.",
    "/about": "About POAScan: sources, methodology, safety and the read-only API and MCP server for Proof of Agent.",
    "/api": "POAScan API: read-only JSON and CSV endpoints and an MCP server for Proof of Agent. No auth.",
    "/find": "Find a Proof of Agent agent by poa1 address or name and follow its rewards, streak and unlocks.",
    "/help": "Start earning on Proof of Agent: check why an Agent is not earning, from public network data, and every way to earn. Read only, never asks for a key.",
    "/wallet": "Check a Proof of Agent wallet: the Agent behind a poa1 address and the external wallets linked to it, with how each was verified. Read only.",
}
TAB_DESCS = {   # tabbed pages whose tabs are their own canonical URLs (canonical()): a description per tab
    ("/network", "anchors"): "Proof of Agent anchor timeline: every checkpoint anchored on Base and Solana, the gap between them and a cross check of each state root.",
    ("/network", "token"): "POA token on Proof of Agent: supply, circulating vs locked, vesting and unlocks.",
    ("/network", "health"): "Proof of Agent and POAScan health: feed state, route halts, upstream latency and uptime.",
    ("/network", "charts"): "Proof of Agent network charts: supply, Agents, activity and grading over 24h, 7d, 30d and All.",
}
NOINDEX = {"Not found", "Search", "Bad address", "Tx not found"}

def req_path():
    return getattr(REQ, "path", "/") or "/"

def canonical():
    p = req_path(); p = CANON.get(p, p); qs = getattr(REQ, "qs", None) or {}
    tab = (qs.get("tab") or [""])[0]   # tabbed pages: each tab is its own canonical URL; the default tab is the bare path
    dflt = {"/agents/top": "holders", "/chain": "closed", "/network": "overview", "/governance": "overview", "/agents/census": "models", "/agents/community": "forum"}
    if p in dflt and tab not in ("", dflt[p]) and re.match(r"^[a-z][a-z-]{0,30}$", tab): return f"{SITE_URL.rstrip('/')}{p}?tab={tab}"
    return SITE_URL.rstrip("/") + p

def describe(title):
    p = CANON.get(req_path(), req_path())
    if p == "/upgrade":
        from . import maint as _M
        return _M.og_desc()
    tab = ((getattr(REQ, "qs", None) or {}).get("tab") or [""])[0]
    if (p, tab) in TAB_DESCS: return TAB_DESCS[(p, tab)]
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

EPOCHS_DS = ("Proof of Agent epoch closes", "Pool, minted, burned and grading per epoch on poa-mainnet-1.", "/chain", "/api/v1/epochs.csv", "/api/v1/epochs")

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
        parent = {"epoch": ("Epochs", "chain"), "address": ("Agents", "agents/top"), "tx": ("Transactions", "chain/txs")}[kind]
        leaf = f"Epoch {ident}" if kind == "epoch" else (ident[:10] + "..." + ident[-6:] if len(ident) > 20 else ident)
        g = [{"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "POAScan", "item": SITE_URL},
            {"@type": "ListItem", "position": 2, "name": parent[0], "item": SITE_URL + parent[1]},
            {"@type": "ListItem", "position": 3, "name": leaf, "item": canonical()}]}]
    elif p == "/chain":
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
            f'<link rel="manifest" href="/site.webmanifest"><meta name="theme-color" content="#0B0A08">{_verify_meta()}{jsonld()}')

from . import join as _join

FOOT = [("/about", "About"), ("/about#what-is-proof-of-agent", "What is Proof of Agent"), ("/about#how-to-mine-poa", "How to mine POA"), ("/about#how-to-buy-poa", "How to buy POA"),
        ("/about#what-is-poascan", "What is POAScan"), (SRC_URL, "Source"), ("/network?tab=health", "Status"), ("/about#safety", "Safety"), ("https://minepoa.com", "minepoa.com"),
        ("/privacy", "Privacy"), ("/api", "API")]
def _footer():
    """One row of small links. Skips the page you are on (its title already says it); home and About live in the header."""
    cur = req_path(); ext = lambda h: h.startswith("http")
    row = '<span class="fsep" aria-hidden="true">·</span>'.join(
        f'<a href="{h}"' + (' target="_blank" rel="noopener noreferrer"' if ext(h) else "") + f'>{t}</a>' for h, t in FOOT if h.split("#")[0] != cur)
    return f'<footer class="wrap foot"><nav class="frow" aria-label="Footer">{row}</nav>{CREDIT}</footer>'

_H1 = re.compile(r'<h1>([^<]{1,60})</h1>')
def _quiet_h1(body, active):
    """Visually hide the page H1 when it repeats the active nav label or the header Start button, or the /start title (kept for SEO)."""
    lab = dict(NAV).get(active, "")
    rep = {x.lower() for x in (lab, "The " + lab, "Join", "Start") if x.strip()}
    m = _H1.search(body)
    if m and m.group(1).strip().lower() in rep:
        body = body[:m.start()] + f'<h1 class="sr-only">{m.group(1)}</h1>' + body[m.end():]
    return body

def search_form(cls, sid):
    """Header search (and the home hero search, which replaces it on /). The hint and name suggestions replace the old /find page."""
    return (f'<form class="{cls}" action="/search" method="get" role="search"><input name="q" placeholder="Address / agent / tx / epoch" aria-label="Search" '
            f'autocomplete="off" enterkeyhint="search" aria-controls="{sid}-s" aria-autocomplete="list"><button aria-label="Search">{ICON_SEARCH}</button>'
            f'<div class="sugg" id="{sid}-s" role="listbox"><p class="shint">Find my agent: paste its poa1 address or type its name</p><div class="sopts"></div></div></form>')

POASWAP_URL = "https://poaswap.io"
# Sister site button, the mirror of POASwap's own POAScan pill: its mark (vendored, static/poaswap-mark.svg) and teal (style.css --swap, --swap-hi).
SWAP_BTN = (f'<a class="swaplink" href="{POASWAP_URL}" target="_blank" rel="noopener noreferrer" title="POASwap, agent to agent swaps" aria-label="POASwap, agent to agent swaps">'
            '<img class="swmark" src="/static/poaswap-mark.svg?v=1" width="18" height="18" alt="" aria-hidden="true"><span>POASwap</span></a>')

# Non-home pages: the header pill hides while maintenance is on (the home strip carries Upgrading), so a small amber dot to /upgrade
# keeps the status visible there. Same source as the strip and the API pill (analytics.freshness state "up"); hidden otherwise.

# 1.26.288: the site-wide development banner (1.26.69) is gone, on Jake's call. Home carries one quiet credit instead: a muted
# pill under the last card that turns gold on hover, linking Jake's X profile in a new tab. One element per view, no share button.
X_LOGO = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>'
# 1.26.300: the credit moved from a floating pill under the home cards into the footer row (every page): right aligned on
# desktop, its own centered line on a phone. Muted like the footer links, gold on hover.
CREDIT = ('<a class="fcredit" href="https://x.com/Jakegallen" target="_blank" rel="noopener noreferrer" aria-label="Built by @Jakegallen on X">'
          f'<span>Built by</span>{X_LOGO}<b>@Jakegallen</b></a>')

# Header status (1.26.169): the dot and word open a small note (the qtip pattern: tap, click, keyboard, mouse hover) with what
# drives the state, the read time in the reader's zone, and links. Grading not confirmed after the completion notice turns a
# Live header Partial; it was the home strip, which is gone. Local data only (freshness, maint.grading_state): no new reads.
GRADING_REASON = {"unconfirmed": "Grading not yet confirmed. No recent seals.", "halted": "Grading halted. Mining open."}

def _grading_reason():
    try:
        from . import maint as M
        if not M.complete() or M.state()["active"]: return ""
        return GRADING_REASON.get(M.grading_state()["state"], "")
    except Exception: return ""

# 1.26.176: while minepoa.com answers with a notice in place of data (strain.py), the reason is one line in this note, never a
# site strip; the affected numbers keep their own Stale and Unconfirmed tags.
NOTICE_REASON = "minepoa.com sent a notice instead of data. Showing the last real data."

def _notice_reason():
    try:
        from . import strain as _ST
        return NOTICE_REASON if _ST.public() else ""
    except Exception: return ""

# 1.26.181: the Home Upgrading strip and the in-page "lookup paused" note are folded into the header status note too.
HALT_NAMES = {"/api/explorer/tx/:id": "tx", "/api/notices": "notices", "/api/chains": "wallet link"}

def _upgrade_reason():
    """While maintenance is on: the strip's line as one sentence ("Hosted mining paused for maintenance. Joining works.")."""
    try:
        from . import maint as _M
        if not _M.state()["active"]: return ""
        lead, aside, tail = _M.strip_text()
        return f"{lead}{aside}." + (f" {tail}" if tail else "")
    except Exception: return ""

def _upgrade_ts():
    try:
        from . import maint as _M
        return _M.stamp_ts()
    except Exception: return None

def _halt_reason(now=None):
    """minepoa.com has a lookup paused (HTTP 503 halted): which, in one line. Pages serve indexed data meanwhile."""
    try:
        from . import indexer as _I
        names = [n for t, n in HALT_NAMES.items() if _I.halted(t, now)]
    except Exception: return ""
    if not names: return ""
    which = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"minepoa.com paused {which} lookups. Showing indexed data."

# 1.26.188: routes Halted or Down per POAScan's own probes (routewatch.py, two bad reads in a row): one line each, the start
# time in the reader's zone (UTC without script), and one as-of line for the probe reads. Turns Live into Partial.
def _ztime(ts):
    """A time that app.js shows in the reader's zone (upts); 'HH:MMZ' without script."""
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts)))
    return f'<time data-upts="{int(ts)}" datetime="{iso}">{time.strftime("%H:%MZ", time.gmtime(int(ts)))}</time>'

def _route_lines():
    """[(text, html)] for the header status note, [] when no route is Halted or Down."""
    try:
        from . import routewatch as _RW
        d = _RW.state(); rs = [r for r in d["routes"] if r["state"] in ("halted", "down")]
    except Exception: return []
    out = []
    for r in rs:
        w = "degraded" if r.get("covered_by") else "halted" if r["state"] == "halted" else "down"   # 1.26.201: covered by the fast index
        t = r["since_ts"]
        out.append((f'{r["label"]} {w} since {time.strftime("%H:%MZ", time.gmtime(t))}.' if t else f'{r["label"]} {w}.',
                    f'{E(r["label"])} {w} since {_ztime(t)}.' if t else f'{E(r["label"])} {w}.'))
    if out and d.get("as_of_ts"):
        a = d["as_of_ts"]; out.append((f'Probes as of {time.strftime("%H:%MZ", time.gmtime(a))}.', f'Probes as of {_ztime(a)}.'))
    return out

def status_pill(f):
    """The header pill from analytics.freshness(): state, label, why, href, reasons and the note's HTML (pop)."""
    state, label, why = f["state"], f["label"], f.get("why") or ""
    reasons = []
    # 1.26.220: Partial only for a core route (mining, grading: routehealth.py), the same rule as /api/health. Every other
    # route or feed that is not ok gets its own line and leaves the dot as it is.
    if state == "partial" and why.startswith("Chain live. Not OK: "):
        bad = why[len("Chain live. Not OK: "):]
        core = {"Mining", "Grading"}; parts = [x.strip() for x in bad.split(",")]
        reasons.append((f"Core route not OK: {bad}." if all(x in core for x in parts) else ("Feeds" if "," in bad else "Feed") + f" not OK: {bad}."))
    elif state not in ("live", "up") and why: reasons.append(why.rstrip(".") + ".")
    try:
        from . import analytics as _A
        fdx = _A.feeds(); rlx = [t for t, _ in _route_lines()]
        for r in fdx["routes"]:   # a route already on a probe line (Halted or Down since) is not repeated
            if not r["core"] and r["state"] in ("degraded", "down") and not any(t.startswith(r["label"] + " ") for t in rlx):
                reasons.append(f'{r["label"]} {r["state"]}: {r["detail"]}.')
        rl0 = {r["label"] for r in fdx["routes"]}; fl = [lab for lab in fdx["degraded"] if lab not in rl0 and lab not in why]
        if fl: reasons.append(("Feeds" if len(fl) > 1 else "Feed") + f" not OK: {', '.join(fl)}.")
    except Exception: fdx = None
    g = _grading_reason()
    try: g_core = next(r for r in fdx["routes"] if r["id"] == "grading")["state"] in ("degraded", "down") if fdx else True
    except StopIteration: g_core = True
    if g and g_core:   # the grading line shows only while the core Grading route is not ok, so the dot and the note agree
        reasons.append(g)
        if state == "live": state, label = "partial", "Partial"
    nr = _notice_reason()
    if nr:
        reasons.append(nr)
    try:
        from . import rewardbasis as _RB
        rr = _RB.pill_reason()   # 1.26.216: the balance is ahead of the held close records (lagging figures carry Stale tags)
    except Exception: rr = ""
    if rr:
        reasons.append(rr)
    rl = _route_lines(); rhtml = {}
    for t, h in rl:
        reasons.append(t); rhtml[t] = h
    if any(t.startswith(("Hosted mining ", "Grading ")) for t, _ in rl) and state == "live": state, label = "partial", "Partial"   # core routes only
    hr = _halt_reason() if not any(t.startswith("Tx lookup ") for t, _ in rl) else ""   # the route line already says tx lookups are halted
    if hr:
        reasons.append(hr)
    ur = _upgrade_reason()   # while maintenance is on, its line is in the note whatever state outranks it (Stale, Lagging)
    if ur: reasons.insert(0, ur) if state == "up" else reasons.append(ur)
    if not reasons: reasons.append("All systems normal." if state == "live" else (why.rstrip(".") + "." if why else label + "."))
    try:
        from . import fastindex as _FX
        fl = _FX.pill_line()   # how current the indexed cache is; Partial comes from its feed row, never from this line
    except Exception: fl = None
    if fl and state != "up":   # 1.26.200: while Tx lookup is not OK and the index is current, tx pages still load from it
        txl = any(t.startswith(("Feed not OK", "Feeds not OK", "Tx lookup ")) and "Tx lookup" in t for t in reasons)
        reasons.append(fl[0] + (" Tx pages load from it." if txl and "Reading" not in fl[0] and "unavailable" not in fl[0] else ""))
    links = ([("/upgrade", "Details")] if g or ur else []) + [("/network?tab=health", "Health")]
    if state == "up": links = [("/upgrade", "Details")]
    ts = (_upgrade_ts() or f.get("fetched_at")) if state == "up" else f.get("fetched_at")   # our last fresh read; while upgrading, the upgrade lines' read
    halted = {t.split(" halted")[0] for t in [x for x, _ in rl] + ([g] if g else []) if " halted" in t} | ({"Tx lookup"} if hr else set())
    pop = _pill_pop(label, fdx, ts, links, f.get("fetched_at"), state, ur, halted)   # 1.26.300: a compact checklist; the sentences stay on Health
    return dict(state=state, label=label, why=why if state != "live" else "Live", href=f.get("href") or "/network?tab=health", reasons=reasons, pop=pop)

# 1.26.300 (Jake, t524u): the header note is a short checklist, one row per feed with a dot and one word. The full reasons
# (with since times) stay on the Health page and in status_pill()["reasons"] for the API.
PILL_NAMES = {"Status": "Chain", "Tx list": "Transactions", "Address lookup": "Addresses", "Tx lookup": "Tx lookup", "Swaps": "Swaps",
              "Swap writes": "Swap writes", "Networks": "Networks", "Notices": "Notices", "Epochs": "Epochs", "Close records": "Close records",
              "Agents": "Agents", "Anchors": "Anchors"}
PILL_WORD = {"ok": ("OK", "ok"), "degraded": ("Slow", "warn"), "stalled": ("Slow", "warn"), "stale": ("Slow", "warn"), "paused upstream": ("Paused", "warn"),
             "paused": ("Paused", "warn"), "down": ("Down", "bad"), "halted": ("Halted", "bad")}

def _age(ts):
    if not ts: return ""
    d = max(0, int(time.time() - int(ts)))
    return "Data just now" if d < 60 else f"Data {d // 60}m old" if d < 3600 else f"Data {d // 3600}h old"

def _pill_rows(fdx, state="live", halted=()):
    """[(name, word, tone)] for the note: the chain, the core routes, then the feeds; not OK first, at most 10."""
    if not fdx: return []
    out, seen = [], set()
    def add(name, st):
        if not name or name in seen: return
        w = PILL_WORD.get(str(st or "").lower())
        if not w: return   # Retired and unknown states are left to Health
        seen.add(name); out.append((name, w[0], w[1]))
    for h in sorted(halted): add(PILL_NAMES.get(h, h), "halted")   # a halt outranks the route's own state
    add("Chain", "down" if state == "stale" else "stalled" if state == "lag" or fdx.get("chain") != "Live" else "ok")
    for r in fdx.get("routes") or []:
        if r.get("core"): add({"Mining": "Mining", "Grading": "Grading"}.get(r["label"], r["label"]), r["state"])
    for r in fdx.get("routes") or []:
        if not r.get("core"): add(PILL_NAMES.get(r["label"], r["label"]), r["state"])
    for r in fdx.get("feeds") or []:
        lab = r.get("label") or ""
        nm = "Fast index" if "index" in lab.lower() else PILL_NAMES.get(lab)
        if nm and nm != "Chain": add(nm, r.get("state"))
    rank = {"bad": 0, "warn": 1, "ok": 2}
    return sorted(out, key=lambda x: rank[x[2]])[:10]

def _pill_pop(label, fdx, ts, links, fetched, state, upgrade_line, halted=()):
    rows = _pill_rows(fdx, state, halted)
    head = f'<span class="sp-h"><b>{E(label)}</b><span class="sp-age">{E(_age(fetched))}</span></span>'
    up = f'<span class="sp-r">{E(upgrade_line)}</span>' if upgrade_line else ""   # maintenance keeps its one line
    lst = ('<ul class="sp-l">' + "".join(f'<li class="{t}"><i aria-hidden="true"></i><span>{E(n)}</span><b>{w}</b></li>' for n, w, t in rows) + '</ul>') if rows else ""
    return head + up + lst + f'<span class="sp-f">{stamp(ts)}' + "".join(f'<a href="{h}">{t}</a>' for h, t in links) + '</span>'

def pill_html(live):
    p = status_pill(live)
    return (f'<details class="qtip hv spill" id="livepill"><summary class="pill {p["state"]}" aria-label="Status: {E(p["label"])}">'
            f'<i aria-hidden="true"></i><span>{E(p["label"])}</span></summary><span class="qbox" role="note">{p["pop"]}</span></details>')

def layout(title, body, active="/", live=None, head=""):
    active = NAV_OF.get(active, active)
    body = _quiet_h1(body, active)
    nav = "".join(f'<a href="{h}" class="on" aria-current="page">{n}</a>' if h == active else f'<a href="{h}" class="">{n}</a>' for h, n in NAV)
    if not isinstance(live, dict):
        from . import analytics as _A
        live = _A.freshness()
    full = SITE_TITLE if active == "/" and title in ("", "Proof of Agent explorer", SITE_TITLE) else f"{title} · POAScan"
    meta = head_meta(full, title)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(full)}</title>{meta}
<meta name="referrer" content="no-referrer">
<link rel="preload" href="/static/fonts/instrumentsans-latin-a64857.woff2" as="font" type="font/woff2" crossorigin><link rel="preload" href="/static/fonts/newsreader-latin-54fd93.woff2" as="font" type="font/woff2" crossorigin><link rel="preload" href="/static/fonts/plexmono400-latin-08949f.woff2" as="font" type="font/woff2" crossorigin>
<style>html,body{{background:#0B0A08;color:#EFE7D6}}</style><link rel="stylesheet" href="/static/style.css?v={ASSET_V["style.css"]}">{head}<script>document.documentElement.className="js"</script></head><body{' class="home"' if active == "/" and 'class="hsearch' in body else ""}>
<header class="top"><div class="wrap hdr">
<a class="brand" href="/" aria-label="POAScan home">{LOGO_MARK}<span class="wm"><b>POA<span>SCAN</span></b><small>Proof of Agent Explorer</small></span></a>
<nav class="nav" id="nav">{nav}</nav>
{search_form("search", "hdr")}
{pill_html(live)}
{SWAP_BTN}
{_join.button("hdrjoin")}
<button class="burger" type="button" aria-label="Menu" aria-controls="nav" aria-expanded="false">{ICON_MENU}</button>
</div></header>
<main class="wrap">{body}</main>
{_footer()}
{_join.shell(start=active == "/start")}{_join.ask_modal()}
<script src="/static/app.js?v={ASSET_V["app.js"]}" defer></script></body></html>'''

# 1.26.150: the CSS and JS cache keys are a hash of the file, so every deploy that changes one gets a new URL. The assets are served
# immutable for a year under ?v=, and the hand-kept numbers (139 and 138) had not moved since Oct 20, so returning visitors could
# keep an old style.css or app.js.
def _asset_v(name):
    import hashlib
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", name), "rb") as f: return hashlib.sha256(f.read()).hexdigest()[:12]
    except OSError: return "0"
ASSET_V = {n: _asset_v(n) for n in ("style.css", "app.js")}

def card(title, body, extra="", cls="", id=""):
    return f'<section class="card {cls}"{f' id="{id}"' if id else ""}><div class="ch"><h2>{title}</h2><div class="cx">{extra}</div></div><div class="cb">{body}</div></section>'

NUM_RX = re.compile(r'(<span class="num[^"]*"(?: title="([^"]*)")?>)([^<]*)(</span>)')

def _sig3(value):
    """Cards show 3 significant figures: the first compact (K/M/B) or decimal-% number is rewritten; its title keeps the full value."""
    m = NUM_RX.search(value)
    if not m: return value
    t = m.group(3)
    if re.fullmatch(r"-?\d+(\.\d+)?[KMB]", t) and m.group(2):
        try: v = float(re.sub(r"[^0-9.\-]", "", m.group(2).split(" ")[0]))
        except ValueError: return value
        new = compact3(v)
    elif re.fullmatch(r"-?\d+\.\d+%", t): new = sig3_pct(t)
    else: return value
    return value[:m.start(3)] + new + value[m.end(3):]

STALE_S = 3 * 3600   # hourly sources (params, release) read longer ago than this are flagged Stale

def _ago(s):
    s = max(0, int(s)); return f"{s // 60}m" if s < 3600 else f"{s // 3600}h {s % 3600 // 60}m" if s < 86400 else f"{s // 86400}d"

def flag(word, detail, tone="warn"):
    """1.26.121: a small state tag beside a stat label (Stale, Unconfirmed, Behind, Stalled, Parked) instead of a sub-line under
    the value. Hover shows the detail (title); tap, click or keyboard opens it (details/summary, the qtip note, closed by app.js)."""
    return (f'<details class="qtip sflag"><summary class="tag {tone}" aria-label="{E(word)}: {E(detail)}" title="{E(detail)}">{E(word)}</summary>'
            f'<span class="qbox" role="note">{E(detail)}</span></details>')

def stat(label, value, sub="", icon="", key=None, asof=None, tip=None, asof_text=None, flag_html=""):
    """Terse stat card: label + value (3 significant figures), no sub-line. `sub` is accepted for compatibility and ignored.
    `asof`: when a slow hourly source was last read; flagged Stale past STALE_S, else the read age is on the label hover.
    `asof_text`: a fixed point the value stands at (e.g. "As of checkpoint 44003"), flagged Stale with that detail.
    `flag_html`: any other flag() tag. `tip`: the definition, shown on hover (methodology stays on /about)."""
    value = _sig3(value)
    if asof and time.time() - int(asof) > STALE_S: flag_html = flag("Stale", f"Last read {_ago(time.time() - int(asof))} ago") + flag_html
    elif asof: tip = ((tip + ". ") if tip else "") + f"Read {_ago(time.time() - int(asof))} ago"
    if asof_text: flag_html = flag("Stale", asof_text) + flag_html
    if tip: label = f'<span title="{E(tip)}">{label}</span>'
    k = f' data-live="{key}"' if key else ""
    label += flag_html; a = ""
    if 'class="usd"' in value:   # number, unit and ≈$ share one line; the number shrinks to fit (style.css .sv.fit)
        k += _fit(value)
        ku = " ku" if 'class="unit"' in value and not re.search(r'<span class="unit">POA</span>', value) else ""   # keep SOL/ETH units
        return f'<div class="stat"><div class="sl">{icon}{label}</div><div class="sv fit{ku}"{k}>{value}</div>{a}</div>'
    return f'<div class="stat"><div class="sl">{icon}{label}</div><div class="sv"{k}>{value}</div>{a}</div>'

def spark(points, n=48, marks=None):
    """Tiny trend under a stat value (no axes): the last n points scaled to their own range, one continuous smooth line over a
    gradient fill, and a glowing dot on the latest point. 1.26.291 (UI/UX P3): no milestone ticks or labels on any chart;
    `marks` is accepted for compatibility and ignored."""
    pts = [(float(t), float(v)) for t, v in (points or []) if v is not None]
    if len(pts) < 2: return ""
    if len(pts) > n: step = len(pts) / n; pts = [pts[int(i * step)] for i in range(n)] + [pts[-1]]
    t0, t1 = pts[0][0], pts[-1][0]; lo = min(v for _, v in pts); hi = max(v for _, v in pts)
    P = [(100 * (t - t0) / ((t1 - t0) or 1), 22 - 19 * (v - lo) / ((hi - lo) or 1)) for t, v in pts]
    d = _smooth(P); gid = _gid("sg", d)
    lx, ly = P[-1]
    return (f'<div class="spkw"><svg class="spk" viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="g0"/><stop offset="1" class="g1"/></linearGradient></defs>'
            f'<path class="sa" d="{d} L100,24 L0,24 Z" fill="url(#{gid})"/><path class="su" d="{d}" transform="translate(0 1.4)" vector-effect="non-scaling-stroke"/>'
            f'<path class="sl" d="{d}" vector-effect="non-scaling-stroke"/></svg>'
            f'<i class="sd" style="left:{lx:.1f}%;top:{100 * ly / 24:.1f}%"></i></div>')

def spark_in(stat_html, points, marks=None):
    """Put a sparkline under a stat card's value (marks: milestone ticks, see spark)."""
    sv = spark(points, marks=marks)
    return stat_html[:-len("</div>")] + sv + "</div>" if sv and stat_html.endswith("</div>") else stat_html

ICON_EXPAND = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M9.5 2.5h4v4M6.5 13.5h-4v-4M13.5 2.5 9 7M2.5 13.5 7 9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'

def pop(stat_html, key):
    """Make a stat card open the chart pop-out (app.js, chartpop.py): the whole card is the button."""
    if not stat_html.startswith('<div class="stat">'): return stat_html
    return (f'<div class="stat cpt" data-chart="{key}" role="button" tabindex="0" aria-haspopup="dialog">'
            f'<i class="cpi" aria-hidden="true">{ICON_EXPAND}</i>' + stat_html[len('<div class="stat">'):])

def pop_btn(key, name):
    """Expand button for a chart card header."""
    return f'<button type="button" class="cpx" data-chart="{key}" aria-haspopup="dialog" aria-label="Expand {E(name)} chart" title="Expand">{ICON_EXPAND}</button>'

def _fit(value):
    """Inline sizing hints: --nc number characters, --fx px taken by unit, ≈$ and gaps (12px mono is ~7.2px a character)."""
    txt = lambda cls: re.sub(r"<[^>]+>", "", (re.search(rf'<span class="{cls}[^"]*"[^>]*>(.*?)</span>', value) or [None, ""])[1])
    nc = max(len(txt("num")), 4) + .5        # headroom for live updates
    fxn = len(txt("usd")) * 7.4 + 6 + 4           # ≈$ and its gap, plus slack
    fx = fxn + (len(txt("unit")) * 7.4 + 6 if 'class="unit"' in value else 0)
    return f' style="--nc:{nc};--fx:{fx:.0f}px;--fxn:{fxn:.0f}px"'

def table(headers, rows, cls="", pri=None, usd=None, sort=None):
    """pri: column indexes that stay visible at 390px (the rest open on tap). usd: POA amount columns the POA | USD toggle converts.
    sort: (cols, key, dir, link) makes the headers sort links (scoresort.heads; one scoresort.Col per column) with the
    phone sort menu above the table; headers is then ignored."""
    pri, usd = set(pri or ()), set(usd or ())
    def c(i, base=""):
        k = " ".join(x for x in (base, "p" if i in pri else "", "pc" if i in usd else "") if x)
        return f' class="{k}"' if k else ""
    pre = ""
    if sort:
        from . import scoresort as SS
        cols, cur, d, link = sort
        cols = [x._replace(cls=" ".join(y for y in (x.cls, "p" if i in pri else "", "pc" if i in usd else "") if y)) for i, x in enumerate(cols)]
        th = SS.heads(cols, cur, d, link); pre = SS.select(cols, cur, d, link) if link else ""
        headers = cols
    else:
        th = "".join(f"<th{c(i)}>{h}</th>" for i, h in enumerate(headers))
    tr = "".join("<tr>" + "".join(f"<td{c(i)}>{x}</td>" for i, x in enumerate(r)) + "</tr>" for r in rows) or f'<tr><td colspan="{len(headers)}" class="na p">No rows yet.</td></tr>'
    cl = " ".join(x for x in (cls, "pri" if pri else "") if x)
    return pre + f'<div class="tw"><table class="{cl}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'

def note(t): return ""  # caveat notes removed site-wide; methodology lives on /about

def na(why): return f'<div class="naBox">{why}</div>'   # empty and error states: say what is missing, no stock label


# ---------- Charts: one spec (1.26.119) ----------
# Geometry lives in an SVG stretched to the plot box (preserveAspectRatio none, non-scaling strokes); every label is HTML in
# 12px mono, so text stays the same size at any width. One series palette by class (s-gold, s-steel, s-ember, s-verd, s-bone):
# a single series is always gold; green and red only for pass and burn. No per-point dots: hover shows one, plus the last point.
SERIES = {"gold": "s-gold", "steel": "s-steel", "ember": "s-ember", "verd": "s-verd", "bone": "s-bone", "copper": "s-copper", "mute": "s-mute"}
def series_cls(c):
    """'gold' / 'steel' / ... -> its series class (anything else reads gold)."""
    return SERIES.get(str(c or "gold"), "s-gold")

VW, VH = 1000, 1000   # plot box in viewBox units; the SVG stretches to the CSS plot height (style.css .cp)

def _f(v): return f"{v:.1f}".rstrip("0").rstrip(".")

def _gid(pre, key=""):
    """An SVG gradient id from the chart's own geometry: the same render gives the same bytes (ETags hold), and two charts
    that share an id share an identical gradient."""
    import zlib
    return f"{pre}{zlib.crc32(str(key).encode()) & 0xffffff:x}"

def _smooth(P):
    """Monotone cubic path through P (Fritsch-Carlson): smooth, never overshoots a point, so a flat run stays flat and a
    cumulative line never dips. P is already in viewBox units; an affine stretch keeps the curve monotone."""
    n = len(P)
    if n < 3: return " ".join(f"{'M' if i == 0 else 'L'}{_f(x)},{_f(y)}" for i, (x, y) in enumerate(P))
    dx = [P[i + 1][0] - P[i][0] for i in range(n - 1)]; m = [(P[i + 1][1] - P[i][1]) / (dx[i] or 1e-9) for i in range(n - 1)]
    t = [m[0]] + [0.0] * (n - 2) + [m[-1]]
    for i in range(1, n - 1):
        if m[i - 1] * m[i] <= 0: t[i] = 0.0
        else:
            w1, w2 = 2 * dx[i] + dx[i - 1], dx[i] + 2 * dx[i - 1]
            t[i] = (w1 + w2) / (w1 / m[i - 1] + w2 / m[i])
    out = [f"M{_f(P[0][0])},{_f(P[0][1])}"]
    for i in range(n - 1):
        h = dx[i] / 3
        out.append(f"C{_f(P[i][0] + h)},{_f(P[i][1] + h * t[i])} {_f(P[i + 1][0] - h)},{_f(P[i + 1][1] - h * t[i + 1])} {_f(P[i + 1][0])},{_f(P[i + 1][1])}")
    return "".join(out)

def _chg(a, b, fmt=None):
    """Period change pill: +12.4% (green tint up), -3.1% (red tint down), 0.0% flat. From a start of 0 it reads the plain
    rise (+26.9B) when a format is given; nothing when the start is missing."""
    if a is None or b is None: return ""
    if a == 0:
        if not fmt or not b: return ""
        return f'<span class="chg {"up" if b > 0 else "dn"}">{"+" if b > 0 else "-"}{E((compact3 if fmt in (compact, compact3) else fmt)(abs(b)))}</span>'
    p = (b - a) / abs(a) * 100
    c = "up" if p >= 0.05 else "dn" if p <= -0.05 else "eq"
    t = "0.0%" if c == "eq" else f"{p:+.1f}%" if abs(p) < 1000 else f"{p:+,.0f}%"
    return f'<span class="chg {c}">{t}</span>'

def _period(x0, x1):
    """Span of a time axis as a terse tag (7D, 30D, 18H); nothing for an epoch or index axis."""
    if not (x0 > 1e9 and x1 > x0): return ""
    s = x1 - x0
    return f"{round(s / 86400)}D" if s >= 1.5 * 86400 else f"{max(1, round(s / 3600))}H"

def _head(v, fmt, chg="", per="", side=""):
    """The chart's headline row: the latest value big, the change pill and the span on the left; side (a legend) on the right."""
    pr = f'<span class="chspan">{E(per)}</span>' if per else ""
    f = compact3 if fmt is compact else fmt   # the headline reads 3 figures (270K, 26.9B); the tip keeps the full value
    sd = f'<span class="chs">{side}</span>' if side else ""
    return f'<div class="chd"><b class="chv" title="{E(fmt(v))}">{E(f(v))}</b>{chg}{pr}{sd}</div>'

def seg(items, cur=None):
    """A segmented timeframe control (7D 30D ALL): items are (label, href), the current one marked. Plain links, so it works
    without script and every view keeps its own URL."""
    on = ' class="on" aria-current="true"'
    return '<nav class="ckrng" aria-label="Range">' + "".join(f'<a href="{E(h)}"{on if l == cur else ""}>{E(l)}</a>' for l, h in items) + "</nav>"

def _plot(svg_inner, overlay, height, top=0, tail="", yg=56, head="", layer="", grid="", yw=0):
    """The chart panel. svg_inner: the data marks (the first SVG: app.js reads its data-tip groups for hover). grid: hairline
    gridlines on their own SVG under the marks, faded toward both edges. layer: the line over the marks with a screen-space
    bloom (style.css .chart.lnl), so the glow stays round although the plot is stretched. A perspective floor grid and a
    baseline glow sit under everything. yg: the right gutter, as wide as the pinned value chip."""
    st = f' style="--ch:{int(height)}px;--yg:{int(yg)}px' + (f';--yw:{int(yw)}px' if yw else "") + (f';--mt:{top}px' if top else "") + '"'
    ly = (f'<svg class="chart lnl" viewBox="0 0 {VW} {VH}" preserveAspectRatio="none" aria-hidden="true">{layer}</svg>' if layer else "")
    gr = (f'<svg class="chart gr" viewBox="0 0 {VW} {VH}" preserveAspectRatio="none" aria-hidden="true">{grid}</svg>' if grid else "")
    return (f'<div class="chartbox ck">{head}<div class="cvg{" tl" if top else ""}{" yL" if yw else ""}"{st}><div class="cvp"><i class="floor" aria-hidden="true"></i><i class="base" aria-hidden="true"></i>'
            f'<svg class="chart" viewBox="0 0 {VW} {VH}" preserveAspectRatio="none" role="img" aria-hidden="true">{svg_inner}</svg>{gr}{ly}'
            f'{overlay}</div></div>{tail}</div>')

def _nice(lo, hi, n=4):
    """Round axis bounds so the gridlines land on round numbers (0, 500M, 1B, 1.5B rather than 393.61M). Tries 3 to 5
    gridline gaps and the 1, 2, 2.5, 5 steps, and keeps the fit that wastes the least height. Returns (lo, hi, gaps)."""
    span = (hi - lo) or abs(hi) or 1; best = None
    for k in (4, 5, 3):
        raw = span / k; m = 10 ** math.floor(math.log10(raw))
        for q in (1, 2, 2.5, 5, 10):
            st = q * m
            if st < raw - 1e-12: continue
            a = math.floor(lo / st + 1e-9) * st; b = math.ceil(hi / st - 1e-9) * st
            kk = round((b - a) / st)
            if kk > 5: continue
            if kk < 3: break
            w = (b - a) / span + (0.02 if kk != 4 else 0)
            if best is None or w < best[0]: best = (w, a, b, kk)
            break
    if best is None: return lo, hi, n
    return best[1], best[2], best[3]

def _tk(fmt):
    """Tick labels abbreviate and drop trailing zeros (2.5K, 1.2B, 450M, 0). A chart whose format carries a unit (12m, 45%)
    keeps its own format."""
    if fmt not in (compact, compact3):
        try:
            if not re.fullmatch(r"[\d,]+(\.\d+)?", fmt(1234.0)): return fmt
        except Exception: return fmt
    def f(v):
        if abs(v) < 1e-9: return "0"
        for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(v) >= div * 0.9995: return f"{v / div:.2f}".rstrip("0").rstrip(".") + suf
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return f

def _grid(ymin, ymax, fmt, n=4, skip=None):
    """Hairline gridlines (none on the floor line; the baseline glow is its own element) and the y labels: inside the plot,
    right aligned, just above their line. The third value (gutter px) is kept for callers and is 0 now."""
    g, lab = [], []; fmt = _tk(fmt)
    for i in range(n + 1):
        y = VH * i / n; v = ymax - (ymax - ymin) * i / n
        if i < n: g.append(f'<line x1="0" x2="{VW}" y1="{_f(y)}" y2="{_f(y)}" class="grid"/>')
        if skip and skip(i / n): continue
        lab.append(f'<span class="yl{" o" if i % 2 and n >= 4 else ""}{" y0" if i == n else ""}" style="top:{100 * i / n:.2f}%">{E(fmt(v))}</span>')
    return "".join(g), "".join(lab), 0

def _xticks(x0, x1, n_max=6):
    """Evenly spaced time ticks on round boundaries: days at 12:00 UTC (the same calendar day in every zone from UTC-11 to
    UTC+11, so a reader-zone label never slips a day), or whole hours. Returns ([ts], kind) with kind "d" or "t"."""
    span = x1 - x0
    if span <= 0: return [], "d"
    for step, kind in ((3600, "t"), (3 * 3600, "t"), (6 * 3600, "t"), (12 * 3600, "t"), (86400, "d"), (2 * 86400, "d"),
                       (7 * 86400, "d"), (14 * 86400, "d"), (30 * 86400, "d"), (91 * 86400, "d")):
        if span / step <= n_max:
            off = 43200 if kind == "d" else 0
            if step == 7 * 86400: t = x1 - ((x1 - off) % 86400)   # weekly: count back from the last day, so it is labelled
            else: t = math.ceil((x0 - off) / step) * step + off
            out = []
            if step == 7 * 86400:
                while t >= x0: out.append(t); t -= step
                out.reverse()
            else:
                while t <= x1: out.append(t); t += step
            return out, kind
    return [x0, x1], "d"

def _xlab(p, txt, attrs=""):
    """One x tick label at p percent: centred on its tick, or start/end aligned at the plot's edges so it never spills."""
    if p < 5: return f'<span class="xl l"{attrs}>{txt}</span>'
    if p > 95: return f'<span class="xl r"{attrs}>{txt}</span>'
    return f'<span class="xl c"{attrs} style="left:{p:.2f}%">{txt}</span>'

def _marks(marks, X, x0, x1):
    """1.26.291 (UI/UX P3, Jake): charts are bare, so no milestone line, chip or legend is drawn on any chart. Kept as a
    no-op so callers that still pass marks render the same chart."""
    return "", "", "", 0

def _tag(cls, x, y, txt, title=""):
    """An HTML value label pinned to a plot point (x, y in viewBox units): .lv the latest value, a glass chip in the line's
    color beside the plot; .ex a high or low callout on a hairline leader."""
    t = f' title="{E(title)}"' if title else ""
    return f'<span class="{cls}" style="left:{100 * x / VW:.2f}%;top:{100 * y / VH:.2f}%"{t}><b>{E(txt)}</b></span>'

def _chipw(txt): return int(7.4 * len(txt) + 24)   # gutter for the pinned chip: 12px tabular figures plus padding and gap

def _xidx(labels, n_max=6):
    """Bar x labels: for epoch labels (E30) only round epochs (E30, E40) at even spacing; else every k-th label."""
    nums = []
    for l in labels:
        m = re.fullmatch(r"E(\d+)", str(l)); nums.append(int(m.group(1)) if m else None)
    if nums and all(v is not None for v in nums):
        span = nums[-1] - nums[0]
        for st in (1, 2, 5, 10, 20, 25, 50, 100, 250, 500):
            if span / st <= n_max - 1: return [i for i, v in enumerate(nums) if v % st == 0]
    n = len(labels); every = max(1, math.ceil(n / n_max))
    return list(range(0, n, every))

def bars(series, height=180, colors=("gold", "ember"), labels=None, fmt=compact, legend=None, stacked=True, ymax=None, xk="t", head=True):
    """series: list of (xlabel, [v1, v2, ...]) or (xlabel, [v...], ts): with a ts the label and tip read in the reader's zone
    (app.js; xk the kind, "t" for hourly buckets). Day buckets that are UTC days keep their plain label. Bars fit the card.
    1.26.291 (UI/UX P3): 3D columns (an isometric extrusion: a lit front face, a darker side face, a top cap), a faint floor
    reflection, the latest bar's value pinned as a glass chip, the tallest bar called out, round ticks inside the plot, and a
    headline row (latest value, change against the bar before, the legend as glowing dots)."""
    tss = [s[2] if len(s) > 2 else None for s in series]; series = [(s[0], s[1]) for s in series]
    if not series: return chart_skel(640, height)
    n = len(series); mx0 = max((sum(v) if stacked else max(v)) for _, v in series) or 1; nk = 4
    if ymax: mx = ymax
    else: _, mx, nk = _nice(0, mx0 * 1.16)   # headroom for the tallest bar's callout
    cls = [series_cls(c) for c in colors] if len(series[0][1]) > 1 or legend else ["s-gold"]
    step = VW / n; bw = step * (0.52 if n < 40 else 0.64); dx = min(bw * 0.42, 20); dy = 8 * VH / max(height, 60)
    g, ylab, _ = _grid(0, mx, fmt, nk)
    gid = _gid("bs", series); gv = _gid("bv", series); gr = _gid("br", series)
    out = [f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" class="b0"/><stop offset=".35" class="b1"/><stop offset="1" class="b2"/></linearGradient>'
           f'<linearGradient id="{gv}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="v0"/><stop offset=".3" class="v1"/><stop offset="1" class="v2"/></linearGradient>'
           f'<linearGradient id="{gr}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="r0"/><stop offset="1" class="r1"/></linearGradient></defs>']
    xs_i = set(_xidx([l for l, _ in series], 7)); xl = []
    tot = lambda vals: (sum(vals) if stacked else max(vals))
    imax = max(range(n), key=lambda i: tot(series[i][1]))
    poly = lambda pts: " ".join(f"{_f(x)},{_f(y)}" for x, y in pts)
    rh = VH * 0.09   # reflection depth under the floor line
    for i, (lab, vals) in enumerate(series):
        x = step * i + (step - bw - dx) / 2; base = VH
        tip = E(str(lab)) + " · " + " · ".join((E(legend[j]) + " " if legend and j < len(legend) else "") + fmt(v) for j, v in enumerate(vals))
        top = VH - VH * (tot(vals) / mx)
        lz = (f' data-ts="{int(tss[i])}" data-tf="{xk}" data-tv="{" · ".join((E(legend[j]) + " " if legend and j < len(legend) else "") + fmt(v) for j, v in enumerate(vals))}"'
              if tss[i] else "")
        out.append(f'<g class="col" data-tip="{tip}"{lz} data-cx="{_f(x + bw / 2)}" data-cy="{_f(top)}">')
        segs = []
        if stacked:
            for j, v in enumerate(vals):
                h = VH * (v / mx); base -= h; segs.append((x, base, bw, max(h, 0), cls[j % len(cls)]))
        else:
            w2 = bw / len(vals)
            for j, v in enumerate(vals):
                h = VH * (v / mx); segs.append((x + j * w2, base - h, w2, max(h, 0), cls[j % len(cls)]))
        bot = [q for q in segs if q[3] > 0][:1]
        if bot:
            sx, _, sw, sh, c = bot[0]
            out.append(f'<rect x="{_f(sx)}" y="{VH}" width="{_f(sw)}" height="{_f(min(rh, sh))}" class="{c} brf" style="fill:url(#{gr})"/>')
        for j, (sx, sy, sw, sh, c) in enumerate(segs):
            if sh <= 0: continue
            out.append(f'<polygon class="{c} bsd" points="{poly([(sx + sw, sy), (sx + sw + dx, sy - dy), (sx + sw + dx, sy + sh - dy), (sx + sw, sy + sh)])}"/>'
                       f'<rect x="{_f(sx)}" y="{_f(sy)}" width="{_f(sw)}" height="{_f(sh)}" class="{c} bf"/>'
                       f'<rect x="{_f(sx)}" y="{_f(sy)}" width="{_f(sw)}" height="{_f(sh)}" class="bsh" style="fill:url(#{gv})"/>'
                       f'<rect x="{_f(sx)}" y="{_f(sy)}" width="{_f(sw)}" height="{_f(sh)}" class="bsh" style="fill:url(#{gid})"/>')
            last_top = stacked and j == len(segs) - 1 or not stacked
            if last_top or (stacked and all(q[3] <= 0 for q in segs[j + 1:])):
                out.append(f'<polygon class="{c} btp" points="{poly([(sx, sy), (sx + dx, sy - dy), (sx + sw + dx, sy - dy), (sx + sw, sy)])}"/>')
        out.append("</g>")
        if i in xs_i:
            p = 100 * (x + (bw + dx) / 2) / VW
            lz = f' data-lts="{int(tss[i])}" data-f="{xk}"' if tss[i] else ""
            xl.append(_xlab(p, E(str(lab)), lz))
    lv = series[-1][1]; lvt = (compact3 if fmt is compact else fmt)(tot(lv))   # the chip reads as the headline does
    tags = _tag("lv b", VW, VH - VH * (tot(lv) / mx) - dy / 2, lvt)
    if imax != n - 1:
        xm = step * imax + (step - bw - dx) / 2 + (bw + dx) / 2
        tags += _tag("ex hi", xm, VH - VH * (tot(series[imax][1]) / mx) - dy, fmt(tot(series[imax][1])))
    lg = ""
    if legend: lg = '<span class="legend">' + "".join(f'<span><i class="{cls[j % len(cls)]}"></i>{E(l)}</span>' for j, l in enumerate(legend)) + "</span>"
    hd = ""
    if head:
        cur = tot(lv); prev = tot(series[-2][1]) if n > 1 else None   # the bar's full height, as the pinned chip reads
        hd = _head(cur, fmt, _chg(prev, cur) if prev is not None else "", _period(tss[0], tss[-1]) if tss[0] and tss[-1] else "", lg)
    elif lg: hd = f'<div class="chd"><span class="chs">{lg}</span></div>'
    yw = int(7 * max(len(_tk(fmt)(mx * k / nk)) for k in range(nk + 1)) + 12)   # bars read their scale on a left axis, clear of the columns
    return _plot("".join(out), ylab + "".join(xl) + tags, height, yg=_chipw(lvt), head=hd, grid=g, yw=yw)

def line(points, height=170, color="gold", fmt=compact, xfmt=None, marks=None, proj_from=None, y0=None, xk="dt", head=True):
    """One series, always gold, one continuous smooth line (never a break, never a milestone). proj_from: x after which
    the line is drawn dashed (projection). `marks` is accepted and ignored (1.26.291, UI/UX P3: bare charts).
    The plot: a raised ribbon (a thick glowing line over an offset darker underside), a multi-stop gradient area fading
    into a perspective floor grid, a glowing endpoint orb, the latest value pinned as a glass chip, the high and low called
    out on hairline leaders when they are not the ends, even date ticks, and a headline row."""
    pts = [(x, y) for x, y in points if y is not None]
    if len(pts) < 2: return chart_skel(640, height)
    x0, x1 = pts[0][0], pts[-1][0]; lo = min(y for _, y in pts); hi = max(y for _, y in pts)
    ymin = lo if y0 is None else y0; y1 = hi
    if y0 is None and hi > lo: ymin = lo - (hi - lo) * 0.06
    if lo >= 0 and ymin < 0: ymin = 0
    if y1 == ymin: y1 = ymin + 1
    y1 += (y1 - ymin) * 0.1
    a, b, nk = _nice(ymin, y1)
    if y0 is None: ymin, y1 = a, b
    else: y1 = ymin + (b - a) if a == ymin else _nice(ymin, y1)[1]; nk = nk if a == ymin else 4
    X = lambda x: VW * (x - x0) / ((x1 - x0) or 1); Y = lambda y: VH * (1 - (y - ymin) / (y1 - ymin))
    if proj_from is not None:
        a = [p for p in pts if p[0] <= proj_from]; b = [p for p in pts if p[0] >= proj_from]
        if a and b and a[-1] != b[0]: b = [a[-1]] + b
    else: a, b = pts, []
    dr = a if len(a) <= 600 else a[::math.ceil(len(a) / 600)] + [a[-1]]
    path = lambda ps: _smooth([(X(x), Y(y)) for x, y in ps])
    cy = Y(lp0[1]) / VH if (lp0 := (([p for p in pts if p[0] <= proj_from] or pts) if proj_from is not None else pts)[-1]) else 0
    g, ylab, _ = _grid(ymin, y1, fmt, nk, skip=lambda f: abs((f * height - 10) - cy * height) < 16)   # no tick label under the line end
    xl = xfmt or (lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%m-%d %H:%M"))
    # x ticks: evenly spaced round days (or hours) on a time axis, read in the reader's zone (data-lts); round steps else
    if x0 > 1e9:
        tk, kind = _xticks(x0, x1)
        xs = "".join(_xlab(100 * X(t) / VW, E(xl(t)), f' data-lts="{int(t)}" data-f="{kind}"') for t in tk if 0 <= 100 * X(t) / VW <= 100)
    else:
        span = x1 - x0; st = next((q for q in (1, 2, 5, 10, 20, 25, 50, 100, 250, 500, 1000) if span / q <= 5), span or 1)
        xs = "".join(_xlab(100 * X(v) / VW, E(xl(v))) for v in range(int(math.ceil(x0 / st) * st), int(x1) + 1, int(st)))
    step = max(1, len(pts) // 160)
    hp = lambda x, y: f'<g data-tip="{E(xl(x))} UTC · {E(fmt(y))}" data-ts="{int(x)}" data-tv="{E(fmt(y))}" data-cx="{_f(X(x))}" data-cy="{_f(Y(y))}"></g>'
    hit = "".join(hp(x, y) for x, y in pts[::step])
    if (len(pts) - 1) % step: hit += hp(*pts[-1])
    lp = a[-1] if a else pts[-1]
    d = path(dr); ga, gb, gs = _gid("la", d), _gid("lb", d), _gid("ls", d)
    defs = (f'<defs><linearGradient id="{ga}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="a0"/><stop offset=".3" class="a1"/><stop offset=".65" class="a2"/><stop offset="1" class="a3"/></linearGradient>'
            f'<linearGradient id="{gb}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="h0"/><stop offset=".14" class="h1"/></linearGradient></defs>')
    area = f'<path class="ar" d="{d} L{_f(X(dr[-1][0]))},{VH} L{_f(X(dr[0][0]))},{VH} Z" fill="url(#{ga})"/><path class="ar hl" d="{d} L{_f(X(dr[-1][0]))},{VH} L{_f(X(dr[0][0]))},{VH} Z" fill="url(#{gb})"/>'
    pb_ = f'<path d="{path(b)}" class="ln pj s-gold"/>' if len(b) > 1 else ""
    dot = f'<i class="ld s-gold" style="left:{100 * X(lp[0]) / VW:.2f}%;top:{100 * Y(lp[1]) / VH:.2f}%"></i>'
    lvt = (compact3 if fmt is compact else fmt)(lp[1]); tags = _tag("lv", VW, Y(lp[1]), lvt)
    ih = max(range(len(pts)), key=lambda i: pts[i][1]); il = min(range(len(pts)), key=lambda i: pts[i][1])
    if 0 < ih < len(pts) - 1 and hi > lo and pts[ih][1] != pts[-1][1]: tags += _tag("ex hi", X(pts[ih][0]), Y(pts[ih][1]), fmt(pts[ih][1]))
    if 0 < il < len(pts) - 1 and hi > lo and il != ih and pts[il][1] not in (pts[0][1], pts[-1][1]): tags += _tag("ex lo" + (" up" if Y(pts[il][1]) > .72 * VH else ""), X(pts[il][0]), Y(pts[il][1]), fmt(pts[il][1]))   # near the floor it reads above the point
    hd = _head(lp[1], fmt, _chg(pts[0][1], lp[1], fmt), _period(x0, lp[0])) if head else ""
    ud = 3.2 * VH / max(height, 60)   # the ribbon's underside: the same path 3 px lower, darker
    lay = (f'<defs><linearGradient id="{gs}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" class="l0"/><stop offset=".7" class="l1"/><stop offset="1" class="l2"/></linearGradient></defs>'
           f'<path d="{d}" class="lu s-gold" transform="translate(0 {_f(ud)})"/><path d="{d}" class="ln s-gold" stroke="url(#{gs})"/>{pb_}')
    return _plot(f'{defs}{area}{hit}', ylab + xs + dot + tags, height, yg=_chipw(lvt), head=hd, layer=lay, grid=g)

def hbars(items, total=None, color="gold", maxn=12):
    """Horizontal bars as 3D extruded pills on an inset track (style.css .hbars.ck), the value and share at the end."""
    items = items[:maxn]; mx = max((v for _, v in items), default=1) or 1; tot = total or sum(v for _, v in items) or 1
    sc = series_cls(color)
    rows = "".join(f'<div class="hb"><span class="hl" title="{E(str(k))}">{E(str(k))}</span><span class="hbar"><i class="{sc}" style="width:{max(1.5, 100 * v / mx):.1f}%"></i></span><span class="hv num">{v:,} <small>({100 * v / tot:.1f}%)</small></span></div>' for k, v in items)
    return f'<div class="hbars ck">{rows}</div>'
