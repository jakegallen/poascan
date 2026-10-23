"""SQLite storage for POAScan. One file, WAL mode, one connection per thread."""
from . import keysafe as _KS
import os, sqlite3, threading, json, time

DB_PATH = os.environ.get("POASCAN_DB", os.path.join(os.path.dirname(__file__), "..", "data", "poascan.db"))
_local = threading.local()
_wlock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS txs(
  id TEXT PRIMARY KEY, type TEXT, from_addr TEXT, to_addr TEXT, amount TEXT, memo TEXT,
  invited_by TEXT, epoch INTEGER, ts INTEGER, atts INTEGER, k INTEGER, final INTEGER,
  first_seen INTEGER, last_seen INTEGER, source TEXT);
CREATE INDEX IF NOT EXISTS txs_ts ON txs(ts DESC);
CREATE INDEX IF NOT EXISTS txs_from ON txs(from_addr, ts DESC);
CREATE INDEX IF NOT EXISTS txs_to ON txs(to_addr, ts DESC);
CREATE INDEX IF NOT EXISTS txs_type ON txs(type, ts DESC);
CREATE INDEX IF NOT EXISTS txs_from_k ON txs(from_addr, ts DESC, id DESC);
CREATE INDEX IF NOT EXISTS txs_to_k ON txs(to_addr, ts DESC, id DESC);
CREATE TABLE IF NOT EXISTS invalid_txs(txid TEXT PRIMARY KEY, error TEXT, first_seen INTEGER);
CREATE TABLE IF NOT EXISTS tx_detail(id TEXT PRIMARY KEY, json TEXT, fetched INTEGER, final INTEGER);
CREATE TABLE IF NOT EXISTS snaps(kind TEXT, ts INTEGER, json TEXT);
CREATE INDEX IF NOT EXISTS snaps_kind ON snaps(kind, ts DESC);
CREATE TABLE IF NOT EXISTS blobs(kind TEXT PRIMARY KEY, ts INTEGER, json TEXT);
CREATE TABLE IF NOT EXISTS accounts(addr TEXT PRIMARY KEY, invited_by TEXT, balance REAL, balance_s TEXT,
  api_ts INTEGER, api_joined_epoch INTEGER, first_seen INTEGER, last_seen INTEGER);
CREATE TABLE IF NOT EXISTS anchors(height INTEGER, chain TEXT, tx TEXT, state_root TEXT, anchored_by TEXT,
  memo TEXT, anchored_at TEXT, PRIMARY KEY(height, chain));
CREATE TABLE IF NOT EXISTS forum_posts(id INTEGER PRIMARY KEY, community TEXT, title TEXT, author TEXT,
  author_public_id TEXT, created_at TEXT, score INTEGER, comment_count INTEGER, deleted INTEGER, pinned INTEGER, fetched INTEGER, body TEXT);
CREATE TABLE IF NOT EXISTS forum_comments(id INTEGER PRIMARY KEY, post_id INTEGER, parent_id INTEGER, author TEXT,
  author_public_id TEXT, created_at TEXT, score INTEGER, body TEXT);
CREATE TABLE IF NOT EXISTS answers(id TEXT PRIMARY KEY, from_addr TEXT, epoch INTEGER, ts INTEGER, len INTEGER,
  slot_template INTEGER, prompt_echo INTEGER, prefix4 TEXT, sampled_at INTEGER, text TEXT, lang TEXT);
CREATE TABLE IF NOT EXISTS labels(addr TEXT PRIMARY KEY, label TEXT, custody TEXT, source TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS probes(ts INTEGER, endpoint TEXT, ok INTEGER, ms INTEGER, code TEXT);
CREATE INDEX IF NOT EXISTS probes_ep ON probes(endpoint, ts);
CREATE INDEX IF NOT EXISTS probes_ts ON probes(ts);
CREATE TABLE IF NOT EXISTS uptime_daily(day INTEGER, endpoint TEXT, n INTEGER, ok INTEGER, ms INTEGER, PRIMARY KEY(day, endpoint));
CREATE TABLE IF NOT EXISTS fetch_log(endpoint TEXT PRIMARY KEY, last_ok INTEGER, last_err INTEGER, err TEXT,
  fails INTEGER, next_at INTEGER, bytes INTEGER);
-- aggregate visit counts (poascan/visits.py): daily totals only; no column can hold an IP, user agent, hash, path or URL
CREATE TABLE IF NOT EXISTS visit_views(day TEXT NOT NULL, grp TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('human','bot','agent')),
  views INTEGER NOT NULL DEFAULT 0 CHECK (views >= 0), PRIMARY KEY (day, grp, kind)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS visit_referrers(day TEXT NOT NULL, domain TEXT NOT NULL CHECK (length(domain) <= 64),
  views INTEGER NOT NULL DEFAULT 0 CHECK (views >= 0), PRIMARY KEY (day, domain)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS visit_uniques(day TEXT PRIMARY KEY, uniques INTEGER NOT NULL DEFAULT 0,
  segments INTEGER NOT NULL DEFAULT 1) WITHOUT ROWID;
-- daily event counts (1.23.0): every key comes from a fixed allowlist or pattern in visits.py (route template, tool name, prompt id, tag)
-- 1.26.44 adds 'pjoin' (/api/v1/prompts/join fetches by registry client id); init() rebuilds an older table to allow it
CREATE TABLE IF NOT EXISTS visit_counts(day TEXT NOT NULL, metric TEXT NOT NULL CHECK (metric IN ('api','mcp','client','prompt','tag','device','country','edge','search','404','5xx','ms','pjoin')),
  key TEXT NOT NULL CHECK (length(key) <= 64), n INTEGER NOT NULL DEFAULT 0 CHECK (n >= 0), PRIMARY KEY (day, metric, key)) WITHOUT ROWID;
-- daily network rollup (1.24.0, poascan/network.py): per UTC day aggregates of archived txs and snapshots, updated incrementally
CREATE TABLE IF NOT EXISTS network_daily(day INTEGER PRIMARY KEY, txs TEXT, snaps TEXT, updated INTEGER);
CREATE TABLE IF NOT EXISTS network_first(addr TEXT PRIMARY KEY, ts INTEGER NOT NULL) WITHOUT ROWID;
-- private ops counters (1.26.26, poascan/opsinternal.py): the hosted route check per read, and upstream reads POAScan chose not to send
CREATE TABLE IF NOT EXISTS route_checks(ts INTEGER NOT NULL, route TEXT NOT NULL, code TEXT NOT NULL CHECK (length(code) <= 8), ms INTEGER, ok INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS route_checks_ts ON route_checks(ts);
-- signup check-ins (1.26.31, poascan/checkin.py): allowlisted version, client and step; the public poa1 address and a time.
-- No IP, user agent, URL, query string or key is ever stored.
CREATE TABLE IF NOT EXISTS checkin_counts(day TEXT NOT NULL, version TEXT NOT NULL CHECK (length(version) <= 8), client TEXT NOT NULL CHECK (length(client) <= 24),
  step TEXT NOT NULL CHECK (step IN ('start','joined')), n INTEGER NOT NULL DEFAULT 0 CHECK (n >= 0), PRIMARY KEY(day, version, client, step)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS checkin_addrs(addr TEXT PRIMARY KEY CHECK (addr LIKE 'poa1%' AND length(addr) <= 64), version TEXT NOT NULL CHECK (length(version) <= 8),
  client TEXT NOT NULL CHECK (length(client) <= 24), ts INTEGER NOT NULL) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS checkin_addrs_ts ON checkin_addrs(ts);
CREATE TABLE IF NOT EXISTS checkin_rates(day TEXT NOT NULL, version TEXT NOT NULL CHECK (length(version) <= 8), client TEXT NOT NULL CHECK (length(client) <= 24),
  route TEXT NOT NULL CHECK (route IN ('register','challenge','answer','mine','me')), n INTEGER NOT NULL DEFAULT 0 CHECK (n >= 0), PRIMARY KEY(day, version, client, route)) WITHOUT ROWID;
-- v2.4 probe check-ins (1.26.36): a count per day, version and client that an agent opened a link it built. The word is never stored.
CREATE TABLE IF NOT EXISTS checkin_probes(day TEXT NOT NULL, version TEXT NOT NULL CHECK (length(version) <= 8), client TEXT NOT NULL CHECK (length(client) <= 24),
  n INTEGER NOT NULL DEFAULT 0 CHECK (n >= 0), PRIMARY KEY(day, version, client)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS upstream_denials(day TEXT NOT NULL, endpoint TEXT NOT NULL CHECK (length(endpoint) <= 80), reason TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, endpoint, reason)) WITHOUT ROWID;
"""

def conn():
    c = getattr(_local, "c", None)
    if c is None:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        _local.c = c
    return c

def init():
    with _wlock:
        conn().executescript(SCHEMA)
        from .swap import store as _swap_store   # the swap module owns and migrates its own tables
        _swap_store.init(conn())
        _visit_counts_pjoin()
        for t in ("forum_posts", "forum_comments"):   # LabLeak author edits set edited_at (shown publicly as an edit)
            if "edited_at" not in {r[1] for r in conn().execute(f"PRAGMA table_info({t})")}:
                conn().execute(f"ALTER TABLE {t} ADD COLUMN edited_at TEXT")
        conn().commit()

def _visit_counts_pjoin():
    """1.26.44: SQLite cannot change a CHECK in place, so a visit_counts table from before 'pjoin' is copied into a new one
    with the wider CHECK, in one transaction (every row kept, same columns and key). Runs once; a no-op afterwards."""
    c = conn(); r = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='visit_counts'").fetchone()
    if not r or "'pjoin'" in r[0]: return
    new = r[0].replace("'ms')", "'ms','pjoin')", 1).replace("visit_counts(", "visit_counts_new(", 1).replace("IF NOT EXISTS ", "", 1)
    if "'pjoin'" not in new: raise RuntimeError("visit_counts CHECK not recognised; not migrating")
    c.commit()
    c.executescript("BEGIN IMMEDIATE; DROP TABLE IF EXISTS visit_counts_new; " + new + "; INSERT INTO visit_counts_new(day,metric,key,n) SELECT day,metric,key,n FROM visit_counts;"
                    " DROP TABLE visit_counts; ALTER TABLE visit_counts_new RENAME TO visit_counts; COMMIT;")

def _clean(a):
    """No PoA key is ever stored: key-shaped tokens in any written string are redacted (poascan/keysafe.py)."""
    if isinstance(a, (list, tuple)): return type(a)(_clean(x) for x in a)
    return _KS.redact(a) if isinstance(a, str) else a

def write(sql, args=(), many=False):
    args = [_clean(r) for r in args] if many else _clean(args)
    with _wlock:
        c = conn()
        if many: c.executemany(sql, args)
        else: c.execute(sql, args)
        c.commit()

def write_tx(stmts):
    """Several statements in one transaction under the write lock: [(sql, args, many), ...]."""
    with _wlock:
        c = conn()
        try:
            for sql, args, many in stmts:
                if many:
                    if args: c.executemany(sql, [_clean(r) for r in args])
                else: c.execute(sql, _clean(args))
            c.commit()
        except Exception:
            c.rollback(); raise

def q(sql, args=()):
    return [dict(r) for r in conn().execute(sql, args).fetchall()]

def q1(sql, args=()):
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None

def put_blob(kind, obj):
    write("INSERT OR REPLACE INTO blobs(kind, ts, json) VALUES(?,?,?)", (kind, int(time.time()), json.dumps(obj)))

def get_blob(kind):
    r = q1("SELECT ts, json FROM blobs WHERE kind=?", (kind,))
    return (json.loads(r["json"]), r["ts"]) if r else (None, None)

def add_snap(kind, obj, ts=None):
    write("INSERT INTO snaps(kind, ts, json) VALUES(?,?,?)", (kind, int(ts or time.time()), json.dumps(obj)))
