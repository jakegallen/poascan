"""Epoch page on the shared kit (audit H4): /epoch/N for a closed epoch is one hero and one tabbed module.

Hero: a finished ring (the epoch number, its close time), the Story chart (answers and grades per hour) and six KPI cards (Pool, Minted, Burned,
Agents paid, Median reward, Settled) each with the last 16 closes as a sparkline. Module: Payouts (20 rows, offset paging, header sort), Record (the close
record as one short table) and Forum (the most replied public threads in the window, only when there are any). Each tab is its own URL
(/epoch/N, ?tab=record, ?tab=forum). No header CSV link: the CSV route stays at /api/v1/epoch/N/rewards.csv. Data is what the page already read."""
import time
from html import escape as E
from . import analytics as A, kit as KIT, segments as SG, closepause as CPZ, marks as MK, market as X, epochstory as EST_, topics as _TOP, scoresort as SS
from .ui import *

PAGE = 20
HEAD = '<link rel="stylesheet" href="/static/epoch.css?v={}">'

def _asset_v(name):
    import hashlib, os
    try: return hashlib.sha256(open(os.path.join(os.path.dirname(__file__), "..", "static", name), "rb").read()).hexdigest()[:10]
    except OSError: return "0"

def _q(qs, k, d=""): return ((qs or {}).get(k) or [d])[0]

def _pager(total, off, url):
    if total <= PAGE: return ""
    prev = f'<a class="chip" href="{url(max(0, off - PAGE))}">Prev</a>' if off > 0 else ""
    nxt = f'<a class="chip" href="{url(off + PAGE)}">Next</a>' if off + PAGE < total else ""
    return f'<div class="chips pager2 gpager">{prev}<span class="dim small num">{off + 1:,} to {min(total, off + PAGE):,} of {total:,}</span>{nxt}</div>'

def _series(rows, n, key, count=16):
    ks = sorted(k for k in rows if k <= n)[-count:]
    return [(rows[k]["close_ts"], rows[k].get(key) or 0) for k in ks if rows[k].get("close_ts")]

def _ring(n, r):
    tk = ('<circle class="mk2" cx="120" cy="120" r="111" pathLength="96" stroke-dasharray=".25 1.75"/>'
          '<circle class="hk" cx="120" cy="120" r="112.5" pathLength="96" stroke-dasharray=".5 15.5" stroke-dashoffset=".25"/>')
    return (f'<div class="ring hring string eclosed" style="--f:1"><svg viewBox="0 0 240 240" aria-hidden="true"><circle class="rt" cx="120" cy="120" r="104"/>'
            f'<circle class="rp" cx="120" cy="120" r="104" pathLength="100" stroke-dasharray="100 100"/>{tk}</svg>'
            f'<div class="rc"><span class="lbl">Epoch</span><b class="bn num">{n}</b><span class="ect">{lt(r["close_ts"], "dt")}</span></div></div>')

def _tags(n, r, arch, zeropay, unc):
    from . import views as V
    t = (f'<a class="tag{" warn" if arch else ""} segt" href="/chain{SG.qs()}">{E(SG.label())}</a>' if SG.has_cut() else "")
    t += '<span class="tag warn" title="Rewards not confirmed in later balances">Unconfirmed</span>' if unc else ""
    t += CPZ.tag(r.get("pause")).strip() + V.nopay_tag(r).strip()
    mk = MK.hall_img(r, 28, "hmark")
    return f'<div class="ests">{mk or ""}{t}</div>' if (t or mk) else ""

def hero(n, r, rows, arch, unc, prev_close, zeropay):
    ch = EST_.chart_html(n, r, prev_close)
    ser = lambda k: _series(rows, n, k)
    top = r.get("max"); same = (top == r["median"])
    kp = "".join([
        KIT.kpi("Pool", f'<span class="num">{compact(r["pool"])}</span>', ser("pool")),
        KIT.kpi("Minted", f'<span class="num">{compact(r["minted"])}</span>', ser("minted")),
        KIT.kpi("Burned", f'<span class="num red" title="{full(r["burned"])} POA">{compact(r["burned"])}</span>', ser("burned"), tip=("No answer reached quorum, nothing was paid" if zeropay else f'{sig3_pct(f"{r["burn_pct"]:.2f}%")} of the pool')),
        KIT.kpi("Agents paid", intc(r["paid"]), ser("paid")),
        KIT.kpi("Median reward" if not same else "Reward", num(r["median"]), ser("median")),
        KIT.kpi("Settled", intc(r["settled"]), ser("settled"), tip="Answers whose grading finished at this close"),
    ])
    bench = (f'<div class="bench ebench"><div class="bl">{_ring(n, r)}{_tags(n, r, arch, zeropay, unc)}</div>'
             f'<div class="br"><div class="bh"><span class="lbl">Hourly</span></div>'
             f'{ch or na("No archived txs for this epoch.")}</div></div>')
    return KIT.pulse(bench, kp, label=f"Epoch {n}", n=6)

def record_body(n, r, e, ch, unp):
    T = lambda label, tip: f'<span title="{E(tip)}">{label}</span>'
    rows = []
    for k, lbl in (("answer_pay", "Answer pay"), ("grading_pay", "Grading pay"), ("referral_pay", "Referral pay")):
        if ch.get(k) is not None: rows.append([lbl, poa(ch[k], mined=True) + X.usd_of(ch[k])])
    if ch.get("state") == "pending": rows.append(["Split", '<span class="tag" title="Answer pay, Grading pay and Referral pay are not in the public close record or close report yet">Pending</span>'])
    if r.get("correction"): rows.append([T("Correction", "Ballot 2464: burned from Agents' locked at this close. Spendable unchanged"), f'<span class="num red" title="{full(r["correction"])} POA">{compact(r["correction"])}</span>'])
    if r["max"] != r["median"]: rows.append([T("Top reward", "Agents paid this close's top reward: " + str(r.get("paid_at_max", 0))), num(r["max"]) + X.usd_of(r["max"])])
    rows += [[T("Paid for answers", "Agents paid for an answer this epoch (others were paid for grading or referrals)"), intc(r["challengers"])],
        [T("Answers eligible", "Answers that met the attestation bar to earn the challenge share"), intc(r["challenge_eligible"])],
        ["Newly established", intc(r["established"])], ["Established removed", intc(r["established_removed"])],
        [T("Passed / failed / expired", "Passed and failed by a jury, and expired with no jury"), f'{r["settled_passed"]:,} / {r.get("settled_failed", 0):,} / {r.get("settled_expired_no_jury", 0):,}'],
        [T("Pending", "Answers still waiting for a grade"), f'{r["pending"]:,}'], ["Pending appeals", intc(r["pending_appeal"])],
        *([['<a href="/about#dropped">Dropped at close</a>', f'{r["dropped"]:,}']] if r.get("dropped") else []),
        [T("Awaiting graders", "Pending answers with no grading panel assigned yet"), intc(r["pending_empty_panel"])],
        ["Graders, grades", f'{r["graders"]} / {r["grades"]:,}'], [T("Attestations", "Attestations and the Agents that attested"), f'{intc(r["attestations"])} / {intc(r["attesters"])}'],
        [T("Slashed", "Graders slashed at this close; red when some were not pardoned"), f'<span class="num{" red" if unp > 0 else ""}">{r["slashed"]}</span>'],
        [T("Audit sampled", "Answers drawn for audit at this close"), intc(r["audit_sampled"])],
        ["Referral payouts", intc(r["referral_paid"])], ["Top-10 share, Gini", f'{pct(r["top10_share"])} / {r["gini"]:.3f}' if r["gini"] is not None else "···"],
        ["Distinct payouts", intc(r["distinct_amounts"])]]
    return table(["Field", "Value"], rows, usd=None)

def payouts_body(n, r, ch, nm, zeropay, qs, unc):
    if zeropay: return na("Closed, no payout (no answer reached quorum).")
    e = A.epoch_detail(n)
    rw = sorted(((a, float(v)) for a, v in e.get("rewards", {}).items()), key=lambda x: -x[1])
    by = ch.get("by_addr") or {}
    keys = ("rank", "agent", "reward") + (("answer_pay", "grading_pay") if by else ())
    cols = [SS.Col("rank", "#", "rank"), SS.Col("agent", "Agent", "text"), SS.Col("reward", "Reward", "num")]
    if by: cols += [SS.Col("answer_pay", "Answer pay", "num"), SS.Col("grading_pay", "Grading pay", "num")]
    srt = SS.page_sort(qs, keys, "rank"); d = SS.page_dir(qs)
    val = {"rank": lambda x: x[0], "agent": lambda x: SS.text_key(nm.get(x[1][0]) or x[1][0]), "reward": lambda x: x[1][1],
           "answer_pay": lambda x: (by.get(x[1][0]) or {}).get("answer_pay"), "grading_pay": lambda x: (by.get(x[1][0]) or {}).get("grading_pay")}[srt]
    allr = SS.sort_rows(list(enumerate(rw, 1)), val, SS.kind_of(cols, srt), d, tie=lambda x: x[0])
    try: off = max(0, min(int(_q(qs, "offset", "0")), max(0, len(allr) - 1))) // PAGE * PAGE
    except ValueError: off = 0
    page = allr[off:off + PAGE]
    link = SS.link_fn(f"/epoch/{n}", "rank", "#emod", **({"segment": SG.selected()} if SG.qs() else {}))
    def _c(a, k):
        v = (by.get(a) or {}).get(k)
        return poa(v, mined=True, dec=4) if v is not None else '<span class="dim">···</span>'
    cells = lambda i, a, v: [i, addr_link(a, nm), poa(v, mined=True, dec=4)] + ([_c(a, "answer_pay"), _c(a, "grading_pay")] if by else [])
    t = table([], [cells(i, a, v) for i, (a, v) in page], usd=(2, 3, 4) if by else (2,), pri=(0, 1, 2) if by else None, sort=(cols, srt, d, link))
    keep = "".join(f"&amp;{k}={E(_q(qs, k))}" for k in ("sort", "dir") if _q(qs, k))
    seg = f"&amp;segment={SG.selected()}" if SG.qs() else ""
    pg = _pager(len(allr), off, lambda o: f"/epoch/{n}?offset={o}{keep}{seg}#emod")
    return (note("Unconfirmed: these rewards are not confirmed in later balances.") if unc else "") + t + pg

def forum_body(prev_ts, close_ts):
    ts_ = _TOP.epoch_threads(prev_ts, close_ts)
    if not ts_: return ""
    rows = "".join(f'<li><a class="fmt" href="https://minepoa.com/lableak/#/post/{int(t["id"])}" rel="noopener noreferrer"><span class="fpid">#{int(t["id"])}</span> {E(t["title"])}</a>'
                   f'<span class="dim fmm">{E(t["community"])} · {_TOP._plur(t["replies"])}</span></li>' for t in ts_)
    return f'<ul class="fmoments">{rows}</ul>'

def page(n, r, rows, arch, nm, qs, page_fn):
    from . import paychannels as PCH
    e = A.epoch_detail(n)
    ch = PCH.for_close(n, rec=e, segment=r.get("segment"))
    unp = r["slashed"] - len((A.params().get("slash_pardons") or {}).get(str(n), []))
    zeropay = r["paid"] == 0 and r["minted"] == 0
    unc = SG.unconfirmed(n)
    prev_close = (rows.get(n - 1) or {}).get("close_ts")
    fb = forum_body(prev_close, r["close_ts"])
    tab = _q(qs, "tab"); tab = tab if tab in ("record", "forum") and (tab != "forum" or fb) else "payouts"
    body = {"payouts": lambda: payouts_body(n, r, ch, nm, zeropay, qs, unc), "record": lambda: record_body(n, r, e, ch, unp), "forum": lambda: fb}[tab]()
    sg = SG.qs().lstrip("?")
    href = lambda t: f"/epoch/{n}" + ("?" + "&amp;".join(x for x in (f"tab={t}" if t != "payouts" else "", sg) if x) if (t != "payouts" or sg) else "")
    tabs = [("payouts", href("payouts"), "Payouts", None), ("record", href("record"), "Record", None)] + ([("forum", href("forum"), "Forum", None)] if fb else [])
    pv = f'<a class="chip epn" href="/epoch/{n - 1}{SG.qs()}" aria-label="Epoch {n - 1}" title="Epoch {n - 1}">‹</a>' if n > 0 else ""
    nx = f'<a class="chip epn" href="/epoch/{n + 1}{SG.qs()}" aria-label="Epoch {n + 1}" title="Epoch {n + 1}">›</a>'
    mod = KIT.tabmod(tabs, tab, body, X.usd_toggle() + pv + nx, id="emod", label="Epoch")
    title = f"Epoch {n}" + (f" · {SG.label()}" if arch else "")
    html = f'<div class="sechead"><h1 class="sr-only">Epoch {n}</h1></div>{hero(n, r, rows, arch, unc, prev_close, zeropay)}{mod}'
    return page_fn(title, html, "/epochs", head=HEAD.format(_asset_v("epoch.css")))
