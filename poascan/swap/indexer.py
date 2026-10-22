"""Swap jobs for the host scheduler: the open-offer book (/api/swaps, 60 s), swap tx details (once each) and the
SOL/ETH USD reference (CoinGecko, 15 min). Upstream reads go through the host's rate-limited client."""
import json, time, logging, urllib.request
from . import host as H, config as C

log = logging.getLogger("poascan.swap")

REF_KEYS = ("ref", "ext_ref", "external_ref", "proof_ref", "tx_ref", "payment_ref", "broadcast_sig", "ext_sig")
def _ref(b):
    """External payment ref of a swap-fill body: top level or under proof (minepoa puts it at proof.ref)."""
    for src in (b, b.get("proof") if isinstance(b.get("proof"), dict) else {}):
        r = next((src[k] for k in REF_KEYS if isinstance(src.get(k), str) and src[k]), None)
        if r: return r
    return None

def _f(x):
    try: return float(x)
    except Exception: return None

# ---- offer state rules ----
# Book (SC-006, SC-021): an offer the upstream book lists is 'open' until its expires_ts, then 'expired', whether or not
# the book still lists it. An open offer missing from the book is 'delisted' (before expiry) or 'expired' only after
# MISS_RUNS reads in a row without it, so one empty or partial book (maintenance) never flips every offer.
# Settlement (SC-005): a swap-fill or swap-cancel tx changes an offer only once the ledger marks it final. Among an
# offer's final fills and cancels, the earliest by ledger ts wins (ties: the lower txid); later ones are ignored. A
# non-final swap tx stays pending in swap_events (final=0), is read again every RECHECK_S (RECHECK_SLOW_S once it is a
# day old) until it is final, and never counts in status, fills, price, volume or market cap until then. A pending tx
# the node no longer knows (HTTP 404) is marked dropped and never applies.
MISS_RUNS = 2
DROP_AFTER_S = 3600   # a pending swap tx the node does not know is dropped only once it is this old
RECHECK_S, RECHECK_SLOW_S, SLOW_AFTER_S = 600, 3600, 86400
NEW_PER_RUN, RECHECK_PER_RUN = 20, 5
_miss = {}   # offer_id -> consecutive book reads without it (memory only)
_all = [False]   # first run after start: every settled offer is resolved once under these rules

def _book_status(exp, now):
    return "expired" if exp is not None and _f(exp) is not None and _f(exp) <= now else "open"

def job_swaps():
    now = int(time.time())
    try:
        d = H.fetch(C.SWAPS_EP, cond=True)
        if d is H.NOT_MODIFIED: d = H.get_blob("swaps")[0]   # same book as last read (304): run the rules on the stored copy
        elif isinstance(d, list): H.put_blob("swaps", d)
        if isinstance(d, list): apply_book(d, now)
    except H.Busy as e:
        log.warning("/api/swaps: %s", e)
    ingest_events(now)
    for r in H.q("SELECT s.offer_id, e.json AS body FROM swaps s JOIN swap_events e ON e.txid=s.fill_txid WHERE s.status='filled' AND (s.ext_ref IS NULL OR s.ext_ref='')"):
        try: ref = _ref(json.loads(r["body"]))   # local backfill, no upstream call
        except Exception: ref = None
        if ref: H.write("UPDATE swaps SET ext_ref=? WHERE offer_id=?", (ref, r["offer_id"]))

def apply_book(d, now):
    """One upstream book read: upsert listed offers (open, or expired past expires_ts), then handle the ones it lacks."""
    for o in d:
        if not isinstance(o, dict) or not o.get("offer_id"): continue
        w = o.get("want") or {}; fee = o.get("fee") or {}
        H.write("""INSERT INTO swaps(offer_id,maker,poa,chain,asset,want,pay_to,expires_ts,status,fee_bp,last_open_seen,updated)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(offer_id) DO UPDATE SET status=CASE WHEN swaps.status IN ('filled','cancelled') THEN swaps.status
          ELSE excluded.status END, last_open_seen=excluded.last_open_seen, updated=excluded.updated, fee_bp=excluded.fee_bp, expires_ts=excluded.expires_ts""",
                (o["offer_id"], o.get("maker"), _f(o.get("poa_locked")), w.get("chain"), w.get("asset"), _f(w.get("amount")), w.get("to"),
                 o.get("expires_ts"), _book_status(o.get("expires_ts"), now), fee.get("fee_bp"), now, now))
    listed = {o["offer_id"] for o in d if isinstance(o, dict) and o.get("offer_id")}
    for k in list(_miss):
        if k in listed: _miss.pop(k, None)
    for r in H.q("SELECT offer_id, expires_ts FROM swaps WHERE status IN ('open','delisted')"):
        exp = r["expires_ts"]; past = exp is not None and exp <= now
        if r["offer_id"] in listed: continue
        if past:   # past expiry: expired, listed or not
            H.write("UPDATE swaps SET status='expired', updated=? WHERE offer_id=? AND status IN ('open','delisted')", (now, r["offer_id"])); continue
        n = _miss[r["offer_id"]] = _miss.get(r["offer_id"], 0) + 1
        if n >= MISS_RUNS:
            H.write("UPDATE swaps SET status='delisted', updated=? WHERE offer_id=? AND status='open'", (now, r["offer_id"]))
    if len(_miss) > 10000: _miss.clear()

def _is_final(d, marks):
    m = marks.get(d.get("id"))
    return bool(d.get("final")) or bool(m and m[1])

def ingest_events(now):
    """Read each archived swap tx's detail once, then re-read the pending (non-final) ones until final; resolve offers."""
    known = {r["txid"]: r for r in H.q("SELECT txid, offer_id, final, checked, dropped, first_seen FROM swap_events")}
    ids = H.swap_tx_ids(); marks = H.tx_marks(ids); touched = set(); new = rech = 0
    for tid in ids:
        k = known.get(tid)
        if k and (k["final"] or k["dropped"]): continue
        if k:   # pending: the explorer feed may already show it final (no upstream read), else re-read on schedule
            m = marks.get(tid)
            if m and m[1]:
                H.write("UPDATE swap_events SET final=1, checked=? WHERE txid=?", (now, tid)); touched.add(k["offer_id"]); continue
            age = now - (k["first_seen"] or now); every = RECHECK_SLOW_S if age > SLOW_AFTER_S else RECHECK_S
            if k["checked"] and now - k["checked"] < every: continue
            if rech >= RECHECK_PER_RUN: continue
            rech += 1
        else:
            if new >= NEW_PER_RUN: continue
            new += 1
        try: d = H.get_tx_detail(tid, bg=H.SWAP_TX_EP)
        except H.Missing:
            if k and now - (k["first_seen"] or now) >= DROP_AFTER_S:   # still unknown to the node an hour on: dropped
                H.write("UPDATE swap_events SET dropped=1, checked=? WHERE txid=?", (now, tid)); touched.add(k["offer_id"])
            elif k: H.write("UPDATE swap_events SET checked=? WHERE txid=?", (now, tid))
            continue
        except H.Busy: break
        if not d or not d.get("id"): continue
        o = ingest_swap_tx(d, final=_is_final(d, marks), now=now)
        if o: touched.add(o)
        time.sleep(0.5)
    if not _all[0]:
        touched |= {r["offer_id"] for r in H.q("SELECT DISTINCT offer_id FROM swap_events WHERE kind IN ('swap-fill','swap-cancel')")}
        touched |= {r["offer_id"] for r in H.q("SELECT offer_id FROM swaps WHERE status IN ('filled','cancelled')")}
        _all[0] = True
    for o in touched: resolve(o, now)

def ingest_swap_tx(d, final=None, now=None):
    """Store one swap tx (final or pending) and, for an offer tx, the offer's own fields. Returns the offer id.
    Fills and cancels change the offer only through resolve()."""
    b = d.get("body") or {}; typ = d.get("type"); ts = int(d.get("ts") or 0); now = int(now or time.time())
    final = bool(d.get("final")) if final is None else bool(final)
    offer = b.get("offer") or b.get("offer_id") or (b.get("fill") or {}).get("offer")
    if typ == "swap-offer":
        offer = d["id"]; w = b.get("want") or {}
        H.write("""INSERT INTO swaps(offer_id,maker,poa,chain,asset,want,pay_to,expires_ts,created_ts,status,memo,updated)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(offer_id) DO UPDATE SET created_ts=excluded.created_ts, memo=excluded.memo,
          maker=COALESCE(swaps.maker, excluded.maker), poa=COALESCE(swaps.poa, excluded.poa), chain=COALESCE(swaps.chain, excluded.chain),
          asset=COALESCE(swaps.asset, excluded.asset), want=COALESCE(swaps.want, excluded.want), pay_to=COALESCE(swaps.pay_to, excluded.pay_to)""",
                (offer, d.get("from_addr"), _f(b.get("amount") or d.get("amount")), w.get("chain"), w.get("asset"), _f(w.get("amount")), w.get("to"),
                 b.get("expires_ts"), ts, _book_status(b.get("expires_ts"), now), b.get("memo") or d.get("memo"), now))
    H.write("""INSERT INTO swap_events(txid,offer_id,kind,addr,ts,json,final,checked,dropped,first_seen) VALUES(?,?,?,?,?,?,?,?,0,?)
      ON CONFLICT(txid) DO UPDATE SET offer_id=excluded.offer_id, kind=excluded.kind, addr=excluded.addr, ts=excluded.ts, json=excluded.json,
      final=MAX(COALESCE(swap_events.final,0), excluded.final), checked=excluded.checked, dropped=0""",
            (d["id"], offer, typ, d.get("from_addr"), ts, json.dumps(b)[:20000], 1 if final else 0, now, now))
    return offer

def resolve(offer, now=None):
    """Offer status from its final fills and cancels (rule above); with none, the book status (open, expired, delisted)."""
    if not offer: return
    now = int(now or time.time())
    r = H.q1("SELECT * FROM swaps WHERE offer_id=?", (offer,))
    if not r: return
    if H.q1("SELECT 1 AS x FROM swap_events WHERE offer_id=? AND kind IN ('swap-fill','swap-cancel') AND final=0 AND dropped=0 AND checked IS NULL", (offer,)):
        return   # an event from before 1.26.3 not yet re-read: leave the offer as it is until it has been
    ev = H.q("SELECT txid, kind, addr, ts, json FROM swap_events WHERE offer_id=? AND kind IN ('swap-fill','swap-cancel') AND final=1 AND dropped=0 "
             "ORDER BY ts, txid LIMIT 1", (offer,))
    w = ev[0] if ev else None
    if w and w["kind"] == "swap-fill":
        try: ref = _ref(json.loads(w["json"] or "{}"))
        except Exception: ref = None
        same = r.get("fill_txid") == w["txid"]
        H.write("UPDATE swaps SET status='filled', taker=?, fill_txid=?, fill_ts=?, ext_ref=COALESCE(?, CASE WHEN ? THEN ext_ref END), "
                "fill_usd=CASE WHEN ? THEN fill_usd END, cancel_txid=NULL, cancel_ts=NULL, updated=? WHERE offer_id=?",
                (w["addr"], w["txid"], w["ts"], ref, 1 if same else 0, 1 if same else 0, now, offer))
        a = (r.get("asset") or "").upper(); fx = H.get_blob("fx")[0] or {}; rate = 1.0 if a == "USDC" else fx.get(a)
        if rate and now - (w["ts"] or 0) < 3 * 3600:   # only near fill time; older fills fall back to the current reference
            H.write("UPDATE swaps SET fill_usd=? WHERE offer_id=? AND fill_usd IS NULL", (rate, offer))
    elif w:
        H.write("UPDATE swaps SET status='cancelled', cancel_txid=?, cancel_ts=?, taker=NULL, fill_txid=NULL, fill_ts=NULL, ext_ref=NULL, fill_usd=NULL, "
                "updated=? WHERE offer_id=?", (w["txid"], w["ts"], now, offer))
    elif r.get("status") in ("filled", "cancelled"):   # no final settlement (dropped or never final): back to the book state
        exp = r.get("expires_ts"); st = "expired" if exp is not None and exp <= now else ("open" if (r.get("last_open_seen") or 0) >= now - 180 else "delisted")
        H.write("UPDATE swaps SET status=?, taker=NULL, fill_txid=NULL, fill_ts=NULL, ext_ref=NULL, fill_usd=NULL, cancel_txid=NULL, cancel_ts=NULL, "
                "updated=? WHERE offer_id=?", (st, now, offer))

def job_fx():
    """Public USD reference for SOL/ETH (CoinGecko simple price). Display only; POA itself has no market price."""
    try:
        req = urllib.request.Request("https://api.coingecko.com/api/v3/simple/price?ids=solana,ethereum&vs_currencies=usd", headers={"User-Agent": H.UA})
        with urllib.request.urlopen(req, timeout=20) as r: d = json.loads(r.read())
        fx = {"SOL": d.get("solana", {}).get("usd"), "ETH": d.get("ethereum", {}).get("usd"), "src": "CoinGecko"}
        if fx["SOL"] or fx["ETH"]: H.put_blob("fx", fx)
    except Exception as e:
        log.warning("fx: %s", e)

# name, fn, interval seconds, upstream endpoint key for the host's backoff
JOBS = [("swaps", job_swaps, 60, C.SWAPS_EP), ("fx", job_fx, 900, None)]
