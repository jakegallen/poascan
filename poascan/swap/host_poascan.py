"""POAScan as the swap module's host: its database, cache, rate-limited minepoa.com client, page layout and HTML helpers.
Loaded through host.py (the default host). Another site supplies its own host module."""
from html import escape as E   # noqa: F401  (re-exported)

# ---- storage: one SQLite database; the module owns the swaps and swap_events tables, and reads two host blobs (fx, chains) ----
from .. import db as _db
q, q1, write, get_blob, put_blob = _db.q, _db.q1, _db.write, _db.get_blob, _db.put_blob

# ---- cache decorator (key, ttl seconds) ----
from .. import analytics as _A
cached = _A.cached

# ---- network facts the module needs from the core indexer ----
def params(): return _A.params()                     # /api/params (swap_fee_bp)
def supply(): return float(_A.status().get("supply") or 0) or None   # mined supply, for FDV
def circulating(): return _A.supply_split().get("spendable")         # spendable POA, for Market Cap and the Sell max
def names(): return _A.forum_names()                 # poa1 address -> agent name, for maker and taker links
def final_fill_ids():
    """swap-fill txs the ledger has finalized (core txs table): trades count only once final."""
    return {r["id"] for r in _db.q("SELECT id FROM txs WHERE type='swap-fill' AND final=1")}
def tx_marks(ids):
    """Attestation count and final flag per tx id, from the core txs table (the explorer feed keeps them current)."""
    ids = [i for i in ids if i]
    if not ids: return {}
    return {r["id"]: (r["atts"], r["final"]) for r in _db.q(f"SELECT id, atts, final FROM txs WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))}
def swap_tx_ids():
    """Swap txs the core indexer has archived, oldest first; the swap indexer reads each one's detail once."""
    return [r["id"] for r in _db.q("SELECT id FROM txs WHERE type LIKE 'swap-%' OR type='attest-fill' ORDER BY ts")]

# ---- upstream reads: the host's rate-limited, backed-off client for minepoa.com ----
_LAZY = ("fetch", "get_tx_detail", "Busy", "UA")   # fetch(path, timeout, endpoint), get_tx_detail(txid), Busy (rate limit hit), UA
def __getattr__(n):   # resolved on first use, so the host indexer can import the swap jobs without a cycle
    if n in _LAZY:
        from .. import indexer as _I
        return getattr(_I, n)
    raise AttributeError(n)
def fetch_log(endpoint):
    """Last ok / last error of the host's scheduled read of an upstream endpoint (no extra upstream call)."""
    return _db.q1("SELECT last_ok, last_err, err, fails FROM fetch_log WHERE endpoint=?", (endpoint,)) or {}

# ---- page layout and HTML helpers ----
def page(title, body, active, head=""):
    """The host's page chrome (header, nav, footer, base stylesheet) around the module's body; head goes into <head>."""
    from .. import views
    return views.page(title, body, active, head)
from ..ui import card, table, poa, utc, rel, addr_link, tx_link, line, plain, short, chart_skel, stat, intc, _ic  # noqa: F401,E402
from ..join import pbox, apps  # noqa: F401,E402   (the prompt box and the "Open in" app set)
