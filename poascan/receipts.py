"""Answer receipts: one record per answer (challenge tx) built only from data POAScan already archives:
the tx itself, close records (basis.pending / basis.settled / rewards) and cached grade-sealed details.
Fields that the public records cannot show are None (unknown), never a guess."""
import json, time
from . import db, analytics as A, indexer as I, segments as S

QUORUM_DEFAULT = 4

@A.cached("receipt_index", 60)
def index():
    """Per answer txid: first/last close it sat in pending, its record there, and the close that settled it."""
    ep = sorted(A.epochs_raw(), key=lambda e: int(e.get("epoch", 0)))
    out, credited, elig, chal = {}, {}, {}, {}
    for e in ep:
        n = int(e.get("epoch", 0)); b = e.get("basis") or {}
        credited[n] = set((e.get("rewards") or {}).keys())
        elig[n] = set(b.get("challenge_eligible") or []); chal[n] = dict(e.get("challenges") or {})
        for t, p in (b.get("pending") or {}).items():
            r = out.setdefault(t, {}); r.setdefault("first", n); r["last"] = n
            r.update(since=A.since_of(t, p), panel=len(p.get("panel") or []), kind=p.get("kind"),
                     graded=len({g.get("grader") for g in p.get("grades") or []}) if "grades" in p else None)   # grades: the live seal list, from the merge on
        for s in b.get("settled") or []:
            t = s.get("answer")
            if t: out.setdefault(t, {})["settled"] = dict(close=n, passed=bool(s.get("passed")), seals=len(s.get("jury") or []), author=s.get("from"))
    seals = {}
    for r in db.q("SELECT json_extract(json, '$.body.assignment') AS a, json_extract(json, '$.from_addr') AS f FROM tx_detail "
                  "WHERE json_extract(json, '$.type') = 'grade-sealed'"):
        if r["a"] and r["f"]: seals.setdefault(r["a"], set()).add(r["f"])
    try:   # seal links read from the fast index (fastindex.bodies): same (answer, grader) pairs, one per seal tx
        for r in db.q("SELECT s.answer AS a, t.from_addr AS f FROM seal_links s JOIN txs t ON t.id = s.seal"):
            if r["a"] and r["f"]: seals.setdefault(r["a"], set()).add(r["f"])
    except Exception: pass   # table not created yet (fast index off)
    closes = [int(e.get("epoch", 0)) for e in ep]
    return dict(rec=out, credited=credited, elig=elig, chal=chal, seals={k: len(v) for k, v in seals.items()}, last=closes[-1] if closes else None)

# basis_state (LabLeak 1375 c3176): where the answer sits in the close records. settled: in a close's basis.settled;
# pending: in the latest close's basis.pending; absent: its epoch has closed and it is in neither (vanished from pending,
# or never recorded); None: its epoch has not closed yet.
BASIS = {"passed": "settled", "failed": "settled", "pending": "pending", "vanished": "absent", "unrecorded": "absent"}

def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def _detail(tid, fetch):
    try: return I.get_tx_detail(tid, allow_fetch=fetch)
    except Exception: return I.get_tx_detail(tid, allow_fetch=False)

def receipt(tid, fetch=False, row=None):
    """Receipt for one answer tx, or None when tid is not a known answer. fetch=True may read the tx once from
    minepoa.com (same as viewing /tx); it is cached for good once final. Read against the close records of the tx's own
    segment (segments.py): a segment 1 answer is never matched to a segment 2 close with the same number."""
    tid = tid.lower()
    row = row or db.q1("SELECT id, type, from_addr, epoch, ts, final, segment FROM txs WHERE id=?", (tid,))
    seg = (row or {}).get("segment") or S.of_ts((row or {}).get("ts"))
    with S.use(seg):
        r = _receipt(tid, fetch, row)
    if r and r.get("accepted"): r["segment"] = seg
    return r

def _receipt(tid, fetch, row):
    d = _detail(tid, fetch) if (fetch or not row) else (I.get_tx_detail(tid, allow_fetch=False) or {})
    d = d or {}
    typ = (row or {}).get("type") or d.get("type")
    if typ != "challenge":
        bad = db.q1("SELECT error FROM invalid_txs WHERE txid=?", (tid,))
        if bad: return dict(tx=tid, accepted=False, status="refused", note=bad["error"])
        return None
    ix = index(); r = ix["rec"].get(tid, {}); body = d.get("body") or {}
    ts = int((row or {}).get("ts") or d.get("ts") or 0) or None
    ep = (row or {}).get("epoch")
    if ep is None: ep = d.get("epoch") if d.get("epoch") is not None else body.get("epoch")
    author = (row or {}).get("from_addr") or d.get("from_addr") or (r.get("settled") or {}).get("author")
    last = ix["last"]; st = r.get("settled"); q = int(A.params().get("grade_quorum") or QUORUM_DEFAULT)
    if st: status = "passed" if st["passed"] else "failed"
    elif r.get("last") is not None and last is not None and r["last"] < last: status = "vanished"
    elif r.get("last") is not None: status = "pending"
    elif ep is not None and last is not None and int(ep) <= last: status = "unrecorded"
    else: status = "awaiting_close"
    seals_close = None
    if st: seals, seals_exact = st["seals"], True
    else:
        n = ix["seals"].get(tid); g = r.get("graded")
        if g is not None and (n or 0) <= g: seals, seals_exact, seals_close = g, True, r.get("last")   # exact as of that close
        else: seals, seals_exact = (n, False) if n else (None, False)
    counting = need = None; src = "close_record" if seals_exact else "archived_txs" if seals is not None else None; seals_as_of = None
    if not st:   # 1.26.137: a pending answer in minepoa's grading list: exact seals, the ones that count, and need
        from . import grading as GR
        g = GR.row_of(tid)
        if g: seals, seals_exact, seals_close, counting, need, src, seals_as_of = g["raw"], True, None, g["qual"], g["need"], "minepoa_grading", GR.upstream_as_of(); q = int((GR.current() or {}).get("quorum") or q)
    paid_close = None; paid = None
    if st:
        if st["passed"] and author: paid = author in ix["credited"].get(st["close"], set()); paid_close = st["close"] if paid else None
        elif not st["passed"]: paid = False
    since = r.get("since") if r.get("since") is not None else ep
    # The answer's own close, keyed on (author, epoch) in challenge_eligible and challenges, not on rewards (LabLeak 1370 c3269, c3502).
    k = int(ep) if ep is not None else None
    have = k is not None and k in ix["elig"] and author is not None
    ce = (author in ix["elig"][k]) if have else None
    ca = ix["chal"][k].get(author) if have else None
    bs = BASIS.get(status)
    return dict(tx=tid, address=author, epoch=ep, accepted=True, final=bool((row or {}).get("final") or d.get("final")),
                seed=body.get("seed"), submitted_at=ts, age_s=int(time.time() - ts) if ts else None,
                closes_waited=(last - int(since)) if (last is not None and since is not None and status in ("pending", "vanished")) else None,
                status=status, kind=r.get("kind"), panel=r.get("panel") if status in ("pending", "vanished") else None,
                seals=seals, seals_exact=seals_exact, seals_as_of_close=seals_close, quorum=q, seals_counting=counting, seals_need=need, seals_source=src, seals_as_of=seals_as_of,
                settled_close=st["close"] if st else None, passed=st["passed"] if st else None,
                paid_close=paid_close, address_credited=paid, reward_attributable=None,
                paid_state=("unconfirmed" if S.unconfirmed(paid_close, (row or {}).get("segment") or S.selected()) else "recorded") if paid_close is not None else None,
                vanished=status == "vanished", last_pending_close=r.get("last"),
                basis_state=bs, challenge_eligible=ce, challenges_amount=ca,
                paid_via_challenge_eligible=(bs == "absent" and bool(ce) and (_num(ca) or 0) > 0) if have and bs else None)

def for_address(a, limit=50):
    rows = db.q("SELECT id, type, from_addr, epoch, ts, final, segment FROM txs WHERE from_addr=? AND type='challenge' ORDER BY ts DESC LIMIT ?", (a, limit))
    return [x for x in (receipt(r["id"], row=r) for r in rows) if x]

# ---------------------------------------------------------------- HTML
from html import escape as E
from .ui import dur, short, table

UNK = '<span class="na">Unknown</span>'
TAG = {"passed": "ok", "failed": "bad", "vanished": "warn", "refused": "bad"}
LABEL = {"passed": "Passed", "failed": "Failed", "pending": "Pending", "awaiting_close": "Awaiting close",
         "vanished": "Dropped at close", "unrecorded": "No record", "refused": "Refused"}

def _e(r, n):
    """E5, or S1 E5 for an answer from an archived segment."""
    sg = r.get("segment") or S.CURRENT
    return f"E{n}" if sg == S.CURRENT else f"S{sg} E{n}"

def status_tag(r):
    s = r["status"]; c = r.get("settled_close") if s in ("passed", "failed") else r.get("last_pending_close") if s == "vanished" else None
    at = f' · {_e(r, c)}' if c is not None else ""
    return f'<span class="tag {TAG.get(s, "")}">{LABEL[s]}{at}</span>'   # pending and awaiting close stay neutral

def seals_txt(r):
    q = r["quorum"]
    if r["seals"] is None: return f'{UNK} <span class="dim">/ {q}</span>'
    if r.get("seals_counting") is not None: return f'<span class="num">{r["seals_counting"]}</span> <span class="dim">/ {q} · {r["seals"]} seal{"" if r["seals"] == 1 else "s"}</span>'
    return f'<span class="num">{"" if r["seals_exact"] else "≥"}{r["seals"]}</span> <span class="dim">/ {q}</span>'

def paid_txt(r):
    if r.get("paid_via_challenge_eligible"): return f'{_e(r, r["epoch"])} <span class="dim">· challenge-eligible, not in basis</span>'
    if r["address_credited"] is True: return _e(r, r["paid_close"]) + (' <span class="tag warn">Unconfirmed</span>' if r.get("paid_state") == "unconfirmed" else "")
    if r["passed"] is True: return f'No credit at {_e(r, r["settled_close"])}'
    if r["passed"] is False: return "No"
    return '<span class="dim">Not settled</span>'

def age_txt(r):
    a = dur(r["age_s"]) if r.get("age_s") is not None else UNK
    w = r.get("closes_waited") if r["status"] == "pending" else None
    return a + (f' <span class="dim">· {w} close{"" if w == 1 else "s"} pending</span>' if w else "")

def card_html(r):
    """kv rows for the /tx receipt card."""
    rows = [("Accepted", "Yes" if r["accepted"] else "No"), ("Seed", f'<span class="mono">{E(r["seed"])}</span>' if r.get("seed") else UNK),
            ("Age", age_txt(r)), ("Status", status_tag(r)),
            ("Seals", seals_txt(r) + (f' <span class="dim">· panel {r["panel"]}</span>' if r.get("panel") is not None else "")),
            ("Paid", paid_txt(r))]   # vanished shows as the status, not a second row
    return "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in rows)

def list_html(rs):
    """Compact list: quorum sits in the header, unsettled rows leave Paid blank."""
    q = rs[0]["quorum"] if rs else None
    def sl(r): return UNK if r["seals"] is None else f'<span class="num">{"" if r["seals_exact"] else "≥"}{r["seals"]}</span>'
    def pd(r): return paid_txt(r) if r["passed"] is not None or r.get("paid_via_challenge_eligible") else '<span class="dim">·</span>'
    return table(["Answer", "Status", f"Seals / {q}" if q else "Seals", "Paid"],
                 [[f'<span class="ep dim">{_e(r, r["epoch"])}</span> <a class="mono hash" href="/tx/{E(r["tx"])}" title="{E(r["tx"])}">{E(short(r["tx"], 4, 4))}</a>',
                   status_tag(r), sl(r), pd(r)] for r in rs], cls="rcpt")
