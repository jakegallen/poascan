"""SQLite storage for POAScan. One file, WAL mode, one connection per thread."""
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
CREATE TABLE IF NOT EXISTS swaps(offer_id TEXT PRIMARY KEY, maker TEXT, poa REAL, chain TEXT, asset TEXT, want REAL, pay_to TEXT,
  expires_ts INTEGER, created_ts INTEGER, status TEXT, taker TEXT, fill_txid TEXT, fill_ts INTEGER, ext_ref TEXT,
  cancel_txid TEXT, cancel_ts INTEGER, fee_bp INTEGER, memo TEXT, last_open_seen INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS swap_events(txid TEXT PRIMARY KEY, offer_id TEXT, kind TEXT, addr TEXT, ts INTEGER, json TEXT);
CREATE TABLE IF NOT EXISTS fetch_log(endpoint TEXT PRIMARY KEY, last_ok INTEGER, last_err INTEGER, err TEXT,
  fails INTEGER, next_at INTEGER, bytes INTEGER);
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
        if "fill_usd" not in {r[1] for r in conn().execute("PRAGMA table_info(swaps)")}:
            conn().execute("ALTER TABLE swaps ADD COLUMN fill_usd REAL")  # USD per unit of the paid asset, recorded when the fill is indexed
        conn().commit()

def write(sql, args=(), many=False):
    with _wlock:
        c = conn()
        if many: c.executemany(sql, args)
        else: c.execute(sql, args)
        c.commit()

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
