"""Onboarding blueprint safety cues (Oct 23): leak watch and critical-notice stop on the write Ask prompts only, fail
closed when /me doesn't answer, pending_receipt is held not paid, the 524 rule, no Emblem chat agent for money, no fee row
outside POASwap. The swap page, its FAQ and its prompt moved to POASwap. Join prompt untouched. Usage: python3 tools/blueprint_copy_test.py"""
import os, re, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_DB", os.path.join(tempfile.mkdtemp(), "b.db"))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
def nodash(t): return not re.search("[\u2013\u2014]", t)

from poascan import db, prompts as PR, agentapi as AG, start as S
db.init()
a = "poa1" + "x" * 40
writes = [PR.answer_epoch(), PR.answer_epoch(3), PR.GRADE, PR.addr_send(a)]
check("WATCH: /me before the first write, address and next_nonce, fail closed, stop on a moved nonce, critical notice stop",
      all(s in PR.WATCH for s in ("Before your first write this visit", "https://minepoa.com/api/hosted/me:", "next_nonce", "No answer: don't write.",
                                  "stop all writes and tell me", "https://minepoa.com/api/notices", "critical notice")))
check("WATCH on every write prompt, before the key rules", all(PR.WATCH + PR.SAFE in p for _, p in writes))
reads = [PR.TXS, PR.NETWORK, PR.GROWTH, PR.BURN, PR.SPENDABLE, PR.FIND, PR.API, PR.MCP, PR.explain_epoch(1), PR.explain_tx("0" * 64)]
check("no WATCH on read-only prompts", not any(PR.WATCH in p for _, p in reads))
check("UPGRADE: critical notice means stop", "If one is critical, stop and tell me." in PR.UPGRADE[1])
check("BACKOFF: /me no answer means no write", "If /me doesn't answer either, don't write; try later." in PR.BACKOFF[1])
allp = [p for _, p in writes + reads + [PR.UPGRADE, PR.BACKOFF, PR.GRADE_BETTER, PR.CLIMB, PR.LABLEAK]]
check("every prompt: no dashes, under 4000 characters", all(nodash(p) and len(p) < 4000 for p in allp))
check("swap page prompts and FAQ are gone (swaps live on POASwap)", not hasattr(PR, "swap_status") and not os.path.exists(os.path.join(ROOT, "poascan", "swap", "faq.py"))
      and not os.path.exists(os.path.join(ROOT, "poascan", "offer.py")))
ll = AG.llms_txt(); safety = ll.split("## Safety", 1)[1].split("## Source", 1)[0]
check("llms.txt Safety: leak watch, critical notice, Emblem chat agent, 524", all(s in safety for s in (
      "next_nonce", "No answer: don't write.", "severity critical", "Emblem's chat agent or agent mode", "524")) and nodash(safety))
check("llms.txt Updated 2026-11-15", "Updated 2026-11-16." in ll)
tool = [d for n, _, d, _, _ in AG.TOOLS if n == "get_swap_status"][0]
check("MCP get_swap_status: pending_receipt is held, not paid", "pending_receipt is held, not paid" in tool)
_sp = [v for k, v in AG.openapi()["paths"].items() if k.endswith("/swaps/status")]
check("OpenAPI swaps status: pending_receipt is held, not paid", len(_sp) == 1 and "pending_receipt is held, not paid" in str(_sp[0]))
check("SAFE (1.26.348): Authorization: Bearer header only, never a key or token in a URL, 401 or 403 means tell me it needs a fix, never shown in the chat",
      "Send SAVED_KEY only in an Authorization: Bearer header on every minepoa.com call above." in PR.SAFE and "401 or 403" in PR.SAFE and "show it in this chat" in PR.SAFE
      and "key=" not in PR.SAFE and "token=" not in PR.SAFE and "key=" not in PR.WATCH)
check("llms.txt Safety: key shapes, a header and never a URL (1.26.199)", "PoA keys (pk_ or GUID)" in safety and "Send a credential in a header" in safety
      and "Authorization: Bearer" in safety and "never send one to POAScan" in safety and "key= is legacy" not in safety and "pk_/psk_" not in ll)
check("MCP safety text names GUID keys and tokens", "PoA keys (pk_ or GUID), tokens" in AG.SAFETY)
check("join prompt v2.9.9, 59174b29", S.template_sha256() == "59174b29fe34e7a824a12059c7231414445238dd51736157ec775a99fba639f5")
check("no 'independent' wording added on these surfaces", "independent" not in (" ".join(allp) + safety).lower())
print("\n%d failure(s)" % len(fails) if fails else "\nall ok"); sys.exit(1 if fails else 0)
