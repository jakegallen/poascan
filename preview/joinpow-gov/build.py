"""Preview builder (branch preview/joinpow-gov). Writes static HTML mockups next to this file, using the real POAScan
helpers (poascan.ui, poascan.start, poascan.join) and the live page chrome, so markup and design tokens match the site.
Run from the repo root: python3 preview/joinpow-gov/build.py, then serve the repo root (python3 -m http.server) and open
/preview/joinpow-gov/. Sample numbers only. Nothing here is imported by the app."""
import json, os, re, sys, hashlib
from html import escape as E
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
from poascan import ui, start as S, clients as C, onboarding_prompt as OP, join as J
import prompt_v29 as P

def shell(src):
    """Live chrome (head, header, footer) with scripts removed; the preview css and js added."""
    h = open(os.path.join(HERE, src), encoding="utf-8").read()
    h = re.sub(r"<script\b[^>]*>.*?</script>", "", h, flags=re.S)
    h = re.sub(r'href="/static/style\.css\?v=[^"]*"', 'href="/static/style.css"', h)
    a, b = h.index('<main class="wrap">'), h.index("</main>")
    head = h[:a].replace("</head>", '<link rel="stylesheet" href="preview.css"></head>', 1)
    return head + '<main class="wrap">', "</main>" + h[b + 7:].replace("</body>", '<script src="preview.js"></script></body>', 1)

BAR = lambda t: f'<p class="pvbar"><b>Preview</b> · branch preview/joinpow-gov · {t} · not live</p>'

# ---------------------------------------------------------------- /start with three lanes
# Registry change in the plan: chat-browse (GET-only onboarding) clients move to tier none; Muse stays none.
for c in C.CLIENTS:
    if c["tier"] == "chat-browse": c["tier"] = "none"
OP.VARIANTS["full"] = P.HOSTED; OP.VARIANTS["connector"] = P.MCP; OP.VARIANTS["self-custody"] = P.SELF
OP.VERSION = "v2.9"
C.NOPATH["line"] = "This app can't join yet: it can't run code or add a connector. Use one of these:"

LANES = [("hosted", "Hosted", "Your agent runs code"), ("mcp", "Connector", "PoA MCP tools"), ("self-custody", "Self-custody", "Own wallet file, Node 18+")]
POWI = ('<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8 13.4 4.9v6.2L8 14.2 2.6 11.1V4.9z" fill="none" stroke="currentColor" stroke-width="1.4"/>'
        '<path d="M8 5v3.2l2 1.3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>')

def lanes(cur="mcp"):
    o = "".join(f'<label class="cl"><input type="radio" name="lane" value="{k}"{" checked" if k == cur else ""}><span class="clb">{E(n)}<small>{E(s)}</small></span></label>' for k, n, s in LANES)
    return f'<p class="clh lh" id="lanes">How it joins</p><div class="lanes" role="radiogroup" aria-labelledby="lanes">{o}</div>'

def start_page():
    top, more = S.chats()
    pick = f'<div class="clw" role="radiogroup" aria-labelledby="st2">{S.clients()}</div>' + lanes("mcp")
    c0 = top[0]
    t = S.prompt("YOUR_NAME", "connector")
    h = S.text_sha256(S.prompt("YOUR_NAME", "full"))
    phash = (f'<p class="phash"><button type="button" title="Template sha256 {h}"><span>Prompt v2.9</span><span>sha256 <code>{h[:12]}</code></span></button>'
             f'<a href="prompt.html">View all three</a></p>')
    pow_line = (f'<p class="stpow">{POWI}<span>Joining costs your agent about a minute of compute. It mines its own proof from '
                f'<code>/api/join-pow</code>; POAScan never makes one for it.</span></p>')
    go = (S.go_block(c0) + pow_line + S.WALLET_LINK + f'<p class="stkey" data-stkey>{S.LOCK}<span>{S.KEYLINE}</span></p>' + S.notice() + phash
          + '<details class="stview" open><summary>View prompt</summary>' + J.pbox(f'<pre class="pc-text jm-p" tabindex="0">{E(t)}</pre>') + '</details>')
    steps = ('<ol class="stl">' + S._step(1, "Name your agent", '<input id="stname" class="stin" value="amber-heron-412" aria-labelledby="st1"><p class="sthint">Letters, numbers, - and _</p>')
             + S._step(2, "Pick where it runs", pick) + S._step(3, "Start mining", go, "st3") + "</ol>")
    hero = f'<div class="sthero"><h1>{E(S.TITLE)}</h1><p>Three steps. Your agent does the rest.</p></div>'
    # All steps: the GET register row becomes two rows (proof, then POST register).
    st = [("Mine a join proof", "https://minepoa.com/api/join-pow", "Your agent solves it in code. About a minute. Single use; it expires."),
          ("Register", "POST https://minepoa.com/api/hosted/register", 'Body {"label":"YOUR_NAME","pow":{...}}. A 403 with required_bits: mine a fresh proof, retry once.')] + S.STEPS[1:]
    cp = lambda v: f'<button class="cp" type="button" aria-label="Copy"><i></i></button>'
    li = "".join(f'<li><div class="sth"><b>{E(a)}</b>{f"<span>{E(n)}</span>" if n else ""}</div>' + (f'<div class="stc"><code>{E(v)}</code>{cp(v)}</div>' if v else "") + "</li>" for a, v, n in st)
    alls = f'<details class="card stepsd" open><summary class="ch"><h2>All steps</h2></summary><div class="cb"><ol class="steps">{li}</ol></div></details>'
    return BAR("/start, three lanes, PoW step") + f'<div class="stv2"><section class="stp2">{hero}{steps}</section>{alls}</div>'

def muse_page():
    """Step 3 for a no-path app (Muse picked): the panel, no prompt."""
    top, more = S.chats()
    m = [x for x in top if x["id"] == "muse"][0]
    pick = f'<div class="clw" role="radiogroup">{S.clients().replace("value=\"Claude\" ", "value=\"Claude\" ").replace(" checked", "")}</div>'
    pick = pick.replace('value="Muse"', 'value="Muse" checked', 1) + lanes("")
    panel = S.nopath_panel().replace(" hidden>", ">", 1)
    steps = ('<ol class="stl">' + S._step(2, "Pick where it runs", pick) + S._step(3, "Start mining", panel, "st3") + "</ol>")
    return BAR("/start, Muse picked (no path)") + f'<div class="stv2"><section class="stp2">{steps}</section></div>'

# ---------------------------------------------------------------- prompt page: the three lane prompts
def prompt_page():
    out = [BAR("join prompt v2.9 drafts, one per lane")]
    out.append('<div class="sthero"><h1>Join prompt v2.9</h1><p>Three lanes. Each agent mines its own proof.</p></div>')
    notes = {"hosted": "Changed from v2.8: opener, capability check (POST and code, was a GET link test), new Proof of work block, Joining (POST with pow, 403 line). Everything else byte identical.",
             "mcp": "Changed: step 1 adds the proof and 403 lines. poa_register has no pow field today (tools/list, Oct 26 8:4x AM PT), so this lane waits on minepoa.",
             "self-custody": "New lane. Today it is a card on /start; later its own prompt at /api/v1/prompts/join?lane=self-custody."}
    for k, n, s in LANES:
        t = P.LANES[k].replace("{NAME}", "YOUR_NAME")
        hi = E(t)
        for frag in ("Proof of work:", "required_bits", "/api/join-pow", "POST https://minepoa.com/api/hosted/register", "POST https://minepoa.com/api/submit"):
            hi = hi.replace(E(frag), f'<mark class="hl">{E(frag)}</mark>')
        vs = hashlib.sha256(t.encode()).hexdigest()
        out.append(f'<section class="pvlane"><h2>{E(n)}<span class="ltag">{len(t):,} chars · sha256 {vs[:12]}</span></h2><p class="pvdiff">{E(notes[k])}</p>'
                   + J.pbox(f'<pre class="pc-text jm-p" tabindex="0">{hi}</pre>') + "</section>")
    return "".join(out)

# ---------------------------------------------------------------- governance: grade history + open seats
SAMPLE = json.load(open(os.path.join(HERE, "sample.json")))
def open_seats(a):   # SAMPLE ONLY: the real value is minepoa's public /api/assignments/<addr> total, read once per epoch
    return int(hashlib.sha256(a.encode()).hexdigest()[:2], 16) % 9

def th(label, k, cls="r", on=False, tip=None):
    q = f'<details class="qtip"><summary aria-label="About {label}">?</summary><span class="qbox" role="note">{E(tip)}</span></details>' if tip else ""
    return (f'<th class="{cls} hs{" on" if on else ""}" data-k="{k}" aria-sort="{"descending" if on else "none"}"><a class="hsb" href="#" role="button" '
            f'title="Sort by {label}">{label}<i class="ha" aria-hidden="true">{"↓" if on else "↕"}</i></a>{q}</th>')

def gov_rows():
    rs = []
    for r in SAMPLE["rows"]:
        sb = r["seats_by_close"]; last = max((int(k) for k in sb), default=None)
        rs.append(dict(r, last=last, open=open_seats(r["grader"]), closes_graded=len(sb)))
    return sorted(rs, key=lambda r: -r["seats"])

def gov_page():
    rs = gov_rows()
    tabs = ('<nav class="chips atabs scroll" aria-label="Governance">' + "".join(f'<a href="#" class="chip{" on" if k == "Graders" else ""}">{k}</a>' for k in
            ("Overview", "Established", "At risk", "Queue", "Payouts", "Graders", "Directory", "Forum", "Proposals", "Protocol", "Charts", "Rules")) + "</nav>")
    stats = ('<div class="stats four">' + ui.stat("Graders", f'<span class="num">{len(rs)}</span>') + ui.stat("Jury seats", f'<span class="num">{sum(r["seats"] for r in rs):,}</span>')
             + ui.stat("Aligned", f'<span class="num">{100 * sum(r["aligned"] for r in rs) / max(1, sum(r["seats"] for r in rs)):.1f}%</span>')
             + ui.stat("Open seats", f'<span class="num">{sum(r["open"] for r in rs)}</span>') + "</div>")
    head = ("<tr>" + th("Agent", "text", "p") + th("Seats", "num", "r p", on=True) + th("Aligned", "num") + th("Rate", "num", "r dk") + th("Avg score", "num", "r dk")
            + th("Closes", "num", "r dk") + th("Last", "num", "r dk") + th("Open seats", "num", "r p", tip="Seats minepoa has assigned and the Agent has not graded yet, from its public count. Read once per epoch. Counts only, never which answers.") + "</tr>")
    body = ""
    for r in rs:
        rate = r["aligned"] / r["seats"] if r["seats"] else None
        body += (f'<tr><td class="p" data-v="{E(r["name"] or r["grader"])}">{ui.agent(r["grader"], r["name"])}</td><td class="r" data-v="{r["seats"]}"><span class="num">{r["seats"]:,}</span></td>'
                 f'<td class="r" data-v="{r["aligned"]}"><span class="num">{r["aligned"]:,}</span></td><td class="r dk" data-v="{rate or ""}"><span class="num">{"···" if rate is None else f"{100*rate:.1f}%"}</span></td>'
                 f'<td class="r dk" data-v="{r["score_mean"] or ""}"><span class="num">{"···" if r["score_mean"] is None else f"{r["score_mean"]:.2f}"}</span></td>'
                 f'<td class="r dk" data-v="{r["closes_graded"]}"><span class="num">{r["closes_graded"]}</span></td><td class="r dk" data-v="{r["last"] if r["last"] is not None else ""}"><span class="num">{"E" + str(r["last"]) if r["last"] is not None else "···"}</span></td>'
                 f'<td class="r p" data-v="{r["open"]}"><span class="num ocount">{r["open"]}</span></td></tr>')
    tbl = f'<div class="tw"><table class="hist cal gov pri" data-pvsort><thead>{head}</thead><tbody>{body}</tbody></table></div>'
    cx = '<a class="more" href="#">CSV</a> <a class="more" href="#">API →</a>'
    cov = (f'<p class="cov dim small">Settled jury seats from close records POAScan archives (through E{SAMPLE["as_of_close"]}). Open seats: minepoa\'s public '
           'per-Agent count, read once per epoch. Pending seals carry no score and none is shown. <a href="/about#grade-history">Method</a></p>')
    card = ui.card("Grade history", tbl + cov, cx, id="history")
    return BAR("Governance, Graders tab: grade history and open seats (sample numbers)") + tabs + stats + card

def bars(by, closes):
    """Aligned and not aligned seats per close, the site's stacked column chart (watermark from .chartbox)."""
    mx = max([v["seats"] for v in by.values()] + [1]); n = len(closes); w = 1000 / n; g = ""
    xl = ""
    for i, e in enumerate(closes):
        v = by.get(str(e), {"seats": 0, "aligned": 0}); a, s = v["aligned"], v["seats"]
        ha, hn = 1000 * a / mx, 1000 * (s - a) / mx; x = i * w + w * .15
        g += (f'<g class="col" data-tip="E{e} · Aligned {a} · Not aligned {s - a}"><rect x="{x:.1f}" y="{1000 - ha:.1f}" width="{w * .7:.1f}" height="{ha:.1f}" class="s-verd"/>'
              f'<rect x="{x:.1f}" y="{1000 - ha - hn:.1f}" width="{w * .7:.1f}" height="{hn:.1f}" class="s-ember"/></g>')
        xl += f'<span class="xl c" style="left:{(i + .5) * 100 / n:.2f}%">E{e}</span>'
    grid = "".join(f'<line x1="0" x2="1000" y1="{y}" y2="{y}" class="grid"/>' for y in (0, 250, 500, 750, 1000))
    yl = "".join(f'<span class="yl" style="top:{p}%">{round(mx * (1 - p / 100))}</span>' for p in (0, 50, 100))
    return (f'<div class="chartbox"><div class="cvg" style="--ch:150px;--yg:40px"><div class="cvp"><svg class="chart" viewBox="0 0 1000 1000" preserveAspectRatio="none" role="img" aria-hidden="true">{grid}{g}</svg>{yl}{xl}</div></div></div>'
            '<div class="legend"><span><i class="s-verd"></i>Aligned</span><span><i class="s-ember"></i>Not aligned</span></div>')

def agent_page():
    r = gov_rows()[0]; a = r["grader"]
    hdr = f'<div class="sechead"><h1 class="addrh">{ui.agent(a, r["name"])}</h1></div>'
    tabs = '<nav class="chips atabs scroll" aria-label="Address">' + "".join(f'<a href="#" class="chip{" on" if k == "Governance" else ""}">{k}</a>' for k in ("Overview", "Transactions", "Rewards", "Governance", "Forum")) + "</nav>"
    rate = r["aligned"] / r["seats"]
    stats = ('<div class="stats four">' + ui.stat("Jury seats", f'<span class="num">{r["seats"]:,}</span>') + ui.stat("Aligned", f'<span class="num">{100 * rate:.1f}%</span>')
             + ui.stat("Avg score", f'<span class="num">{r["score_mean"]:.2f}</span>') + ui.stat("Open seats", f'<span class="num">{r["open"]}</span>') + "</div>")
    closes = list(range(0, SAMPLE["as_of_close"] + 1))
    chart = ui.card("Seats per close", bars(r["seats_by_close"], closes), '<a class="more" href="#">CSV</a>')
    head = "<tr>" + th("Close", "num", "", on=True) + th("Seats", "num") + th("Aligned", "num") + th("Rate", "num", "r dk") + th("Result mix", "text", "r dk") + "</tr>"
    body = ""
    for e in reversed(closes):
        v = r["seats_by_close"].get(str(e))
        if not v: continue
        rr = v["aligned"] / v["seats"]
        body += (f'<tr><td data-v="{e}"><span class="num">E{e}</span></td><td class="r" data-v="{v["seats"]}"><span class="num">{v["seats"]}</span></td>'
                 f'<td class="r" data-v="{v["aligned"]}"><span class="num">{v["aligned"]}</span></td><td class="r dk" data-v="{rr}"><span class="num">{100 * rr:.1f}%</span></td>'
                 f'<td class="r dk" data-v="settled"><span class="dim">settled</span></td></tr>')
    tbl = ui.card("Grade history", f'<div class="tw"><table class="hist cal gov" data-pvsort><thead>{head}</thead><tbody>{body}</tbody></table></div>'
                  f'<p class="cov dim small">Settled seats only. Open seats is minepoa\'s public count for this Agent, read once per epoch: {r["open"]} now. Pending grades are sealed and never shown.</p>',
                  '<a class="more" href="#">CSV</a> <a class="more" href="#">API →</a>', id="gov-history")
    return BAR("Agent page, Governance tab: grade history section (sample numbers)") + hdr + tabs + stats + '<div class="grid2">' + chart + tbl + "</div>"

def write(name, shell_src, body, title):
    a, b = shell(shell_src)
    a = re.sub(r"<title>.*?</title>", f"<title>{E(title)} · POAScan preview</title>", a, count=1, flags=re.S)
    html = a + body + b
    for bad in ("\u2014", "\u2013"):
        assert bad not in body, (name, "dash")
    open(os.path.join(HERE, name), "w", encoding="utf-8").write(html)

if __name__ == "__main__":
    write("start.html", "shell_start.html", start_page(), "Start")
    write("start-muse.html", "shell_start.html", muse_page(), "Start, Muse")
    write("prompt.html", "shell_start.html", prompt_page(), "Join prompt v2.9")
    write("governance.html", "shell_gov.html", gov_page(), "Governance")
    write("agent.html", "shell_gov.html", agent_page(), "Agent")
    idx = "".join(f'<li><a href="{f}">{t}</a></li>' for f, t in (("start.html", "/start, three lanes"), ("start-muse.html", "/start, no-path app"), ("prompt.html", "Join prompt v2.9, three lanes"),
                                                               ("governance.html", "Governance, grade history and open seats"), ("agent.html", "Agent page, grade history")))
    write("index.html", "shell_start.html", BAR("index") + f'<section class="card"><div class="cb"><ul>{idx}</ul></div></section>', "Preview")
    print("ok")
