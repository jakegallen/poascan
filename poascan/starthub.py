"""Start hub (consolidation step 6): one module with Join, Check and Earn tabs beside a live panel (mock start2).

Join: the existing /start card (startv2.body(), 1.26.246: name, app, then what that app needs), unchanged except that its own heading and tab chips are not drawn. The prompt text, its hashes (join template 32f96b73, combined f9205f0f), the key warning copy
and every link that carries a key are untouched; only the old /start heading and the Sign up and Start earning chips moved into the tabs.
Check: paste one address, read its lifecycle as a vertical stepper (joined, first answer, first seal, first payout) with a Watching dot that re-reads
until the last stage lands. The address is checked for format first (never echoed when wrong); an unknown address says so.
Earn: ways to earn as short rows (Pays, Qualifies, Next); the FAQ stays on /about.
Live panel: the open epoch with its answer countdown and three KPIs (Joined today, Pass rate, Median to pay) with the joins per hour history.

Data: Build's 7a lifecycle (agents.agent_lifecycle) and 7b joiners (agents.joiners), read in process, the same data as /api/v1/agents/{addr}/lifecycle and /api/v1/agents/joiners."""
import time, re, statistics
from html import escape as E
from . import db, analytics as A, kit as KIT, segments as SG
from .ui import *
from . import ui as _ui

TABS = [("join", "/start", "Join"), ("check", "/start?tab=check", "Check"), ("earn", "/start?tab=earn", "Earn")]
HEAD = '<link rel="stylesheet" href="/static/start.css?v={}"><script src="/static/start.js?v={}" defer></script>'
STAGES = [("joined_ts", "Joined"), ("first_answer_ts", "First answer"), ("first_seal_ts", "First seal"), ("first_payout_ts", "First payout")]

def _asset_v(name):
    import hashlib, os
    try: return hashlib.sha256(open(os.path.join(os.path.dirname(__file__), "..", "static", name), "rb").read()).hexdigest()[:10]
    except OSError: return "0"

def _q(qs, k, d=""): return ((qs or {}).get(k) or [d])[0]

# ---------------- 7a, 7b (Build's readers, in process) ----------------
def lifecycle(addr):
    """None for an unknown or malformed address, else Build's 7a fields (agents.agent_lifecycle, the same data as /api/v1/agents/{addr}/lifecycle)."""
    from . import agents as AGN
    try: r = AGN.agent_lifecycle(addr)
    except Exception: return None
    return None if r in (None, "badaddr") else r

def joiners(days=30):
    """Build's 7b (agents.joiners, the same data as /api/v1/agents/joiners?days=30): joins per hour, medians to first pass and first pay.
    1.26.398: the panel reads 30 days (the median to first pass is about 3 days, so a 7 day window is censored by its own newest joiners)."""
    from . import agents as AGN
    try: return AGN.joiners(days)
    except Exception: return None

def _last_join():
    try:
        from . import maint
        return maint.last_join()
    except Exception: return None

def _state_tags():
    """Why the numbers may be flat: the direct HTTP route halt and the MCP path stay separate (maint.join_pow_route, join_state_api). Nothing while joining is open."""
    try:
        from . import maint
        halt = maint.join_halt(); st = maint.join_state_api()
    except Exception: return ""
    tags = []
    if halt: tags.append(f'<span class="tag warn" title="Direct HTTP join is halted. MCP join is a separate path.">Direct halted {lt(halt["since_ts"], "d")}</span>')
    elif st != "open": tags.append('<span class="tag warn">Paused</span>')
    if tags and st == "open": tags.append('<span class="tag ok">MCP open</span>')
    return f'<div class="ststate">{"".join(tags)}</div>' if tags else ""

def _span_s(s):
    """Short span: 45m, 7h, 3.4d."""
    s = int(s)
    return f"{s // 60}m" if s < 3600 else f"{s // 3600}h" if s < 48 * 3600 else f"{s / 86400:.1f}d"

def _daily(hrs, now, days=14):
    """Joins per UTC day for the last `days` days, zero filled, so a halt reads as a flat line after the last burst."""
    d0 = int(now) // 86400 * 86400; base = d0 - (days - 1) * 86400; out = {base + i * 86400: 0 for i in range(days)}
    for h, n in hrs:
        k = int(h) // 86400 * 86400
        if k in out: out[k] += n
    return sorted(out.items())

# ---------------- live panel ----------------
def live_panel():
    o = A.open_epoch() or {}; ep = o.get("epoch"); now = time.time(); ec = o.get("est_close"); lc = o.get("last_close")
    left = int(ec - now) if ec else None; per = (ec - lc) if (ec and lc) else None
    f = min(1.0, max(0.0, 1 - left / per)) if (left is not None and per) else 0
    j = joiners() or {}; hrs = j.get("joins_per_hour") or []
    today = sum(n for h, n in hrs if h >= now - 86400); lj = _last_join()
    pay = j.get("median_s_to_first_pay"); med_pass = j.get("median_s_to_first_pass")
    # pass rate only over joiners old enough to have had the median wait; below 20 of them it is n/a (never a 0% from a window of newcomers)
    elig = sum(n for h, n in hrs if med_pass and h <= now - med_pass)
    paid = min(1.0, (j.get("reached_first_pass") or 0) / elig) if elig >= 20 else None
    cd = (f'<span class="lbl">Answer in</span><b class="num stcd" data-left="{left}" data-at="{int(now)}">{dur(left)}</b>' if left and left > 0 else "")
    tk = ('<circle class="mk2" cx="120" cy="120" r="111" pathLength="96" stroke-dasharray=".25 1.75"/>'
          '<circle class="hk" cx="120" cy="120" r="112.5" pathLength="96" stroke-dasharray=".5 15.5" stroke-dashoffset=".25"/>')
    ring = (f'<div class="ring hring string" style="--f:{f:.4f}"><svg viewBox="0 0 240 240" aria-hidden="true"><circle class="rt" cx="120" cy="120" r="104"/>'
            f'<circle class="rp" cx="120" cy="120" r="104" pathLength="100" stroke-dasharray="{f * 100:.2f} 100"/>{tk}</svg>'
            f'<i class="rhd" aria-hidden="true"><i></i></i><i class="rpl" aria-hidden="true"></i>'
            f'<div class="rc"><span class="lbl">Epoch</span><b class="bn num">{ep if ep is not None else "···"}</b>{cd}</div></div>')
    daily = _daily(hrs, now) if hrs else []
    w = "Joiners of the last 30 days"
    if today or not lj: k1 = KIT.kpi("Joined today", f'<span class="num">{intc(today)}</span>' if hrs else "···", daily if daily else None)
    else: k1 = KIT.kpi("Last join", f'<span class="num">{_span_s(now - lj)}</span>', daily if daily else None, tip="Time since the latest join on the ledger")
    kp = [k1,
          KIT.kpi("Pass rate", f'<span class="num">{100 * paid:.0f}%</span>' if paid is not None else '<span class="num">n/a</span>', tip=w),
          KIT.kpi("Median to pay", f'<span class="num">{_span_s(pay)}</span>' if pay else "···", tip=w)]
    return (f'<aside class="card benchc stlive" aria-label="Live"><div class="string">{ring}</div>{_state_tags()}'
            f'<section class="stats four kpis three" role="group" aria-label="Headline numbers">{"".join(kp)}</section></aside>')

# ---------------- tabs ----------------
def _ago(ts, now): 
    d = max(0, int(now - ts)); return _span_s(d) + " ago" if d >= 60 else "now"

def check_body(qs):
    raw = _q(qs, "address").strip()
    from .earnview import ADDR_RX
    form = (f'<form class="stq" action="/start" method="get" role="search" autocomplete="off"><input type="hidden" name="tab" value="check">'
            f'<input name="address" value="{E(raw) if ADDR_RX.match(raw) else ""}" placeholder="poa1 address" aria-label="Agent address" autocomplete="off" autocapitalize="off" '
            f'spellcheck="false" maxlength="64" enterkeyhint="search" required></form>')
    if not raw:
        pre = "".join(f'<li class="stl-wait"><i class="stdot" aria-hidden="true">{i}</i><b>{t}</b></li>' for i, (_, t) in enumerate(STAGES, 1))
        return form + f'<ol class="stper stnext" aria-label="Stages">{pre}</ol>' + _ask(None)
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
    return form + head + f'<ol class="stper" data-stper data-watch="{1 if watching else 0}">{"".join(li)}</ol>' + WV.binding_card(raw, lookup=True) + _ask(raw)

def _ask(addr):
    """The one Ask agent button on the site (the earn check prompt), here in Start only."""
    from . import prompts as PR
    from .earnview import ask_item
    return f'<div class="stask">{PR.ask([ask_item(addr)])}</div>'

def earn_body():
    from . import earn as EA
    rows = "".join(f'<tr><td>{E(w["label"])}</td><td>{E(w["pays"])}</td><td>{E(w["qualifies"])}</td><td>{E(w["next"])}</td></tr>' for w in EA.ways())
    return _ask(None) + f'<div class="tw"><table class="hist stearn"><thead><tr><th>Way</th><th>Pays</th><th>Qualifies</th><th>Next</th></tr></thead><tbody>{rows}</tbody></table></div>'

NEXT = ["Pick app", "Paste prompt", "Get graded", "Get paid"]

def join_body():
    """The existing wizard, then (only while the name step shows) the road ahead as a quiet stepper so the panel is never an empty box."""
    from . import startv2 as SV2
    nx = ('<ol class="stper stnext" aria-label="Road ahead">' + "".join(f'<li class="stl-wait"><i class="stdot" aria-hidden="true">{i}</i><b>{t}</b></li>' for i, t in enumerate(NEXT, 1)) + "</ol>")
    h = SV2.body(hero=False); k = "data-sv-err0 hidden></p></div>"
    return h.replace(k, k + nx, 1) if k in h else h

def page(page_fn):
    qs = getattr(_ui.REQ, "qs", None) or {}; tab = _q(qs, "tab"); tab = tab if tab in ("join", "check", "earn") else "join"
    body = {"join": join_body, "check": lambda: check_body(qs), "earn": earn_body}[tab]()
    mod = KIT.tabmod([(k, h, t, None) for k, h, t in TABS], tab, body, "", id="stmod", label="Start")
    mod = mod.replace(' data-kit-tab="join"', "")   # the wizard binds on load: Join is a full page load, never an in-place swap
    if tab == "join": mod = mod.replace('data-kit="tabs"', 'data-kit="join"', 1)   # app.js reloads on popstate while a tabs module exists; the wizard steps back with the hash, so Join is not one
    html = f'<div class="sthub"><div class="stmain">{mod}</div>{live_panel()}</div>'
    v2 = (f'<link rel="stylesheet" href="/static/startv2.css?v={_asset_v("startv2.css")}"><script src="/static/startv2.js?v={_asset_v("startv2.js")}" defer></script>' if tab == "join" else "")
    return page_fn("Start", f'<div class="sechead"><h1 class="sr-only">Start</h1></div>{html}', "/start", head=v2 + HEAD.format(_asset_v("start.css"), _asset_v("start.js")))
