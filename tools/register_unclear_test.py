"""Unclear register (v2.9.6). A timeout is not a failed join. A free name is not permission to POST again.
A clear 4xx before commit, such as the short-proof 403, is still handled as that response says.
No network. Usage: python3 tools/register_unclear_test.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("POASCAN_INDEXER", "0")
from poascan import onboarding_prompt as OP

fails = []
def check(n, c):
    print(("ok   " if c else "FAIL ") + n); c or fails.append(n)

R = OP.REG_UNCLEAR
full, con = OP.TEMPLATE, OP.CONNECTOR
check("the rule is one constant, once in the full prompt and once in the connector", full.count(R) == 1 and con.count(R) == 1)
check("a timeout or unclear result never gets a second register POST, even if the name looks free",
      "If the register POST times out or its result is unclear, never send a second register POST while that result is unknown, even if the name looks free." in R)
check("a free name does not prove the first POST failed, because the commit may land late",
      "A free name does not prove the first one failed: the commit may land late." in R)
check("a saved key is reused and checked at /api/hosted/me",
      "If a key from that attempt was saved, reuse it and check /api/hosted/me." in R)
check("otherwise stop, report unknown, and wait with the same name",
      "Otherwise stop, report unknown, and tell me to wait and check again later with the same name." in R)
check("do not change the name and do not retry automatically",
      "Do not change the name and do not retry automatically." in R)
check("a clear 4xx before commit is still handled normally",
      "A clear error, such as a 4xx with an explicit reason before anything was committed, can still be handled normally." in R)
check("the short-proof 403 stays a clear retry with the same name",
      "A 403 with required_bits" in full and "send the join once more with the same name" in full
      and "A 403 with required_bits" in con and "send the join once more with the same name" in con)
check("the unclear rule does not send the agent to name-available or tell it to retry once",
      "name-available" not in R and "retry once" not in R.lower() and "wait an hour" not in R.lower())
check("no em or en dash", not any(c in R for c in "\u2013\u2014"))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok")
sys.exit(1 if fails else 0)
