#!/usr/bin/env python3
"""1.26.216: Balance vs Total rewards, Spendable and Locked never silently disagree (LabLeak post 1960, comment 7600:
balance 905,962.893314 from the agent list, which already held the E16 payout of 393,966.242113, while the reward figures
stood at the E15 close at 511,996.651201)."""
import json, os, sys, tempfile, time
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, analytics as A, segments as SG, rewardbasis as RB, views as V, server as S, agentapi as AG, ui as UI
db.init()
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NOW = int(time.time()); P = 21600; seg = SG.CURRENT
a = "poa15VA8Smq8kAt8jzx9N9B4cp11zj4QZ2cQv2oMtYmey8em"; b = "poa192Zv1dHoQ5UcRqpmRsGWpmNkV84g8R8N814G4jxoHQfo"
t15 = NOW - P - 1800   # E15 closed 6.5 h ago: E16 is 30 min past due
closes = [dict(epoch=k, ts=t15 - (15 - k) * P, rewards={}, basis={}) for k in range(16)]
closes[6]["rewards"] = {a: "511996.651201", b: "511996.651201"}
db.put_blob(SG.blob_kind(seg), closes)
db.put_blob("params", {"auto_epoch_seconds": P})
db.put_blob("status", {"epochs_closed": 16, "supply": "1", "txs": 1})
db.write("INSERT INTO accounts(addr, balance, balance_s, last_seen, first_seen) VALUES(?,?,?,?,?)", (a, 905962.893314, "905962.893314", NOW - 60, NOW - 9 * P))
A._cache.clear()

bs = RB.basis(905962.893314, 511996.651201, NOW - 60)
check("906K vs 512K with the E16 close past due: behind, as of E15, ahead by 393,966.242113",
      bs["behind"] and bs["as_of"]["epoch"] == 15 and abs(bs["balance_ahead_by"] - 393966.242113) < 1e-6 and "E16" in bs["reason"])
check("agreeing figures are never tagged", not RB.basis(511996.651201, 511996.651201, NOW - 60)["behind"])
check("before the next close is due nothing is tagged", not RB.basis(905962.893314, 511996.651201, t15 + 600)["behind"])

html = V.address(a); html = html if isinstance(html, str) else str(html)
head = html[:html.find('class="tabs')] if 'class="tabs' in html else html
check("page: Total rewards, Spendable and Locked carry a Stale tag naming the E15 close", head.count("As of the E15 close") >= 3 and "Stale" in head)
check("page: the split is not re-estimated (Spendable + Locked still sum to 512K)", "906K" in head or "905" in head)
r = S.api("/api/address/" + a, {})[0]
check("API: rewards_total 511,996.651201, as of E15, rewards_behind with reason and balance_ahead_by",
      abs(r["rewards_total"] - 511996.651201) < 1e-6 and r["rewards_as_of"]["epoch"] == 15 and r["rewards_behind"] is True and r["rewards_behind_reason"] and abs(r["balance_ahead_by"] - 393966.242113) < 1e-6)
check("API: spendable_est + locked_est = rewards_total (no invented split)", abs(r["spendable_est"] + r["locked_est"] - r["rewards_total"]) < 1e-3)
m = AG.t_address({"address": a, "tx_limit": 0})
check("MCP get_address carries rewards_as_of and rewards_behind", m["rewards_behind"] is True and m["rewards_as_of"]["epoch"] == 15)
pill = UI.status_pill(dict(state="live", label="Live", why="Live", fetched_at=NOW))
check("status note says why, and Live turns Partial", pill["state"] == "partial" and any("as of the E15 close" in x for x in pill["reasons"]))

db.put_blob("status", {"epochs_closed": 17, "supply": "1", "txs": 1}); A._cache.clear()
lg = RB.lag(t15 + 600)
check("upstream lists a close POAScan has not read: behind even before the due time", lg and lg["kind"] == "missing" and lg["missing"] == 1)

closes.append(dict(epoch=16, ts=NOW - 1500, rewards={a: "393966.242113"}, basis={})); db.put_blob(SG.blob_kind(seg), closes); A._cache.clear()
r = S.api("/api/address/" + a, {})[0]
check("once E16 is read: figures agree, no tag, as of E16", r["rewards_behind"] is False and r["rewards_as_of"]["epoch"] == 16 and abs(r["rewards_total"] - 905962.893314) < 1e-6)
html = V.address(a); html = html if isinstance(html, str) else str(html)
check("page: no Stale reward tag once current", "As of the E1" not in html)
check("no em or en dash in the new copy", not any(c in (RB.tag_text(bs) or "") + RB.__doc__ for c in "\u2014\u2013"))
ab = V.about(); ab = ab if isinstance(ab, str) else str(ab)
check("/about has the method", 'id="reward-basis"' in ab)
print("ALL OK" if not fails else f"FAIL: {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
