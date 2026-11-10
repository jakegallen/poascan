"""1.26.311 (Jake t532u): /start is one centred card. The folds below (What this prompt does, All steps, Prompt history)
stay in the page and keep their bytes, but are hidden; the chips show once an app is chosen; Check my Agent is a quiet link."""
import os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_DB", os.path.join(tempfile.mkdtemp(), "t.db")); os.environ["POASCAN_INDEXER"] = "0"
from poascan import startv2 as SV, start as S
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)
b = SV.body()
i = b.find('<div class="sv-below" data-sv-below hidden>')
check("folds are in the page, inside one hidden wrapper", i > 0 and all(x in b[i:] for x in ("What this prompt does", "All steps", "Prompt history", 'id="prompt-history"')))
check("the folds keep their markup byte for byte", S.below() in b)
check("starts on the name step (chips hidden until an app is chosen)", 'data-st="name"' in b)
check("Check my Agent is a quiet link (details) that opens the field", '<details class="sv-vf-chk"><summary>Check my Agent</summary>' in b and "data-sv-vf-addr" in b)
check("payment rule shows with the wallet link", S.PAY in b[:i])
check("no key, no referral, no dash", not re.search("[\u2013\u2014]", b) and not re.search(r"[?&](ref|invite|code|referral)=", b, re.I) and "sk_" not in b)
css = open(os.path.join(ROOT, "static", "startv2.css"), encoding="utf-8").read()
js = open(os.path.join(ROOT, "static", "startv2.js"), encoding="utf-8").read()
check("card centred on the page", ".s2v{min-height:calc(100dvh - 190px);display:flex;flex-direction:column;justify-content:center" in css)
check("chips hidden on the name and app steps", '.s2v[data-st="name"] .sv-vf,.s2v[data-st="apps"] .sv-vf{display:none}' in css)
check("step state follows render, anchors open the folds", 'rt.dataset.st=a?"app":st' in js and "[data-sv-below]" in js)
check("phones: own padding", "@media (max-width:640px){\n .s2v{min-height:calc(100dvh - 230px)" in css)
print("\nall passed" if not fails else f"\n{len(fails)} failed"); sys.exit(1 if fails else 0)
