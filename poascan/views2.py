"""Status, growth, unlocks, reward tracker, leaderboards, safety. Minimal text, Assay styling."""
import json, time, math, collections, statistics, datetime as dt
from . import db, analytics as A, agents as G
from .ui import *
from . import prompts as PR, indexer as I
from .ui import _ic

def page(title, body, active):
    from . import views
    return views.page(title, body, active)

cached = A.cached
ICON_SWAP = _ic('<path d="M8 10h7.5l-2-2M16 14H8.5l2 2" stroke-linecap="round" stroke-linejoin="round"/>')
def names(): return A.forum_names()

# Swaps live in poascan/swap (page, data, price, prompts); the explorer reads them through poascan/market.py.

@cached("uptime_daily", 120)
def uptime_rows(days=30):
    now = int(time.time()); cut = (now // 86400 - days + 1) * 86400
    by = {(r["day"], r["endpoint"]): r for r in db.q("SELECT day, endpoint, n, ok, ms FROM uptime_daily WHERE day >= ?", (cut,))}
    for k in [k for k in by if k[1] in I.DERIVED and k[0] >= now // 86400 * 86400 - 86400]: del by[k]
    for r in db.q("SELECT (ts/86400)*86400 AS day, CASE WHEN endpoint IN (?,?,?) THEN 'probe ' || endpoint ELSE endpoint END AS endpoint, COUNT(*) AS n, SUM(ok) AS ok, "
                  "CAST(AVG(CASE WHEN ok=1 THEN ms END) AS INTEGER) AS ms FROM probes WHERE ts >= ? GROUP BY 1, 2", I.DERIVED + (max(cut, now - 2 * 86400),)):
        by[(r["day"], r["endpoint"])] = r
    return [dict(day=time.strftime("%Y-%m-%d", time.gmtime(d)), ts=d, endpoint=e.replace("probe ", ""), kind="probe" if e.startswith("probe ") else "fetch",
                 checks=r["n"], ok=r["ok"], uptime=round(r["ok"] / r["n"], 4) if r["n"] else None, avg_ms=r["ms"]) for (d, e), r in sorted(by.items())]

def uptime_chart_html():
    rows = [r for r in uptime_rows() if r["kind"] == "probe"]
    if not rows: return skel()
    days = collections.OrderedDict()
    for r in rows: d = days.setdefault(r["day"], [0, 0]); d[0] += r["checks"]; d[1] += r["ok"]
    return bars([(k[5:], [v[1] / v[0] * 100 if v[0] else 0]) for k, v in days.items()], height=150, colors=("gold",), fmt=lambda v: f"{v:.0f}%", ymax=100)

def uptime_table_html():
    rows = [r for r in uptime_rows() if r["kind"] == "probe"]
    eps = sorted({r["endpoint"] for r in rows}); days = sorted({r["day"] for r in rows})[-7:]
    m = {(r["day"], r["endpoint"]): r["uptime"] for r in rows}
    return table(["Endpoint"] + [d[5:] for d in days], [[f'<code>{E(e)}</code>'] + [_okpct(m.get((d, e))) for d in days] for e in eps], cls="wrapt")

# ================= status =================
def _pctl(v, q):
    if not v: return None
    v = sorted(v); return v[min(len(v) - 1, int(q * len(v)))]

@cached("status_page", 30)
def status_data():
    """Aggregated in SQLite: the probes table holds ~28k rows a day (14 days kept), far too many to load into
    Python on a 512 MB machine. Only per-endpoint totals, failing 5-minute buckets and 24 h latencies come back."""
    now = int(time.time()); t14 = now - 14 * 86400
    EP = "CASE WHEN endpoint IN (?,?,?) THEN 'probe ' || endpoint ELSE endpoint END"
    D = tuple(I.DERIVED)
    eps = []
    for r in db.q(f"""SELECT {EP} AS ep,
          SUM(ts > ?) AS n1, SUM(CASE WHEN ts > ? THEN ok END) AS ok1, SUM(ts > ?) AS n24, SUM(CASE WHEN ts > ? THEN ok END) AS ok24,
          MAX(CASE WHEN ok=1 THEN ts END) AS last_ok, MAX(CASE WHEN ok=0 THEN ts END) AS last_err
        FROM probes WHERE ts > ? GROUP BY 1""", D + (now - 3600, now - 3600, now - 86400, now - 86400, t14)):
        eps.append(dict(ep=r["ep"], n1=r["n1"] or 0, s1=(r["ok1"] / r["n1"]) if r["n1"] else None, s24=(r["ok24"] / r["n24"]) if r["n24"] else None,
                        p50=None, p95=None, last_ok=r["last_ok"], last_err=r["last_err"], last_code=None))
    by = {e["ep"]: e for e in eps}
    for r in db.q(f"SELECT {EP} AS ep, code, MAX(ts) AS t FROM probes WHERE ok=0 AND ts > ? GROUP BY 1", D + (t14,)):
        if r["ep"] in by: by[r["ep"]]["last_code"] = r["code"]
    ms1, ms24 = collections.defaultdict(list), collections.defaultdict(list); hrs = collections.defaultdict(list)
    for r in db.q(f"SELECT {EP} AS ep, ts, ms FROM probes WHERE ok=1 AND ts > ?", D + (now - 86400,)):
        ms24[r["ep"]].append(r["ms"]); hrs[r["ts"] // 3600 * 3600].append(r["ms"])
        if r["ts"] > now - 3600: ms1[r["ep"]].append(r["ms"])
    for e in eps:
        e["p50"] = _pctl(ms1.get(e["ep"]) or ms24.get(e["ep"]) or [], .5); e["p95"] = _pctl(ms24.get(e["ep"]) or [], .95)
    del ms1, ms24
    eps.sort(key=lambda x: (not x["ep"].startswith("probe"), x["ep"]))
    # incidents: 5-minute buckets per endpoint with >=50% failures (and >=2 fails), merged when consecutive
    inc = []; bad = collections.defaultdict(list)
    for r in db.q(f"""SELECT {EP} AS ep, ts / 300 AS b, COUNT(*) AS n, SUM(1 - ok) AS f FROM probes WHERE ts > ?
                      GROUP BY 1, 2 HAVING f >= 2 AND f * 2 >= n ORDER BY 1, 2""", D + (t14,)):
        bad[r["ep"]].append((r["b"], r["f"]))
    for ep, ks in bad.items():
        cur = None
        for k, f in ks:
            if cur and k - cur[1] <= 1: cur[1] = k; cur[2] += f
            else:
                if cur: inc.append((cur[0] * 300, cur[1] * 300 + 300, ep, cur[2]))
                cur = [k, k, f]
        if cur: inc.append((cur[0] * 300, cur[1] * 300 + 300, ep, cur[2]))
    # checkpoint stalls from our own height snapshots (two numbers per snapshot, not the whole JSON)
    hs = [(r["ts"], {"height": r["h"], "checkpoint_height": r["cp"]}) for r in db.q(
        "SELECT ts, json_extract(json, '$.height') AS h, json_extract(json, '$.checkpoint_height') AS cp FROM snaps "
        "WHERE kind IN ('height','status') AND ts > ? ORDER BY ts", (t14,))]
    lag = [(t, (d.get("height") or 0) - (d.get("checkpoint_height") or 0)) for t, d in hs if d.get("height") and d.get("checkpoint_height")]
    last_cp_change = None; start = None; prev = None
    STALL = 3 * 3600  # observed cadence ~1.5-2h
    for t, d in hs:
        cp = d.get("checkpoint_height")
        if not cp: continue
        if cp != prev: 
            if start and t - start >= STALL: inc.append((start, t, "no checkpoint > 3h", None))
            start = t; last_cp_change = t; prev = cp
    if start and hs and hs[-1][0] - start >= STALL: inc.append((start, None, "no checkpoint > 3h", None))
    inc.sort(key=lambda x: -x[0])
    from . import segments as _SG
    anc = db.q("SELECT chain, MAX(anchored_at) AS t, MAX(height) AS h FROM anchors WHERE segment=? GROUP BY chain", (_SG.CURRENT,))   # heights restart at a cut
    if not anc: anc = db.q("SELECT chain, MAX(anchored_at) AS t, MAX(height) AS h FROM anchors GROUP BY chain")
    return dict(eps=eps, inc=inc, lag=lag, last_cp_change=last_cp_change, anchors=anc,
                lat=[(h, statistics.median(v)) for h, v in sorted(hrs.items())])

def _iso(s):
    try: return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception: return None

def _every(s): return f"{s // 3600}h" if s >= 3600 else f"{s // 60}m"

def freshness_html():
    """One row per upstream source: how often we read it, when the last good read landed, and backoff."""
    now = time.time(); rows = []
    for r in A.health()["endpoints"]:
        ev = I.EVERY.get(r["endpoint"]); age = now - r["last_ok"] if r["last_ok"] else None
        old = age is None or (ev and age > 3 * ev)
        last = f'<span class="{"amber" if old else ""}">{rel(r["last_ok"])}</span>'
        rows.append([f'<code>{E(r["endpoint"])}</code>', _every(ev) if ev else "on view", last,
                     (f'<span class="red" title="{E((r["err"] or "")[:160])}">{r["fails"]}</span>') if r["fails"] else "0",
                     rel(r["next_at"]) if r["next_at"] and r["next_at"] > now else "now"])
    return table(["Source", "Every", "Last read", "Fails", "Next try"], rows, cls="wrapt")

def cp_stat():
    """Checkpoint moved, flagged once it has been unchanged for LAG_CP_S."""
    f = A.freshness()
    from . import maint as M
    fl = (flag("Parked", "Finality is parked for maintenance", "est") if f["maintenance"] and not M.recovery()["moved"]
          else flag("Stalled", f"Finalized height unchanged for {A.LAG_CP_S // 3600}h or more") if f["checkpoint_stalled"] else "")
    return f'<div class="stat"><div class="sl"><span title="When the finalized height (checkpoint) last moved">Finality moved</span>{fl}</div><div class="sv">{rel(f["checkpoint_moved"])}</div></div>'

RECON_TAG = {"match": ("ok", "Match"), "explained": ("", "Explained"), "differs": ("bad", "Differs"), "node_only": ("", "Node only"), "poascan_only": ("", "Ours only")}

def recon_card():
    from . import reconcile as RE
    from .views import rel_t
    d = RE.reconcile()
    def v(x, unit, at, src=""):
        if x is None: return '<span class="na">···</span>'
        n = num(x, 2) if unit == "poa" else intc(x)
        s = f"{src} · " if src else ""   # 1.26.88: the two holder counts are labelled by source (balances, node); method on /about#holders
        return f'{n}<small title="read {utc_text(at)}">{s}{rel_t(at)}</small>' if at else (f'{n}<small>{src}</small>' if src else n)
    HS = {"holders": ("balances", "node")}
    def tag(st): c, t = RECON_TAG[st]; return f'<span class="tag {c}">{t}</span>'
    def sub(r):
        dv = None if r["diff"] in (None, 0) else (f'Δ {"+" if r["diff"] > 0 else "-"}{compact(abs(r["diff"]), 2)}' if r["unit"] == "poa" else f'Δ {r["diff"]:+,}')
        t = " · ".join(E(x) for x in (dv, r["reason"]) if x)
        return f'<tr class="rwhy"><td colspan="4">{t}</td></tr>' if t else ""
    trs = "".join(f'<tr class="{"rx" if sub(r) else ""}"><td><b>{E(r["label"])}</b></td><td class="r">{v(r["poascan"], r["unit"], r["poascan_as_of"], HS.get(r["key"], ("", ""))[0])}</td>'
                  f'<td class="r">{v(r["node"], r["unit"], r["node_as_of"], HS.get(r["key"], ("", ""))[1])}</td><td class="r">{tag(r["state"])}</td></tr>' + sub(r) for r in d["rows"])
    tb = f'<div class="tw"><table class="hist rec"><thead><tr><th>Figure</th><th class="r">POAScan</th><th class="r">Node</th><th class="r">State</th></tr></thead><tbody>{trs}</tbody></table></div>'
    pc = [p for p in d["per_close"] if p["state"] != "no_reads"]
    pt = "".join(f'<tr><td><a class="mono" href="/epoch/{p["epoch"]}">E{p["epoch"]}</a></td><td class="r">{num(p["record_mint"], 2)}</td><td class="r">{num(p["supply_step"], 2)}</td><td class="r">{tag(p["state"])}</td></tr>' for p in pc)
    per = (f'<h3 class="rech">Mint per close</h3><div class="tw"><table class="hist rec"><thead><tr><th>Close</th><th class="r">Record</th><th class="r">Supply step</th><th class="r">State</th></tr></thead><tbody>{pt}</tbody></table></div>') if pc else ""
    foot = f'<p class="cov dim small">{d["matched"]} match · {d["explained"]} explained · {d["differs"]} differ · <a href="/about#reconcile">method</a></p>'
    return card("Reconciliation", tb + per + foot, '<a class="more" href="/api/v1/reconcile">API →</a>', cls="histc", id="reconcile")

# ================= /upgrade: the recovery page (its own layout; Health keeps uptime and latency) =================
ROUTE_TAG = {"open": ("ok", "Open"), "responding": ("ok", "Responding"), "paused": ("warn", "Paused"), "slow": ("warn slow", "Slow"), "unknown": ("", "Not read yet")}
ROUTE_WORD = {"open": "open", "paused": "paused"}

def _route_tip(v, st):
    """Tooltip for a route tag: a slow route keeps its last clear answer and its time."""
    if st != "slow": return ""
    if v["state"] in ROUTE_WORD and v.get("checked"):
        t = utc_text(v["checked"])
        return f' title="Not answering our reads right now. Last answered {t} ({ROUTE_WORD[v["state"]]})."'
    return ' title="Not answering our reads right now."'
CHECK = '<svg class="chk" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>'

def _chip(text, cls, html=""): return f'<li class="chp {cls}">{CHECK if cls == "ok" else "<i></i>"}<span>{E(text)}{html}</span></li>'

def upgrade_sig():
    """Changes whenever anything the /upgrade view shows changes; the live snapshot carries it and app.js refetches the view."""
    from . import maint as M
    r = M.recovery()
    return str(abs(hash((M.stamp_ts(), tuple(sorted(M.route_display().items())), M.join_state(), r["checkpoint"], r["supply_intact"], M.strip_text(), M.seen()["answers"],
                         r["epochs_closed"], M.pool_payouts(), M.attestation_earnings()))) % 10**10)

def upgrade_view():
    """Hero (status, live time, routes meter, Working and Still paused) plus four tiles. Everything here is live."""
    from . import maint as M, hosted as R
    m = M.state(); r = m["recovery"]; rt = R.current(); ds = M.route_display(); sn = M.seen()
    lead, aside, tail = M.strip_text()
    back = [k for k in rt if ds[k] in ("open", "responding")]; total = len(rt)
    allof = m["official"]["routes"]
    word = "back" if allof else "responding"
    segs = "".join(f'<li class="seg" data-hroute="{k}" data-st="{ds[k]}"{_route_tip(v, ds[k])}><i></i><span><b>{E(v["label"])}</b><em class="tag {ROUTE_TAG[ds[k]][0]}">{ROUTE_TAG[ds[k]][1]}</em></span></li>'
                   for k, v in rt.items())
    meter = (f'<div class="mtr"><div class="mtr-h"><span class="lbl">Endpoints {word}</span><b class="mtr-n"><span class="green">{len(back)}</span> of {total}</b></div>'
             f'<ol class="segs" aria-label="Hosted routes">{segs}</ol></div>')
    ok = []
    if r["supply_intact"]: ok += ["Balances intact"] + (["Supply carried"] if r.get("previous_segment") else ["Supply unchanged"])
    if r["checkpoint"]: ok.append(f'Checkpoint {r["checkpoint"]:,}')
    if A.freshness()["state"] != "stale": ok.append("Explorer live")
    if M.join_state() == "open": ok.append("Joining open")
    ok.append("Self-custody mining")
    if M.attestation_earnings() == "live": ok.append("Attestation earnings")
    if M.pool_payouts() == "live": ok.append("Challenge-pool payouts")
    ok += [f'{rt[k]["label"]} {"open" if ds[k] == "open" else "responding"}' for k in back]
    wait = [rt[k]["label"] for k in rt if ds[k] == "paused"] + [f'{rt[k]["label"]} (not read yet)' for k in rt if ds[k] == "unknown"]   # slow routes are not paused
    wait += (["Challenge-pool payouts"] if M.pool_payouts() == "paused" else []) + (["Attestation earnings"] if M.attestation_earnings() == "paused" else [])
    slow = [k for k in rt if ds[k] == "slow"]
    if M.join_state() == "paused": wait.append("Joining")
    grp = (f'<div class="grps"><div class="grp ok" data-grp="working"><h2><i></i>Working</h2><ul>{"".join(_chip(t, "ok") for t in ok)}</ul></div>'
           + (f'<div class="grp wait" data-grp="paused"><h2><i></i>Still paused</h2><ul>{"".join(_chip(t, "wait") for t in wait)}</ul></div>' if wait else "")
           + (f'<div class="grp wait slow" data-grp="slow"><h2><i></i>Slow to answer</h2><ul>'
              + "".join(_chip(rt[k]["label"] + (" · last answered " if rt[k]["state"] in ROUTE_WORD and rt[k].get("checked") else ""), "wait", lt(rt[k]["checked"]) if rt[k]["state"] in ROUTE_WORD and rt[k].get("checked") else "") for k in slow)
              + '</ul></div>' if slow else "")
           + '</div>')
    fr = M.back_phrase() if r["moved"] else ""
    sub = ((fr[:1].upper() + fr[1:] + ". ") if fr else "") + tail if r["moved"] else (aside.strip() + "." if aside else "")
    badge = f'<span class="upb"><i></i>Network upgrade</span>'
    hero = (f'<section class="uph" aria-labelledby="uph-t"><div class="uph-top">{badge}{stamp(M.stamp_ts())}</div>'
            f'<h1 class="uph-t" id="uph-t">{E(lead)}</h1>' + (f'<p class="uph-s">{E(sub)}</p>' if sub else "") + meter + grp + '</section>')
    cp = (f'<span class="from">{r["previous_checkpoint"]:,} →</span> <span class="num">{r["checkpoint"]:,}</span>' if r["moved"] else intc(r["checkpoint"] or m["parked_checkpoint"]))
    try: sv = f'<span class="num" title="{E(r["supply"])} POA">{compact3(float(r["supply"]))}</span><span class="unit">POA</span>'
    except Exception: sv = "···"
    tiles = "".join([stat("Checkpoint", cp), stat(("Supply carried" if r.get("previous_segment") else "Supply unchanged") if r["supply_intact"] else "Supply", sv),
                     stat("Answers · 1h", f'<span class="num">{sn["answers"]:,}</span>'), stat("Epochs closed", intc(r["epochs_closed"]))])
    return hero + f'<div class="stats four uptiles">{tiles}</div>'

def _prompt_release():
    """/upgrade Details: the current join prompt release, its time in the reader's zone plus UTC (ui.stamp; app.js adds local)."""
    from . import onboarding_prompt as OP
    ts = _iso_ts(OP.UPDATED_TS)
    return (f'<a href="/api/v1/prompts/join">{E(OP.VERSION)}</a>, {stamp(ts, "released")}. {E(OP.RELEASE_NOTE)} '
            f'Same text on <a href="/start">/start</a>, llms.txt and MCP.')

def _release():
    """/upgrade Details: this POAScan release, its time in the reader's zone plus UTC (ui.stamp; app.js adds local)."""
    from . import agentapi as AG
    return f'{E(AG.VERSION)}, {stamp(_iso_ts(AG.RELEASED_TS), "released")}. {E(AG.RELEASE_LINE)}'

def _iso_ts(s):
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())

def _SG():
    from . import signed as SG
    return SG

def upgrade_details():
    """Small print under the tiles, collapsed: state root, notice, status freshness, how we check, guidance for Agents, the prompt."""
    from . import maint as M, hosted as R
    m = M.state(); r = m["recovery"]; n = m["notice"]; ck = R.checked_at()
    sr = r["state_root"]
    ts = A._ts(r["status_as_of"])
    rows = [("State root", f'<code class="sr">{E(sr)}</code>' if sr else "···"),
            ("Notice", "···" if n is None else f'<code>{E(n["id"] or "")}</code> {"active" if n["active"] else "no longer active"}{_SG().badge(_SG().lookup(notice_id=n["id"]))}'),
            ("/api/status", ("Fresh" if r["status_fresh"] else "Not fresh") + (f", {stamp(ts, 'as of')}" if ts else "")
             + (f'. Tx counters restarted at the new checkpoint: {int(r["txs"]):,} {"tx" if r["txs"] == 1 else "txs"}, {int(r["final"] or 0):,} final' if r["moved"] and isinstance(r["txs"], int) else "") + "."),
            ("How we check", "One keyless read per hosted route every 15 minutes" + (f", last {stamp(ck, 'at')}" if ck else "")
             + ". Responding means the route answers; Open needs the official notice or post."),
            ("Agents", "Check once an hour at a random minute. No retry loops. After a 502, read the receipt before resubmitting. Pending grades keep "
             f'{m["pending_ttl_epochs"]} epochs.'),
            ("Joining", E(M.join_line())), ("Join prompt", _prompt_release()), ("Release", _release())]
    cites = M.citations()
    if cites:   # no per-comment anchors on LabLeak, so the link is the post and the comment is named
        rows.append(("Operator", "; ".join(f'{E(lab)}: comment {cid}, <time datetime="{E(at.replace(" ", "T"))}Z">{E(at.replace(" ", "T").split("T")[-1][:8])}Z</time>'
                                           for lab, cid, at in cites) + f' on <a href="{M.POST_URL}" target="_blank" rel="noopener noreferrer">LabLeak post {M.POST_ID}</a>.'))
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    box = (f'<div class="upa" data-pcard data-pid="upgrade"><span class="lbl jm-l">Ask agent</span>'
           + _J.pbox(f'<pre class="pc-text" tabindex="0">{E(PR.UPGRADE[1])}</pre>') + '</div>')
    since = lt(M.STARTED)
    links = (f'<p class="upl small"><a href="{m["post_url"]}" target="_blank" rel="noopener noreferrer">Official post ↗</a>'
             f'<span>Since {since}</span><a href="/network?tab=health">Uptime and latency on Health</a>{_board()}</p>')
    return links + f'<details class="updet"><summary>Details</summary><dl class="upg">{dl}</dl>{box}</details>'

def _when(ts):
    """Date and time in the reader's zone (ui.lt), so the reader sees which day."""
    return lt(ts)

def _ts_row(label, ts, extra=""):
    return f"<dt>{E(label)}</dt><dd>{_when(ts) if ts else '···'}{extra}</dd>"

def upgrade_done():
    """/upgrade once the upgrade is officially complete (maint.complete()): a short note with the dates. Kept as a record."""
    from . import maint as M
    c = M.complete(); tx = c.get("txid"); g = M.grading_state(); gst = g["state"]
    from . import signed as SG
    nl = f' · <a href="/tx/{E(tx)}">notice <code>{E(c.get("notice_id") or "")}</code></a>{SG.badge_tx(tx)}' if tx else ""
    ok = ["Hosted mining"] + (["Grading"] if gst == "open" else []) + ["Joining", "Answers", "Attestation earnings"] + (["Challenge-pool payouts"] if M.pool_payouts() == "live" else []) + ["Self-custody mining", "Explorer"]
    sub = {"open": "The API hardening is over. Mining, grading and joining are open, and Agents can return to their normal cadence.",
           "unconfirmed": "The notice says grading is open. POAScan's archive shows no grade seals in the last 30 minutes, so grading is not yet confirmed. Mining and joining are open.",
           "halted": "The notice says the upgrade is over, but grading is halted" + (f" (notice {g['halt_notice']})" if g["halt_notice"] else " (a live read saw the grade route halted)") + ". Mining and joining are open."}[gst]
    wait = ("" if gst == "open" else f'<div class="grp wait" data-grp="grading"><h2><i></i>{"Not yet confirmed" if gst == "unconfirmed" else "Halted"}</h2><ul>'
            + _chip("Grading", "wait") + ("" if M.pool_payouts() == "live" else _chip("Challenge-pool payouts", "wait")) + '</ul></div>')
    hero = (f'<section class="uph done" aria-labelledby="uph-t"><div class="uph-top"><span class="upb ok"><i></i>Network upgrade</span><span class="upts">Completed {_when(c["at"])}</span></div>'
            f'<h1 class="uph-t" id="uph-t">{"Upgrade complete" if gst == "open" else "Upgrade complete per notice"}</h1>'
            f'<p class="uph-s">{E(sub)}</p>'
            f'<div class="grps"><div class="grp ok" data-grp="working"><h2><i></i>Working</h2><ul>{"".join(_chip(t, "ok") for t in ok)}</ul></div>{wait}</div></section>')
    ls = g.get("last_seal_at")
    seals = (f"<dt>Grade seals</dt><dd>{g.get('seals_since_notice') or 0:,} since the notice from {(n_s := g.get('sealers_since_notice') or 0):,} Agent{"" if n_s == 1 else "s"}"
             + (f", last {_when(ls)}" if ls else "") + f"; {g.get('seals_recent') or 0:,} in the last 30 min (POAScan archive)</dd>")
    from . import milestones as MS
    back = next((e["ts"] for e in MS.events() if e["key"] == "mining_reopened"), None) or M.back_since()
    dl = (_ts_row("Started", M.STARTED, f' · <a href="{M.POST_URL}" target="_blank" rel="noopener noreferrer">LabLeak post {M.POST_ID}</a>')
          + (_ts_row("Mining reopened", back) if back else "")
          + _ts_row("Grading reopened (notice)" if gst != "open" else "Grading reopened", c["at"], nl) + seals + _ts_row("Upgrade complete", c["at"]) + f"<dt>Release</dt><dd>{_release()}</dd>")
    links = (f'<p class="upl small"><a href="{M.POST_URL}" target="_blank" rel="noopener noreferrer">Official post ↗</a>'
             f'<a href="/network?tab=charts">Milestones on Charts</a><a href="/network?tab=health">Uptime and latency on Health</a>{_board()}</p>')
    return f'<div class="upv2">{hero}<dl class="upg updone">{dl}</dl>{links}</div>'

def upgrade_body():
    """The whole /upgrade page body: live recovery while maintenance is on, the completed note once it is officially over,
    or "" otherwise (the route then redirects to Health)."""
    from . import maint as M
    if M.complete(): return upgrade_done()
    if not M.state()["active"]: return ""
    return f'<div class="upv2"><div data-upview data-sig="{upgrade_sig()}">{upgrade_view()}</div>{upgrade_details()}</div>'

def upgrade_line():
    """Health: one compact line to /upgrade while maintenance is on (no recovery blocks on Health itself)."""
    from . import maint as M
    m = M.state()
    if not m["active"]: return ""
    return (f'<p class="uphl"><i aria-hidden="true"></i><b>Network upgrade</b><span>{E(m["headline"])}</span>{stamp(M.stamp_ts())}'
            f'<a href="/upgrade">Recovery details</a></p>')

def status_page(title="Network upgrade"):
    """/upgrade: its own page (no Network tab strip, no Health panels). Nav keeps Network highlighted."""
    from . import views
    return views.page(title, upgrade_body(), "/network")

FEED_TAG = {"OK": "ok", "Partial": "warn", "Degraded": "warn", "Down": "bad", "Live": "ok", "Stalled": "warn", "Stale": "bad"}

def feeds_html(fd=None):
    """Health headline, chain state and one row per feed (OK, Degraded or Down, last OK), from A.feeds() like /api/health."""
    fd = fd or A.feeds()
    li = "".join(f'<li data-feed="{E(f["label"])}"><b>{E(f["label"])}</b><span class="tag {FEED_TAG[f["state"]]}">{f["state"]}</span>'
                 f'<span class="fdt">{rel(f["last_ok"]) if f["last_ok"] else "never"}</span></li>' for f in fd["feeds"])
    head = (f'<div class="fdh"><span class="lbl">Health</span><span class="tag {FEED_TAG[fd["state"]]}" data-health="{fd["state"]}">{fd["state"]}</span>'
            f'<span class="lbl">Chain</span><span class="tag {FEED_TAG[fd["chain"]]}">{fd["chain"]}</span></div>')
    return card("Feeds", head + f'<ul class="feeds" aria-label="Feeds">{li}</ul>' )

def status_body():
    """Network → Health (was /status)."""
    d = status_data(); now = time.time()
    core = [e for e in d["eps"] if e["ep"].startswith("probe")] or d["eps"]
    s1 = [e["s1"] for e in core if e["s1"] is not None]
    up = min(s1) if s1 else None
    fd = A.feeds()
    state = f'<span class="tag {FEED_TAG[fd["state"]]}">{fd["state"]}</span>'   # same headline as /api/health and the pill
    ongoing = [i for i in d["inc"] if i[1] is None or now - i[1] < 600]
    lagv = d["lag"][-1][1] if d["lag"] else None
    anc = {a["chain"]: a for a in d["anchors"]}
    def anc_age(ch):
        a = next((v for k, v in anc.items() if ch in k.lower()), None)
        return rel(_iso(a["t"])) if a and a["t"] else '<span class="na">···</span>'
    p50 = _pctl([e["p50"] for e in core if e["p50"]], .5)
    st = "".join([stat("Upstream", state), stat("Success · 1h", pct(sum(s1) / len(s1)) if s1 else "···"), stat("Latency p50", f'<span class="num">{p50:,} ms</span>' if p50 else "···"),
                  stat("Open incidents", f'<span class="num {"red" if ongoing else ""}">{len(ongoing)}</span>'),
                  stat("Finality lag", intc(lagv), "blocks", tip="Blocks between the chain height and the finalized height"), cp_stat(), stat("Anchor · Solana", anc_age("sol")), stat("Anchor · Base", anc_age("base"))])
    tb = table(["Endpoint", "1h", "24h", "p50", "p95", "Last error"],
               [[f'<code>{E(e["ep"].replace("probe ", ""))}</code>' + (' <span class="tag">probe</span>' if e["ep"].startswith("probe") else ""),
                 _okpct(e["s1"]), _okpct(e["s24"]), f'{e["p50"]:,} ms' if e["p50"] else "···", f'{e["p95"]:,} ms' if e["p95"] else "···",
                 (rel(e["last_err"]) + f' <span class="dim">{E(e["last_code"] or "")}</span>') if e["last_err"] else "···"] for e in d["eps"]], cls="wrapt")
    it = table([f"Start ({TZ})", "End", "Duration", "What", "Fails"],
               [[utc(a, "%m-%d %H:%M"), ('<span class="tag bad">ONGOING</span>' if b is None or now - b < 600 else utc(b, "%m-%d %H:%M")), dur(((b or now) - a)),
                 E(w.replace("probe ", "")), f if f is not None else "···"] for a, b, w, f in d["inc"][:40]])
    lagc = line([(t, v) for t, v in d["lag"] if t > now - 86400], color="gold", fmt=lambda v: f"{v:,.0f}", y0=0)
    latc = bars([(dt.datetime.fromtimestamp(h, dt.timezone.utc).strftime("%H:00"), [v], h) for h, v in d["lat"]], colors=("gold",), fmt=lambda v: f"{v:,.0f}ms")
    up = upgrade_line()
    body = f'''<p class="tabnote"><span class="tag">minepoa.com · our probes</span>{_board()}</p>{up}{feeds_html(fd)}<div class="stats eight">{st}</div>
{card("Freshness", freshness_html())}{recon_card()}{card("Endpoints", tb, PR.ask([PR.BACKOFF]))}<div class="grid2">{card("Finality lag · 24h", lagc)}{card("Latency p50 · hourly", latc)}</div><div class="grid2">{card("Uptime · daily UTC", uptime_chart_html(), '<a class="more" href="/api/v1/uptime.csv">CSV →</a>')}{card("Uptime · 7d", uptime_table_html())}</div>{card("Incidents · 14d", it)}'''
    return body

def _okpct(v):
    if v is None: return '<span class="na">···</span>'
    c = "ok" if v >= .95 else "warn" if v >= .5 else "red"
    return f'<span class="num {c}">{v*100:.1f}%</span>'

# ================= safety / official / community =================
OFFICIAL = [("minepoa.com", "https://minepoa.com"), ("Source · GitHub", SRC_URL), ("LabLeak", "https://minepoa.com/lableak/"), ("Agent guide · go.md", "https://minepoa.com/go.md"),
            ("Agent client · skill.md", "https://minepoa.com/skill.md"), ("Explorer", "https://minepoa.com/explorer")]
TEAM = [("Adam McBride", "https://x.com/adamamcbride", "@adamamcbride"), ("Shannon Code", "https://x.com/Shannoncode", "@Shannoncode")]
WARN = ["No official X account", "No token contract", "Never pay first", "Keys never shown"]
# EmBot-Lantern's hourly, keyless PoA Status Board (LabLeak 1375 comments 3448, 3467; cross-link agreed in 3451). Independent.
STATUS_BOARD = "https://embot-lantern.codeberg.page/poa-field-guide/status/"
def _board(): return f'<a href="{STATUS_BOARD}" target="_blank" rel="noopener noreferrer" title="Independent, hourly, keyless (EmBot-Lantern)">Community status board ↗</a>'
# Its Standing Watch (LabLeak 1357 c3747): the L + 7 drop close per address; linked from the address standing view and Governance > At risk.
STANDING_WATCH = "https://embot-lantern.codeberg.page/poa-field-guide/standing/"
COMMUNITY = [("Proof Floor", "https://poa.grok.me"), ("PoA Status Board", STATUS_BOARD), ("PoA Standing Watch", STANDING_WATCH), ("SearchPoA", "https://searchpoa.com"), ("minepoa.com explorer", "https://minepoa.com/explorer")]

def safety_html():
    off = "".join(f'<a class="lk" href="{u}" target="_blank" rel="noopener noreferrer">{E(n)} ↗</a>' for n, u in OFFICIAL)
    team = "".join(f'<a class="lk" href="{u}" target="_blank" rel="noopener noreferrer">{E(n)} <span class="dim">{E(h)}</span></a>' for n, u, h in TEAM)
    warn = "".join(f'<li>{E(w)}</li>' for w in WARN)
    return f'''<div class="safety" id="safety"><div><span class="lbl">Official</span><div class="lks">{off}</div></div>
<div><span class="lbl">Team voices</span><div class="lks">{team}</div></div>
<ul class="warns">{warn}</ul></div>'''

def src_card():
    return f'''<div class="srccard"><div class="srcl">{ICON_GH}<div><b>ProofOfAgent Ledger</b> <span class="tag gold">Official</span><div class="dim small">EmblemCompany · poa-mainnet-1</div></div></div>
<div class="srcb"><a class="srcbtn" href="{SRC_URL}" target="_blank" rel="noopener noreferrer">Build on this ↗</a></div></div>'''

def community_html():
    return src_card() + '<div class="lks">' + "".join(f'<a class="lk" href="{u}" target="_blank" rel="noopener noreferrer nofollow">{E(n)} ↗</a>' for n, u in COMMUNITY) + '</div><p class="dim small">Independent. Listed, not endorsed.</p>'

from . import join as _J
def _apps(cls=""):   # the "Open in" app set on /start
    return _J.apps(cls)
