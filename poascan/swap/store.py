"""The module's own tables. The host database creates them through init() (called from the host's db.init)."""
from . import host as H

SCHEMA = """
CREATE TABLE IF NOT EXISTS swaps(offer_id TEXT PRIMARY KEY, maker TEXT, poa REAL, chain TEXT, asset TEXT, want REAL, pay_to TEXT,
  expires_ts INTEGER, created_ts INTEGER, status TEXT, taker TEXT, fill_txid TEXT, fill_ts INTEGER, ext_ref TEXT,
  cancel_txid TEXT, cancel_ts INTEGER, fee_bp INTEGER, memo TEXT, last_open_seen INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS swap_events(txid TEXT PRIMARY KEY, offer_id TEXT, kind TEXT, addr TEXT, ts INTEGER, json TEXT);
"""

def init(conn):
    """Create or migrate the swap tables on a sqlite3 connection (inside the host's write lock)."""
    conn.executescript(SCHEMA)
    if "fill_usd" not in {r[1] for r in conn.execute("PRAGMA table_info(swaps)")}:
        conn.execute("ALTER TABLE swaps ADD COLUMN fill_usd REAL")  # USD per unit of the paid asset, recorded when the fill is indexed

def swaps_all(): return H.q("SELECT * FROM swaps ORDER BY COALESCE(fill_ts, cancel_ts, created_ts, last_open_seen) DESC")
def offer(oid): return H.q1("SELECT * FROM swaps WHERE offer_id=?", (oid,)) if oid else None
def events(oid): return H.q("SELECT * FROM swap_events WHERE offer_id=? ORDER BY ts", (oid,))
def open_count(): return H.q1("SELECT COUNT(*) AS n FROM swaps WHERE status='open'")["n"]
def fx(): return H.get_blob("fx")[0] or {}   # {"SOL": usd, "ETH": usd, "src": "CoinGecko"}, written by indexer.job_fx
def chains(): return H.get_blob("chains")[0] or {}
def events_all():
    """Every swap tx event, grouped by offer, oldest first."""
    out = {}
    for e in H.q("SELECT offer_id, txid, kind, ts FROM swap_events ORDER BY ts"): out.setdefault(e["offer_id"], []).append(e)
    return out
def fx_ts(): return H.get_blob("fx")[1]
