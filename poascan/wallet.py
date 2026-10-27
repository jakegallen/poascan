"""Wallet binding (1.26.187): is an Agent's poa1 address linked to a vault, which external addresses its chains map holds
and which txs did it. Public data only, read from POAScan's own copies; a page view, API call or MCP call never reads
minepoa.com.

Sources
  linked, vault   minepoa's public /api/links (the bulk list of every linked address and its vault publicId, about 1 KB),
                  read every LINKS_S (10 min) by the indexer, stored as one blob. family_size is how many addresses that
                  list binds to the same vault (go.md: a linked vault is one entity, one jury seat, one vote).
  chains          minepoa's /api/chains (archived hourly): each chain's address and its verified flag, as published.
  txs             identity-link and chains-update txs POAScan archived for the address (the ledger record of the link).
  joined          the address's join tx in the archive.
The Check my wallet lookup (/wallet?address=poa1...) takes an address only. It never asks for, accepts or echoes a key."""
import re, time
from . import db

PATH = "/api/links"
BLOB = "vault_links"
LINKS_S = 600            # bulk list read every 10 min (about 1 KB)
STALE_S = 3600           # no good read in this long: Stale
RECENT_S = 72 * 3600     # joined within this long without a link: the warning state
ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")
VAULT_RX = re.compile(r"^v[0-9a-f]{8,64}$")
ROUTE = "/wallet"        # stable lookup URL: /wallet?address=<poa1 address> (POASwap /start links here)
METHOD = "/about#wallet-binding"

def lookup_url(a=None, base=""):
    return f"{base}{ROUTE}" + (f"?address={a}" if a else "")

# ---------------------------------------------------------------- read (indexer job)
def parse(d):
    """{addr: vault} from the bulk /api/links body (a list of {addr, vault}); rows that are not a poa1 address and a
    vault publicId are dropped. Raises ValueError on a body that is not a list."""
    if not isinstance(d, list): raise ValueError("unexpected shape")
    out = {}
    for r in d:
        if isinstance(r, dict) and ADDR_RX.match(str(r.get("addr") or "")) and VAULT_RX.match(str(r.get("vault") or "")):
            out[r["addr"]] = r["vault"]
    return out

def job(now=None, get=None):
    """One GET of the bulk list (conditional when minepoa sends an ETag); the stored copy is kept on any failure."""
    from . import indexer as I
    now = int(now or time.time())
    if get is None:
        if not I.can_fetch(PATH): I.skip_backoff(PATH); return False
        get = lambda: I.fetch(PATH, cond=True)
    cur = db.get_blob(BLOB)[0] or {}
    try:
        d = get()
        if d is I.NOT_MODIFIED or d is None:
            db.put_blob(BLOB, dict(cur, checked_at=now)); return True
        links = parse(d)
    except (I.Busy, ValueError) as e:
        db.put_blob(BLOB, dict(cur, err=str(e)[:120], err_at=now)) if cur else None
        return False
    db.put_blob(BLOB, dict(links=links, fetched_at=now, checked_at=now, err=None, err_at=None))
    return True

def state():
    """The stored copy: dict(links={addr: vault}, fetched_at, checked_at) or None before the first read."""
    v = db.get_blob(BLOB)[0]
    return v if isinstance(v, dict) and isinstance(v.get("links"), dict) else None

# ---------------------------------------------------------------- binding view (no upstream call)
def _txs(a, typ, n=10):
    try: return [dict(id=r["id"], ts=r["ts"], final=bool(r["final"])) for r in
                 db.q("SELECT id, ts, final FROM txs WHERE type=? AND from_addr=? ORDER BY ts DESC LIMIT ?", (typ, a, n))]
    except Exception: return []

def _joined(a):
    try:
        r = db.q1("SELECT MIN(ts) AS t FROM txs WHERE type='join' AND from_addr=?", (a,))
        return int(r["t"]) if r and r["t"] else None
    except Exception: return None

def binding(a, now=None):
    """Everything public about one address's wallet binding. linked is None before POAScan has read /api/links."""
    now = int(now or time.time())
    s = state(); links = (s or {}).get("links") or {}
    vault = links.get(a); linked = (a in links) if s else None
    fam = sorted(x for x, v in links.items() if vault and v == vault)
    ch = (db.get_blob("chains")[0] or {}).get(a) or {}
    chains = [dict(chain=c, address=v.get("addr"), verified=v.get("verified") is True)
              for c, v in sorted(ch.items()) if isinstance(v, dict) and v.get("addr")]
    il, cu = _txs(a, "identity-link"), _txs(a, "chains-update")
    joined = _joined(a)
    from . import indexer as I
    chk = (s or {}).get("checked_at")
    warn = None
    if linked is False and joined and 0 <= now - joined <= RECENT_S:
        h = max(0, (now - joined) // 3600)
        warn = dict(kind="joined_no_link", hours=int(h), text=f"Joined {h} hour{'' if h == 1 else 's'} ago, no wallet link")
    return dict(address=a, linked=linked, vault=vault, family_size=len(fam) if vault else None, family=fam if vault else [],
                chains=chains, identity_link_txs=il, chains_update_txs=cu, joined_ts=joined, warning=warn,
                links_checked_at=chk, links_stale=(not chk) or now - int(chk) > STALE_S,
                chains_as_of=I.last_ok("/api/chains"), lookup_url=lookup_url(a, "https://poascan.io"),
                source=dict(linked="minepoa /api/links (read every 10 min)", chains="minepoa /api/chains (read hourly)", txs="POAScan tx archive"),
                note="Public data only. A wallet link is needed only to swap. POAScan never asks for keys. Never send payment outside the network.",
                method="https://poascan.io" + METHOD)
