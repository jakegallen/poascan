"""Cookieless aggregate visit counts. Daily totals only: views per (path group, kind), human views per referring
domain, and a unique-visitor estimate. No client script, no cookie, and nothing that identifies a visitor is kept:
the unique estimate is a HyperLogLog sketch (4096 one-byte registers) fed by HMAC-SHA256(daily salt, IP + UA).
The salt is 32 random bytes held only in this module, replaced at startup and at each UTC midnight; the hash
itself is never stored, only register maxima. Memory is fixed (about 64 KB at most). Details on /privacy.
Since 1.23.0 also daily event counts (visit_counts): every key comes from a fixed allowlist or a fixed pattern, so a
count can never hold a path, query, search text, IP or user agent. See METRICS for what each one counts."""
import datetime as dt, hashlib, hmac, logging, math, os, re, threading, time, urllib.parse
from . import db, geo

log = logging.getLogger("visits")
FLUSH_EVERY = int(os.environ.get("POASCAN_VISITS_FLUSH", "600"))   # seconds
P = 12; M = 1 << P                       # HyperLogLog: 4096 registers, about 1.6% standard error
REF_CAP = 256                            # referrer domains held between flushes; new ones past the cap count as 'other'
REF_MIN = 3                              # referrers seen fewer times in a day are saved only as 'other' (held in memory until then)
KEEP_DAYS = 400                          # retention of every visit_* table
KINDS = ("human", "bot", "agent")
OWN_HOSTS = ("poascan.io", "poascan.fly.dev")
BOT_NAMES = []                           # extra bot names (server.AI_BOTS), matched case-insensitively
BOT_RX = re.compile(r"(?i)bot|crawl|spider|slurp|preview|monitor|uptime|headless|lighthouse|python|curl|wget|httpx|go-http|okhttp|java/|node-fetch|axios|libwww|scrapy")
DOMAIN_RX = re.compile(r"^[a-z0-9.-]{1,64}$")
ASSET_RX = re.compile(r"\.(?:js|css|png|jpe?g|gif|webp|svg|ico|woff2?|ttf|map|webmanifest|xml)$")
SKIP_PREFIX = ("/static/", "/fragment/", "/og/", "/ops/", "/j/", "/favicon", "/apple-touch-icon")   # /j/: check-ins have their own counts
SKIP_EXACT = {"/ws", "/j", "/healthz", "/robots.txt", "/sitemap.xml", "/ops", "/site.webmanifest", "/BingSiteAuth.xml", "/.well-known/agentpeering-verify"}
SKIP_RX = re.compile(r"^/(?:google[0-9a-f]{8,32}\.html|[0-9a-f]{32}\.txt)$")   # site-verification and IndexNow key files

SEG = {"epochs": "epochs", "epoch": "epochs", "blocks": "epochs", "txs": "txs", "tx": "txs", "address": "address",
       "agents": "agents", "find": "find", "token": "token", "unlocks": "unlocks", "swaps": "swaps", "network": "network",
       "forum": "forum", "community": "forum", "grading": "grading", "live": "grading", "status": "status", "upgrade": "upgrade",
       "start": "start", "join": "start", "onboarding": "start", "about": "about", "privacy": "privacy", "search": "search",
       "growth": "network", "mining": "agents"}
GROUPS = ("home", "epochs", "txs", "address", "agents", "find", "token", "unlocks", "swaps", "network", "forum", "grading",
          "status", "upgrade", "start", "about", "privacy", "apidocs", "search", "api", "mcp", "agentdocs", "other")

# ---- daily event counts (1.23.0). metric -> what the key is. Keys outside each allowlist are counted as 'other'.
METRICS = {
    "api": "API calls by route template (OpenAPI path, never the raw path or parameters)",
    "mcp": "MCP tools/call by tool name",
    "client": "bot and agent requests by client family (fixed list)",
    "prompt": "prompt button clicks by fixed id, from POST /ops/e",
    "tag": "human page views by ?ref= campaign tag",
    "device": "human page views by device class",
    "country": "human page views by country (offline DB-IP Lite lookup; IP dropped)",
    "edge": "human page views by Fly edge region (Fly-Region)",
    "search": "/search outcomes by result type, never the query",
    "404": "not-found responses by path group",
    "5xx": "server errors by path group",
    "ms": "server response time bucket by path group"}
MS_BUCKETS = ((100, "lt100ms"), (300, "lt300ms"), (1000, "lt1s"))
MS_TOP = "ge1s"
TAG_RX = re.compile(r"^[a-z0-9_-]{1,24}$")
TAG_CAP = 64                             # campaign tags held between flushes; new ones past the cap count as 'other'
COPY_ACTS = ("copy", "copyreg", "app", "appreg")   # prompt actions that hand the prompt to the visitor
SEARCH = ("address", "tx", "epoch", "list", "none")
DEVICES = ("mobile", "tablet", "desktop")
EDGES = frozenset("ams arn atl bog bom bos cdg den dfw ewr eze fra gdl gig gru hkg iad jnb lax lhr mad mia nrt ord otp phx qro scl sea sin sjc syd waw yul yyz".split())
# client families, first match wins (case-insensitive substring of the User-Agent). The label is all that is kept.
CLIENTS = (("claudebot", "ClaudeBot"), ("claude-user", "Claude-User"), ("claude-searchbot", "Claude-SearchBot"), ("claude-code", "claude-cli"),
           ("gptbot", "GPTBot"), ("chatgpt-user", "ChatGPT-User"), ("oai-searchbot", "OAI-SearchBot"), ("perplexitybot", "PerplexityBot"),
           ("perplexity-user", "Perplexity-User"), ("google-extended", "Google-Extended"), ("googlebot", "Googlebot"), ("google-other", "Google"),
           ("bingbot", "bingbot"), ("applebot", "Applebot"), ("ccbot", "CCBot"), ("bytespider", "Bytespider"), ("amazonbot", "Amazonbot"),
           ("meta-externalagent", "meta-externalagent"), ("duckduckbot", "DuckDuckBot"), ("yandex", "YandexBot"), ("baidu", "Baiduspider"),
           ("mistral", "MistralAI"), ("cohere", "cohere-ai"), ("grok", "Grok"), ("xai", "xAI"), ("cursor", "Cursor"), ("windsurf", "Windsurf"),
           ("mcp-remote", "mcp-remote"), ("mcp-client", "mcp"), ("openai", "OpenAI"), ("anthropic", "Anthropic"),
           ("python-requests", "python-requests"), ("python-httpx", "python-httpx"), ("aiohttp", "aiohttp"), ("python-urllib", "Python-urllib"),
           ("curl", "curl"), ("wget", "Wget"), ("node-fetch", "node-fetch"), ("axios", "axios"), ("undici", "undici"), ("deno", "Deno"), ("bun", "Bun/"),
           ("go-http", "Go-http-client"), ("okhttp", "okhttp"), ("java", "Java"), ("postman", "PostmanRuntime"), ("uptime", "uptime"), ("headless", "Headless"))
CLIENT_KEYS = frozenset([k for k, _ in CLIENTS] + ["browser", "none", "other"])
API_SRC = None                           # callable returning the OpenAPI path templates (set by server.py)
MCP_TOOLS = frozenset()                  # tool names (set by server.py)
PROMPT_IDS = frozenset()                 # prompt button ids (set by server.py from prompts.ids())

def client(ua):
    if not ua: return "none"
    lo = ua.lower()
    for k, s in CLIENTS:
        if s.lower() in lo: return k
    return "browser" if ua.startswith("Mozilla/") else "other"

def device(ua):
    lo = (ua or "").lower()
    if "ipad" in lo or "tablet" in lo or ("android" in lo and "mobile" not in lo): return "tablet"
    if "mobi" in lo or "iphone" in lo or "android" in lo: return "mobile"
    return "desktop"

def edge(h):
    h = (h or "").strip().lower()
    return h if h in EDGES else "other"

def tag(query):
    """The ?ref= campaign tag only: lowercase [a-z0-9_-]{1,24} or 'other'. Nothing else from the URL is read."""
    v = urllib.parse.parse_qs(query or "").get("ref")
    if not v: return None
    v = v[0].strip().lower()
    return v if TAG_RX.match(v) else "other"

def ms_bucket(ms):
    for lim, k in MS_BUCKETS:
        if ms < lim: return k
    return MS_TOP

_API = [None]
def api_route(p):
    """Route template for an /api/ path (the OpenAPI path with /api/v1 as the prefix), else 'other'."""
    if _API[0] is None:
        ex, par = {}, []
        try: src = list(API_SRC() if API_SRC else [])
        except Exception: src = []
        for t in src:
            if not t.startswith("/api/v1/"): continue
            r = t[len("/api/v1"):]
            if "{" in t: par.append((re.compile("^" + re.sub(r"\\{[a-z_]+\\}", "[^/]+", re.escape(r)) + "$"), t))
            else: ex[r] = t
        _API[0] = (ex, par)
    ex, par = _API[0]
    if p.startswith("/api/v1/"): r = p[len("/api/v1"):]
    elif p.startswith("/api/"): r = p[len("/api"):]
    else: return "other"
    if r.endswith(".csv"): r = r[:-4]
    if r in ex: return ex[r]
    for rx, t in par:
        if rx.match(r): return t
    return "other"

def skip(p):
    return p in SKIP_EXACT or p.startswith(SKIP_PREFIX) or bool(SKIP_RX.match(p)) or bool(ASSET_RX.search(p))

def group(p):
    """Fixed path group for a normalized path. Full paths are never kept."""
    if p in ("/", "/index.html"): return "home"
    if p in ("/api", "/api/v1"): return "apidocs"
    if p.startswith("/api/"): return "api"
    if p == "/mcp": return "mcp"
    if (p.startswith("/llms") and p.endswith(".txt")) or (p.startswith("/openapi") and p.endswith(".json")) or p.startswith("/.well-known/") or p.startswith("/mcp/"):
        return "agentdocs"
    return SEG.get(p.split("/")[1], "other")

def kind(p, ua):
    if p.startswith("/api/") or p == "/mcp": return "agent"
    if not ua or not ua.startswith("Mozilla/") or BOT_RX.search(ua): return "bot"
    lo = ua.lower()
    if any(b.lower() in lo for b in BOT_NAMES): return "bot"
    return "human"

def referrer(ref):
    """Hostname only (lowercase, no www. or port); None for none or our own site; 'app' for android-app://."""
    ref = (ref or "").strip()
    if not ref: return None
    if ref.lower().startswith("android-app:"): return "app"
    try: h = (urllib.parse.urlsplit(ref).hostname or "").lower()
    except ValueError: return "other"
    if not h: return "other"
    if h.startswith("www."): h = h[4:]
    if any(h == o or h.endswith("." + o) for o in OWN_HOSTS): return None
    return h if DOMAIN_RX.match(h) else "other"

def today(t=None): return time.strftime("%Y-%m-%d", time.gmtime(t if t is not None else time.time()))

def _sigma(x):
    if x == 1: return math.inf
    y, z = 1.0, x
    while True:
        x *= x; z0 = z; z += x * y; y += y
        if z == z0: return z

def _tau(x):
    if x == 0 or x == 1: return 0.0
    y, z = 1.0, 1 - x
    while True:
        x = math.sqrt(x); z0 = z; y *= 0.5; z -= (1 - x) ** 2 * y
        if z == z0: return z / 3

class HLL:
    """HyperLogLog, p=12: a fixed 4 KB bytearray. add() takes a 64-bit int; no added value is retained."""
    __slots__ = ("r",)
    def __init__(self): self.r = bytearray(M)
    def add(self, x):
        j = x >> (64 - P); w = x & ((1 << (64 - P)) - 1)
        rank = (64 - P) - w.bit_length() + 1
        if rank > self.r[j]: self.r[j] = rank
    def estimate(self):
        """Ertl's improved estimator (arXiv:1702.01284): no bias tables, accurate from 0 to far past 1e9."""
        q = 64 - P; c = [0] * (q + 2)
        for v in self.r: c[v] += 1
        z = M * _tau(1 - c[q + 1] / M)
        for k in range(q, 0, -1): z = 0.5 * (z + c[k])
        z += M * _sigma(c[0] / M)
        return int(round(M * M / (2 * math.log(2)) / z)) if z != math.inf else 0

class Counter:
    def __init__(self, now=time.time):
        self.now = now; self.lk = threading.Lock()
        self._fresh(today(now()))
        self.base = 0

    def _fresh(self, day):
        self.day = day; self.salt = os.urandom(32); self.hll = HLL(); self.views = {}; self.refs = {}; self.ev = {}

    def hit(self, method, code, raw_path, ua, ref, ip_fn, ms=None, region=None):
        """Called from H.send() for every response. Views count successful GETs (and POST /mcp) only; site health
        counts 404s, 5xx and response time for the same paths. ms is server time to the response, in milliseconds."""
        u = urllib.parse.urlsplit(raw_path or "/"); p = u.path.rstrip("/") or "/"
        if method not in ("GET", "POST") or skip(p): return
        if method == "POST" and p != "/mcp": return
        g = group(p); g = g if g in GROUPS else "other"
        ok = 200 <= code < 300 or code == 304
        self._roll(today(self.now()))
        with self.lk:
            if ms is not None: self._ev("ms", g + "." + ms_bucket(ms))
            if code >= 500: self._ev("5xx", g)
            elif code == 404 and g != "search": self._ev("404", g)   # search misses are counted under search
            if p.startswith("/api/"): self._ev("api", api_route(p))   # every API call, whatever the status
        if not ok: return
        k = kind(p, ua or "")
        if k == "human":
            ip = ip_fn() or ""
            cc = geo.country(ip) if geo.reader() else None
            msg = (ip + "\n" + (ua or "")).encode("utf-8", "replace"); ip = None
            t = tag(u.query)
            with self.lk:
                x = int.from_bytes(hmac.digest(self.salt, msg, "sha256")[:8], "big"); del msg
                self.hll.add(x); x = None
                self._inc(g, k); dom = referrer(ref)
                if dom: self._ref(dom, 1)
                self._ev("device", device(ua))
                self._ev("edge", edge(region))
                if geo.reader(): self._ev("country", cc or "unknown")
                if t: self._tag(t, 1)
            return
        with self.lk:
            self._inc(g, k); self._ev("client", client(ua))

    def event(self, metric, key):
        """A counted event from outside H.send(): mcp tool, prompt click, search outcome. Unknown keys count as 'other'."""
        if metric == "mcp": key = key if isinstance(key, str) and key in MCP_TOOLS else "other"
        elif metric == "prompt":
            if not (isinstance(key, str) and key in PROMPT_IDS): return False
        elif metric == "search": key = key if key in SEARCH else "other"
        else: return False
        self._roll(today(self.now()))
        with self.lk: self._ev(metric, key)
        return True

    def _ev(self, m, key):
        k = (m, key); self.ev[k] = self.ev.get(k, 0) + 1

    def _tag(self, t, n):
        if ("tag", t) not in self.ev and sum(1 for m, _ in self.ev if m == "tag") >= TAG_CAP - 1: t = "other"
        k = ("tag", t); self.ev[k] = self.ev.get(k, 0) + n

    def _inc(self, g, k):
        key = (g if g in GROUPS else "other", k); self.views[key] = self.views.get(key, 0) + 1

    def _ref(self, dom, n):
        if dom not in self.refs and len(self.refs) >= REF_CAP - 1: dom = "other"   # 255 domains plus 'other' at most
        self.refs[dom] = self.refs.get(dom, 0) + n

    def _take(self):
        """Under the counter lock: detach the deltas (zeroed) and read the current estimate."""
        v, r, e = self.views, self.refs, self.ev; self.views, self.refs, self.ev = {}, {}, {}
        return self.day, v, r, self.base + self.hll.estimate(), e

    def _put_back(self, v, r, e):
        for key, n in v.items(): self.views[key] = self.views.get(key, 0) + n
        for d, n in r.items(): self._ref(d, n)
        for (m, key), n in e.items():
            if m == "tag": self._tag(key, n)
            else: self.ev[(m, key)] = self.ev.get((m, key), 0) + n

    def _write(self, day, v, r, uniq, e=None):
        st = [("INSERT INTO visit_views(day,grp,kind,views) VALUES (?,?,?,?) ON CONFLICT(day,grp,kind) DO UPDATE SET views = views + excluded.views",
               [(day, g, k, n) for (g, k), n in v.items() if n], True),
              ("INSERT INTO visit_referrers(day,domain,views) VALUES (?,?,?) ON CONFLICT(day,domain) DO UPDATE SET views = views + excluded.views",
               [(day, d, n) for d, n in r.items() if n], True),
              ("INSERT INTO visit_counts(day,metric,key,n) VALUES (?,?,?,?) ON CONFLICT(day,metric,key) DO UPDATE SET n = n + excluded.n",
               [(day, m, k, n) for (m, k), n in (e or {}).items() if n], True)]
        if uniq is not None:
            st.append(("INSERT INTO visit_uniques(day,uniques,segments) VALUES (?,?,1) ON CONFLICT(day) DO UPDATE SET uniques = excluded.uniques", (day, uniq), False))
        db.write_tx(st)

    def _split(self, r, stored, final):
        """Referrer deltas to write now. A domain not yet saved by name today and under REF_MIN views stays in memory
        (put back); at day end or shutdown (final) it is written as 'other'. So a rare domain is never written by name."""
        out, held = {}, {}
        for d, n in r.items():
            (held if d != "other" and d not in stored and n < REF_MIN else out)[d] = n
        if final:
            if held: out["other"] = out.get("other", 0) + sum(held.values())
        else:
            for d, n in held.items(): self._ref(d, n)
        return out

    def _stored_refs(self, day):
        try: return {x["domain"] for x in db.q("SELECT domain FROM visit_referrers WHERE day=?", (day,))}
        except Exception: return set()

    def flush(self, final=False):
        stored = self._stored_refs(self.day)
        with self.lk:
            day, v, r, uniq, e = self._take()
            r = self._split(r, stored if day == self.day else set(), final)
            if not v and not r and uniq == self.base and not self.base: uniq = None   # nothing seen yet today
        try: self._write(day, v, r, uniq, e)
        except Exception as e:
            log.warning("visit flush failed: %s", type(e).__name__)
            with self.lk:
                if self.day == day: self._put_back(v, r, e)
            return False
        return True

    def _roll(self, d):
        """At a UTC day change: flush the old day, fold its small referrers, drop the salt and sketch."""
        if d == self.day: return
        stored = self._stored_refs(self.day)
        with self.lk:
            if d == self.day: return
            old = list(self._take()); old[2] = self._split(old[2], stored, True); self._fresh(d); self.base = 0
        try: self._write(*old)
        except Exception as e: log.warning("visit rollover flush failed: %s", type(e).__name__)
        fold_before(d)

    def start(self):
        """Startup: fold finished days, prune old referrers, pick up today's base estimate and count this segment."""
        fold_before(self.day)
        r = db.q1("SELECT uniques FROM visit_uniques WHERE day=?", (self.day,))
        if r:
            self.base = int(r["uniques"] or 0)
            db.write("UPDATE visit_uniques SET segments = segments + 1 WHERE day=?", (self.day,))
        threading.Thread(target=self._loop, daemon=True, name="visits").start()

    def _loop(self):
        while True:
            t = self.now(); nxt = (int(t) // 86400 + 1) * 86400 + 1
            time.sleep(max(1, min(FLUSH_EVERY, nxt - t)))
            try:
                self._roll(today(self.now())); self.flush()
            except Exception as e: log.warning("visit loop: %s", type(e).__name__)

    def size(self):
        return dict(registers=len(self.hll.r), views_keys=len(self.views), referrer_keys=len(self.refs), salt=len(self.salt), event_keys=len(self.ev))

def fold_before(day):
    """Referrers and campaign tags with fewer than REF_MIN views on a finished day become 'other' (a safety net: flush
    already holds them back); rows of every visit_* table past KEEP_DAYS are pruned."""
    cut = (dt.date.fromisoformat(day) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    db.write_tx([
        ("INSERT INTO visit_referrers(day,domain,views) SELECT day,'other',SUM(views) FROM visit_referrers WHERE day<? AND domain<>'other' AND views<? GROUP BY day "
         "ON CONFLICT(day,domain) DO UPDATE SET views = views + excluded.views", (day, REF_MIN), False),
        ("DELETE FROM visit_referrers WHERE day<? AND domain<>'other' AND views<?", (day, REF_MIN), False),
        ("DELETE FROM visit_referrers WHERE day<?", (cut,), False),
        ("INSERT INTO visit_counts(day,metric,key,n) SELECT day,'tag','other',SUM(n) FROM visit_counts WHERE metric='tag' AND day<? AND key<>'other' AND n<? GROUP BY day "
         "ON CONFLICT(day,metric,key) DO UPDATE SET n = n + excluded.n", (day, REF_MIN), False),
        ("DELETE FROM visit_counts WHERE metric='tag' AND day<? AND key<>'other' AND n<?", (day, REF_MIN), False),
        ("DELETE FROM visit_counts WHERE day<?", (cut,), False),
        ("DELETE FROM visit_views WHERE day<?", (cut,), False),
        ("DELETE FROM visit_uniques WHERE day<?", (cut,), False)])

def report(frm, to):
    """Daily rows for [frm, to]. Today's small referrers are shown folded too."""
    days = {}
    def d(x): return days.setdefault(x, dict(day=x, uniques=0, segments=0, views={}, referrers={}))
    for r in db.q("SELECT day,uniques,segments FROM visit_uniques WHERE day BETWEEN ? AND ?", (frm, to)):
        d(r["day"]).update(uniques=r["uniques"], segments=r["segments"])
    for r in db.q("SELECT day,grp,kind,views FROM visit_views WHERE day BETWEEN ? AND ?", (frm, to)):
        d(r["day"])["views"].setdefault(r["grp"], {k: 0 for k in KINDS})[r["kind"]] = r["views"]
    for r in db.q("SELECT day,domain,views FROM visit_referrers WHERE day BETWEEN ? AND ?", (frm, to)):
        rf = d(r["day"])["referrers"]
        if r["domain"] != "other" and r["views"] < REF_MIN: rf["other"] = rf.get("other", 0) + r["views"]
        else: rf[r["domain"]] = rf.get(r["domain"], 0) + r["views"]
    ev = {}
    for r in db.q("SELECT day,metric,key,n FROM visit_counts WHERE day BETWEEN ? AND ?", (frm, to)):
        d(r["day"]); m = ev.setdefault(r["day"], {}).setdefault(r["metric"], {})
        k = "other" if r["metric"] == "tag" and r["key"] != "other" and r["n"] < REF_MIN else r["key"]
        m[k] = m.get(k, 0) + r["n"]
    srt = lambda x: dict(sorted(x.items(), key=lambda kv: (kv[0] == "other", -kv[1], kv[0])))
    for day, x in days.items():
        x["referrers"] = srt(x["referrers"]); e = ev.get(day, {})
        ms = {}
        for k, n in e.get("ms", {}).items():
            g, _, b = k.partition("."); ms.setdefault(g, {b2: 0 for _, b2 in MS_BUCKETS} | {MS_TOP: 0})[b] = n
        pr = e.get("prompt", {})
        pid = lambda act: sum(n for k, n in pr.items() if k.rsplit(".", 1)[-1] == act)
        cp = lambda card: sum(n for k, n in pr.items() if k.startswith(card + ".") and k.rsplit(".", 1)[-1] in COPY_ACTS)
        x.update(api=srt(e.get("api", {})), mcp=srt(e.get("mcp", {})), clients=srt(e.get("client", {})), prompts=srt(pr),
                 funnel=dict(start_views=sum(x["views"].get("start", {}).values()), start_views_human=x["views"].get("start", {}).get("human", 0),
                             start_copies=cp("start"), join_opens=pr.get("join.open", 0), join_copies=cp("join"),
                             registry_shows=pid("regshow"), registry_copies=pid("copyreg") + pid("appreg")),
                 campaigns=srt(e.get("tag", {})), devices=srt(e.get("device", {})), countries=srt(e.get("country", {})),
                 edges=srt(e.get("edge", {})), search=srt(e.get("search", {})),
                 health=dict(not_found=srt(e.get("404", {})), errors=srt(e.get("5xx", {})), response_ms=dict(sorted(ms.items()))))
    try:   # requests POAScan sent to minepoa.com, per endpoint template (poascan/indexer.py counter); counts only
        from . import indexer as I
        up = I.upstream_report(); upd = I.upstream_daily(frm, to); up["daily"] = dict(sorted(upd.items(), reverse=True))
    except Exception as e:
        log.warning("upstream report: %s", type(e).__name__); up, upd = None, {}
    for day, x in days.items(): x["health"]["upstream"] = dict(sorted(upd.get(day, {}).items(), key=lambda kv: -kv[1]))
    return dict(**{"from": frm, "to": to}, country_source=geo.source(), metrics=METRICS, upstream=up, days=[days[k] for k in sorted(days, reverse=True)])

COUNTER = Counter()

def token_ok(auth):
    """POASCAN_STATS_TOKEN (32+ chars) as 'Authorization: Bearer <token>', compared in constant time."""
    exp = os.environ.get("POASCAN_STATS_TOKEN") or ""
    if len(exp) < 32: return False
    sch, _, got = (auth or "").strip().partition(" ")
    if sch.lower() != "bearer": got = ""
    return hmac.compare_digest(hashlib.sha256(got.strip().encode()).digest(), hashlib.sha256(exp.encode()).digest())

def parse_range(qs, now=None):
    """(from, to) as YYYY-MM-DD; default the last 30 days; at most 400 days. ValueError on bad input."""
    t = dt.date.fromisoformat(today(now)); to = qs.get("to", [""])[0] or t.isoformat()
    to_d = dt.date.fromisoformat(to) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", to) else None
    if not to_d: raise ValueError("to must be YYYY-MM-DD")
    fr = qs.get("from", [""])[0] or (to_d - dt.timedelta(days=29)).isoformat()
    fr_d = dt.date.fromisoformat(fr) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fr) else None
    if not fr_d: raise ValueError("from must be YYYY-MM-DD")
    if fr_d > to_d: raise ValueError("from is after to")
    if (to_d - fr_d).days + 1 > KEEP_DAYS: raise ValueError(f"at most {KEEP_DAYS} days")
    return fr_d.isoformat(), to_d.isoformat()
