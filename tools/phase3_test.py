"""Phase 3 (signature moments). Maker's marks and hallmarks (marks.py): deterministic rosettes from an address or a close's record,
served as immutable SVG at /mark/{address}.svg and /hallmark/{epoch}-{paid}-{minted}.svg, strict inputs, no database read. They sit in
Home Closes, the Chain table, the epoch header and the Agent header. The Pour: /fragment/pour and the close sequence hooks.
Temp database and a local server, no network. Usage: python3 tools/phase3_test.py"""
import os, re, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "f.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
import fixture
fixture.seed()
from poascan import marks as MK, views as V, analytics as A
A1 = "poa1DH98ZZ3RA5TuRxicRj9ygTJs9esWEX16emciYp3LrdkS"
s1 = MK.agent_svg(A1); MK.rosette.cache_clear(); s2 = MK.agent_svg(A1)
check("maker's mark: deterministic SVG, gold, hairlines that do not scale, 4 layers", s1 == s2 and s1.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"')
      and 'stroke="#FFB000"' in s1 and s1.count("<path") == 6 and "non-scaling-stroke" in s1 and len(s1) < 20000)
check("different addresses, different marks", MK.agent_svg(A1[:-1] + "T") != s1)
check("not a poa1 address: no mark", MK.agent_svg("poa1<script>") is None and MK.agent_svg("0xabc") is None and MK.agent_svg("") is None)
h = MK.hall_svg("1-116-82830000")
check("hallmark: seeded by the close record, gold when it paid Agents, bone when it paid none, 3 layers", h == MK.hall_svg("1-116-82830000") and 'stroke="#FFB000"' in h
      and 'stroke="#8C836F"' in MK.hall_svg("2-0-0") and h.count("<path") == 5 and h != MK.hall_svg("1-116-82830001"))
check("hallmark keys are strict", all(MK.hall_svg(k) is None for k in ("1-2", "a-1-1", "1-1-1-1", "9999999-1-1", "1-1-1.5", "../x")))
r = dict(epoch=3, paid=116, minted=82830000.4)
check("img tags: decorative, sized, lazy, URL carries the seed", MK.hall_img(r, 28) == '<img class="hmark" src="/hallmark/3-116-82830000.svg" width="28" height="28" alt="" aria-hidden="true" loading="lazy" decoding="async">'
      and MK.mark_img(A1, 56).startswith(f'<img class="mmark" src="/mark/{A1}.svg" width="56"') and MK.mark_img("bad") == "")
hm = V.home(); ch = V.epochs_table(A.epoch_rows()[-3:])
check("hallmarks in Home Closes and the Chain table", hm.count('class="hmark"') >= 1 and 'src="/hallmark/' in hm and ch.count('class="hmark"') == 3)
ep = A.epoch_rows()[-1]["epoch"]; eh = V.epoch(ep); eh = eh[1] if isinstance(eh, tuple) else eh
check("epoch header carries its hallmark at 56 px", 'class="hmark big"' in eh and 'width="56"' in eh)
check("no em or en dashes in marks.py", "\u2014" not in open(os.path.join(ROOT, "poascan/marks.py")).read() and "\u2013" not in open(os.path.join(ROOT, "poascan/marks.py")).read())
js = open(os.path.join(ROOT, "static/app.js")).read(); css = open(os.path.join(ROOT, "static/style.css")).read()
check("the Pour: a new close refetches the card, the bar splits, the new hallmark draws in; reduced motion skips it",
      "function pourLive(s)" in js and "/fragment/pour" in js and "pourLive(s)}" in js and "tr.in .hmark{animation:hallin 1.2s" in css and "@media (prefers-reduced-motion:reduce){tr.in .hmark{animation:none}}" in css)

from poascan import profile as PF
FA = fixture.A1; ah = V.address(FA); ah = ah[1] if isinstance(ah, tuple) else ah
check("Agent page: a profile header led by the maker's mark at 104 px, then the address with copy and its tags",
      '<section class="card prof addrhead">' in ah and f'src="/mark/{FA}.svg" width="104"' in ah and 'class="amono"' in ah and 'class="ptags"' in ah)
check("Agent page: the Score as a dial with its four parts and six facts, then Rewards and Activity",
      'class="dial"' in ah and ah.count('class="ppart"') == 4 and ah.count('class="pf"') == 6 and 'class="pheat"' in ah and ah.count('class="phr"') == 7 and "Txs by hour" in ah)
check("Agent page: tabs, the stats and the Profile card stay", 'class="stats eight"' in ah and ">Overview<" in ah and "Profile" in ah)
d = PF.dial(72)
check("dial: the arc is the Score out of 100", '72 100' in d and '>72<' in d and 'pathLength="100"' in d)
check("no Score yet: an honest empty state", "No Score in this segment yet" in PF.score_card(None, ""))
check("no em or en dashes in profile.py", not any(ch in open(os.path.join(ROOT, "poascan/profile.py")).read() for ch in "\u2014\u2013"))

from poascan import og as OG
if OG.available():
    t0 = time.perf_counter(); png, age = OG.render(f"/og/address/{FA}.png"); dt = time.perf_counter() - t0
    check(f"OG: an Agent's preview is a 1200x630 PNG under 90 KB with its maker's mark, rendered quickly ({len(png) // 1024} KB, {dt * 1000:.0f} ms)",
          png[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(png[16:20], "big") == 1200 and int.from_bytes(png[20:24], "big") == 630 and len(png) < 90000 and dt < 1.5)
    check("OG: set in the site's own type (Newsreader, Instrument Sans, IBM Plex Mono from static/fonts)",
          all(os.path.exists(os.path.join(OG.FONTS, OG._FILES[k][0])) for k in ("fig", "ui", "mono")) and "newsreader" in OG._font("fig", 40).path)
    ep_spec = OG._epoch(A.epoch_rows()[-1]["epoch"])[0]
    check("OG: an epoch's preview carries its hallmark, the same seed as /hallmark", ep_spec[4][0] == MK.hall_key_seed(MK.hall_seed(**{k: A.epoch_rows()[-1][k] for k in ("epoch", "paid", "minted")}))[0])
    OG._BUCKET[:] = [0.0, time.monotonic()]
    hit = OG.render(f"/og/address/{FA}.png"); miss = OG.render(f"/og/address/{fixture.A2}.png")
    check("OG: over the render budget a cached preview still serves, a new one gets the generic card for 5 minutes, uncached",
          hit == (png, age) and miss == (OG._fallback(), OG.FALLBACK_AGE) and f"/og/address/{fixture.A2}.png" not in OG._CACHE)
    OG._BUCKET[:] = [float(OG.BURST), time.monotonic()]

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(u):
    try:
        with op.open(base + u, timeout=30) as f: return f.status, {k.lower(): v for k, v in f.headers.items()}, f.read()
    except urllib.error.HTTPError as e: return e.code, {}, e.read()
port = free_port(); base = f"http://127.0.0.1:{port}"
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_MAINTENANCE="0")
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(150):
        try: get("/healthz"); break
        except Exception: time.sleep(0.2)
    c, hd, b = get(f"/mark/{A1}.svg")
    check(f"/mark: 200, image/svg+xml, immutable for a year ({c})", c == 200 and hd.get("content-type", "").startswith("image/svg+xml") and hd.get("cache-control") == MK.CACHE and b.decode() == s1)
    c2, hd2, b2 = get("/hallmark/1-116-82830000.svg")
    check(f"/hallmark: 200, immutable ({c2})", c2 == 200 and hd2.get("cache-control") == MK.CACHE and b2.decode() == h)
    check("bad mark URLs: 404", all(get(u)[0] == 404 for u in ("/mark/nope.svg", f"/mark/{A1}", "/hallmark/1-2.svg", "/hallmark/x.svg", "/mark/", "/hallmark/")))
    c3, _, b3 = get("/fragment/pour")
    check(f"/fragment/pour: the latest close's split ({c3})", c3 == 200 and b'id="pour" data-ep="' in b3 and b"Minted" in b3)
finally:
    srv.terminate(); srv.wait(10)
if fails: print(f"FAIL: {len(fails)}: {fails}"); sys.exit(1)
print("all passed")
