"""Parse test for poascan/halts.py against a sanitized copy of the halt table (tools/halts_fixture.md: endpoints and
status only). Usage: python3 tools/halts_test.py (temp database, no network)."""
import os, sys, tempfile
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, halts as H, maint as M

FIX = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "halts_fixture.md"), encoding="utf-8").read()
fails = []
def check(name, cond): print(("ok   " if cond else "FAIL ") + name); cond or fails.append(name)

def main():
    db.init()
    d = H.parse(FIX)
    check("fixture: all nine groups map, none unknown", set(d["groups"]) == set(H.GROUPS) and d["unknown"] == 0)
    check("fixture: awaiting halts read as planned", set(d["groups"].values()) == {"planned"})
    check("fixture: stays live has self-custody mining and explorer", {"Self-custody mining", "Explorer"} <= set(d["stays_live"]))
    for cell, want in [("🟢 halt", "paused"), ("🟢 halted", "paused"), ("done, halted", "paused"), ("🟡 halt", "planned"), ("⬜ halt", "planned"),
                       ("⏳ halt soon", "planned"), ("🟢 re-enabled", "back"), ("cleared", "back"), ("back live", "back"), ("❌ cancelled", "live"),
                       ("🟢", None), ("???", None)]:
        check(f"state_of({cell!r}) == {want}", H.state_of(cell) == want)
    mixed = FIX.replace("| `GET/POST /api/hosted/register` | - | - | ⏳ halt |", "| `GET/POST /api/hosted/register` | - | - | 🟢 halt |") \
               .replace("| `GET/POST /api/hosted/answer` | - | - | ⏳ halt |", "| `GET/POST /api/hosted/answer` | - | - | 🟢 re-enabled |") \
               .replace("| `/mcp` mining tools | - | - | ⏳ halt |", "| `/mcp` mining tools | - | - | 🤷 |")
    m = H.parse(mixed)
    check("mixed: Joining is paused when register is (worst of the family)", m["groups"]["Joining"] == "paused")
    check("mixed: re-enabled reads back", m["groups"]["Answers"] == "back")
    check("mixed: unknown row counted and left out (no change)", m["unknown"] == 1 and "MCP mining tools" not in m["groups"])
    try: H.parse("# nothing here"); bad = False
    except ValueError: bad = True
    check("missing section raises (caller keeps last good)", bad)
    # JOIN_OPEN: manual env override wins, else tracker, else default open
    M.JOIN_ENV = None
    check("no tracker state: joining open (manual default)", M.join_open() is True)
    db.put_blob(H.BLOB, dict(groups=m["groups"], stays_live=[], ts=int(__import__("time").time())))
    check("tracker says Joining paused: join_open is False", M.join_open() is False)
    M.JOIN_ENV = "1"
    check("manual override POASCAN_JOIN_OPEN=1 wins", M.join_open() is True)
    M.JOIN_ENV = None
    s = H.summary()
    check("summary exposes groups and source only", s["surfaces_source"] == "tracker" and s["surfaces"]["Joining"] == "paused" and set(s) == {"surfaces", "surfaces_source", "surfaces_as_of", "stays_live"})
    if fails: print(f"{len(fails)} failed"); sys.exit(1)
    print("all passed")

main()
