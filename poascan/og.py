"""Link-preview images for /tx, /address and /epoch. Rendered from the local archive only (never calls minepoa.com),
one at a time, cached in memory. Without Pillow the generic og-card.png is served instead."""
import io, os, re, threading, time, collections
from . import db, analytics as A, agents as G, views as V
from .ui import TYPE_LABEL, ADDR_RX, plain, compact

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = None

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "og_assets")
FONTS = os.path.join(os.path.dirname(HERE), "..", "static", "fonts")
W, H = 1200, 630
# style.css tokens: --ink-1, --bone-hi, --bone-2, --bone-3, --gold, --verd, --rule, --rule-2
BG, HI, DIM, MUTE, AMBER, GREEN, RULE, RULE2 = (16, 14, 10), (246, 240, 226), (185, 175, 153), (140, 131, 111), (255, 176, 0), (79, 197, 154), (39, 34, 25), (58, 51, 37)
_LOCK = threading.Lock(); _RENDER = threading.Lock(); _CACHE = collections.OrderedDict(); _MAX = 300
_F = {}
# Crawlers can ask for thousands of distinct previews at once. Renders draw from a small token bucket (a burst of 6, then one every
# 5 s); a miss with no token gets the generic card for 5 minutes, uncached here, so CPU on the shared machine stays flat.
BURST, REFILL = 6, 5.0
_BUCKET = [float(BURST), time.monotonic()]
FALLBACK_AGE = 300

def available(): return Image is not None

def _fallback():
    if "card" not in _F: _F["card"] = open(os.path.join(os.path.dirname(HERE), "..", "static", "og-card.png"), "rb").read()
    return _F["card"]

def _take():
    with _LOCK:
        now = time.monotonic(); t, last = _BUCKET
        t = min(BURST, t + (now - last) / REFILL)
        if t < 1: _BUCKET[:] = [t, now]; return False
        _BUCKET[:] = [t - 1, now]; return True

# The site's own type: Newsreader for figures and titles, Instrument Sans for labels, IBM Plex Mono for ids. The woff2 files in
# static/fonts are read directly (Pillow's FreeType has WOFF2); the older TTFs stay as a fallback.
_FILES = {"fig": ("newsreader-latin-54fd93.woff2", "SpaceGrotesk.ttf"), "ui": ("instrumentsans-latin-a64857.woff2", "SpaceGrotesk.ttf"),
          "mono": ("plexmono400-latin-08949f.woff2", "JetBrainsMono.ttf"), "mono5": ("plexmono500-latin-01d285.woff2", "JetBrainsMono.ttf")}

def _font(kind, size, weight=400):
    k = (kind, size, weight)
    if k not in _F:
        new, old = _FILES[kind]
        try: f = ImageFont.truetype(os.path.join(FONTS, new), size)
        except Exception: f = ImageFont.truetype(os.path.join(HERE, old), size)
        if kind == "ui":
            try: f.set_variation_by_axes([weight])
            except Exception: pass
        _F[k] = f
    return _F[k]

def _mark():
    if "mark" not in _F: _F["mark"] = Image.open(os.path.join(HERE, "mark.png")).convert("RGBA")
    return _F["mark"]

def _fit(d, text, kind, size, weight, width, floor=28):
    """Largest size <= `size` that fits `width`, then ellipsize if still too long."""
    while size > floor and d.textlength(text, font=_font(kind, size, weight)) > width: size -= 4
    f = _font(kind, size, weight)
    while d.textlength(text, font=f) > width and len(text) > 4: text = text[:-2].rstrip() + "\u2026"
    return text, f

def _label(d, xy, text, size=17, fill=MUTE, track=2.2):
    """Uppercase label with letter spacing, as .lbl on the site."""
    x, y = xy; f = _font("ui", size, 600)
    for ch in text.upper(): d.text((x, y), ch, font=f, fill=fill); x += d.textlength(ch, font=f) + track
    return x

def rosette_png(seed, layers, size, color=AMBER, n=360, alpha=1.0):
    """The maker's mark or hallmark (marks.py) as an RGBA image: drawn at 2x and reduced, so the hairlines stay clean."""
    from . import marks as MK
    S = size * 2; sc = S / 100.0; im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    def ring(r, op, dash=False):
        lay = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(lay); c = S / 2; rr = r * sc
        if dash:
            for i in range(180):
                if i % 4 == 0: d.arc((c - rr, c - rr, c + rr, c + rr), i * 2, i * 2 + 1.6, fill=color + (int(255 * op * alpha),), width=2)
        else: d.ellipse((c - rr, c - rr, c + rr, c + rr), outline=color + (int(255 * op * alpha),), width=2)
        return lay
    im = Image.alpha_composite(im, ring(49, .35)); im = Image.alpha_composite(im, ring(45, .2, True))
    for pts, ws, op in MK.points(seed, layers, n, sc, S / 2, S / 2):
        lay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(lay).line(pts, fill=color + (int(255 * op * alpha),), width=max(2, round(3 * ws)), joint="curve")
        im = Image.alpha_composite(im, lay)
    return im.resize((size, size), Image.LANCZOS)

def card(kicker, title, sub, stats, art=None):
    """kicker: small label; title: the big line (Newsreader); sub: mono id line(s); stats: [(label, value)] up to 3;
    art: (seed, layers, paid) for a maker's mark or hallmark on the right, else the POAScan mark as a faint watermark."""
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    tw = W - 144
    if art:
        seed, layers, paid = art; ro = rosette_png(seed, layers, 420, AMBER if paid else MUTE)
        im.paste(ro, (W - 72 - 420 + 24, 104), ro); tw = W - 144 - 420
    else:
        m = _mark(); big = m.resize((int(m.width * 1.9), int(m.height * 1.9)), Image.LANCZOS)
        a = big.getchannel("A").point(lambda v: v * 0.07); big.putalpha(a)
        im.paste(big, (W - big.width + 70, H - big.height + 40), big)
    sm = _mark().resize((30, 34), Image.LANCZOS)
    im.paste(sm, (72, 60), sm)
    x = _label(d, (114, 66), "POA", 22, HI, 3.2); _label(d, (x, 66), "SCAN", 22, AMBER, 3.2)
    if kicker: _label(d, (72, 164), kicker, 18, AMBER, 2.6)
    t, f = _fit(d, title, "fig", 92, 400, tw, 44); d.text((70, 196), t, font=f, fill=HI)
    y = 318
    for line in sub[:2]:
        s, f = _fit(d, line, "mono", 26, 400, tw, 18); d.text((72, y), s, font=f, fill=DIM); y += 38
    if stats:
        d.line((72, 418, 72 + tw, 418), fill=RULE2, width=1)
        x = 72; cw = tw // max(1, min(3, len(stats)))
        for lbl, val in stats[:3]:
            _label(d, (x, 440), lbl, 16)
            v, f = _fit(d, val, "fig", 48, 400, cw - 24, 24); d.text((x, 468), v, font=f, fill=HI); x += cw
    d.ellipse((72, 566, 82, 576), fill=GREEN)
    d.text((94, 558), "poascan.io", font=_font("mono", 22), fill=DIM)
    d.rectangle((0, H - 4, W, H), fill=AMBER)
    out = io.BytesIO(); im.quantize(128, method=Image.Quantize.MEDIANCUT).save(out, "PNG", optimize=True)   # about 45 KB, not 110
    return out.getvalue()

def _utc(ts): return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts)) if ts else "···"
def _poa(v):
    try: return plain(float(v), 4) + " POA"
    except Exception: return "···"

def _tx(tid):
    d = None
    r = db.q1("SELECT json FROM tx_detail WHERE id=?", (tid,))
    if r: import json; d = json.loads(r["json"])
    if not d: d = db.q1("SELECT id, type, from_addr, to_addr, amount, epoch, ts, final FROM txs WHERE id=?", (tid,))
    d = dict(d or {}); t = d.get("type")
    label = TYPE_LABEL.get(t, (t or "Transaction").replace("-", " ")).title()
    amt = d.get("amount"); title = f"{label} · {_poa(amt)}" if amt not in (None, "", "0") else label
    if not d: return (None, "Transaction", [tid[:32], tid[32:]], []), False
    ep = d.get("epoch") if d.get("epoch") is not None else (d.get("body") or {}).get("epoch")
    if ep is None and d.get("ts"): ep = G.epoch_of_ts(d["ts"])
    st = [("Epoch", f"E{ep}" if ep is not None else "···"), ("Status", "Final" if d.get("final") else "Pending"), ("Time · UTC", time.strftime("%b %d %H:%M", time.gmtime(d["ts"])) if d.get("ts") else "···")]
    fa = d.get("from_addr") or d.get("from") or ""
    return ("Transaction", title, [tid[:32], tid[32:]], st, (fa, 4, True) if ADDR_RX.match(fa) else None), bool(d.get("final"))

def _address(a):
    acc = db.q1("SELECT balance, first_seen FROM accounts WHERE addr=?", (a,))
    nm = V.names().get(a)
    return ("Agent", nm or (a[:10] + "…" + a[-6:]), [a] if nm else [], [("Balance", (compact(acc["balance"]) + " POA") if acc and acc["balance"] is not None else "···"), ("First seen", _utc(acc["first_seen"])[:10] if acc else "···")], (a, 4, True)), False

def _epoch(n):
    r = {x["epoch"]: x for x in A.epoch_rows()}.get(n)
    if not r: return ("Open epoch", f"Epoch {n:,}", ["Open"], []), False
    return ("Closed epoch", f"Epoch {n:,}", [f"Closed {_utc(r.get('close_ts'))}"],
            [("Minted", compact(r["minted"]) + " POA"), ("Burned", f'{r["burn_pct"]:.1f}%'), ("Agents paid", f'{r["paid"]:,}')], _hall(r)), True

def _hall(r):
    from . import marks as MK
    seed, paid = MK.hall_key_seed(MK.hall_seed(r.get("epoch"), r.get("paid"), r.get("minted")))
    return (seed, 3, bool(paid))

ROUTE = re.compile(r"^/og/(tx|address|epoch)/([^/]+)\.png$")

def _upgrade():
    from . import maint as M
    rh = M.probe_halts()
    if M.complete() and rh:   # 1.26.188: routes halted per POAScan's probes outrank the completion notice
        return ("Network status", "Routes halted", ["Per POAScan probes"], [(r["label"], "Halted" if r["state"] == "halted" else "Down") for r in rh[:3]])
    if M.complete():
        g = M.grading_state()["state"]
        if g == "open": return ("Network upgrade", "Upgrade complete", ["Mining, grading and joining open"], [("Mining", "Open"), ("Grading", "Open"), ("Joining", "Open")])
        return ("Network upgrade", "Upgrade complete per notice", ["Grading not yet confirmed" if g == "unconfirmed" else "Grading halted"],
                [("Mining", "Open"), ("Grading", "Unconfirmed" if g == "unconfirmed" else "Halted"), ("Joining", "Open")])
    lead = M.strip_text()[0]; jp = M.join_state() == "paused"   # a paused join is already in the lead; no second row saying so
    r = M.recovery()
    if r["moved"]:
        from . import hosted as R
        rt = R.current(); ds = M.route_display(); lab = {"open": "Open", "responding": "Responding", "paused": "Paused", "slow": "Slow"}
        return ("Network upgrade", lead, [f'Checkpoint {r["checkpoint"]:,}' + (" · balances intact" if r["supply_intact"] else "")],
                [(rt[k]["label"], lab.get(ds[k], "Not read yet")) for k in ("mining", "grading")] + [("Self-custody", "Working")])
    return ("Network upgrade", lead, ["Rewards paying · epochs closing"],
            ([] if jp else [("Joining", "Open")]) + [("Self-custody", "Working"), ("Finalized height", "Parked")])

def render(path):
    """Returns (png bytes, max-age) or None for a path that is not an OG route."""
    if path == "/og/upgrade.png":
        now = time.time(); hit = _CACHE.get(path)
        if hit and now < hit[0]: return hit[1], hit[2]
        if not _take(): return _fallback(), FALLBACK_AGE
        with _RENDER: png = card(*_upgrade())
        _CACHE[path] = (now + 600, png, 600); return png, 600
    m = ROUTE.match(path)
    if not m: return None
    kind, key = m.groups()
    if kind == "tx" and not re.fullmatch(r"[0-9a-f]{64}", key): return None
    if kind == "address" and not ADDR_RX.match(key): return None
    if kind == "epoch" and not key.isdigit(): return None
    now = time.time(); hit = _CACHE.get(path)
    if hit and now < hit[0]: _CACHE.move_to_end(path); return hit[1], hit[2]
    if not _take(): return _fallback(), FALLBACK_AGE   # over the render budget: the generic card, not cached here
    with _RENDER:                                 # one render at a time keeps CPU light
        spec, done = {"tx": _tx, "address": _address, "epoch": lambda k: _epoch(int(k))}[kind](key)
        png = card(*spec)
    age = 86400 if done else 900
    _CACHE[path] = (now + age, png, age)
    while len(_CACHE) > _MAX: _CACHE.popitem(last=False)
    return png, age

def url_for(path):
    """og:image for a detail page, or None to keep the generic card."""
    if not available(): return None
    if path == "/upgrade": return "og/upgrade.png"
    m = re.match(r"^/(tx|address|epoch)/([^/]+)$", path or "")
    return f"og/{m.group(1)}/{m.group(2)}.png" if m else None
