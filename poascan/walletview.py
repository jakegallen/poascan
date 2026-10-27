"""Wallet binding card (address page) and the Check my wallet lookup (/wallet?address=poa1...). Reads wallet.binding()
only; no upstream call. The lookup takes an address only and never echoes anything else back."""
import time
from html import escape as E
from . import wallet as W, prompts as PR
from .ui import card, flag, qtip, lt, short, na, ICON_SEARCH

CHAIN_NAME = {"solana": "Solana", "ethereum": "EVM", "base": "Base"}
TIP_LINKED = "Linked: minepoa's public /api/links lists this address with a vault. A vault link is needed only to swap; mining, grading and voting never need one."
TIP_VAULT = "The vault's publicId from /api/links. Family size: addresses linked to the same vault. A linked vault counts as one entity: one jury seat, one vote."
TIP_CHAINS = "External addresses in this address's chains map (/api/chains, read hourly), with minepoa's verified flag: an ownership proof that verified on the ledger."
TIP_TXS = "Vault link: the identity-link tx. Wallet link: the chains-update tx that set the chains map. Times in your time zone."

def _tx(rows):
    if not rows: return ""
    r = rows[0]
    more = f' <span class="dim">· {len(rows) - 1} earlier</span>' if len(rows) > 1 else ""
    return (f'<a class="mono hash" href="/tx/{E(r["id"])}" title="{E(r["id"])}">{E(short(r["id"], 6, 4))}</a> '
            f'<span class="dim sep">·</span> {lt(r["ts"], "dt")}' + ("" if r["final"] else ' <span class="tag">Pending</span>') + more)

def ask_items(a):
    check = ("Check my wallet link",
             f"Check the wallet binding of my PoA (Proof of Agent) address {a}: is it linked to a vault, which external addresses are in its chains map and are they verified. "
             f"Data: https://minepoa.com/api/links/{a}, https://minepoa.com/api/chains and https://poascan.io{W.lookup_url(a)}. "
             "If it is not linked and I want to swap, tell me what go.md's LINK section says to do and wait for my go-ahead." + PR.RO + PR.PAY)
    link = ("Link my vault for swaps",
            f"Link my PoA (Proof of Agent) address {a} to my vault so I can swap, following the LINK section of https://minepoa.com/go.md exactly. "
            "Do it only if I say I want to swap. First confirm with me which vault, then make the one link call go.md gives, "
            f"then verify with https://minepoa.com/api/links/{a} and https://minepoa.com/api/chains. Never ask me for a seed phrase or private key." + PR.SAFE + PR.PAY)
    return [check, link]

def kv_rows(b):
    rows = []
    if b["linked"] is None: lk = '<span class="na">···</span>'
    else:
        lk = '<span class="tag ok">YES</span>' if b["linked"] else '<span class="tag">NO</span>'
        if b["warning"]: lk += " " + flag(b["warning"]["text"], "No vault link yet. It is needed only to swap; mining, grading and voting work without one. POAScan never asks for keys. Never send payment outside the network.")
    if b["links_stale"] and b["linked"] is not None:
        t = b["links_checked_at"]
        lk += " " + flag("Stale", f"Link list checked {int((time.time() - t) // 60)} min ago" if t else "Link list not read yet")
    rows.append(("Vault linked", lk + " " + qtip(TIP_LINKED, W.METHOD, "What vault linked means")))
    if b["vault"]:
        rows.append(("Vault", f'<span class="mono">{E(b["vault"])}</span> ' + qtip(TIP_VAULT, W.METHOD, "What vault and family size mean")))
        fam = b["family_size"]
        others = [x for x in b["family"] if x != b["address"]]
        rows.append(("Family size", f'<span class="num">{fam}</span>' + ("" if not others else ' <span class="dim">· ' + ", ".join(
            f'<a class="mono" href="/address/{E(x)}">{E(short(x, 6, 4))}</a>' for x in others[:8]) + "</span>")))
    for c in b["chains"]:
        v = '<span class="tag ok">Verified</span>' if c["verified"] else '<span class="tag warn">Unverified</span>'
        rows.append((CHAIN_NAME.get(c["chain"], E(c["chain"].capitalize())), f'<span class="mono">{E(c["address"])}</span> {v}'))
    if b["chains"]: rows[-len(b["chains"])] = (rows[-len(b["chains"])][0], rows[-len(b["chains"])][1] + " " + qtip(TIP_CHAINS, W.METHOD, "What the chain rows mean"))
    il, cu = _tx(b["identity_link_txs"]), _tx(b["chains_update_txs"])
    if il: rows.append(("Vault link", il + " " + qtip(TIP_TXS, W.METHOD, "Which txs these are")))
    if cu: rows.append(("Wallet link", cu + ("" if il else " " + qtip(TIP_TXS, W.METHOD, "Which txs these are"))))
    return rows

def binding_card(a, lookup=False):
    b = W.binding(a)
    kv = "".join(f'<div class="kv"><span>{k}</span><div>{v}</div></div>' for k, v in kv_rows(b))
    foot = (f'<p class="cov dim small">Public data only · POAScan never asks for keys · '
            + (f'<a href="/address/{E(a)}">Address page</a>' if lookup else f'<a href="{W.lookup_url()}">Check another wallet</a>')
            + f' · <a href="{W.METHOD}">Method</a></p>')
    links = PR.ask(ask_items(a)) + f'<a class="more" href="/api/v1/wallet/{E(a)}">API →</a>'
    return card("Wallet binding", kv + foot, links, id="wallet")

def lookup_form(value=""):
    v = E(value) if W.ADDR_RX.match(value or "") else ""
    return (f'<form class="wlook" action="{W.ROUTE}" method="get" role="search" autocomplete="off">'
            f'<input name="address" value="{v}" placeholder="poa1… address" aria-label="Your poa1 address" autocomplete="off" autocapitalize="off" '
            f'spellcheck="false" inputmode="text" maxlength="64" pattern="poa1[1-9A-HJ-NP-Za-km-z]{{20,60}}" enterkeyhint="search" required>'
            f'<button aria-label="Check">{ICON_SEARCH}</button></form>'
            '<p class="dim small wl-note">Address only. Read-only. POAScan never asks for keys or seed phrases.</p>')

def page(qs, render):
    """render(title, body, active) -> HTML. 200 for the form and a valid address; 400 for anything else (never echoed)."""
    raw = ((qs.get("address") or [""])[0] or "").strip()
    head = '<div class="sechead"><h1>Check my wallet</h1></div>'
    if not raw:
        return render("Check my wallet", head + card("Lookup", lookup_form()), "/")
    if not W.ADDR_RX.match(raw):
        return 400, render("Check my wallet", head + card("Lookup", lookup_form() + na("That is not a poa1 address. Paste the address only, never a key.")), "/")
    return render("Wallet " + short(raw), head + card("Lookup", lookup_form(raw)) + binding_card(raw, lookup=True), "/")
