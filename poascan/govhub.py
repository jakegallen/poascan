"""Governance hub (consolidation step 4): one hero and one module for what were 17 tabs.

Hero: the Established ring, the Added and removed per close chart, and six KPI cards.
Module: Standing, Closes, Payouts, Graders, Proposals and Rules as tabs (kit.tabmod). Each tab and each chip inside a tab is its own URL;
the old /governance?tab= links open the right place (established, at-risk, queue, directory and never land on Standing; settlement, changes,
intake, settleage and charts on Closes; forum and protocol on Proposals). Every list shows 20 rows and pages by offset.
One word once per screen (Jake's standing order): a state is a coloured dot whose chip carries the word, an epoch number is shown once.
Data: standing rows and counts come from governance.standing_rows (in process); the Moves chip reads Build's 5b/5c rows through
governance.api_standing_moves, the same data as /api/v1/governance/standing-moves (limit 20, offset paging)."""
import os, json, time
from . import closepause as CPZ
from html import escape as E
from . import db, analytics as A, kit as KIT, segments as SG, standing as SD, calibration as CA, governance as GOV, govv2 as GV2, grading as GR, gradingview as GVW, scoresort as SS
from .ui import *
from . import ui as _ui

PAGE = 20
TABS = [("standing", "/governance", "Standing"), ("closes", "/governance?tab=closes", "Closes"), ("payouts", "/governance?tab=payouts", "Payouts"),
        ("graders", "/governance?tab=graders", "Graders"), ("proposals", "/governance?tab=proposals", "Proposals"), ("rules", "/governance?tab=rules", "Rules")]
ALIAS = {"": "standing", "overview": "standing", "established": "standing", "at-risk": "standing", "queue": "graders", "directory": "standing", "never": "standing",
         "settlement": "closes", "changes": "closes", "intake": "closes", "settleage": "closes", "charts": "closes", "forum": "proposals", "protocol": "proposals"}
SUBTAB = {"settlement": "settlement", "changes": "changes", "intake": "intake", "settleage": "settleage"}
LEVEL_CLS = {"risk": "bad", "watch": "warn", "safe": "ok", "norecord": "nd", "system": "nd"}
HEAD = '<link rel="stylesheet" href="/static/gov.css?v={}"><script src="/static/gov.js?v={}" defer></script>'

def _asset_v(name):
    import hashlib
    try: return hashlib.sha256(open(os.path.join(os.path.dirname(__file__), "..", "static", name), "rb").read()).hexdigest()[:10]
    except OSError: return "0"

def _q(qs, k, d=""): return ((qs or {}).get(k) or [d])[0]

def _off(qs):
    try: return max(0, int(_q(qs, "offset", "0")))
    except ValueError: return 0

def sub_chips(items, cur, label):
    return (f'<nav class="chips kit-sub scroll" aria-label="{E(label)}">' + "".join(
        f'<a href="{h}" class="chip {"on" if k == cur else ""}" data-kit-sub="{E(k)}"{" aria-current=\"page\"" if k == cur else ""}>{t}</a>' for k, h, t in items) + "</nav>")

def pager(total, off, url):
    """Offset paging, 20 rows: Prev and Next, and where you are. url(offset) builds the link."""
    if total <= PAGE: return ""
    prev = f'<a class="chip" href="{url(max(0, off - PAGE))}" data-kit-sub="p{max(0, off - PAGE)}">Prev</a>' if off > 0 else ""
    nxt = f'<a class="chip" href="{url(off + PAGE)}" data-kit-sub="p{off + PAGE}">Next</a>' if off + PAGE < total else ""
    return f'<div class="chips pager2 gpager">{prev}<span class="dim small num">{off + 1:,} to {min(total, off + PAGE):,} of {total:,}</span>{nxt}</div>'

def dot(level, word=None):
    w = word or dict(GOV.LEVELS).get(level, level)
    return f'<i class="sd {LEVEL_CLS.get(level, "nd")}" role="img" aria-label="{E(w)}" title="{E(w)}"></i>'

# ---------------- Build's 5b contract (moves) ----------------
def moves(limit=20, offset=0):
    """Changed standing rows from Build's 5b/5c data (governance.api_standing_moves, the same rows as /api/v1/governance/standing-moves):
    {rows:[{address, name, level watch|at_risk|removed, left, close}], total}, off safe, biggest change first."""
    try: return GOV.api_standing_moves(limit, offset)
    except Exception: return None

# ---------------- hero ----------------
def _day(ts):
    import datetime as dt
    d = dt.datetime.fromtimestamp(int(ts or 0), dt.timezone.utc); return d.strftime("%b ") + str(d.day)

def ring(est, safe):
    f = min(1.0, max(0.0, safe / est)) if est else 0
    tk = ('<circle class="mk2" cx="120" cy="120" r="111" pathLength="96" stroke-dasharray=".25 1.75"/>'
          '<circle class="hk" cx="120" cy="120" r="112.5" pathLength="96" stroke-dasharray=".5 15.5" stroke-dashoffset=".25"/>')
    return (f'<div class="ring hring ering gring" style="--f:{f:.4f}"><svg viewBox="0 0 240 240" aria-hidden="true"><circle class="rt" cx="120" cy="120" r="104"/>'
            f'<circle class="rp" cx="120" cy="120" r="104" pathLength="100" stroke-dasharray="{f * 100:.2f} 100"/>{tk}</svg>'
            f'<i class="rhd" aria-hidden="true"><i></i></i><i class="rpl" aria-hidden="true"></i><i class="rpl r2" aria-hidden="true"></i>'
            f'<div class="rc"><span class="lbl">Established</span><b class="bn num" data-cu="{int(est)}">{intc(est)}</b></div></div>')

def hero():
    d = GOV.standing_rows(); c = d["counts"]; est = len(d["rows"]); ep = A.epoch_rows(); last = ep[-1] if ep else {}
    ch = GV2.standing_changes()
    chart = bars([(_day(r["close_ts"]), [r["added"], r["removed"]]) for r in ch[-60:]], height=170, colors=("verd", "ember"), fmt=lambda z: f"{z:,.0f}", legend=["Added", "Removed"], stacked=False) if ch else na("No close record yet.")
    try: cd = int((A.open_epoch() or {}).get("closing_in") or 0)
    except Exception: cd = 0
    closing = f'<span class="lbl">Closes in</span><b class="num gcd" data-left="{cd}" data-at="{int(time.time())}">{dur(cd) if cd > 0 else "···"}</b>' if cd > 0 else ""
    bench = (f'<div class="bench gbench"><div class="bl">{ring(est, c["safe"])}</div>'
             f'<div class="br"><div class="bh"><i class="ldot" aria-hidden="true"></i><span class="lbl on">Live</span><span class="lbl">Per close</span><span class="gcl">{closing}</span></div>{chart}</div></div>')
    cal = CA.calibration(); pe = None
    sk = lambda k: [(r["close_ts"], r.get(k) or 0) for r in ep[-24:] if r.get("close_ts")] or None
    net = (ch[-1]["net"] if ch else None)
    cards = [KIT.kpi("Last paid", intc(last.get("paid")), sk("paid")),
             KIT.kpi("Eligible", intc(last.get("challenge_eligible")), sk("challenge_eligible")),
             KIT.kpi("Median", f'<span class="num">{compact(last["median"])}</span>' if last.get("median") else "···", sk("median"), tip="Median reward per Agent at the last paid close"),
             KIT.kpi("Burned", f'<span class="num red">{float(last.get("burn_pct") or 0):.1f}%</span>', sk("burn_pct")),
             KIT.kpi("Agreement", pct(cal.get("aligned_rate")) if cal.get("aligned_rate") is not None else "···", tip="Jury seats that agreed with the settled outcome"),
             KIT.kpi("Net", f'<span class="num">{net:+,}</span>' if net is not None else "···", [(r["close_ts"], r["net"]) for r in ch[-24:] if r.get("close_ts")] or None, tip="Established Agents added minus removed at the last close")]
    strip = f'<section class="stats four kpis six" role="group" aria-label="Headline numbers">{"".join(cards)}</section>'
    return f'<section id="tracker" class="card benchc hpulse govhero" aria-label="Governance">{bench}{strip}</section>'

# ---------------- Standing ----------------
LV_CHIPS = [("", "All"), ("safe", "Safe"), ("watch", "Watch"), ("risk", "At risk"), ("never", "Never established"), ("directory", "Directory")]
DIR_COLS = [("name", "Agent", ""), ("score", "Score", "r"), ("rewards", "Rewards", "r"), ("seals", "Seals", "r dk")]

def standing_body(qs):
    d = GOV.standing_rows(); c = d["counts"]; lv = _q(qs, "level"); lv = lv if lv in ("safe", "watch", "risk", "never", "directory") else ""
    if _q(qs, "tab") == "directory" and not lv: lv = "directory"
    if _q(qs, "tab") == "at-risk" and not lv: lv = "risk"
    if _q(qs, "tab") == "never" and not lv: lv = "never"
    off = _off(qs)
    def u(**o):
        p = dict(tab="standing", level=lv, sort=_q(qs, "sort"), dir=_q(qs, "dir")); p.update(o)
        q = [f"{k}={v}" for k, v in p.items() if v and not (k == "tab" and v == "standing")]
        return "/governance" + ("?" + "&amp;".join(q) if q else "")
    cnt = {"": len(d["rows"]), "safe": c["safe"], "watch": c["watch"], "risk": c["risk"], "never": None, "directory": None}
    by = _q(qs, "sort"); by = by if by in dict((k, 0) for k, _, _ in DIR_COLS) else "rewards"; dr = "asc" if _q(qs, "dir") == "asc" else "desc"
    if lv == "directory":
        drows = GOV.directory_rows(); cnt["directory"] = len(drows)
        rows = GOV.directory_select(by, "", dr); total = len(rows); sel = rows[off:off + PAGE]
        def th(k, t, c):
            nd = "asc" if (by == k and dr == "desc") else "desc"
            if k == "name" and by != "name": nd = "asc"
            return (f'<th class="{c}"><a class="srt{" cur " + dr if by == k else ""}" href="{u(sort=k, dir=nd, offset="")}" data-kit-sub="s{k}{nd}">{t}</a></th>')
        tb = ('<div class="tw"><table class="hist cal gtbl"><thead><tr>' + "".join(th(*x) for x in DIR_COLS) + "</tr></thead><tbody>"
              + "".join(f'<tr><td>{agent(r["address"], r.get("name") or "")}</td><td class="r">{GOV._score_cell(r.get("score"))}</td><td class="r">{compact(r["rewards"]) if r["rewards"] else "<span class=dim>···</span>"}</td>'
                        f'<td class="r dk">{intc(r["seals"]) if r["seals"] else "<span class=dim>···</span>"}</td></tr>' for r in sel) + "</tbody></table></div>")
    elif lv == "never":
        rows = GV2.never_established(); total = len(rows)
        sel = rows[off:off + PAGE]
        tb = table(["Agent", "Answers"], [[agent(r["address"], r.get("name") or ""), intc(r["answers"])] for r in sel], cls="gtbl")
    else:
        rows = [r for r in d["rows"] if not lv or r["level"] == lv]; total = len(rows)
        rows.sort(key=lambda r: ((r["left"] if r["left"] is not None else 1 << 30), (r["name"] or "~").lower())) if lv else None
        sc = GOV.scores()["rows"]; sel = rows[off:off + PAGE]
        tb = table(["Agent", "Score", "Level", "Left"], [[GOV._agent(r, True), GOV._score_cell(GOV.parts_of(r["address"], sc).get("score")), dot(r["level"]),
                                                        intc(r["left"]) if r["left"] is not None else "···"] for r in sel], cls="gtbl")
    chips = sub_chips([(k, u(level=k, offset="", sort="", dir=""), (f'<i class="sd {LEVEL_CLS.get(k, "")}" aria-hidden="true"></i>' if k in ("safe", "watch", "risk") else "") + t
                        + (f' <span class="dim">{cnt[k]:,}</span>' if cnt.get(k) is not None else "")) for k, t in LV_CHIPS], lv, "Level")
    return chips + tb + pager(total, off, lambda o: u(offset=str(o) if o else ""))

# ---------------- Closes ----------------
CL_SUBS = [("latest", "/governance?tab=closes", "Latest"), ("changes", "/governance?tab=changes", "Moves"), ("settlement", "/governance?tab=settlement", "Settlement"),
           ("intake", "/governance?tab=intake", "Intake"), ("settleage", "/governance?tab=settleage", "Settle age")]

def moves_body(qs):
    off = _off(qs); m = moves(PAGE, off)
    if not m or not m["rows"]: return na("No standing moves at the last close.")
    lab = {"watch": "Watch", "at_risk": "At risk", "removed": "Removed"}
    cls = {"watch": "warn", "at_risk": "bad", "removed": "nd"}
    dot = lambda k: f'<i class="sd {cls.get(k, "nd")}" role="img" aria-label="{lab.get(k, k)}" title="{lab.get(k, k)}"></i>'
    cell = lambda r: (f'E{r["close"]}' if r["level"] == "removed" and r.get("close") is not None else (intc(r["left"]) if r.get("left") is not None else "···"))
    tb = table(["Agent", "Level", "Closes left"], [[agent(r["address"], r.get("name") or ""), dot(r["level"]), cell(r)] for r in m["rows"]], cls="gtbl")
    return tb + pager(m["total"], off, lambda o: "/governance?tab=changes" + (f"&amp;offset={o}" if o else ""))

def latest_body(qs):
    ep = A.epoch_rows(); off = _off(qs); rows = list(reversed(ep)); total = len(rows)
    sel = rows[off:off + PAGE]
    tb = table(["Close", "Paid", "Per Agent", "Max"], [[f'<a href="/epoch/{r["epoch"]}{SG.qs()}">E{r["epoch"]}</a>{CPZ.tag(r.get("pause"))}', intc(r["paid"]), compact(r["median"]) if r.get("median") else "···", compact(r["max"]) if r.get("max") else "···"] for r in sel], cls="gtbl")
    ch = bars([("", [r["paid"]]) for r in ep[-48:]], height=240, colors=("gold",), fmt=lambda z: f"{z:,.0f}") if ep else na("No close record yet.")
    u = lambda o: "/governance?tab=closes" + (f"&amp;offset={o}" if o else "")
    return KIT.split('<span class="lbl">Closes</span>' + tb + pager(total, off, u), '<span class="lbl">Paid per close</span>' + ch).replace('<span class="lbl">Closes</span>', "", 1)

def settlement_body(qs):
    rows = GV2.settlement_closes(); off = _off(qs); rows = list(reversed(rows)); total = len(rows)
    sel = rows[off:off + PAGE]
    tb = table(["Close", "Settled", "Not paid", "Expired", "Open"], [[f'<a href="/epoch/{r["close"]}{SG.qs()}">E{r["close"]}</a>{CPZ.tag_for(r["close"])}', intc(r["settled"]), intc(r["not_paid"]), intc(r["expired_no_jury"]), intc(r["open"])] for r in sel], cls="gtbl")
    return tb + pager(total, off, lambda o: "/governance?tab=settlement" + (f"&amp;offset={o}" if o else ""))

def closes_body(qs, sub):
    if sub == "changes": inner = moves_body(qs)
    elif sub == "settlement": inner = settlement_body(qs)
    elif sub == "intake": inner = intake_body(qs)
    elif sub == "settleage": inner = settleage_body(qs)
    else: inner = latest_body(qs)
    return sub_chips(CL_SUBS, sub, "Closes") + inner

# ---------------- Payouts, Graders, Proposals, Rules ----------------
def payouts_body(qs):
    pe = GOV.payout_estimate(); o, K, ans = GOV.answered_since_close(); ec = o.get("est_close")
    nxt = f'<time class="t" data-ts="{int(ec)}">~{max(0, int(ec - time.time())) // 3600}h {max(0, int(ec - time.time())) % 3600 // 60}m</time>' if ec else "···"
    fg = KIT.figs([("Next close", nxt), ("Answered", intc(ans["n"]) if ans else "···"), ("K-attested", intc(ans["k"]) if ans else "···"),
                   ("Est. per Agent", f'<span class="num">{compact(pe["estimate"])}</span>' if pe["estimate"] is not None else "···"), ("Pool", compact(o.get("pool")) if o.get("pool") else "···")])
    rows = [[f'<a href="/epoch/{r["epoch"]}{SG.qs(r["segment"])}">E{r["epoch"]}</a>', intc(r["paid"]), compact(r["median"]), compact(r["max"])] for r in pe["basis"]]
    return fg + '<span class="lbl">Basis</span>' + (table(["Close", "Paid", "Per Agent", "Max"], rows, cls="gtbl") if rows else na("No paid closes yet."))

GR_SUBS = [("seals", "/governance?tab=graders", "Seals"), ("queue", "/governance?tab=graders&amp;sub=queue", "Queue")]

def queue_body(qs):
    if SG.archived(): return na("The grading list is the live network's.")
    if GR.is_retired(): return na("minepoa retired its grading list.")
    if not GR.usable(): return na("The grading list has not been read yet.")
    s = GR.summary(); off = _off(qs); rows = GVW.queue_select("", "need", "desc"); total = len(rows); sel = rows[off:off + PAGE]; qn = s["quorum"]
    fg = KIT.figs([("Pending", intc(s["pending"]) + GVW.stale_flag()), ("Ready", intc(s["ready_next_close"])), ("Carried", intc(s["at_quorum_queued"])),
                   ("Trusted", pct(s["trusted_share"]) if s.get("trusted_share") is not None else "···")])
    dim = '<span class="dim">···</span>'
    tb = table(["Answer", "Quorum", "Age", "Expires"], [[GVW.ans_link(r["id"]), GVW.qprog(r, qn), intc(r["age"]) if r.get("age") is not None else dim,
                                                        intc(r["expires_in"]) if r.get("expires_in") is not None else dim] for r in sel], cls="gtbl gq") if sel else na("No answers pending.")
    return fg + tb + pager(total, off, lambda o: "/governance?tab=graders&amp;sub=queue" + (f"&amp;offset={o}" if o else ""))

def graders_body(qs):
    sub = "queue" if (_q(qs, "sub") == "queue" or _q(qs, "tab") == "queue") else "seals"
    return sub_chips(GR_SUBS, sub, "Graders") + (queue_body(qs) if sub == "queue" else seals_body(qs))

def seals_body(qs):
    js = GOV.jury_series(); t, rows = GOV.seals_select("seals", "desc"); nm = A.forum_names(); exact = GR.usable()
    gs = GR.summary() if exact else None; last = js[-1] if js else None
    ns = sum(r["seals"] for r in rows)
    fg = KIT.figs([("Active", intc(len(rows))), ("Sealed", intc(ns)), ("Pending", intc(gs["pending"]) if gs else (intc(last["queue"]) if last else "···")),
                   ("Counting", pct(sum(r.get("counting", 0) for r in rows) / ns) if (exact and ns) else "···")])
    seats = sum(x["aligned"] + x["other"] for x in js)
    ch = bars([("", [x["aligned"], x["other"]]) for x in js[-48:]], height=200, colors=("verd", "ember"), fmt=lambda v: f"{v:,.0f}", legend=["Aligned", "Not aligned"]) if seats else na("No settled jury seats yet.")
    off = _off(qs); sel = rows[off:off + PAGE]
    tb = table(["Agent", "Count", "Score"], [[agent(r["address"], nm.get(r["address"]) or ""), intc(r["seals"]), GOV._score_cell(r.get("score"))] for r in sel], cls="gtbl") if rows else na("No seals since the last close.")
    return fg + KIT.split('<span class="lbl">Jury</span>' + ch, tb + pager(len(rows), off, lambda o: "/governance?tab=graders" + (f"&amp;offset={o}" if o else "")))

def intake_body(qs):
    from . import intake as IK
    cs = [c for c in IK.closes() if c["eligible"] or c["admitted"]]; off = _off(qs); rows = list(reversed(cs)); sel = rows[off:off + PAGE]
    if not cs: return na("No intake at any close yet.")
    tb = table(["Close", "Candidates", "Cap", "Change"], [[f'<a href="/epoch/{r["close"]}{SG.qs()}">E{r["close"]}</a>{CPZ.tag_for(r["close"])}', intc(r["eligible"]), intc(r["cap"]), f'{r["net"]:+,}'] for r in sel], cls="gtbl")
    ch = bars([("", [r["admitted"], r["not_admitted"]]) for r in cs[-48:]], height=240, colors=("verd", "gold"), fmt=lambda z: f"{z:,.0f}", legend=["Admitted", "Waiting"])
    fl = KIT.figs([("Proposal L params", "Set" if IK.propl_state()["present"] else "Not set")])   # the Set flag stays (1.26.110 intake contract)
    return fl + KIT.split(tb + pager(len(rows), off, lambda o: "/governance?tab=intake" + (f"&amp;offset={o}" if o else "")), ch)

def settleage_body(qs):
    from . import settleage as SA
    d = SA.distribution()
    if not d["closes"]: return na("No settled answer in this segment yet.")
    fg = KIT.figs([("Settled", intc(d["settled"])), ("Median age", SA._med(d["median"])), ("Expired", intc(d["expired"])), ("Unknown", intc(d["unknown"]))])
    rows = SA._rows(d)
    top = max([r["answers"] for r in rows] or [1]) or 1
    tb = table(["Age", "Answers", ""], [[E(str(r["band"])), intc(r["answers"]), f'<span class="gbar" style="--w:{100 * r["answers"] / top:.1f}%"></span>'] for r in rows], cls="gtbl")
    return fg + tb

PR_SUBS = [("posts", "/governance?tab=proposals", "Posts"), ("ballots", "/governance?tab=proposals&amp;sub=ballots", "Ballots"), ("protocol", "/governance?tab=protocol", "Protocol")]

def dot_(cls, word): return f'<i class="sd {cls}" role="img" aria-label="{word}" title="{word}"></i> '

def protocol_body(qs):
    """Protocol timeline as a Proposals chip: stats, kind chips, header sort, 20 rows by offset (the CSV and API stay at /api/v1/protocol)."""
    from . import protocolview as PV
    off = _off(qs); k = _q(qs, "kind"); by = PV.SS.page_sort(qs, dict(PV.SORTS), "when"); d = PV.SS.page_dir(qs)
    total = len(PV.select(k if k in dict(PV.FILTERS) else "", by, d))
    q = lambda o: GOV.href("protocol", **dict(sort=by if by != "when" else "", dir="asc" if d == "asc" else "", kind=k, offset=str(o) if o else ""))
    return sub_chips(PR_SUBS, "protocol", "Proposals") + PV.tab(qs, GOV.href, GOV.qsx, n=PAGE, off=off, links=False) + pager(total, off, lambda o: q(o))

def proposals_body(qs):
    if _q(qs, "sub") == "protocol" or _q(qs, "tab") == "protocol": return protocol_body(qs)
    rows, live = GOV.proposals_data(); sub = "ballots" if _q(qs, "sub") == "ballots" else "posts"
    if sub == "ballots":
        bl = [[E(b["name"]), (GOV.lt(GOV._iso(b["ends"])) if GOV._iso(b["ends"]) else E(b["ends"][5:16].replace("T", " "))),
               (GOV._post(b["voting_post"], "Tally not public") if b["tally"] is None else E(b["tally"]) + GOV._effect(b))] for b in GOV.BALLOTS]
        bl += [[E(str(b.get("name") or b.get("id") or b.get("ballot_id") or "")[:24]), E(str(b.get("status") or "open")), "Open"] for b in live]
        inner = table(["Ballot", "Ended", "Tally"], bl, cls="gtbl")
    else:
        off = _off(qs); sel = rows[off:off + PAGE]
        mark = lambda r: (dot_("ok", "Ballot") if r["status"] == "ballot" else dot_("warn", "Discussion") if r["status"] == "discussion" else "")
        inner = table(["Post", "Title", "Comments", "Posted"], [[GOV._post(r["id"]), mark(r) + E(GOV._nodash(r["title"])[:80]), intc(r["comment_count"]), E(str(r["created_at"] or "")[:10])] for r in sel], cls="gtbl") \
            + pager(len(rows), off, lambda o: "/governance?tab=proposals" + (f"&amp;offset={o}" if o else ""))
    return sub_chips(PR_SUBS, sub, "Proposals") + inner

def _nosrc(h):
    import re
    GO, SK = GOV.GO, GOV.SK
    h = re.sub(r" \((?:%s|%s)(?:[;,] (?:%s|%s))*\)" % (re.escape(GO), re.escape(SK), re.escape(GO), re.escape(SK)), "", h)
    return h.replace("(" + GO + ", ", "(").replace("(" + GO + "; ", "(").replace("; " + SK + ")", ")")

def rules_body(qs):
    GOV._COLLECT.rows = []
    try: GOV.rules(); rows = GOV._COLLECT.rows
    finally: GOV._COLLECT.rows = None
    th = f'<div class="grule head"><span class="lbl">Docs {GOV.GO} {GOV.SK}</span><span class="lbl">Observed</span></div>'
    li = "".join(f'<section class="grule" id="{E(i)}"><h3>{E(t)}</h3><div>{_nosrc(d)}</div><div>{o}</div></section>' for i, t, d, o in rows)
    return f'<div class="grules">{th}{li}</div>'

# ---------------- page ----------------
def module(tab, sub, qs):
    if tab == "closes": body = closes_body(qs, sub)
    elif tab == "payouts": body = payouts_body(qs)
    elif tab == "graders": body = graders_body(qs)
    elif tab == "proposals": body = proposals_body(qs)
    elif tab == "rules": body = rules_body(qs)
    else: body = standing_body(qs)
    return KIT.tabmod([(k, h, t, None) for k, h, t in TABS], tab, body, "", id="govmod", label="Governance")

def page(qs):
    qs = qs or {}; raw = _q(qs, "tab"); tab = GOV.ALIAS_TAB.get(raw, raw) if hasattr(GOV, "ALIAS_TAB") else raw
    sub = SUBTAB.get(raw, "latest"); tab = ALIAS.get(raw, raw); tab = tab if tab in dict((k, 0) for k, _, _ in TABS) else "standing"
    body = f'<div class="sechead"><h1 class="sr-only">Governance</h1></div>{hero()}{module(tab, sub, qs)}'
    title = {"standing": "Governance", "closes": "Governance closes", "payouts": "Governance payouts", "graders": "Governance graders", "proposals": "Governance proposals", "rules": "Governance rules"}[tab]
    from . import views as V
    return V.page(title, body, "/governance", head=HEAD.format(_asset_v("gov.css"), _asset_v("gov.js")))
