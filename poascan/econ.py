"""Close economics per segment and epoch (1.26.257): one config for every param dependent value POAScan shows or computes.

econ_rules.json lists, per segment, epoch ranges with the rule each close ran under: estab_ttl, the intake door (floor and
rate), the waitlist, the settle cap and emission carry. A past close always reads the range it fell in, so history stays on
the old rules (E0 to E35 of segment 2 on estab_ttl 6 and max(5, 10%), E36 on under Proposal L's hybrid). The newest range
of the current segment is overlaid with POAScan's hourly /api/params copy where it carries the matching key, so a later
param flip shows up at the next read without a code change; a key the params dropped (settle_cap_per_close) reads as the
config says (null: no cap). No upstream read here."""
import json, math, os
from . import db, segments as SG

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "econ_rules.json")
KEYS = ("estab_ttl", "intake_floor", "intake_rate", "waitlist_epochs", "settle_cap", "carry_cap_pools")
METHOD = "/about#econ"

def _load(path=None):
    with open(path or PATH) as f: c = json.load(f)
    for seg, rs in (c.get("segments") or {}).items():
        assert rs and int(rs[0]["from_epoch"]) == 0, f"segment {seg}: the first range starts at E0"
        assert all(int(a["from_epoch"]) < int(b["from_epoch"]) for a, b in zip(rs, rs[1:])), f"segment {seg}: ranges in order"
        assert all(k in rs[0] for k in KEYS), f"segment {seg}: the first range sets every key"
    return c
CFG = _load()

def _ranges(seg):
    """[(from_epoch, values, source, post)] for a segment, each range carrying every key (earlier values roll forward)."""
    rs = (CFG.get("segments") or {}).get(str(seg)) or (CFG.get("segments") or {}).get(str(max(int(k) for k in CFG["segments"])))
    out, cur = [], {}
    for r in rs:
        cur = dict(cur, **{k: r[k] for k in KEYS if k in r})
        out.append((int(r["from_epoch"]), dict(cur), r.get("source"), r.get("post")))
    return out

def _params():
    """POAScan's stored /api/params copy, through analytics.params() (the cached reader every other module uses)."""
    try:
        from . import analytics as A
        p = A.params()
        return (p if isinstance(p, dict) else {}), None
    except Exception:
        try:
            p, ts = db.get_blob("params"); return (p if isinstance(p, dict) else {}), ts
        except Exception: return {}, None

def _num(v, f=int):
    try: return f(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError): return None

def at(epoch=None, seg=None, live=True):
    """{values..., from_epoch, source, live_keys, post} for the close `epoch` of segment `seg` (default: the selected
    segment; epoch None: the open epoch's rule, the newest range). live: overlay /api/params on the newest range of the
    current segment."""
    seg = seg or SG.selected(); rs = _ranges(seg)
    if epoch is None: pick = rs[-1]
    else: pick = next((r for r in reversed(rs) if int(epoch) >= r[0]), rs[0])
    v = dict(pick[1]); lk = []
    if live and seg == SG.CURRENT and pick is rs[-1]:
        p, _ = _params()
        for k, pk in (CFG.get("params_keys") or {}).items():
            if pk in p and p[pk] is not None:
                n = _num(p[pk], float if k == "intake_rate" else int)
                if n is not None and n != v.get(k): v[k] = n; lk.append(k)
                elif n is not None: lk.append(k)
    return dict(v, from_epoch=pick[0], source=pick[2], post=pick[3], live_keys=lk, segment=seg)

def ranges(seg=None):
    """The segment's ranges for the API and /about (the newest one with the live overlay)."""
    seg = seg or SG.selected(); rs = _ranges(seg); out = []
    for i, (fe, v, src, post) in enumerate(rs):
        cur = at(None, seg) if i == len(rs) - 1 else dict(v, from_epoch=fe, source=src, post=post, live_keys=[])
        out.append(dict({k: cur[k] for k in KEYS}, from_epoch=fe, to_epoch=rs[i + 1][0] - 1 if i + 1 < len(rs) else None,
                        source=src, live_keys=cur.get("live_keys", []), post=post))
    return out

def cap_of(size, floor, rate):
    return max(int(floor), math.ceil(float(rate) * int(size) - 1e-9))

def intake_cap(size, epoch=None, seg=None):
    r = at(epoch, seg); return cap_of(size, r["intake_floor"], r["intake_rate"])

def door_text(epoch=None, seg=None):
    """'max(25, ceil(25% of the set))' for the rule at `epoch`."""
    r = at(epoch, seg); pct = r["intake_rate"] * 100
    return f"max({int(r['intake_floor'])}, ceil({pct:g}% of the set))"

def estab_ttl(epoch=None, seg=None): return int(at(epoch, seg)["estab_ttl"])
def waitlist(epoch=None, seg=None): return int(at(epoch, seg)["waitlist_epochs"] or 0)
def settle_cap(epoch=None, seg=None):
    v = at(epoch, seg)["settle_cap"]; return int(v) if v else None

def period_s():
    p, _ = _params(); return _num(p.get("auto_epoch_seconds")) or 21600

def ttl_hours(ttl=None):
    """Hours an estab_ttl spans at the live epoch length."""
    return int((estab_ttl() if ttl is None else ttl) * period_s() / 3600)

def ttl_phrase(ttl=None):
    """'26 epochs, about 6.5 days' (or 'about 36 hours' under a day and a half)."""
    t = estab_ttl() if ttl is None else int(ttl); h = ttl_hours(t)
    span = f"about {h} hours" if h <= 36 else f"about {h / 24:g} days" if (h / 24) == round(h / 24, 1) else f"about {round(h / 24, 1):g} days"
    return f"{t} epochs, {span}"

def changes(seg=None):
    """[(from_epoch, {key: (old, new)}, source, post)] between consecutive ranges, for the rules note and API."""
    rs = ranges(seg); out = []
    for a, b in zip(rs, rs[1:]):
        d = {k: (a[k], b[k]) for k in KEYS if a[k] != b[k]}
        if d: out.append(dict(from_epoch=b["from_epoch"], changes={k: dict(old=o, new=n) for k, (o, n) in d.items()}, source=b["source"], post=b["post"]))
    return out

def api_block(seg=None):
    seg = seg or SG.selected()
    return dict(segment=seg, current=at(None, seg), ranges=ranges(seg), changes=changes(seg),
                note="Each close reads the range it fell in; the newest range takes /api/params where it carries the key. settle_cap null: no cap. carry_cap_pools 0: unallocated emission burns.",
                method="https://poascan.io" + METHOD)


def about_html():
    """/about#econ: the rule each close ran under, per range of the selected segment."""
    from html import escape as E
    seg = SG.selected(); rs = ranges(seg)
    f = lambda v, k: ("none" if not v else f"{v:,}") if k == "settle_cap" else ("on" if v else "off") if k == "carry_cap_pools" else ("none" if not v else f"{v} closes")
    rows = "".join(f'<tr><td>E{r["from_epoch"]}{"" if r["to_epoch"] is None else " to E" + str(r["to_epoch"])}</td><td class="r">{r["estab_ttl"]}</td>'
                   f'<td>max({int(r["intake_floor"])}, ceil({r["intake_rate"] * 100:g}%))</td><td>{f(r["waitlist_epochs"], "w")}</td>'
                   f'<td>{f(r["settle_cap"], "settle_cap")}</td><td>{f(r["carry_cap_pools"], "carry_cap_pools")}</td></tr>' for r in rs)
    return ('<h3 id="econ">Rules by close</h3><p>Each close is read under the rule it ran under, so history keeps the old values. '
            'The newest range follows the live /api/params (<code>estab_ttl</code>, <code>estab_intake_floor</code>, <code>estab_intake_rate</code>, '
            '<code>estab_waitlist_epochs</code>, <code>carry_cap_pools</code>); a dropped <code>settle_cap_per_close</code> means no cap. '
            'Established drops at close L + <code>estab_ttl</code> + 1. Intake admits up to max(floor, ceil(rate x the set)) newly eligible Agents in sha256 draw order; '
            'with a waitlist, an eligible Agent not admitted keeps its place for that many closes. Carry off: emission a close does not pay burns. '
            f'API: <code>/api/v1/governance/econ</code>.</p><div class="tw"><table class="hist gov"><thead><tr><th>Closes</th><th class="r">estab_ttl</th><th>Intake</th>'
            f'<th>Waitlist</th><th>Settle cap</th><th>Carry</th></tr></thead><tbody>{rows}</tbody></table></div>')
