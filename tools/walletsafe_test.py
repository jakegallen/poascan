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

    from poascan.swap import prompts as P, faq as SF
    from poascan import start as ST, faq as FQ, regcode as RC, join as J, keysafe as KS
    import json
    check("pinned CLI carries --hustle-url https://emblemvault.ai", P.EMB == "npx -y -p @emblemvault/agentwallet@3.3.0 emblemai " + HUSTLE and ST.INSTALL == P.EMB)
    on = P.templates()["connect"]
    texts = {"default": on}
    check("templates() connect is WALLET_PROMPT", P.WALLET_PROMPT == on)
    for nm, t in texts.items():
        check(f"[{nm}] pinned CLI, no global install, no bare emblemai", P.EMB in t and "npm install" not in t and not GLOBAL.search(t) and not bare_agent(t)
              and not re.search(r"(?<![-@/\w])emblemai --help", t))
        check(f"[{nm}] backup first, then the file-name check", t.index("cp -a ~/.emblemai ~/.emblemai.backup-") < t.index("find ~/.emblemai ~/.emblem-vault"))
        check(f"[{nm}] file names only; a wallet needs .env and .env.keys", "Find my wallet by file names only" in t and "Never open, print, edit or delete anything in ~/.emblemai" in t
              and "has both .env and .env.keys" in t and "cat " not in t.replace("never open, cat or print it", ""))
        check(f"[{nm}] every emblemai --agent run has --hustle-url (EMBLEMAI defined with it)", AGENT.search(t) and not no_hustle(t) and DEFINE.search(t))
        check(f"[{nm}] always --profile; never -p or EMBLEM_PASSWORD", "EMBLEMAI --profile PROFILE --agent -m" in t and "Never use -p, --password or EMBLEM_PASSWORD." in t
              and " -p " not in t.replace("npx -y -p @", "") and "EMBLEM_PASSWORD=" not in t)
        check(f"[{nm}] one attempt; stop on 'created a new wallet identity'; no retry on 500/405", "one attempt only" in t and '"created a new wallet identity"' in t
              and "no retry" in t and "Other errors (500, 405, any): show it, say my files are unchanged, stop." in t)
        check(f"[{nm}] asks before a new wallet", "No: ask me to confirm a new wallet. Only on yes, run EMBLEMAI profile create default" in t)
        check(f"[{nm}] own computer, Node 20.18+ with install commands, then check again", t.split("\n1. ", 1)[1].startswith("Only on my own computer") and "Need node -v 20.18+" in t
              and all(k in t for k in ("macOS: brew install node", "Linux: nvm install 22", "Windows: winget install OpenJS.NodeJS.LTS", "wait for me, check again")))
        check(f"[{nm}] one npx --cache retry with the Windows hint, one network retry, no version check", 'retry once with npx --cache "$(mktemp -d)" (Windows: use any new empty folder); network error' in t and "network error: say so, retry once." in t
              and not re.search(r"emblemai\b[^\n]{0,80}?(--version|\s-v\b|-V\b)", t, re.I) and "never another version" not in t)
        check(f"[{nm}] profile inspect shows Credentials: present before the one read", "EMBLEMAI profile inspect PROFILE runs and, in case A or B, shows Credentials: present; else stop." in t
              and t.index("EMBLEMAI profile inspect PROFILE") < t.index("EMBLEMAI --profile PROFILE --agent"))
        check(f"[{nm}] no em or en dashes", "\u2014" not in t and "\u2013" not in t)
        check(f"[{nm}] safety lines kept and no key-shaped text", "Never paste or show passwords, keys or seed phrases in chat." in t and not KS.has_key(t))
        f = RC.fill(t, P.WALLET_REG["lead"], P.WALLET_REG["before"], "s_" + "a" * 16)
        nums = [l for l in f.split("\n") if re.match(r"^\d+\. ", l)]
        check(f"[{nm}] setup code step lands last ({nums[-1][:12]!r})", [n[:2] for n in nums] == ["1.", "2.", "3.", "4.", "5."] and nums[-1].startswith(P.WALLET_REG["lead"]))
        ll = max(len(p) + len(quote(f, safe="")) for _, _, _, p, _ in J.APPS if p)
        check(f"[{nm}] longest prefill link under 8,000 characters ({ll})", ll < 8000)
    # POASwap wallet step v2 (main d26bd69): steps 1 to 3 of poaswap.io/start/prompt.txt, hold off, tokens filled
    SW_STEPS = "1. Only on my own computer: in a sandbox or container, stop and tell me. Need node -v 20.18+. Missing or older: give me the command (macOS: brew install node; Linux: nvm install 22; Windows: winget install OpenJS.NodeJS.LTS), wait for me, check again. Wallet CLI: only npx -y -p @emblemvault/agentwallet@3.3.0 emblemai --hustle-url https://emblemvault.ai (EMBLEMAI below). npx cache or permission error: retry once with npx --cache \"$(mktemp -d)\"; network error: say so, retry once.\n2. Find my wallet by file names only. Never open, print, edit or delete anything in ~/.emblemai or ~/.emblem-vault. Never use -p, --password or EMBLEM_PASSWORD. If ~/.emblemai exists, back it up: cp -a ~/.emblemai ~/.emblemai.backup-$(date +%s); check it exists. Then run find ~/.emblemai ~/.emblem-vault -maxdepth 3 -name '.env*' -o -name metadata.json -o -name .emblem-vault 2>/dev/null; echo END (END alone: none). Pick one case:\nA. ~/.emblemai/profiles/PROFILE has both .env and .env.keys: use it (several: ask me which).\nB. ~/.emblemai/.env and .env.keys at the top (old layout): ask me first. On yes, run EMBLEMAI profile list once; check profiles/default has both files and grep -c migratedFrom ~/.emblemai/profiles/default/metadata.json prints 1; PROFILE is default.\nC. Anything else (a lone .env, an empty profile, ~/.emblem-vault, anything unclear): stop, tell me what you found and where the backup is, run nothing else.\nD. Nothing found: ask me once, \"Do you already have an Emblem Wallet? (made on another computer / signed in at emblemvault.ai / no)\". Another computer: I run EMBLEMAI --restore-auth with my backup file; then redo this step. emblemvault.ai: skip step 3; I type my addresses under Need help on POASwap. No: ask me to confirm a new wallet. Only on yes, run EMBLEMAI profile create default; PROFILE is default.\n3. Check (offline): EMBLEMAI profile inspect PROFILE runs and, in case A or B, shows Credentials: present; else stop. Read the addresses, one attempt only: EMBLEMAI --profile PROFILE --agent -m \"List my wallet addresses as JSON: solana, evm. Addresses only.\"\nCase A or B and it says \"created a new wallet identity\"? Stop: no retry, no other wallet command, no change in ~/.emblemai; tell me it made a new wallet, not mine, and where the backup is. Other errors (500, 405, any): show it, say my files are unchanged, stop. Case D: tell me it is new and how to back it up: run EMBLEMAI in Terminal, type /auth, pick Backup Agent Auth, keep that file offline. Emblem backup: tell me only where the file is; never open, cat or print it."
    SW_CMDS = ("find ~/.emblemai ~/.emblem-vault -maxdepth 3 -name '.env*' -o -name metadata.json -o -name .emblem-vault 2>/dev/null; echo END",
               "cp -a ~/.emblemai ~/.emblemai.backup-$(date +%s)", "grep -c migratedFrom ~/.emblemai/profiles/default/metadata.json")
    check("POASwap wording: same check, backup and migrated commands", (P.CHECK_CMD, P.BACKUP_CMD, P.MIGRATED_CMD) == SW_CMDS)
    ours = "1. " + on.split("\n1. ", 1)[1].split("\n4. ", 1)[0]
    SW_W, OURS_W = 'retry once with npx --cache "$(mktemp -d)"; network', 'retry once with npx --cache "$(mktemp -d)" (Windows: use any new empty folder); network'
    SW_D, OURS_D = "emblemvault.ai: skip step 3; I type my addresses under Need help on POASwap.", "emblemvault.ai: skip step 3; link that vault in step 4."
    check("POASwap wording: steps 1 to 3 verbatim except the Windows hint and case D's emblemvault.ai line (no POASwap page here)",
          SW_D in SW_STEPS and SW_STEPS.count(SW_W) == 1 and ours == SW_STEPS.replace(SW_D, OURS_D).replace(SW_W, OURS_W) and "POASwap" not in ours)
    d = ST.data()
    nt = d["wallet"]["note"]
    check("MCP and llms data: wallet run pinned with a safety note (v2: Node, npx retries, inspect)", d["wallet"]["install"] == P.EMB and "--profile" in nt and "EMBLEM_PASSWORD" in nt
          and all(k in nt for k in ("Node 20.18+", "brew install node", "nvm install 22", "winget install OpenJS.NodeJS.LTS", 'npx --cache "$(mktemp -d)"', "Windows: any new empty folder",
                                     "network error: retry once", "emblemai profile inspect NAME must show Credentials: present, else stop"))
          and "\u2014" not in nt and "\u2013" not in nt
          and HUSTLE in nt and not GLOBAL.search(json.dumps(d)) and not bare_agent(json.dumps(d)) and not no_hustle(json.dumps(d)))
    fq = repr([p.get("qa") for p in FQ.PAGES.values() if isinstance(p, dict)])
    check("FAQ: Emblem Wallet is the recommended wallet, run pinned with --hustle-url", "the recommended wallet is Emblem Wallet, run pinned with Node 20.18+: " + P.EMB in fq and not GLOBAL.search(fq) and not no_hustle(fq))
    check("swap FAQ and safety line kept", "The recommended wallet is Emblem Wallet." in open(os.path.join(ROOT, "poascan", "swap", "faq.py")).read()
          and P.SAFE == "Never send payment outside the network.")
    print("FAILED: " + ", ".join(fails) if fails else "all walletsafe checks passed"); sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
