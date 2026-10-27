"""Wallet binding (1.26.187): the bulk /api/links read (parse, conditional, failures keep the copy), the binding view
(linked, vault, family size, chains with verified flags, identity-link and chains-update txs, joined, the joined_no_link
warning within 72 h), the address page card, the Check my wallet lookup (/wallet?address=, address only, never echoes a
non-address), API (/api/v1/wallet/<a>, ?address=, wallet_binding on the address API), MCP get_wallet_binding, OpenAPI,
llms.txt and /about. Usage: python3 tools/wallet_binding_test.py (temp database, no network)."""
import os, sys, tempfile, time, json, re
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, wallet as W, walletview as WV, indexer as I, agentapi as AG, server as SV, views as V

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

NOW = int(time.time())
L1, L2, U1, U2 = ("poa1" + c * 40 for c in "LMUV")
VA = "vf8bbeb0be5680fba6c0d0e"
TX = lambda c: c * 64

def seed():
    db.init()
    db.put_blob("chains", {L1: {"solana": {"addr": "J6kWfKRfvJGBJQu5EbZiYiURgUDWPZih2zv1Dc6RvEsg", "verified": True},
                                "ethereum": {"addr": "0x3a0e9c1a92ae4914426b57766f4d124a64fa3dc8", "verified": False}}})
    rows = [(TX("a"), "join", L1, NOW - 9 * 86400), (TX("b"), "identity-link", L1, NOW - 3600), (TX("c"), "chains-update", L1, NOW - 3500),
            (TX("d"), "join", U1, NOW - 5 * 3600), (TX("e"), "join", U2, NOW - 10 * 86400)]
    db.write("INSERT OR IGNORE INTO txs(id, type, from_addr, ts, final) VALUES(?,?,?,?,1)", rows, many=True)

def main():
    seed()
    # parse and job
    check("parse keeps addr and vault rows only", W.parse([{"addr": L1, "vault": VA}, {"addr": L2, "vault": VA}, {"addr": "x", "vault": VA}, {"addr": U1, "vault": "pk_secret"}, 5]) == {L1: VA, L2: VA})
    try: W.parse({"error": "x"}); ok = False
    except ValueError: ok = True
    check("parse refuses a body that is not a list", ok)
    check("binding before the first read: linked null", W.binding(L1)["linked"] is None)
    check("job stores the copy", W.job(now=NOW, get=lambda: [{"addr": L1, "vault": VA}, {"addr": L2, "vault": VA}]) and W.state()["links"] == {L1: VA, L2: VA})
    check("304 keeps the copy and moves checked_at", W.job(now=NOW + 600, get=lambda: I.NOT_MODIFIED) and W.state()["links"] == {L1: VA, L2: VA} and W.state()["checked_at"] == NOW + 600)
    def busy(): raise I.Busy("HTTP 503")
    check("a failure keeps the copy", W.job(now=NOW + 1200, get=busy) is False and W.state()["links"] == {L1: VA, L2: VA})
    check("a bad shape keeps the copy", W.job(now=NOW + 1300, get=lambda: {"notice": "x"}) is False and W.state()["links"] == {L1: VA, L2: VA})
    check("fetch allowlist takes /api/links only", I.ALLOWED.match("/api/links") and not I.ALLOWED.match("/api/links/" + L1))
    W.job(now=NOW, get=lambda: [{"addr": L1, "vault": VA}, {"addr": L2, "vault": VA}])

    # binding
    b = W.binding(L1, now=NOW)
    check("linked Agent: linked, vault, family of 2", b["linked"] is True and b["vault"] == VA and b["family_size"] == 2 and b["family"] == sorted([L1, L2]))
    check("chains with verified flags, as published", b["chains"] == [dict(chain="ethereum", address="0x3a0e9c1a92ae4914426b57766f4d124a64fa3dc8", verified=False),
                                                                       dict(chain="solana", address="J6kWfKRfvJGBJQu5EbZiYiURgUDWPZih2zv1Dc6RvEsg", verified=True)])
    check("identity-link and chains-update txs", [t["id"] for t in b["identity_link_txs"]] == [TX("b")] and [t["id"] for t in b["chains_update_txs"]] == [TX("c")])
    check("no warning when linked", b["warning"] is None and not b["links_stale"])
    check("lookup URL is the stable /wallet?address= form", b["lookup_url"] == "https://poascan.io/wallet?address=" + L1)
    u = W.binding(U1, now=NOW)
    check("unlinked recent Agent: warning with hours", u["linked"] is False and u["warning"] == dict(kind="joined_no_link", hours=5, text="Joined 5 hours ago, no wallet link"))
    check("unlinked older Agent: no warning", W.binding(U2, now=NOW)["warning"] is None and W.binding(U2, now=NOW)["linked"] is False)
    check("1 hour reads singular", W.binding(U1, now=NOW - 4 * 3600)["warning"]["text"] == "Joined 1 hour ago, no wallet link")
    check("Stale after an hour without a read", W.binding(L1, now=NOW + 3700)["links_stale"])

    # card
    h = WV.binding_card(L1)
    check("card: title, YES, vault, family size, chain rows, verified tags", all(x in h for x in ("Wallet binding", "tag ok\">YES", VA, "Family size", "Solana", "EVM", "Verified", "Unverified")))
    check("card: tx links to POAScan tx pages, times in the visitor zone", f'href="/tx/{TX("b")}"' in h and f'href="/tx/{TX("c")}"' in h and 'class="t lt' in h and 'data-ts=' in h)
    check("card: Vault link and Wallet link rows", ">Vault link<" in h and ">Wallet link<" in h)
    check("card: Ask agent prompts, read-only check and payment line", "data-ask=" in h and "Never send payment outside the network." in h.replace("&#x27;", "'"))
    check("card: API link and Check another wallet", f"/api/v1/wallet/{L1}" in h and 'href="/wallet"' in h)
    check("card: ? tips present", h.count('class="qtip"') >= 3)
    hu = WV.binding_card(U1)
    check("card: unlinked recent warning tag", "Joined 5 hours ago, no wallet link" in hu and 'tag warn' in hu and "tag\">NO" in hu)
    page = SV.page("/address/" + L1, {}) if False else V.address(L1)
    check("address page carries the card", 'id="wallet"' in (page if isinstance(page, str) else page[1]))

    # lookup page
    r = WV.page({}, lambda t, b, a: b)
    check("/wallet: one box, address only, never asks for keys", 'name="address"' in r and r.count("<input") == 1 and "never asks for keys" in r and 'action="/wallet"' in r)
    r = WV.page({"address": [L1]}, lambda t, b, a: b)
    check("/wallet?address=: the card plus Address page link", 'id="wallet"' in r and f'href="/address/{L1}"' in r and f'value="{L1}"' in r)
    secret = "pk_" + "Q" * 30
    r = WV.page({"address": [secret]}, lambda t, b, a: b)
    check("/wallet with a key-shaped value: 400, never echoed", isinstance(r, tuple) and r[0] == 400 and secret not in r[1] and "QQQQ" not in r[1])
    r = WV.page({"address": ["<script>"]}, lambda t, b, a: b)
    check("/wallet with junk: 400, never echoed", r[0] == 400 and "<script>" not in r[1])
    check("route is wired", SV.page("/wallet", {}) is not None and "/wallet" in SV.STATIC_ROUTES)

    # API and MCP
    d, _ = SV.api("/api/wallet/" + L1, {})
    check("API /api/wallet/<a>", d["linked"] is True and d["vault"] == VA and d["family_size"] == 2)
    d, _ = SV.api("/api/wallet", {"address": [U1]})
    check("API /api/wallet?address=", d["linked"] is False and d["warning"]["kind"] == "joined_no_link")
    for bad in ("/api/wallet/" + secret, "/api/wallet/xyz"):
        try: SV.api(bad, {}); ok = False
        except SV.BadRequest as e: ok = secret not in str(e)
        check(f"API 400 without echo: {bad[:16]}", ok)
    try: SV.api("/api/wallet/" + L1, {"x": ["1"]}); ok = False
    except SV.BadRequest: ok = True
    check("API rejects unknown parameters", ok)
    d, _ = SV.api("/api/address/" + L1, {})
    check("address API carries wallet_binding", d["wallet_binding"]["vault"] == VA)
    m = AG.TOOL_FN["get_wallet_binding"]({"address": L1})
    check("MCP get_wallet_binding", m["linked"] is True and m["lookup_url"].endswith("/wallet?address=" + L1))
    tl = {t["name"]: t for t in AG.tools_list()}
    check("MCP: 41 tools, get_wallet_binding says when to use it", len(tl) == 41 and "Use it" in tl["get_wallet_binding"]["description"])
    check("OpenAPI and llms.txt", "/api/v1/wallet/{address}" in json.dumps(AG.openapi()) and "get_wallet_binding" in AG.llms_txt() and "/wallet?address=" in AG.llms_txt())
    ab = V.about(); ab = ab if isinstance(ab, str) else ab[1]
    check("/about#wallet-binding", 'id="wallet-binding"' in ab and "wallet?address=" in ab)
    allsrc = "".join(open(os.path.join(ROOT, "poascan", f)).read() for f in ("wallet.py", "walletview.py"))
    check("no em or en dashes; Agents wording", not re.search("[\u2013\u2014]", allsrc + h + hu) and "Account" not in h + hu)
    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all passed")); sys.exit(1 if fails else 0)

main()
