"""Prompts the swap page hands to the visitor's agent. Nothing is signed or sent from here."""
from . import config as C

SAFE = "Never send payment outside the network."

# Emblem Wallet CLI: npm @emblemvault/agentwallet (bin: emblemai); npm "repository" points at this repo.
EMB_REPO = "https://github.com/EmblemCompany/EmblemAi-AgentWallet"
EMB_INSTALL = "npm install -g @emblemvault/agentwallet"
WALLET_PROMPT = ("Install the Emblem Wallet CLI for me and link it to my PoA (Proof of Agent, minepoa.com) agent. "
    f"Source: {EMB_REPO} (npm package @emblemvault/agentwallet).\n\n"
    f"1. Install it (needs Node.js): {EMB_INSTALL} and check it runs: emblemai --help\n"
    "2. Set up or log in to the vault: run emblemai (browser auth, recommended), or emblemai --agent for password auth. "
    "Login and signup are the same action. If a password is generated, keep it encrypted on this machine and back it up with /auth > Backup Agent Auth to a file I store offline.\n"
    "3. Link that vault to my PoA agent as in https://minepoa.com/go.md (section LINK): connect at https://minepoa.com/lableak/connect, "
    "then GET https://minepoa.com/api/link-auto?token=MY_AUTH_TOKEN. Verify at https://minepoa.com/api/links/MY_POA_ADDRESS and check that https://minepoa.com/api/chains shows verified:true.\n\n"
    "Never paste or show passwords, keys or seed phrases in chat. Don't use any referral or invite code. Only use minepoa.com and the official Emblem tools, and report each step's result.")
_CHECK_LIVE = ("Before anything else, GET https://minepoa.com/api/swaps. If it doesn't answer with JSON (no response, a timeout or a non-200 status), "
          "tell me swaps are being upgraded, don't call swap-take or any other swap endpoint, don't retry in a loop, and offer to try again later. ")
_CHECK_SOON = ("Swaps are coming soon. Until " + C.STATUS_URL + " shows available:true, don't call swap-offer, swap-take "
               "or any other swap endpoint: tell me swaps are coming soon and help me get ready by linking an Emblem vault (go.md LINK). Once it's true: ")
def _check(): return _CHECK_LIVE if C.SWAPS_LIVE else _CHECK_SOON
_TAIL = " Follow https://minepoa.com/go.md (sections SWAPS and LINK) and https://minepoa.com/skill.md exactly. Use the coordinated flow (receipt before broadcast); never pay first. Never send payment outside the network: only pay through the network's swap flow, never to an address directly. Never ask me for keys or seed phrases. Act only on minepoa.com. Report each step's response."

BUY = ("Buy POA (Proof of Agent, minepoa.com) with up to {IN} {ASSET}. Take offer {OFFERS} from https://minepoa.com/api/swaps: check its amount, "
       "what it wants and its expiry, and confirm with me. Use my Emblem vault linked to my PoA agent (go.md LINK; link it first if it isn't). "
       "Call /api/hosted/swap-take with that offer id; if it returns pending_receipt, re-call until stage is filled. I expect about {OUT} POA after the network fee.")
SELL = ("Sell {IN} of my spendable POA for {OUT} {ASSET} on {CHAINNAME} (PoA = Proof of Agent, minepoa.com). First make sure my Emblem vault is linked "
        "(go.md LINK) and my {CHAINNAME} address shows verified:true in https://minepoa.com/api/chains. Then post the offer with /api/hosted/swap-offer "
        "(chain={CHAIN}, asset={ASSET}, want_amount={OUT}, to = my verified address, ttl in seconds) and tell me the offer id and expiry.")

BUY_TOKEN = ("Buy POA (Proof of Agent, minepoa.com) with up to {IN} {ASSET} on {CHAINNAME}. Check offer {OFFERS} in https://minepoa.com/api/swaps (amount, what it wants, "
             "expiry) and confirm with me. One-call swap-take pays native legs only, so use the coordinated flow in go.md: build and sign the {ASSET} payment to the offer's want.to "
             "from my linked Emblem vault without broadcasting, register it with /api/hosted/swap-intent, poll /api/hosted/swap-receipt until receipt_ready, then "
             "/api/hosted/swap-broadcast and /api/hosted/swap-fill with that ref. I expect about {OUT} POA after the network fee.")

# Wallet setup prompt: the host may add an optional last step here (POAScan: the wallet registry step, filled in the
# browser with a browser-made code; see poascan/regcode.py). lead starts the step, before is the line it goes above.
WALLET_REG = dict(lead="4. Optional: ", before="Never paste or show passwords")

def templates():
    c = _check()
    return {"buy": c + BUY + _TAIL, "buy_token": c + BUY_TOKEN + _TAIL, "sell": c + SELL + _TAIL, "connect": WALLET_PROMPT}

