"""Block keys and tokens from ever being committed. Prints file:line and the rule name only, never the match.
  python3 tools/keyscan.py            scan every tracked file
  python3 tools/keyscan.py --staged   scan lines being added in the index (pre-commit hook)
  python3 tools/keyscan.py --range A..B   scan lines added in a commit range (CI)
Exit 1 on any finding."""
import re, subprocess, sys
RULES = [
    ("PoA key", re.compile(r"(?<![A-Za-z0-9])(?:p?sk|pk)_(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("Fly token", re.compile(r"\bFlyV1\s+fm\d_[A-Za-z0-9_\-+/=]{20,}|\bfm2_[A-Za-z0-9_\-+/=]{40,}")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("credential in URL", re.compile(r"(?i)[?&](?:api_key|apikey|key|token|auth_token|access_token|guid)=(?![A-Z_]{3,}\b|\{|<|%s|\.\.\.|…|pk_…)[A-Za-z0-9_\-]{20,}")),
]
SKIP = re.compile(r"\.(?:woff2?|png|jpe?g|gif|webp|ico|bundle|db|sqlite)$")

def scan_text(name, lines):
    out = []
    for n, line in lines:
        for rule, rx in RULES:
            if rx.search(line): out.append(f"{name}:{n}: {rule}")
    return out

def tracked():
    out = []
    for f in subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout.decode().split("\0"):
        if not f or SKIP.search(f): continue
        try: txt = open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError): continue
        out += scan_text(f, enumerate(txt.splitlines(), 1))
    return out

def added(args):
    diff = subprocess.run(["git", "diff", "--no-color", "-U0", *args], capture_output=True, check=True).stdout.decode("utf-8", "replace")
    out, f, n = [], None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "): f = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"): n = int(re.search(r"\+(\d+)", line).group(1))
        elif line.startswith("+") and f and not SKIP.search(f): out += scan_text(f, [(n, line[1:])]); n += 1
    return out

def main():
    a = sys.argv[1:]
    found = added(["--cached"]) if a[:1] == ["--staged"] else added([a[1]]) if a[:1] == ["--range"] else tracked()
    for x in found: print("secret scan: " + x)
    print(f"secret scan: {len(found)} finding(s)")
    sys.exit(1 if found else 0)

if __name__ == "__main__":
    main()
