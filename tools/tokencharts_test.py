"""Token tab price and volume charts (1.26.354): built from swapclient price-history only, UTC days from the first fill
day to the last with no gap (a day with no fill keeps the last price, volume 0), USD only while the reference is shown
and every fill has its fill_usd, nothing when there are no fills, and no trade links in the cards.
Usage: python3 tools/tokencharts_test.py"""
import os, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "tc.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
from poascan import swapclient as SC, tokencharts as T
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

D = 1_792_540_800   # a UTC midnight
HIST = [dict(ts=D + 3600, asset="SOL", chain="solana", poa=10000.0, price_per_1m_poa=0.1, offer_id="a"),
        dict(ts=D + 2 * 86400 + 60, asset="SOL", chain="solana", poa=5000.0, price_per_1m_poa=0.3, offer_id="b"),
        dict(ts=D + 2 * 86400 + 7200, asset="SOL", chain="solana", poa=4000.0, price_per_1m_poa=0.4, offer_id="c"),
        dict(ts=D + 86400, asset="SOL", chain="solana", poa=0, price_per_1m_poa=0.9, offer_id="bad"),
        dict(ts=None, asset="SOL", price_per_1m_poa=1, poa=1)]
calls = []
def setup(hist, shown=False, fx=None):
    SC.price_history = lambda: calls.append("ph") or hist
    SC.price = lambda: {"shown": shown}
    SC.offers = lambda status=None: [dict(offer_id=k, fill_usd=v, status="filled") for k, v in (fx or {}).items()]
    T._c.clear()

setup(HIST); d = T.data()
check("days run first fill day to last, no gap", [t for _, _, t in d["volume"]] == [D, D + 86400, D + 2 * 86400])
check("volume per day, empty day is 0, bad rows skipped", [v for _, v, _ in d["volume"]] == [10000.0, 0.0, 9000.0] and d["fills"] == 3)
check("price is each day's last fill, an empty day keeps the day before", [v for _, v, _ in d["price"]] == [0.1, 0.1, 0.4])
check("unit is the traded asset while USD is withheld", d["unit"] == "SOL")
n = len(calls); T.data(); check("cached between calls", len(calls) == n)

setup(HIST, shown=True, fx={"a": 100.0, "b": 110.0})
check("USD needs every fill's fill_usd, else the asset", T.data()["unit"] == "SOL")
setup(HIST, shown=True, fx={"a": 100.0, "b": 110.0, "c": 120.0})
d = T.data(); check("USD at fill time when shown", d["unit"] == "USD" and [round(v, 6) for _, v, _ in d["price"]] == [10.0, 10.0, 48.0])

setup(HIST); h = T.cards_html()
check("two chart cards, terse titles", 'id="price"' in h and 'id="volume"' in h and "Price · SOL per 1M POA" in h and "Daily volume · POA" in h)
check("chart only: no trade link, offer book or alert", "poaswap" not in h.lower() and "/swap" not in h and "Buy" not in h and "alert" not in h.lower())
check("no dashes", "\u2014" not in h and "\u2013" not in h)
setup([]); check("no fills, no cards", T.cards_html() == "" and T.data() is None)
SC.price_history = lambda: HIST; check("an empty read is kept 30 s, not 5 min", T.data() is None)
T._c["d"] = (T._c["d"][0] - 31, None); check("after 30 s the next read fills the charts", T.data() is not None)
src = open(os.path.join(ROOT, "poascan", "tokencharts.py")).read()
check("reads only swapclient (no new upstream polling)", "urllib" not in src and "minepoa" not in src)
print("FAILED: " + ", ".join(fails) if fails else "all tokencharts checks passed"); sys.exit(1 if fails else 0)
