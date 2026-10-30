"""Growth bench (1.26.236): does memory and CPU stay flat as closes and Agents grow?
Builds copies of a bench DB with the close list and the Agents (accounts and txs) scaled 1x, 2x and 5x, starts the
server on each with no upstream, reads a fixed set of heavy pages twice, and reports startup time, the time of each
pass and resident memory (VmRSS, VmHWM). Not a CI test: it needs a real bench DB and takes minutes.
Usage: python3 tools/growth_bench.py BENCH.db [SCALES, default 1,2,5] [WORKDIR, default /tmp/growth]"""
import os, sys, json, time, shutil, sqlite3, subprocess, urllib.request
ROOT = os.environ.get("GROWTH_TREE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")   # GROWTH_TREE: run another checkout with this bench
SPAN = 600   # spacing of the added closes, seconds: short, so they stay inside the current segment (a later ts would cross a configured segment cut and make boot regroup every record)

def build(src, dst, k):
    for x in ("", "-wal", "-shm"):
        if os.path.exists(dst + x): os.remove(dst + x)
    shutil.copy(src, dst); c = sqlite3.connect(dst)
    for kind, raw in c.execute("SELECT kind, json FROM blobs WHERE kind='epochs' OR kind LIKE 'epochs:s%'").fetchall():
        v = json.loads(raw); n = len(v)
        if not n or k == 1: continue
        out = list(v); last = v[-1]
        for j in range(1, k):   # each copy: later epochs, later close times, its own answer ids (pending rows grow too)
            for e in v:
                e2 = dict(e, epoch=int(e["epoch"]) + j * n, ts=int(last["ts"]) + (int(e["epoch"]) - int(v[0]["epoch"]) + 1 + (j - 1) * n) * SPAN)
                b = dict(e.get("basis") or {}); p = b.get("pending")
                if isinstance(p, dict): b["pending"] = {a[:-2] + f"{j:02d}": r for a, r in p.items()}
                e2["basis"] = b; out.append(e2)
        c.execute("UPDATE blobs SET json=?, ts=ts+1 WHERE kind=?", (json.dumps(out), kind)); v = out = None
    if k > 1:   # Agents: k-1 more copies of every account and its txs, under new addresses and tx ids
        cols = [r[1] for r in c.execute("PRAGMA table_info(txs)")]
        for j in range(1, k):
            sfx = f"x{j}"
            c.execute(f"INSERT OR IGNORE INTO accounts SELECT addr||'{sfx}', invited_by||'{sfx}', balance, balance_s, api_ts, api_joined_epoch, first_seen, last_seen FROM accounts WHERE addr NOT LIKE '%x_'")
            sel = ", ".join({"id": f"id||'{sfx}'", "from_addr": f"from_addr||'{sfx}'", "to_addr": f"to_addr||'{sfx}'", "invited_by": f"invited_by||'{sfx}'"}.get(x, x) for x in cols)
            c.execute(f"INSERT OR IGNORE INTO txs ({', '.join(cols)}) SELECT {sel} FROM txs WHERE id NOT LIKE '%x_'")
    c.commit(); c.close()

def top_grader(db):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    r = c.execute("SELECT from_addr FROM txs WHERE type='grade-sealed' GROUP BY from_addr ORDER BY COUNT(*) DESC LIMIT 1").fetchone(); c.close()
    return r[0] if r else None

def proc(pid):
    out = {}
    for l in open(f"/proc/{pid}/status"):
        if l.startswith(("VmRSS", "VmHWM")): out[l.split(":")[0]] = int(l.split()[1]) // 1024
    return out

def run(db, port, urls):
    env = dict(os.environ, POASCAN_DB=db, PORT=str(port), HOST="127.0.0.1", POA_BASE="http://127.0.0.1:9", LOG_LEVEL="ERROR",
               MALLOC_ARENA_MAX="2", MALLOC_MMAP_THRESHOLD_="131072", MALLOC_TRIM_THRESHOLD_="131072")
    t0 = time.time(); p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(600):
            try: urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2); break
            except Exception: time.sleep(0.5)
        res = dict(start_s=round(time.time() - t0, 1), passes=[])
        for _ in range(2):
            t = time.time(); bad = 0
            for u in urls:
                try: urllib.request.urlopen(f"http://127.0.0.1:{port}{u}", timeout=300).read()
                except Exception: bad += 1
            res["passes"].append(dict(s=round(time.time() - t, 1), errors=bad, **proc(p.pid)))
        return res
    finally: p.terminate(); p.wait(30)

if __name__ == "__main__":
    src = sys.argv[1]; scales = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "1,2,5").split(",")]
    wd = sys.argv[3] if len(sys.argv) > 3 else "/tmp/growth"; os.makedirs(wd, exist_ok=True)
    for k in scales:
        db = os.path.join(wd, f"g{k}.db"); t = time.time(); build(src, db, k); bt = round(time.time() - t, 1)
        g = top_grader(db)
        urls = ["/", "/chain", "/chain?tab=pending", "/chain?tab=backlog", "/chain?tab=grading", "/governance?tab=charts", "/agents", "/agents/top",
                "/api/v1/epochs", "/api/v1/cohorts", "/api/v1/agents/calibration", "/api/grading", "/api/pending-by-epoch", "/api/v1/epoch-records"] + ([f"/address/{g}"] if g else [])
        r = run(db, 18950 + k, urls)
        print(json.dumps(dict(scale=k, build_s=bt, db_mb=os.path.getsize(db) // 2**20, **r)), flush=True)
