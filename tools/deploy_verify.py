"""Post-deploy check (1.26.286), run by the deploy job after liveness. Proves the build that just deployed is the one
serving, and that the served prompts are byte identical to the repo:
- /api/health commit equals GITHUB_SHA (polled while the single machine swaps over) and X-API-Commit matches it;
- sha256 of the served /api/v1/prompts/combined .text equals the repo slot (poascan/combined_prompt.txt) and its pin;
- /api/v1/prompts/join template_sha256 equals the repo template.
A served em or en dash, or a key or token in a URL, on /, /start or /help is reported as a warning (page data can carry
upstream text, so it does not fail the deploy). Light: a handful of GETs. Never prints a secret.
Usage: GITHUB_SHA=<sha> python3 tools/deploy_verify.py [base]"""
import hashlib, json, os, re, sys, time, urllib.error, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://poascan.io").rstrip("/")
SHA = os.environ.get("GITHUB_SHA", "")
UA = {"User-Agent": "poascan-deploy-verify/1"}

def get(path, timeout=25):
    req = urllib.request.Request(BASE + path, headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=timeout); return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read()

fails, warns = [], []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

# 1) the deployed commit is the one serving
seen, hhd = None, {}
for i in range(24):
    try:
        st, hhd, b = get("/api/health")   # no-store at the edge, so never an old build's cached copy
        seen = (json.loads(b) or {}).get("commit")
        if seen == SHA: break
    except Exception as e:
        seen = f"error {type(e).__name__}"
    time.sleep(10)
check(f"/api/health commit is this build ({SHA[:12]}), saw {str(seen)[:12]}", bool(SHA) and seen == SHA)
check("X-API-Commit header on /api/health is this build", {k.lower(): v for k, v in hhd.items()}.get("x-api-commit") == SHA)

def get_json(path, tries=12):
    """A JSON body from path, retried while the single machine is still cold after the deploy (a 503 "server busy" text,
    an edge error page or a timeout), up to about 2 minutes. Returns (status, body or None)."""
    st = None
    for i in range(tries):
        try:
            st, hd, b = get(path)
            if st == 200: return st, json.loads(b)
        except Exception as e: st = type(e).__name__
        time.sleep(10)
    return st, None

# 2) served prompt bytes equal the repo
from poascan import combined as CB, start as S
st, d = get_json("/api/v1/prompts/combined")
if d is None: check(f"combined prompt readable (last answer {st})", False)
else:
    t = d.get("text") or ""; srv = hashlib.sha256(t.encode()).hexdigest()
    check(f"served combined .text sha256 {srv[:8]} equals the repo slot {str(CB.SHA256)[:8]} and the advertised combined_sha256",
          CB.SHA256 is not None and srv == CB.SHA256 == d.get("combined_sha256") and t == CB.TEXT)
st, d = get_json("/api/v1/prompts/join")
if d is None: check(f"join prompt readable (last answer {st})", False)
else: check(f"served join template_sha256 equals the repo template {S.template_sha256()[:8]}", d.get("template_sha256") == S.template_sha256())

# 3) served copy scan, warnings only
KEYURL = re.compile(r"[?&](?:key|api_key|token|guid)=(?!YOUR_|KEY\b|\{)[A-Za-z0-9_\-]{8,}")
for path in ("/", "/start", "/help"):
    try:
        st, hd, b = get(path); s = b.decode("utf-8", "replace")
        if "\u2014" in s or "\u2013" in s: warns.append(f"{path}: em or en dash served")
        if KEYURL.search(s): warns.append(f"{path}: key-like value in a URL")
    except Exception as e: warns.append(f"{path}: not read ({type(e).__name__})")
for w in warns: print(f"::warning::{w}")
print(f"deploy verify: {len(fails)} failure(s), {len(warns)} warning(s)")
sys.exit(1 if fails else 0)
