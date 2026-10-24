"""Offer state corrections from public evidence, shared by the swap API and pages. The stored rows are untouched."""
import time
from . import host as H

def _iso(ts): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None

OPEN_AT_CUT_S = 900   # an offer the book listed within this many seconds before a boundary was open at it (the book is read every 60 s)

def _correct(r, cuts, evid):
    """State corrections from public evidence, applied to the API row (the stored row is untouched):
    * an offer the book still listed just before a segment boundary, never filled or cancelled, reads refunded at that
      boundary, with refund_basis naming the boundary notice; refund_txid stays null (no per-offer refund tx is public).
    * an expired offer whose swap-fill tx is shown settled by public balances (host fill_evidence) reads filled, with
      fill_basis "balances" and the evidence; fill_final stays false (the ledger never marked that tx final)."""
    oid = r.get("offer_id"); e = evid.get(oid)
    if e and r.get("status") in ("expired", "delisted") and not r.get("fill_txid"):
        fe = next((x for x in H.q("SELECT txid, ts FROM swap_events WHERE txid=? AND offer_id=? AND kind='swap-fill' AND dropped=0", (e["fill_txid"], oid))), None) or (
            dict(txid=e["fill_txid"], ts=e.get("fill_ts")) if e.get("fill_ts") else None)
        if fe:
            r.update(status="filled", fill_txid=fe["txid"], fill_ts=fe["ts"], taker=e.get("taker"), fill_basis="balances",
                     fill_evidence={k: e[k] for k in ("basis", "taker_balance", "taker_balance_source", "checked_at") if k in e}, fill_final_ledger=False)
            return
    if r.get("status") not in ("expired", "delisted", "open") or r.get("fill_txid") or r.get("cancel_txid"): return
    for c in cuts:
        t = int(c["ts"]); seen = r.get("last_open_seen") or 0
        if (r.get("created_ts") or 0) < t and t - OPEN_AT_CUT_S <= seen < t + 60:
            r["status_before"] = r["status"]; r["status"] = "refunded"
            r["refund_basis"] = dict(kind="segment_boundary", label=c.get("label"), notice_id=c.get("notice_id"), notice_txid=c.get("txid"),
                                     ts=t, at=_iso(t), segment=c.get("segment"))
            return

def correct(rows):
    """Apply _correct to each row (dicts, in place) with the host's segment boundaries and fill evidence (optional hooks)."""
    cuts = H.segment_cuts() if hasattr(H, "segment_cuts") else []
    evid = H.fill_evidence() if hasattr(H, "fill_evidence") else {}
    for r in rows: _correct(r, cuts, evid)
    return rows
