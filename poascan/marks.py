"""Phase 3: maker's marks and hallmarks. A guilloche rosette is drawn from a seed: an Agent's address (its maker's mark) or a close's
own record (its hallmark: epoch, Agents paid, POA minted). Pure functions of public data, so a mark is reproducible by anyone and
never changes: the URL carries the whole seed, the SVG is cached in memory (LRU) and served immutable for a year. Rendering is a
few thousand float operations; nothing here reads the database or minepoa.

  /mark/{address}.svg                  maker's mark (gold, 4 layers)
  /hallmark/{epoch}-{paid}-{minted}.svg  hallmark (gold when the close paid Agents, bone when it paid none; 3 layers)"""
import functools, math, re

GOLD, BONE3 = "#FFB000", "#8C836F"   # style.css tokens --gold, --bone-3
ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")
HALL_RX = re.compile(r"^(\d{1,6})-(\d{1,7})-(\d{1,15})$")
CACHE = "public, max-age=31536000, immutable"

def _h32(s, seed):
    h = seed & 0xFFFFFFFF
    for ch in s: h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h

def _rng(seed):
    x = [seed or 1]
    def r():
        v = x[0]; v ^= (v << 13) & 0xFFFFFFFF; v ^= v >> 17; v ^= (v << 5) & 0xFFFFFFFF; x[0] = v & 0xFFFFFFFF
        return (x[0] % 100000) / 100000
    return r

def _curve(rad, q, k, ph, n, fn, dec=1):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n; rr = rad * fn(q, k, t, ph)
        pts.append(f"{50 + rr * math.cos(t):.{dec}f} {50 + rr * math.sin(t):.{dec}f}")
    return "M" + "L".join(pts) + "Z"

def _plan(seed, layers):
    """The rosette's curves for a seed: [(radius, q, k, phase, kind, width scale, opacity)], in draw order. Shared by the SVG and
    the link-preview raster (og.py), so both draw the same mark."""
    r = _rng(_h32(str(seed), 2166136261)); out = []
    for L in range(layers):
        k = 5 + int(r() * 9); q = 0.18 + r() * 0.22; rad = 42 * (1 - L * 0.17)
        out.append((rad, q, k, L, "cos", 1.0, round(0.85 - L * 0.14, 2)))
        k2 = k + 2 + int(r() * 5)
        if L < 2: out.append((rad * 0.62, q * 0.8, k2, 0, "sin", 0.8, 0.5))
    return out

def _fn(kind):
    return (lambda q, k, t, ph: 1 - q + q * math.cos(k * t + ph)) if kind == "cos" else (lambda q, k, t, ph: 1 - q + q * math.sin(k * t))

def points(seed, layers, n, scale=1.0, cx=50.0, cy=50.0):
    """Float points per curve, for rasters: [(pts, width scale, opacity)]."""
    out = []
    for rad, q, k, ph, kind, ws, op in _plan(seed, layers):
        f = _fn(kind); pts = []
        for i in range(n + 1):
            t = 2 * math.pi * i / n; rr = rad * f(q, k, t, ph) * scale
            pts.append((cx + rr * math.cos(t), cy + rr * math.sin(t)))
        out.append((pts, ws, op))
    return out

@functools.lru_cache(maxsize=4096)
def rosette(seed, layers=4, color=GOLD, n=240, w=0.8, dec=1):
    """SVG text for one rosette in a 100 unit box. Strokes do not scale (vector-effect), so a 28 px hallmark and a 120 px maker's
    mark both draw hairlines."""
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="none" stroke="{color}" stroke-linejoin="round">',
         f'<g vector-effect="non-scaling-stroke"><circle cx="50" cy="50" r="49" stroke-opacity=".35" stroke-width="{w}" vector-effect="non-scaling-stroke"/>',
         f'<circle cx="50" cy="50" r="45" stroke-opacity=".2" stroke-width="{w}" stroke-dasharray="1 3" vector-effect="non-scaling-stroke"/>']
    for rad, q, k, ph, kind, ws, op in _plan(seed, layers):
        d = _curve(rad, q, k, ph, n, _fn(kind), dec)
        sw = w if ws == 1.0 else f"{w * ws:.2f}"; so = f"{op:.2f}" if kind == "cos" else ".5"
        o.append(f'<path d="{d}" stroke-width="{sw}" stroke-opacity="{so}" vector-effect="non-scaling-stroke"/>')
    return "".join(o) + "</g></svg>"

def hall_key_seed(key):
    """(rosette seed, paid) for a strict hallmark key, or None."""
    m = HALL_RX.match(key or "")
    if not m: return None
    e, p, mi = (int(x) for x in m.groups())
    return f"E{e}:{p}:{mi}", p

def agent_svg(addr):
    """The maker's mark for an address, or None when it is not a poa1 address."""
    return rosette(addr, 4, GOLD, 240) if ADDR_RX.match(addr or "") else None

def hall_seed(epoch, paid, minted):
    return f"{int(epoch)}-{int(paid or 0)}-{int(round(float(minted or 0)))}"

def hall_svg(key):
    """The hallmark for '{epoch}-{paid}-{minted}', or None when the key is malformed."""
    m = HALL_RX.match(key or "")
    if not m: return None
    e, p, mi = (int(x) for x in m.groups())
    return rosette(f"E{e}:{p}:{mi}", 3, GOLD if p else BONE3, 144, 0.8, 0)   # small: 144 points, whole units, about 1.6 KB gzipped

def mark_img(addr, size=48, cls="mmark"):
    """<img> for a maker's mark (decorative: the name or address sits beside it)."""
    if not ADDR_RX.match(addr or ""): return ""
    return f'<img class="{cls}" src="/mark/{addr}.svg" width="{size}" height="{size}" alt="" aria-hidden="true" loading="lazy" decoding="async">'

def hall_img(r, size=28, cls="hmark"):
    """<img> for a close's hallmark from its row (epoch, paid, minted)."""
    k = hall_seed(r.get("epoch"), r.get("paid"), r.get("minted"))
    return f'<img class="{cls}" src="/hallmark/{k}.svg" width="{size}" height="{size}" alt="" aria-hidden="true" loading="lazy" decoding="async">'
