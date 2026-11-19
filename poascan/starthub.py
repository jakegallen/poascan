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

def joiners(days=7):
    """Build's 7b (agents.joiners, the same data as /api/v1/agents/joiners?days=7): joins per hour, medians to first pass and first pay. Cached 5 minutes there."""
    from . import agents as AGN
    try: return AGN.joiners(days)
    except Exception: return None

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
