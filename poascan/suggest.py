"""Header search suggestions (GET /fragment/suggest?q=): instant, typed rows from POAScan's own archive, never an upstream read.

Rows: {kind, id, label, sub, url}. kind is agent, tx or epoch. Agents match by name (LabLeak forum names plus hosted join
names, one in-memory index rebuilt every 5 minutes) or by poa1 prefix (primary key range scan, case sensitive). Txs match by
hex prefix (primary key range scan). Epochs match a number, with or without a leading E. At most 8 rows, about 1 KB."""
import re, threading, time
from . import db

ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")
ADDR_PRE = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{2,59}$")
HEX_PRE = re.compile(r"^[0-9a-fA-F]{6,64}$")
EPOCH_RX = re.compile(r"^[Ee]?(\d{1,6})$")
MAX_ROWS, MAX_AGENTS, MAX_TXS = 8, 6, 5
INDEX_S = 300
_idx = {"ts": 0, "rows": [], "names": {}}
_lock = threading.Lock()

def _build():
    """[(lower name, name, addr)] from forum names and hosted join names (labels rows, then join tx memos), one per (addr, name)."""
    from . import analytics as A
    seen, rows, names = set(), [], {}
    def add(a, n):
        n = (n or "").strip()
        if not n or not ADDR_RX.match(a or "") or (a, n.lower()) in seen: return
        seen.add((a, n.lower())); rows.append((n.lower(), n, a)); names.setdefault(a, n)
    for a, n in (A.forum_names() or {}).items(): add(a, n)
    for r in db.q("SELECT addr, label FROM labels WHERE source='join memo' AND label != ''"): add(r["addr"], r["label"])
    for r in db.q("SELECT from_addr, memo FROM txs WHERE type='join' AND memo IS NOT NULL AND lower(memo) LIKE 'hosted join%'"):
        add(r["from_addr"], re.sub(r"^hosted join:?\s*", "", r["memo"] or "", flags=re.I))
    return rows, names

def _index():
    now = time.time()
    if now - _idx["ts"] > INDEX_S:
        with _lock:
            if now - _idx["ts"] > INDEX_S:
                try: _idx["rows"], _idx["names"] = _build()
                except Exception: pass   # keep the last index; a failed rebuild never blanks suggestions
                _idx["ts"] = now
    return _idx["rows"], _idx["names"]

def _bal(addrs):
    if not addrs: return {}
    from .ui import compact
    rs = db.q(f"SELECT addr, balance_s, balance FROM accounts WHERE addr IN ({','.join('?' * len(addrs))})", tuple(addrs))
    out = {}
    for r in rs:
        try: v = float(r["balance_s"] if r["balance_s"] is not None else r["balance"])
        except (TypeError, ValueError): continue
        out[r["addr"]] = f"{compact(v)} POA"
    return out

def _short(a, h=6, t=4): return a if len(a) <= h + t + 1 else f"{a[:h]}…{a[-t:]}"

def _agents(pairs):
    b = _bal([a for a, _ in pairs])
    return [dict(kind="agent", id=a, label=n or _short(a), sub=b.get(a, ""), url=f"/address/{a}") for a, n in pairs]

def _epochs(n):
    from . import segments as S   # the newest close number of the current segment: one indexed MAX, never the epoch rows walk
    r = db.q1("SELECT MAX(epoch) AS m FROM close_rows WHERE kind=?", (S.blob_kind(),)); last = r and r["m"]
    if last is None:   # close rows not stored yet (fresh start): the slim close list, read once and kept by analytics
        from . import analytics as A
        raw = A.epochs_raw(); last = int(raw[-1]["epoch"]) if raw else None
    if last is None or n > last + 1: return []
    return [dict(kind="epoch", id=f"E{n}", label=f"Epoch {n}", sub="Open" if n == last + 1 else "Closed", url=f"/epoch/{n}")]

def suggest(q):
    q = (q or "").strip()[:64]
    if len(q) < 2: return []
    from . import keysafe as KS
    if KS.has_key(q): return []   # a pasted key is never looked up or echoed
    out = []
    m = EPOCH_RX.match(q)
    if m: out += _epochs(int(m.group(1)))
    if ADDR_PRE.match(q):
        rows, names = _index()
        hits = [r["addr"] for r in db.q("SELECT addr FROM accounts WHERE addr >= ? AND addr < ? ORDER BY addr LIMIT ?", (q, q + "\U0010ffff", MAX_AGENTS))]
        if ADDR_RX.match(q) and q not in hits: hits = [q] + hits[:MAX_AGENTS - 1]
        out += _agents([(a, names.get(a)) for a in hits])
    if HEX_PRE.match(q):
        lo = q.lower()
        out += [dict(kind="tx", id=r["id"], label=_short(r["id"], 10, 6), sub=r["type"] or "", url=f"/tx/{r['id']}")
                for r in db.q("SELECT id, type FROM txs WHERE id >= ? AND id < ? ORDER BY id LIMIT ?", (lo, lo + "g", MAX_TXS))]
    if not q.lower().startswith("poa1") and not (HEX_PRE.match(q) and len(q) > 12):
        ql = q.lower(); rows, _ = _index()
        hits = sorted(((r[0] != ql, not r[0].startswith(ql), r[0].find(ql), len(r[0]), r[1], r[2]) for r in rows if ql in r[0]))
        seen, pairs = {o["id"] for o in out}, []
        for *_, n, a in hits:
            if a in seen: continue
            seen.add(a); pairs.append((a, n))
            if len(pairs) >= MAX_AGENTS: break
        out += _agents(pairs)
    return out[:MAX_ROWS]
