"""Agent profile v2 (1.26.213): the Timeline tab on the address page. One Agent's milestones in the selected segment, oldest
first, from POAScan's archive (final txs) and the segment's close records only: join, first answer, first grade seal, first
transfer, first invitee, first paid close, best close reward, Established added or removed, slashed or ejected, and the latest
tx. No upstream read. /api/v1/address/<a>/timeline and MCP get_agent_timeline carry the same rows."""
import time
from . import db, analytics as A, segments as SG
from .ui import E, card, lt, intc

METHOD = "/about#timeline"
KINDS = {"join": "Joined", "answer": "First answer", "seal": "First grade seal", "transfer": "First transfer",
         "invite": "First invitee joined", "paid": "First paid close", "best": "Best close reward", "est_add": "Established",
         "est_rm": "Established removed", "slashed": "Slashed", "ejected": "Ejected", "latest": "Latest tx"}
_TX = (("join", "join"), ("answer", "challenge"), ("seal", "grade-sealed"))

def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0

def _first(sql, args):
    r = db.q1(sql, args); return dict(r) if r else None

_memo, MEMO_S, MEMO_MAX = {}, 120, 500

def events(a):
    """Current segment only (the tab and API read the current segment). Memoized per address for MEMO_S, at most MEMO_MAX."""
    now = time.time(); hit = _memo.get(a)
    if hit and now - hit[0] < MEMO_S: return hit[1]
    v = _events(a)
    if len(_memo) >= MEMO_MAX: _memo.clear()
    _memo[a] = (now, v); return v

def _events(a):
    seg = SG.CURRENT; ev = []
    for k, typ in _TX:
        r = _first("SELECT id, ts, epoch FROM txs WHERE from_addr=? AND type=? AND segment=? ORDER BY ts, id LIMIT 1", (a, typ, seg))
        if r: ev.append(dict(kind=k, ts=r["ts"], tx=r["id"], close=None, value=None))
    r = _first("SELECT id, ts, amount FROM txs WHERE (from_addr=? OR to_addr=?) AND type='transfer' AND segment=? ORDER BY ts, id LIMIT 1", (a, a, seg))
    if r: ev.append(dict(kind="transfer", ts=r["ts"], tx=r["id"], close=None, value=_f(r["amount"])))
    r = _first("SELECT id, ts, from_addr FROM txs WHERE invited_by=? AND type='join' AND segment=? ORDER BY ts, id LIMIT 1", (a, seg))
    if r: ev.append(dict(kind="invite", ts=r["ts"], tx=r["id"], close=None, value=None))
    paid = best = None
    for e in sorted(A.segment_closes(SG.CURRENT), key=lambda e: int(e.get("epoch", 0))):
        n = int(e.get("epoch", 0)); ts = int(e.get("ts") or 0) or None; b = e.get("basis") or {}
        v = _f((e.get("rewards") or {}).get(a))
        if v > 0:
            if paid is None: paid = dict(kind="paid", ts=ts, tx=None, close=n, value=v)
            if best is None or v > best["value"]: best = dict(kind="best", ts=ts, tx=None, close=n, value=v)
        if a in (b.get("established_after") or []): ev.append(dict(kind="est_add", ts=ts, tx=None, close=n, value=None))
        if a in (b.get("established_removed") or []): ev.append(dict(kind="est_rm", ts=ts, tx=None, close=n, value=None))
        if a in (b.get("slashed") or []): ev.append(dict(kind="slashed", ts=ts, tx=None, close=n, value=None))
        if a in (b.get("ejected") or []): ev.append(dict(kind="ejected", ts=ts, tx=None, close=n, value=None))
    ev += [x for x in (paid, best) if x]
    r = _first("SELECT id, ts, type FROM txs WHERE (from_addr=? OR to_addr=?) AND segment=? ORDER BY ts DESC, id DESC LIMIT 1", (a, a, seg))
    if r and not any(x.get("tx") == r["id"] for x in ev): ev.append(dict(kind="latest", ts=r["ts"], tx=r["id"], close=None, value=None, type=r["type"]))
    order = list(KINDS)
    ev.sort(key=lambda x: ((x["ts"] or 0), order.index(x["kind"])))
    for x in ev: x["label"] = KINDS[x["kind"]]
    return ev

def _where(x):
    if x.get("tx"): return f'<a class="mono" href="/tx/{E(x["tx"])}">{E(x["tx"][:10])}…</a>'
    if x.get("close") is not None: g = SG.gkey(x["close"], SG.CURRENT); return f'<a href="{SG.ep_href(g)}">{SG.ep_label(g)}</a>'
    return ""

def tab_html(a):
    if SG.selected() != SG.CURRENT: return card("Timeline", '<p class="na">The timeline covers the current segment.</p>', id="timeline")
    ev = events(a)
    if not ev: return card("Timeline", '<p class="na">No milestones for this Agent in this segment yet.</p>', id="timeline")
    li = "".join(f'<li class="tlx tl-{E(x["kind"])}"><span class="tld" aria-hidden="true"></span><div><b>{E(x["label"])}</b>'
                 f'{" · " + intc(round(x["value"])) + " POA" if x.get("value") and x["kind"] in ("paid", "best", "transfer") else ""}'
                 f'{" · " + E(x.get("type") or "") if x["kind"] == "latest" else ""}'
                 f'<span class="tlw">{lt(x["ts"], "dt") if x["ts"] else ""} {_where(x)}</span></div></li>' for x in ev)
    foot = f'<p class="cov dim small">From final txs and close records in this segment · <a href="{METHOD}">Method</a></p>'
    return card(f"Timeline · {len(ev)}", f'<ol class="tl">{li}</ol>' + foot, f'<a class="more" href="/api/v1/address/{E(a)}/timeline">API →</a>', id="timeline")

def api(a):
    return dict(address=a, segment=SG.CURRENT, events=events(a), kinds=KINDS, method="https://poascan.io" + METHOD,
                url=f"https://poascan.io/address/{a}?tab=timeline")
