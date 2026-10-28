"""Earn check (/help, /api/v1/earn, MCP get_earn_check): the checklist from synthetic public payloads (no network, an empty temporary database).
Usage: python3 tools/earn_test.py"""
import os, sys, tempfile
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "e.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")   # an empty DB, no upstream
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, earn as EA, earnview as EV
db.init()
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
txt = repr(d) + repr(e) + repr(EA.WAYS) + repr(EA.GRADING_RULES) + EA.DISCLAIMER + repr(EV.FAQ) + EV.ask_item(A)[1]
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
check("verdict: main reason from its record, next step fixes the client first", "E9 close record shows that share capped to 0" in b["verdict"]["reason"] and b["verdict"]["step"].startswith("Fix the client first"))
check("its record: never quotes a post", not any("YOUR_INTRO" in x or "Same note" in x for x in b["specific"]) and "YOUR_INTRO" not in repr(b))
quiet = EA.check(A, dict(new, forum=EA.forum_stats([dict(kind="post", title="Hi", body="A real intro", ts=now - 10)], now)))
check("one ordinary post: no forum alarm", {i["key"]: i for i in quiet["items"]}["forum"]["state"] == "na" and not quiet["verdict"]["step"].startswith("Fix"))
idle = EA.check(A, dict(new, receipts=[rc(1, "passed", 4, 9)], forum=EA.forum_stats([dict(kind="comment", body=f"thought {i}", ts=now - i) for i in range(9)], now)))
check("heavy forum, no recent answer: answers pay, posts don't", {i["key"]: i for i in idle["items"]}["forum"]["state"] == "warn" and "Forum posts don't pay" in idle["verdict"]["step"])

# ---- wording: record based, never a documented rule ----
check("payouts: record based wording, no 'by the network'", it["payouts"]["next"] == "Caps come from the close record. Keep answering every epoch." and "by the network" not in repr(d)
      and any("The E9 close record shows this share capped to 0." in x for x in d["specific"]))
# ---- disclaimer: page line, API field, MCP result ----
check("disclaimer: one plain sentence pair, no dashes", d["disclaimer"].startswith("Unofficial guidance.") and "not the official rules" in d["disclaimer"] and "go.md and skill.md" in d["disclaimer"]
      and gone["disclaimer"] == d["disclaimer"])
api = EA.api(A, lambda p, q: {"/api/address/" + A: new["address"], f"/api/address/{A}/standing": new["standing"]}.get(p))
check("API result carries disclaimer, history, grading and ways", api["disclaimer"] == EA.DISCLAIMER and "history" in api and "ways" in api and "grading" in api)
# ---- per close history from a synthetic close record ----
T1, T2, T3 = "a1" * 32, "b2" * 32, "c3" * 32
mine = [dict(tx=T1, epoch=4, segment=2, status="passed"), dict(tx=T2, epoch=5, segment=2, status="pending"), dict(tx=T3, epoch=3, segment=2, status="vanished", vanished=True, last_pending_close=5)]
R6 = dict(epoch=6, ts=1793000000, challenges={A: "2840909.090909"}, rewards={A: "0.000000"}, weights={A: 0.2177}, propagation={},
          note="v2.2: verification 70% (challenge-gated, reciprocity+kinship-weighted, newcomer-dampened, capped)",
          basis=dict(challenge_eligible=[A], attestations={A: 21}, pending={T2: dict(kind="short", since=5, grades=[1, 2], panel=[])},
                     settled=[dict(answer=T1, **{"from": A}, passed=True, jury=[]), dict(answer="dd" * 32, **{"from": "poa1X"}, passed=False, jury=[dict(grader=A, aligned=True), dict(grader="poa1Y", aligned=False)])],
                     ceiling=dict(capped={A: 0}, repooled={}, triggered=[[A]]), final_payout=dict(capped={A: "7901742.398001"}, repooled={}),
                     graders_served={A: 2}, established_after=[], established_removed=[], slashed=[], ejected=[], marks={}, spotcheck=[T1],
                     referral2=dict(paid={A: "1000.000000"}, work={})))
r6 = EA.close_row(6, R6, A, mine, False); txt6 = [x["text"] for x in r6["lines"]]; f6 = {x["field"] for x in r6["lines"]}
check("history: share and paid from challenges and rewards", r6["share"] == "2840909.090909" and r6["paid"] == "0.000000" and r6["close"] == 6 and not r6["answered"])
check("history: missed epoch, capped to 0, final payout cap, weight", "No answer in E6. No answer, no rewards that epoch." in txt6 and "The E6 close record shows this share capped to 0" in txt6
      and "Final payout capped" in txt6 and "Verification weight 0.22 (reciprocity and kinship)" in txt6)
check("history: pending, passed, dropped answers", "E5 answer waiting for a jury" in txt6 and sum(1 for x in r6["lines"] if x["kind"] == "wait") == 1 and "E4 answer passed" in txt6 and "E3 answer left the pending list with no grade" in txt6)
check("history: eligible not drawn, credits, referral, spot check", "Eligible for Established, not drawn at intake" in txt6 and "21 attestations credited" in txt6
      and "Served 2 grading seats" in txt6 and "1 of 1 grades aligned with the verdict" in txt6 and "Referral income" in txt6 and "E4 answer spot checked" in txt6)
check("history: every line names a record field and its raw value", all(x["field"] and "raw" in x for x in r6["lines"]) and "basis.ceiling.capped" in f6 and "basis.final_payout.capped" in f6)
check("history: never invents newcomer dampening (no per Agent field)", not any("ewcomer" in x for x in txt6))
check("history: cuts counted, seats and jury per close", r6["cuts"] >= 4 and r6["seats"] == 2 and r6["jury"] == 1 and r6["aligned"] == 1 and r6["_est"] is False)
R7 = dict(R6, epoch=7, basis=dict(R6["basis"], established_after=[A], ceiling={}, final_payout={}, spotcheck=[]), weights={})
r7 = EA.close_row(7, R7, A, mine + [dict(tx="ee" * 32, epoch=7, segment=2, status="awaiting_close")], False)
check("history: admitted at a close, answered", "Admitted to Established" in [x["text"] for x in r7["lines"]] and r7["answered"] and r7["_est"] is True)
recs = {6: R6, 7: R7}
def get(p, q):
    if p.startswith("/api/epoch/"): return recs.get(int(p.split("/")[3]))
    return {"/api/address/" + A: dict(new["address"], txs=[dict(type="join", ts=1, segment=2, epoch=6)]), f"/api/address/{A}/standing": dict(new["standing"], last_close=7),
            "/api/receipts": mine, f"/api/address/{A}/established": {}, "/api/status": st2}.get(p)
g = EA.gather(A, get)
check("gather: one history row per stored close from the first tx to the last close", [h["close"] for h in g["history"]] == [6, 7] and "_est" not in g["history"][0])
hc = EA.check(A, g)
check("check: history and grading in the result", [h["close"] for h in hc["history"]] == [6, 7] and hc["grading"]["seats"] and hc["grading"]["missed"] is None and "not kept" in hc["grading"]["missed_note"])
# ---- grading section ----
gn = d["grading"]; ge = e["grading"]
check("grading: not Established says why and what it takes", gn["state"] == "warn" and "Not Established" in gn["why"] and "E9" in gn["why"] and len(gn["rules"]) >= 8)
check("grading: Established with seats", ge["state"] == "ok" and ge["aligned"] == 50 and ge["jury_seats"] == 66)
rl = {r["label"]: r for r in gn["rules"]}
check("grading rules: draw, buffer, expiry, conduct, penalties, sources labelled", {"Who gets seats", "Closes buffer", "Seat expiry", "Conduct", "Penalties"} <= set(rl)
      and "48 epochs" in rl["Penalties"]["text"] and rl["Closes buffer"]["source"] == "observed" and rl["Penalties"]["source"] == "go.md, skill.md")
# ---- ways to earn ----
wk = [w["key"] for w in EA.WAYS]
check("ways: answers, attestations, grading, Established, invites, and what does not pay", wk == ["answers", "attest", "grading", "established", "invites", "none"]
      and all(w["pays"] and w["qualifies"] and w["next"] for w in EA.WAYS) and "Forum posts" in EA.WAYS[-1]["pays"] and "votes" in EA.WAYS[-1]["pays"])
check("ways: observed things labelled observed", "Observed:" in EA.WAYS[1]["qualifies"] and "Observed:" in EA.WAYS[4]["pays"])
check("ways: no invite link or code", not any("invite link" in w["next"].lower() or "code" in (w["pays"] + w["next"]).lower() for w in EA.WAYS))
# ---- page ----
html = EV.page({"address": [A], "sort": ["paid"], "dir": ["asc"]}, lambda t, b, act: b, lambda a: hc)
check("page: disclaimer line under the input, go.md and skill.md linked", 'class="ecdis small"' in html and html.index("ecdis") < html.index("ech0")
      and 'href="https://minepoa.com/go.md"' in html and 'href="https://minepoa.com/skill.md"' in html)
check("page: history under the verdict, sortable headers, mobile columns", html.index('id="history"') > html.index("ecv0") and "sort=paid" in html and 'class="ehist pri"' in html and "#history" in html)
check("page: each reduction has its raw field in a tooltip", "basis.ceiling.capped: 0" in html and 'class="qtip hv"' in html)
check("page: Grading and Ways to earn cards", 'id="grading"' in html and ">Ways to earn<" in html and "Help my agent earn" in html)
check("page: no em or en dashes, Agents not Accounts", "\u2014" not in html and "\u2013" not in html and "Account" not in html)
check("method link is /about#earn-check", EA.METHOD == "/about#earn-check" and "/about#earn-check" in html)
print("FAILED" if fails else "ALL OK", len(fails)); sys.exit(1 if fails else 0)
