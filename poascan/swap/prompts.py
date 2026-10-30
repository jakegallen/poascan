"""Prompts the swap page hands to the visitor's agent. Nothing is signed or sent from here."""
from . import config as C

SAFE = "Never send payment outside the network."

# Emblem Wallet CLI: npm @emblemvault/agentwallet (bin: emblemai); npm "repository" points at this repo.
# Wallet steps follow POASwap's wording (wallet step v2, main d26bd69; EMB as main 2452a02) (Oct 22 incident: 3.3.0 in --agent mode mints a new random
# wallet when its profile has no password). Pinned CLI, no global install, backup first, file names only, always --profile.
EMB_REPO = "https://github.com/EmblemCompany/EmblemAi-AgentWallet"
EMB = "npx -y -p @emblemvault/agentwallet@3.3.0 emblemai --hustle-url https://emblemvault.ai"   # pinned: 3.3.0's source was read for the Oct 22 incident; --hustle-url: agenthustle.ai/api/chat 301s and fetch turns the POST into a GET (405)
ADDR_CMD = 'EMBLEMAI --profile PROFILE --agent -m "List my wallet addresses as JSON: solana, evm. Addresses only."'   # --profile: a missing profile exits, never mints
CHECK_CMD = "find ~/.emblemai ~/.emblem-vault -maxdepth 3 -name '.env*' -o -name metadata.json -o -name .emblem-vault 2>/dev/null; echo END"   # no globs
BACKUP_CMD = "cp -a ~/.emblemai ~/.emblemai.backup-$(date +%s)"
MIGRATED_CMD = "grep -c migratedFrom ~/.emblemai/profiles/default/metadata.json"   # metadata.json holds no secrets
BACKUP_RULE = "Emblem backup: tell me only where the file is; never open, cat or print it."
# Wallet step v2: POASwap's start_prompt.json registration blocks (install, find_wallet with case_a and case_b, addresses) on main
# d26bd69 (unchanged through 5b6caa1). Two changes on purpose: the Windows hint after the npx --cache retry in install,
# and case D's emblemvault.ai line (no POASwap page here).
# emblemai has no --version (any other flag runs the CLI and the legacy move), so there is no version check.
W_INSTALL = "Only on my own computer: in a sandbox or container, stop and tell me. Need node -v 20.18+. Missing or older: give me the command (macOS: brew install node; Linux: nvm install 22; Windows: winget install OpenJS.NodeJS.LTS), wait for me, check again. Wallet CLI: only {emb} (EMBLEMAI below). npx cache or permission error: retry once with npx --cache \"$(mktemp -d)\" (Windows: use any new empty folder); network error: say so, retry once."
W_FIND = "Find my wallet by file names only. Never open, print, edit or delete anything in ~/.emblemai or ~/.emblem-vault. Never use -p, --password or EMBLEM_PASSWORD. If ~/.emblemai exists, back it up: {backup_cmd}; check it exists. Then run {check_cmd} (END alone: none). Pick one case:\nA. ~/.emblemai/profiles/PROFILE has both .env and .env.keys: use it (several: ask me which).\nB. ~/.emblemai/.env and .env.keys at the top (old layout): ask me first. On yes, run EMBLEMAI profile list once; check profiles/default has both files and {migrated_cmd} prints 1; PROFILE is default.\nC. Anything else (a lone .env, an empty profile, ~/.emblem-vault, anything unclear): stop, tell me what you found and where the backup is, run nothing else.\nD. Nothing found: ask me once, \"Do you already have an Emblem Wallet? (made on another computer / signed in at emblemvault.ai / no)\". Another computer: I run EMBLEMAI --restore-auth with my backup file; then redo this step. emblemvault.ai: skip step 3; link that vault in step 4. No: ask me to confirm a new wallet. Only on yes, run EMBLEMAI profile create default; PROFILE is default."
W_ADDR = "Check (offline): EMBLEMAI profile inspect PROFILE runs and, in case A or B, shows Credentials: present; else stop. Read the addresses, one attempt only: {addr_cmd}\nCase A or B and it says \"created a new wallet identity\"? Stop: no retry, no other wallet command, no change in ~/.emblemai; tell me it made a new wallet, not mine, and where the backup is. Other errors (500, 405, any): show it, say my files are unchanged, stop. Case D: tell me it is new and how to back it up: run EMBLEMAI in Terminal, type /auth, pick Backup Agent Auth, keep that file offline. {backup}"

def wallet_steps():
    """Steps 1 to 3 in POASwap's wording: own machine, Node 20.18+, pinned CLI, npx retries; backup and file-name check, cases A to D; inspect, one read."""
    return [W_INSTALL.format(emb=EMB), W_FIND.format(backup_cmd=BACKUP_CMD, check_cmd=CHECK_CMD, migrated_cmd=MIGRATED_CMD),
            W_ADDR.format(addr_cmd=ADDR_CMD, backup=BACKUP_RULE)]

def wallet_prompt():
    a, b, c = wallet_steps()
    return ("Set up my Emblem Wallet and link it to my PoA (Proof of Agent, minepoa.com) agent. "
        f"Source: {EMB_REPO} (npm package @emblemvault/agentwallet).\n\n"
        f"1. {a}\n2. {b}\n3. {c}\n"
        "4. Link that vault to my PoA agent as in https://minepoa.com/go.md (section LINK): connect it as that section says, "
        "then call https://minepoa.com/api/link-auto with the auth token only in a header (Authorization: Bearer), never in the URL; if it only takes the token in the URL, stop and tell me. Verify at https://minepoa.com/api/links/MY_POA_ADDRESS and check that https://minepoa.com/api/chains shows verified:true.\n\n"
        "Never paste or show passwords, keys or seed phrases in chat. Don't use any referral or invite code. Only use minepoa.com and the official Emblem tools, and report each step's result.")
WALLET_PROMPT = wallet_prompt()
_CHECK_LIVE = ("Before anything else, GET https://minepoa.com/api/swaps. If it doesn't answer with JSON (no response, a timeout or a non-200 status), "
          "tell me swaps are being upgraded, don't call swap-take or any other swap endpoint, don't retry in a loop, and offer to try again later. ")
_CHECK_SOON = ("Swaps are coming soon. Until " + C.STATUS_URL + " shows available:true, don't call swap-offer, swap-take "
               "or any other swap endpoint: tell me swaps are coming soon and help me get ready by linking an Emblem vault (go.md LINK). Once it's true: ")
def _check(): return _CHECK_LIVE if C.SWAPS_LIVE else _CHECK_SOON
_TAIL = " Follow https://minepoa.com/go.md (sections SWAPS and LINK) and https://minepoa.com/skill.md exactly. Use the coordinated flow (receipt before broadcast); never pay first. Never send payment outside the network: only pay through the network's swap flow, never to an address directly. Never ask me for keys or seed phrases. Act only on minepoa.com. Report each step's response."

# Take wording (1.26.53, after the first real fill): a failed or timed out take can still create a nonce account, and a second
# take broadcasts the held payment. So: one more take only on receipt_ready true, status before any re-take, never loop.
BUY = ("Buy POA (Proof of Agent, minepoa.com) with up to {IN} {ASSET}. Take offer {OFFERS} from https://minepoa.com/api/swaps: check its amount, "
       "what it wants and its expiry, and confirm with me. Use my Emblem vault linked to my PoA agent (go.md LINK; link it first if it isn't). "
       "Call /api/hosted/swap-take with that offer id. If it returns pending_receipt, call swap-take again once, only when a /api/hosted/swap-receipt read with that ref shows receipt_ready true. "
       "After a failure or timeout, check status (swap-receipt with that ref, and the offer in https://minepoa.com/api/swaps) before any re-take. Never loop. "
       "Stop at Filled, Expired or Failed. I expect about {OUT} POA after the network fee.")
SELL = ("Sell {IN} of my spendable POA for {OUT} {ASSET} on {CHAINNAME} (PoA = Proof of Agent, minepoa.com). First make sure my Emblem vault is linked "
        "(go.md LINK) and my {CHAINNAME} address shows verified:true in https://minepoa.com/api/chains. Then post the offer with /api/hosted/swap-offer "
        "(chain={CHAIN}, asset={ASSET}, want_amount={OUT}, to = my verified address, ttl in seconds) and tell me the offer id and expiry.")

BUY_TOKEN = ("Buy POA (Proof of Agent, minepoa.com) with up to {IN} {ASSET} on {CHAINNAME}. Check offer {OFFERS} in https://minepoa.com/api/swaps (amount, what it wants, "
             "expiry) and confirm with me. One-call swap-take pays native legs only, so use the coordinated flow in go.md: build and sign the {ASSET} payment to the offer's want.to "
             "from my linked Emblem vault without broadcasting, register it with /api/hosted/swap-intent, then read /api/hosted/swap-receipt with that ref at most once every 30 seconds for up to 10 minutes. "
             "If receipt_ready is not true by then, stop and tell me; don't broadcast and never keep polling. Once it is true, "
             "/api/hosted/swap-broadcast and /api/hosted/swap-fill with that ref. I expect about {OUT} POA after the network fee.")

# Wallet setup prompt: the host may add an optional last step here (POAScan: the wallet registry step, filled in the
# browser with a browser-made code; see poascan/regcode.py). lead starts the step, before is the line it goes above.
WALLET_REG = dict(lead="5. Optional: ", before="Never paste or show passwords")

def templates():
    c = _check()
    return {"buy": c + BUY + _TAIL, "buy_token": c + BUY_TOKEN + _TAIL, "sell": c + SELL + _TAIL, "connect": wallet_prompt()}

