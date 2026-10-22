"""Playwright checks for the header/drawer at many widths, on home and one other page (default /epochs). Usage: menu_test.py BASE OUTDIR [PAGE2]"""
import sys, os, json
from playwright.sync_api import sync_playwright
base, out = sys.argv[1], sys.argv[2]; os.makedirs(out, exist_ok=True)
PAGE2 = sys.argv[3] if len(sys.argv) > 3 else "/epochs"
W = [360, 390, 430, 600, 768, 900, 1024, 1100, 1101, 1200, 1300, 1440]
CHECK = """() => {
 const r = e => e ? e.getBoundingClientRect() : null, q = s => document.querySelector(s);
 const burger = q('.burger'), nav = q('#nav'), hdr = q('.hdr');
 const bv = getComputedStyle(burger).display !== 'none';
 const ns = getComputedStyle(nav); const links = [...nav.querySelectorAll('a')];
 const sw = q('.swaplink'), pill = q('#livepill');
 const out = {burger: bv, overflowX: document.documentElement.scrollWidth - innerWidth, navVisibility: ns.visibility, navPos: ns.position,
   swapTab: links.some(a => (a.getAttribute('href') || '').startsWith('/swaps')), swapBtn: !!sw && r(sw).width > 0 && r(sw).right <= innerWidth,
   pillShown: !!pill && getComputedStyle(pill).display !== 'none'};
 const dot = q('#updot'); out.dot = !!dot && getComputedStyle(dot).display !== 'none';
 if (out.dot) { const d = r(dot); out.dotIn = d.left >= 0 && d.right <= innerWidth && d.width >= 24 && d.height >= 24 && d.bottom <= r(hdr).bottom; }
 // header controls never overlap each other, at any width (the drawer nav is checked separately)
 const hi = [q('.brand'), bv ? null : nav, q('.search'), pill, dot, sw, q('.joinbtn'), bv ? burger : null].filter(e => e && getComputedStyle(e).display !== 'none' && r(e).width > 0).map(r);
 let hov = 0; for (let i = 0; i < hi.length; i++) for (let j = i+1; j < hi.length; j++) { const a = hi[i], b = hi[j];
   if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) hov++; }
 out.hdrOverlaps = hov;
 if (bv) {
   const nr = r(nav); out.nav = {top: Math.round(nr.top), bottom: Math.round(nr.bottom), w: Math.round(nr.width), hdrBottom: Math.round(r(hdr).bottom)};
   out.linksHitOk = links.every(a => { const b = r(a); if (b.bottom > innerHeight) return true; const el = document.elementFromPoint(b.left + b.width/2, b.top + b.height/2); return el && (el === a || a.contains(el)); });
   out.minLinkH = Math.min(...links.map(a => r(a).height));
   out.bodyLocked = getComputedStyle(document.documentElement).overflow;
 } else {
   // desktop row: nothing in the header row may overlap
   const items = [q('.brand'), nav, q('.search'), q('#livepill'), q('#updot'), q('.swaplink'), q('.joinbtn')].filter(Boolean).map(r);
   let ov = 0; for (let i = 0; i < items.length; i++) for (let j = i+1; j < items.length; j++) { const a = items[i], b = items[j];
     if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) ov++; }
   out.overlaps = ov; out.hdrH = Math.round(r(hdr).height);
 }
 return out; }"""
res = {}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for w in W:
        ctx = b.new_context(viewport={"width": w, "height": 820}, is_mobile=w < 1024, has_touch=w < 1024, device_scale_factor=1)
        pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + PAGE2, wait_until="networkidle"); pg.wait_for_timeout(500)   # a non-home page: the status dot shows there while Upgrading
        r = {"page2": pg.evaluate(CHECK)}; pg.screenshot(path=f"{out}/w{w}-page2.png")
        pg.goto(base + "/", wait_until="networkidle"); pg.wait_for_timeout(500)
        r["closed"] = pg.evaluate(CHECK)
        pg.screenshot(path=f"{out}/w{w}-closed.png")
        if r["closed"]["burger"]:
            pg.click(".burger"); pg.wait_for_timeout(300)
            r["open"] = pg.evaluate(CHECK); pg.screenshot(path=f"{out}/w{w}-open.png")
            pg.keyboard.press("Escape"); pg.wait_for_timeout(250); r["afterEsc"] = pg.evaluate("document.body.classList.contains('navopen')")
            pg.click(".burger"); pg.wait_for_timeout(250); pg.mouse.click(w // 2, 30); pg.wait_for_timeout(250)
            r["afterOutside"] = pg.evaluate("document.body.classList.contains('navopen')")
            pg.click(".burger"); pg.wait_for_timeout(250)
            pg.click("#nav a[href='/token']"); pg.wait_for_load_state("networkidle"); r["afterLink"] = pg.url
        r["errors"] = errs; res[w] = r; ctx.close()
    b.close()
print(json.dumps(res, indent=0))
# Summary: no horizontal scroll, no header overlap, POASwap button in view, no Swap tab; the dot never on home and, when shown, in the header
bad = [f"{w}:{k}" for w, r in res.items() for k in ("page2", "closed") if r[k]["overflowX"] > 0 or r[k]["hdrOverlaps"] or r[k].get("overlaps") or not r[k]["swapBtn"] or r[k]["swapTab"]
       or (k == "closed" and r[k]["dot"]) or (r[k]["dot"] and not r[k].get("dotIn")) or (r[k]["dot"] and r[k]["pillShown"]) or r["errors"]]
print("dot shown on page2 at", [w for w, r in res.items() if r["page2"]["dot"]])
print("FAIL " + " ".join(bad) if bad else "menu: all widths ok"); sys.exit(1 if bad else 0)
