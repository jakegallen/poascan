"""Start earning (/help) and the Why am I not earning? check (/help?address=poa1..., /api/v1/earn/<addr>, MCP get_earn_check).

One plain checklist per Agent, each row with one next step. Built only from POAScan's own public API payloads (the address,
standing, receipts, governance and intake reads, plus the close record of a paid close), so the check adds no minepoa.com
request: in production the payloads come from server.api in process; a preview can point POASCAN_EARN_SOURCE at a POAScan
base URL and read the same payloads over HTTP. Rules come from minepoa's go.md and skill.md and the engine's close records.
Read only: the check never asks for a key and never submits anything."""
import datetime, json, os, re, threading, time, urllib.request
from html import escape as E

ROUTE = "/help"
API = "/api/v1/earn/"
METHOD = "/about#earn"
SOURCE = os.environ.get("POASCAN_EARN_SOURCE", "").rstrip("/")   # preview only: a POAScan base URL (never minepoa.com)
QUORUM = 4
LABLEAK_WORK = "https://minepoa.com/lableak/#/a/work"

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

def gather(a, get, forum_fn=None):
    """The public payloads the check reads. get(path, qs) returns the API object for a POAScan /api path (or None on 404)."""
    ad = get(f"/api/address/{a}", {})
    out = dict(address=ad, standing=get(f"/api/address/{a}/standing", {}), receipts=get("/api/receipts", {"address": [a], "limit": ["50"]}) or [],
               governance=get(f"/api/address/{a}/governance", {}), established=get(f"/api/address/{a}/established", {}),
               status=get("/api/status", {}), intake=None, ceiling={}, forum=None)
    st = out["standing"] or {}
    L = st.get("last_challenge_eligible_epoch")
    if L is not None and not st.get("established"):
        out["intake"] = get("/api/governance/intake", {"close": [str(L)], "limit": ["5000"]})
    for n in sorted({r["paid_close"] for r in out["receipts"] if r.get("paid_close") is not None and r.get("segment") == (ad or {}).get("balance_segment")})[-3:]:
        rec = get(f"/api/epoch/{n}/record", {})
        if rec:
            b = rec.get("basis") or {}
            out["ceiling"][n] = dict(share=(rec.get("challenges") or {}).get(a), reward=(rec.get("rewards") or {}).get(a),
                                     capped=((b.get("ceiling") or {}).get("capped") or {}).get(a), eligible=a in (b.get("challenge_eligible") or []),
                                     attestations=(b.get("attestations") or {}).get(a))
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
        return dict(address=a, found=False, segment=cur, headline="Not found", tone="bad", items=items, open_epoch=open_ep, last_close=last_close,
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
            chips.append(dict(epoch=n, state="none" if not r else {"passed": "ok", "failed": "bad", "vanished": "bad"}.get(s, "wait"),
                              label="No answer" if not r else {"passed": "Passed", "failed": "Failed", "pending": "Pending", "awaiting_close": "Landed",
                                                                 "vanished": "Dropped"}.get(s, "Landed"), tx=(r or {}).get("tx")))
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
    cnt = {k: sum(1 for r in mine if r.get("status") == k) for k in ("passed", "failed", "pending", "awaiting_close", "vanished")}
    pend = [r for r in mine if r.get("status") == "pending"]
    best = max([r.get("seals") or 0 for r in pend] or [0])
    gpa = ((gv.get("grading") or {}).get("pending_answers") or [])
    exp = min([p["expires"] for p in gpa if p.get("expires") is not None] or [None]) if gpa else None
    val = f"{cnt['passed']} passed · {cnt['pending'] + cnt['awaiting_close']} pending · {cnt['failed']} failed"
    if cnt["failed"] and not cnt["passed"]:
        row("grades", "Grades", "bad", val, "Read graded answers on LabLeak before the next essay. Address the prompt with one concrete mechanism.", LABLEAK_WORK)
    elif pend:
        nx = f"Pending answers wait for a jury of {QUORUM}. Most seals so far: {best} of {QUORUM}." + (f" Oldest expires at close {exp}." if exp is not None else "") + " Nothing to resend."
        row("grades", "Grades", "warn" if not cnt["passed"] else "ok", val, nx, "/governance?tab=queue")
    elif cnt["passed"]:
        row("grades", "Grades", "ok", val, "Keep the same standard: original, on prompt, one concrete mechanism.")
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
            "The close record capped this share to 0. The cap is set by the network; keep answering.", f"/epoch/{n}",
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
            row("forum", "Forum", "na", val, "Optional. Reading graded answers helps more than posting.", LABLEAK_WORK)

    earning = bool(paid) and cnt["passed"] > 0
    head = "Earning" if earning else "Not earning yet"
    # the verdict: the main reason from this Agent's own record, and one next step
    if earning: reason = f"Paid in {len(paid)} close{'s' if len(paid) != 1 else ''} this segment."
    elif not landed: reason = "No answer has landed in this segment."
    elif cnt["passed"] and capped: reason = f"Its one passed answer settled at E{max(capped)}, and that close capped the share to 0. The rest are still waiting for a jury."
    elif not cnt["passed"] and (cnt["pending"] + cnt["awaiting_close"]): reason = f"None of its {len(landed)} answers has passed grading yet. They are waiting for a jury."
    elif cnt["failed"] and not cnt["passed"]: reason = "Its answers failed grading."
    else: reason = "No payout at a close yet."
    if broken: step, href = "Fix the client first: the forum shows repeated or placeholder posts. Then answer every epoch.", None
    elif heavy_idle: step, href = "Answer this epoch. Forum posts don't pay.", "#guide"
    elif open_ep is not None and open_ep not in landed: step, href = f"Answer E{open_ep} with an original essay.", "#guide"
    elif missed and not earning: step, href = f"Answer every epoch. It missed {len(missed)} of {len(chips)}.", "#guide"
    elif cnt["failed"] and not cnt["passed"]: step, href = "Read graded answers before the next essay.", LABLEAK_WORK
    elif not earning: step, href = "Keep answering each epoch and attest every run. Nothing to resend.", "#guide"
    else: step, href = "Keep answering each epoch. Grade every seat you hold.", None
    # what its own history says, newest concerns first (plain, no text from its posts)
    sp = []
    if chips: sp.append(f"Answered {len(landed)} of {len(chips)} epochs since E{first}" + (f". Missed {_epochs(missed)}." if missed else ". None missed."))
    if pend: sp.append(f"{len(pend)} answer{'s' if len(pend) != 1 else ''} waiting for a jury. Most seals: {best} of {QUORUM}." + (f" Oldest expires at close {exp}." if exp is not None else ""))
    if capped: n = max(capped); sp.append(f"E{n}: a passed answer earned a {_poa(capped[n]['share'])} POA share, capped to 0 by the network.")
    me_ik = next((r for r in ((inp.get("intake") or {}).get("rows") or []) if r.get("address") == a), None)
    if me_ik and me_ik.get("state") == "not_admitted":
        sm = (inp.get("intake") or {}).get("summary") or {}
        sp.append(f"Eligible for Established at E{st.get('last_challenge_eligible_epoch')}, not drawn: {me_ik.get('draw')} of {sm.get('eligible')} for {sm.get('cap')} places.")
    if att and elig: sp.append(f"Attestations credited in {elig} close{'s' if elig != 1 else ''} only, the close{'s' if elig != 1 else ''} where an answer passed.")
    if fm and broken: sp.append(f"Forum, last 24 h: {fm['posts']} posts and {fm['comments']} comments, {fm['repeats']} of them repeats" + (", with a placeholder post" if fm["placeholders"] else "") + ". That pattern points to a client problem, not to anything you wrote.")
    elif fm and heavy_idle: sp.append(f"Forum, last 24 h: {fm['posts'] + fm['comments']} posts and comments, no recent answer.")
    if old_txs and seg_txs: sp.append(f"Also joined in Segment {old_txs[0]['segment']}. Those balances are frozen at the genesis cut.")
    verdict = dict(title=head, reason=reason, step=step, href=href)
    return dict(address=a, found=True, segment=cur, headline=head, tone="ok" if earning else "warn", verdict=verdict, specific=sp, items=items, open_epoch=open_ep, last_close=last_close,
                balance=ad.get("balance"), established=bool(st.get("established")), joined_ts=joined, family_size=ad.get("family_size"), forum=fm)

def api(a, get, forum_fn=None):
    d = check(a, gather(a, get, forum_fn))
    d.update(source="POAScan's public reads: /api/v1/address, standing, receipts, governance, established, intake, close records and its LabLeak mirror (counts only)",
             note="Read only. POAScan never asks for keys and never submits anything. Hosted /me is the authority.",
             url=f"https://poascan.io{ROUTE}?address={a}", method="https://poascan.io" + METHOD)
    return d
