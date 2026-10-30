"""Expiry horizon per pending cohort (1.26.186): Governance, Queue.

A cohort is every answer still pending in the selected segment's latest close record (basis.pending) with the same entry
epoch (since; analytics.since_of fills a missing one), plus the open epoch's answers archived since that close. Each cohort
expires at the close entry epoch + pending TTL, the TTL read by netparams (minepoa's /api/params per segment, 16 only as a
flagged fallback). Counts only: a row's grades list is used for whether it has any seal at all (its length), never a score,
and no seal blob is read. No upstream read: close records and the params copy POAScan already holds."""
import time
from . import analytics as A, segments as SG, scoresort as SS, netparams as NP
from .ui import E, card, qtip, dur

METHOD = "/about#ttl"
# LabLeak post 1582, comment 6150 (Sluicekeeper-AI, E10 close record): the zero seal cohorts since 2, 3 and 4 expire at
# E18, E19 and E20 in segment 2. Config, not a rule: the rows tagged Watched.
WATCH = dict(segment=2, closes=(18, 19, 20), post=1582, comment=6150, url="https://minepoa.com/lableak/#/post/1582")

def _cohorts(last):
    """{since: [pending, no_seal]} from one close record's basis.pending."""
    out = {}
    for tid, v in ((A.pending_of(last) if last else None) or {}).items():
        if not isinstance(v, dict): continue
        x = out.setdefault(A.since_of(tid, v), [0, 0]); x[0] += 1
        if not v.get("grades"): x[1] += 1
    return out

@A.cached("pending_horizon", 60)
def horizon():
    seg = SG.selected(); arch = SG.archived(seg); raw = A.epochs_raw(); t = NP.pending_ttl(seg); ttl = t["value"]
    obs = None if arch else NP.observed_pending_ttl()
    last = raw[-1] if raw else None; lc = int(last["epoch"]) if last else None; lts = int(last.get("ts") or 0) if last else None
    period = int(A.params().get("auto_epoch_seconds") or 21600)
    o = None if arch else A.open_epoch(); cur = o.get("epoch") if o else None
    rows = []
    for since, (n, z) in sorted(_cohorts(last).items()):
        rows.append(dict(cohort=since, pending=n, no_seal=z, source="close"))
    if not arch and cur is not None and lc is not None and cur > lc:
        from . import db
        r = db.q1("SELECT COUNT(*) AS n FROM txs WHERE type='challenge' AND ts > ?", (lts,))
        if r and r["n"]: rows.append(dict(cohort=cur, pending=int(r["n"]), no_seal=None, source="open"))
    for x in rows:
        ex = x["cohort"] + ttl; x["expires_close"] = ex
        x["closes_left"] = (ex - cur) if cur is not None else None
        x["expires_est_ts"] = (lts + (ex - lc) * period) if (lts and lc is not None and not arch) else None
        x["watched"] = bool(seg == WATCH["segment"] and ex in WATCH["closes"])
        x["state"] = "ended" if arch else ("expiring" if x["closes_left"] is not None and x["closes_left"] <= 0 else "open")
    return dict(segment=seg, archived=arch, as_of_close=lc, as_of_close_ts=lts, open_epoch=cur, epoch_seconds=period,
                ttl=ttl, ttl_source=t["source"], ttl_confirmed=t["confirmed"], ttl_stale=t["stale"], ttl_fallback=t["fallback"],
                ttl_read=t, ttl_observed=obs, ttl_flags=[w for w, _ in NP.flags(t, obs)],
                estab_ttl=NP.estab_ttl(seg), total=sum(x["pending"] for x in rows),
                next_expiry=min((x["expires_close"] for x in rows if x["source"] == "close"), default=None), rows=rows,
                watch=dict(WATCH, closes=list(WATCH["closes"]), note="Zero seal cohorts since 2, 3 and 4 that LabLeak post 1582, comment 6150 tracks (segment 2)."))

COLS = [SS.Col("cohort", "Cohort", "low"), SS.Col("pending", "Pending", "num", "r"), SS.Col("no_seal", "No seal", "num", "r"),
        SS.Col("expires", "Expires", "low", "r"), SS.Col("left", "Left", "low", "r dk"), SS.Col("in", "In", "low", "r")]
SORTS = [(c.key, c.label) for c in COLS]
_V = {"cohort": lambda r: r["cohort"], "pending": lambda r: r["pending"], "no_seal": lambda r: r["no_seal"], "expires": lambda r: r["expires_close"],
      "left": lambda r: r["closes_left"], "in": lambda r: r["expires_est_ts"]}
TIP = ("Cohort: answers pending since that entry epoch. No seal: rows the close record lists with no grade. "
       "Expires: entry epoch + pending TTL. Left: closes after the open epoch. In: estimated time to that close.")

def select(by="cohort", d="desc"):
    rows = horizon()["rows"]
    return SS.sort_rows(list(rows), _V.get(by, _V["cohort"]), SS.kind_of(COLS, by), d, tie=lambda r: r["cohort"])

def _cd(ts):
    if not ts: return '<span class="dim">···</span>'
    return f'<span class="cd num" data-close="{int(ts)}">{dur(max(0, int(ts - time.time())))}</span>'

def ttl_line(h):
    t = h["ttl_read"]; e = h["estab_ttl"]
    src = "/api/params" if t["confirmed"] and not h["archived"] else t["source"]
    return (f'Pending TTL <b class="num">{h["ttl"]}</b> closes, {E(src)}{NP.flag_html(t, h["ttl_observed"])} · '
            f'Establishment TTL <b class="num">{e["value"]}</b>{NP.flag_html(e)}')

def card_html(qs, href):
    """The Expiry horizon card: one line per pending cohort with its expiry close and countdown."""
    h = horizon()
    if not h["rows"]: return card("Expiry horizon", f'<p class="na">No pending answers in this segment\'s latest close record.</p><p class="cov dim small">{ttl_line(h)}</p>', id="horizon")
    hq = {"sort": (qs or {}).get("hsort") or [""], "dir": (qs or {}).get("hdir") or [""]}   # its own keys: sort and dir belong to the settle queue
    by = SS.page_sort(hq, dict(SORTS), "cohort"); d = SS.page_dir(hq)
    link = lambda k, dd: href("queue", hsort=k if k != "cohort" else "", hdir="asc" if dd == "asc" else "") + "#horizon"
    def wtag(r): return (' <span class="tag warn" title="' + E(f'Tracked in LabLeak post {WATCH["post"]}, comment {WATCH["comment"]}') + '">Watched</span>') if r["watched"] else ""
    def left(r): return '<span class="dim">···</span>' if r["closes_left"] is None else f'<span class="num">{r["closes_left"]}</span>'
    trs = "".join(f'<tr{" class=hw" if r["watched"] else ""}><td>E{r["cohort"]}{" <small class=dim>open</small>" if r["source"] == "open" else ""}</td>'
                  f'<td class="r"><span class="num">{r["pending"]:,}</span></td>'
                  f'<td class="r">{"<span class=num>" + format(r["no_seal"], ",") + "</span>" if r["no_seal"] is not None else "<span class=dim>···</span>"}</td>'
                  f'<td class="r">E{r["expires_close"]}{wtag(r)}</td><td class="r dk">{left(r)}</td>'
                  f'<td class="r">{"<span class=dim>Ended</span>" if h["archived"] else "<span class=dim title=\'Past its expiry close; the engine drops expired rows\'>Past</span>" if (r["closes_left"] or 0) < 0 else _cd(r["expires_est_ts"])}</td></tr>' for r in select(by, d))
    cols = [c._replace(tip=qtip(TIP, METHOD, "About Expiry horizon", "hv")) if c.key == "expires" else c for c in COLS]
    lk = lambda k, dd: link(k, dd)
    tb = SS.select(cols, by, d, lk) + f'<div class="tw"><table class="hist cal gov hz"><thead><tr>{SS.heads(cols, by, d, lk)}</tr></thead><tbody>{trs}</tbody></table></div>'
    w = [r for r in h["rows"] if r["watched"]]
    note = (f' · E{WATCH["closes"][0]} to E{WATCH["closes"][-1]}: {sum(r["no_seal"] or 0 for r in w):,} no seal rows tracked in '
            f'<a href="{WATCH["url"]}" target="_blank" rel="noopener noreferrer">LabLeak post {WATCH["post"]}</a>, comment {WATCH["comment"]}') if w else ""
    asof = f' · As of the E{h["as_of_close"]} close' if h["as_of_close"] is not None else ""
    cov = f'<p class="cov dim small">{ttl_line(h)}{asof}{note} · <a href="{METHOD}">Method</a></p>'
    q = "?segment=" + str(h["segment"]) if h["archived"] else ""
    links = f'<a class="more" href="/api/v1/governance/pending-horizon.csv{q}" download>CSV →</a><a class="more" href="/api/v1/governance/pending-horizon{q}">API →</a>'
    return card(f'Expiry horizon · {len(h["rows"]):,}', tb + cov, links, cls="histc", id="horizon")

def api(sort="cohort", d="desc"):
    h = dict(horizon()); h["rows"] = select(sort, d)
    h.update(sort=sort, dir=d, source="close records (basis.pending) and /api/params", definitions=TIP,
             rule="expires_close = cohort (entry epoch) + pending TTL; closes_left = expires_close minus the open epoch",
             method="https://poascan.io" + METHOD, url="https://poascan.io/governance?tab=queue#horizon")
    return h

CSV_KEYS = ("cohort", "pending", "no_seal", "expires_close", "closes_left", "expires_est_ts", "watched", "source", "state")
def csv_rows(rows, h=None):
    h = h or horizon()
    return [dict({k: r.get(k) for k in CSV_KEYS}, ttl=h["ttl"], ttl_source=h["ttl_source"], segment=h["segment"]) for r in rows]
