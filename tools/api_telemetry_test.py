"""In-process API telemetry (6a): the bounded ring (poascan/apitel.py) and the /api/telemetry route.
Checks: route templates collapse addresses, hashes and numbers (no raw path kept); surfaces classify
rest / mcp / csv; HTML and asset paths are not counted; the ring stays bounded; snapshot math (success
rate, p50, top endpoints) is correct; and the live /api/telemetry route serves JSON and counts itself.
Usage: python3 tools/api_telemetry_test.py"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import apitel as APT

FAILS = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or FAILS.append(name)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def req(url):
    r = urllib.request.urlopen(url, timeout=20)
    return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Content-Type", "")

def unit():
    # template: addresses, hashes and ids never survive as keys
    check("template collapses a poa1 address to {addr}",
          APT.template("/api/v1/address/poa19xk7qmfexample8z/txs") == "/api/v1/address/{addr}/txs")
    check("template collapses a long hex hash to {hash}",
          APT.template("/api/v1/tx/" + "a" * 40) == "/api/v1/tx/{hash}")
    check("template collapses an epoch number to {n}",
          APT.template("/api/v1/epoch/2851/record") == "/api/v1/epoch/{n}/record")
    check("template drops the query string", APT.template("/api/v1/txs?limit=50&offset=0") == "/api/v1/txs")

    # surface classification, only API surfaces counted
    APT._mins.clear()
    APT.record("/api/v1/txs", 200, 12.0, "application/json")       # rest
    APT.record("/mcp", 200, 5.0, "application/json")               # mcp
    APT.record("/api/v1/txs?format=csv", 200, 9.0, "text/csv")     # csv
    APT.record("/about", 200, 3.0, "text/html")                    # not an API surface, not counted
    APT.record("/static/apiref.js", 200, 1.0, "application/javascript")  # asset, not counted
    s = APT.snapshot(60)
    check("only API surfaces are counted (HTML + assets ignored)", s["requests"] == 3)
    check("surfaces split rest / mcp / csv", s["by_surface"] == {"rest": 1, "mcp": 1, "csv": 1})

    # success rate and latency percentile
    APT._mins.clear()
    for _ in range(9): APT.record("/api/v1/health", 200, 10.0)
    APT.record("/api/v1/health", 500, 100.0)
    s = APT.snapshot(60)
    check("success_rate counts 2xx/3xx only", s["success_rate"] == 0.9)
    check("p50 is a real sample from the window", s["p50_ms"] == 10.0)
    check("a 5xx is still a request", s["requests"] == 10)

    # top endpoints by template
    APT._mins.clear()
    for _ in range(5): APT.record("/api/v1/txs", 200, 1.0)
    for _ in range(2): APT.record("/api/v1/epoch/7/record", 200, 1.0)
    s = APT.snapshot(60)
    top = s["top_endpoints"]
    check("top_endpoints ranks the busiest template first",
          top and top[0]["endpoint"] == "/api/v1/txs" and top[0]["count"] == 5)
    check("concrete ids never appear in top_endpoints (epoch 7 collapsed to {n})",
          any(t["endpoint"] == "/api/v1/epoch/{n}/record" for t in top)
          and not any("/epoch/7/" in t["endpoint"] for t in top))

    # bounded: template cap holds and recording never raises on junk
    APT._mins.clear()
    for i in range(APT.MAX_TMPL + 50): APT.record(f"/api/v1/x{i}", 200, 1.0)
    bucket = next(iter(APT._mins.values()))
    check("template count per bucket is capped (bounded memory)", len(bucket["tmpl"]) <= APT.MAX_TMPL)
    check("latency samples per bucket are capped", len(bucket["lat"]) <= APT.LAT_CAP)
    APT.record(None, None, None, None)   # must not raise
    check("record swallows bad input without raising", True)
    APT._mins.clear()

def live():
    port = free_port(); base = f"http://127.0.0.1:{port}"; tmp = tempfile.mkdtemp()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "t.db"),
               POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env)
    try:
        for _ in range(50):
            try: req(base + "/api/health"); break
            except Exception: time.sleep(0.2)
        # drive a few API reads, then read telemetry (both /api and the /api/v1 alias)
        for _ in range(3):
            try: req(base + "/api/v1/health")
            except Exception: pass
        c, b, ct = req(base + "/api/telemetry?minutes=60")
        j = json.loads(b)
        check("/api/telemetry serves JSON (200)", c == 200 and "json" in ct)
        check("telemetry reports the window and a request count", j.get("window_minutes") == 60 and j.get("requests", 0) >= 1)
        check("telemetry counts the rest surface", j.get("by_surface", {}).get("rest", 0) >= 1)
        check("telemetry keeps only route templates (no raw address/hash in top_endpoints)",
              all("poa1" not in t["endpoint"] for t in j.get("top_endpoints", [])))
        c2, b2, _ = req(base + "/api/v1/telemetry?minutes=5")
        check("/api/v1/telemetry alias resolves to the same route", c2 == 200 and json.loads(b2).get("window_minutes") == 5)

        # 6b: stored samples
        c3, b3, ct3 = req(base + "/api/v1/reference/samples")
        j3 = json.loads(b3)
        check("/api/v1/reference/samples serves JSON (200)", c3 == 200 and "json" in ct3)
        check("samples carries a per-endpoint list with a ttl and generated_ts",
              isinstance(j3.get("samples"), list) and j3.get("count") == len(j3["samples"]) and j3.get("ttl") == 3600 and j3.get("generated_ts"))
        check("every sample names a public /api/v1 endpoint and a status",
              all(s.get("endpoint", "").startswith("/api/v1/") and "status" in s for s in j3["samples"]))
        check("samples includes the cheap cached endpoints (health, summary)",
              any(s["endpoint"].startswith("/api/v1/health") for s in j3["samples"])
              and any(s["endpoint"].startswith("/api/v1/summary") for s in j3["samples"]))
        c4, b4, _ = req(base + "/api/v1/reference/samples")
        check("samples is cached (same generated_ts on a second read within the hour)",
              json.loads(b4).get("generated_ts") == j3.get("generated_ts"))
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
