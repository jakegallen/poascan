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

def job_swaps():
    now = int(time.time())
    try:
        d = H.fetch(C.SWAPS_EP)
        if isinstance(d, list):
            H.put_blob("swaps", d)
            for o in d:
                w = o.get("want") or {}; fee = o.get("fee") or {}
                H.write("""INSERT INTO swaps(offer_id,maker,poa,chain,asset,want,pay_to,expires_ts,status,fee_bp,last_open_seen,updated)
                  VALUES(?,?,?,?,?,?,?,?,'open',?,?,?) ON CONFLICT(offer_id) DO UPDATE SET status=CASE WHEN swaps.status IN ('filled','cancelled') THEN swaps.status ELSE 'open' END,
                  last_open_seen=excluded.last_open_seen, updated=excluded.updated, fee_bp=excluded.fee_bp, expires_ts=excluded.expires_ts""",
                        (o["offer_id"], o.get("maker"), _f(o.get("poa_locked")), w.get("chain"), w.get("asset"), _f(w.get("amount")), w.get("to"),
                         o.get("expires_ts"), fee.get("fee_bp"), now, now))
            open_ids = {o["offer_id"] for o in d}
            for r in H.q("SELECT offer_id, expires_ts FROM swaps WHERE status='open'"):
                if r["offer_id"] not in open_ids:
                    H.write("UPDATE swaps SET status=?, updated=? WHERE offer_id=?", ("expired" if (r["expires_ts"] or 0) < now else "delisted", now, r["offer_id"]))
    except H.Busy as e:
        log.warning("/api/swaps: %s", e)
    for r in H.q("SELECT s.offer_id, e.json AS body FROM swaps s JOIN swap_events e ON e.txid=s.fill_txid WHERE s.status='filled' AND (s.ext_ref IS NULL OR s.ext_ref='')"):
        try: ref = _ref(json.loads(r["body"]))   # local backfill, no upstream call
        except Exception: ref = None
        if ref: H.write("UPDATE swaps SET ext_ref=? WHERE offer_id=?", (ref, r["offer_id"]))
    known = {r["txid"] for r in H.q("SELECT txid FROM swap_events")}
    for tid in H.swap_tx_ids():
        if tid in known: continue
        try: d = H.get_tx_detail(tid)
        except H.Busy: break
        if not d or not d.get("id") or not d.get("final") and time.time() - (d.get("ts") or 0) < 3600: continue
        ingest_swap_tx(d); time.sleep(0.5)

def ingest_swap_tx(d):
    b = d.get("body") or {}; typ = d.get("type"); ts = int(d.get("ts") or 0); now = int(time.time())
    offer = b.get("offer") or b.get("offer_id") or (b.get("fill") or {}).get("offer")
    if typ == "swap-offer":
        offer = d["id"]; w = b.get("want") or {}
        H.write("""INSERT INTO swaps(offer_id,maker,poa,chain,asset,want,pay_to,expires_ts,created_ts,status,memo,updated)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(offer_id) DO UPDATE SET created_ts=excluded.created_ts, memo=excluded.memo,
          maker=COALESCE(swaps.maker, excluded.maker), poa=COALESCE(swaps.poa, excluded.poa), chain=COALESCE(swaps.chain, excluded.chain),
          asset=COALESCE(swaps.asset, excluded.asset), want=COALESCE(swaps.want, excluded.want), pay_to=COALESCE(swaps.pay_to, excluded.pay_to)""",
                (offer, d.get("from_addr"), _f(b.get("amount") or d.get("amount")), w.get("chain"), w.get("asset"), _f(w.get("amount")), w.get("to"),
                 b.get("expires_ts"), ts, "expired" if (b.get("expires_ts") or 0) < now else "open", b.get("memo") or d.get("memo"), now))
    elif typ == "swap-fill" and offer:
        ref = _ref(b)
        H.write("UPDATE swaps SET status='filled', taker=?, fill_txid=?, fill_ts=?, ext_ref=?, updated=? WHERE offer_id=?",
                (d.get("from_addr"), d["id"], ts, ref, now, offer))
        r = H.q1("SELECT asset FROM swaps WHERE offer_id=?", (offer,)) or {}; a = (r.get("asset") or "").upper()
        fx = H.get_blob("fx")[0] or {}; rate = 1.0 if a == "USDC" else fx.get(a)
        if rate and now - ts < 3 * 3600:   # only near fill time; older fills fall back to the current reference
            H.write("UPDATE swaps SET fill_usd=? WHERE offer_id=? AND fill_usd IS NULL", (rate, offer))
    elif typ == "swap-cancel" and offer:
        H.write("UPDATE swaps SET status='cancelled', cancel_txid=?, cancel_ts=?, updated=? WHERE offer_id=? AND status!='filled'", (d["id"], ts, now, offer))
    H.write("INSERT OR REPLACE INTO swap_events VALUES(?,?,?,?,?,?)", (d["id"], offer, typ, d.get("from_addr"), ts, json.dumps(b)[:20000]))

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
