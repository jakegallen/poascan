"""Established set per minepoa's engine (1.26.140; poa.mjs establishedAt and the close decay, v1.1.2-carveout2).

Seed: Agents flagged established in the segment's genesis import (config in established.json, pinned by sha256; segment 2
starts from segment 1's final checkpoint). Then every close of the segment in order: basis.established_after adds,
basis.established_removed drops, except a removal the engine voids by params.slash_pardons (that close's pardon list names
the Agent and the Agent is in that close's basis.slashed). Trusted and system graders are not added, and grading seats or
jury seats neither grant nor keep standing. Keeping it: only challenge_eligible. L is the last close in this segment
listing the Agent (-1 when none), and the engine removes it at close L + estab_ttl + 1 (decay: L < n - estab_ttl).
Pure folds; the caller passes closes and params. No upstream reads."""
import json, os

CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "established.json")

def load_cfg(path=None):
    with open(path or CFG_PATH) as f: c = json.load(f)
    for k, v in (c.get("imports") or {}).items():
        assert int(k) >= 1 and len(v["established"]) == v["established_count"], f"import for segment {k}: established_count mismatch"
        assert all(a.startswith("poa1") for a in v["established"]), "import addresses are poa1"
    return c
CFG = load_cfg()

def imported(seg):
    """Agents the segment's genesis import flags established (empty when the segment has no import)."""
    v = (CFG.get("imports") or {}).get(str(seg))
    return frozenset(v["established"]) if v else frozenset()

def import_info(seg):
    v = (CFG.get("imports") or {}).get(str(seg))
    return {k: v[k] for k in ("url", "sha256", "final_checkpoint_height", "agents", "established_count")} if v else None

def ttl_of(params):
    try: return int((params or {}).get(CFG.get("ttl_param", "estab_ttl")) or CFG.get("ttl_default", 6))
    except (TypeError, ValueError): return int(CFG.get("ttl_default", 6))

def _pardoned(pardons, n, a, slashed):
    l = (pardons or {}).get(n, (pardons or {}).get(str(n)))
    return isinstance(l, list) and a in l and a in slashed

def fold(closes, seed=frozenset(), pardons=None):
    """(established set after the last close, {address: last challenge_eligible close}, {address: (how, close)}) for one
    segment's closes. how: "import", "added" or "removed" (the latest change)."""
    est = set(seed); le = {}; why = {a: ("import", None) for a in seed}
    for e in sorted(closes, key=lambda r: int(r.get("epoch", 0))):
        n = int(e.get("epoch", 0)); b = e.get("basis", {}) or {}
        sl = set(b.get("slashed") or [])
        for a in b.get("established_after") or []: est.add(a); why[a] = ("added", n)
        for a in b.get("established_removed") or []:
            if _pardoned(pardons, n, a, sl): continue
            est.discard(a); why[a] = ("removed", n)
        for a in b.get("challenge_eligible") or []: le[a] = n
    return est, le, why

def drop_close(L, ttl):
    """The close at which the engine removes an Agent whose last challenge_eligible close is L (-1 when none): L + ttl + 1."""
    return (L if L is not None else -1) + ttl + 1
