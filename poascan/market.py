"""Swap data as the explorer shows it: the ≈$ beside POA amounts, the price figures on the Token tab and the swap rows
on /tx. Everything here reads the swap module through its API (swapclient), never its tables."""
from html import escape as E
from . import swapclient as SC
from .ui import plain, stat, addr_link, short

# ---------------- USD: one reference, from /api/v1/price ----------------
def _sig(v, n): return float(f"{v:.{n}g}") if v else v

def money(v, n=3):
    """$ with n significant figures: $13K, $710, $0.11."""
    if v is None: return None
    v = _sig(v, n)
    for d, u in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= d: return f"${plain(v / d, n)}{u}"
    return f"${plain(v, n)}"

def price(): return SC.price()

# Consolidation: POA only. The page UI shows no USD, no POA/USD toggle and no reference label. The public /api/v1/price,
# /api/v1/swaps/* and the MCP price fields are served by swapclient and agentapi and are untouched. The three helpers stay so
# every caller keeps working; they render nothing.
def usd_of(amount):
    return ""

def usd_src():
    return ""

def usd_toggle():
    return ""

# ---------------- price formatting, from /api/v1/swaps/status ----------------
from .views2 import ICON_SWAP   # noqa: E402

def _pfmt(per_m, asset):
    if per_m is None: return '<span class="na">···</span>'
    return f'<span class="num">{plain(per_m, 6)}</span> <span class="unit">{E(asset or "")}</span>'

def open_escrow():
    """POA locked in open offers (for reconciliation)."""
    return [r.get("poa") for r in SC.offers("open")]

# ---------------- /tx: offer and payment rows, from /api/v1/swaps/<offer_id> ----------------
CHAIN_NAME = {"solana": "Solana", "base": "Base", "ethereum": "Ethereum"}
EXPL = {"solana": ("https://solscan.io/account/", "https://solscan.io/tx/"),
        "base": ("https://basescan.org/address/", "https://basescan.org/tx/"),
        "ethereum": ("https://etherscan.io/address/", "https://etherscan.io/tx/")}

def net_logo(chain):
    """Small round network mark (static/net-*.svg)."""
    c = (chain or "").lower(); n = CHAIN_NAME.get(c, c.capitalize() or "Network")
    if c not in CHAIN_NAME: return f'<span class="netl" role="img" aria-label="{E(n)}" title="{E(n)}"></span>'
    return f'<img class="netl" src="/static/net-{c}.svg?v=1" width="16" height="16" alt="{E(n)}" aria-label="{E(n)}" title="{E(n)}">'

def _ext(chain, addr, tx=False):
    if not addr: return '<span class="na">···</span>'
    e = EXPL.get((chain or "").lower())
    if not e: return f'<span class="mono">{E(short(addr, 6, 4))}</span>'
    return f'<a class="mono" href="{e[1 if tx else 0]}{E(addr)}" target="_blank" rel="noopener noreferrer">{E(short(addr, 6, 4))} ↗</a>'

def tx_rows(b, nm=None):
    """Offer and payment-proof rows for swap txs on /tx: pair, amounts, maker and the external-chain payment."""
    out = []; oid = b.get("offer") or ""; pr = b.get("proof") or {}
    o = ((SC.offer(oid) or {}).get("offer")) if oid else None
    if o:
        ch = (o["chain"] or "").lower(); asset = E(o["asset"] or "")
        fee = (o.get("fee_bp") or 100) / 1e4; net = o["poa"] * (1 - fee) if o["poa"] else None
        out.append(("To", addr_link(o["maker"], nm, (48, 0)) + ' <span class="dim small">maker</span>'))
        out.append(("Amount", f'<span class="num">{plain(o["poa"], 6)}</span> <span class="unit">POA</span> for <span class="num">{plain(o["want"], 6)}</span> <span class="unit">{asset}</span>'
                    + (f' <span class="dim small">· taker gets {plain(net, 6)} POA after the {fee * 100:g}% fee</span>' if net else "")))
        out.append(("Offer", f'{net_logo(ch)}<b>POA / {asset}</b> <span class="dim small">{E(o["status"])}</span>'
                    f'<div class="mono wrap small">{E(oid)}</div>'))
    elif oid:
        out.append(("Offer", f'<span class="mono wrap">{E(oid)}</span>'))
    if pr.get("ref"):
        ch = (pr.get("chain") or "").lower()
        out.append(("Payment", f'{net_logo(ch)}{_ext(ch, pr["ref"], tx=True)}'))
    return out
