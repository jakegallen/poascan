"""Regenerate POAScan favicons + og card from the logo artwork. Usage: python3 tools/make_icons.py <logo.jpg>"""
import sys, os
import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont
OUT = os.path.join(os.path.dirname(__file__), "..", "static")
BG = (14, 13, 11)
src = Image.open(sys.argv[1]).convert("RGB")
# crystal mark bbox in the 1280x720 artwork: x 220-434, y 210-467
cx, cy, side = 327, 338, 290
crop = src.crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2))
a = np.asarray(crop).astype(float)
bgv = np.array(BG, float)
# alpha = how far each pixel is from the graphite background (drops the dot grid and JPEG noise)
dist = np.clip((a - bgv).max(axis=2), 0, 255)
alpha = np.clip((dist - 28) / (150 - 28), 0, 1)
# un-premultiply colour against the background
col = np.where(alpha[..., None] > 0.02, bgv + (a - bgv) / np.maximum(alpha[..., None], 1e-3), 0)
col = np.clip(col, 0, 255)
mark = Image.fromarray(np.dstack([col, alpha * 255]).astype("uint8"), "RGBA")

def icon(size, bold=0, pad=0.10, round_bg=True):
    big = 512
    m = mark
    if bold:  # thicken strokes so they survive tiny sizes
        r, g, b, al = m.split()
        al = al.filter(ImageFilter.MaxFilter(bold))
        rgb = m.convert("RGB").filter(ImageFilter.MaxFilter(bold))
        m = Image.merge("RGBA", (*rgb.split(), al))
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    if round_bg: d.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.18), fill=BG + (255,))
    else: d.rectangle((0, 0, big, big), fill=BG + (255,))
    inner = int(big * (1 - 2 * pad))
    mm = m.resize((inner, inner), Image.LANCZOS)
    canvas.alpha_composite(mm, ((big - inner) // 2, (big - inner) // 2))
    return canvas.resize((size, size), Image.LANCZOS)

def tiny(size=16):
    k = 32; S = size * k
    c = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(c)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.18), fill=BG + (255,))
    f = S / 64.0
    hexp = [(32, 3), (57, 17.5), (57, 46.5), (32, 61), (7, 46.5), (7, 17.5)]
    pts = [(x * f, y * f) for x, y in hexp]
    d.line(pts + [pts[0], pts[1]], fill=(255, 176, 0, 255), width=int(5.2 * f), joint="curve")
    d.line([(20 * f, 33 * f), (29 * f, 42 * f), (45 * f, 22 * f)], fill=(255, 200, 90, 255), width=int(8.5 * f), joint="curve")
    return c.resize((size, size), Image.LANCZOS)

i16, i32, i48 = tiny(16), icon(32, bold=7, pad=0.04), icon(48, bold=5, pad=0.06)
i32.save(os.path.join(OUT, "favicon-32.png"))
i16.save(os.path.join(OUT, "favicon-16.png"))
i48.save(os.path.join(OUT, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)], append_images=[i16, i32])
icon(180, bold=3, pad=0.12, round_bg=False).convert("RGB").save(os.path.join(OUT, "apple-touch-icon.png"))
icon(192, bold=3, pad=0.10).save(os.path.join(OUT, "icon-192.png"))
icon(512, pad=0.10).save(os.path.join(OUT, "icon-512.png"))

# ---- 1200x630 og card ----
W, H = 1200, 630
og = Image.new("RGBA", (W, H), BG + (255,))
d = ImageDraw.Draw(og)
for x in range(20, W, 28):
    for y in range(20, H, 28):
        d.point((x, y), fill=(58, 54, 46, 255)); d.point((x+1, y), fill=(40, 37, 31, 255))
# amber glow behind mark
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse((60, 130, 420, 490), fill=(255, 176, 0, 34))
og.alpha_composite(glow.filter(ImageFilter.GaussianBlur(70)))
mk = mark.resize((320, 320), Image.LANCZOS)
og.alpha_composite(mk, (80, 152))
FD = os.environ.get("POASCAN_FONT_DIR", "/usr/share/fonts/truetype/google/")  # folder with the display fonts used below
def font(path, size, wght=None):
    f = ImageFont.truetype(path, size)
    if wght:
        try: f.set_variation_by_axes([wght])
        except Exception: pass
    return f
fw = font(FD + "Space Grotesk/SpaceGrotesk-VariableFont_wght.ttf", 132, 700)
fm = font(FD + "IBM Plex Mono/IBMPlexMono-Regular.ttf", 31)
fs = font(FD + "IBM Plex Mono/IBMPlexMono-Regular.ttf", 24)
x0, y0 = 450, 210
d = ImageDraw.Draw(og)
d.text((x0, y0), "POA", font=fw, fill=(243, 237, 224))
d.text((x0 + d.textlength("POA", font=fw), y0), "SCAN", font=fw, fill=(255, 176, 0))
d.text((x0 + 6, y0 + 160), "The Proof of Agent block explorer", font=fm, fill=(196, 188, 170))
# accents: amber rule + green "live" dot + domain
d.rectangle((0, H - 8, W, H), fill=(255, 176, 0))
d.rectangle((x0 + 6, y0 - 22, x0 + 126, y0 - 16), fill=(255, 176, 0))
d.ellipse((x0 + 6, 497, x0 + 22, 513), fill=(57, 211, 83))
d.text((x0 + 34, 490), "poascan.io", font=fs, fill=(140, 132, 116))
print("wordmark right edge", x0 + d.textlength("POASCAN", font=fw), "tagline right", x0 + 6 + d.textlength("The Proof of Agent block explorer", font=fm))
og.convert("RGB").save(os.path.join(OUT, "og-card.png"), optimize=True)
print("ok")
