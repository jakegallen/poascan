"""Link-preview images for /tx, /address and /epoch. Rendered from the local archive only (never calls minepoa.com),
one at a time, cached in memory. Without Pillow the generic og-card.png is served instead."""
import io, os, re, threading, time, collections
from . import db, analytics as A, views as V
from .ui import TYPE_LABEL, ADDR_RX, plain, compact

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = None

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "og_assets")
W, H = 1200, 630
BG, HI, DIM, MUTE, AMBER, GREEN = (14, 13, 11), (246, 240, 226), (165, 156, 138), (122, 114, 95), (255, 176, 0), (61, 220, 151)
_LOCK = threading.Lock(); _CACHE = collections.OrderedDict(); _MAX = 300
_F = {}

def available(): return Image is not None

def _font(kind, size, weight):
    k = (kind, size, weight)
    if k not in _F:
        f = ImageFont.truetype(os.path.join(HERE, "SpaceGrotesk.ttf" if kind == "ui" else "JetBrainsMono.ttf"), size)
        try: f.set_variation_by_axes([weight])
        except Exception: pass
        _F[k] = f
    return _F[k]

def _mark():
    if "mark" not in _F: _F["mark"] = Image.open(os.path.join(HERE, "mark.png")).convert("RGBA")
    return _F["mark"]

def _fit(d, text, kind, size, weight, width):
    """Largest size <= `size` that fits `width`, then ellipsize if still too long."""
    while size > 28 and d.textlength(text, font=_font(kind, size, weight)) > width: size -= 4
    f = _font(kind, size, weight)
    while d.textlength(text, font=f) > width and len(text) > 4: text = text[:-2].rstrip() + "…"
    return text, f

def card(kicker, title, sub, stats):
    """kicker: small amber label; title: big line; sub: mono id line(s); stats: [(label, value)] up to 3."""
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    for y in range(18, H, 36):                      # faint dot grid, like the generic card
        for x in range(18, W, 36): d.point((x, y), fill=(32, 30, 26))
    m = _mark(); big = m.resize((int(m.width * 1.9), int(m.height * 1.9)), Image.LANCZOS)
    a = big.getchannel("A").point(lambda v: v * 0.09); big.putalpha(a)
    im.paste(big, (W - big.width + 70, H - big.height + 40), big)     # watermark
    sm = m.resize((44, 50), Image.LANCZOS); im.paste(sm, (72, 58), sm)
    d.text((128, 62), "POA", font=_font("ui", 34, 700), fill=HI)
    d.text((128 + d.textlength("POA", font=_font("ui", 34, 700)), 62), "SCAN", font=_font("ui", 34, 700), fill=AMBER)
    if kicker: d.text((72, 160), kicker.upper(), font=_font("mono", 24, 600), fill=AMBER)
    t, f = _fit(d, title, "ui", 76, 700, W - 144); d.text((70, 196), t, font=f, fill=HI)
    y = 300
    for line in sub[:2]:
        s, f = _fit(d, line, "mono", 30, 400, W - 144); d.text((72, y), s, font=f, fill=DIM); y += 42
    x = 72; cw = (W - 144) // 3
    for lbl, val in stats[:3]:
        d.text((x, 420), lbl.upper(), font=_font("mono", 20, 500), fill=MUTE)
        v, f = _fit(d, val, "ui", 44, 600, cw - 24); d.text((x, 450), v, font=f, fill=HI); x += cw
    d.ellipse((72, 556, 86, 570), fill=GREEN)
    d.text((98, 548), "poascan.io", font=_font("mono", 24, 400), fill=DIM)
    d.rectangle((0, H - 10, W, H), fill=AMBER)
    out = io.BytesIO(); im.save(out, "PNG", optimize=True); return out.getvalue()

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
    st = [("Epoch", f"E{ep}" if ep is not None else "···"), ("Status", "Final" if d.get("final") else "Pending"), ("Time", time.strftime("%b %d %H:%M UTC", time.gmtime(d["ts"])) if d.get("ts") else "···")]
    return ("Transaction", title, [tid[:32], tid[32:]], st), bool(d.get("final"))

def _address(a):
    acc = db.q1("SELECT balance, first_seen FROM accounts WHERE addr=?", (a,))
    nm = V.names().get(a)
    return ("Agent", nm or (a[:10] + "…" + a[-6:]), [a] if nm else [], [("Balance", (compact(acc["balance"]) + " POA") if acc and acc["balance"] is not None else "···"), ("First seen", _utc(acc["first_seen"])[:10] if acc else "···")]), False

def _epoch(n):
    r = {x["epoch"]: x for x in A.epoch_rows()}.get(n)
    if not r: return (None, f"Epoch {n:,}", ["Open"], []), False
    return (None, f"Epoch {n:,}", [f"Closed {_utc(r.get('close_ts'))}"],
            [("Minted", compact(r["minted"]) + " POA"), ("Burn", f'{r["burn_pct"]:.1f}%'), ("Paid agents", f'{r["paid"]:,}')]), True

ROUTE = re.compile(r"^/og/(tx|address|epoch)/([^/]+)\.png$")

def render(path):
    """Returns (png bytes, max-age) or None for a path that is not an OG route."""
    m = ROUTE.match(path)
    if not m: return None
    kind, key = m.groups()
    if kind == "tx" and not re.fullmatch(r"[0-9a-f]{64}", key): return None
    if kind == "address" and not ADDR_RX.match(key): return None
    if kind == "epoch" and not key.isdigit(): return None
    now = time.time(); hit = _CACHE.get(path)
    if hit and now < hit[0]: _CACHE.move_to_end(path); return hit[1], hit[2]
    with _LOCK:                                   # one render at a time keeps CPU light
        spec, done = {"tx": _tx, "address": _address, "epoch": lambda k: _epoch(int(k))}[kind](key)
        png = card(*spec)
    age = 86400 if done else 900
    _CACHE[path] = (now + age, png, age)
    while len(_CACHE) > _MAX: _CACHE.popitem(last=False)
    return png, age

def url_for(path):
    """og:image for a detail page, or None to keep the generic card."""
    if not available(): return None
    m = re.match(r"^/(tx|address|epoch)/([^/]+)$", path or "")
    return f"og/{m.group(1)}/{m.group(2)}.png" if m else None
