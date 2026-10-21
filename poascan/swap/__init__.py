"""Swap module: everything behind POAScan's /swaps, packaged so it can move to its own site (swap.example.com) as is.

Layout
  config.py   brand, base URL, page path, SWAPS_LIVE and other switches (env overridable)
  host.py     the only door into the host app: database, cache, upstream fetch, page layout, HTML helpers
  store.py    the swaps and swap_events tables and their reads
  indexer.py  scheduler jobs: offer book (60 s), swap tx details, SOL/ETH USD reference (15 min)
  market.py   availability, book, fills, market stats and the one POA/USD price (fills only)
  pages.py    the swap page; static/swap.css and static/swap.js
  prompts.py  agent prompts (Buy, Sell, Connect); nothing is signed here
  faq.py      the "How to buy POA" FAQ
  api.py      JSON routes, page route, static files, live fragment

The host wires it in at five points: db.init -> store.init, indexer JOBS += indexer.JOBS, server -> api.api / api.page /
api.STATIC, the live snapshot -> api.live, and its FAQ -> faq.PAGE. The explorer reads swap data only through the API
(poascan/swapclient.py). See LIFTING.md."""
from .api import api, page, live, STATIC  # noqa: F401
from .indexer import JOBS  # noqa: F401
from .store import init as init_db  # noqa: F401
