"""Swap module: the swap data behind POAScan's JSON routes (the pages moved to POASwap), packaged so it can run under
another host as is.

Layout
  config.py   brand, base URL, SWAPS_LIVE and other switches (env overridable)
  host.py     the only door into the host app: database, cache, upstream fetch, HTML helpers
  store.py    the swaps and swap_events tables and their reads
  indexer.py  scheduler jobs: offer book (60 s), swap tx details, SOL/ETH USD reference (15 min)
  market.py   availability, book, fills, market stats and the one POA/USD price (fills only)
  hoststatus.py  /api/v1/swaps/status, the route POASwap reads before every swap write
  api.py      JSON routes

The host wires it in at three points: db.init -> store.init, indexer JOBS += indexer.JOBS, server -> api.api. The explorer
reads swap data only through the API (poascan/swapclient.py)."""
from .api import api, etag  # noqa: F401
from .indexer import JOBS  # noqa: F401
from .store import init as init_db  # noqa: F401
