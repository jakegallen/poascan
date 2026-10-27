from playwright.sync_api import sync_playwright
out = "/workspace/screenshots/graderscope1027"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for w, mob in ((1280, False), (390, True)):
        ctx = b.new_context(viewport={"width": w, "height": 900 if not mob else 844}, device_scale_factor=2 if mob else 1, is_mobile=mob, has_touch=mob)
        pg = ctx.new_page(); pg.goto("http://127.0.0.1:8971/", wait_until="networkidle"); pg.wait_for_timeout(1200)
        print(w, "overflow", pg.evaluate("document.documentElement.scrollWidth - innerWidth"), "dash", pg.evaluate("/[\\u2013\\u2014]/.test(document.body.innerText)"))
        pg.screenshot(path=f"{out}/patterns-{w}-top.png")
        pg.screenshot(path=f"{out}/patterns-{w}-full.png", full_page=True)
        pg.evaluate("document.getElementById('patterns').scrollIntoView()"); pg.wait_for_timeout(300)
        pg.screenshot(path=f"{out}/patterns-{w}-table.png")
        s = pg.query_selector("#patterns th details.qtip summary")
        if s:
            s.click(); pg.wait_for_timeout(400); pg.screenshot(path=f"{out}/patterns-{w}-tooltip.png")
        ctx.close()
    b.close()
