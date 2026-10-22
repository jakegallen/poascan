"""Verified external addresses per Agent. The address list and its verified flag come from minepoa.com /api/chains
(archived hourly); verified_at comes from the ledger's chains-update txs that POAScan archived (each body names the
addresses and carries their ownership proofs). Request handlers read only the local archive, never minepoa.com."""
import time
from . import db, analytics as A

def _norm(addr):
    """EVM addresses compare case-insensitively; every other chain's address is compared exactly."""
    a = str(addr or "")
    return a.lower() if a[:2].lower() == "0x" else a

def _iso(t): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(t))) if t else None

@A.cached("agent_addresses", 60)
def all_addresses():
    """{agent: [{chain, address, verified_at}]} for every Agent with a verified link. One cache entry for the whole
    network; the chains-update join is aggregated in SQL (newest finalized registration per agent, chain and address)."""
    try:
        rows = db.q("""SELECT t.from_addr AS a, j.key AS chain, CAST(j.value AS TEXT) AS addr, MAX(t.ts) AS ts
                       FROM txs t JOIN tx_detail d ON d.id = t.id, json_each(d.json, '$.body.chains') j
                       WHERE t.type = 'chains-update' AND (t.final = 1 OR d.final = 1) AND t.from_addr IS NOT NULL
                       GROUP BY 1, 2, 3""")
    except Exception:
        rows = []
    seen = {}
    for r in rows:
        k = (r["a"], r["chain"], _norm(r["addr"]))
        if r["ts"] and r["ts"] > (seen.get(k) or 0): seen[k] = r["ts"]
    out = {}
    for agent, links in (db.get_blob("chains")[0] or {}).items():
        if not str(agent).startswith("poa1") or not isinstance(links, dict): continue
        lst = [dict(chain=c, address=v["addr"], verified_at=_iso(seen.get((agent, c, _norm(v["addr"])))))
               for c, v in sorted(links.items()) if isinstance(v, dict) and v.get("verified") is True and v.get("addr")]
        if lst: out[agent] = lst
    return out

def addresses(agent):
    """An Agent's verified external addresses, sorted by chain (empty list when it has none)."""
    return [dict(x) for x in all_addresses().get(agent, [])]

def known(agent):
    """True when the archive knows the Agent: listed by /api/agents, linked in /api/chains or the sender of an archived tx."""
    if agent in all_addresses(): return True
    if db.q1("SELECT 1 AS x FROM accounts WHERE addr=?", (agent,)): return True
    if (db.get_blob("chains")[0] or {}).get(agent) is not None: return True
    return bool(db.q1("SELECT 1 AS x FROM txs WHERE from_addr=? LIMIT 1", (agent,)))
