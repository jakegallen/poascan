"""Onboarding blueprint safety cues (Oct 23): leak watch and critical-notice stop on the write Ask prompts only, fail
closed when /me doesn't answer, pending_receipt is held not paid, the 524 rule, no Emblem chat agent for money, no fee row
outside POASwap's Swap Fee card. Join prompt untouched. Usage: python3 tools/blueprint_copy_test.py"""
import os, re, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_DB", os.path.join(tempfile.mkdtemp(), "b.db"))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
def nodash(t): return not re.search("[\u2013\u2014]", t)

from poascan import db, prompts as PR, offer as OF, agentapi as AG, start as S
from poascan.swap import faq as F
db.init()
a = "poa1" + "x" * 40
writes = [PR.answer_epoch(), PR.answer_epoch(3), PR.GRADE, PR.addr_send(a)]
check("WATCH: /me before the first write, address and next_nonce, fail closed, stop on a moved nonce, critical notice stop",
      all(s in PR.WATCH for s in ("Before your first write this visit", "/api/hosted/me?key=SAVED_KEY", "next_nonce", "No answer: don't write.",
                                  "stop all writes and tell me", "https://minepoa.com/api/notices", "critical notice")))
check("WATCH on every write prompt, before the key rules", all(PR.WATCH + PR.SAFE in p for _, p in writes))
reads = [PR.TXS, PR.NETWORK, PR.GROWTH, PR.BURN, PR.SPENDABLE, PR.FIND, PR.API, PR.MCP, PR.explain_epoch(1), PR.explain_tx("0" * 64), PR.swap_status("0" * 64)]
check("no WATCH on read-only prompts", not any(PR.WATCH in p for _, p in reads))
check("UPGRADE: critical notice means stop", "If one is critical, stop and tell me." in PR.UPGRADE[1])
check("BACKOFF: /me no answer means no write", "If /me doesn't answer either, don't write; try later." in PR.BACKOFF[1])
_, sp = PR.swap_status("0" * 64)
check("swap status prompt: pending_receipt is held, not paid; lag is not failure; still no fee, key or referral",
      "pending_receipt means held, not paid" in sp and "lag is not failure" in sp and "fee" not in sp.lower() and "SAVED_KEY" not in sp and "referral" not in sp.lower())
allp = [p for _, p in writes + reads + [PR.UPGRADE, PR.BACKOFF, PR.GRADE_BETTER, PR.CLIMB, PR.LABLEAK]]
check("every prompt: no dashes, under 4000 characters", all(nodash(p) and len(p) < 4000 for p in allp))
qa = dict((q, x) for q, x in F.PAGE["qa"] if isinstance(x, str))
how, safe, tout = qa["How does a buy work?"], qa["How do I stay safe?"], qa["What if a take times out?"]
check("FAQ buy: held, not paid; nonce rent named", "(held, not paid: it waits for the seller)" in how and "0.00106 SOL" in how and "durable nonce account" in how)
check("FAQ safety: no Emblem chat agent or agent mode for money, low vault balance, payment rule kept",
      "Never move money through Emblem's chat agent or agent mode." in safe and "Keep the vault balance low" in safe and "Never send payment outside the network." in safe)
check("FAQ timeout: wait, read, one more take only when nothing is held, then stop",
      "wait about 2 minutes" in tout and "Held: wait for receipt_ready" in tout and "Nothing held: take once more. Still nothing: stop." in tout and "524" in tout)
hw = F.how_html()
check("How swaps work: no fee row (the fee lives only on POASwap's Swap Fee card)", "<dt>Fee</dt>" not in hw and "1%" not in hw)
check("FAQ and How swaps work: no dashes, no 1%", nodash(how + safe + tout + hw) and "1%" not in how + safe + tout)
ns = " ".join(OF.next_steps("open", {}))
check("/swap open steps: held not paid, 524 rule, never loop, stop states, lag, payment rule, no fee",
      "pending_receipt is held, not paid" in ns and "524" in ns and "never loop" in ns and "Stop at Filled, Expired or Failed." in ns
      and "lag is not failure" in ns and "Never send payment outside the network." in ns and not re.search(r"\bfee\b", ns, re.I) and nodash(ns))
ll = AG.llms_txt(); safety = ll.split("## Safety", 1)[1].split("## Source", 1)[0]
check("llms.txt Safety: leak watch, critical notice, Emblem chat agent, 524", all(s in safety for s in (
      "next_nonce", "No answer: don't write.", "severity critical", "Emblem's chat agent or agent mode", "524")) and nodash(safety))
check("llms.txt Updated 2026-10-28", "Updated 2026-10-28." in ll)
tool = [d for n, _, d, _, _ in AG.TOOLS if n == "get_swap_status"][0]
check("MCP get_swap_status: pending_receipt is held, not paid", "pending_receipt is held, not paid" in tool)
_sp = [v for k, v in AG.openapi()["paths"].items() if k.endswith("/swaps/status")]
check("OpenAPI swaps status: pending_receipt is held, not paid", len(_sp) == 1 and "pending_receipt is held, not paid" in str(_sp[0]))
check("SAFE: X-Api-Key header preferred on /me, key= only as fallback, token= per go.md", "X-Api-Key header (/api/hosted/me does), send SAVED_KEY there instead of in the link; use key= only if that fails." in PR.SAFE
      and "go.md now calls key= legacy" in PR.SAFE and "token=" in PR.SAFE)
check("llms.txt Safety: key shapes, a header and never a URL (1.26.199)", "PoA keys (pk_ or GUID)" in safety and "Send a credential in a header" in safety
      and "X-Api-Key" in safety and "never send one to POAScan" in safety and "key= is legacy" not in safety and "pk_/psk_" not in ll)
check("MCP safety text names GUID keys and tokens", "PoA keys (pk_ or GUID), tokens" in AG.SAFETY)
check("join prompt v2.9.1, 410e5ee6", S.template_sha256() == "410e5ee62626a008f66bc4b0fae9f783d06453c25b9777aff8312a651dd63be8")
check("no 'independent' wording added on these surfaces", "independent" not in (" ".join(allp) + how + safe + tout + hw + safety + ns).lower())
print("\n%d failure(s)" % len(fails) if fails else "\nall ok"); sys.exit(1 if fails else 0)
