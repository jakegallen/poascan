"""/swap/<offer_id>: one swap offer's status, read only (LabLeak 1332, comment 2913: a per-offer read so a taker never has
to call a money route to learn where a swap stands). Built from POAScan's own swap data through the swap module's public
API (swapclient.offer, the same as /api/v1/swaps/<offer_id>): no upstream request, nothing signed or sent. Shows the
stage history, the maker's escrow, the fill and the external payment ref with their txids, and next steps under the
safe swap rules (never send payment outside the network, check status before any re-take, never loop, stop at Filled,
Expired or Failed). The network fee is not shown here (it lives on the Swap Fee card)."""
import re, time
from html import escape as E
from . import swapclient as SC, prompts as PR
from .ui import card, table, utc, rel, addr_link, tx_link, plain, short, copy, na

OID_RX = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
CHAIN = {"solana": "Solana", "base": "Base", "ethereum": "Ethereum"}
EXPL = {"solana": ("https://solscan.io/account/", "https://solscan.io/tx/"), "base": ("https://basescan.org/address/", "https://basescan.org/tx/"),
        "ethereum": ("https://etherscan.io/address/", "https://etherscan.io/tx/")}
STATUS = "https://poaswap.io/status/"            # POASwap's canonical per-offer status page (read only); replaces the older track page
ADDR_STATUS = "https://poaswap.io/status?address="   # POASwap's status for every offer of one poa1 address
HEX64 = re.compile(r"^[0-9a-f]{64}$")

def status_url(oid):
    """POASwap's canonical status URL for an offer id (64 hex, lowercase), or None for anything else."""
    o = (oid or "").strip().lower()
    return STATUS + o if HEX64.match(o) else None

def addr_status_url(a):
    """POASwap's status URL for a poa1 address, or None."""
    return ADDR_STATUS + a if a and re.fullmatch(r"poa1[1-9A-HJ-NP-Za-km-z]{20,60}", a) else None
CHECK = "https://poaswap.io/api/v1/check?offer="
LABEL = {"open": "Open", "filled": "Filled", "cancelled": "Cancelled", "expired": "Expired", "delisted": "Delisted", "filling": "Fill landing"}
TONE = {"open": "ok", "filled": "ok", "filling": "warn", "cancelled": "", "expired": "", "delisted": "warn"}
EVENT = {"swap-offer": "Offered (escrow locked)", "swap-fill": "Filled", "swap-cancel": "Cancelled"}

def _ext(chain, v, tx=False):
    if not v: return '<span class="na">···</span>'
    e = EXPL.get((chain or "").lower())
    if not e: return f'<span class="mono">{E(short(v, 6, 4))}</span>{copy(v)}'
    return f'<a class="mono" href="{e[1 if tx else 0]}{E(v)}" target="_blank" rel="noopener noreferrer">{E(short(v, 6, 4))} ↗</a>{copy(v)}'

TERMINAL = ("filled", "cancelled", "expired")   # final per the API record: nothing inferred from events can override these

def stage(d):
    """Display stage. The status is the API record's (d is exactly what /api/v1/swaps/<offer_id> returns), and a
    terminal status (filled, cancelled, expired) always wins. Only a live offer (open, or delisted before its expiry)
    with a swap-fill tx seen but not yet final reads 'filling' (Fill landing); a fill that never finalized before the
    offer expired or was cancelled is history, not an in-flight state."""
    o = d["offer"]; st = o.get("status") or "open"
    if st in TERMINAL: return st
    if any(e.get("kind") == "swap-fill" and not e.get("final") for e in d.get("events") or []): return "filling"
    return st

def unfinished(d):
    """The offer's swap-fill txs that are archived but not final (not dropped), unless the offer is filled."""
    if (d["offer"].get("status") or "") == "filled": return []
    return [e for e in d.get("events") or [] if e.get("kind") == "swap-fill" and not e.get("final")]

UNSEEN_PAY = "Unknown: a fill was submitted but is not final, and POAScan can't see external-chain payments."

def next_steps(st, o, pend=False):
    """Plain next steps for this stage, under the safe swap rules. Terse."""
    if st == "filled": return ["Filled and final: nothing left to do. Stop checking.", "Don't take or pay this offer again."]
    if st == "filling": return ["A fill tx is landing. Wait for it to finalize; check this page once more in a few minutes.", "Don't re-take or pay again while it lands."]
    sub = ("A fill was submitted but is not final. The payment may have landed on the external chain; POAScan can't see it. "
           "Check status on POASwap with your ref before anything else, then ask on LabLeak. Never loop.")
    if st == "expired": return ["Expired: stop. Don't take or pay this offer.", sub if pend else "If you paid and it never filled, check status with your ref before anything else, then ask on LabLeak. Never loop."]
    if st == "cancelled": return ["Cancelled by the maker: stop. Don't take or pay this offer."] + ([sub] if pend else [])
    if st == "delisted": return ["Gone from the book before its expiry. Check status before any take; don't pay."]
    return ["Open. Check status before any take or re-take.", "Take only through the network's swap flow (receipt before broadcast). Never send payment outside the network.",
            "pending_receipt is held, not paid: wait for the seller.",
            "One take, and never loop. After a timeout or a 524, wait about 2 min, then check status: held, wait; nothing held, take once more; still nothing, stop.",
            "Stop at Filled, Expired or Failed. POAScan can lag a few minutes; lag is not failure."]

def ask(oid):
    return PR.swap_status(oid)

def page_body(oid):
    """(title, body html) for /swap/<oid>, or None when POAScan holds no such offer."""
    if not OID_RX.match(oid or ""): return None
    d = SC.offer(oid)
    if not d or not d.get("offer"): return None
    o = d["offer"]; st = stage(d); ch = (o.get("chain") or "").lower(); asset = E(o.get("asset") or "")
    tag = f'<span class="tag {TONE.get(st, "")}">{E(LABEL.get(st, st.capitalize()))}</span>'
    ev = [e for e in d.get("events") or []]
    pend = unfinished(d)
    hist = [[E("Fill submitted, not final" if e["kind"] == "swap-fill" and not e.get("final") else EVENT.get(e["kind"], e["kind"])), utc(e.get("ts")) + " · " + rel(e.get("ts")), tx_link(e["txid"], (10, 6)),
             '<span class="ok">final</span>' if e.get("final") else ('<span class="dim">not final</span>' if st in ("expired", "cancelled") else '<span class="warn">pending</span>')] for e in ev]
    if o.get("status") == "expired" and o.get("expires_ts"): hist.append(["Expired", utc(o["expires_ts"]) + " · " + rel(o["expires_ts"]), "···", "···"])
    pay_to = _ext(ch, o.get("pay_to"))
    rows = [("Offer id", f'<span class="mono wrap">{E(oid)}</span>{copy(oid)}'), ("Status", tag + (f' <span class="dim small">E{o["fill_epoch"]} fill</span>' if o.get("fill_epoch") is not None else "")
             + (f' <a class="small oftrack" href="{E(su)}" target="_blank" rel="noopener noreferrer" title="This offer\'s status on POASwap (read only)">Status on POASwap ↗</a>' if (su := status_url(oid)) else "")),
            ("Maker", addr_link(o.get("maker"), None, (48, 0))),
            ("Escrow", f'<span class="num">{plain(o.get("poa"), 6)}</span> <span class="unit">POA</span> locked by the maker' + (f' · offer tx {tx_link(oid, (10, 6))}' if any(e["txid"] == oid for e in ev) else "")),
            ("Wants", f'<span class="num">{plain(o.get("want"), 6)}</span> <span class="unit">{asset}</span> on {E(CHAIN.get(ch, ch.capitalize() or "···"))} to {pay_to}'),
            ("Created", utc(o.get("created_ts"))), ("Expires", utc(o.get("expires_ts")) + (" · " + rel(o["expires_ts"]) if o.get("expires_ts") else "")),
            ("Taker", addr_link(o.get("taker"), None, (48, 0)) if o.get("taker") else '<span class="na">···</span>'),
            ("Payment ref", (_ext(ch, o.get("ext_ref"), tx=True) + (' <span class="dim small">taker\'s payment on the external chain</span>' if o.get("ext_ref") else ""))
                            if o.get("ext_ref") or not pend else f'<span class="dim">{E(UNSEEN_PAY)}</span>'),
            ("Fill", (tx_link(o["fill_txid"], (10, 6)) + " · " + utc(o.get("fill_ts")) + (f' · {o["fill_atts"]} attestations' if o.get("fill_atts") is not None else "")
                      + (' · <span class="ok">final</span>' if o.get("fill_final") else "")) if o.get("fill_txid")
             else ("Submitted, not final · " + tx_link(pend[-1]["txid"], (10, 6)) + " · " + utc(pend[-1].get("ts"))) if pend else '<span class="na">···</span>'),
            ("Cancel", tx_link(o["cancel_txid"], (10, 6)) + " · " + utc(o.get("cancel_ts")) if o.get("cancel_txid") else None),
            ("Memo", E(o["memo"]) if o.get("memo") else None)]
    kv = "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in rows if v)
    tv = (o.get("taker_chains") or {}).get(ch)
    unseen = ('<p class="dim small">Not in POAScan\'s data: anything on the external chain beyond the payment ref, such as a durable nonce account or its rent '
              'from a timed out take.' + (f' Check the taker\'s verified {E(CHAIN.get(ch, ch))} address: {_ext(ch, tv)}.' if tv else "") + '</p>')
    steps = "".join(f"<li>{E(s)}</li>" for s in next_steps(st, o, bool(pend)))
    links = f'<a class="more" href="/api/v1/swaps/{E(oid)}">API →</a>'   # Status on POASwap sits in the Status row, so the header fits one line at 390px
    body = (f'<div class="sechead"><h1>Swap offer <span class="mono">{E(short(oid, 8, 6))}</span></h1></div>'
            + card("Offer", kv + unseen, PR.ask([ask(oid)]) + links)
            + card("Next steps", f'<ol class="ofs">{steps}</ol><p class="dim small">Read only: this page never signs or sends anything. Never send payment outside the network.</p>')
            + card("Stage history", table(["Stage", "When", "Tx", "Ledger"], hist, cls="wrapt") if hist else na("No swap txs archived for this offer yet.")))
    return "Swap " + short(oid, 8, 6), body
