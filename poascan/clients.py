"""The shared client registry (data/clients.json): one row per app that /start offers, with its tier, how it opens with a
prompt (prefill prefix, or none) and how to add the PoA connector. POAScan's /start and /api/v1/prompts/join?client= read it
here; POASwap can load the same file or GET /api/v1/prompts/clients. Tiers map to the prompt variants in
onboarding_prompt.py: full and connector (chat-browse retired in v2.9); "none" has no prompt (the /start no-path panel)."""
import json, os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "clients.json")
TIERS = ("full", "connector", "none")
ROWS = ("top", "more")

def _load():
    with open(PATH, encoding="utf-8") as f: d = json.load(f)
    ids = [c["id"] for c in d["clients"]]
    assert len(ids) == len(set(ids)), "client ids are unique"
    for c in d["clients"]:
        assert c["tier"] in TIERS and c["row"] in ROWS, c["id"]
        assert c["tier"] != "connector" or c.get("connector"), c["id"] + ": a connector client has connector settings"
    assert all(a in ids for a in d["nopath"]["alternatives"]), "no-path alternatives are known ids"
    return d

DATA = _load()
RAW = open(PATH, encoding="utf-8").read()   # served as is at /api/v1/prompts/clients
CLIENTS = DATA["clients"]
BY_ID = {c["id"]: c for c in CLIENTS}
MCP_URL = DATA["mcp_url"]
NOPATH = DATA["nopath"]

def get(cid):
    """The registry row for a client id, or None."""
    return BY_ID.get(cid)

def variant(c):
    """The prompt variant for a registry row (None for tier none)."""
    return DATA["tiers"][c["tier"]]["variant"]

def ids():
    return [c["id"] for c in CLIENTS]
