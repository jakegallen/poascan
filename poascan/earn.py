"""Start earning (/help) and the Why am I not earning? check (/help?address=poa1..., /api/v1/earn/<addr>, MCP get_earn_check).

One plain checklist per Agent, each row with one next step. Built only from POAScan's own public API payloads (the address,
standing, receipts, governance and intake reads, plus the close record of a paid close), so the check adds no minepoa.com
request: in production the payloads come from server.api in process; a preview can point POASCAN_EARN_SOURCE at a POAScan
base URL and read the same payloads over HTTP. Rules come from minepoa's go.md and skill.md and the engine's close records.
Read only: the check never asks for a key and never submits anything."""
import datetime, json, os, re, threading, time, urllib.request
from html import escape as E
from . import outcome as OC

ROUTE = "/help"
API = "/api/v1/earn/"
METHOD = "/about#earn-check"
SOURCE = os.environ.get("POASCAN_EARN_SOURCE", "").rstrip("/")   # preview only: a POAScan base URL (never minepoa.com)
QUORUM = 4
LABLEAK_WORK = "https://minepoa.com/go.md"   # 1.26.244: the GRADE section; no grading guide link

class Unknown(Exception): pass

# ---------------------------------------------------------------- inputs
_cache, _lock = {}, threading.Lock()
TTL = 60

def _remote(path):
    """Preview: one POAScan API read (cached 60 s; close records 1 h)."""
    url = SOURCE + "/api/v1" + path[len("/api"):]
    k = ("r", url); now = time.time()
    with _lock:
        hit = _cache.get(k)
        if hit and now - hit[0] < (3600 if "/record" in path else TTL): return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": "POAScan-earn-preview", "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r: d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404: d = None
        else: raise
    with _lock: _cache[k] = (now, d)
    return d

PLACEHOLDER = re.compile(r"^\s*(YOUR_[A-Z_]+|[A-Z][A-Z0-9_]{3,}_(TEXT|INTRO|POST|ANSWER|NAME))\s*$")
URLENC = re.compile(r"%(2C|3A|20|2B|21|3F|27|0A)", re.I)
FORUM_WINDOW = 86400
HEAVY = 8   # posts plus comments in the window

def forum_stats(rows, now=None):
    """rows: [{kind: post|comment, title, body, ts}] by one Agent. Counts only (never text): items in the last 24 h, repeats
    (same text as an earlier item), placeholders (a bare template token such as YOUR_INTRO) and URL encoded bodies."""
    now = int(now or time.time()); recent = [r for r in rows if r.get("ts") and now - int(r["ts"]) <= FORUM_WINDOW]
    seen, rep = set(), 0
    for r in sorted(recent, key=lambda r: r["ts"]):
        k = ((r.get("title") or "") + "\n" + (r.get("body") or "")).strip().lower() if r["kind"] == "post" else (r.get("body") or "").strip().lower()
        if k in seen: rep += 1
        seen.add(k)
    ph = sum(1 for r in recent if PLACEHOLDER.match(r.get("body") or "") or PLACEHOLDER.match(r.get("title") or ""))
    enc = sum(1 for r in recent if len(URLENC.findall((r.get("title") or "") + (r.get("body") or ""))) >= 2)
    return dict(window_s=FORUM_WINDOW, posts=sum(1 for r in recent if r["kind"] == "post"), comments=sum(1 for r in recent if r["kind"] == "comment"),
                repeats=rep, placeholders=ph, url_encoded=enc, total_posts=sum(1 for r in rows if r["kind"] == "post"), total_comments=sum(1 for r in rows if r["kind"] == "comment"))

def _ts(s):
    try: d = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T"))
    except (TypeError, ValueError): return None
    try: return int((d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)).timestamp())
    except (TypeError, ValueError): return None

def forum_rows_local(a):
    """POAScan's LabLeak mirror (forum_posts, forum_comments) by author_public_id: no upstream read."""
    from . import db
    ps = db.q("SELECT title, body, created_at FROM forum_posts WHERE author_public_id=? AND COALESCE(deleted,0)=0", (a,))
    cs = db.q("SELECT body, created_at FROM forum_comments WHERE author_public_id=?", (a,))
    return [dict(kind="post", title=r["title"], body=r["body"], ts=_ts(r["created_at"])) for r in ps] + [dict(kind="comment", body=r["body"], ts=_ts(r["created_at"])) for r in cs]

FORUM_FIXTURE = os.environ.get("POASCAN_EARN_FORUM_FIXTURE", "")   # preview only: a JSON list of LabLeak post objects (with comments) read once

def forum_rows_fixture(a):
    try: posts = json.load(open(FORUM_FIXTURE))
    except (OSError, ValueError): return []
    out, seen = [], set()
    for p in posts:
        if p.get("author_public_id") == a and p.get("id") not in seen and p.get("title") is not None:
            seen.add(p.get("id")); out.append(dict(kind="post", title=p.get("title"), body=p.get("body"), ts=_ts(p.get("created_at"))))
        for c in p.get("comments") or []:
            if c.get("author_public_id") == a and ("c", c.get("id")) not in seen:
                seen.add(("c", c.get("id"))); out.append(dict(kind="comment", body=c.get("body"), ts=_ts(c.get("created_at"))))
    return out

HIST = 40   # closes in the history table

def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def close_row(n, rec, a, mine, est_before):
    """One close of the per close history, read only from fields that are in the public close record and the receipts.
    lines: [{kind, text, field, raw}]; kind cut (reduced or zeroed), bad (failed, dropped, penalty), miss (no answer),
    wait (pending), exp (expired with no jury: no credit, not a failure), good (credited), info. A reason is listed only when its field is in the record."""
    b = rec.get("basis") or {}; L = []
    def ln(kind, text, field, raw): L.append(dict(kind=kind, text=text, field=field, raw=raw if isinstance(raw, (int, float, bool)) or raw is None else str(raw)))
    share = (rec.get("challenges") or {}).get(a); paid = (rec.get("rewards") or {}).get(a)
    elig = a in (b.get("challenge_eligible") or [])
    ans = [r for r in mine if r.get("epoch") == n]
    known = [r for r in mine if r.get("epoch") is not None and r["epoch"] <= n]
    raw = {}
    if not ans: ln("miss", f"No answer in E{n}. No answer, no rewards that epoch.", "receipts", f"none for E{n}")
    from . import analytics as _A
    pend = (b.get("pending") or {}) if "pending" in b else _A.pending_get(rec, [r.get("tx") for r in known])   # 1.26.235: a local slim record
    pw = [(r, pend[r.get("tx")]) for r in known if isinstance(pend.get(r.get("tx") or ""), dict)]
    if pw:
        eps_w = sorted(r["epoch"] for r, _ in pw)
        ln("wait", (f"E{eps_w[0]} answer" if len(pw) == 1 else f"{len(pw)} answers ({_epochs(eps_w)})") + " waiting for a jury", "basis.pending",
           "; ".join(f"{(r.get('tx') or '')[:10]} kind {p.get('kind')}, since E{p.get('since')}, grades {len(p.get('grades') or [])}" for r, p in pw))
    for r in known:
        if r.get("vanished") and r.get("last_pending_close") is not None and r["last_pending_close"] == n - 1:
            ln("bad", f"E{r['epoch']} answer left the pending list with no grade", "basis.pending", f"absent at E{n}, last listed E{n - 1}")
    for x in b.get("settled") or []:
        if x.get("from") == a:
            ep = next((r["epoch"] for r in known if r.get("tx") == x.get("answer")), None)
            w = f"E{ep} answer" if ep is not None else "Answer"
            if x.get("passed"): ln("good", f"{w} passed", "basis.settled", "passed true")
            elif OC.no_jury(x): ln("exp", f"{w} expired, no jury", "basis.settled", "expired true, jury empty")
            else: ln("bad", f"{w} failed grading", "basis.settled", "passed false")
    if ans and not elig: ln("cut", "Not challenge eligible at this close. The verification share is challenge gated.", "basis.challenge_eligible", "not listed")
    if elig: ln("good", "Challenge eligible", "basis.challenge_eligible", "listed")
    cg = b.get("ceiling") or {}
    v = (cg.get("capped") or {}).get(a); raw["ceiling_capped"] = v
    if v is not None:
        if (_num(v) or 0) == 0: ln("cut", f"The E{n} close record shows this share capped to 0", "basis.ceiling.capped", v)
        else: ln("cut", "Ceiling cap applied to this share", "basis.ceiling.capped", v)
    v = (cg.get("repooled") or {}).get(a)
    if v is not None: ln("info", "Listed in the ceiling repool", "basis.ceiling.repooled", v)
    fp = b.get("final_payout") or {}
    v = (fp.get("capped") or {}).get(a)
    if v is not None: ln("cut", "Final payout capped", "basis.final_payout.capped", v)
    v = (fp.get("repooled") or {}).get(a)
    if v is not None: ln("info", "Listed in the final payout repool", "basis.final_payout.repooled", v)
    w = (rec.get("weights") or {}).get(a)
    if w is not None and (_num(w) or 0) < 1: ln("cut", f"Verification weight {float(w):.2f} (reciprocity and kinship)", "weights", w)
    at = (b.get("attestations") or {}).get(a); raw["attestations"] = at
    if at: ln("good", f"{int(at):,} attestations credited", "basis.attestations", at)
    gs = (b.get("graders_served") or {}).get(a)
    jn = ja = 0
    for x in b.get("settled") or []:
        for j in x.get("jury") or []:
            if j.get("grader") == a: jn += 1; ja += 1 if j.get("aligned") else 0
    if gs: ln("good", f"Served {int(gs)} grading seat{'s' if int(gs) != 1 else ''}", "basis.graders_served", gs)
    if jn: ln("good" if ja == jn else "bad", f"{ja} of {jn} grades aligned with the verdict", "basis.settled[].jury", f"{ja} aligned, {jn - ja} not")
    v = ((b.get("referral2") or {}).get("paid") or {}).get(a)
    if v is not None: ln("good", "Referral income", "basis.referral2.paid", v)
    v = (rec.get("propagation") or {}).get(a)
    if v is not None: ln("good", "Propagation reward (observed)", "propagation", v)
    est = est_before
    if a in (b.get("established_after") or []):
        if not est: ln("good", "Admitted to Established", "basis.established_after", "listed")
        est = True
    elif elig and not est: ln("cut", "Eligible for Established, not drawn at intake", "basis.established_after", "not listed")
    if a in (b.get("established_removed") or []): ln("bad", "Lost Established", "basis.established_removed", "listed"); est = False
    if a in (b.get("slashed") or []) or a in ((b.get("audit") or {}).get("slashed") or []): ln("bad", "Slashed", "basis.slashed", "listed")
    if a in (b.get("ejected") or []): ln("bad", "Ejected", "basis.ejected", "listed")
    v = (b.get("marks") or {}).get(a) if isinstance(b.get("marks"), dict) else None
    if v: ln("bad", f"{v} audit mark{'s' if v != 1 else ''}", "basis.marks", v)
    sc = set(b.get("spotcheck") or [])
    for r in known:
        if r.get("tx") in sc: ln("info", f"E{r['epoch']} answer spot checked", "basis.spotcheck", "listed")
    return dict(close=n, ts=rec.get("ts"), answered=bool(ans), share=share, paid=paid, eligible=elig, seats=int(gs or 0), jury=jn, aligned=ja,
                cuts=sum(1 for x in L if x["kind"] in ("cut", "bad", "miss")), lines=L, raw=raw, _est=est)

def gather(a, get, forum_fn=None):
    """The public payloads the check reads. get(path, qs) returns the API object for a POAScan /api path (or None on 404)."""
    ad = get(f"/api/address/{a}", {})
    out = dict(address=ad, standing=get(f"/api/address/{a}/standing", {}), receipts=get("/api/receipts", {"address": [a], "limit": ["50"]}) or [],
               governance=get(f"/api/address/{a}/governance", {}), established=get(f"/api/address/{a}/established", {}),
               status=get("/api/status", {}), intake=None, ceiling={}, history=[], forum=None)
    st = out["standing"] or {}
    L = st.get("last_challenge_eligible_epoch")
    if L is not None and not st.get("established"):
        out["intake"] = get("/api/governance/intake", {"close": [str(L)], "limit": ["5000"]})
    # per close history: every close of this segment from the Agent's first tx or answer here to the last close (at most HIST)
    seg = (ad or {}).get("balance_segment"); lc = st.get("last_close")
    eps = [t.get("epoch") for t in (ad or {}).get("txs") or [] if t.get("segment") == seg and t.get("epoch") is not None]
    eps += [r["epoch"] for r in out["receipts"] if r.get("segment") == seg and r.get("epoch") is not None]
    out["history"] = []
    if eps and lc is not None:
        mine = [r for r in out["receipts"] if r.get("segment") == seg]
        est = (out["established"] or {}).get("basis") == "import"
        for n in range(max(min(eps), lc - HIST + 1, 0), lc + 1):
            rec = get(f"/api/epoch/{n}/record", {})
            if not rec: continue
            if n >= lc - 1:   # preview (earn gates): this Agent's pending answers and their grade counts at the last two closes
                b0 = rec.get("basis") if isinstance(rec.get("basis"), dict) else {}
                from . import analytics as _A
                pg = b0.get("pending") if "pending" in b0 else _A.pending_of(rec)   # 1.26.235: a local slim record reads its row
                pg = pg if isinstance(pg, dict) else {}; mt = {r.get("tx") for r in mine}
                out.setdefault("pend_grades", {})[n] = {t: dict(grades=len({(g.get("grader") if isinstance(g, dict) else g) for g in p.get("grades") or []}), panel=len(p.get("panel") or []))
                                                         for t, p in pg.items() if t in mt and isinstance(p, dict)}
            row = close_row(n, rec, a, mine, est); est = row.pop("_est")
            out["history"].append(row)
            if n in {r.get("paid_close") for r in mine}:
                out["ceiling"][n] = dict(share=row["share"], reward=row["paid"], capped=row["raw"].get("ceiling_capped"), eligible=row["eligible"],
                                         attestations=row["raw"].get("attestations"))
    if forum_fn:
        try: out["forum"] = forum_stats(forum_fn(a))
        except Exception: out["forum"] = None
    return out

def gather_remote(a):
    return gather(a, lambda p, qs: _remote(p + ("?" + "&".join(f"{k}={v[0]}" for k, v in qs.items()) if qs else "")), forum_rows_fixture if FORUM_FIXTURE else None)

# ---------------------------------------------------------------- the check
def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def _epochs(xs):
    """[4, 6, 7, 8, 9, 10] -> 'E4, E6 to E10' (no dashes)."""
    xs = sorted(set(xs)); out = []; i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[j] + 1: j += 1
        out.append(f"E{xs[i]}" if i == j else f"E{xs[i]}, E{xs[j]}" if j == i + 1 else f"E{xs[i]} to E{xs[j]}"); i = j + 1
    return ", ".join(out)

def _poa(v):
    v = _f(v) or 0.0
    if v >= 1e9: return f"{v / 1e9:,.2f}B"
    if v >= 1e6: return f"{v / 1e6:,.2f}M"
    if v >= 1e3: return f"{v / 1e3:,.1f}K"
    return f"{v:,.0f}"

def check(a, inp, now=None):
    """The checklist. state per row: ok, warn, bad, na. Every row has one next step (text, optional link)."""
    ad = inp.get("address") or {}; st = inp.get("standing") or {}; gv = inp.get("governance") or {}; fx = gv.get("facts") or {}
    eh = inp.get("established") or {}; rc = inp.get("receipts") or []; wb = ad.get("wallet_binding") or {}
    status = inp.get("status") or {}
    segs = status.get("segments") or []; cur = status.get("segment") or ad.get("balance_segment") or 2
    off = sum(int(s.get("closes") or 0) for s in segs if s.get("segment", 0) < cur)
    txs = ad.get("txs") or []
    seg_txs = [t for t in txs if t.get("segment") == cur]
    old_txs = [t for t in txs if t.get("segment") not in (None, cur)]
    joined = next((t["ts"] for t in sorted(txs, key=lambda t: t["ts"]) if t.get("type") == "join"), None) or wb.get("joined_ts")
    found = bool(txs) or _f(ad.get("balance")) not in (None, 0.0) or bool(wb.get("linked"))
    open_ep = st.get("open_epoch"); last_close = st.get("last_close")
    items = []
    def row(key, label, state, value, nxt, href=None, tip=None, chips=None):
        items.append(dict(key=key, label=label, state=state, value=value, next=nxt, href=href, tip=tip, chips=chips or []))

    if not found:
        row("agent", "Agent", "bad", "Not found",
            "Check the address. It starts poa1 and is case sensitive. A new join shows here within a few minutes.", "/start")
        return dict(address=a, found=False, history=[], grading=None, grades=None, ways=WAYS, disclaimer=DISCLAIMER, segment=cur, headline="Not found", tone="bad", items=items, open_epoch=open_ep, last_close=last_close,
                    verdict=dict(title="Not found", reason="No Agent at this address in POAScan's archive.", step="Paste the address again from your agent. It is case sensitive.", href=None), specific=[])

    # 1 Agent
    if seg_txs:
        row("agent", "Agent", "ok", f"Found · Segment {cur}", "Open the address page for every tx.", f"/address/{a}")
    elif old_txs:
        row("agent", "Agent", "warn", f"Segment {old_txs[0]['segment']} only",
            f"Joined before the genesis cut. Answer once in Segment {cur} to start this segment's record.", f"/address/{a}")
    else:
        row("agent", "Agent", "warn", "Joined, no answers yet", "Answer this epoch's challenge to start earning.", "#guide")

    # 2 Answers per epoch (receipts: accepted and final means it landed on chain)
    mine = [r for r in rc if r.get("segment") == cur]
    landed = sorted({r["epoch"] for r in mine if r.get("accepted")})
    first = landed[0] if landed else None
    chips = []
    if first is not None and open_ep is not None:
        for n in range(first, open_ep + 1):
            r = next((x for x in mine if x["epoch"] == n), None)
            s = (r or {}).get("status")
            chips.append(dict(epoch=n, state="none" if not r else {"passed": "ok", "failed": "bad", "vanished": "bad", OC.EXPIRED: "exp"}.get(s, "wait"),
                              label="No answer" if not r else {"passed": "Passed", "failed": "Failed", "pending": "Pending", "awaiting_close": "Landed",
                                                                 "vanished": "Dropped", OC.EXPIRED: OC.LABEL[OC.EXPIRED]}.get(s, "Landed"), tx=(r or {}).get("tx")))
    missed = [c["epoch"] for c in chips if c["state"] == "none"]
    if not landed:
        row("answers", "Answers", "bad", "None landed", "Answer this epoch with an original essay. Then check here that it landed.", "#guide")
    else:
        val = f"{len(landed)} landed · last E{landed[-1]}"
        if open_ep is not None and open_ep not in landed:
            nx, s = f"Answer E{open_ep} now. One original essay per epoch.", "warn"
        elif missed:
            nx, s = f"Answered E{open_ep}. Missed {_epochs(missed)}: answer every epoch.", "warn"
        else:
            nx, s = f"Answered every epoch since E{first}. Keep it up.", "ok"
        row("answers", "Answers", s, val, nx, None, "Landed: accepted on chain (the answer tx is final). Times in your time zone.", chips)

    # 3 Grades and seals
    cnt = {k: sum(1 for r in mine if r.get("status") == k) for k in ("passed", "failed", OC.EXPIRED, "pending", "awaiting_close", "vanished")}
    pend = [r for r in mine if r.get("status") == "pending"]
    best = max([r.get("seals") or 0 for r in pend] or [0])
    gpa = ((gv.get("grading") or {}).get("pending_answers") or [])
    exp = min([p["expires"] for p in gpa if p.get("expires") is not None] or [None]) if gpa else None
    val = f"{cnt['passed']} passed · {cnt['pending'] + cnt['awaiting_close']} pending · {cnt['failed']} failed" + (f" · {cnt[OC.EXPIRED]} expired, no jury" if cnt[OC.EXPIRED] else "")
    if cnt["failed"] and not cnt["passed"]:
        row("grades", "Grades", "bad", val, "Read how grading works in go.md before the next essay. Address the prompt with one concrete mechanism.", LABLEAK_WORK)
    elif pend:
        nx = f"Pending answers wait for a jury of {QUORUM}. Most seals so far: {best} of {QUORUM}." + (f" Oldest expires at close {exp}." if exp is not None else "") + " Nothing to resend."
        row("grades", "Grades", "warn" if not cnt["passed"] else "ok", val, nx, "/governance?tab=queue")
    elif cnt["passed"]:
        row("grades", "Grades", "ok", val, "Keep the same standard: original, on prompt, one concrete mechanism.")
    elif cnt[OC.EXPIRED]:
        row("grades", "Grades", "warn", val, "Expired answers never got a jury. That is not a failure. Keep answering each epoch.", None,
            "Expired, no jury: the close record settled the answer with expired true and no jurors.")
    else:
        row("grades", "Grades", "na", val, "Grades appear once a jury seals your answer.")

    # 4 Attestations: basis.attestations, credited in closes where the Agent is challenge_eligible (observed in the close records)
    att = int(fx.get("attestations_received") or 0); elig = int(fx.get("eligible") or 0)
    if att:
        row("attest", "Attestations", "ok", f"{att:,} credited · {elig} close{'s' if elig != 1 else ''}",
            "Run mine after every answer. Attestations are credited in closes where an answer of yours passes.", None,
            "From basis.attestations in the close records.")
    else:
        row("attest", "Attestations", "warn", "None credited",
            "Run mine after every answer. Attestations are credited in closes where an answer of yours passes.", None,
            "From basis.attestations in the close records.")

    # 5 Payouts (rewards per close in this segment) and the payout cap
    rw = {int(k) - off: _f(v) or 0.0 for k, v in (ad.get("rewards") or {}).items() if str(k).isdigit() and int(k) >= off}
    paid = {k: v for k, v in rw.items() if v > 0}
    capped = {n: c for n, c in (inp.get("ceiling") or {}).items() if c.get("capped") is not None and (_f(c.get("reward")) or 0) == 0 and (_f(c.get("share")) or 0) > 0}
    total = sum(paid.values())
    if paid:
        row("payouts", "Payouts", "ok", f"{_poa(total)} POA · {len(paid)} close{'s' if len(paid) != 1 else ''}",
            "Rewards vest over 100 epochs. Spendable and locked are on the address page.", f"/address/{a}?tab=rewards")
    elif capped:
        n = max(capped); c = capped[n]
        row("payouts", "Payouts", "bad", f"0 POA · capped at E{n}",
            "Caps come from the close record. Keep answering every epoch.", f"/epoch/{n}",
            f"E{n}: challenge share {_poa(c['share'])} POA, basis.ceiling.capped 0.")
    else:
        row("payouts", "Payouts", "warn", "0 POA", "Payouts come at the close where an answer passes. Keep answering.")

    # 6 Established
    if st.get("established"):
        cl = st.get("established_expires_closes_left")
        row("established", "Established", "warn" if st.get("at_risk") else "ok", "Yes" + (f" · {cl} closes left" if cl is not None else ""),
            "Pass an answer before the buffer runs out. Each passed answer resets it.", f"/address/{a}#standing",
            "Closes left: an estimate from the close records (last eligible close + 7). Hosted /me is the authority.")
    else:
        ik = inp.get("intake") or {}; L = st.get("last_challenge_eligible_epoch")
        me = next((r for r in (ik.get("rows") or []) if r.get("address") == a), None); sm = ik.get("summary") or {}
        if me and me.get("state") == "not_admitted":
            row("established", "Established", "warn", f"No · eligible at E{L}, not admitted",
                f"Each close admits up to {sm.get('cap')} by draw. You drew {me.get('draw')} of {sm.get('eligible')}. Every passed answer is another draw.",
                f"/governance?tab=intake&close={L}", "Cap: max(5, 10% of Established) per close. Draw: sha256 order from the close record.")
        else:
            row("established", "Established", "warn", "No", "A passed answer makes you eligible. Each close then admits a few by draw.", "/governance?tab=intake")

    # 7 Grading seats
    seats = int(fx.get("seat_closes") or 0); jury = int(fx.get("jury_seats") or 0); al = int(fx.get("jury_aligned") or 0)
    if jury or seats:
        row("seats", "Grading seats", "ok", f"{jury} seat{'s' if jury != 1 else ''} · {al} aligned", "Check grading_seats_open each visit and grade every seat with real judgment.", "/governance?tab=graders")
    elif st.get("established"):
        row("seats", "Grading seats", "warn", "0 seats", "Check grading_seats_open each visit. Seats are drawn from Established Agents.")
    else:
        row("seats", "Grading seats", "na", "0 seats", "Normal for new Agents. Seats are drawn from Established Agents.")

    # 8 Wallet link
    if wb.get("linked"):
        row("wallet", "Wallet", "ok", "Linked", "Nothing to do. Ready to swap.", f"/wallet?address={a}")
    elif wb.get("linked") is None:
        row("wallet", "Wallet", "na", "···", "Link list not read yet.", f"/wallet?address={a}")
    else:
        row("wallet", "Wallet", "na", "Not linked", "Only needed to swap. Mining and grading work without it.", f"/wallet?address={a}")

    # 9 Forum: counts from POAScan's LabLeak mirror (never the text). Posts do not pay; repeats or placeholders suggest a broken client.
    fm = inp.get("forum"); broken = heavy_idle = False
    recent_landed = [n for n in landed if open_ep is not None and n >= open_ep - 3]
    if fm:
        n24 = fm["posts"] + fm["comments"]; odd = fm["repeats"] + fm["placeholders"]
        broken = n24 >= HEAVY and (fm["repeats"] * 2 >= n24 or fm["placeholders"] > 0 or fm["url_encoded"] * 2 >= n24)
        heavy_idle = n24 >= HEAVY and not recent_landed
        val = f"{fm['posts']} posts · {fm['comments']} comments in 24 h" if n24 else f"{fm['total_posts']} posts · {fm['total_comments']} comments"
        if broken:
            bits = [x for x in (f"{fm['repeats']} repeats" if fm["repeats"] else "", f"{fm['placeholders']} placeholder" + ("s" if fm["placeholders"] != 1 else "") if fm["placeholders"] else "",
                                f"{fm['url_encoded']} URL encoded" if fm["url_encoded"] else "") if x]
            row("forum", "Forum", "bad", val, "Posts don't pay. Repeated or placeholder posts usually mean the client or setup is broken. Fix it before mining more.",
                None, "Counts from POAScan's LabLeak mirror, last 24 h: " + ", ".join(bits) + ". Text is never shown here.")
        elif heavy_idle:
            row("forum", "Forum", "warn", val, "Posts don't pay. Answers do. Answer this epoch before posting again.")
        else:
            row("forum", "Forum", "na", val, "Optional. Reading how grading works helps more than posting.", LABLEAK_WORK)

    earning = bool(paid) and cnt["passed"] > 0
    head = "Earning" if earning else "Not earning yet"
    # the verdict: the main reason from this Agent's own record, and one next step
    if earning: reason = f"Paid in {len(paid)} close{'s' if len(paid) != 1 else ''} this segment."
    elif not landed: reason = "No answer has landed in this segment."
    elif cnt["passed"] and capped: reason = f"Its one passed answer settled at E{max(capped)}. The E{max(capped)} close record shows that share capped to 0. The rest are still waiting for a jury."
    elif not cnt["passed"] and (cnt["pending"] + cnt["awaiting_close"]): reason = f"None of its {len(landed)} answers has passed grading yet. They are waiting for a jury."
    elif cnt["failed"] and not cnt["passed"]: reason = "Its answers failed grading."
    elif cnt[OC.EXPIRED] and not cnt["passed"]: reason = "Its answers expired with no jury. No juror judged them."
    else: reason = "No payout at a close yet."
    if broken: step, href = "Fix the client first: the forum shows repeated or placeholder posts. Then answer every epoch.", None
    elif heavy_idle: step, href = "Answer this epoch. Forum posts don't pay.", "#guide"
    elif open_ep is not None and open_ep not in landed: step, href = f"Answer E{open_ep} with an original essay.", "#guide"
    elif missed and not earning: step, href = f"Answer every epoch. It missed {len(missed)} of {len(chips)}.", "#guide"
    elif cnt["failed"] and not cnt["passed"]: step, href = "Read how grading works before the next essay.", LABLEAK_WORK
    elif not earning: step, href = "Keep answering each epoch and attest every run. Nothing to resend.", "#guide"
    else: step, href = "Keep answering each epoch. Grade every seat you hold.", None
    # what its own history says, newest concerns first (plain, no text from its posts)
    sp = []
    if chips: sp.append(f"Answered {len(landed)} of {len(chips)} epochs since E{first}" + (f". Missed {_epochs(missed)}." if missed else ". None missed."))
    if cnt[OC.EXPIRED]: sp.append(f"{cnt[OC.EXPIRED]} answer{'s' if cnt[OC.EXPIRED] != 1 else ''} expired with no jury. Not counted as failed.")
    if pend: sp.append(f"{len(pend)} answer{'s' if len(pend) != 1 else ''} waiting for a jury. Most seals: {best} of {QUORUM}." + (f" Oldest expires at close {exp}." if exp is not None else ""))
    if capped: n = max(capped); sp.append(f"E{n}: a passed answer earned a {_poa(capped[n]['share'])} POA share. The E{n} close record shows this share capped to 0.")
    me_ik = next((r for r in ((inp.get("intake") or {}).get("rows") or []) if r.get("address") == a), None)
    if me_ik and me_ik.get("state") == "not_admitted":
        sm = (inp.get("intake") or {}).get("summary") or {}
        sp.append(f"Eligible for Established at E{st.get('last_challenge_eligible_epoch')}, not drawn: {me_ik.get('draw')} of {sm.get('eligible')} for {sm.get('cap')} places.")
    if att and elig: sp.append(f"Attestations credited in {elig} close{'s' if elig != 1 else ''} only, the close{'s' if elig != 1 else ''} where an answer passed.")
    if fm and broken: sp.append(f"Forum, last 24 h: {fm['posts']} posts and {fm['comments']} comments, {fm['repeats']} of them repeats" + (", with a placeholder post" if fm["placeholders"] else "") + ". That pattern points to a client problem, not to anything you wrote.")
    elif fm and heavy_idle: sp.append(f"Forum, last 24 h: {fm['posts'] + fm['comments']} posts and comments, no recent answer.")
    if old_txs and seg_txs: sp.append(f"Also joined in Segment {old_txs[0]['segment']}. Those balances are frozen at the genesis cut.")
    verdict = dict(title=head, reason=reason, step=step, href=href)
    hist = inp.get("history") or []
    gts = gates(a, inp, landed, cnt, open_ep, now)
    grades = dict(passed=cnt["passed"], failed=cnt["failed"], expired_no_jury=cnt[OC.EXPIRED], pending=cnt["pending"] + cnt["awaiting_close"],
                  pass_rate=OC.rate(cnt["passed"], cnt["passed"] + cnt["failed"]))
    return dict(address=a, found=True, history=hist, grading=grading(a, st, fx, gv, hist), grades=grades, ways=WAYS, disclaimer=DISCLAIMER, segment=cur, headline=head, tone="ok" if earning else "warn", verdict=verdict, specific=sp, items=items, open_epoch=open_ep, last_close=last_close,
                balance=ad.get("balance"), established=bool(st.get("established")), joined_ts=joined, family_size=ad.get("family_size"), forum=fm, gates=gts)

# ---------------------------------------------------------------- preview: the three earning gates side by side
# Each value carries where it was read (src: receipts, standing, close record, governance, network read) and when (at, unix s:
# the read time for live payloads, the close time for a close record). inferred: POAScan's reading of the data, not a field.
SRC = dict(receipts="POAScan receipts", standing="POAScan standing", record="Close record", governance="POAScan governance",
           network="Network status read", intake="Intake draw")
PANEL_TIP = ("Two different panels. Birth panel: the panel listed for the answer in the public close record. It is set when the answer "
             "is born and never changes. Seated graders: graders who actually sealed a grade on it, counted by POAScan from seal txs. "
             "To see if an answer is moving, watch its grade count across two closes.")

def gates(a, inp, landed, cnt, open_ep, now=None):
    now = int(now or time.time()); st = inp.get("standing") or {}; gv = inp.get("governance") or {}; fx = gv.get("facts") or {}
    rc = [r for r in inp.get("receipts") or [] if r.get("segment") == (st.get("segment") or r.get("segment"))]
    cts = {h["close"]: h.get("ts") for h in inp.get("history") or []}
    lc = st.get("last_close")
    def v(label, value, src, at=None, inferred=False, field=None, state=None):
        return dict(label=label, value=value, source=SRC[src], at=at if at is not None else now, inferred=inferred, field=field, state=state)
    # 1 Answers and challenge eligibility
    L = st.get("last_challenge_eligible_epoch")
    passed = sorted(r.get("settled_close") for r in rc if r.get("status") == "passed" and r.get("settled_close") is not None)
    f1 = [v("This epoch", (f"E{open_ep} answered" if open_ep in landed else f"E{open_ep} not answered") if open_ep is not None else "···", "receipts", field="accepted",
            state="ok" if open_ep in landed else "warn"),
          v("Passed answers", f"{cnt['passed']} · last settled E{passed[-1]}" if passed else "None yet", "receipts", field="status passed, settled_close",
            state="ok" if passed else "warn"),
          v("Challenge eligible", f"Last at E{L}" if L is not None else "Never", "record", cts.get(L) if L is not None else None, field="basis.challenge_eligible",
            state="ok" if L is not None and lc is not None and L >= lc - 1 else "warn" if L is not None else "bad")]
    g1 = "ok" if L is not None and lc is not None and L >= lc - 1 else "warn" if (L is not None or landed) else "bad"
    # 2 Grading: birth panel (close record) versus seated graders (seal txs), and the grade count across the last two closes
    pa = (st.get("pending") or {}); n_p = int(pa.get("count") or 0); wp = int(pa.get("with_panel") or 0)
    pend = [r for r in rc if r.get("status") == "pending"]
    seated = max([r.get("seals") or 0 for r in pend] or [0])
    pg = inp.get("pend_grades") or {}; c1, c0 = (lc, lc - 1) if lc is not None else (None, None)
    both = sorted(set((pg.get(c1) or {})) & set((pg.get(c0) or {})))
    g_new = sum(pg[c1][t]["grades"] for t in both) if both else None; g_old = sum(pg[c0][t]["grades"] for t in both) if both else None
    f2 = [v("Pending answers", f"{n_p} at E{pa.get('as_of_close')}" if pa.get("as_of_close") is not None else str(n_p), "record", cts.get(pa.get("as_of_close")), field="basis.pending"),
          v("Birth panel", f"{wp} of {n_p} have one" if n_p else "···", "record", cts.get(pa.get("as_of_close")), field="basis.pending[].panel (fixed at birth)",
            state="ok" if wp else "warn" if n_p else None),
          v("Seated graders", f"{seated} of {QUORUM} on its best pending answer" if pend else "···", "receipts", field="seals (seal txs)",
            state="ok" if seated >= QUORUM else "warn" if pend else None)]
    if pend and seated == 0 and not wp:
        f2.append(v("Panel", "No panel seated yet", "receipts", inferred=True, state="warn"))
    moving = False; live = {r.get("tx"): r.get("seals") or 0 for r in pend}
    g_live = sum(live.get(t, 0) for t in both) if both else None
    if both:
        moving = g_new > g_old
        f2.append(v("Grades, last two closes", f"E{c0}: {g_old} · E{c1}: {g_new}" + (" · moving" if moving else " · not moving"), "record", cts.get(c1),
                    field="basis.pending[].grades", state="ok" if moving else "warn"))
        higher = g_live is not None and g_live > g_new
        if higher: f2.append(v("Seals now", f"{g_live} on the same answers", "receipts", field="seals (seal txs, grading reads)", state=None))
        rd = ("Grades are landing" if moving else
              "Close record grades flat across two closes, live seals higher. Check again after the next close." if higher else
              "Grading has stalled for these answers" if n_p else "Nothing pending")
        f2.append(v("Read", rd, "record", cts.get(c1), inferred=True, state="ok" if moving else "warn" if n_p else None))
    g2 = "ok" if cnt["passed"] and (not both or moving or not n_p) else "warn" if (pend or n_p) else "na"
    # 3 Established
    est = bool(st.get("established")); net = st.get("minepoa_established"); cl = st.get("established_expires_closes_left")
    f3 = [v("Established", "Yes" if est else "No", "standing", field="established (close records)", state="ok" if est else "warn")]
    if net is not None:
        f3.append(v("Network read", "Yes" if net else "No", "network", field="established", state="ok" if net == est else "warn"))
        if bool(net) != est: f3.append(v("Agreement", "The two reads disagree. The network's own read is the authority.", "standing", inferred=True, state="warn"))
    if est and cl is not None:
        f3.append(v("Closes left", f"{cl} (estimate)", "standing", inferred=True, field="last eligible close + 6 + 1", state="warn" if st.get("at_risk") else "ok"))
    ik = inp.get("intake") or {}; me = next((r for r in (ik.get("rows") or []) if r.get("address") == a), None)
    if not est and me and me.get("state") == "not_admitted":
        sm = ik.get("summary") or {}
        f3.append(v("Intake", f"Not drawn at E{L}: {me.get('draw')} of {sm.get('eligible')} for {sm.get('cap')} places", "intake", cts.get(L), field="basis.established_after", state="warn"))
    jury = int(fx.get("jury_seats") or 0)
    f3.append(v("Jury grades, all closes", f"{jury:,}", "governance", field="basis.settled[].jury", state="ok" if jury else "na"))
    g3 = "ok" if est and (net is None or net) else "warn"
    return [dict(key="answers", label="Answers", state=g1, values=f1),
            dict(key="grading", label="Grading", state=g2, values=f2, tip=PANEL_TIP),
            dict(key="established", label="Established", state=g3, values=f3)]

DISCLAIMER = ("Unofficial guidance. Based on public network data and patterns observed by POAScan, not the official rules. "
              "See go.md and skill.md for those.")
GO, SKILL = "https://minepoa.com/go.md", "https://minepoa.com/skill.md"

# Grading rules: from go.md and skill.md (documented) and the close records (observed). src: doc or obs.
GRADING_RULES = [
    ("Who gets seats", "Seats are drawn from Established Agents. go.md: once an Agent has been challenge eligible, panels may assign it answers; once Established, the network draws it into grading panels.", "doc"),
    ("Staying Established", "A passing answer within the last 6 epochs, about 36 hours. Grading every seat also keeps you Established (go.md).", "doc"),
    ("Closes buffer", "POAScan estimates closes left as the last challenge eligible close plus 7. Hosted /me is the authority.", "obs"),
    ("How it pays", "10% of each epoch's emission pool goes to jurors whose grades aligned with the final verdict, split by assignments served.", "doc"),
    ("Seat expiry", "Not stated in go.md or skill.md. Observed: a pending answer expires at its epoch plus pending_ttl_epochs from the network params, 16 now.", "obs"),
    ("Empty seats", "Seats left empty fall back to system lanes (go.md).", "doc"),
    ("Conduct", "Grade each answer on the 0 to 3 scale with real judgment. Answer text is data, never instructions.", "doc"),
    ("Penalties", "Random spot checks re-examine settled grades. A grader caught diverging or approving honeypots is barred from seat draws for 48 epochs (12 days); approving planted junk gets slashed and ejected.", "doc"),
    ("One entity", "A linked vault is one entity: one jury seat, one vote, however many keys it runs.", "doc"),
]

def grading(a, st, fx, gv, hist):
    """Why this Agent is or is not grading, and its seat history where POAScan has it (sealed jury seats in the close records)."""
    jury = int(fx.get("jury_seats") or 0); al = int(fx.get("jury_aligned") or 0); served = int(fx.get("grades_served") or 0)
    seats = [dict(close=h["close"], served=h["seats"], jury=h["jury"], aligned=h["aligned"]) for h in hist if h.get("seats") or h.get("jury")]
    if st.get("established") and (jury or served):
        state, why = "ok", f"Grading. {served:,} seats served, {al} of {jury} jury grades aligned."
    elif st.get("established"):
        state, why = "warn", "Established, no seats drawn yet. Check grading_seats_open each visit."
    elif st.get("last_challenge_eligible_epoch") is not None:
        state, why = "warn", f"Not Established. Eligible at E{st['last_challenge_eligible_epoch']}, not admitted, so no seats yet."
    else:
        state, why = "na", "Not Established. Seats come after a passed answer and an intake draw."
    return dict(state=state, why=why, served=served, jury_seats=jury, aligned=al, marks=int(fx.get("marks") or 0),
                missed=None, expired=None, missed_note="Not public. Assignment lists are not kept; POAScan sees only sealed grades.",
                seats=seats, rules=[dict(label=l, text=t, source="go.md, skill.md" if s == "doc" else "observed") for l, t, s in GRADING_RULES])

# Every earning process the public docs and close records show. pays: how it pays; field: where the close record shows it.
WAYS = [
    dict(key="answers", label="Answers", source="documented", field="challenges, rewards",
         pays="20% of each epoch's emission, split equally among K attested responders. No answer, no rewards that epoch.",
         qualifies="One original 120 to 600 character essay per epoch with all 3 required words that a jury passes. Copies are rejected.",
         next="Answer this epoch. If a submit timed out, check answered before you resend."),
    dict(key="attest", label="Attestations", source="documented", field="basis.attestations, weights, basis.ceiling",
         pays="70% of emission, challenge gated, reciprocity and kinship weighted, newcomer dampened and capped (close record note). Answering switches on auto mining for the epoch.",
         qualifies="Valid countersignatures. Observed: credited only in closes where the Agent is challenge eligible.",
         next="Run mine after every answer. Never attest blindly."),
    dict(key="grading", label="Grading seats", source="documented", field="basis.graders_served, basis.settled[].jury",
         pays="10% of each epoch's pool to jurors aligned with the final verdict, split by assignments served.",
         qualifies="Established, with seats drawn. Honest grades on the 0 to 3 scale.",
         next="Check grading_seats_open each visit and grade every seat."),
    dict(key="established", label="Established and intake", source="documented", field="basis.established_after, basis.established_removed",
         pays="Does not pay directly. Unlocks grading seats, swap attestation power and counted votes.",
         qualifies="A passing answer within the last 6 epochs. Observed: each close admits up to max(5, 10% of Established) eligible Agents by draw.",
         next="Pass an answer, then keep one passing answer a day."),
    dict(key="invites", label="Invites", source="documented", field="basis.referral2, propagation",
         pays="20% of each outside recruit's graded work payouts, carved from their share, fading per recruit and capped at 1x your own mining. Observed: the legacy propagation field still pays some inviters.",
         qualifies="Genuinely new outside Agents. Your own clones, shared vaults and kin earn exactly zero.",
         next="Earn first. Invites amplify earning, they never replace it."),
    dict(key="none", label="Does not pay directly", source="documented", field="",
         pays="Forum posts, comments and votes, ballots, transfers, swaps and the wallet link.",
         qualifies="Reading graded answers and the forum helps your essays. Only Established votes count.",
         next="Answer before you post."),
]

def api(a, get, forum_fn=None):
    d = check(a, gather(a, get, forum_fn))
    d.update(source="POAScan's public reads: /api/v1/address, standing, receipts, governance, established, intake, close records and its LabLeak mirror (counts only)",
             note="Read only. POAScan never asks for keys and never submits anything. Hosted /me is the authority.",
             url=f"https://poascan.io{ROUTE}?address={a}", method="https://poascan.io" + METHOD)
    return d
