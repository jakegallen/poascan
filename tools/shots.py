"""Render POAScan screenshots. Usage: shots.py BASE_URL OUTDIR ADDR TX"""
import sys, os, json
from playwright.sync_api import sync_playwright
base, out, addr, tx = sys.argv[1:5]
os.makedirs(out, exist_ok=True)
pages = {"home": "/", "token": "/token", "agents": "/agents", "address": f"/address/{addr}", "tx": f"/tx/{tx}", "growth": "/growth", "unlocks": "/unlocks"}
report = {}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for vp, (w, h, mob) in {"desktop": (1440, 900, False), "mobile": (390, 844, True)}.items():
        ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if mob else 1, is_mobile=mob, has_touch=mob)
        for name, path in pages.items():
            pg = ctx.new_page(); errs = []; ws = []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("websocket", lambda s: ws.append(s.url))
            pg.goto(base + path, wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(1200)
            # reveal all charts for the full-page capture
            pg.evaluate("document.querySelectorAll('.chart').forEach(c=>c.classList.add('in'))")
            pg.wait_for_timeout(300)
            overflow = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            f = os.path.join(out, f"{name}-{vp}.png")
            pg.screenshot(path=f, full_page=True)
            report[f"{name}-{vp}"] = dict(file=f, console_errors=errs, ws=ws, h_overflow_px=overflow)
            pg.close()
        ctx.close()
    b.close()
print(json.dumps(report, indent=1))
