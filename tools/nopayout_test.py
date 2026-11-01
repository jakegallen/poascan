"""Zero-payout closes (1.26.251): a close that pays nothing because no answer reached the four grader quorum (rewards {},
paid 0, minted 0) reads as a clear state, not missing data. Covers the epoch row, the nopay_tag helper, the epoch page (the
No payout tag, the "Closed, no payout (no answer reached quorum)." note in place of the empty Payouts table, the neutral
header with no asserted burn figure) and the epochs list and Home tag. No network. Usage: python3 tools/nopayout_test.py"""
import os, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "x.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
def nodash(h): return "\u2014" not in h and "\u2013" not in h and "&mdash;" not in h and "&ndash;" not in h

import fixture; fixture.seed()
from poascan import db, analytics as A, views as V

# the latest close pays nothing: no rewards and nothing settled (no answer reached the grading quorum)
eps = db.get_blob("epochs")[0]; z = int(eps[-1]["epoch"])
eps[-1]["rewards"] = {}; eps[-1]["basis"]["settled"] = []
db.put_blob("epochs", eps); A._cache.clear()

r = next(x for x in A.epoch_rows() if x["epoch"] == z)
check(f"epoch row is a zero-payout close (paid {r['paid']}, minted {r['minted']})",
      r["paid"] == 0 and r["minted"] == 0 and r["settled_passed"] == 0 and r["settled_failed"] == 0)
check("row still exposes burn_pct as before (additive, no field dropped)", r["burn_pct"] == 100)

# the tag helper (CPZ.tag idiom): present for a zero-payout close, empty when something was paid
t = V.nopay_tag(r)
check("nopay_tag renders a warn tag that reads No payout", 'class="tag warn"' in t and ">No payout</span>" in t
      and "No answer reached the grading quorum" in t)
check("nopay_tag is empty when something was paid", V.nopay_tag({"paid": 3, "minted": 5.0}) == ""
      and V.nopay_tag({"paid": 0, "minted": 2.0}) == "")

# the epoch page
ep = V.epoch(z); ep = ep[1] if isinstance(ep, tuple) else ep
check("epoch page shows the No payout tag", ">No payout</span>" in ep)
check("epoch page: Payouts reads the no-payout note, not an empty table", "Closed, no payout (no answer reached quorum)." in ep)
check("epoch page header reads 0 Agents paid, no payout", "0 Agents paid · no payout" in ep)
check("epoch page does not assert a burned percent as fact for this close", "% burned" not in ep and "100.00%" not in ep)

# the epochs list and Home
lst = V.epochs_table(A.epoch_rows())
check("epochs list shows the No payout tag", ">No payout</span>" in lst)
home = V.home_epochs(A.epoch_rows())
check("Home closes show the No payout tag", ">No payout</span>" in home)

# a normal (paid) close is unchanged: no tag, header still carries the burn figure
paid_n = next(x for x in A.epoch_rows() if x["paid"] > 0 and x["epoch"] != z)["epoch"]
pp = V.epoch(paid_n); pp = pp[1] if isinstance(pp, tuple) else pp
check("a paid close keeps its burned figure and shows no No payout tag", "burned</span>" in pp and ">No payout</span>" not in pp)

txt = t + ep + lst + home + pp
check("no em or en dashes", nodash(txt))
check("says Agents, never Accounts", "Accounts" not in txt)

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
