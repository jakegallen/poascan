"""/start v2 preview (POASCAN_STARTV2=1): off by default; on, it renders the picker, the templates and the data, with no key,
token or referral in any link, no em or en dash, and the key warning for chat apps."""
import os, sys, re, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_DB", "/tmp/startv2_test.db")
from poascan import startv2 as SV, start as S
bad = 0
def check(n, ok):
    global bad; print(("ok   " if ok else "FAIL ") + n); bad += not ok
os.environ.pop(SV.FLAG, None)
check("off by default", not SV.on())
os.environ[SV.FLAG] = "1"
h = SV.body()
d = json.loads(re.search(r'<script type="application/json" data-sv-json>(.*?)</script>', h, re.S).group(1))
check("on: picker with every supported app as a tile, not supported behind Something else", SV.on() and h.count('class="sv-t ') == sum(a["tier"] != "none" for a in d["apps"])
      and h.count('class="sv-o"') == sum(a["tier"] == "none" for a in d["apps"]) and "Something else" in h)
check("code tiles first, then chat", [a["tier"] for a in d["apps"] if a["tier"] != "none"] == sorted([a["tier"] for a in d["apps"] if a["tier"] != "none"], key=lambda t: t != "full"))
check("data: the key warning, minepoa's connector URL, Claude's prefill (no key, no referral)", d["warn"] == S.KEY_WARN and d["mcp"] == "https://minepoa.com/mcp"
      and any(a["id"] == "claude" and "connectorName=Proof%20of%20Agent" in a["cset"] for a in d["apps"]))
links = re.findall(r'https?://[^\s"<>]+', h + json.dumps(d))
check("no key, token, guid or referral in any link", not any(re.search(r"[?&](key|api_key|token|guid|ref|invited_by)=", u, re.I) for u in links))
src = h + open(os.path.join(ROOT, "static", "startv2.js")).read() + open(os.path.join(ROOT, "static", "startv2.css")).read()
check("no em or en dash", "\u2014" not in src and "\u2013" not in src)
check("JS reads only POAScan's own API", not re.search(r'fetch\("https?://', src) and "/api/v1/agents/name-available" in src)
print("all ok" if not bad else f"{bad} FAILED"); sys.exit(1 if bad else 0)
