"""Re-admission flag (build only, not released). An Agent back in established_after one close after an
established_removed, with no challenge_eligible record at either close, reads readmitted with the close it came back
at: established history (API and MCP get_address), get_standing and /api/v1/address/<a>/standing state, and the
address page (tag, row, change label). A normal return (eligible, or a longer gap) is not flagged. Temp database, no network."""
import json, os, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(); os.environ.update(POASCAN_DB=os.path.join(tmp, "r.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
from poascan import db, analytics as A, agents as G, standing as SD, views as V
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
db.init()
ad = lambda c: "poa1" + c * 40
R, N, L = ad("R"), ad("N"), ad("L")   # readmitted, normal return (eligible), long gap
def close(n, **b): return {"epoch": n, "ts": 1_000_000 + n * 21600, "pool": 1e9, "rewards": {}, "challenges": {},
                           "basis": dict({"established_after": [], "established_removed": [], "challenge_eligible": [], "settled": [], "pending": {}}, **b)}
eps = [close(0), close(1, established_after=[R, N, L], challenge_eligible=[R, N, L]), close(2), close(3, established_removed=[R, N, L]),
       close(4, established_after=[R, N], challenge_eligible=[N]), close(5), close(6, established_after=[L])]
db.put_blob("epochs", eps); A._cache.clear()
h = G.established_history(R)
check("readmitted: back one close after removal, no eligibility", h["readmitted"] is True and h["readmitted_epoch"] == 4 and h["basis"] == "readmitted" and h["basis_epoch"] == 4)
check("readmitted: readmissions list and the change flag", h["readmissions"] == [dict(epoch=4, close_ts=eps[4]["ts"], removed_epoch=3)] and h["changes"][0]["readmitted"] is True and h["changes"][1]["readmitted"] is False)
hn = G.established_history(N); hl = G.established_history(L)
check("not flagged: an eligible return", hn["readmitted"] is False and hn["basis"] == "listed" and hn["readmitted_epoch"] is None)
check("not flagged: a longer gap", hl["readmitted"] is False and hl["basis"] == "listed")
A.established_set = lambda: {R, N, L}
st = SD.standing(R)
check("standing: state readmitted with the close", st["state"] == "readmitted" and st["readmitted_epoch"] == 4)
check("standing: a normal Agent reads established", SD.standing(N)["state"] == "established")
html = V.established_card(R) if hasattr(V, "established_card") else None
if html is None:
    fn = [getattr(V, n) for n in dir(V) if n.startswith("_est") or n in ("established_html", "_established")]
    html = fn[0](R) if fn else ""
check("address card: RE-ADMITTED tag, row and change label", "RE-ADMITTED" in html and "Re-admitted at the E4 close" in html and "Re-admitted" in html and "removed at E3" in html)
check("no em or en dash", "\u2014" not in html and "\u2013" not in html)
print("ALL OK" if not fails else f"{len(fails)} FAILED"); sys.exit(1 if fails else 0)
