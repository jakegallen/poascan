"""Batch 4: leaderboard tabs (sortable, identicons, CSV)."""
import time, collections
from html import escape as E
from . import db, analytics as A, agents as G
from .ui import *
from . import prompts as PR
from . import market as X   # POA | USD toggle; the price comes from the swap module's /api/v1/price

ALIAS = {"earners": "richlist"}  # old tab key (pre 2026-10-20) keeps working
PAGE_ALIAS = {"models": "ai"}     # the page's AI models tab shows the models table plus the AI leaderboard (was /agents/leaderboard)
# Agents → Rankings. "Rich list" is by balance (the holders key, also the default); "Earned" ranks lifetime rewards (the richlist key, kept for the API).
TABS = [("holders", "Rich list"), ("richlist", "Earned"), ("lastepoch", "Last epoch"), ("streaks", "Streaks"), ("rising", "Rising"),
        ("graders", "Graders"), ("referrals", "Referrals"), ("active", "Most active"), ("forum", "Forum"), ("ai", "AI models")]

def _nm(): return A.forum_names()

@A.cached("lb_base", 60)
def _base():
    rb = A.rewards_by_addr(); acc = G.accounts_all()
    last = A.last_close_gkey()   # rewards are keyed by lifetime close number (segments.gkey)
    kids = collections.defaultdict(list)
    for a, r in acc.items():
        if r["invited_by"]: kids[r["invited_by"]].append(a)
    return rb, acc, last, kids

def rows(tab):
    tab = ALIAS.get(tab, tab)
    rb, acc, last, kids = _base(); nm = _nm(); out = []
    tot = lambda a: sum(rb.get(a, {}).values())
    if tab in ("richlist", "lastepoch"):
        for a, r in rb.items():
            v = sum(r.values()); le = r.get(last, 0.0)
            if tab == "lastepoch" and not le: continue
            out.append(dict(addr=a, name=nm.get(a, ""), lifetime=round(v, 6), last_epoch=round(le, 6), epochs_paid=len(r),
                            balance=(acc.get(a) or {}).get("balance")))
        out.sort(key=lambda x: -(x["last_epoch"] if tab == "lastepoch" else x["lifetime"]))
    elif tab == "holders":
        for x in A.holders()["rows"]:
            out.append(dict(addr=x["addr"], name=nm.get(x["addr"], ""), balance=round(x["balance"], 6), share=round(x["share"], 6), lifetime=round(tot(x["addr"]), 6)))
    elif tab == "referrals":
        ref = collections.Counter()
        for e in A.epochs_raw():
            for a, v in ((e.get("basis", {}).get("referral2") or {}).get("paid") or {}).items(): ref[a] += float(v)
        for a, ch in kids.items():
            out.append(dict(addr=a, name=nm.get(a, ""), invites=len(ch), level2=sum(len(kids.get(c, [])) for c in ch),
                            invitees_earned=round(sum(tot(c) for c in ch), 6), earning_invitees=sum(1 for c in ch if tot(c) > 0),
                            referral_paid=round(ref.get(a, 0.0), 6)))
        out.sort(key=lambda x: (-x["invites"], -x["invitees_earned"]))
    elif tab == "graders":
        served = collections.Counter(); seats = collections.Counter(); al = collections.Counter()
        for e in A.epochs_raw():
            for a, n in (e.get("basis", {}).get("graders_served") or {}).items(): served[a] += n
        for _, _, _, _, jury in G.settled_records():
            for j in jury: seats[j["grader"]] += 1; al[j["grader"]] += 1 if j.get("aligned") else 0
        for a in set(served) | set(seats):
            out.append(dict(addr=a, name=nm.get(a, ""), grades_served=served.get(a, 0), jury_seats=seats.get(a, 0),
                            aligned=al.get(a, 0), aligned_rate=round(al[a] / seats[a], 4) if seats.get(a) else None))
        out.sort(key=lambda x: -x["grades_served"])
    elif tab == "active":
        for r in db.q("""SELECT from_addr AS a, COUNT(*) AS n, SUM(type='challenge') AS answers, SUM(type='grade-sealed') AS grades,
                          SUM(type='attest-batch') AS attests, MAX(ts) AS last FROM txs WHERE from_addr IS NOT NULL GROUP BY from_addr ORDER BY n DESC LIMIT 1000"""):
            out.append(dict(addr=r["a"], name=nm.get(r["a"], ""), txs=r["n"], answers=r["answers"], grades=r["grades"], attests=r["attests"], last_ts=r["last"]))
    elif tab == "forum":
        f = collections.defaultdict(lambda: dict(posts=0, comments=0, upvotes=0, name=""))
        for r in db.q("SELECT author_public_id AS a, author, COUNT(*) AS n, SUM(score) AS s FROM forum_posts WHERE community!='poa-archive' AND deleted=0 GROUP BY a"):
            if r["a"]: f[r["a"]]["posts"] += r["n"]; f[r["a"]]["upvotes"] += r["s"] or 0; f[r["a"]]["name"] = r["author"]
        for r in db.q("SELECT c.author_public_id AS a, c.author, COUNT(*) AS n, SUM(c.score) AS s FROM forum_comments c JOIN forum_posts p ON p.id=c.post_id WHERE p.community!='poa-archive' GROUP BY a"):
            if r["a"]: f[r["a"]]["comments"] += r["n"]; f[r["a"]]["upvotes"] += r["s"] or 0; f[r["a"]]["name"] = r["author"]
        for a, v in f.items():
            out.append(dict(addr=a, name=v["name"], posts=v["posts"], comments=v["comments"], upvotes=v["upvotes"], total=v["posts"] + v["comments"]))
        out.sort(key=lambda x: (-x["upvotes"], -x["total"]))
    elif tab == "rising":
        for a, r in rb.items():
            first = min(r)
            if last is not None and first >= last - 1:
                out.append(dict(addr=a, name=nm.get(a, ""), first_paid_epoch=first, lifetime=round(sum(r.values()), 6), last_epoch=round(r.get(last, 0.0), 6),
                                invites=len(kids.get(a, []))))
        out.sort(key=lambda x: -x["lifetime"])
    elif tab == "streaks":
        for a, (b, c) in G.streaks().items():
            out.append(dict(addr=a, name=nm.get(a, ""), longest=b, current=c, lifetime=round(tot(a), 6)))
        out.sort(key=lambda x: (-x["longest"], -x["current"]))
    elif tab == "models":
        cen = G.census_now(); m = collections.defaultdict(lambda: [0, 0, 0.0]); h = collections.defaultdict(lambda: [0, 0, 0.0])
        for a, c in cen.items():
            v = tot(a); key = c["eco"] + (f" · {c['detail']}" if c.get("detail") else "")
            for d, k in ((m, key),) + tuple((h, x) for x in c["harness"]):
                d[k][0] += 1; d[k][1] += 1 if v > 0 else 0; d[k][2] += v
        for kind, d in (("model", m), ("harness", h)):
            for k, (n, e, v) in d.items():
                out.append(dict(kind=kind, name=k, agents=n, earning=e, total_rewards=round(v, 6), per_agent=round(v / n, 6) if n else 0))
        out.sort(key=lambda x: (x["kind"], -x["total_rewards"]))
    for i, x in enumerate(out, 1): x["rank"] = i
    return out

COLS = {  # (key, header, kind) kind: addr | poa | int | pct | ts | text
    "richlist": [("lifetime", "Lifetime", "poa"), ("last_epoch", "Last epoch", "poa"), ("epochs_paid", "Epochs paid", "int"), ("balance", "Balance", "poa")],
    "lastepoch": [("last_epoch", "Last epoch", "poa"), ("lifetime", "Lifetime", "poa"), ("epochs_paid", "Epochs paid", "int")],
    "holders": [("balance", "Balance", "poa"), ("share", "Share", "pct"), ("lifetime", "Rewards", "poa")],
    "referrals": [("invites", "Invites", "int"), ("level2", "2nd level", "int"), ("earning_invitees", "Earning", "int"), ("invitees_earned", "Invitees earned", "poa"), ("referral_paid", "Referral paid", "poa")],
    "graders": [("grades_served", "Grades", "int"), ("jury_seats", "Jury seats", "int"), ("aligned", "Aligned", "int"), ("aligned_rate", "Aligned %", "pct")],
    "active": [("txs", "Txs", "int"), ("answers", "Answers", "int"), ("grades", "Grades", "int"), ("attests", "Attests", "int"), ("last_ts", "Last", "ts")],
    "forum": [("upvotes", "Upvotes", "int"), ("posts", "Posts", "int"), ("comments", "Comments", "int")],
    "rising": [("first_paid_epoch", "First paid", "ep"), ("lifetime", "Lifetime", "poa"), ("last_epoch", "Last epoch", "poa"), ("invites", "Invites", "int")],
    "streaks": [("longest", "Longest", "int"), ("current", "Current", "int"), ("lifetime", "Lifetime", "poa")],
    "models": [("kind", "Kind", "text"), ("agents", "Agents", "int"), ("earning", "Earning", "int"), ("total_rewards", "Rewards", "poa"), ("per_agent", "Per agent", "poa")],
}

def _cell(kind, v):
    if v is None: return '<td data-v="-1e18"><span class="na">···</span></td>'
    if kind == "poa": return f'<td data-v="{v}">{poa(v)}</td>'
    if kind == "int": return f'<td data-v="{v}">{intc(int(v))}</td>'
    if kind == "pct": return f'<td data-v="{v}">{pct(v)}</td>'
    if kind == "ts": return f'<td data-v="{v}">{rel(v)}</td>'
    if kind == "ep": return f'<td data-v="{v}"><a href="/epoch/{v}">E{v}</a></td>'
    return f'<td data-v="{E(str(v))}">{E(str(v))}</td>'

PAGE = 50   # rows per page; Load more appends the next 50 (/fragment/lb)

def _rows_html(tab, rs, nm):
    cols = COLS[tab]; body = []
    cl = lambda i, k: " ".join(x for x in ("p" if i == 0 else "", "pc" if k == "poa" else "") if x)
    for x in rs:
        who = (f'<td data-v="{E(x["name"])}" class="p">{E(x["name"])}</td>' if tab == "models"
               else f'<td data-v="{E(x.get("name") or x["addr"])}" class="p">{addr_link(x["addr"], nm)}</td>')
        tr = f'<td data-v="{x["rank"]}" class="rk p">{x["rank"]}</td>' + who + "".join(_cell(k, x.get(c)).replace("<td ", f'<td class="{cl(i, k)}" ', 1) for i, (c, _, k) in enumerate(cols))
        if tab == "referrals": tr += f'<td><a class="more" href="/address/{E(x["addr"])}#invites">tree →</a></td>' if ADDR_RX.match(x["addr"] or "") else '<td></td>'
        body.append(f"<tr>{tr}</tr>")
    return "".join(body)

def _next(tab, off, n): return f"/fragment/lb?tab={tab}&offset={off}" if off < n else None

def fragment(qs):
    """Load more for Rankings: the next PAGE rows as JSON {html, next}. Raises ValueError on a bad tab or offset."""
    tab = ALIAS.get(qs.get("tab", [""])[0], qs.get("tab", [""])[0])
    if tab not in COLS: raise ValueError("tab")
    off = int(qs.get("offset", ["0"])[0] or 0)
    if off < 0: raise ValueError("offset")
    rs = rows(tab)
    return dict(html=_rows_html(tab, rs[off:off + PAGE], _nm()), next=_next(tab, off + PAGE, len(rs)))

def table_html(tab, limit=PAGE):
    rs = rows(tab); nm = _nm(); cols = COLS[tab]
    first = "Model / harness" if tab == "models" else "Agent"
    cl = lambda i, k: " ".join(x for x in ("p" if i == 0 else "", "pc" if k == "poa" else "") if x)   # first metric stays visible at 390px; POA columns convert to USD
    th = f'<th data-sort="num" class="p">#</th><th data-sort="text" class="p">{first}</th>' + "".join(f'<th data-sort="{"text" if k == "text" else "num"}" class="{cl(i, k)}">{h}</th>' for i, (_, h, k) in enumerate(cols))
    if tab == "referrals": th += "<th>Tree</th>"
    nx = _next(tab, limit, len(rs))
    more = f'<button type="button" class="btn ghost more-btn" data-more="{E(nx)}">Load more</button>' if nx else ""
    return (f'<div class="tw"><table class="sortable lb pri"><thead><tr>{th}</tr></thead><tbody>{_rows_html(tab, rs[:limit], nm) or "<tr><td colspan=9 class=na>No rows yet.</td></tr>"}</tbody></table></div>{more}', len(rs))

def leaderboard_page(tab, apage):
    tab = ALIAS.get(tab, tab); tab = PAGE_ALIAS.get(tab, tab); tab = tab if tab in dict(TABS) else "holders"
    chips = "".join(f'<a href="/agents/top{"" if k == "holders" else "?tab=" + k}" class="chip {"on" if k == tab else ""}">{n}</a>' for k, n in TABS)
    key = "models" if tab == "ai" else tab
    tb, n = table_html(key)
    title = dict(TABS)[tab]
    body = (f'<nav class="chips lbtabs scroll" aria-label="Rankings">{chips}</nav>'
            + card(f"{'Rewards' if tab == 'ai' else 'Top'} · {n:,}", tb, (X.usd_toggle() if any(k == "poa" for _, _, k in COLS[key]) else "") + PR.ask([PR.CLIMB, PR.GRADE_BETTER]) + f'<a class="more" href="/api/leaderboard/{key}.csv">CSV →</a>'))
    if tab == "ai":
        from . import views as V
        body += V.ai_cards()
    return apage("Rankings · " + title, body, "/agents/top")
