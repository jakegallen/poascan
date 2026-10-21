"""POASCAN HTTP server: pages, read-only JSON/CSV API, static files. Python stdlib only."""
import json, os, re, csv, io, gzip, time, logging, mimetypes, traceback, urllib.parse
from html import escape as E
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from . import db, analytics as A, agents as G, indexer as I, views as V, views2 as V2, views3 as V3, views4 as V4, live as L, agentapi as AG, start as ST, faq as FQ, ui as UI

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
ROOT_FILES = {"/favicon.ico": ("favicon.ico", "image/x-icon"), "/favicon.svg": ("favicon.svg", "image/svg+xml"),
              "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"), "/apple-touch-icon-precomposed.png": ("apple-touch-icon.png", "image/png"),
              "/site.webmanifest": ("site.webmanifest", "application/manifest+json")}
log = logging.getLogger("server")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
STARTED = int(time.time())

def to_csv(rows):
    if not rows: return ""
    buf = io.StringIO(); keys = list(rows[0].keys())
    w = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore"); w.writeheader()
    for r in rows: w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
    return buf.getvalue()

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
        lim = min(1000, int(qs.get("limit", ["100"])[0])); off = int(qs.get("offset", ["0"])[0]); typ = qs.get("type", [""])[0]; ad = qs.get("addr", [""])[0]
        w, a = [], []
        if typ: w.append("type=?"); a.append(typ)
        if ad: w.append("(from_addr=? OR to_addr=?)"); a += [ad, ad]
        sql = "SELECT * FROM txs" + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY ts DESC LIMIT ? OFFSET ?"
        return db.q(sql, tuple(a) + (lim, off)), True
    m = re.match(r"^/api/tx/([0-9a-fA-F]{64})$", path)
    if m: return I.get_tx_detail(m.group(1).lower()), False
    m = re.match(r"^/api/address/(poa1\w+)$", path)
    if m:
        a = m.group(1); p = G.profile(a); d, err = V.fetch_address(a)
        return dict(address=a, balance=(d or {}).get("balance"), rewards=p["rewards"], streak=p["streak"], census=p["census"], family_size=(p["family"] or [None, None])[1],
                    forum_name=p["forum_name"], established=a in A.established_set(), txs=db.q("SELECT * FROM txs WHERE from_addr=? OR to_addr=? ORDER BY ts DESC LIMIT 500", (a, a)), fetch_error=err), False
    if path == "/api/epochs": return A.epoch_rows(), True
    if path == "/api/swaps": return V2.swaps_all(), True
    if path == "/api/swaps/status": return V2.swap_status_api(), False
    if path == "/api/swaps/price-history": return V2.price_history(), True
    if path == "/api/agents/new-per-day": return G.new_per_day(), True
    if path == "/api/concentration": return A.concentration(), False
    if path == "/api/uptime":
        rows = V2.uptime_rows(); ep = qs.get("endpoint", [""])[0]
        return ([r for r in rows if r["endpoint"] == ep] if ep else rows), True
    if path == "/api/unlocks": return V3.unlocks_api(), True
    if path.startswith("/api/leaderboard/"):
        t = path.rsplit("/", 1)[1]; t = V4.ALIAS.get(t, t)
        if t not in V4.COLS: return {"error": "unknown tab", "tabs": list(V4.COLS)}, False
        return V4.rows(t), True
    if path == "/api/status":
        d = V2.status_data(); return dict(endpoints=d["eps"], incidents=[dict(start=a, end=b, what=w, fails=f) for a, b, w, f in d["inc"]], anchors=d["anchors"], last_checkpoint_change=d["last_cp_change"]), False
    m = re.match(r"^/api/epoch/(\d+)$", path)
    if m:
        r = [x for x in A.epoch_rows() if x["epoch"] == int(m.group(1))]
        if not r: raise KeyError
        return dict(r[0], rewards=A.epoch_detail(int(m.group(1))).get("rewards")), False
    if path == "/api/richlist": return [{k: r[k] for k in ("rank", "addr", "balance", "share", "src")} for r in A.holders()["rows"]], True
    if path in ("/api/agents/series", "/api/accounts/series"): return [dict(ts=p[0], accounts=p[1], holders=p[2], supply=p[3], window_txs=p[4]) for p in A.accounts_series()], True
    if path == "/api/forum":
        f = dict(A.forum()); f["top_threads"] = [{k: t[k] for k in ("id", "title", "community", "comment_count", "score")} for t in f["top_threads"]]; return f, False
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
    if path == "/api/agents/streaks": return [dict(addr=a, longest=b, current=c) for a, (b, c) in sorted(G.streaks().items(), key=lambda kv: -kv[1][0])], True
    if path == "/api/agents/activity-clock": return G.activity_clock(), False
    if path == "/api/agents/social": return G.social(), False
    if path == "/api/agents/builders":
        b = dict(G.builders()); return b, False
    raise KeyError(path)

def page(path, qs):
    if path in ("/", "/index.html"): return V.home()
    if path == "/txs": return V.txs(qs)
    m = re.match(r"^/tx/([0-9a-fA-F]{64})$", path)
    if m: return V.tx(m.group(1).lower())
    m = re.match(r"^/address/(poa1\w+)$", path)
    if m: return V.address(m.group(1))
    if path == "/token": return V.token()
    if path == "/swaps": return V2.swaps_page(None)
    if path in FQ.PAGES: return FQ.page(path, V.page, V.card)
    if path in ("/start", "/join", "/onboarding"): return ST.page(V.page, V.card, V2._apps(auto_first=True))
    if path == "/growth": return V3.growth_page()
    if path == "/agents/top": return V4.leaderboard_page(qs.get("tab", ["richlist"])[0], V.apage)
    if path == "/unlocks": return V.page("Unlocks", '<div class="sechead"><h1>Unlocks</h1></div>' + V3.unlock_section(), "/token")
    if path == "/status": return V2.status_page()
    if path == "/find": return V.find_page()
    if path in ("/epochs", "/blocks"): return V.epochs_page()
    m = re.match(r"^/epoch/(\d+)$", path)
    if m: return V.epoch(int(m.group(1)))
    routes = {"/agents": V.agents_overview, "/agents/leaderboard": V.leaderboard_page, "/agents/census": V.census_page, "/agents/journey": V.journey_page,
              "/agents/operators": V.operators_page, "/agents/answers": V.answers_page, "/agents/graders": V.graders_page, "/agents/builders": V.builders_page,
              "/agents/social": V.social_page, "/grading": V.grading, "/forum": V.forum_page, "/community": V.forum_page, "/network": V.network, "/about": V.about, "/privacy": V.privacy}
    if path in routes: return routes[path]()
    return None

AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "PerplexityBot", "Perplexity-User",
           "Google-Extended", "Applebot-Extended", "CCBot"]
ROBOTS = ("User-agent: *\nAllow: /\nDisallow: /ws\nDisallow: /fragment/\n\n" + "".join(f"User-agent: {b}\n" for b in AI_BOTS)
          + "Allow: /\nDisallow: /ws\nDisallow: /fragment/\n\nSitemap: https://poascan.io/sitemap.xml\n")

AGENTPEERING_VERIFY = "ap-verify-cec18af41a029ed83d4e21ee0268f52c"  # public verification string for agentpeering.com

STATIC_ROUTES = ["/", "/start", "/txs", "/epochs", "/token", "/unlocks", "/swaps", "/growth", "/agents", "/agents/top", "/agents/leaderboard", "/agents/census",
                 "/agents/journey", "/agents/operators", "/agents/answers", "/agents/graders", "/agents/builders", "/agents/social", "/grading", "/forum",
                 "/network", "/status", "/about", "/privacy", "/api", "/find"] + list(FQ.PAGES)
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

class H(BaseHTTPRequestHandler):
    server_version = "POASCAN/1.0"
    def log_message(self, fmt, *a): log.info("%s %s", self.address_string(), fmt % a)
    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        if isinstance(body, str) and ("html" in ctype or "json" in ctype or ctype.startswith("text/")): body = nodash(body)
        b = body.encode() if isinstance(body, str) else body
        gz = (len(b) > 1400 and "gzip" in (self.headers.get("Accept-Encoding") or "") and
              (ctype.startswith("text/") or "json" in ctype or "javascript" in ctype or "svg" in ctype or "manifest" in ctype))
        if gz: b = gzip.compress(b, 5)
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        if gz: self.send_header("Content-Encoding", "gzip"); self.send_header("Vary", "Accept-Encoding")
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(b)
    def do_HEAD(self): self.do_GET()
    def client_ip(self):
        return (self.headers.get("Fly-Client-IP") or (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or self.client_address[0])
    def do_POST(self):
        """The only write-shaped method we accept is JSON-RPC to the read-only MCP server."""
        if (urllib.parse.urlparse(self.path).path.rstrip("/") or "/") != "/mcp": return self.send(405, "read-only", "text/plain", {"Allow": "GET, HEAD"})
        try:
            ok, wait = AG.LIMIT.allow(self.client_ip())
            if not ok: return self.send(429, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "rate limited"}}), "application/json", dict(MCP_HDRS, **{"Retry-After": str(wait)}))
            n = int(self.headers.get("Content-Length") or -1)
            if n < 0: return self.send(411, json.dumps(AG._err(None, -32600, "Content-Length required")), "application/json", MCP_HDRS)
            if n > 65536: return self.send(413, json.dumps(AG._err(None, -32600, "request too large")), "application/json", MCP_HDRS)
            pv = self.headers.get("MCP-Protocol-Version")
            if pv and pv not in AG.PROTOCOLS: return self.send(400, json.dumps(AG._err(None, -32600, "unsupported MCP-Protocol-Version")), "application/json", MCP_HDRS)
            code, out = AG.handle_mcp(self.rfile.read(n))
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
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); path = u.path.rstrip("/") or "/"; qs = urllib.parse.parse_qs(u.query)
        if path == AG.API_PREFIX: path = "/api"                                   # /api/v1 is canonical; /api/... stays as an alias
        elif path.startswith(AG.API_PREFIX + "/"): path = "/api/" + path[len(AG.API_PREFIX) + 1:]
        V.REQ.path, V.REQ.qs = path, qs
        try:
            if path == "/ws":
                return HUB.accept(self)
            if path in ("/api/summary", "/api/live"):
                m = AG.meta(); d = json.loads(HUB.snapshot()) if path == "/api/summary" else dict(HUB.stats())
                if isinstance(d, dict):
                    if path == "/api/summary": d["swaps"] = V2.swap_status_api(); d["concentration"] = A.concentration()
                    d.setdefault("meta", m)
                return self.send(200, json.dumps(d, default=str), "application/json", dict(AG.meta_headers(m), **{"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"}))
            if path.startswith("/static/"):
                f = os.path.normpath(os.path.join(STATIC, path[8:]))
                if not f.startswith(os.path.normpath(STATIC)) or not os.path.isfile(f): return self.send(404, "not found", "text/plain")
                ct = {".ico": "image/x-icon", ".webmanifest": "application/manifest+json"}.get(os.path.splitext(f)[1]) or mimetypes.guess_type(f)[0] or "application/octet-stream"
                return self.send(200, open(f, "rb").read(), ct, {"Cache-Control": "public, max-age=3600"})
            if path in ROOT_FILES:
                fn, ct = ROOT_FILES[path]
                return self.send(200, open(os.path.join(STATIC, fn), "rb").read(), ct, {"Cache-Control": "public, max-age=86400"})
            if path == "/healthz": return self.send(200, "ok\n", TXT, {"Cache-Control": "no-store"})
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
            if path == "/search":
                q = (qs.get("q", [""])[0] or "").strip()
                if re.match(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$", q): loc = "/address/" + q
                elif HEX64.match(q): loc = "/tx/" + q.lower()
                elif re.match(r"^[Ee]?\d{1,7}$", q): loc = "/epoch/" + q.lstrip("Ee")
                else:
                    hits = [h for h in AG.t_search({"query": q})["results"] if h.get("kind") == "address"] if len(q) >= 2 else []
                    exact = [h for h in hits if (h.get("name") or "").lower() == q.lower()]
                    if len(exact) == 1 or len(hits) == 1: loc = "/address/" + (exact or hits)[0]["id"]
                    elif hits: return self.send(200, V.search_hits(q, hits[:20]))
                    else: return self.send(404, V.search_results(q))
                return self.send(302, "", extra={"Location": loc})
            if path.startswith("/fragment/feed"): return self.send(200, V.feed_rows(), extra={"Cache-Control": "no-store"})
            if path.startswith("/api/"):
                fmt = "csv" if path.endswith(".csv") else qs.get("format", ["json"])[0]
                p = path[:-4] if path.endswith(".csv") else path
                try: data, is_list = api(p, qs)
                except KeyError: return self.send(404, json.dumps({"error": "unknown endpoint"}), "application/json", {"X-API-Version": AG.VERSION})
                m = AG.meta(); mh = AG.meta_headers(m)
                if not is_list and isinstance(data, dict) and fmt != "csv": data = dict(data); data.setdefault("meta", m)
                if p == "/api/health" and fmt != "csv":   # for uptime monitors; Fly checks /healthz so stale upstream data never pulls the machine
                    return self.send(200 if data["ok"] else 503, json.dumps(data, default=str), "application/json", dict(mh, **{"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"}))
                if fmt == "csv":
                    rows = data if is_list else (data.get("txs") if isinstance(data, dict) and "txs" in data else [data])
                    name = p.strip("/").replace("/", "_") + ".csv"
                    return self.send(200, to_csv(rows), "text/csv; charset=utf-8", dict(mh, **{"Content-Disposition": f'attachment; filename="{name}"', "Access-Control-Allow-Origin": "*"}))
                return self.send(200, json.dumps(data, default=str), "application/json", dict(mh, **{"Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=15"}))
            html = page(path, qs)
            if html is None: return self.send(404, V.not_found())
            return self.send(200, html)
        except BrokenPipeError:
            pass
        except Exception as e:
            log.error("error on %s: %s\n%s", self.path, e, traceback.format_exc())
            try: self.send(500, V.page("Error", V.card("Something went wrong", V.na("This page failed to render. The indexer may still be loading data.")), "/") if not path.startswith("/api/") else json.dumps({"error": "internal"}), "text/html; charset=utf-8" if not path.startswith("/api/") else "application/json")
            except Exception: pass

class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.detached = set()
    def shutdown_request(self, request):
        if request in self.detached:      # upgraded to WebSocket: the hub owns it now
            self.detached.discard(request); return
        super().shutdown_request(request)

def main():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
    db.init()
    if os.environ.get("POASCAN_INDEXER", "1") == "1":
        I.start(os.environ.get("POASCAN_SEED_DIR"))
    host = os.environ.get("HOST", "0.0.0.0"); port = int(os.environ.get("PORT", "8080"))
    HUB.start()
    srv = Server((host, port), H)
    log.info("POASCAN listening on %s:%s", host, port)
    srv.serve_forever()

if __name__ == "__main__":
    main()
