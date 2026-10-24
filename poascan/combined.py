"""Combined prompt hash slot. POASwap supplies the combined prompt text; until it lands this module publishes nothing.
Slot: poascan/combined_prompt.txt (POASCAN_COMBINED_PROMPT overrides the path, for tests). Read once at import, so the
hash is fixed per build (the file ships in the image with poascan/). Rule: the file's UTF-8 text with one trailing LF
dropped, then the join prompt rule (start.text_sha256: LF only, no BOM, no trailing newline). Absent, empty or invalid:
TEXT and SHA256 are None, every API carries combined_sha256 null and no page renders anything new."""
import os

SLOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "combined_prompt.txt")
HASH_RULE = ("SHA-256 of the UTF-8 text from /api/v1/prompts/combined: LF newlines, no BOM, no trailing newline. "
             "null until the combined prompt is published.")
# 1.26.89: available but not the default. POAScan's default is the mining-only join prompt; this is POASwap's wallet setup prompt.
DEFAULT_PROMPT = "https://poascan.io/api/v1/prompts/join"
VERIFY = "curl -s https://poascan.io/api/v1/prompts/combined | jq -j .text | sha256sum"

def load(path=None):
    """(text, sha256, error). text and sha256 are None when the slot is absent, empty or breaks the rule; error says why (None when absent or fine)."""
    p = path or os.environ.get("POASCAN_COMBINED_PROMPT") or SLOT
    try: raw = open(p, "rb").read()
    except FileNotFoundError: return None, None, None
    try: t = raw.decode("utf-8")
    except UnicodeDecodeError: return None, None, "not UTF-8"
    if t.endswith("\n"): t = t[:-1]
    if not t.strip(): return None, None, "empty"
    if t.startswith("\ufeff"): return None, None, "BOM"
    if "\r" in t: return None, None, "CR newline"
    if t.endswith("\n"): return None, None, "more than one trailing newline"
    from .start import text_sha256
    return t, text_sha256(t), None

TEXT, SHA256, ERROR = load()

def fields():
    """The one field every join hash surface adds: combined_sha256 (None until the text lands)."""
    return dict(combined_sha256=SHA256)

def api():
    """GET /api/v1/prompts/combined. Always 200: available false and nulls until the text lands."""
    return dict(available=SHA256 is not None, default=False, default_prompt=DEFAULT_PROMPT, text=TEXT, combined_sha256=SHA256, hash_rule=HASH_RULE, verify=VERIFY if SHA256 else None,
                source="POASwap supplies the combined prompt text; POAScan publishes its hash next to the join prompt hash.")
