"""1.26.436 polish: the Agent header shows a chip once (model and harness both Undisclosed showed it twice); bar charts with
more than four x labels mark every other one .xo so a 390px phone hides it (style.css); tx_counts is cached so /api/health
no longer scans every tx per call; /about says Reference, not Full list. Temp database, no network.
Usage: python3 tools/better1128_test.py"""
import os, re, sys, tempfile
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "b.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from poascan import db, analytics as A, profile as PF, ui as U
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()

h = PF.tags(True, "safe", {"eco": "Undisclosed", "harness": ["Undisclosed"]})
check(f"Undisclosed chip once ({h.count('>Undisclosed<')})", h.count(">Undisclosed<") == 1)
h2 = PF.tags(True, "safe", {"eco": "Anthropic", "harness": ["Hermes Agent (Nous)", "Cursor"]})
check("distinct chips all kept, order kept", re.findall(r">([^<]+)</span>", h2) == ["Established", "Safe", "Anthropic", "Hermes Agent (Nous)", "Cursor"])
check("no census: no empty chip", PF.tags(False, None, None) == "")

ser = [(f"Nov {d}", [d, 1]) for d in range(1, 61)]
ch = U.bars(ser, height=170, legend=["Added", "Removed"], stacked=False)
xl = re.findall(r'class="xl[^"]*"', ch)
check(f"many labels: every other one is xo ({xl})", len(xl) > 4 and all(("xo" in c) == bool(k % 2) for k, c in enumerate(xl)))
few = U.bars([("Nov 1", [1]), ("Nov 2", [2]), ("Nov 3", [3])])
check("four labels or fewer: none hidden", "xo" not in " ".join(re.findall(r'class="xl[^"]*"', few)))
css = open(os.path.join(HERE, "..", "static", "style.css")).read()
check("phone rule hides .ck .xl.xo", re.search(r"@media \(max-width:640px\)\{\.ck \.xl\.xo\{display:none\}\}", css) is not None)

db.write("INSERT INTO txs(id, type, ts, first_seen) VALUES(?,?,?,?)", ("a" * 64, "transfer", 1795000000, 1795000000))
A._cache.clear(); n1 = A.tx_counts()["n"]
db.write("INSERT INTO txs(id, type, ts, first_seen) VALUES(?,?,?,?)", ("b" * 64, "transfer", 1795000001, 1795000001))
check("tx_counts is cached (same count inside its TTL)", A.tx_counts()["n"] == n1 == 1)
A._cache.clear()
check("tx_counts recounts once the cache is cleared", A.tx_counts()["n"] == 2)

src = open(os.path.join(HERE, "..", "poascan", "views.py")).read()
check("/about: no Full list label", "Full list" not in src and 'Reference: <a href="/api">/api</a>' in src)
print("\n" + (f"{len(fails)} failed" if fails else "all passed")); sys.exit(1 if fails else 0)
