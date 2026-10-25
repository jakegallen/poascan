"""Design tokens lint (1.26.118). Every color, radius and font in static/style.css comes from the one :root token block;
rules use var() only. Python views and static/app.js may only use hex values that are token values (or the shrinking
LEGACY list, emptied as the chart and cleanup releases land). No em or en dashes in any tracked text file.
No network, no database. Usage: python3 tools/design_tokens_test.py"""
import os, re, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
HEX = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![0-9A-Za-z_-])")
css = open(os.path.join(ROOT, "static/style.css"), encoding="utf-8").read()
nocom = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
roots = [m.start() for m in re.finditer(r"(?m)^:root\{", nocom)]
check("style.css has exactly one :root token block", len(roots) == 1)
r0 = roots[0] if roots else 0; r1 = nocom.index("}", r0) + 1 if roots else 0
block, rest = nocom[r0:r1], nocom[:r0] + nocom[r1:]
TOKENS = {h.upper() for h in HEX.findall(block)}
TOKENS |= {"#" + "".join(c * 2 for c in h[1:]) for h in TOKENS if len(h) == 4}
check("token block defines the palette", len(TOKENS) >= 20 and "#FFB000" in TOKENS)
stray = sorted(set(HEX.findall(rest)))
check(f"no hard-coded hex color in style.css outside :root {stray[:8]}", not stray)
rg = sorted(set(re.findall(r"rgba?\([^)]*\d[^)]*\)|hsla?\([^)]*\)", rest)))
check(f"no rgb()/hsl() literal in style.css outside :root {rg[:4]}", not rg)
rad = sorted(set(m for m in re.findall(r"border(?:-[a-z]+)*-radius:([^;}]+)", rest) if re.search(r"\d+px", m)))
check(f"radii come from tokens (--r-sm/md/lg/pill) {rad[:6]}", not rad)
fam = re.findall(r"font-family:\s*['\"]?([A-Za-z][^;}]*)", nocom[r1:])
fam = [f for f in fam if not f.strip().startswith(("var(", "inherit"))]
check(f"font families come from --ui, --mono, --fig {fam[:4]}", not fam)
ff = re.findall(r"font-family:'([^']+)'", nocom[:r0])
check("faces: Instrument Sans, Newsreader, IBM Plex Mono only, all font-display swap",
      set(ff) == {"Instrument Sans", "Newsreader", "IBM Plex Mono"} and nocom[:r0].count("font-display:swap") == nocom[:r0].count("@font-face"))
for f in set(re.findall(r"/static/fonts/([\w.-]+\.woff2)", css)):
    check(f"font file present: {f}", os.path.exists(os.path.join(ROOT, "static/fonts", f)))
undef = sorted({v for v in re.findall(r"var\((--[\w-]+)\)", nocom)} - set(re.findall(r"(--[\w-]+)\s*:", nocom)))
check(f"every var() used in style.css is defined {undef[:6]}", not undef)
check("no faked weights: font-synthesis none, nothing above 600",
      "font-synthesis:none" in rest and not re.search(r"font-weight:\s*(?:700|800|900|bold)|font:\s*(?:700|800|900)\s", rest))
# Python views and app.js: hex only from the token palette (og.py draws images with its own fonts; swap/ has its own sheet)
LEGACY = {"#E3A33A", "#3DDC97", "#FF5A4E", "#0E0D0B", "#FFF", "#FFF4D6", "#F3EDE0", "#2B261C"}
srcs = subprocess.run(["git", "ls-files", "poascan/*.py", "static/app.js"], cwd=ROOT, capture_output=True, text=True).stdout.split()
bad = {}
for p in srcs:
    if p.startswith("poascan/swap/") or p == "poascan/og.py": continue
    s = open(os.path.join(ROOT, p), encoding="utf-8").read()
    for h in HEX.findall(s):
        if h.upper() not in TOKENS and h.upper() not in LEGACY: bad.setdefault(p, set()).add(h)
check(f"python views and app.js use token hex values only {dict((k, sorted(v)[:4]) for k, v in bad.items())}", not bad)
# no em or en dashes anywhere
files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
dash = []
for p in files:
    if re.search(r"\.(?:woff2?|ttf|png|jpe?g|gif|webp|ico|db|sqlite|bundle)$", p): continue
    try: s = open(os.path.join(ROOT, p), encoding="utf-8").read()
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError): continue
    if "\u2013" in s or "\u2014" in s: dash.append(p)
check(f"no em or en dash in tracked files {dash[:6]}", not dash)
print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
