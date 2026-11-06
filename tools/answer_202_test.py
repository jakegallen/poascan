"""Join prompt v2.9.6: the 202 answer rule is one constant, in both variants, with the trusted-origin check
and an explicit no-resubmit. The key backup is not described as wallet activation, download, or restore.
No network. Usage: python3 tools/answer_202_test.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("POASCAN_INDEXER", "0")
os.environ.setdefault("POASCAN_DB", os.path.join(os.path.dirname(__file__), "..", "poascan", "no.db"))
from poascan import onboarding_prompt as OP, start as S, agentapi as AG, faq as F

fails = []
def check(n, c):
    print(("ok   " if c else "FAIL ") + n); c or fails.append(n)

R = OP.ANSWER_202
full, con = OP.TEMPLATE, OP.CONNECTOR
check("v2.9.6", OP.VERSION == "v2.9.6")
check("ANSWER_202 is one constant and both variants carry it once", full.count(R) == 1 and con.count(R) == 1 and "job_id and poll_url" in R)
check("202 is accepted and pending, not failed and not complete", "accepted and pending, not failed and not complete" in R)
check("trusted origin: https minepoa.com /api/job/ same origin, no redirects, do not send the key",
      "https://minepoa.com/api/job/" in R and "same origin" in R and "Do not follow redirects." in R and "do not send the key" in R and "report unknown" in R)
check("wait the larger of Retry-After and retry_after_seconds, floor 5 seconds, stop after 3 minutes",
      "larger of any Retry-After header and any retry_after_seconds" in R and "at least 5 seconds" in R and "Stop after 3 minutes" in R)
check("never resubmit while pending or unknown", "Never resubmit this epoch's answer while the job is pending or unknown." in R)
check("timeout, 404 and 410 are unknown and not permission to resend; check /me or answered first",
      "A timeout, a 404 or a 410 is unknown" in R and "not permission to resend" in R and "/api/hosted/me or the challenge answered flag" in R)
check("409 duplicate_in_flight stays queued", "duplicate_in_flight" in R and "keep polling" in R and "do not resend" in R)
check("unclear register is its own constant, once in each variant", full.count(OP.REG_UNCLEAR) == 1 and con.count(OP.REG_UNCLEAR) == 1)
check("mine only after the answer is confirmed", "Mine only after the answer is confirmed." in R)
check("challenge stays GET, not POST", "/api/hosted/challenge" in full and "POST /api/hosted/challenge" not in full and "POST /api/hosted/challenge" not in con)
check("no poa-tools, poa-join-core, or a join() call", "poa-tools" not in full + con and "poa-join-core" not in full + con and "join()" not in full + con)
def blurred(text):
    t = text.lower().replace("not a wallet download, wallet activation, or wallet restore", "")
    return "wallet download" in t or "wallet activation" in t or "wallet restore" in t
blobs = {"prompt": full + con, "steps": S.steps_md(), "faq": str(F.PAGES), "llms": AG.llms_txt(), "mcp": [t for t in AG.TOOLS if t[0] == "get_onboarding_steps"][0][2]}
for name, text in blobs.items():
    check(f"{name}: key backup is not called wallet download, activation, or restore", not blurred(text))
check("key backup is named as not a wallet action in the prompt, steps, faq and llms",
      OP.KEY_NOT_WALLET in full and OP.KEY_NOT_WALLET in con
      and "not a wallet download, wallet activation, or wallet restore" in S.steps_md().lower()
      and "not a wallet download, wallet activation, or wallet restore" in str(F.PAGES).lower()
      and "not a wallet download, wallet activation, or wallet restore" in AG.llms_txt().lower())
check("no em or en dash in the rule", not any(c in R + OP.KEY_NOT_WALLET for c in "\u2013\u2014"))
print(f"\n{len(fails)} FAILED" if fails else "\nall ok")
sys.exit(1 if fails else 0)
