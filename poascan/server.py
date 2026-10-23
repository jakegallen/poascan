"""POASCAN HTTP server: pages, read-only JSON/CSV API, static files. Python stdlib only."""
import json, hashlib, os, re, csv, io, gzip, time, logging, mimetypes, signal, traceback, urllib.parse
from html import escape as E
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from . import guard as GD
from . import visits as VS
from . import network as NW
from . import keysafe as KS
from . import names as NM
from . import opsinternal as OI
from . import db, analytics as A, agents as G, indexer as I, views as V, views2 as V2, views3 as V3, views4 as V4, live as L, agentapi as AG, start as ST, faq as FQ, ui as UI, og as OG, receipts as RC, records as RR, history as HI, calibration as CA, cohorts as CO, reconcile as RE, maint as MT, swap as SW, swapclient as SC, links as LK

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
ROOT_FILES = {"/favicon.ico": ("favicon.ico", "image/x-icon"), "/favicon.svg": ("favicon.svg", "image/svg+xml"),
              "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"), "/apple-touch-icon-precomposed.png": ("apple-touch-icon.png", "image/png"),
              "/site.webmanifest": ("site.webmanifest", "application/manifest+json")}
log = logging.getLogger("server")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
STARTED = int(time.time())

NUM_RX = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
def cell(v):
    """CSV cell (SC-015): a text value a spreadsheet would run as a formula (=, +, -, @, tab, CR) gets a leading
    apostrophe. Numbers, and text that is just a number such as "-1.5", are left as they are."""
    if isinstance(v, (dict, list)): v = json.dumps(v)
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") and not NUM_RX.match(v): return "'" + v
    return v

def to_csv(rows):
    if not rows: return ""
    buf = io.StringIO(); keys = list(dict.fromkeys(k for r in rows for k in r.keys()))   # union: optional fields still get a column
    w = csv.DictWriter(buf, fieldnames=[cell(k) for k in keys], extrasaction="ignore"); w.writeheader()
    for r in rows: w.writerow({cell(k): cell(v) for k, v in r.items()})
    return buf.getvalue()

INT_RX = re.compile(r"^[+-]?\d{1,18}$")
def qint(qs, k, default, lo, hi):
    """An integer query parameter (SC-002): missing or empty is the default, anything else non-integer is a 400,
    and the value is clamped to [lo, hi]."""
    v = (qs.get(k) or [""])[0].strip()
    if v == "": return default
    if not INT_RX.match(v): raise BadRequest(f"{k} must be an integer from {lo} to {hi}")
    return max(lo, min(hi, int(v)))

TXS_MAX, OFFSET_MAX = 1000, 10_000_000

def api(path, qs):
    """Return (rows_or_obj, is_list). Raises KeyError for unknown routes."""
    if path == "/api/health":
        h = A.health(); st = A.status()
        ok = bool(h["live_last_ok"] and time.time() - h["live_last_ok"] < 300)
        return dict(ok=ok, started=STARTED, live_last_ok=h["live_last_ok"], node_as_of=st.get("as_of"), node_stale=st.get("stale"),
                    txs_indexed=A.tx_counts()["n"], jobs=h["jobs"], endpoints=h["endpoints"]), False
    if path == "/api/summary":
        s = V.summary_json(); return s, False
    if path == "/api/txs":
        lim = qint(qs, "limit", 100, 1, TXS_MAX); off = qint(qs, "offset", 0, 0, OFFSET_MAX); typ = qs.get("type", [""])[0]; ad = qs.get("addr", [""])[0]
        w, a = [], []
        if typ: w.append("type=?"); a.append(typ)
        if ad: w.append("(from_addr=? OR to_addr=?)"); a += [ad, ad]
        sql = "SELECT * FROM txs" + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY ts DESC LIMIT ? OFFSET ?"
        return db.q(sql, tuple(a) + (lim, off)), True
    m = re.match(r"^/api/tx/([0-9a-fA-F]{64})$", path)
    if m: return upstream(lambda: I.get_tx_detail(m.group(1).lower()), "transaction not found"), False
    m = re.match(r"^/api/address/(poa1\w+)/(txs|assignments)$", path)
    if m:
        a, k = m.groups(); c = qs.get("cursor", [""])[0] or None
        if not V.ADDR_RX.match(a): raise BadRequest("address must be a poa1 address")
        lim = qint(qs, "limit", 50, 1, 200)
        try:
            if k == "assignments": return dict(address=a, **HI.assignments(a, c, lim), method=AG.BASE + "/about#history"), False
            typ = qs.get("type", [""])[0] or None; rows, nxt = HI.txs_page(a, c, lim, typ)
        except ValueError: raise BadRequest("bad cursor")
        return dict(address=a, type=typ, txs=rows, next_cursor=nxt, types=HI.type_counts(a), coverage=HI.coverage(a), method=AG.BASE + "/about#history"), False
    m = re.match(r"^/api/address/(poa1\w+)$", path)
    if m:
        a = m.group(1)
        if not V.ADDR_RX.match(a): raise BadRequest("address must be a poa1 address")
        p = G.profile(a); d, err = V.fetch_address(a)
        bal = (d or {}).get("balance")
        if bal is None:   # no fresh read (budget, backoff or busy): the balance from the network's agent list, 15 min old at most
            acc = db.q1("SELECT balance_s, balance FROM accounts WHERE addr=?", (a,))
            if acc: bal = acc["balance_s"] if acc["balance_s"] is not None else acc["balance"]
        return dict(address=a, balance=bal, rewards=p["rewards"], streak=p["streak"], census=p["census"], family_size=(p["family"] or [None, None])[1],
                    forum_name=p["forum_name"], established=a in A.established_set(), addresses=LK.addresses(a), txs=db.q("SELECT * FROM txs WHERE from_addr=? OR to_addr=? ORDER BY ts DESC LIMIT 500", (a, a)), fetch_error=err), False
    m = re.match(r"^/api/agents/([^/]{1,80})/addresses$", path)
    if m:
        a = m.group(1)
        if not V.ADDR_RX.match(a) or not LK.known(a): raise NotFound("unknown agent")
        return dict(agent=a, addresses=LK.addresses(a)), False
    m = re.match(r"^/api/receipt/([0-9a-fA-F]{64})$", path)
    if m:
        r = RC.receipt(m.group(1), fetch=True)
        if not r: raise KeyError(path)
        return r, False
    if path == "/api/receipts":
        a = qs.get("address", [""])[0]
        if not V.ADDR_RX.match(a): raise BadRequest("address must be a poa1 address")
        return RC.for_address(a, qint(qs, "limit", 50, 1, 200)), True
    if path == "/api/epochs": return A.epoch_rows(), True
    if path == "/api/price" or path == "/api/swaps" or path.startswith("/api/swaps/"): return SW.api(path, qs)   # the swap module's routes
    if path == "/api/agents/new-per-day": return G.new_per_day(), True
    if path == "/api/concentration": return A.concentration(), False
    if path == "/api/clusters":
        cs = dict(G.cluster_signals()); sg = qs.get("signal", [""])[0]
        if sg: cs["groups"] = [g for g in cs["groups"] if g["signal"] == sg]
        return cs, False
    if path == "/api/uptime":
        rows = V2.uptime_rows(); ep = qs.get("endpoint", [""])[0]
        return ([r for r in rows if r["endpoint"] == ep] if ep else rows), True
    if path == "/api/unlocks": return V3.unlocks_api(), True
    if path.startswith("/api/leaderboard/"):
        t = path.rsplit("/", 1)[1]; t = V4.ALIAS.get(t, t)
        if t not in V4.COLS: return {"error": "unknown tab", "tabs": list(V4.COLS)}, False
        return V4.rows(t), True
    if path == "/api/status":
        d = V2.status_data(); return dict(endpoints=d["eps"], incidents=[dict(start=a, end=b, what=w, fails=f) for a, b, w, f in d["inc"]], anchors=d["anchors"], last_checkpoint_change=d["last_cp_change"], **V.joins_fields()), False
    m = re.match(r"^/api/epoch/(\d{1,9})$", path)
    if m:
        r = [x for x in A.epoch_rows() if x["epoch"] == int(m.group(1))]
        if not r: raise KeyError
        return dict(r[0], rewards=A.epoch_detail(int(m.group(1))).get("rewards")), False
    if path == "/api/richlist": return [{k: r[k] for k in ("rank", "addr", "balance", "share", "src")} for r in A.holders()["rows"]], True
    if path in ("/api/agents/series", "/api/accounts/series"): return [dict(ts=p[0], accounts=p[1], holders=p[2], supply=p[3], window_txs=p[4]) for p in A.accounts_series()], True
    if path == "/api/forum":
        f = dict(A.forum()); f["top_threads"] = [{k: t[k] for k in ("id", "title", "community", "comment_count", "score")} for t in f["top_threads"]]; return f, False
    if path == "/api/pending-by-epoch": return A.pending_by_epoch(), False
    if path == "/api/grading": return [{k: r[k] for k in ("epoch", "pending", "pending_short", "pending_appeal", "pending_empty_panel", "settled", "settled_passed", "graders", "grades", "slashed")} for r in A.epoch_rows()], True
    if path == "/api/anchors": return A.anchors_latest(500), True
    if path == "/api/params": return {k: v for k, v in A.params().items() if not k.startswith("swap_fee")}, False
    if path == "/api/chains": return db.get_blob("chains")[0] or {}, False
    if path == "/api/agents/health": return G.network_health(), False
    if path == "/api/agents/leaderboard": return G.leaderboard()["by_family"], True
    if path == "/api/agents/leaderboard-harness": return G.leaderboard()["by_harness"], True
    if path == "/api/agents/census": return G.census_series(), True
    if path == "/api/agents/funnel": return G.funnel()["overall"], False
    if path == "/api/agents/retention": return G.retention(), True
    if path == "/api/agents/originality": return G.originality()["epochs"], True
    if path == "/api/agents/traits": return G.answer_traits(), False
    if path == "/api/agents/operators":
        o = dict(G.operators()); o.pop("fam_of", None); return o, False
    if path == "/api/agents/graders": return [dict(grader=g, settled=n, aligned=al, rate=r, served=s, trusted=t) for g, n, al, r, s, t in G.graders()["graders"]], True
    if path == "/api/reconcile": return dict(RE.reconcile(), method=AG.BASE + "/about#reconcile"), False
    if path == "/api/cohorts": return dict(CO.cohorts(), rows=CO.rows(), method=AG.BASE + "/about#cohorts"), False
    if path == "/api/agents/calibration":
        by = qs.get("sort", ["name"])[0]
        if by not in ("name", "n"): raise BadRequest("sort is name or n")
        c, rows = CA.sorted_rows(by); return dict({k: v for k, v in c.items() if k != "graders"}, sort=by, rows=rows, method=AG.BASE + "/about#calibration"), False
    if path == "/api/agents/streaks": return [dict(addr=a, longest=b, current=c) for a, (b, c) in sorted(G.streaks().items(), key=lambda kv: -kv[1][0])], True
    if path == "/api/agents/activity-clock": return G.activity_clock(), False
    if path == "/api/agents/social": return G.social(), False
    if path == "/api/agents/builders":
        b = dict(G.builders()); return b, False
    raise KeyError(path)

PREFIX_HEX = re.compile(r"^[0-9a-fA-F]{6,63}$")
PREFIX_ADDR = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{2,59}$")
def prefix_hits(q, n=20):
    """Index range scans on the primary keys: txs by id prefix, Agents by address prefix (base58 is case-sensitive)."""
    if PREFIX_HEX.match(q):
        lo = q.lower(); rows = db.q("SELECT id, type FROM txs WHERE id >= ? AND id < ? ORDER BY id LIMIT ?", (lo, lo + "g", n))
        out = [dict(kind="transaction", id=r["id"], type=r["type"]) for r in rows]
        if out or not PREFIX_ADDR.match(q): return out
    rows = db.q("SELECT addr FROM accounts WHERE addr >= ? AND addr < ? ORDER BY addr LIMIT ?", (q, q + "\U0010ffff", n))
    return [dict(kind="address", id=r["addr"]) for r in rows]

def page(path, qs):
    if path in ("/", "/index.html"): return V.home()
    if path == "/txs": return V.txs(qs)
    m = re.match(r"^/tx/([0-9a-fA-F]{64})$", path)
    if m: return V.tx(m.group(1).lower())
    m = re.match(r"^/address/(poa1\w+)$", path)
    if m: return V.address(m.group(1))
    if path == "/token": return V.token()
    if path == SW.config.PAGE_PATH: return SW.page(path)
    if path in ("/start", "/join", "/onboarding"): return ST.page(V.page)
    if path == "/agents/graders": return V.graders_page(qs)
    if path == "/agents/top": return V4.leaderboard_page(qs.get("tab", [""])[0], V.apage)
    if path == "/unlocks": return V.page("Unlocks", '<div class="sechead"><h1>Unlocks</h1></div>' + V3.unlock_section(), "/token")
    if path == "/upgrade": return V2.status_page("Network upgrade")
    if path in ("/epochs", "/blocks"): return V.epochs_page(qs)
    m = re.match(r"^/epoch/(\d+)$", path)
    if m: return V.epoch(int(m.group(1)))
    tab = (qs.get("tab") or [""])[0]
    if path == "/agents/census": return V.census_page(tab)
    if path == "/agents/community": return V.community_page(tab)
    if path == "/network": return V.network(tab, (qs.get("range") or [""])[0])
    routes = {"/agents": V.agents_overview, "/agents/operators": V.operators_page, "/about": V.about, "/privacy": V.privacy}
    if path in routes: return routes[path]()
    return None

AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "PerplexityBot", "Perplexity-User",
           "Google-Extended", "Applebot-Extended", "CCBot"]
VS.BOT_NAMES = AI_BOTS
from . import prompts as _PR
VS.API_SRC = lambda: AG.openapi()["paths"]; VS.MCP_TOOLS = frozenset(AG.TOOL_FN); VS.PROMPT_IDS = _PR.ids()
AG.ON_TOOL = lambda name: VS.COUNTER.event("mcp", name)   # tool name only, never the arguments
EVENT_LIMIT = AG.Limiter(0.5, 20)   # POST /ops/e: per IP, in memory
NAME_LIMIT = AG.Limiter(2, 40)      # GET /api/v1/agents/name-available: per IP, in memory (typing checks, debounced)
PROMPT_LIMIT = AG.Limiter(0.5, 30)   # GET /api/v1/prompts/join: per IP, in memory
OPS_LIMIT = AG.Limiter(0.2, 10)     # GET /ops/visits, /ops/network and /ops/internal: per IP, in memory, apart from MCP
# GET /address/* and /tx/* HTML pages, per Fly-Client-IP, in memory only (a token bucket, dropped after 2 idle minutes).
# A person reading pages stays far inside it; a crawler walking every address gets 429 with Retry-After. /api, /healthz,
# /static, /fragment and everything else are not limited here, so API mirrors (POASwap polls every 60 s and 120 s) never see it.
PAGE_LIMIT = AG.Limiter(float(os.environ.get("POASCAN_PAGE_RATE", "0.5")), int(os.environ.get("POASCAN_PAGE_BURST", "60")))
PAGE_LIMITED = re.compile(r"^/(address|tx)/[^/]+$")
_fci_seen = [False]
ROBOTS = ("User-agent: *\nAllow: /\nDisallow: /ws\nDisallow: /fragment/\n\n" + "".join(f"User-agent: {b}\n" for b in AI_BOTS)
          + "Allow: /\nDisallow: /ws\nDisallow: /fragment/\n\nSitemap: https://poascan.io/sitemap.xml\n")

AGENTPEERING_VERIFY = "ap-verify-cec18af41a029ed83d4e21ee0268f52c"  # public verification string for agentpeering.com

STATIC_ROUTES = ["/", "/start", "/txs", "/epochs", "/token", "/unlocks", "/agents", "/agents/top", "/agents/census",
                 "/agents/operators", "/agents/graders", "/agents/community", "/network", "/about", "/privacy", "/api"]

# Batch 3 merged pages into tabs. Every old URL keeps working: 301 to its new home (query strings that still mean something are kept).
MOVED = {"/live": "/epochs?tab=pending", "/grading": "/epochs?tab=grading", "/growth": "/network?tab=charts", "/status": "/network?tab=health",
         "/forum": "/agents/community", "/community": "/agents/community", "/agents/social": "/agents/community?tab=social",
         "/agents/builders": "/agents/community?tab=builders", "/agents/answers": "/agents/community?tab=answers",
         "/agents/leaderboard": "/agents/top?tab=ai", "/agents/journey": "/agents/census?tab=journey", **FQ.REDIRECTS}
# The swap HTML moved to POASwap (2026-10-22). Only these HTML paths leave; every /api/v1/swaps*, /api/swaps, /api/price and
# price-history route stays here unchanged, and so do the swap jobs. Query strings are dropped (the target is fixed).
OFFSITE = {"/swaps": "https://poaswap.io/", "/how-to-buy-poa": "https://poaswap.io/about#faq"}
def offsite(path): return OFFSITE.get(path.rstrip("/") or "/")
def moved(path, qs):
    if path == "/find":
        q = (qs.get("q", [""])[0] or "").strip()
        return "/search?" + urllib.parse.urlencode({"q": q}) if q else "/#find"
    return MOVED.get(path)
V.ROUTES = STATIC_ROUTES
_SITEMAP = [0, ""]
def sitemap():
    """Static routes, every epoch close and the top 500 holders. Rebuilt at most every 10 min."""
    if time.time() - _SITEMAP[0] < 600 and _SITEMAP[1]: return _SITEMAP[1]
    base = "https://poascan.io"; ep = A.epoch_rows(); day = lambda t: time.strftime("%Y-%m-%d", time.gmtime(t or time.time()))
    last = day(max([r["close_ts"] or 0 for r in ep] or [0]) or None)
    urls = [(base + p, last) for p in STATIC_ROUTES] + [(f"{base}/epoch/{r['epoch']}", day(r["close_ts"])) for r in ep]
    try: urls += [(f"{base}/address/{r['addr']}", last) for r in A.holders()["rows"][:500]]
    except Exception: pass
    body = "".join(f"<url><loc>{E(u)}</loc><lastmod>{d}</lastmod></url>" for u, d in urls)
    _SITEMAP[:] = [time.time(), '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</urlset>\n"]
    return _SITEMAP[1]

UI.JSONLD_HOOK = FQ.jsonld
UI.OG_HOOK = OG.url_for
UI.DESCS.update({p: d["desc"] for p, d in FQ.PAGES.items()})
HUB = L.Hub(lambda: V.live_snapshot())

EM, EN, EMJ, ENJ = chr(0x2014), chr(0x2013), "\\u2014", "\\u2013"
_DASH = re.compile(r"\s*(?:" + EM + "|" + re.escape(EMJ) + r")\s*")
def nodash(t):
    """House rule: no em dashes anywhere, including upstream text we relay. Em dash -> comma, en dash -> hyphen."""
    if EM not in t and EMJ not in t and EN not in t and ENJ not in t: return t
    return _DASH.sub(", ", t).replace(EN, "-").replace(ENJ, "-")

MCP_HDRS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Accept, Mcp-Session-Id, MCP-Protocol-Version, Last-Event-ID",
            "Access-Control-Expose-Headers": "Mcp-Session-Id", "Allow": "POST, OPTIONS"}
TXT = "text/plain; charset=utf-8"
HSTS = "max-age=31536000"
CANONICAL = os.environ.get("POASCAN_CANONICAL", "https://poascan.io").rstrip("/")   # the apex www. redirects to
MPID = re.compile(rb'"mp\d+"')
IMMUTABLE = "public, max-age=31536000, immutable"

QS_RX = re.compile(r"\?[^\s\"']*")   # query strings (searches included) never reach the log

class BadRequest(Exception): pass
class NotFound(Exception): pass   # a known route with an unknown subject: 404 with the reason
class TooMany(Exception):         # the per-client or global on-demand upstream budget is spent: 429 with Retry-After
    def __init__(self, msg, retry): super().__init__(msg); self.retry = max(1, int(retry or 1))
class Unavailable(Exception): pass   # upstream busy or backing off and nothing stored: 503

def upstream(fn, missing):
    """Run an on-demand upstream read for the API: unknown ids are 404, a spent budget 429, a busy node 503 (never 500)."""
    try: d = fn()
    except I.Missing: raise NotFound(missing)
    except I.Limited as e: raise TooMany(str(e), e.retry)
    except I.Busy as e: raise Unavailable(str(e) or "upstream busy")
    if not (isinstance(d, dict) and d.get("id")): raise NotFound(missing)
    return d

class H(BaseHTTPRequestHandler):
    timeout = 20   # a slow or idle client cannot hold a request thread for longer than this
    server_version = "POASCAN/1.0"
    def log_message(self, fmt, *a):   # no address (on Fly the peer is the proxy) and no query string; paths pass the redaction filter
        log.info("%s", QS_RX.sub("", fmt % a))
    def parse_request(self):
        self._t0 = time.monotonic(); return super().parse_request()
    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        try:
            ms = (time.monotonic() - self._t0) * 1000 if getattr(self, "_t0", None) else None
            VS.COUNTER.hit(self.command, code, self.path, self.headers.get("User-Agent"), self.headers.get("Referer"), self.client_ip, ms, self.headers.get("Fly-Region"))
        except Exception: pass   # counting never breaks a response
        if isinstance(body, str) and ("html" in ctype or "json" in ctype or ctype.startswith("text/")): body = nodash(body)
        if isinstance(body, str) and "json" in ctype: body = AG.plainjson(body)
        if isinstance(body, str): body = KS.redact(body)   # no key-shaped token in any text response (forum text, memos, errors)
        b = body.encode() if isinstance(body, str) else body
        gz = (len(b) > 1400 and "gzip" in (self.headers.get("Accept-Encoding") or "") and
              (ctype.startswith("text/") or "json" in ctype or "javascript" in ctype or "svg" in ctype or "manifest" in ctype))
        hdr = dict(extra or {})
        if code == 200 and ctype.startswith("text/html") and "Cache-Control" not in hdr:
            tag = 'W/"' + hashlib.sha1(MPID.sub(b"", b)).hexdigest()[:16] + '"'  # toggle ids count up per render; ignore them
            hdr.update({"ETag": tag, "Cache-Control": "no-cache"})
            if tag in (self.headers.get("If-None-Match") or ""):
                self.send_response(304); self.send_header("ETag", tag); self.send_header("Cache-Control", "no-cache"); self.send_header("Strict-Transport-Security", HSTS)
                self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Referrer-Policy", "no-referrer"); self.end_headers(); return
        if gz: b = gzip.compress(b, 5)
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        if gz: self.send_header("Content-Encoding", "gzip"); self.send_header("Vary", "Accept-Encoding")
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Referrer-Policy", "no-referrer"); self.send_header("Strict-Transport-Security", HSTS)
        self.send_header("Content-Security-Policy", CSP); self.send_header("X-Frame-Options", "DENY"); self.send_header("Permissions-Policy", PERMS)
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        for k, v in hdr.items(): self.send_header(k, KS.redact(str(v)))
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(b)
    def do_HEAD(self): self.do_GET()
    def cond(self, body, sha, cache, extra):
        """Strong ETag = the body's sha256 (of the decoded bytes, whatever the transfer encoding); 304 on a matching If-None-Match."""
        tag = f'"{sha}"'; hd = dict(extra, **{"ETag": tag, "Cache-Control": cache, "Access-Control-Allow-Origin": "*"})
        hd["Access-Control-Expose-Headers"] = ", ".join(x for x in (hd.get("Access-Control-Expose-Headers"), "ETag, X-Record-SHA256, X-Record-Bytes, X-Next-From") if x)
        inm = [t.strip().removeprefix("W/") for t in (self.headers.get("If-None-Match") or "").split(",") if t.strip()]
        if tag in inm or "*" in inm: return self.send(304, b"", "application/json", hd)
        return self.send(200, body, "application/json", hd)
    def records(self, p, qs, fmt):
        m = AG.meta(); mh = AG.meta_headers(m)
        def nf(msg, **k): return self.send(404, json.dumps(dict(error=msg, **k)), "application/json", dict(mh, **{"Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=60"}))
        ix = RR.index(); last = ix[-1]["epoch"] if ix else None
        mm = re.match(r"^/api/epoch/(\d+)/record$", p)
        if mm:
            n = int(mm.group(1)); r = RR.record(n)
            if not r: return nf(f"no close record for epoch {n}", last_close=last)
            b, h = r
            return self.cond(b, h, RR.IMMUTABLE, dict(mh, **{"X-Record-SHA256": h, "X-Record-Bytes": str(len(b)), "X-Canonical": RR.CANON}))
        fr = qs.get("from", [None])[0]
        rows = [dict(r, url=f"{AG.BASE}{AG.API_PREFIX}/epoch/{r['epoch']}/record") for r in ix]
        if fr is None:
            if fmt == "csv": return self.send(200, to_csv(rows), "text/csv; charset=utf-8", dict(mh, **{"Content-Disposition": 'attachment; filename="api_epoch_records.csv"', "Access-Control-Allow-Origin": "*"}))
            b = RR.canonical(rows); return self.cond(b, RR.sha256(b), "max-age=60", mh)
        if not fr.isdigit(): return self.send(400, json.dumps({"error": "from must be a closed epoch number"}), "application/json", mh)
        try: lim = qint(qs, "limit", RR.FROM_MAX, 1, RR.FROM_MAX)
        except BadRequest as e: return self.send(400, json.dumps({"error": str(e)}), "application/json", mh)
        if len(fr) > 9: return self.send(404, json.dumps({"error": f"no close record for epoch {fr}", "last_close": last}), "application/json", mh)
        b, nxt = RR.page(int(fr), lim)
        return self.cond(b, RR.sha256(b), "max-age=60", dict(mh, **({"X-Next-From": str(nxt)} if nxt is not None else {})))
    def client_ip(self):
        return (self.headers.get("Fly-Client-IP") or (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or self.client_address[0])
    def ops_event(self):
        """POST /ops/e {"e": "<id>"}: one prompt button click, by a fixed id from prompts.ids(). No cookie is read or set,
        nothing about the sender is kept; unknown ids, other origins, big bodies and bursts are refused. 204 when counted."""
        hd = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}
        ok, wait = EVENT_LIMIT.allow(self.client_ip())
        if not ok: return self.send(429, "", TXT, dict(hd, **{"Retry-After": str(wait)}))
        org = self.headers.get("Origin")
        if org and org != "null":
            oh = (urllib.parse.urlsplit(org).hostname or "").lower(); host = (self.headers.get("Host") or "").split(":")[0].lower()
            if oh != host and oh not in VS.OWN_HOSTS: return self.send(403, "", TXT, hd)
        n = self.headers.get("Content-Length") or ""
        if not n.isdigit() or int(n) > 256: return self.send(413 if n.isdigit() else 411, "", TXT, hd)
        try: e = json.loads(self.rfile.read(int(n)) or b"null")
        except Exception: e = None
        e = e.get("e") if isinstance(e, dict) else None
        if not isinstance(e, str) or e not in VS.PROMPT_IDS: return self.send(400, json.dumps({"error": "unknown event"}), "application/json", hd)
        if VS.kind("/", self.headers.get("User-Agent") or "") == "human": VS.COUNTER.event("prompt", e)
        return self.send(204, b"", TXT, hd)
    def do_POST(self):
        """The only write-shaped methods we accept are JSON-RPC to the read-only MCP server and the click count."""
        I.CLIENT.ip = self.client_ip()
        pth = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if pth == "/ops/e":
            try: return self.ops_event()
            except BrokenPipeError: return
            except Exception as e:
                log.error("ops event: %s", type(e).__name__)
                try: return self.send(500, "", TXT, {"Cache-Control": "no-store"})
                except Exception: return
        if pth != "/mcp": return self.send(405, "read-only", "text/plain", {"Allow": "GET, HEAD"})
        try:
            ok, wait = AG.LIMIT.allow(self.client_ip())
            if not ok: return self.send(429, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "rate limited"}}), "application/json", dict(MCP_HDRS, **{"Retry-After": str(wait)}))
            n = self.headers.get("Content-Length") or ""
            n = int(n) if n.isdigit() else -1
            if n < 0: return self.send(411, json.dumps(AG._err(None, -32600, "Content-Length required")), "application/json", MCP_HDRS)
            if n > 65536: return self.send(413, json.dumps(AG._err(None, -32600, "request too large")), "application/json", MCP_HDRS)
            pv = self.headers.get("MCP-Protocol-Version")
            if pv and pv not in AG.PROTOCOLS: return self.send(400, json.dumps(AG._err(None, -32600, "unsupported MCP-Protocol-Version")), "application/json", MCP_HDRS)
            raw = self.rfile.read(n)
            if KS.has_key(raw):   # MCP tools never take keys; refuse without echoing the request
                log.warning("refused an MCP call with a key-shaped value (not logged)")
                return self.send(400, json.dumps(AG._err(None, -32602, KS.WARN)), "application/json", dict(MCP_HDRS, **{"Cache-Control": "no-store"}))
            extra = AG.batch_size(raw) - 1   # SC-013: a batch spends one token per message, not one per POST
            if extra > 0:
                ok, wait = AG.LIMIT.allow(self.client_ip(), extra)
                if not ok: return self.send(429, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "rate limited"}}), "application/json", dict(MCP_HDRS, **{"Retry-After": str(wait)}))
            code, out = AG.handle_mcp(raw)
            if out is None: return self.send(202, b"", "application/json", MCP_HDRS)
            return self.send(code, json.dumps(out, default=str), "application/json", dict(MCP_HDRS, **{"Cache-Control": "no-store"}))
        except BrokenPipeError: pass
        except Exception as e:
            log.error("mcp error: %s\n%s", e, traceback.format_exc())
            try: self.send(500, json.dumps(AG._err(None, -32603, "internal error")), "application/json", MCP_HDRS)
            except Exception: pass
    def do_OPTIONS(self):
        if (urllib.parse.urlparse(self.path).path.rstrip("/") or "/") == "/mcp": return self.send(204, b"", "text/plain", MCP_HDRS)
        return self.send(405, "read-only", "text/plain", {"Allow": "GET, HEAD"})
    def do_PUT(self): self.send(405, "read-only", "text/plain", {"Allow": "GET, HEAD"})
    do_DELETE = do_PATCH = do_PUT
    def www(self):
        """www.poascan.io redirects to the apex, keeping path and query. Fly health checks use the machine address, never www."""
        host = (self.headers.get("Host") or "").lower()
        if not host.startswith("www."): return False
        off = offsite(urllib.parse.urlparse(self.path).path)   # one hop for the moved swap pages
        self.send(301, "", TXT, {"Location": off or (CANONICAL + self.path), "Cache-Control": "public, max-age=86400"}); return True   # never built from Host
    def key_guard(self):
        """Anything key-shaped in the path or query, or a credential parameter, is refused before routing:
        never fetched upstream, never logged, stored, cached, echoed or redirected."""
        raw = self.path or ""; q = raw.partition("?")[2]
        if not (KS.has_key(raw) or KS.has_cred_param(q)): return False
        log.warning("refused a request with a key-shaped value (not logged)")
        self.send(400, KS.WARN + "\n", TXT, {"Cache-Control": "no-store"}); return True
    def ops_gate(self, path, qs, parse=VS.parse_range):
        """Shared gate for the private /ops JSON: without POASCAN_STATS_TOKEN set, or without the right Bearer token, the
        normal 404 page, byte for byte. Rate limited per IP; never cached, indexed or CORS-enabled.
        Returns (headers, from, to) when the caller may answer, else None after sending the response."""
        ok, _ = OPS_LIMIT.allow(self.client_ip())   # checked first, own bucket: over the limit is the same 404, token or not
        if not ok or not VS.token_ok(self.headers.get("Authorization")): self.send(404, V.not_found(path=path)); return None
        hd = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}
        try: fr, to = parse(qs)
        except ValueError as e: self.send(400, json.dumps({"error": str(e)}), "application/json", hd); return None
        return hd, fr, to
    def ops_visits(self, path, qs):
        """Private daily visit totals (gate: ops_gate)."""
        g = self.ops_gate(path, qs)
        if not g: return
        hd, fr, to = g
        try: VS.COUNTER.flush(); out = json.dumps(VS.report(fr, to))
        except Exception as e:
            log.error("ops visits: %s", type(e).__name__); return self.send(500, json.dumps({"error": "internal"}), "application/json", hd)
        return self.send(200, out, "application/json", hd)
    def ops_network(self, path, qs):
        """Private daily network aggregates from the archive (poascan/network.py; gate: ops_gate). No upstream call."""
        g = self.ops_gate(path, qs)
        if not g: return
        hd, fr, to = g
        try: out = NW.report(fr, to)
        except Exception as e:
            log.error("ops network: %s", type(e).__name__); return self.send(500, json.dumps({"error": "internal"}), "application/json", hd)
        return self.send(200, out, "application/json", hd)
    def ops_internal(self, path, qs):
        """Private ops stats for POASwap's dashboard (poascan/opsinternal.py; gate: ops_gate). At most 31 days, default 7.
        Only from and to are accepted: any other query parameter (a token in the URL included) is a 400. No upstream call."""
        g = self.ops_gate(path, qs, OI.parse_range)
        if not g: return
        hd, fr, to = g
        if set(qs) - {"from", "to"}: return self.send(400, json.dumps({"error": "only from and to are accepted; send the token in the Authorization header"}), "application/json", hd)
        try: out = json.dumps(OI.report(fr, to, AG.VERSION))
        except Exception as e:
            log.error("ops internal: %s", type(e).__name__); return self.send(500, json.dumps({"error": "internal"}), "application/json", hd)
        return self.send(200, out, "application/json", hd)
    def page_limited(self):
        """True after sending a 429 for an /address or /tx page over the per-client budget. Keyed on Fly-Client-IP only:
        without it (local runs) nothing is limited, since every request would share the proxy address. The IP is never logged."""
        ip = (self.headers.get("Fly-Client-IP") or "").strip()
        if not _fci_seen[0]:
            _fci_seen[0] = True; log.info("page limit: Fly-Client-IP header present=%s", bool(ip))   # presence only, once per process
        if not ip: return False
        ok, wait = PAGE_LIMIT.allow(ip)
        if ok: return False
        self.send(429, "Too many page requests. Please slow down; the JSON API at /api/v1 is the better fit for bulk reads.\n", TXT,
                  {"Retry-After": str(wait), "Cache-Control": "no-store"})
        return True
    def do_GET(self):
        I.CLIENT.ip = self.client_ip()   # for the on-demand upstream budget (memory only, this request)
        if self.key_guard(): return
        if self.www(): return
        u = urllib.parse.urlparse(self.path); path = u.path.rstrip("/") or "/"; qs = urllib.parse.parse_qs(u.query)
        off = offsite(path)
        if off: return self.send(301, "", TXT, {"Location": off, "Cache-Control": "public, max-age=3600"})
        if path == AG.API_PREFIX: path = "/api"                                   # /api/v1 is canonical; /api/... stays as an alias
        elif path.startswith(AG.API_PREFIX + "/"): path = "/api/" + path[len(AG.API_PREFIX) + 1:]
        V.REQ.path, V.REQ.qs = path, qs
        if PAGE_LIMITED.match(path) and self.page_limited(): return
        if path == "/ops/visits": return self.ops_visits(path, qs)
        if path == "/ops/network": return self.ops_network(path, qs)
        if path == "/ops/internal": return self.ops_internal(path, qs)
        try:
            if path == "/ws":
                return HUB.accept(self)
            if path in ("/api/summary", "/api/live"):
                m = AG.meta(); d = json.loads(HUB.snapshot()) if path == "/api/summary" else dict(HUB.stats())
                if isinstance(d, dict):
                    if path == "/api/summary": d["swaps"] = SC.status(); d["concentration"] = A.concentration()
                    d.setdefault("meta", m)
                return self.send(200, json.dumps(d, default=str), "application/json", dict(AG.meta_headers(m), **{"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"}))
            if path in SW.STATIC:   # the swap module's own assets, same URLs as before
                f, ct = SW.STATIC[path]
                return self.send(200, open(f, "rb").read(), ct, {"Cache-Control": IMMUTABLE if "v" in qs else "public, max-age=3600"})
            if path.startswith("/static/"):
                f = os.path.normpath(os.path.join(STATIC, path[8:]))
                if not f.startswith(os.path.normpath(STATIC)) or not os.path.isfile(f): return self.send(404, "not found", "text/plain")
                ct = {".ico": "image/x-icon", ".webmanifest": "application/manifest+json", ".woff2": "font/woff2"}.get(os.path.splitext(f)[1]) or mimetypes.guess_type(f)[0] or "application/octet-stream"
                return self.send(200, open(f, "rb").read(), ct, {"Cache-Control": IMMUTABLE if "v" in qs else "public, max-age=3600"})
            if path in ROOT_FILES:
                fn, ct = ROOT_FILES[path]
                return self.send(200, open(os.path.join(STATIC, fn), "rb").read(), ct, {"Cache-Control": "public, max-age=86400"})
            if path.startswith("/og/"):
                r = OG.render(path) if OG.available() else None
                if r: return self.send(200, r[0], "image/png", {"Cache-Control": f"public, max-age={r[1]}"})
                if OG.ROUTE.match(path) or path == "/og/upgrade.png": return self.send(200, open(os.path.join(STATIC, "og-card.png"), "rb").read(), "image/png", {"Cache-Control": "public, max-age=3600"})
                return self.send(404, "not found", TXT)
            if path == "/healthz":   # answered by a request thread after a real DB read, so a hung server or locked DB fails it
                db.q1("SELECT 1 AS x"); return self.send(200, "ok\n", TXT, {"Cache-Control": "no-store"})
            if path == "/robots.txt": return self.send(200, ROBOTS, TXT, {"Cache-Control": "public, max-age=3600"})
            if path == "/sitemap.xml": return self.send(200, sitemap(), "application/xml; charset=utf-8", {"Cache-Control": "public, max-age=600"})
            if path == "/mcp": return self.send(405, json.dumps(AG._err(None, -32000, "Method not allowed: POST JSON-RPC to /mcp (stateless Streamable HTTP, no SSE stream)")), "application/json", MCP_HDRS)
            if path == "/openapi-gpt.json": return self.send(200, json.dumps(AG.openapi_gpt(), indent=1), "application/json", {"Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=300"})
            if path == "/openapi.json": return self.send(200, json.dumps(AG.openapi(), indent=1), "application/json", {"Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=300"})
            if path == "/llms-full.txt": return self.send(200, AG.llms_full_txt(), TXT, {"Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=300"})
            if path in ("/mcp/server-card", "/.well-known/mcp/server-card.json", "/.well-known/mcp-server-card"):
                ct = "application/json" if path.endswith(".json") else "application/mcp-server-card+json"
                return self.send(200, json.dumps(AG.server_card(), indent=1), ct, {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET", "Cache-Control": "public, max-age=3600"})
            if path == "/.well-known/agentpeering-verify": return self.send(200, AGENTPEERING_VERIFY, TXT, {"Cache-Control": "public, max-age=3600"})
            if path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
                return self.send(200, json.dumps(AG.agent_card(), indent=1), "application/json", {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=3600"})
            if path == f"/{AG.INDEXNOW_KEY}.txt": return self.send(200, AG.INDEXNOW_KEY, TXT, {"Cache-Control": "public, max-age=86400"})
            if V.SITE_VERIFY.get("google_file") and path == "/" + V.SITE_VERIFY["google_file"]:
                return self.send(200, "google-site-verification: " + V.SITE_VERIFY["google_file"], "text/html; charset=utf-8")
            if path == "/BingSiteAuth.xml" and V.SITE_VERIFY.get("bing"):
                return self.send(200, f'<?xml version="1.0"?>\n<users>\n\t<user>{E(V.SITE_VERIFY["bing"])}</user>\n</users>\n', "application/xml; charset=utf-8")
            if path in ("/.well-known/ai-catalog.json", "/.well-known/mcp/catalog.json"):
                return self.send(200, json.dumps(AG.ai_catalog(), indent=1), "application/ai-catalog+json", {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=3600"})
            if path in ("/llms.txt", "/.well-known/llms.txt"): return self.send(200, AG.llms_txt(), TXT, {"Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=300"})
            if path == "/.well-known/mcp.json": return self.send(200, json.dumps(AG.mcp_manifest(), indent=1), "application/json", {"Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=300"})
            if path == "/api": return self.send(200, AG.api_page(V.page, V.card))
            if path == "/mining": return self.send(302, "", extra={"Location": "/agents"})
            if path == "/upgrade" and not MT.state()["active"]: return self.send(302, "", extra={"Location": "/network?tab=health"})
            loc = moved(path, qs)
            if loc: return self.send(301, "", TXT, {"Location": loc, "Cache-Control": "public, max-age=3600"})
            if path == "/search":
                q = (qs.get("q", [""])[0] or "").strip()
                # counted: the outcome only (address, tx, epoch, list or none). The query is never counted, stored or logged.
                cnt = lambda r: q and VS.COUNTER.event("search", r)
                if re.match(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$", q): loc = "/address/" + q; cnt("address")
                elif HEX64.match(q): loc = "/tx/" + q.lower(); cnt("tx")
                elif re.match(r"^[Ee]?\d{1,7}$", q): loc = "/epoch/" + q.lstrip("Ee"); cnt("epoch")
                elif PREFIX_HEX.match(q) or PREFIX_ADDR.match(q):   # partial hash or address: one match goes there, several list
                    hits = prefix_hits(q)
                    if len(hits) == 1: loc = ("/tx/" if hits[0]["kind"] == "transaction" else "/address/") + hits[0]["id"]; cnt("tx" if hits[0]["kind"] == "transaction" else "address")
                    elif hits: cnt("list"); return self.send(200, V.search_hits(q, hits))
                    else: cnt("none"); return self.send(404, V.search_results(q))
                else:
                    hits = [h for h in AG.t_search({"query": q})["results"] if h.get("kind") == "address"] if len(q) >= 2 else []
                    exact = [h for h in hits if (h.get("name") or "").lower() == q.lower()]
                    if len(exact) == 1 or len(hits) == 1: loc = "/address/" + (exact or hits)[0]["id"]; cnt("address")
                    elif hits: cnt("list"); return self.send(200, V.search_hits(q, hits[:20]))
                    else: cnt("none"); return self.send(404, V.search_results(q))
                return self.send(302, "", extra={"Location": loc})
            if path == "/fragment/addr":
                try: return self.send(200, json.dumps(V.addr_fragment(qs)), "application/json", {"Cache-Control": "no-store"})
                except ValueError: return self.send(400, json.dumps({"error": "bad cursor or address"}), "application/json")
            if path == "/fragment/suggest":   # header search typeahead: agent names from the local archive only (no upstream call)
                q = (qs.get("q", [""])[0] or "").strip().lower()[:40]; out = []
                if len(q) >= 2:
                    nm = A.forum_names(); hits = [(n.lower().find(q), len(n), a, n) for a, n in nm.items() if n and q in n.lower()]
                    out = [dict(id=a, name=n) for _, _, a, n in sorted(hits) if V.ADDR_RX.match(a or "")][:6]   # SC-014: addresses only
                return self.send(200, json.dumps(out), "application/json", {"Cache-Control": "public, max-age=60"})
            if path == "/fragment/lb":   # Rankings Load more
                try: return self.send(200, json.dumps(V4.fragment(qs)), "application/json", {"Cache-Control": "no-store"})
                except ValueError: return self.send(400, json.dumps({"error": "bad tab or offset"}), "application/json")
            if path == "/fragment/rows":   # new txs or closes for a live table, local archive only
                h = V.live_rows(qs.get("t", [""])[0])
                if h is None: return self.send(404, "", "text/plain")
                return self.send(200, h, extra={"Cache-Control": "no-store"})
            if path == "/fragment/upgrade":   # the live /upgrade view, refetched by app.js when the snapshot's upsig changes
                if not MT.state()["active"]: return self.send(404, "", "text/plain")
                return self.send(200, f'<div data-upview data-sig="{V2.upgrade_sig()}">{V2.upgrade_view()}</div>', extra={"Cache-Control": "no-store"})
            if path.startswith("/fragment/feed"): return self.send(200, V.feed_rows(), extra={"Cache-Control": "no-store"})
            if path.startswith("/api/"):
                fmt = "csv" if path.endswith(".csv") else qs.get("format", ["json"])[0]
                p = path[:-4] if path.endswith(".csv") else path
                if p == "/api/epoch-records" or re.match(r"^/api/epoch/\d+/record$", p): return self.records(p, qs, fmt)
                if p == "/api/agents/name-available":   # names.available: POAScan's archive only, no upstream read; the name is never logged
                    ok, wait = NAME_LIMIT.allow(self.client_ip())
                    hd = {"X-API-Version": AG.VERSION, "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS"}
                    if not ok: return self.send(429, json.dumps({"error": "rate limited"}), "application/json", dict(hd, **{"Retry-After": str(wait), "Cache-Control": "no-store"}))
                    nq = qs.get("name") or [""]
                    code, d = NM.available(nq[0] if len(nq) == 1 else "")
                    return self.send(code, json.dumps(d, ensure_ascii=False), "application/json", dict(hd, **{"Cache-Control": "public, max-age=30" if code == 200 else "no-store"}))
                if p == "/api/prompts/join":   # the /start prompt as data (start.api_join); keyless, read-only, cached 10 min
                    ok, wait = PROMPT_LIMIT.allow(self.client_ip())
                    if not ok: return self.send(429, json.dumps({"error": "rate limited"}), "application/json", {"Retry-After": str(wait), "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"})
                    nq = qs.get("name")
                    if nq is not None and len(nq) != 1: return self.send(400, json.dumps({"error": "one name only"}), "application/json", {"X-API-Version": AG.VERSION, "Access-Control-Allow-Origin": "*"})
                    try: d = ST.api_join(nq[0] if nq else None)
                    except ValueError as e: return self.send(400, json.dumps({"error": str(e)}), "application/json", {"X-API-Version": AG.VERSION, "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})
                    body = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
                    return self.cond(body, hashlib.sha256(body.encode()).hexdigest(), "public, max-age=600",
                                     {"X-API-Version": AG.VERSION, "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS", "Vary": "Accept-Encoding"})
                if p == "/api/agents/view":
                    try: body, etag = G.agents_view(qs.get("after", [""])[0], qint(qs, "limit", 100, 1, 500))
                    except BadRequest as e: return self.send(400, json.dumps({"error": str(e)}), "application/json", {"X-API-Version": AG.VERSION})
                    except ValueError: return self.send(400, json.dumps({"error": "bad cursor"}), "application/json", {"X-API-Version": AG.VERSION})
                    m = AG.meta(); hd = dict(AG.meta_headers(m), **{"ETag": etag, "Cache-Control": "max-age=15", "Access-Control-Allow-Origin": "*", "Access-Control-Expose-Headers": "ETag"})
                    inm = [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]
                    if etag in inm or etag.replace('W/', '') in inm or "*" in inm: return self.send(304, b"", "application/json", hd)
                    if fmt == "csv": return self.send(200, to_csv(body["rows"]), "text/csv; charset=utf-8", dict(hd, **{"Content-Disposition": 'attachment; filename="api_agents_view.csv"'}))
                    return self.send(200, json.dumps(dict(body, meta=m), default=str), "application/json", hd)
                try: data, is_list = api(p, qs)
                except NotFound as e: return self.send(404, json.dumps({"error": str(e)}), "application/json", {"X-API-Version": AG.VERSION, "Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=60"})
                except KeyError: return self.send(404, json.dumps({"error": "unknown endpoint"}), "application/json", {"X-API-Version": AG.VERSION})
                except BadRequest as e: return self.send(400, json.dumps({"error": str(e)}), "application/json", {"X-API-Version": AG.VERSION, "Access-Control-Allow-Origin": "*"})
                except TooMany as e: return self.send(429, json.dumps({"error": str(e)}), "application/json", {"X-API-Version": AG.VERSION, "Retry-After": str(e.retry), "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})
                except Unavailable as e: return self.send(503, json.dumps({"error": str(e)}), "application/json", {"X-API-Version": AG.VERSION, "Retry-After": "60", "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})
                m = AG.meta(); mh = AG.meta_headers(m)
                tag = SW.etag(p) if fmt != "csv" else None   # swap list routes: weak ETag of the data (SC-010)
                if tag:
                    mh = dict(mh, **{"ETag": tag, "Access-Control-Expose-Headers": mh["Access-Control-Expose-Headers"] + ", ETag"})
                    if tag in [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]:
                        return self.send(304, b"", "application/json", dict(mh, **{"Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=15"}))
                if isinstance(data, dict) and data.get("next_cursor"):
                    mh = dict(mh, **{"X-Next-Cursor": data["next_cursor"], "Access-Control-Expose-Headers": mh["Access-Control-Expose-Headers"] + ", X-Next-Cursor"})
                if not is_list and isinstance(data, dict) and fmt != "csv": data = dict(data); data.setdefault("meta", m)
                if p == "/api/health" and fmt != "csv":   # for uptime monitors; Fly checks /healthz so stale upstream data never pulls the machine
                    return self.send(200 if data["ok"] else 503, json.dumps(data, default=str), "application/json", dict(mh, **{"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"}))
                if fmt == "csv":
                    rows = data if is_list else (data.get("txs") if isinstance(data, dict) and "txs" in data else data.get("rows") if p.endswith("/assignments") or p in ("/api/agents/calibration", "/api/cohorts", "/api/reconcile") else [data])
                    name = p.strip("/").replace("/", "_") + ".csv"
                    return self.send(200, to_csv(rows), "text/csv; charset=utf-8", dict(mh, **{"Content-Disposition": f'attachment; filename="{name}"', "Access-Control-Allow-Origin": "*"}))
                return self.send(200, json.dumps(data, default=str), "application/json", dict(mh, **{"Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=15"}))
            html = page(path, qs)
            if html is None: return self.send(404, V.not_found(path=path))
            if isinstance(html, tuple): return self.send(*html)   # (status, html): a known route with an unknown subject
            return self.send(200, html)
        except BrokenPipeError:
            pass
        except Exception as e:
            log.error("error on %s: %s\n%s", self.path.split("?", 1)[0], e, traceback.format_exc())
            try: self.send(500, V.page("Error", V.card("Something went wrong", V.na("This page failed to render. The indexer may still be loading data.")), "/") if not path.startswith("/api/") else json.dumps({"error": "internal"}), "text/html; charset=utf-8" if not path.startswith("/api/") else "application/json")
            except Exception: pass

# Strict CSP: own scripts plus the one inline class toggle (by hash), own fonts and images, same-origin fetch and WebSocket.
CSP = ("default-src 'self'; script-src 'self' 'sha256-cvlem2Rlcb+inScVb7910PMAU98gRDEfAIUVUKXOWd4='; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
PERMS = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), clipboard-read=()"

class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.detached = set()
    def process_request(self, request, client_address):
        GD.slots.acquire()               # bounded: at most GD.MAX_WORKERS requests in flight, the rest wait in the backlog
        try: super().process_request(request, client_address)
        except Exception: GD.slots.release(); raise
    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request, client_address)
        finally: GD.slots.release()
    def shutdown_request(self, request):
        if request in self.detached:      # upgraded to WebSocket: the hub owns it now
            self.detached.discard(request); return
        super().shutdown_request(request)

def main():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
    KS.install_log_filter()   # every log line: keys and credential parameters redacted
    db.init()
    VS.COUNTER.start()
    try: OI.start()   # when the /ops/internal counters began (since_ts)
    except Exception as e: log.warning("ops internal start: %s", type(e).__name__)
    def _term(*_):   # flush the visit counts, then exit as before
        try: VS.COUNTER.flush(final=True)   # rare referrers go out as 'other', never by name
        except Exception: pass
        try: I.flush_counts(force=True)   # upstream request and denial counts held in memory
        except Exception: pass
        logging.shutdown(); os._exit(0)
    signal.signal(signal.SIGTERM, _term)
    if os.environ.get("POASCAN_INDEXER", "1") == "1":
        I.start(os.environ.get("POASCAN_SEED_DIR"))
    host = os.environ.get("HOST", "0.0.0.0"); port = int(os.environ.get("PORT", "8080"))
    HUB.start()
    srv = Server((host, port), H)
    GD.start(port)
    log.info("POASCAN listening on %s:%s", host, port)
    srv.serve_forever()

if __name__ == "__main__":
    main()
