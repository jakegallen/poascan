"""Set the release times to now (UTC) right before shipping: agentapi.RELEASED_TS and onboarding_prompt.UPDATED_TS.
/upgrade Details shows both in the reader's time plus UTC (PT for Jake), so they must be the real ship time, not the build time.
Usage: python3 tools/stamp_release.py [--prompt-only | --release-only] [YYYY-MM-DDTHH:MM:00Z]"""
import os, re, sys, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
ts = args[0] if args else time.strftime("%Y-%m-%dT%H:%M:00Z", time.gmtime())
if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", ts): sys.exit("time: YYYY-MM-DDTHH:MM:SSZ (UTC)")
todo = [("poascan/agentapi.py", "RELEASED_TS"), ("poascan/onboarding_prompt.py", "UPDATED_TS")]
if "--prompt-only" in sys.argv: todo = todo[1:]
if "--release-only" in sys.argv: todo = todo[:1]
for f, var in todo:
    p = os.path.join(ROOT, f); s = open(p, encoding="utf-8").read()
    s2, n = re.subn(r'^(' + var + r' = ")[^"]+(")', r"\g<1>" + ts + r"\g<2>", s, count=1, flags=re.M)
    if n != 1: sys.exit(f"{f}: {var} not found")
    open(p, "w", encoding="utf-8").write(s2); print(f"{f}: {var} = {ts}")
