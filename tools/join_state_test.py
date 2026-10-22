"""Joining reads paused while maintenance is on and no join has landed for 90 minutes; a new join flips it back.
Usage: python3 tools/join_state_test.py"""
import os, sys, tempfile, time
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "j.db"); os.environ.pop("POASCAN_JOIN_OPEN", None); os.environ["POASCAN_MAINTENANCE"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, maint as M, analytics as A
db.init(); now = int(time.time())
M._active = lambda: True; M._surfaces = lambda: {}
db.write("INSERT OR REPLACE INTO fetch_log(endpoint,last_ok,fails,next_at,bytes) VALUES('/api/explorer/txs',?,0,0,1)", (now,))
def add_join(i, ts): db.write("INSERT INTO txs(id, type, ts) VALUES(?,?,?)", (f"{i:064x}", "join", ts))
fails = []
def check(n, c): print(("ok   " if c else "FAIL ") + n); c or fails.append(n)
check("no joins indexed -> open", M.join_state() == "open")
add_join(1, now - 2 * 3600)
check("last join 2h ago in maintenance -> paused (derived)", M.join_state() == "paused" and M.join_quiet())
st = "".join(M.strip_text())
check("strip: Hosted mining and joining paused for maintenance, paused once", st == "Hosted mining and joining paused for maintenance" and st.count("paused") == 1)
check("start line is the paused notice", M.join_line() == "Joining is paused during the upgrade. Your agent may need to retry later.")
check("meta description says joining paused once", "joining paused" in M.og_desc() and M.og_desc().count("paused") == 1)
check("no delayed wording anywhere", "delay" not in (st + M.join_line() + M.og_desc()).lower())
db.write("UPDATE fetch_log SET last_ok=? WHERE endpoint='/api/explorer/txs'", (now - 3600,))
check("our own feed stale -> not claimed paused", M.join_state() == "open")
db.write("UPDATE fetch_log SET last_ok=? WHERE endpoint='/api/explorer/txs'", (now,))
add_join(2, now - 60)
check("a new join lands -> open again", M.join_state() == "open" and M.strip_text()[2] == "Joining works.")
M._active = lambda: False; add_join(3, now - 5 * 3600); db.write("DELETE FROM txs WHERE id=?", (f"{2:064x}",))
check("maintenance off -> open", M.join_state() == "open")
M._surfaces = lambda: {"Joining": "paused"}
check("tracker paused wins", M.join_state() == "paused")
sys.exit(1 if fails else 0)
