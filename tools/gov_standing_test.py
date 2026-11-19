"""Governance standing data asks: 5a summary (/api/v1/governance/standing, counts only), 5b changed rows feed and
5c offset paging (/api/v1/governance/standing-moves). Unit-tests the fold math with a crafted standing (safe omitted,
removed from the last close only, biggest-change-first order, paging), then checks both live routes answer JSON.
Usage: python3 tools/gov_standing_test.py"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import governance as GV

FAILS = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or FAILS.append(name)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def req(url):
    r = urllib.request.urlopen(url, timeout=20)
    return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Content-Type", "")

def unit():
    # a crafted standing: 2 safe, 1 watch, 2 at_risk (one closing next), with a last close E50
    rows = [
        dict(address="poa1safe1", name="S1", level="safe", left=9, drop=59, last=49, missed=1),
        dict(address="poa1safe2", name="S2", level="safe", left=5, drop=55, last=49, missed=1),
        dict(address="poa1watch", name="W", level="watch", left=3, drop=53, last=47, missed=3),
        dict(address="poa1risk1", name="R1", level="risk", left=1, drop=51, last=45, missed=5),
        dict(address="poa1risk0", name="R0", level="risk", left=0, drop=50, last=44, missed=6),
    ]
    counts = {k: sum(1 for r in rows if r["level"] == k) for k, _ in GV.LEVELS}
    fake_standing = dict(rows=rows, open_epoch=51, ttl=6, last_close=50, counts=counts)
    chg = [dict(close=49, close_ts=1000, removed_list=["poa1old"]),
           dict(close=50, close_ts=2000, removed_list=["poa1gone1", "poa1gone2"])]
    orig_sr, orig_fn, orig_sc = GV.standing_rows, GV.A.forum_names, GV.GV2.standing_changes
    GV.standing_rows = lambda: fake_standing
    GV.A.forum_names = lambda: {}
    GV.GV2.standing_changes = lambda: chg
    try:
        # 5a summary
        s = GV.api_standing_summary()
        check("5a counts safe/watch/at_risk", s["safe"] == 2 and s["watch"] == 1 and s["at_risk"] == 2)
        check("5a closing_next counts left==1", s["closing_next"] == 1)
        check("5a established is the sum", s["established"] == 5)
        check("5a carries open_epoch/last_close, counts only (no rows key)", s["open_epoch"] == 51 and s["last_close"] == 50 and "rows" not in s)

        # 5b changed rows only
        m = GV.api_standing_moves(limit=20, offset=0)
        levels = [r["level"] for r in m["rows"]]
        check("5b omits safe rows", not any(r["address"].startswith("poa1safe") for r in m["rows"]))
        check("5b includes watch + both at_risk + 2 removed (from last close only)", m["total"] == 5)
        check("5b removed come only from the last close (E50), not E49", not any(r["address"] == "poa1old" for r in m["rows"]))
        check("5b biggest change first: removed, then at_risk, then watch",
              levels == ["removed", "removed", "at_risk", "at_risk", "watch"])
        check("5b at_risk ordered by fewest closes left (R0 before R1)",
              [r["address"] for r in m["rows"] if r["level"] == "at_risk"] == ["poa1risk0", "poa1risk1"])
        check("5b counts split removed/at_risk/watch", m["counts"] == {"removed": 2, "at_risk": 2, "watch": 1})
        check("5b removed rows carry close + close_ts, not left", all(
            (r.get("close") == 50 and r.get("close_ts") == 2000 and r["left"] is None) for r in m["rows"] if r["level"] == "removed"))

        # 5c paging
        p1 = GV.api_standing_moves(limit=2, offset=0); p2 = GV.api_standing_moves(limit=2, offset=2)
        check("5c limit pages the rows", len(p1["rows"]) == 2 and p1["total"] == 5 and p1["limit"] == 2)
        check("5c offset advances the page", [r["address"] for r in p2["rows"]] == [r["address"] for r in m["rows"][2:4]])
    finally:
        GV.standing_rows, GV.A.forum_names, GV.GV2.standing_changes = orig_sr, orig_fn, orig_sc

def live():
    port = free_port(); base = f"http://127.0.0.1:{port}"; tmp = tempfile.mkdtemp()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "t.db"),
               POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env)
    try:
        for _ in range(50):
            try: req(base + "/api/health"); break
            except Exception: time.sleep(0.2)
        c, b, ct = req(base + "/api/v1/governance/standing")
        j = json.loads(b)
        check("/api/v1/governance/standing serves JSON (200) with counts, no rows", c == 200 and "json" in ct and "rows" not in j and "safe" in j)
        c2, b2, _ = req(base + "/api/v1/governance/standing-moves?limit=5")
        j2 = json.loads(b2)
        check("/api/v1/governance/standing-moves serves JSON with rows/total/counts/limit", c2 == 200 and all(k in j2 for k in ("rows", "total", "counts", "limit")))
        check("standing-moves limit is clamped to the 1..100 cap", json.loads(req(base + "/api/v1/governance/standing-moves?limit=500")[1])["limit"] == 100)
        try:
            req(base + "/api/v1/governance/standing-moves?bogus=1"); ok = False
        except urllib.error.HTTPError as e:
            ok = e.code == 400
        check("standing-moves rejects an unknown query parameter (400)", ok)
    finally:
        p.terminate()
        try: p.wait(timeout=5)
        except Exception: p.kill()

def main():
    unit(); live()
    print(("all passed" if not FAILS else f"{len(FAILS)} failure(s)"))
    sys.exit(1 if FAILS else 0)

if __name__ == "__main__":
    main()
