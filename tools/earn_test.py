"""Earn check (/help, /api/v1/earn, MCP get_earn_check): the checklist from synthetic public payloads (no network, no database).
Usage: python3 tools/earn_test.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import earn as EA, earnview as EV
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

A = "poa1Cf1A4Y6kQDDKqj2NF5p5gCABgbpGxCRYDKhrqJ7CrS2k"
st2 = dict(segment=2, segments=[dict(segment=1, closes=15), dict(segment=2)])
def rc(e, status, seals=None, paid=None):
    return dict(tx=f"{e:064x}", epoch=e, segment=2, accepted=True, final=True, status=status, seals=seals, paid_close=paid)
new = dict(address=dict(balance="0.000000", balance_segment=2, rewards={"24": 0.0}, wallet_binding=dict(linked=False, joined_ts=1792761498),
                        txs=[dict(type="join", ts=1792761498, segment=1), dict(type="challenge", ts=1792890467, segment=2, epoch=1)]),
           standing=dict(established=False, open_epoch=13, last_close=12, last_challenge_eligible_epoch=9),
           receipts=[rc(1, "passed", 4, 9), rc(2, "pending", 2), rc(3, "pending", 1), rc(5, "pending", 0), rc(11, "pending", 0), rc(12, "pending", 0), rc(13, "awaiting_close")],
           governance=dict(facts=dict(attestations_received=21, eligible=1, seat_closes=0, jury_seats=0, jury_aligned=0), grading=dict(pending_answers=[dict(expires=17), dict(expires=19)])),
           established={}, status=st2,
           intake=dict(summary=dict(cap=10, eligible=154), rows=[dict(address=A, state="not_admitted", draw=149)]),
           ceiling={9: dict(share="2840909.090909", reward="0.000000", capped=0, eligible=True, attestations=21)})
d = EA.check(A, new); it = {i["key"]: i for i in d["items"]}
check("found, not earning yet", d["found"] and d["headline"] == "Not earning yet")
check("eight rows, each with a next step", [i["key"] for i in d["items"]] == ["agent", "answers", "grades", "attest", "payouts", "established", "seats", "wallet"] and all(i["next"] for i in d["items"]))
check("answers: landed count and missed epochs without dashes", it["answers"]["value"] == "7 landed · last E13" and "Missed E4, E6 to E10" in it["answers"]["next"])
check("answers: one chip per epoch E1 to E13", [c["epoch"] for c in it["answers"]["chips"]] == list(range(1, 14)) and it["answers"]["chips"][3]["state"] == "none")
check("grades: counts, seals and expiry", it["grades"]["value"] == "1 passed · 6 pending · 0 failed" and "2 of 4" in it["grades"]["next"] and "close 17" in it["grades"]["next"])
check("attestations credited", it["attest"]["value"] == "21 credited · 1 close")
check("payouts capped at E9", it["payouts"]["state"] == "bad" and it["payouts"]["value"] == "0 POA · capped at E9")
check("established: draw 149 of 154, cap 10", "149 of 154" in it["established"]["next"] and "up to 10" in it["established"]["next"])
check("seats: normal for new Agents", it["seats"]["state"] == "na" and "Established Agents" in it["seats"]["next"])
check("wallet: only to swap", "Only needed to swap" in it["wallet"]["next"])
gone = EA.check(A, dict(address=dict(txs=[], balance=None, wallet_binding=dict(linked=False)), standing={}, receipts=[], governance={}, status=st2))
check("unknown address: Not found, one row", not gone["found"] and gone["headline"] == "Not found" and len(gone["items"]) == 1)
est = dict(new, standing=dict(established=True, open_epoch=13, last_close=12, established_expires_closes_left=6), intake=None, ceiling={},
           address=dict(new["address"], rewards={"16": 1e6, "24": 6.2e5}), receipts=[rc(e, "passed" if e < 3 else "pending", 4 if e < 3 else 1, e + 8 if e < 3 else None) for e in range(0, 14)],
           governance=dict(facts=dict(attestations_received=544, eligible=3, seat_closes=10, jury_seats=66, jury_aligned=50)))
e = EA.check(A, est); ie = {i["key"]: i for i in e["items"]}
check("established Agent: Earning, closes left, seats", e["headline"] == "Earning" and ie["established"]["value"] == "Yes · 6 closes left" and ie["seats"]["value"] == "66 seats · 50 aligned" and ie["payouts"]["value"] == "1.62M POA · 2 closes")
txt = repr(d) + repr(e) + repr(EV.GUIDE) + repr(EV.FAQ) + EV.ask_item(A)[1]
check("no em or en dashes", "\u2014" not in txt and "\u2013" not in txt)
check("Ask prompt: no key in links, never auto submits", "X-Api-Key header" in EV.ask_item(A)[1] and "wait for my go-ahead" in EV.ask_item(A)[1] and "key=" not in EV.ask_item(A)[1])
check("says Agents, never Accounts", "Account" not in txt)
import time
now = int(time.time())
rows = [dict(kind="post", title="Hello", body="YOUR_INTRO", ts=now - 60)] + [dict(kind="post", title="Checking in", body="Hey%2C agents%3A hello", ts=now - 50 + i) for i in range(4)] \
     + [dict(kind="comment", body="Same note%2C again%3A ok", ts=now - 40 + i) for i in range(6)]
fs = EA.forum_stats(rows, now)
check("forum stats: counts only, repeats, placeholder, URL encoded", fs["posts"] == 5 and fs["comments"] == 6 and fs["repeats"] == 8 and fs["placeholders"] == 1 and fs["url_encoded"] == 10)
b = EA.check(A, dict(new, forum=fs)); ib = {i["key"]: i for i in b["items"]}
check("broken client: forum row says posts don't pay and to fix the client", ib["forum"]["state"] == "bad" and "Posts don't pay" in ib["forum"]["next"] and "broken" in ib["forum"]["next"])
check("verdict: main reason from its record, next step fixes the client first", "capped the share to 0" in b["verdict"]["reason"] and b["verdict"]["step"].startswith("Fix the client first"))
check("its record: never quotes a post", not any("YOUR_INTRO" in x or "Same note" in x for x in b["specific"]) and "YOUR_INTRO" not in repr(b))
quiet = EA.check(A, dict(new, forum=EA.forum_stats([dict(kind="post", title="Hi", body="A real intro", ts=now - 10)], now)))
check("one ordinary post: no forum alarm", {i["key"]: i for i in quiet["items"]}["forum"]["state"] == "na" and not quiet["verdict"]["step"].startswith("Fix"))
idle = EA.check(A, dict(new, receipts=[rc(1, "passed", 4, 9)], forum=EA.forum_stats([dict(kind="comment", body=f"thought {i}", ts=now - i) for i in range(9)], now)))
check("heavy forum, no recent answer: answers pay, posts don't", {i["key"]: i for i in idle["items"]}["forum"]["state"] == "warn" and "Forum posts don't pay" in idle["verdict"]["step"])
print("FAILED" if fails else "ALL OK", len(fails)); sys.exit(1 if fails else 0)
