"""The module's own tables. The host database creates them through init() (called from the host's db.init)."""
import time
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
    cols = {r[1] for r in conn.execute("PRAGMA table_info(swap_events)")}
    if "final" not in cols:   # 1.26.3 (SC-005): ledger finality per swap tx; rows from before are re-read once (checked NULL)
        for c in ("final INTEGER", "checked INTEGER", "dropped INTEGER NOT NULL DEFAULT 0", "first_seen INTEGER"):
            conn.execute("ALTER TABLE swap_events ADD COLUMN " + c)
        conn.execute("UPDATE swap_events SET final=1, checked=0 WHERE txid IN (SELECT id FROM txs WHERE final=1)")
        conn.execute("UPDATE swap_events SET final=0, first_seen=COALESCE(ts, 0) WHERE final IS NULL")
        conn.execute("UPDATE swap_events SET first_seen=COALESCE(first_seen, ts, 0)")

def effective(r, now=None):
    """Read-time status (SC-006): an open or delisted offer past its expires_ts reads as expired, even between book reads."""
    now = time.time() if now is None else now
    if r.get("status") in ("open", "delisted") and r.get("expires_ts") is not None and r["expires_ts"] <= now:
        r = dict(r, status="expired")
    return r

def swaps_all():
    now = time.time()
    return [effective(r, now) for r in H.q("SELECT * FROM swaps ORDER BY COALESCE(fill_ts, cancel_ts, created_ts, last_open_seen) DESC")]
def offer(oid):
    r = H.q1("SELECT * FROM swaps WHERE offer_id=?", (oid,)) if oid else None
    return effective(r) if r else None
def events(oid):
    """Every stored swap tx of the offer, oldest first, with final (bool) and dropped; pending ones are not applied."""
    return [dict(e, final=bool(e.get("final")), dropped=bool(e.get("dropped"))) for e in H.q("SELECT * FROM swap_events WHERE offer_id=? ORDER BY ts, txid", (oid,))]
def open_count(): return H.q1("SELECT COUNT(*) AS n FROM swaps WHERE status='open' AND (expires_ts IS NULL OR expires_ts > ?)", (int(time.time()),))["n"]
def fx(): return H.get_blob("fx")[0] or {}   # {"SOL": usd, "ETH": usd, "src": "CoinGecko"}, written by indexer.job_fx
def chains(): return H.get_blob("chains")[0] or {}
def events_all():
    """Every final swap tx event, grouped by offer, oldest first (pending and dropped txs are left out)."""
    out = {}
    for e in H.q("SELECT offer_id, txid, kind, ts FROM swap_events WHERE final=1 AND dropped=0 ORDER BY ts, txid"): out.setdefault(e["offer_id"], []).append(e)
    return out
def fx_ts(): return H.get_blob("fx")[1]
