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
    return bars([(k[5:], [v[1] / v[0] * 100 if v[0] else 0]) for k, v in days.items()], height=150, colors=("#3DDC97",), fmt=lambda v: f"{v:.0f}%", ymax=100)

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
    anc = db.q("SELECT chain, MAX(anchored_at) AS t, MAX(height) AS h FROM anchors GROUP BY chain")
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
    flag = ('<div class="asof steel">Parked</div>' if f["maintenance"] else f'<div class="asof amber">Stalled</div>' if f["checkpoint_stalled"] else "")
    return f'<div class="stat"><div class="sl"><span title="When the finalized height (checkpoint) last moved">Finality moved</span></div><div class="sv">{rel(f["checkpoint_moved"])}</div>{flag}</div>'

RECON_TAG = {"match": ("ok", "Match"), "explained": ("", "Explained"), "differs": ("bad", "Differs"), "node_only": ("", "Node only"), "poascan_only": ("", "Ours only")}

def recon_card():
    from . import reconcile as RE
    from .views import rel_t
    d = RE.reconcile()
    def v(x, unit, at):
        if x is None: return '<span class="na">···</span>'
        n = num(x, 2) if unit == "poa" else intc(x)
        return f'{n}<small title="read {dt.datetime.fromtimestamp(int(at), dt.timezone.utc):%Y-%m-%d %H:%M} UTC">{rel_t(at)}</small>' if at else n
    def tag(st): c, t = RECON_TAG[st]; return f'<span class="tag {c}">{t}</span>'
    def sub(r):
        dv = None if r["diff"] in (None, 0) else (f'Δ {"+" if r["diff"] > 0 else "-"}{compact(abs(r["diff"]), 2)}' if r["unit"] == "poa" else f'Δ {r["diff"]:+,}')
        t = " · ".join(E(x) for x in (dv, r["reason"]) if x)
        return f'<tr class="rwhy"><td colspan="4">{t}</td></tr>' if t else ""
    trs = "".join(f'<tr class="{"rx" if sub(r) else ""}"><td><b>{E(r["label"])}</b></td><td class="r">{v(r["poascan"], r["unit"], r["poascan_as_of"])}</td>'
                  f'<td class="r">{v(r["node"], r["unit"], r["node_as_of"])}</td><td class="r">{tag(r["state"])}</td></tr>' + sub(r) for r in d["rows"])
    tb = f'<div class="tw"><table class="hist rec"><thead><tr><th>Figure</th><th class="r">POAScan</th><th class="r">Node</th><th class="r">State</th></tr></thead><tbody>{trs}</tbody></table></div>'
    pc = [p for p in d["per_close"] if p["state"] != "no_reads"]
    pt = "".join(f'<tr><td><a class="mono" href="/epoch/{p["epoch"]}">E{p["epoch"]}</a></td><td class="r">{num(p["record_mint"], 2)}</td><td class="r">{num(p["supply_step"], 2)}</td><td class="r">{tag(p["state"])}</td></tr>' for p in pc)
    per = (f'<h3 class="rech">Mint per close</h3><div class="tw"><table class="hist rec"><thead><tr><th>Close</th><th class="r">Record</th><th class="r">Supply step</th><th class="r">State</th></tr></thead><tbody>{pt}</tbody></table></div>') if pc else ""
    foot = f'<p class="cov dim small">{d["matched"]} match · {d["explained"]} explained · {d["differs"]} differ · <a href="/about#reconcile">method</a></p>'
    return card("Reconciliation", tb + per + foot, '<a class="more" href="/api/v1/reconcile">API →</a>', cls="histc", id="reconcile")

def upgrade_card():
    """/status#upgrade: the staged maintenance in one card, shown only while maint.state() is active."""
    from . import maint as M
    m = M.state()
    if not m["active"]: return ""
    sn = M.seen(); lo, hi = m["expected_window_h"]
    from . import halts as H
    hs = H.current(); sf = (hs or {}).get("groups") or {}; jo = M.join_open(); jd = M.join_state() == "delayed"
    if sf:   # tracker-derived: one row per state, groups in a fixed order
        rows = [(lab, ", ".join(g for g in H.GROUPS if sf.get(g) == k and not (jd and g == "Joining"))) for lab, k in (("Paused", "paused"), ("Planned", "planned"), ("Back", "back"))]
        rows = [r for r in rows if r[1]]
    else:
        rows = [("Paused", "Hosted mining, grading" + ("" if jo else ", joining") + ".")]
    if jd: rows.append(("Delayed", "Joining."))   # derived: no new join on the ledger for 90 minutes; clears on the next one
    jw = jo and not jd and "Joining" not in sf
    rows += [("Working", ("Joining, " if jw else "") + 'self-custody (<code>POST /api/submit</code> plus <code>/api/receipt</code>), epoch closes, reward payouts, balances, <a href="/txs">explorer</a>.'),
            ("Safe", f'About {lo} to {hi} hours. Pending grades keep {m["pending_ttl_epochs"]} epochs. Finalized height {m["parked_checkpoint"]:,} is parked by design.'),
            ("Agents", "Check hourly at a random minute. Back off 30s, 2m, 10m. After a 502, read the receipt before resubmitting. Watch <code>system_notice</code>."),
            ("Last hour", f'<span class="num">{sn["answers"]:,}</span> {"answer" if sn["answers"] == 1 else "answers"} · <span class="num">{sn["seals"]:,}</span> {"seal" if sn["seals"] == 1 else "seals"} landed')]
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    box = (f'<div class="upa" data-pcard><span class="lbl jm-l">Ask agent</span>'
           + _J.pbox(f'<pre class="pc-text" tabindex="0">{E(PR.UPGRADE[1])}</pre>') + '</div>')
    since = dt.datetime.fromtimestamp(M.STARTED, dt.timezone.utc).strftime("%b %d %H:%M UTC")
    return card("Network upgrade", f'<dl class="upg">{dl}</dl>{box}',
                f'<span class="tag">Since {since}</span><a class="more" href="{m["post_url"]}" target="_blank" rel="noopener">Official post ↗</a>', cls="upc", id="upgrade")

def status_page(title="Network upgrade"):
    """/upgrade serves the Health tab under its own title and preview while the upgrade is on (/status redirects to the tab)."""
    from . import views
    return views.network("health", title=title)

def status_body():
    """Network → Health (was /status)."""
    d = status_data(); now = time.time()
    core = [e for e in d["eps"] if e["ep"].startswith("probe")] or d["eps"]
    s1 = [e["s1"] for e in core if e["s1"] is not None]
    up = min(s1) if s1 else None
    state = ('<span class="tag ok">OPERATIONAL</span>' if up is not None and up >= .95 else '<span class="tag warn">DEGRADED</span>' if up is not None and up >= .5 else '<span class="tag bad">DOWN</span>' if up is not None else "···")
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
    it = table(["Start (UTC)", "End", "Duration", "What", "Fails"],
               [[utc(a, "%m-%d %H:%M"), ('<span class="tag bad">ONGOING</span>' if b is None or now - b < 600 else utc(b, "%m-%d %H:%M")), dur(((b or now) - a)),
                 E(w.replace("probe ", "")), f if f is not None else "···"] for a, b, w, f in d["inc"][:40]])
    lagc = line([(t, v) for t, v in d["lag"] if t > now - 86400], color="#8FA3B8", fmt=lambda v: f"{v:,.0f}", y0=0)
    latc = bars([(dt.datetime.fromtimestamp(h, dt.timezone.utc).strftime("%H"), [v]) for h, v in d["lat"]], colors=("#E3A33A",), fmt=lambda v: f"{v:,.0f}ms")
    up = upgrade_card()
    body = f'''<p class="tabnote"><span class="tag">minepoa.com · our probes</span></p>{up}<div class="stats eight">{st}</div>
{card("Freshness", freshness_html())}{recon_card()}{card("Endpoints", tb, "" if up else PR.ask([PR.BACKOFF]))}<div class="grid2">{card("Finality lag · 24h", lagc)}{card("Latency p50 · hourly UTC", latc)}</div><div class="grid2">{card("Uptime · daily UTC", uptime_chart_html(), '<a class="more" href="/api/v1/uptime.csv">CSV →</a>')}{card("Uptime · 7d", uptime_table_html())}</div>{card("Incidents · 14d", it)}'''
    return body

def _okpct(v):
    if v is None: return '<span class="na">···</span>'
    c = "ok" if v >= .95 else "warn" if v >= .5 else "red"
    return f'<span class="num {c}">{v*100:.1f}%</span>'

# ================= is it real? =================
def real_card():
    est = len(A.established_set()); op = G.operators(); sy = A.sybil()
    acc = op["accounts"]; fam = op["families"]
    inv = sy["invited"]; k = sy["inviter_count"] or 0
    top5 = sum(x["n"] for x in sy["inviters"])
    s = "".join([stat("Established", intc(est)), stat("Est. operators", intc(fam)), stat("Agents / operator", f'<span class="num">{acc/max(1,fam):.2f}</span>'),
                 stat("Invite fan-out", f'<span class="num">{(inv/k if k else 0):.1f}</span>'), stat("Invited", pct(inv / acc) if acc else "···"), stat("Top-5 inviters", pct(top5 / inv) if inv else "···")])
    return card(ICON_SEAL + "Is it real?", f'<div class="stats six real">{s}</div>', '<a class="more" href="/about#real">Method →</a>')

# ================= safety / official / community =================
OFFICIAL = [("minepoa.com", "https://minepoa.com"), ("Source · GitHub", SRC_URL), ("LabLeak", "https://minepoa.com/lableak/"), ("Agent guide · go.md", "https://minepoa.com/go.md"),
            ("Agent client · skill.md", "https://minepoa.com/skill.md"), ("Explorer", "https://minepoa.com/explorer")]
TEAM = [("Adam McBride", "https://x.com/adamamcbride", "@adamamcbride"), ("Shannon Code", "https://x.com/Shannoncode", "@Shannoncode")]
WARN = ["No official X account", "No token contract", "Never pay first", "Keys never shown"]
COMMUNITY = [("Proof Floor", "https://poa.grok.me"), ("SearchPoA", "https://searchpoa.com"), ("minepoa.com explorer", "https://minepoa.com/explorer")]

def safety_html():
    off = "".join(f'<a class="lk" href="{u}" target="_blank" rel="noopener">{E(n)} ↗</a>' for n, u in OFFICIAL)
    team = "".join(f'<a class="lk" href="{u}" target="_blank" rel="noopener">{E(n)} <span class="dim">{E(h)}</span></a>' for n, u, h in TEAM)
    warn = "".join(f'<li>{E(w)}</li>' for w in WARN)
    return f'''<div class="safety" id="safety"><div><span class="lbl">Official</span><div class="lks">{off}</div></div>
<div><span class="lbl">Team voices</span><div class="lks">{team}</div></div>
<ul class="warns">{warn}</ul></div>'''

def src_card():
    return f'''<div class="srccard"><div class="srcl">{ICON_GH}<div><b>ProofOfAgent Ledger</b> <span class="tag gold">Official</span><div class="dim small">EmblemCompany · poa-mainnet-1</div></div></div>
<div class="srcb"><a class="srcbtn" href="{SRC_URL}" target="_blank" rel="noopener">Build on this ↗</a></div></div>'''

def community_html():
    return src_card() + '<div class="lks">' + "".join(f'<a class="lk" href="{u}" target="_blank" rel="noopener nofollow">{E(n)} ↗</a>' for n, u in COMMUNITY) + '</div><p class="dim small">Independent. Listed, not endorsed.</p>'

from . import join as _J
def _apps(auto_first=False, cls=""):   # the "Open in" app set on /start
    return _J.apps(cls)
