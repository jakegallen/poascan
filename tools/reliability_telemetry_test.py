"""Reliability telemetry (read-only diagnostics): memory-guard counters, process start/restart count, and per-warm-path
render health with POAScan's own render latency kept apart from the upstream minepoa probe p50/p95 on /api/status.
Nothing here makes an upstream call or changes gating. Usage: python3 tools/reliability_telemetry_test.py"""
import os, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["POASCAN_INDEXER"] = "0"
os.environ["POASCAN_HTML_CACHE"] = "1"   # warm telemetry is exercised with the cache on
os.environ["POA_BASE"] = "http://127.0.0.1:9"

fails = []
def check(n, c):
    print(("ok   " if c else "FAIL ") + n); c or fails.append(n)

from poascan import db, htmlcache as HC, guard as GD, server as SV
db.init()

# ---- warm-set per-path telemetry ----
renders = []
def fake_render(p, qs):
    renders.append(p); return f"<html>{p}:{sorted(qs)}</html>"
HC.warm_once(fake_render, lambda: None, force=True)
check("warm pass rendered every WARM path", len(set(renders)) >= len({u.partition('?')[0] for u in HC.WARM}))
st = HC.state()
check("state carries warm_paths and warm_total_paths", isinstance(st.get("warm_paths"), dict) and st.get("warm_total_paths") == len(HC.WARM))
check("every WARM url has a record with ok>=1, a last render ms and a last-warm-age",
      all(u in st["warm_paths"] and st["warm_paths"][u]["ok"] >= 1 and isinstance(st["warm_paths"][u]["last_ms"], int)
          and isinstance(st["warm_paths"][u]["last_warm_age_s"], int) for u in HC.WARM))
check("self_render_ms carries p50, p95 and a sample count (POAScan's own render latency)",
      set(st["self_render_ms"]) == {"p50", "p95", "n"} and st["self_render_ms"]["n"] >= len(HC.WARM)
      and st["self_render_ms"]["p50"] is not None)

# a failing render is counted as a warm failure, not a success
def boom_render(p, qs):
    if p == "/help": raise RuntimeError("render failed")
    return f"<html>{p}</html>"
HC.warm_paths.clear(); HC._warm_ms.clear(); HC.stats["warm"] = 0
HC.warm_once(boom_render, lambda: None, force=True)
check("a render that raises records a warm failure and no success for that path",
      HC.warm_paths["/help"]["fail"] >= 1 and HC.warm_paths["/help"]["ok"] == 0 and HC.warm_paths["/"]["ok"] >= 1)

# ---- memory-guard telemetry ----
g = GD.telemetry()
check("guard telemetry exposes trim/gc/rss counters and the self-check fails",
      {"trims", "gcs", "rss_mb", "rss_exit_mb", "rss_over", "self_check_fails", "throttled_fails"} <= set(g)
      and isinstance(g["trims"], int) and isinstance(g["gcs"], int) and isinstance(g["rss_over"], int))
before = GD.state["trims"]; GD.trim(full=False)
check("a trim bumps the trim counter", GD.telemetry()["trims"] == before + 1)

# ---- process start/restart counter (persisted) ----
check("restart counter starts null before a boot records it", SV.STARTS["count"] is None)
SV._record_start(); SV._record_start()
check("two recorded boots count to 2 and keep the first_at", SV.STARTS["count"] == 2 and SV.STARTS["first_at"] is not None)
check("the count is persisted in the proc_starts blob", (db.get_blob("proc_starts")[0] or {}).get("count") == 2)

# ---- surfaced on /api/status, kept apart from the upstream probe latency ----
d = SV.api("/api/status", {})[0]
diag = d.get("diagnostics") or {}
check("/api/status carries a diagnostics block with restarts, mem_guard and page_cache",
      {"restarts", "mem_guard", "page_cache", "note"} <= set(diag))
check("diagnostics.restarts and mem_guard match the live telemetry",
      diag["restarts"]["count"] == 2 and "trims" in diag["mem_guard"] and "self_render_ms" in diag["page_cache"])
check("upstream probe latency (endpoints[].p50/p95) stays separate from POAScan's own self_render_ms",
      "endpoints" in d and all("p50" in e and "p95" in e for e in d["endpoints"]) and "self_render_ms" in diag["page_cache"]
      and "self_render_ms" not in str(d["endpoints"]))

print(f"\n{len(fails)} failed" if fails else "\nall ok"); sys.exit(1 if fails else 0)
