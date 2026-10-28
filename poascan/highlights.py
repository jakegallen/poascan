"""Records and highlights (1.26.207): Network, Records. Notable records and firsts for the last 24 hours, the last 7 days and
the whole current segment, read only from POAScan's own archive (final txs) and the stored close records. No upstream read.
Neutral wording: each entry states a value, who holds it and when, nothing more."""
import time
from . import db, analytics as A, segments as SG
from .ui import E, card, agent, lt, intc

METHOD = "/about#highlights"
PERIODS = [("day", "24 h", 86400), ("week", "7 days", 7 * 86400), ("ever", "Segment", None)]

def _poa(v):
    try: v = float(v)
    except (TypeError, ValueError): return "···"
    if v >= 1e6: return f"{v / 1e6:,.2f}M POA"
    if v >= 1e3: return f"{v / 1e3:,.1f}K POA"
    return f"{v:,.2f} POA"

def _tx_records(seg, since):
    w = "segment=? AND final=1" + (" AND ts>=?" if since else ""); a = (seg,) + ((since,) if since else ())
    out = {}
    r = db.q1(f"SELECT id, from_addr, to_addr, amount, ts FROM txs WHERE type='transfer' AND {w} ORDER BY CAST(amount AS REAL) DESC LIMIT 1", a)
    out["transfer"] = dict(value=float(r["amount"]), who=r["from_addr"], to=r["to_addr"], ts=r["ts"], tx=r["id"]) if r and r["amount"] is not None else None
    for key, typ in (("busy_hour", None), ("seal_hour", "grade-sealed"), ("answer_hour", "challenge")):
        r = db.q1(f"SELECT ts / 3600 AS h, COUNT(*) AS n FROM txs WHERE {w}" + (" AND type=?" if typ else "") + " GROUP BY h ORDER BY n DESC, h DESC LIMIT 1", a + ((typ,) if typ else ()))
        out[key] = dict(value=int(r["n"]), ts=int(r["h"]) * 3600) if r and r["n"] else None
    r = db.q1(f"SELECT ts / 86400 AS d, COUNT(*) AS n FROM txs WHERE type='join' AND {w} GROUP BY d ORDER BY n DESC, d DESC LIMIT 1", a)
    out["join_day"] = dict(value=int(r["n"]), ts=int(r["d"]) * 86400) if r and r["n"] else None
    r = db.q1(f"SELECT from_addr, COUNT(*) AS n, MAX(ts) AS t FROM txs WHERE type='grade-sealed' AND {w} GROUP BY from_addr ORDER BY n DESC, t DESC LIMIT 1", a)
    out["seals_by_one"] = dict(value=int(r["n"]), who=r["from_addr"], ts=r["t"]) if r and r["n"] else None
    return out

def _close_records(eps, since):
    cs = [e for e in eps if not since or int(e.get("ts") or 0) >= since]
    out = dict(reward=None, paid=None, settled=None, served=None)
    for e in cs:
        n = int(e.get("epoch", 0)); ts = int(e.get("ts") or 0); rw = e.get("rewards") or {}; b = e.get("basis") or {}
        num = lambda v: float(v) if isinstance(v, (int, float, str)) and str(v).replace(".", "", 1).isdigit() else 0.0
        if rw:
            a, v = max(rw.items(), key=lambda kv: num(kv[1]))
            if num(v) > 0 and (out["reward"] is None or num(v) > out["reward"]["value"]): out["reward"] = dict(value=num(v), who=a, close=n, ts=ts)
            p = sum(1 for x in rw.values() if num(x) > 0)
            if out["paid"] is None or p > out["paid"]["value"]: out["paid"] = dict(value=p, close=n, ts=ts)
        s = len(b.get("settled") or [])
        if s and (out["settled"] is None or s > out["settled"]["value"]): out["settled"] = dict(value=s, close=n, ts=ts)
        gs = b.get("graders_served") or {}
        if gs:
            a, v = max(gs.items(), key=lambda kv: num(kv[1]))
            if out["served"] is None or num(v) > out["served"]["value"]: out["served"] = dict(value=int(num(v)), who=a, close=n, ts=ts)
    return out

def _first(where, args):
    r = db.q1("SELECT id, from_addr, ts, epoch FROM txs WHERE final=1 AND " + where + " ORDER BY ts, id LIMIT 1", args)
    return dict(who=r["from_addr"], ts=r["ts"], tx=r["id"], epoch=r["epoch"]) if r else None

def _firsts(seg, eps):
    last = eps[-1] if eps else None; lts = int(last.get("ts") or 0) if last else 0; open_ep = (int(last["epoch"]) + 1) if last else None
    out = [("first_answer", "First answer in this segment", _first("type='challenge' AND segment=?", (seg,))),
           ("first_seal", "First grade seal in this segment", _first("type='grade-sealed' AND segment=?", (seg,))),
           ("first_join", "First join in this segment", _first("type='join' AND segment=?", (seg,)))]
    if open_ep is not None:
        out.append(("open_answer", f"First answer of E{open_ep}", _first("type='challenge' AND segment=? AND epoch=?", (seg, open_ep))))
        out.append(("close_seal", f"First grade seal after the E{open_ep - 1} close", _first("type='grade-sealed' AND segment=? AND ts>?", (seg, lts))))
    return [dict(key=k, label=l, **(v or {}), found=v is not None) for k, l, v in out]

ROWS = [  # key, label, group, format
    ("reward", "Largest reward to one Agent at a close", "close", "poa"), ("paid", "Most Agents paid at one close", "close", "int"),
    ("settled", "Most answers settled at one close", "close", "int"), ("served", "Most grading seats served by one Agent at a close", "close", "int"),
    ("transfer", "Largest transfer", "tx", "poa"), ("busy_hour", "Most txs in one hour", "tx", "int"), ("answer_hour", "Most answers in one hour", "tx", "int"),
    ("seal_hour", "Most grade seals in one hour", "tx", "int"), ("seals_by_one", "Most grade seals by one Agent", "tx", "int"), ("join_day", "Most joins in one day (UTC)", "tx", "int")]

@A.cached("highlights", 600)
def data(now=None):
    seg = SG.selected(); now = int(now or time.time()); eps = sorted(A.epochs_raw(), key=lambda e: int(e.get("epoch", 0)))
    per = {}
    for k, label, span in PERIODS:
        since = now - span if span else None
        per[k] = dict(label=label, since=since, records={**_tx_records(seg, since), **_close_records(eps, since)})
    return dict(segment=seg, as_of=now, periods=per, firsts=_firsts(seg, eps))

def _val(x, fmt):
    if not x: return '<span class="na">···</span>'
    v = _poa(x["value"]) if fmt == "poa" else intc(x["value"])
    who = (" " + agent(x["who"])) if x.get("who") else ""
    at = (f'<a href="/epoch/{x["close"]}">E{x["close"]}</a> · ' if x.get("close") is not None else "") + (lt(x["ts"], "dt") if x.get("ts") else "")
    if x.get("tx"): at = f'<a href="/tx/{E(x["tx"])}">{lt(x["ts"], "dt")}</a>'
    return f'<b class="hv0">{v}</b>{who}<span class="dim small hl-at">{at}</span>'

def body():
    d = data(); P = d["periods"]; cols = [k for k, _, _ in PERIODS]
    head = "".join(f'<th>{E(P[k]["label"])}</th>' for k in cols)
    tr = "".join(f'<tr><th scope="row">{E(lbl)}</th>' + "".join(f'<td>{_val(P[k]["records"].get(key), fmt)}</td>' for k in cols) + "</tr>" for key, lbl, _, fmt in ROWS)
    tb = f'<div class="tw"><table class="hist hlt"><thead><tr><th>Record</th>{head}</tr></thead><tbody>{tr}</tbody></table></div>'
    fl = "".join(f'<li><span class="lbl">{E(f["label"])}</span>'
                 + (f'{agent(f["who"])}<a class="dim small" href="/tx/{E(f["tx"])}">{lt(f["ts"], "dt")}</a>' if f["found"] else '<span class="na">Not yet</span>') + "</li>" for f in d["firsts"])
    foot = (f'<p class="cov dim small">From POAScan\'s archive of final txs and the stored close records, this segment only · Read {lt(d["as_of"], "t")} · '
            f'<a href="{METHOD}">Method</a> · <a href="/api/v1/highlights">API</a></p>')
    return card("Records", tb, cls="histc", id="records") + card("Firsts", f'<ul class="hlf">{fl}</ul>' + foot, id="firsts")

def api():
    d = data()
    return dict(d, method="https://poascan.io" + METHOD, url="https://poascan.io/network?tab=records",
                labels={k: l for k, l, *_ in ROWS})
