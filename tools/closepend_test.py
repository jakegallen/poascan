"""1.26.307: closes counted by /api/status with no record in /api/epochs (minepoa.com halted that list on Nov 8).
Their archived close reports are read (at most 2 per run), and Home, /chain History, Token tips and
/api/v1/epochs?pending=1 show them as Record pending, with reward fields blank. Temp DB, no network.
Usage: python3 tools/closepend_test.py"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "c.db")
for k in ("PORT", "HOST", "POASCAN_MAINTENANCE"): os.environ.pop(k, None)
os.environ.update(POASCAN_DB=DB, POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
FAILS = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or FAILS.append(name)

subprocess.run([sys.executable, "tools/fixture.py"], cwd=ROOT, env=os.environ, check=True, capture_output=True)
from poascan import db, closepend as C, analytics as A, segments as SG
with SG.use(SG.CURRENT): last = A.epoch_rows()[-1]
L, T = int(last["epoch"]), int(last["close_ts"])
st, _ = db.get_blob("status")
check("nothing missing while records keep up: no read", C.missing() == [] and C.run() == 0)
st["epochs_closed"] = L + 4; db.put_blob("status", st)   # three closes past the last record
rep = lambda n: {"close_epoch": n, "close_ts": T + (n - L) * 21600, "settled_count": 10, "settled_split": {"passed": 7, "failed": 2, "expired_empty_jury": 1, "expired_with_seals": 0},
                 "establishment": {"admitted": 3, "eligible": 9}}
db.put_blob("close_report_auth", rep(L + 3))
check("missing lists the closes past the record", C.missing() == [L + 1, L + 2, L + 3])
calls = []
def fake(p): calls.append(p); n = int(p.rsplit("=", 1)[1]); return rep(n)
C.job(fetch=fake, sleep=lambda s: None)
check("the latest close comes from the hourly close report (no extra read); two archived reads, newest first",
      calls == [f"/api/close-report?epoch={L + 2}", f"/api/close-report?epoch={L + 1}"])
calls.clear(); C.job(fetch=fake, sleep=lambda s: None)
check("each report is read once", calls == [])
r = C.rows()
check("rows: pending closes oldest first, reward fields null, settled split kept",
      [x["epoch"] for x in r] == [L + 1, L + 2, L + 3] and all(x["minted"] is None and x["paid"] is None and x["record"] == "pending" for x in r)
      and r[0]["settled_passed"] == 7 and r[0]["settled_expired_no_jury"] == 1)
check("span names the gap", C.span() == f"E{L + 1} to E{L + 3}")
bad = lambda p: {"close_epoch": 999, "close_ts": 1}
db.put_blob(C.BLOB, {}); db.put_blob("close_report_auth", {})
C.job(fetch=bad, sleep=lambda s: None)
check("a report for another close is not stored", C.rows() == [])
C.job(fetch=fake, sleep=lambda s: None); C.job(fetch=fake, sleep=lambda s: None)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
port = free_port(); base = f"http://127.0.0.1:{port}"
p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=dict(os.environ, PORT=str(port), HOST="127.0.0.1"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def get(u):
    with urllib.request.urlopen(base + u, timeout=60) as r: return r.read().decode()
try:
    for _ in range(100):
        try: get("/api/health"); break
        except Exception: time.sleep(0.2)
    h = get("/")
    i = h.find('data-liverows="closes-home"'); home = h[i:i + 12000]
    check("Home Closes shows the newest close first, marked Record pending", f">E{L + 3}<" in home and "Record pending" in home
          and home.find(f">E{L + 3}<") < home.find(f">E{L + 2}<") < home.find(f"E{L}<"))
    c = get("/chain")
    check("/chain History lists the pending closes on top", "RECORD PENDING" in c and c.find(f">E{L + 3}<") < c.find(f">E{L}<") and c.count("RECORD PENDING") == 3)
    c2 = get("/chain?sort=paid")
    check("a sorted History leaves them out (no blank sort values)", "RECORD PENDING" not in c2)
    a = json.loads(get("/api/v1/epochs"))
    check("/api/v1/epochs by default is unchanged (records only)", a[-1]["epoch"] == L and all(x.get("record") != "pending" for x in a))
    ap = json.loads(get("/api/v1/epochs?pending=1"))
    check("/api/v1/epochs?pending=1 ends with the latest close", ap[-1]["epoch"] == L + 3 and ap[-1]["record"] == "pending" and ap[-1]["minted"] is None and len(ap) == len(a) + 3)
    t = get("/network?tab=token")
    check("Token totals say which closes they leave out", f"E{L + 1} to E{L + 3} closed with no record published yet" in t)
    check("no em or en dashes in the new rows", not any(ch in home for ch in "\u2014\u2013"))
finally:
    p.terminate()
    try: p.wait(timeout=5)
    except Exception: p.kill()
print("all passed" if not FAILS else f"{len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
