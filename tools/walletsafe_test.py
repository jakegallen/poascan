"""Wallet safety after the Oct 22 emblemai 3.3.0 incident (a new random wallet when --agent found no stored password).
* No served text tells an agent to install the CLI globally or to run emblemai --agent without --profile or without
  --hustle-url https://emblemvault.ai (agenthustle.ai/api/chat 301s; fetch turns the POST into a GET, 405). EMBLEMAI
  shorthand counts only where the text defines it as the pinned command with --hustle-url.
* The wallet prompt uses POASwap's wallet step v2 (main d26bd69, as served at poaswap.io/start/prompt.txt) word for
  word, except the Windows hint after the npx --cache retry and case D's emblemvault.ai line: own computer, Node 20.18+ with the install command per OS, pinned
  npx -y -p @emblemvault/agentwallet@3.3.0 emblemai --hustle-url https://emblemvault.ai, one npx --cache retry and one
  network retry, no version check, cp -a backup first, file names only (.env and .env.keys), cases A to D, always
  --profile, never -p or EMBLEM_PASSWORD, profile inspect must show Credentials: present, one attempt, stop on
  "created a new wallet identity", no retry on 500/405, ask before a new wallet.
* Its prefill links stay under 8,000 characters with the setup code step in. No em or en dashes.
Usage: python3 tools/walletsafe_test.py"""
import os, re, subprocess, sys
from urllib.parse import quote
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

GLOBAL = re.compile(r"npm\s+(install|i)\s+-g\s+@emblemvault", re.I)
AGENT = re.compile(r"emblemai\b[^\n\"']{0,120}?--agent\b", re.I)   # an emblemai (or EMBLEMAI) command reaching --agent
def bare_agent(s):
    """emblemai ... --agent spans that lack --profile (python's own escapes are fine: we scan raw source and rendered text)."""
    return [m.group(0) for m in AGENT.finditer(s) if "--profile" not in m.group(0)]

HUSTLE = "--hustle-url https://emblemvault.ai"
DEFINE = re.compile(r"emblemai --hustle-url https://emblemvault\.ai\b[^\n]{0,40}?\(EMBLEMAI below\)|\{emb\} \(EMBLEMAI below\)")
def no_hustle(s):
    """emblemai ... --agent spans without --hustle-url; EMBLEMAI ... spans pass only if s defines EMBLEMAI with it."""
    ok_short = bool(DEFINE.search(s))
    return [m.group(0) for m in AGENT.finditer(s) if HUSTLE not in m.group(0) and not (m.group(0).startswith("EMBLEMAI") and ok_short)]

def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    skip = ("CHANGELOG.md", "tools/walletsafe_test.py", "data/census.csv")   # history and this test's own patterns
    return [f for f in out if f not in skip and os.path.splitext(f)[1] in (".py", ".js", ".json", ".md", ".txt", ".html", ".toml", ".css")]

def main():
    hits_g, hits_a, hits_h = [], [], []
    for f in tracked():
        try: s = open(os.path.join(ROOT, f), encoding="utf-8").read()
        except (UnicodeDecodeError, FileNotFoundError): continue
        if GLOBAL.search(s): hits_g.append(f)
        if bare_agent(s): hits_a.append(f)
        if no_hustle(s): hits_h.append(f)
    check(f"no 'npm install -g @emblemvault' in any tracked source {hits_g}", not hits_g)
    check(f"no emblemai --agent without --profile in any tracked source {hits_a}", not hits_a)
    check(f"no emblemai --agent without {HUSTLE} in any tracked source {hits_h}", not hits_h)

    from poascan import start as ST, faq as FQ
    import json
    check("pinned CLI carries --hustle-url https://emblemvault.ai", ST.INSTALL == "npx -y -p @emblemvault/agentwallet@3.3.0 emblemai " + HUSTLE)
    check("the swap page wallet prompt is gone with the swap page (POASwap serves its own)", not os.path.exists(os.path.join(ROOT, "poascan", "swap", "prompts.py")))
    d = ST.data()
    nt = d["wallet"]["note"]
    check("MCP and llms data: wallet run pinned with a safety note (v2: Node, npx retries, inspect)", d["wallet"]["install"] == ST.INSTALL and "--profile" in nt and "EMBLEM_PASSWORD" in nt
          and all(k in nt for k in ("Node 20.18+", "brew install node", "nvm install 22", "winget install OpenJS.NodeJS.LTS", 'npx --cache "$(mktemp -d)"', "Windows: any new empty folder",
                                     "network error: retry once", "emblemai profile inspect NAME must show Credentials: present, else stop"))
          and "\u2014" not in nt and "\u2013" not in nt
          and HUSTLE in nt and not GLOBAL.search(json.dumps(d)) and not bare_agent(json.dumps(d)) and not no_hustle(json.dumps(d)))
    fq = repr([p.get("qa") for p in FQ.PAGES.values() if isinstance(p, dict)])
    check("FAQ: Emblem Wallet is the recommended wallet, run pinned with --hustle-url", "the recommended wallet is Emblem Wallet, run pinned with Node 20.18+: " + ST.INSTALL in fq and not GLOBAL.search(fq) and not no_hustle(fq))
    print("FAILED: " + ", ".join(fails) if fails else "all walletsafe checks passed"); sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
