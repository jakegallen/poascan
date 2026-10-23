"""Wallet safety after the Oct 22 emblemai 3.3.0 incident (a new random wallet when --agent found no stored password).
* No served text tells an agent to install the CLI globally or to run emblemai --agent without --profile.
* The wallet prompt uses POASwap's steps (fix/wallet-prompt-safety) word for word: own computer, Node 20.18+, pinned
  npx -y -p @emblemvault/agentwallet@3.3.0 emblemai, cp -a backup first, file names only (.env and .env.keys), cases A to D,
  always --profile, never -p or EMBLEM_PASSWORD, one attempt, stop on "created a new wallet identity", no retry on 500/405,
  ask before a new wallet. POASCAN_WALLET_HOLD (default on) stops cases A and B before the CLI runs.
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

def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    skip = ("CHANGELOG.md", "tools/walletsafe_test.py", "data/census.csv")   # history and this test's own patterns
    return [f for f in out if f not in skip and os.path.splitext(f)[1] in (".py", ".js", ".json", ".md", ".txt", ".html", ".toml", ".css")]

def main():
    hits_g, hits_a = [], []
    for f in tracked():
        try: s = open(os.path.join(ROOT, f), encoding="utf-8").read()
        except (UnicodeDecodeError, FileNotFoundError): continue
        if GLOBAL.search(s): hits_g.append(f)
        if bare_agent(s): hits_a.append(f)
    check(f"no 'npm install -g @emblemvault' in any tracked source {hits_g}", not hits_g)
    check(f"no emblemai --agent without --profile in any tracked source {hits_a}", not hits_a)

    from poascan.swap import prompts as P, faq as SF
    from poascan import start as ST, faq as FQ, regcode as RC, join as J, keysafe as KS
    import json
    texts = {}
    for hold in ("on", "off"):
        os.environ["POASCAN_WALLET_HOLD"] = hold
        texts[hold] = P.templates()["connect"]
    os.environ.pop("POASCAN_WALLET_HOLD", None)
    on, off = texts["on"], texts["off"]
    check("default is hold on (the import-time WALLET_PROMPT and templates())", P.WALLET_PROMPT == on and P.wallet_hold())
    for nm, t in texts.items():
        check(f"[{nm}] pinned CLI, no global install, no bare emblemai", P.EMB in t and "npm install" not in t and not GLOBAL.search(t) and not bare_agent(t)
              and not re.search(r"(?<![-@/\w])emblemai --help", t))
        check(f"[{nm}] backup first, then the file-name check", t.index("cp -a ~/.emblemai ~/.emblemai.backup-") < t.index("find ~/.emblemai ~/.emblem-vault"))
        check(f"[{nm}] file names only; a wallet needs .env and .env.keys", "find my wallet by file names only" in t and "Never open, print, edit or delete anything in ~/.emblemai" in t
              and "has both .env and .env.keys" in t and "cat " not in t.replace("never open, cat or print it", ""))
        check(f"[{nm}] always --profile; never -p or EMBLEM_PASSWORD", "EMBLEMAI --profile PROFILE --agent -m" in t and "Never use -p, --password or EMBLEM_PASSWORD." in t
              and " -p " not in t.replace("npx -y -p @", "") and "EMBLEM_PASSWORD=" not in t)
        check(f"[{nm}] one attempt; stop on 'created a new wallet identity'; no retry on 500/405", "one attempt only" in t and '"created a new wallet identity"' in t
              and "no retry" in t and "Other errors (500, 405, any): show the error, say my files are unchanged, stop." in t)
        check(f"[{nm}] asks before a new wallet", "No: ask me to confirm a new wallet. Only on yes, run EMBLEMAI profile create default" in t)
        check(f"[{nm}] own computer, Node 20.18", t.split("\n1. ", 1)[1].startswith("Only on my own computer") and "node -v under 20.18" in t)
        check(f"[{nm}] no em or en dashes", "\u2014" not in t and "\u2013" not in t)
        check(f"[{nm}] safety lines kept and no key-shaped text", "Never paste or show passwords, keys or seed phrases in chat." in t and not KS.has_key(t))
        f = RC.fill(t, P.WALLET_REG["lead"], P.WALLET_REG["before"], "s_" + "a" * 16)
        nums = [l for l in f.split("\n") if re.match(r"^\d+\. ", l)]
        check(f"[{nm}] setup code step lands last ({nums[-1][:12]!r})", [n[:2] for n in nums] == ["1.", "2.", "3.", "4.", "5."] and nums[-1].startswith(P.WALLET_REG["lead"]))
        ll = max(len(p) + len(quote(f, safe="")) for _, _, _, p, _ in J.APPS if p)
        check(f"[{nm}] longest prefill link under 8,000 characters ({ll})", ll < 8000)
    check("hold on: cases A and B stop before the CLI", P.CASE_A_HOLD in on and P.CASE_B_HOLD in on and P.CASE_A not in on)
    check("hold off: cases A and B read per POASwap", P.CASE_A in off and P.CASE_B.format(migrated_cmd=P.MIGRATED_CMD) in off and P.CASE_A_HOLD not in off)

    # POASwap's blocks, as on fix/wallet-prompt-safety d21f6ae (poaswap/prompts/start_prompt.json, poaswap/site.py), with tokens filled
    SW_INSTALL = "Only on my own computer: in a sandbox or container, stop and tell me. node -v under 20.18: stop, ask me to upgrade. Wallet CLI: only npx -y -p @emblemvault/agentwallet@3.3.0 emblemai (EMBLEMAI below), never another version."
    SW_ADDR = ('Read the addresses, one attempt only: EMBLEMAI --profile PROFILE --agent -m "List my wallet addresses as JSON: solana, evm. Addresses only."\nCase A or B and it says "created a new wallet identity"? '
               "Stop: no retry, no other wallet command, no change in ~/.emblemai; tell me it made a new wallet, not mine, and where the backup is. Other errors (500, 405, any): show the error, say my files are unchanged, stop. "
               "Case D: tell me it is new and how to back it up: run EMBLEMAI in Terminal, type /auth, pick Backup Agent Auth, keep that file offline. Emblem backup: tell me only where the file is; never open, cat or print it.")
    SW_CMDS = ("find ~/.emblemai ~/.emblem-vault -maxdepth 3 -name '.env*' -o -name metadata.json -o -name .emblem-vault 2>/dev/null; echo END",
               "cp -a ~/.emblemai ~/.emblemai.backup-$(date +%Y%m%d-%H%M%S)", "grep -c migratedFrom ~/.emblemai/profiles/default/metadata.json")
    check("POASwap wording: install and read steps verbatim", SW_INSTALL in on and SW_ADDR in on)
    check("POASwap wording: same check, backup and migrated commands", (P.CHECK_CMD, P.BACKUP_CMD, P.MIGRATED_CMD) == SW_CMDS)
    fw = on.split("\n2. ", 1)[1].split("\n3. ", 1)[0]
    check("POASwap wording: find step verbatim except the emblemvault.ai line (no POASwap page here)",
          fw.startswith("Back up, then find my wallet by file names only.") and "emblemvault.ai: skip the next step; link that vault in the last step." in fw and "POASwap" not in fw)

    d = ST.data()
    check("MCP and llms data: wallet run pinned with a safety note", d["wallet"]["install"] == P.EMB and "--profile" in d["wallet"]["note"] and "EMBLEM_PASSWORD" in d["wallet"]["note"]
          and not GLOBAL.search(json.dumps(d)) and not bare_agent(json.dumps(d)))
    fq = repr([p.get("qa") for p in FQ.PAGES.values() if isinstance(p, dict)])
    check("FAQ: Emblem Wallet is the recommended wallet, run pinned", "the recommended wallet is Emblem Wallet" in fq and P.EMB in fq and not GLOBAL.search(fq))
    check("swap FAQ and safety line kept", "The recommended wallet is Emblem Wallet." in open(os.path.join(ROOT, "poascan", "swap", "faq.py")).read()
          and P.SAFE == "Never send payment outside the network.")
    print("FAILED: " + ", ".join(fails) if fails else "all walletsafe checks passed"); sys.exit(1 if fails else 0)

if __name__ == "__main__": main()
