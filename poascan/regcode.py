"""Optional wallet registry step for the wallet setup prompts (/swaps Add Wallet, /start step 8).
The setup code is made in the visitor's browser (static/app.js: 's_' + 16 chars of a-z2-7, crypto.getRandomValues) and
filled into the prompt there. POAScan's server never generates, receives, logs or stores it, never calls poaswap.io for it (the server's only poaswap.io read is the public swap status, swapflag.py), and
never puts the code in a URL, cookie or local storage. Without JS the prompt shows without this step.
Only public addresses: no created/sig/type fields, because those need the PoA key and prompts never handle the key."""
from html import escape as E

URL = "https://poaswap.io/api/v1/registry/register"
SLOT = "{SETUP_CODE}"          # app.js swaps this for the browser-made code
ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
CODE_RX = r"^s_[a-z2-7]{16}$"
FIELDS = ("code", "src", "event", "poa1", "sol", "evm", "client", "app_version")

CORE = ("register this wallet's public addresses with the POASwap wallet registry. POST JSON (body only, no query string) to "
        f'{URL} with only these fields: "code":"{SLOT}", "src":"scan", "event":"created" if the vault is new or "connected" '
        'if it already existed, "poa1", "sol" and "evm" (the public addresses you have, at least one), "client" (your app\'s name) '
        'and "app_version" (its version). Public addresses only, never keys, passwords or signatures. Skip if unsure.')

def step(lead):
    return lead + CORE

def fill(text, lead, before, code):
    """Python mirror of app.js, for tests: insert the step on its own line before the blank line that precedes `before`."""
    i = text.find("\n\n" + before)
    return text if i < 0 else text[:i] + "\n" + step(lead).replace(SLOT, code) + text[i:]

def attrs(lead, before):
    """data- attributes on the prompt's <pre>; app.js reads them, the server never fills them."""
    return f' data-reg="{E(step(lead))}" data-reg-at="{E(before)}"'
