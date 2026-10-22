"""Polite poller for public minepoa.com endpoints. Read-only GETs only; never uses keys."""
import json, os, random, re, threading, time, urllib.request, urllib.error, glob, logging
from . import db

BASE = os.environ.get("POA_BASE", "https://minepoa.com")
UA = "POAScan-indexer/1.0 (+https://poascan.io; read-only)"
log = logging.getLogger("indexer")
# Hard allowlist: the indexer can only ever call these read-only paths.
ALLOWED = re.compile(r"^/(api/(status|networks|txs|explorer/txs|explorer/tx/[0-9a-f]{64}|explorer/address/poa1[1-9A-HJ-NP-Za-km-z]+|"
                     r"epochs|agents|anchors|params|release|notices|ballots|chains|swaps)|lableak/api/(communities|posts|posts/\d+))(\?[\w=&.\-]*)?$")

class Busy(Exception):
    def __init__(self, msg, retry=None):
        super().__init__(msg); self.retry = retry

def fetch(path, timeout=60, endpoint=None):
    """GET BASE+path, return parsed JSON. Records health in fetch_log. Raises on failure."""
    if not ALLOWED.match(path):
        raise ValueError("path not allowlisted: " + path)
    ep = endpoint or path.split("?")[0]
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept": "application/json"})
    now = int(time.time()); t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        _probe(ep, True, t0, "200")
        if raw[:1] not in (b"{", b"["):
            raise Busy("non-JSON response (load page?)")
        data = json.loads(raw)
        db.write("INSERT INTO fetch_log(endpoint,last_ok,fails,next_at,bytes,err) VALUES(?,?,0,0,?,NULL) "
                 "ON CONFLICT(endpoint) DO UPDATE SET last_ok=excluded.last_ok, fails=0, next_at=0, bytes=excluded.bytes",
                 (ep, now, len(raw)))
        return data
    except urllib.error.HTTPError as e:
        retry = None
        try:
            body = json.loads(e.read() or b"{}"); retry = body.get("retry_after_seconds")
        except Exception:
            pass
        _probe(ep, False, t0, str(e.code)); _fail(ep, f"HTTP {e.code}", retry)
        raise Busy(f"HTTP {e.code}", retry)
    except Busy as e:
        _fail(ep, str(e), None); raise
    except Exception as e:
        _probe(ep, False, t0, type(e).__name__); _fail(ep, type(e).__name__ + ": " + str(e)[:120], None)
        raise Busy(str(e))

def _probe(ep, ok, t0, code):
    try: db.write("INSERT INTO probes VALUES(?,?,?,?,?)", (int(time.time()), uptime_name(ep), 1 if ok else 0, int((time.time() - t0) * 1000), code))
    except Exception: pass

# Status probes: only the two public pages, every 10 min, first 1 KB. The JSON endpoints we already
# poll (status, swaps, communities) count toward uptime from those regular fetches instead.
PROBES = ["/", "/go.md"]
DERIVED = ("/api/status", "/api/swaps", "/lableak/api/communities")
def uptime_name(ep): return "probe " + ep if ep in DERIVED else ep
def job_probe():
    for path in PROBES:
        t0 = time.time()
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Range": "bytes=0-1023"})
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read(1024); _probe("probe " + path, 200 <= r.status < 400, t0, str(r.status))
        except urllib.error.HTTPError as e: _probe("probe " + path, False, t0, str(e.code))
        except Exception as e: _probe("probe " + path, False, t0, type(e).__name__)
        time.sleep(0.5)
    db.write("DELETE FROM probes WHERE ts < ?", (int(time.time()) - 14 * 86400,))
    rollup_uptime()

def rollup_uptime(now=None):
    """Fold the last two UTC days of probe and fetch outcomes into one small row per day and endpoint; keep a year."""
    now = int(now or time.time()); d0 = (now // 86400 - 1) * 86400
    db.write("""INSERT OR REPLACE INTO uptime_daily(day, endpoint, n, ok, ms)
      SELECT (ts/86400)*86400, CASE WHEN endpoint IN (?,?,?) THEN 'probe ' || endpoint ELSE endpoint END, COUNT(*), SUM(ok), CAST(AVG(CASE WHEN ok=1 THEN ms END) AS INTEGER)
      FROM probes WHERE ts >= ? GROUP BY 1, 2""", DERIVED + (d0,))
    db.write("DELETE FROM uptime_daily WHERE day >= ? AND endpoint IN (?,?,?)", (d0,) + DERIVED)
    db.write("DELETE FROM uptime_daily WHERE day < ?", (now - 365 * 86400,))

def _fail(ep, err, retry):
    row = db.q1("SELECT fails FROM fetch_log WHERE endpoint=?", (ep,))
    fails = (row["fails"] if row else 0) + 1
    backoff = min(900, 30 * (2 ** min(fails - 1, 5)))
    if retry: backoff = max(backoff, int(retry))
    now = int(time.time())
    db.write("INSERT INTO fetch_log(endpoint,last_err,err,fails,next_at) VALUES(?,?,?,?,?) "
             "ON CONFLICT(endpoint) DO UPDATE SET last_err=excluded.last_err, err=excluded.err, fails=excluded.fails, next_at=excluded.next_at",
             (ep, now, err, fails, now + backoff + random.randint(0, 15)))

def can_fetch(ep):
    row = db.q1("SELECT next_at FROM fetch_log WHERE endpoint=?", (ep,))
    return not row or not row["next_at"] or row["next_at"] <= time.time()

# ---------------- ingest helpers ----------------
def upsert_txs(rows, source):
    now = int(time.time()); out = []
    for t in rows:
        tid = t.get("id")
        if not tid: continue
        fr = t.get("from_addr", t.get("from")) or None
        to = t.get("to_addr", t.get("to")) or None
        amt = t.get("amount") or None
        fin = t.get("final"); fin = 1 if fin in (1, True, "1") else 0
        out.append((tid, t.get("type"), fr, to, amt, t.get("memo") or None, t.get("invited_by"), t.get("epoch"),
                    int(t.get("ts") or 0), int(t.get("atts") or 0), t.get("K"), fin, now, now, source))
    db.write("""INSERT INTO txs(id,type,from_addr,to_addr,amount,memo,invited_by,epoch,ts,atts,k,final,first_seen,last_seen,source)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET atts=MAX(txs.atts, excluded.atts), final=MAX(txs.final, excluded.final),
        last_seen=excluded.last_seen, memo=COALESCE(txs.memo, excluded.memo), invited_by=COALESCE(txs.invited_by, excluded.invited_by),
        epoch=COALESCE(txs.epoch, excluded.epoch), k=COALESCE(txs.k, excluded.k)""", out, many=True)
    labs = []
    for t in rows:
        if t.get("type") == "join":
            memo = t.get("memo") or ""
            fr = t.get("from_addr", t.get("from"))
            hosted = memo.lower().startswith("hosted join")
            labs.append((fr, re.sub(r"^hosted join:?\s*", "", memo).strip(), "hosted" if hosted else "non-hosted join (likely self-custody)", "join memo", int(t.get("ts") or 0)))
    if labs:
        db.write("INSERT OR REPLACE INTO labels VALUES(?,?,?,?,?)", labs, many=True)
    return len(out)

def job_live():
    # Each read stands alone: a slow /api/networks must not hold back the tx feed that drives the Live pill.
    rows = fetch("/api/explorer/txs?limit=200")
    upsert_txs(rows, "explorer/txs")
    for path, fn in (("/api/status", _live_status), ("/api/networks", _live_networks)):
        if not can_fetch(path): continue
        try: fn(fetch(path, timeout=20))
        except Busy as e: log.warning("%s: %s", path, e)

def _live_status(st): db.add_snap("status", st); db.put_blob("status", st)

def _live_networks(nw):
    db.put_blob("networks", nw)
    for c in nw.get("chains", []):
        if c.get("chain_id") == "poa-mainnet-1":
            db.add_snap("height", {"height": c.get("height"), "checkpoint_height": c.get("checkpoint_height")})

def job_window():
    d = fetch("/api/txs", timeout=90)
    upsert_txs(d.get("valid", []), "txs-window")
    now = int(time.time())
    db.write("INSERT OR IGNORE INTO invalid_txs(txid,error,first_seen) VALUES(?,?,?)",
             [(x.get("txid"), x.get("error"), now) for x in d.get("invalid", []) if x.get("txid")], many=True)

def job_meta():
    for kind, path in (("anchors", "/api/anchors"), ("notices", "/api/notices"), ("ballots", "/api/ballots")):
        if not can_fetch(path): continue
        try:
            d = fetch(path); db.put_blob(kind, d)
            if kind == "anchors":
                db.write("INSERT OR IGNORE INTO anchors VALUES(?,?,?,?,?,?,?)",
                         [(a["height"], a["chain"], a.get("tx_hash") or a.get("tx_signature"), a.get("state_root"),
                           a.get("anchored_by"), a.get("memo"), a.get("anchored_at")) for a in d], many=True)
        except Busy as e:
            log.warning("%s: %s", path, e)
        time.sleep(1)

def job_hourly_meta():
    for kind, path in (("params", "/api/params"), ("release", "/api/release"), ("chains", "/api/chains")):
        if not can_fetch(path): continue
        try: db.put_blob(kind, fetch(path))
        except Busy as e: log.warning("%s: %s", path, e)
        time.sleep(1)

def job_epochs(force=False):
    from . import analytics as A   # shared parsed copy; re-parsing the ~11 MB blob here every 5 min cost ~50 MB each run
    st, _ = db.get_blob("status"); have = A.epochs_count(); ep = have
    need = (st or {}).get("epochs_closed", 0)
    if not force and ep and have >= need: return False
    d = fetch("/api/epochs", timeout=180)
    if isinstance(d, list) and d:
        db.put_blob("epochs", d); return True
    return False

def job_agents():
    d = fetch("/api/agents", timeout=120)
    now = int(time.time())
    rows = [(a["addr"], a.get("invited_by"), float(a.get("balance") or 0), a.get("balance"), a.get("ts"), a.get("joined_epoch"), now, now) for a in d]
    db.write("""INSERT INTO accounts(addr,invited_by,balance,balance_s,api_ts,api_joined_epoch,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?)
      ON CONFLICT(addr) DO UPDATE SET balance=excluded.balance, balance_s=excluded.balance_s, api_ts=excluded.api_ts,
        api_joined_epoch=excluded.api_joined_epoch, last_seen=excluded.last_seen,
        invited_by=COALESCE(accounts.invited_by, excluded.invited_by)""", rows, many=True)
    db.add_snap("accounts", {"total": len(d), "with_balance": sum(1 for a in d if float(a.get("balance") or 0) > 0)})

def job_forum():
    B = "/lableak/api"
    comms = fetch(B + "/communities"); db.put_blob("communities", comms)
    known = {r["id"]: (r["comment_count"], r["edited_at"]) for r in db.q("SELECT id, comment_count, edited_at FROM forum_posts")}
    changed = []
    for c in comms:
        time.sleep(1)
        ps = fetch(f"{B}/posts?sort=new&community={c['slug']}&limit=1000", endpoint=B + "/posts")
        for p in ps:
            pid = int(p["id"]); cc = int(p.get("comment_count") or 0); ed = p.get("edited_at") or None
            # The list carries body (and edited_at once a post is edited): edited bodies refresh here at no extra request.
            db.write("""INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body,edited_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT fetched FROM forum_posts WHERE id=?),0),?,?)
              ON CONFLICT(id) DO UPDATE SET score=excluded.score, title=excluded.title, deleted=excluded.deleted, pinned=excluded.pinned,
              body=COALESCE(excluded.body, forum_posts.body), edited_at=COALESCE(excluded.edited_at, forum_posts.edited_at)""",
                     (pid, p.get("community"), p.get("title"), p.get("author"), p.get("author_public_id"), p.get("created_at"),
                      int(p.get("score") or 0), known.get(pid, (-1, None))[0], int(p.get("deleted") or 0), int(p.get("pinned") or 0), pid,
                      p.get("body"), ed))
            k = known.get(pid)
            if not k or k[0] != cc or (ed and ed != k[1]): changed.append(pid)   # new comments, or an edit (its comments may have changed too)
    for pid in changed[:120]:   # cap detail calls per run; the rest catch up next run
        time.sleep(0.8)
        try: ingest_post(fetch(f"{B}/posts/{pid}", endpoint=B + "/posts/:id"))
        except Busy as e: log.warning("forum post %s: %s", pid, e); break

def ingest_post(p):
    pid = int(p["id"]); cs = p.get("comments", [])
    db.write("""INSERT INTO forum_posts(id,community,title,author,author_public_id,created_at,score,comment_count,deleted,pinned,fetched,body,edited_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET comment_count=excluded.comment_count, score=excluded.score,
      fetched=excluded.fetched, body=excluded.body, title=excluded.title, edited_at=COALESCE(excluded.edited_at, forum_posts.edited_at)""",
             (pid, p.get("community"), p.get("title"), p.get("author"), p.get("author_public_id"), p.get("created_at"),
              int(p.get("score") or 0), len(cs), int(p.get("deleted") or 0), int(p.get("pinned") or 0), int(time.time()), p.get("body"), p.get("edited_at") or None))
    db.write("INSERT OR REPLACE INTO forum_comments(id,post_id,parent_id,author,author_public_id,created_at,score,body,edited_at) VALUES(?,?,?,?,?,?,?,?,?)",
             [(int(c["id"]), pid, (int(c["parent_id"]) if c.get("parent_id") not in (None, "None", "") else None), c.get("author"),
               c.get("author_public_id"), c.get("created_at"), int(c.get("score") or 0), c.get("body"), c.get("edited_at") or None) for c in cs], many=True)

# ---------------- swaps (on-ledger escrow offers, fills, cancels) ----------------
# Swap offers, swap tx details and the SOL/ETH USD reference: poascan/swap/indexer.py (its JOBS are spliced in below).

# ---------------- answer-text sampling (Sybil signals) ----------------
SLOT = re.compile(r"\b(the words|words)\s+[a-z]+,\s*[a-z]+,?\s+(and\s+)?[a-z]+\b|\bwith\s+[a-z]+,\s*[a-z]+\s+and\s+[a-z]+\b|"
                  r"\b(of|evaluate|think of)\s+[a-z]+,\s*[a-z]+\s+and\s+[a-z]+\b|\band\s+[a-z]+,\s*[a-z]+,\s*[a-z]+\s+(remind|mark|capture)", re.I)
ECHO = re.compile(r"120-600 chars|plain prose|^need (original|write)", re.I)

def classify(text):
    t = text or ""
    words = re.findall(r"[a-z]+", t.lower())
    return dict(lang=lang(t), len=len(t), slot_template=1 if (len(t) < 300 and SLOT.search(t)) else 0,
                prompt_echo=1 if ECHO.search(t) else 0, prefix4=" ".join(words[:4]))

STOP = {"en": "the and of to is a in that for each with", "es": "el la de que y los las una por para", "fr": "le la les de et des une est pour que",
        "de": "der die und das ist nicht ein eine zu mit", "pt": "o a de que e os uma para com não", "it": "il la di che e per una con non sono"}
STOP = {k: set(v.split()) for k, v in STOP.items()}
def lang(t):
    if re.search(r"[\u3040-\u30ff]", t): return "ja"
    if re.search(r"[\uac00-\ud7af]", t): return "ko"
    if re.search(r"[\u4e00-\u9fff]", t): return "zh"
    if re.search(r"[\u0400-\u04ff]", t): return "ru"
    if re.search(r"[\u0600-\u06ff]", t): return "ar"
    w = re.findall(r"[a-zà-ÿ]+", t.lower())
    if not w: return "unknown"
    sc = {k: sum(1 for x in w if x in v) for k, v in STOP.items()}
    best = max(sc, key=sc.get)
    return best if sc[best] >= 2 else "unknown"

# On-demand upstream reads made while serving a page (tx detail, address balance). They must never pile up
# behind a slow or down upstream: short timeout, at most ONDEMAND_MAX at once, one fetch per id, and the
# endpoint's backoff is honoured, so during maintenance pages answer from what is stored instead of waiting.
ONDEMAND_MAX = int(os.environ.get("POASCAN_ONDEMAND_MAX", "3"))
ONDEMAND_TIMEOUT = float(os.environ.get("POASCAN_ONDEMAND_TIMEOUT", "8"))
_ondemand = threading.BoundedSemaphore(ONDEMAND_MAX)
_tx_lock = threading.Lock(); _tx_inflight = {}

def fetch_ondemand(path, endpoint):
    if not can_fetch(endpoint): raise Busy("upstream backing off")
    if not _ondemand.acquire(timeout=0.5): raise Busy("upstream busy")
    try: return fetch(path, timeout=ONDEMAND_TIMEOUT, endpoint=endpoint)
    finally: _ondemand.release()

def get_tx_detail(tid, allow_fetch=True):
    r = db.q1("SELECT json, fetched, final FROM tx_detail WHERE id=?", (tid,))
    if r and (r["final"] or time.time() - r["fetched"] < 120):
        return json.loads(r["json"])
    if not allow_fetch:
        return json.loads(r["json"]) if r else None
    with _tx_lock:
        ev = _tx_inflight.get(tid); mine = ev is None
        if mine: ev = _tx_inflight[tid] = threading.Event()
    if not mine:                        # another request is fetching this tx: wait briefly, then use what is stored
        ev.wait(ONDEMAND_TIMEOUT + 2)
        return get_tx_detail(tid, allow_fetch=False)
    try:
        d = fetch_ondemand(f"/api/explorer/tx/{tid}", "/api/explorer/tx/:id")
    except Busy:
        if r: return json.loads(r["json"])
        raise
    finally:
        with _tx_lock: _tx_inflight.pop(tid, None)
        ev.set()
    if isinstance(d, dict) and d.get("id"):
        db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,?)", (tid, json.dumps(d), int(time.time()), 1 if d.get("final") else 0))
        upsert_txs([d], "explorer/tx")
    return d

def job_sample(n=20):
    rows = db.q("""SELECT id, from_addr, ts, epoch FROM txs WHERE type='challenge' AND id NOT IN (SELECT id FROM answers)
                   ORDER BY ts DESC LIMIT 400""")
    random.shuffle(rows)
    for r in rows[:n]:
        time.sleep(1.0)
        try: d = get_tx_detail(r["id"])
        except Busy: break
        body = (d or {}).get("body") or {}
        c = classify(body.get("answer", ""))
        db.write("INSERT OR REPLACE INTO answers VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (r["id"], r["from_addr"], body.get("epoch", r["epoch"]), r["ts"], c["len"], c["slot_template"], c["prompt_echo"], c["prefix4"],
                  int(time.time()), body.get("answer", ""), c["lang"]))

# ---------------- seeding from earlier public snapshots (optional) ----------------
def seed(seed_dir):
    """Import previously captured public snapshots (same endpoints) so a fresh box has history."""
    if not seed_dir or not os.path.isdir(seed_dir): return
    if db.q1("SELECT 1 AS x FROM blobs WHERE kind='seeded'"): return
    log.info("seeding from %s", seed_dir)
    def J(p):
        try: return json.load(open(p))
        except Exception: return None
    raw = os.path.join(seed_dir, "dashboard", "raw")
    e = J(os.path.join(raw, "epochs.json"))
    if isinstance(e, list) and e: db.put_blob("epochs", e)
    for kind in ("params", "release", "notices", "ballots", "chains", "networks"):
        d = J(os.path.join(raw, kind + ".json"))
        if d is not None: db.put_blob(kind, d)
    a = J(os.path.join(raw, "anchors.json"))
    if a:
        db.put_blob("anchors", a)
        db.write("INSERT OR IGNORE INTO anchors VALUES(?,?,?,?,?,?,?)",
                 [(x["height"], x["chain"], x.get("tx_hash") or x.get("tx_signature"), x.get("state_root"), x.get("anchored_by"), x.get("memo"), x.get("anchored_at")) for x in a], many=True)
    # status history points (mainnet only; all captured from unprefixed /api/status after launch)
    for p in ["st.json", "status_m2.json", "status_now.json", "dashboard/raw/status.json", "dashboard/raw/status_1141.json"]:
        d = J(os.path.join(seed_dir, p))
        if d and d.get("as_of"):
            import datetime as dt
            ts = int(dt.datetime.fromisoformat(d["as_of"].replace("Z", "+00:00")).timestamp())
            db.add_snap("status", dict(d, seeded=True), ts)
    t = J(os.path.join(raw, "txs.json"))
    if t: upsert_txs(t.get("valid", []), "seed")
    # mainnet address histories captured Oct 19 evening (explorer/address responses)
    for p in ["research/explorer.json", "research/explorer2.json"]:
        d = J(os.path.join(seed_dir, p)) or {}
        for v in d.values():
            if isinstance(v, dict): upsert_txs(v.get("txs", []), "seed")
    ag = J(os.path.join(raw, "agents.json"))
    if ag:
        now = int(time.time())
        db.write("INSERT OR IGNORE INTO accounts VALUES(?,?,?,?,?,?,?,?)",
                 [(x["addr"], x.get("invited_by"), float(x.get("balance") or 0), x.get("balance"), x.get("ts"), x.get("joined_epoch"), now, now) for x in ag], many=True)
    comms = J(os.path.join(raw, "forum", "communities.json"))
    if comms: db.put_blob("communities", comms)
    for f in glob.glob(os.path.join(raw, "forum", "posts", "*.json")):
        d = J(f)
        if d: ingest_post(d)
    s = J(os.path.join(raw, "chall", "sample80.json")) or {}
    for tid, d in s.items():
        if "body" in d:
            db.write("INSERT OR REPLACE INTO tx_detail VALUES(?,?,?,?)", (tid, json.dumps(d), int(time.time()), 1 if d.get("final") else 0))
            c = classify(d["body"].get("answer", ""))
            db.write("INSERT OR REPLACE INTO answers VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (tid, d.get("from_addr"), d["body"].get("epoch"), d.get("ts"), c["len"], c["slot_template"], c["prompt_echo"], c["prefix4"],
                      int(time.time()), d["body"].get("answer", ""), c["lang"]))
    import csv
    cp = os.path.join(os.path.dirname(__file__), "..", "data", "census.csv")
    if os.path.exists(cp):
        rows = [r for r in csv.DictReader(open(cp)) if r["addr"].startswith("poa1") and r["label"]]
        db.write("INSERT OR IGNORE INTO labels VALUES(?,?,?,?,?)", [(r["addr"], r["label"], None, "census.csv registration label (Oct 19)", 0) for r in rows], many=True)
    db.put_blob("seeded", {"from": seed_dir})

# ---------------- scheduler ----------------
# How often each upstream source is read when healthy (for the /status freshness table).
EVERY = {"/api/explorer/txs": 60, "/api/status": 60, "/api/networks": 60, "/api/swaps": 60, "/api/txs": 600, "/api/anchors": 300,
         "/api/notices": 300, "/api/ballots": 300, "/api/epochs": 300, "/api/agents": 900, "/api/params": 3600, "/api/release": 3600,
         "/api/chains": 3600, "/lableak/api/communities": 1800, "/lableak/api/posts": 1800}

_SWAP_JOBS = __import__("poascan.swap.indexer", fromlist=["x"]).JOBS   # the swap module's jobs, at their old slots
JOBS = [  # name, fn, interval seconds, endpoint key used for backoff
    ("live", job_live, 60, "/api/explorer/txs"),
    _SWAP_JOBS[0],   # swaps: open-offer book, 60 s
    ("probe", job_probe, 600, None),
    _SWAP_JOBS[1],   # fx: SOL/ETH USD reference, 15 min
    ("window", job_window, 600, "/api/txs"),
    ("meta", job_meta, 300, None),
    ("epochs", job_epochs, 300, "/api/epochs"),
    ("agents", job_agents, 900, "/api/agents"),
    ("hourly", job_hourly_meta, 3600, None),
    ("forum", job_forum, 1800, "/lableak/api/communities"),
    ("sample", job_sample, 1800, "/api/explorer/tx/:id"),
    ("census", lambda: __import__("poascan.agents", fromlist=["x"]).census_job(), 86400, None),
    ("pulse", lambda: __import__("poascan.pulse", fromlist=["x"]).job(), 300, None),   # private live prober, off the node; no-op without POASCAN_PULSE_SRC
    ("halts", lambda: __import__("poascan.halts", fromlist=["x"]).job(), 600, None),   # private tracker, off the node; no-op without POASCAN_HALT_SRC
]

def run_forever(stop=None):
    last = {}
    while not (stop and stop.is_set()):
        now = time.time()
        for name, fn, every, ep in JOBS:
            if now - last.get(name, 0) < every: continue
            if ep and not can_fetch(ep): continue
            last[name] = now
            try:
                fn()
            except Busy as e:
                log.warning("job %s busy: %s", name, e)
            except Exception as e:
                log.exception("job %s failed: %s", name, e)
            db.put_blob("job:" + name, {"ran": int(time.time())})
            time.sleep(2)  # spacing between jobs
        time.sleep(5)

def start(seed_dir=None):
    db.init()
    try: seed(seed_dir)
    except Exception as e: log.exception("seed failed: %s", e)
    th = threading.Thread(target=run_forever, daemon=True, name="indexer"); th.start()
    return th
