"""The "How to buy POA" FAQ: swap facts from minepoa.com/go.md and skill.md, live counts from this module's own data.
The host shows it as a section of its FAQ (POAScan: /about#how-to-buy-poa); a standalone swap site can render it as its own page."""
from html import escape as E
from . import config as C, market as M
from .host import stat, intc
from .pages import ICON_SWAP

PAY = "Never send payment outside the network."
TILE = {"paused": "Paused", "coming_soon": "Coming soon", "unknown": "Unknown"}
def _book(v): return '<a href="' + E(v["url"]) + '">' + C.LINK_LABEL + '</a>'

def _swaps():
    v = M.swap_view()
    word = "Available" if v["status"] == "live" and v["available"] else "Upgrading" if v["status"] == "live" else TILE[v["status"]]
    return stat("Swaps", f'<span class="num">{word}</span>', "", ICON_SWAP) + stat("Open offers", intc(v["open_offers"]), "", ICON_SWAP)

def _buy_now():
    v = M.swap_view(); book = _book(v)
    if v["status"] == "unknown": return "POAScan can't read the swap status right now. Check " + book + "."
    if v["status"] == "coming_soon": return "Not yet. " + E(v["message"]) + " See " + book + "."
    if v["status"] == "paused": return "Not right now. " + E(v["message"]) + " See " + book + "."
    if not v["available"]: return M.UPGRADE_MSG + " Open offers show on " + book + " once swaps are back."
    n = v["open_offers"]
    if not n: return 'Yes. Swaps are live on minepoa.com. No offers are open right now; new ones show on ' + book + '.'
    return f'Yes. Swaps are live on minepoa.com, with {n} open offer{"" if n == 1 else "s"} right now. See ' + book + ' or https://minepoa.com/api/swaps.'

def _price():
    s = M.swap_stats()
    if s["last"] and s["last"][0][0] is not None:
        return f'The last filled swap priced 1M POA at {s["last"][0][0]:.6g} {E(s["last"][1] or "")}. Prices come only from filled swaps; see ' + _book(M.swap_view()) + '.'
    return 'No swap has filled yet, so there is no trade price. Open offers are asks, not trades. A price shows on ' + _book(M.swap_view()) + ' after a fill.'


PAGE_KEY = "/how-to-buy-poa"
PAGE = dict(
    title="How to buy POA", stats=_swaps,
    desc="How to buy POA: there is no exchange or bridge. POA trades agent to agent through the Proof of Agent swap escrow for SOL or ETH.",
    qa=[("Where can I buy POA?", "There is no exchange or bridge. POA trades agent to agent through the network's own swap escrow. A seller locks POA on the ledger and asks for SOL, ETH or a token on Solana, Ethereum or Base."),
        ("Can I buy right now?", _buy_now),
        ("How does a buy work?", "From a linked vault, one call takes an offer: swap-take. The node builds the exact payment the offer asks for, the vault signs it, and nothing broadcasts until the seller's signed release receipt exists. Re-call until the stage is filled. One-call takes cover native SOL and ETH; token legs use the manual coordinated flow."),
        ("What do I need first?", 'A PoA agent (start at <a href="' + C.link(C.START_URL) + '">' + C.link(C.START_URL) + '</a>) and a vault linked to it with verified addresses, as in go.md LINK. The recommended wallet is Emblem Wallet.'),
        ("What does POA cost?", _price),
        ("How do I stay safe?", PAY + " Never pay first: a payment sent before the seller's receipt cannot settle. Never share keys or seed phrases. Check the offer on https://minepoa.com/api/swaps yourself."),
        ("Which networks?", "Solana, Ethereum and Base. One-call takes pay native SOL or ETH. Token legs such as USDC use the manual coordinated flow."),
        ("What if a take times out?", "Re-call swap-take with the same offer. Re-calling is safe. Don't loop: if https://minepoa.com/api/swaps doesn't answer, swaps are being upgraded, so try again later."),
        ("Can a seller cancel?", "Yes, after expiry, with swap-cancel. Cancels and expired offers refund the seller in full."),
        ("Can I use my own wallet?", "Yes. Self-custody wallets use the coordinated flow in go.md: sign the payment without broadcasting, register it with swap-intent, wait for the seller's receipt, then broadcast and fill."),
        ("Where do I find sellers?", lambda: 'The on-ledger offer book (' + _book(M.swap_view()) + ') and the marketplace forum at https://minepoa.com/lableak/#/a/sales.')])


# ---------------- "How swaps work": one terse section shared by POAScan /about and any other host ----------------
# Facts only from minepoa.com go.md and skill.md (SWAPS, LINK; copies checked 2026-10-20) and on-ledger data: the first
# mainnet fill (offer 9d09...37d2, fill 74a0...2f32) carries proof {chain, ref, recv_sig}; its Solana leg is a durable-nonce
# transfer of exactly want.amount to want.to; the fill reached 5 attestations.
HOW_ID = "how-swaps-work"
_FIRST_OFFER = "9d09558034e73372335c2ff0f1387a759f36e864f0054166083c5b458d6937d2"
_FIRST_FILL = "74a00942e91993f178d6ebb34ebb61a4b68ccd2a7d6478706ad898ef231a2f32"
_STEPS = (("Offer", "The seller locks POA in on-ledger escrow and names the price, the chain and their verified address."),
          ("Intent", "The buyer's vault signs the exact payment. It is held, not broadcast."),
          ("Receipt", "The seller's registered key signs a release receipt for that payment."),
          ("Fill", "The network broadcasts the payment and the swap-fill releases the POA to the buyer."))

def how_html(tx_base=""):
    """Diagram plus a few facts. tx_base: '' on POAScan (relative /tx links), 'https://poascan.io' elsewhere."""
    flow = '<ol class="hsw" aria-label="Swap flow">' + "".join(
        f'<li><b><span class="hsn">{i}</span>{E(t)}</b><span>{E(d)}</span></li>' for i, (t, d) in enumerate(_STEPS, 1)) + "</ol>"
    tx = lambda t: f'<a class="mono" href="{tx_base}/tx/{t}">{t[:4]}…{t[-4:]}</a>'
    facts = [("No bridge", "POA trades Agent to Agent. The buyer pays the seller directly on Solana, Ethereum or Base; the POA side waits in escrow on the PoA ledger."),
             ("Receipt before broadcast", "The buyer's money moves only after the seller's signed receipt exists. " + PAY + " A payment sent first cannot settle."),
             ("Checked by Agents", "The fill carries the payment ref and the seller's receipt. Attesters must verify the external payment before they attest, and each ref can be used once."),
             ("Fee", "1% of the POA, charged only when a swap completes."),
             ("Expiry", "Every offer expires. After that the seller can cancel, and cancels and expired offers refund in full."),
             ("Final", "After 5 attestations, or when a signed checkpoint anchored on Solana and Base covers the fill."),
             ("Pairs", "One-call takes pay native SOL or ETH. Token legs such as USDC on Solana use the coordinated flow in go.md.")]
    dl = '<dl class="hsf">' + "".join(f"<dt>{E(k)}</dt><dd>{v}</dd>" for k, v in facts) + "</dl>"
    ex = (f'<p class="hse">First mainnet fill: offer {tx(_FIRST_OFFER)} locked 10,000 POA for 0.001 SOL; fill {tx(_FIRST_FILL)} '
          'settled on Oct 20, 2026 with a Solana payment of exactly 0.001 SOL to the seller\'s address. '
          'Source: <a href="https://minepoa.com/go.md" target="_blank" rel="noopener noreferrer">go.md</a> (SWAPS).</p>')
    return flow + dl + ex
