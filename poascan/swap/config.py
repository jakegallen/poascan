"""Swap module settings. Everything that differs between poascan.io/swaps and a standalone swap.example.com lives here.
Each can be set from the environment, so the spin-out is a deploy flag, not a code change."""
import os

def _env(k, d): return os.environ.get(k, d)

BRAND = _env("SWAP_BRAND", "POAScan")                    # site name in titles and copy
BASE_URL = _env("SWAP_BASE_URL", "https://poascan.io")   # public origin that serves the swap page and API
PAGE_PATH = _env("SWAP_PAGE_PATH", "/swaps")             # "/" on swap.example.com
API_PATH = _env("SWAP_API_PATH", "/api/v1")              # versioned API prefix on BASE_URL
METHOD_URL = _env("SWAP_METHOD_URL", "https://poascan.io/about#market")   # how the USD reference is built
START_URL = _env("SWAP_START_URL", "https://poascan.io/start")       # where a new agent starts (the host's onboarding)
UPSTREAM = "https://minepoa.com"                          # the network's own swap flow; never a third party

SWAPS_LIVE = False      # False: /swaps is a live preview with a "Coming soon" button; True: normal swap flow
STATS_WINDOW = "all"    # stats row: "all" shows cumulative Trades and Volume, "24h" the last 24 hours
FRESH_S = 900           # swaps data older than this (or a failed last fetch) reads as "being upgraded"
SWAPS_EP = "/api/swaps" # upstream endpoint the indexer polls (60 s, with the host's backoff)

PAGE_URL = BASE_URL + PAGE_PATH
PAGE_LABEL = PAGE_PATH if PAGE_PATH != "/" else BASE_URL.split("//", 1)[-1].rstrip("/")   # link text: /swaps, or swap.example.com at a site root
STATUS_URL = BASE_URL + API_PATH + "/swaps/status"

def link(url):
    """href for a URL: same-origin links stay relative (so poascan.io renders exactly as before), others stay absolute."""
    return url[len(BASE_URL):] or "/" if url.startswith(BASE_URL + "/") or url == BASE_URL else url
