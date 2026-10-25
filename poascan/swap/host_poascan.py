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
def swap_writes():   # 1.26.127: ({swap_offer: {state, http, checked_at, since, stale}}, swaps_writable) from the write check
    from .. import hosted as _HO
    return _HO.writes()
def circulating_basis(): return _A.supply_split().get("circulating_basis")   # carry_unlocked, vesting_continues or unconfirmed (1.26.123)
def names(): return _A.forum_names()                 # poa1 address -> agent name, for maker and taker links
def epoch_of_ts(ts):
    """Network epoch a ledger timestamp falls in: the epoch of the first archived close after ts (a tx at a close's exact
    second belongs to the next epoch, as tx epochs on the ledger do). After the newest archived close it is the open epoch,
    but only when a /api/status read taken at or after ts reports no further close; otherwise None (not yet known)."""
    import bisect, datetime as _dt
    if not ts: return None
    rows = _A.epoch_rows()
    if not rows: return None
    k = bisect.bisect_right([r["close_ts"] for r in rows], int(ts))
    if k < len(rows): return int(rows[k]["epoch"])
    st, read_ts = _db.get_blob("status")
    st = st or {}
    try: as_of = int(_dt.datetime.fromisoformat(str(st.get("as_of")).replace("Z", "+00:00")).timestamp())
    except Exception: as_of = None
    seen = min([x for x in (as_of, read_ts) if x] or [0])
    return int(rows[-1]["epoch"]) + 1 if st.get("epochs_closed") == len(rows) and seen >= ts else None

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
# fetch(path, timeout, endpoint, cond), get_tx_detail(txid, bg=SWAP_TX_EP), Busy (rate limit hit), Missing (unknown id), NOT_MODIFIED (304), UA
_LAZY = ("fetch", "get_tx_detail", "Busy", "Missing", "NOT_MODIFIED", "SWAP_TX_EP", "UA")
def __getattr__(n):   # resolved on first use, so the host indexer can import the swap jobs without a cycle
    if n in _LAZY:
        from .. import indexer as _I
        return getattr(_I, n)
    raise AttributeError(n)
def segment_cuts():
    """Segment boundaries from the segments config (poascan/segments.py)."""
    from .. import segments as _S
    return _S.cuts()

_EVID = {}
def fill_evidence():
    """offer_id -> evidence entry from poascan/swap_evidence.json (fills shown settled by public balances)."""
    if not _EVID:
        import json as _j, os as _o
        p = _o.environ.get("POASCAN_SWAP_EVIDENCE", _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), "swap_evidence.json"))
        if not p: return _EVID   # set empty: no evidence file (tests of the ledger-only states)
        try: _EVID.update({x["offer_id"]: x for x in (_j.load(open(p, encoding="utf-8")).get("fills") or [])})
        except (OSError, ValueError): pass
    return _EVID

def blob_ts(kind):
    """When the host last stored a blob (no JSON parse)."""
    r = _db.q1("SELECT ts FROM blobs WHERE kind=?", (kind,)); return r["ts"] if r else None
def swap_flag():
    """POASwap's swap flag as POAScan reads it (poascan/swapflag.py): status, available, url, message, source, fetched_at.
    A host without this hook keeps the module's own minepoa.com read."""
    from .. import swapflag as _F
    from . import config as _C
    return _F.current(live=_C.SWAPS_LIVE)
def swap_flag_version():
    from .. import swapflag as _F
    return _F.version()
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
from ..regcode import attrs as reg_attrs  # noqa: F401,E402   (optional wallet registry step on the Add Wallet prompt)
