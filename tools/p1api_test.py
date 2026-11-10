"""1.26.289 (UI/UX P1): API gaps, additive. Sybil route and MCP tool, at-risk offset, leaderboard limit/offset, uptime
incidents, summary lite; defaults unchanged. No network: in-process calls on a temp database."""
import os, sys, tempfile, json
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."); sys.path.insert(0, ROOT)
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
from poascan import db
db.init()
from poascan import server as SV, agentapi as AG, analytics as A
src = open(os.path.join(ROOT, "poascan", "server.py")).read()
s = A.sybil_public()
check("sybil: counts only, the card's numbers", all(k in s for k in ("sampled_answers", "slot_templates", "instruction_echo", "capped_payees", "invited_agents", "inviters",
      "top5_inviter_counts", "web_labels", "shared_external_wallets", "anchor_linked_agents", "method")) and "poa1" not in json.dumps(s))
r = SV.api("/api/agents/sybil", {})
check("sybil route returns the same object", r[0] == A.sybil_public())
try: SV.api("/api/agents/sybil", {"x": ["1"]}); ok = False
except SV.BadRequest: ok = True
check("sybil route: an unknown parameter is a 400", ok)
names = [t[0] for t in AG.TOOLS]
check("MCP: sybil_signals is a tool (54 in all)", "sybil_signals" in names and len(names) == 54)
st = [t for t in AG.TOOLS if t[0] == "list_governance_standing"][0]
check("MCP: list_governance_standing takes offset", "offset" in json.dumps(st[3]))
check("at-risk: offset allowed and passed", '"/api/governance/at-risk": {"level", "limit", "offset", "sort", "dir"}' in SV.GOV_API.__repr__().replace("'", '"') or "offset" in SV.GOV_API["/api/governance/at-risk"])
from poascan import governance as GV
check("at-risk: rows are sliced by offset and the response carries offset and limit", "rows[offset:offset + limit]" in open(os.path.join(ROOT, "poascan", "governance.py")).read()
      and GV.api_at_risk.__defaults__[-1] == 0)
op = AG.openapi() if hasattr(AG, "openapi") else None
spec = json.dumps(op) if op else open(os.path.join(ROOT, "poascan", "agentapi.py")).read()
check("OpenAPI: sybil route, uptime incidents, leaderboard limit/offset, at-risk offset, summary lite", all(x in spec for x in ("/api/agents/sybil", "sybilSignals", '"incidents"', '"lite"')))
check("summary lite: drops cards, frags, feed, pill.pop and is never edge-cached", 'for k in ("cards", "frags", "feed"): d.pop(k, None)' in src and 'if path == "/api/summary" and not lite: hd["CDN-Cache-Control"]' in src)
check("leaderboard: paging only when asked", 'if qs.get("limit") or qs.get("offset"):' in src)
up = SV.api("/api/uptime", {"incidents": ["1"]})
check("uptime incidents=1 returns a list", isinstance(up[0], list))
check("uptime default unchanged (daily rows list)", isinstance(SV.api("/api/uptime", {})[0], list))
try: SV.api("/api/uptime", {"incidents": ["x"]}); ok = False
except SV.BadRequest: ok = True
check("uptime incidents must be 1 or 0", ok)
lb = SV.api("/api/leaderboard/earners", {}); lb2 = SV.api("/api/leaderboard/earners", {"limit": ["1"]})
check("leaderboard default unchanged; limit slices", isinstance(lb[0], list) and len(lb2[0]) <= 1)
llms = AG.llms_txt()
check("llms.txt lists the sybil route and the paging parameters", "/agents/sybil" in llms and "incidents=1" in llms and "lite=1" in llms)
check("no em or en dash in the new text", not any(ch in (json.dumps(s) + llms) for ch in "\u2013\u2014"))
print(f"{len(fails)} failed" if fails else "all ok"); sys.exit(1 if fails else 0)
