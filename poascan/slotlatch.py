"""Slot latch pins (1.26.263). minepoa v0.84-slotlatch-cc44 added /api/params slot_latch_overrides: nonce slots where one
author sent more than one tx on the same nonce, each pinned to a fixed winner (author, nonce, txid, provenance height).
The winner is Pinned; any other tx POAScan holds for that author and nonce is Superseded and is left out of the address's
sent and type counts, so a twin is never counted twice. Read from POAScan's hourly params copy and its own archive (tx
bodies carry the nonce); no upstream read."""
from . import db, analytics as A

PINNED_TIP = "Slot latch pin: minepoa's /api/params fixes this tx as the winner of its nonce slot"

def overrides(p=None):
    """[{author, nonce, txid, height}] from /api/params slot_latch_overrides; malformed rows are skipped."""
    p = A.params() if p is None else p
    out = []
    for r in (p.get("slot_latch_overrides") if isinstance(p, dict) else None) or []:
        if not isinstance(r, dict): continue
        a, t = r.get("author"), str(r.get("txid") or "").lower()
        try: n = int(r.get("nonce"))
        except (TypeError, ValueError): continue
        if isinstance(a, str) and a.startswith("poa1") and len(t) == 64:
            out.append(dict(author=a, nonce=n, txid=t, height=r.get("provenance_height")))
    return out

def _slots(): return {(o["author"], o["nonce"]): o for o in overrides()}

def state_of(txid, author, nonce):
    """dict(state, nonce, winner, height) for a tx on a pinned slot: pinned (the winner) or superseded; None otherwise."""
    try: n = int(nonce)
    except (TypeError, ValueError): n = None
    sl = _slots(); tid = str(txid or "").lower()
    for o in sl.values():
        if o["txid"] == tid: return dict(state="pinned", nonce=o["nonce"], winner=o["txid"], height=o["height"])
    o = sl.get((author, n)) if n is not None else None
    if o: return dict(state="superseded", nonce=o["nonce"], winner=o["txid"], height=o["height"])
    return None

@A.cached("slot_latch", 120, light=True)
def index():
    """{txid: state_of(...)} for every archived tx on a pinned slot (the winner and any twins with a stored body)."""
    out = {}
    for o in overrides():
        out[o["txid"]] = dict(state="pinned", nonce=o["nonce"], winner=o["txid"], height=o["height"])
        for r in db.q("SELECT t.id AS id FROM txs t JOIN tx_detail d ON d.id = t.id WHERE t.from_addr = ? "
                      "AND CAST(json_extract(d.json, '$.body.nonce') AS INTEGER) = ?", (o["author"], o["nonce"])):
            if r["id"] != o["txid"]: out[r["id"]] = dict(state="superseded", nonce=o["nonce"], winner=o["txid"], height=o["height"])
    return out

def of(txid): return index().get(str(txid or "").lower())

def superseded_rows(a):
    """[{id, type, segment}] of archived txs sent by a that a pin superseded."""
    ids = [t for t, s in index().items() if s["state"] == "superseded"]
    if not ids: return []
    return db.q("SELECT id, type, segment FROM txs WHERE from_addr = ? AND id IN (" + ",".join("?" * len(ids)) + ")", (a, *ids))

def for_detail(d):
    """The slot state of one tx detail (its body names author and nonce), else the archive index."""
    if not isinstance(d, dict): return None
    b = d.get("body") or {}
    return state_of(d.get("id"), b.get("from") or d.get("from_addr"), b.get("nonce")) if b.get("nonce") is not None else of(d.get("id"))

def tag(s, link=True):
    """'Pinned' (ok) for the winner, 'Superseded' (warn) for a twin; '' otherwise."""
    if not s: return ""
    if s["state"] == "pinned": return f' <span class="tag ok" title="{PINNED_TIP} (nonce {int(s["nonce"])})">Pinned</span>'
    w = s["winner"]
    tip = f"Same nonce ({int(s['nonce'])}) as the pinned winner {w[:8]}; not counted"
    return f' <span class="tag warn" title="{tip}">Superseded</span>'
