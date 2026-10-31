"""Join popup PROTOTYPE (branch popup-join-proto, flag POASCAN_JOINPOPUP=1, not shipped). Proves there is no key data path:
minepoa.com's signup opens with noopener,noreferrer (no handle, no opener), nothing listens for or sends postMessage, nothing
reads the other window, and the only value that leaves /start is a poa1 address sent to POAScan's own /api/v1/agents/joined.
Key-shaped input is cleared and never sent; the server refuses it without echoing it. Flag off: nothing changes. No request ever
reaches minepoa.com (blocked in the browser). Joins are paused upstream, so the new Agent is a seeded join row.
Usage: python3 tools/popup_join_test.py  (POPUP_SHOTS=<dir> also writes screenshots at 390 and 1280)"""
import os, re, sys, json, tempfile, time, socket, subprocess, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "p.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, ROOT)
from poascan import db, start as S, names as NM, maint as M
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init(); M.join_halt = lambda: None
NEW = "poa1" + "PopupJoinDemo" + "2" * 31   # seeded: the Agent that "appeared"
OTHER = "poa1" + "NotJoinedYet" + "3" * 32
FAKE_KEY = "pk_live_" + "a1b2c3d4" * 4
GUID = "-".join(("3f2b8c1e", "4d5a", "4b6c", "9e7f", "0a1b2c3d4e5f"))   # a fake GUID-shaped key, built at run time
now = int(time.time())
db.write("INSERT INTO txs(id,type,from_addr,memo,ts,first_seen,last_seen,source) VALUES(?,?,?,?,?,?,?,?)", ("f" * 64, "join", NEW, "hosted join: web", now - 30, now, now, "test"))

# server side
top, rest = S.chats(); claude = top[0]
os.environ.pop("POASCAN_JOINPOPUP", None)
check("flag off: /start renders no popup button, no panel", "data-popjoin" not in S.go_block(claude) and "data-pop" not in S.go_block(claude))
os.environ["POASCAN_JOINPOPUP"] = "1"
g = S.go_block(claude)
check("flag on: hosted apps get the popup button and panel; code apps do not", "data-popjoin" in g and "data-pop " in g and "data-popjoin" not in S.go_block(next(c for c in top + rest if c["id"] == "cursor")))
check("panel: no key field, never asks for a key; one optional poa1 address field", g.count("<input") == 2 and 'placeholder="poa1..."' in g and not re.search(r"(api.?key|pk_|paste (your|the) key|enter (your|the) key)", g, re.I) and "Never share it" in g)
check("copy: no em or en dash", not re.search("[\u2013\u2014]", g))
c1, d1 = NM.joined(FAKE_KEY); c2, d2 = NM.joined(GUID); c3, d3 = NM.joined("https://minepoa.com/api/hosted/me?key=" + FAKE_KEY)
check("joined(): key-shaped input refused (400), never echoed", (c1, c2, c3) == (400, 400, 400) and not any(FAKE_KEY in json.dumps(d) or GUID in json.dumps(d) for d in (d1, d2, d3)))
c4, d4 = NM.joined(NEW); c5, d5 = NM.joined(OTHER)
check("joined(): POAScan's index only: the seeded Agent found, another not", c4 == 200 and d4["found"] is True and c5 == 200 and d5["found"] is False)
src = open(os.path.join(ROOT, "poascan", "names.py"), encoding="utf-8").read()
check("joined(): no upstream read", "fetch(" not in src[src.index("def joined"):] and "minepoa.com/api" not in src[src.index("def joined"):])

# client code: the prototype block, comments stripped
js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
blk = js[js.index("/* Join popup PROTOTYPE"):]; code = re.sub(r"/\*.*?\*/", "", blk, flags=re.S)
jsc = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
check("app.js: no postMessage call and no window message listener anywhere (ws.onmessage is the live feed socket)", "postMessage" not in jsc
      and not re.search(r"""addEventListener\(\s*["']message""", jsc) and re.findall(r"[\w.]*onmessage", jsc) == ["ws.onmessage"])
check("prototype: no opener, no handle kept (window.open result never used), noopener,noreferrer", "opener" not in code.replace("noopener", "")
      and re.search(r"window\.open\([^;]*noopener,noreferrer\"\)", code) and not re.search(r"[=(,]\s*window\.open|window\.open\([^)]*\)\s*\.", code))
check("prototype: one fetch, POAScan's own /api/v1/agents/joined, no credentials, no referrer, gated by the poa1 pattern",
      code.count("fetch(") == 1 and 'fetch("/api/v1/agents/joined?address="' in code and 'credentials:"omit"' in code and "no-referrer" in code
      and code.index("if(!ADDR.test(a))") < code.index("fetch(") and code.index("if(KEYISH.test(a))") < code.index("fetch("))
check("prototype: no minepoa.com read, no iframe, no storage, no clipboard", not any(x in code for x in ("minepoa.com", "iframe", "localStorage", "sessionStorage", "clipboard", "document.cookie")))

# browser: Chromium at 1280 and 390; minepoa.com is blocked so the test never loads it
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None; check("playwright installed", os.environ.get("CI") != "true")
if sync_playwright:
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close(); base = f"http://127.0.0.1:{port}"
    srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=dict(os.environ, PORT=str(port), HOST="127.0.0.1"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shots = os.environ.get("POPUP_SHOTS")
    try:
        for _ in range(150):
            try: urllib.request.urlopen(base + "/healthz", timeout=2); break
            except Exception: time.sleep(0.2)
        code0 = urllib.request.urlopen(base + "/api/v1/agents/joined?address=" + NEW).status
        try: urllib.request.urlopen(base + "/api/v1/agents/joined?address=" + FAKE_KEY); kc = 200
        except urllib.error.HTTPError as e: kc = e.code; kb = e.read().decode()
        check("endpoint: the seeded address 200, a key 400 without echo", code0 == 200 and kc == 400 and FAKE_KEY not in kb)
        with sync_playwright() as p:
            b = p.chromium.launch()
            for w in (1280, 390):
                ctx = b.new_context(viewport={"width": w, "height": 900 if w > 400 else 844}, has_touch=w < 400, is_mobile=w < 400)
                sent = []; mp = []
                ctx.route("https://minepoa.com/**", lambda r: (mp.append(r.request.url), r.abort()))
                ctx.on("request", lambda r: sent.append(r.url + " " + (r.post_data or "")))
                pg = ctx.new_page()
                pg.add_init_script("window.__wo=[];var _o=window.open;window.open=function(u,n,f){window.__wo.push([u,n,f]);return null};")
                pg.goto(base + "/start", wait_until="networkidle")
                pg.locator("[data-popjoin]").scroll_into_view_if_needed()
                pg.locator("[data-popjoin]").click()
                wo = pg.evaluate("window.__wo")
                vis = pg.locator("[data-pop]").is_visible()
                if w > 400:
                    check(f"{w}px: one popup, name poajoin, 480 wide, noopener,noreferrer; the panel shows {wo}", vis and len(wo) == 1 and wo[0][0] == "https://minepoa.com/" and wo[0][1] == "poajoin"
                          and "width=480" in wo[0][2] and wo[0][2].endswith("noopener,noreferrer"))
                else:
                    check(f"{w}px: no popup on a phone, the link's own new tab (blocked here); the panel shows", vis and wo == [] and len(ctx.pages) >= 1)
                if shots: os.makedirs(shots, exist_ok=True)
                if shots: pg.evaluate("[...document.querySelectorAll('body *')].forEach(e=>{const p=getComputedStyle(e).position;if((p=='fixed'||p=='sticky')&&!e.closest('li.st3'))e.style.visibility='hidden'})"); pg.locator("li.st3").screenshot(path=os.path.join(shots, f"popup-open-{w}.png"))
                pg.fill("[data-popaddr]", FAKE_KEY); v1 = pg.evaluate("document.querySelector('[data-popaddr]').value"); pg.click("[data-popfind]")
                pg.fill("[data-popaddr]", GUID); pg.click("[data-popfind]"); pg.wait_for_timeout(300)
                st = pg.evaluate("({v:document.querySelector('[data-popaddr]').value,s:document.querySelector('[data-popst]').textContent})")
                check(f"{w}px: a pk_ key is cleared as typed (the sitewide key guard), a GUID key on Find; neither is sent {st}", v1 == "" and st["v"] == "" and st["s"] == S.POP_KEY)
                pg.fill("[data-popaddr]", NEW); pg.click("[data-popfind]"); pg.wait_for_timeout(1200)
                st = pg.evaluate("({s:document.querySelector('[data-popst]').textContent,go:document.querySelector('[data-cfirst]').classList.contains('jwgo'),nx:document.querySelector('[data-popnext]').disabled})")
                check(f"{w}px: the new Agent appears on POAScan: found, moved on to step 2 {st}", st["s"] == S.POP_FOUND and st["go"] and not st["nx"])
                if shots: pg.evaluate("[...document.querySelectorAll('body *')].forEach(e=>{const p=getComputedStyle(e).position;if((p=='fixed'||p=='sticky')&&!e.closest('li.st3'))e.style.visibility='hidden'})"); pg.locator("li.st3").screenshot(path=os.path.join(shots, f"popup-found-{w}.png"))
                leak = [x for x in sent if FAKE_KEY in x or GUID in x]
                ext = [x for x in sent if not x.startswith(base) and "minepoa.com" not in x]
                check(f"{w}px: no request carries the key; only POAScan requests (minepoa only via the link's own tab) {leak} {ext[:3]}", not leak and not ext
                      and all(u.split("?")[0].rstrip("/") in ("https://minepoa.com",) for u in mp))
                ctx.close()
            b.close()
    finally:
        srv.terminate(); srv.wait(10)
print(f"\n{len(fails)} FAILED" if fails else "\nall ok"); sys.exit(1 if fails else 0)
