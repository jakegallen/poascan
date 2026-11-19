"""Start hub (consolidation step 6): one module with Join, Check and Earn tabs beside a live panel (mock start2).

Join: the existing /start card (startv2.body(), 1.26.246: name, app, then what that app needs), unchanged except that its own heading and tab chips are not drawn. The prompt text, its hashes (join template 32f96b73, combined f9205f0f), the key warning copy
and every link that carries a key are untouched; only the old /start heading and the Sign up and Start earning chips moved into the tabs.
Check: paste one address, read its lifecycle as a vertical stepper (joined, first answer, first seal, first payout) with a Watching dot that re-reads
until the last stage lands. The address is checked for format first (never echoed when wrong); an unknown address says so.
Earn: ways to earn as short rows (Pays, Qualifies, Next); the FAQ stays on /about.
Live panel: the open epoch with its answer countdown and three KPIs (Joined today, Pass rate, Median to pay) with the joins per hour history.

Backend (agreed in the issue 147 thread, not on main yet): 7a GET /api/v1/agents/{addr}/lifecycle -> {stage (paid|grading|answering|joined), joined_ts, first_answer_ts, first_seal_ts, first_payout_ts}
(404 on unknown), 7b GET /api/v1/agents/joiners?days=7 -> {joins_per_hour:[[hour_ts,n]], median_s_to_first_pass, median_s_to_first_pay, joiners, reached_first_pass, reached_first_pay}. Both are staged as PR 179.
Until those land the same fields are computed here from the local archive (cached, no upstream read), through lifecycle() and joiners();
LIFECYCLE_FN and JOINERS_FN take Build's readers when they exist."""
import time, re, statistics
from html import escape as E
from . import db, analytics as A, kit as KIT, segments as SG
from .ui import *
from . import ui as _ui

TABS = [("join", "/start", "Join"), ("check", "/start?tab=check", "Check"), ("earn", "/start?tab=earn", "Earn")]
HEAD = '<link rel="stylesheet" href="/static/start.css?v={}"><script src="/static/start.js?v={}" defer></script>'
LIFECYCLE_FN = None; JOINERS_FN = None
STAGES = [("joined_ts", "Joined"), ("first_answer_ts", "First answer"), ("first_seal_ts", "First seal"), ("first_payout_ts", "First payout")]

def _asset_v(name):
    import hashlib, os
    try: return hashlib.sha256(open(os.path.join(os.path.dirname(__file__), "..", "static", name), "rb").read()).hexdigest()[:10]
    except OSError: return "0"

def _q(qs, k, d=""): return ((qs or {}).get(k) or [d])[0]

# ---------------- 7a, 7b (local until Build's endpoints land) ----------------
@A.cached("start_first_pay", 600)
def _first_pay():
    """address -> ts of the first close that paid it, over every segment."""
    out = {}
    for n in SG.NUMBERS:
        for e in sorted(A.segment_closes(n), key=lambda e: int(e.get("ts") or 0)):
            t = int(e.get("ts") or 0)
            for a, v in (e.get("rewards") or {}).items():
                if a not in out and float(v or 0) > 0: out[a] = t
    return out

def lifecycle(addr):
    """None for an unknown address, else the 7a fields. Archive only."""
    if LIFECYCLE_FN:
        try: return LIFECYCLE_FN(addr)
        except Exception: return None
    j = db.q1("SELECT MIN(ts) AS t FROM txs WHERE type='join' AND from_addr=? AND ts>0", (addr,))
    acc = db.q1("SELECT api_ts, first_seen FROM accounts WHERE addr=?", (addr,))
    if not (j and j["t"]) and not acc: return None
    joined = int((j or {}).get("t") or (acc or {}).get("api_ts") or (acc or {}).get("first_seen") or 0) or None
    def first(tp):
        r = db.q1("SELECT MIN(ts) AS t FROM txs WHERE type=? AND from_addr=? AND ts>0", (tp, addr)); return int(r["t"]) if r and r["t"] else None
    d = dict(joined_ts=joined, first_answer_ts=first("challenge"), first_seal_ts=first("grade-sealed"), first_payout_ts=_first_pay().get(addr))
    done = [k for k, _ in STAGES if d.get(k)]
    d["stage"] = {"joined_ts": "joined", "first_answer_ts": "answering", "first_seal_ts": "grading", "first_payout_ts": "paid"}[done[-1]] if done else "unknown"   # Build's 7a vocabulary (staged PR 179)
    return d

@A.cached("start_joiners", 300)
def joiners(days=7):
    if JOINERS_FN:
        try: return JOINERS_FN(days)
        except Exception: return None
    import os
    if os.environ.get("POASCAN_PAGES_FIXTURE") == "1": days = 28   # fixture screenshots only: the copy has no join in the last 7 days
    now = int(time.time()); since = now - days * 86400
    rows = db.q("SELECT from_addr AS a, MIN(ts) AS t FROM txs WHERE type='join' AND ts>? AND from_addr IS NOT NULL GROUP BY from_addr", (since - 86400,))
    hours = {}
    for r in rows:
        if r["t"] >= since: h = int(r["t"]) // 3600 * 3600; hours[h] = hours.get(h, 0) + 1
    fp = _first_pay(); pay = [fp[r["a"]] - r["t"] for r in rows if r["t"] >= since and r["a"] in fp and fp[r["a"]] >= r["t"]]
    fans = {}
    for r in rows:
        if r["t"] < since: continue
        x = db.q1("SELECT MIN(ts) AS t FROM txs WHERE type='challenge' AND from_addr=? AND ts>=?", (r["a"], r["t"]))
        if x and x["t"]: fans[r["a"]] = x["t"] - r["t"]
    cohort = [r for r in rows if r["t"] >= since]
    return dict(joins_per_hour=sorted([h, n] for h, n in hours.items()), median_s_to_first_pass=(statistics.median(fans.values()) if fans else None),
                median_s_to_first_pay=(statistics.median(pay) if pay else None), joiners=len(cohort),
                reached_first_pass=len(fans), reached_first_pay=len(pay))   # local: first pass is read as the first answer; Build's 7b (staged PR 179) counts the first passed answer

# ---------------- live panel ----------------
def live_panel():
    o = A.open_epoch() or {}; ep = o.get("epoch"); now = time.time(); ec = o.get("est_close"); lc = o.get("last_close")
    left = int(ec - now) if ec else None; per = (ec - lc) if (ec and lc) else None
    f = min(1.0, max(0.0, 1 - left / per)) if (left is not None and per) else 0
    j = joiners() or {}; hrs = j.get("joins_per_hour") or []
    today = sum(n for h, n in hrs if h >= now - 86400)
    pay = j.get("median_s_to_first_pay"); paid = (j.get("reached_first_pass") or 0) / j["joiners"] if j.get("joiners") else None
    cd = (f'<span class="lbl">Answer in</span><b class="num stcd" data-left="{left}" data-at="{int(now)}">{dur(left)}</b>' if left and left > 0 else "")
    tk = ('<circle class="mk2" cx="120" cy="120" r="111" pathLength="96" stroke-dasharray=".25 1.75"/>'
          '<circle class="hk" cx="120" cy="120" r="112.5" pathLength="96" stroke-dasharray=".5 15.5" stroke-dashoffset=".25"/>')
    ring = (f'<div class="ring hring string" style="--f:{f:.4f}"><svg viewBox="0 0 240 240" aria-hidden="true"><circle class="rt" cx="120" cy="120" r="104"/>'
            f'<circle class="rp" cx="120" cy="120" r="104" pathLength="100" stroke-dasharray="{f * 100:.2f} 100"/>{tk}</svg>'
            f'<i class="rhd" aria-hidden="true"><i></i></i><i class="rpl" aria-hidden="true"></i>'
            f'<div class="rc"><span class="lbl">Epoch</span><b class="bn num">{ep if ep is not None else "···"}</b>{cd}</div></div>')
    spark = [(h, n) for h, n in hrs[-24:]]
    kp = [KIT.kpi("Joined today", f'<span class="num">{intc(today)}</span>' if hrs else "···", spark if len(spark) > 1 else None),
          KIT.kpi("Pass rate", f'<span class="num">{100 * paid:.0f}%</span>' if paid is not None else "···"),
          KIT.kpi("Median to pay", f'<span class="num">{pay / 3600:.1f}h</span>' if pay else "···")]
    return (f'<aside class="card benchc stlive" aria-label="Live"><div class="string">{ring}</div>'
            f'<section class="stats four kpis three" role="group" aria-label="Headline numbers">{"".join(kp)}</section></aside>')

# ---------------- tabs ----------------
def _ago(ts, now): 
    d = max(0, int(now - ts)); return dur(d) + " ago" if d >= 60 else "now"

def check_body(qs):
    raw = _q(qs, "address").strip()
    from .earnview import ADDR_RX
    form = (f'<form class="stq" action="/start" method="get" role="search" autocomplete="off"><input type="hidden" name="tab" value="check">'
            f'<input name="address" value="{E(raw) if ADDR_RX.match(raw) else ""}" placeholder="poa1 address" aria-label="Agent address" autocomplete="off" autocapitalize="off" '
            f'spellcheck="false" maxlength="64" enterkeyhint="search" required></form>')
    if not raw: return form
    if not ADDR_RX.match(raw): return form + na("That is not a poa1 address. Paste the address only, never a key.")
    d = lifecycle(raw)
    if not d: return form + na("No Agent found for that address.")
    now = time.time(); done = [k for k, _ in STAGES if d.get(k)]; nxt = next((k for k, _ in STAGES if not d.get(k)), None)
    li = []
    for i, (k, t) in enumerate(STAGES, 1):
        ts = d.get(k)
        st = "done" if ts else ("now" if k == nxt else "wait")
        right = f'<time class="t" data-ts="{int(ts)}" title="{utc_text(ts)}">{_ago(ts, now)}</time>' if ts else ""
        li.append(f'<li class="stl-{st}"><i class="stdot" aria-hidden="true">{"" if st != "wait" else i}</i><b>{t}</b><span class="dim">{right}</span></li>')
    watching = nxt is not None
    head = f'<div class="stw {"on" if watching else ""}"><i class="ldot" aria-hidden="true"></i><span class="lbl">{"Watching" if watching else "Complete"}</span></div>'
    from . import walletview as WV
    return form + head + f'<ol class="stper" data-stper data-watch="{1 if watching else 0}">{"".join(li)}</ol>' + WV.binding_card(raw, lookup=True)

def earn_body():
    from . import earn as EA
    rows = "".join(f'<tr><td>{E(w["label"])}</td><td>{E(w["pays"])}</td><td>{E(w["qualifies"])}</td><td>{E(w["next"])}</td></tr>' for w in EA.ways())
    return f'<div class="tw"><table class="hist stearn"><thead><tr><th>Way</th><th>Pays</th><th>Qualifies</th><th>Next</th></tr></thead><tbody>{rows}</tbody></table></div>'

def join_body():
    from . import startv2 as SV2
    return SV2.body(hero=False)

def page(page_fn):
    qs = getattr(_ui.REQ, "qs", None) or {}; tab = _q(qs, "tab"); tab = tab if tab in ("join", "check", "earn") else "join"
    body = {"join": join_body, "check": lambda: check_body(qs), "earn": earn_body}[tab]()
    mod = KIT.tabmod([(k, h, t, None) for k, h, t in TABS], tab, body, "", id="stmod", label="Start")
    mod = mod.replace(' data-kit-tab="join"', "")   # the wizard binds on load: Join is a full page load, never an in-place swap
    if tab == "join": mod = mod.replace('data-kit="tabs"', 'data-kit="join"', 1)   # app.js reloads on popstate while a tabs module exists; the wizard steps back with the hash, so Join is not one
    html = f'<div class="sthub"><div class="stmain">{mod}</div>{live_panel()}</div>'
    v2 = (f'<link rel="stylesheet" href="/static/startv2.css?v={_asset_v("startv2.css")}"><script src="/static/startv2.js?v={_asset_v("startv2.js")}" defer></script>' if tab == "join" else "")
    return page_fn("Start", f'<div class="sechead"><h1 class="sr-only">Start</h1></div>{html}', "/start", head=v2 + HEAD.format(_asset_v("start.css"), _asset_v("start.js")))
