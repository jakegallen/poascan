"""The swap module's only door into its host app. Nothing else in poascan/swap imports the host.

The host is a module named by SWAP_HOST (default poascan.swap.host_poascan, POAScan itself; another site sets its own).
It provides storage (q, q1, write, get_blob, put_blob, cached), network facts (params, supply, circulating, names,
final_fill_ids, swap_tx_ids), upstream reads (fetch, get_tx_detail, Busy, UA, fetch_log), page chrome (page) and HTML
helpers (card, table, stat, pbox, apps, ...). A host that follows another instance's swap API instead of indexing
minepoa.com itself also provides upstream_health(), upstream_price() and upstream_market(); see market.py."""
import os as _os, importlib as _il

NAME = _os.environ.get("SWAP_HOST") or "poascan.swap.host_poascan"
_h = _il.import_module(NAME)
globals().update({k: v for k, v in vars(_h).items() if not (k.startswith("__") and k.endswith("__"))})
if hasattr(_h, "__getattr__"): __getattr__ = _h.__getattr__   # lazily resolved names (POAScan's indexer client)
