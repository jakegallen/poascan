"""Swap API state and signed feed backfill (1.26.68 reports).
* /api/v1/swaps/<offer_id> keeps its terminal status (case: offer de1ddefb, expired with a swap-fill tx that never
  finalized). The /swap page moved to POASwap. No /track?offer= link anywhere.
* /api/v1/notices/verified: distinct signed txs that share a version name are kept (no txid repeats) and labelled with a
  short txid; /network releases show the short txid for a repeated name.
* Pending signed records are retried over time at the same light load (at most FETCH_PER_RUN real reads per 10 min run):
  a 404 waits 1 h doubling to 24 h, a failed read (5xx, timeout) waits 20 min doubling to 6 h so one failing tx never
  holds the head of the queue, a read skipped without a request costs no slot.
Usage: python3 tools/swap_state_test.py (temp database, no network)."""
import json, os, re, sys, tempfile, time
os.environ["POASCAN_SWAP_EVIDENCE"] = ""   # ledger-only states: no balance evidence applied
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "s.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import db, swapclient as SC, swap as SWM, signed as S, indexer as I, views as V
def no_upstream(*a, **k): raise AssertionError("upstream read")
I.fetch = no_upstream

FX = json.load(open(os.path.join(HERE, "swap_expired_fixture.json"))); SW = FX["swap"]; OID = SW["offer_id"]
now = int(time.time())
def put(o, events=()):
    cols = ",".join(o); db.write(f"INSERT OR REPLACE INTO swaps({cols}) VALUES({','.join('?' * len(o))})", tuple(o.values()))
    for e in events:
        db.write("INSERT OR REPLACE INTO swap_events(txid, offer_id, kind, addr, ts, json, final, checked, dropped, first_seen) VALUES(?,?,?,?,?,?,?,?,0,?)",
                 (e["txid"], o["offer_id"], e["kind"], e["addr"], e["ts"], "{}", 1 if e["final"] else 0, e["ts"] if e["final"] else None, e["ts"]))
def tag(h):
    m = re.search(r'<span>Status</span><div><span class="tag[^"]*">([^<]+)</span>', h); return m.group(1) if m else None
put(SW, FX["events"])

# ---------------- the reported offer: the API record wins (the /swap page moved to POASwap) ----------------
api = SC.offer(OID)
check("fixture: the API record says expired and carries a non-final swap-fill", api["offer"]["status"] == "expired"
      and any(e["kind"] == "swap-fill" and not e["final"] for e in api["events"]))
check("the module API serves the same expired record", SWM.api("/api/swaps/" + OID, {})[0]["offer"]["status"] == "expired")
src = "".join(open(os.path.join(ROOT, d, f), encoding="utf-8").read() for d in ("poascan", "static") for f in os.listdir(os.path.join(ROOT, d)) if f.endswith((".py", ".txt", ".js", ".json", ".html")))
check("no /track?offer= link left in the code or static docs", "track?offer=" not in src)

# ---------------- signed feed: same version name, distinct txs ----------------
S.time.sleep = lambda s: None
REL = [{"version": "v1.8.1-hostedrelief", "ts": 1792566385, "txid": "f8" * 32}, {"version": "v1.8.1-hostedrelief", "ts": 1792566972, "txid": "07" * 32},
       {"version": "v1.8.1-hostedrelief", "ts": 1792567062, "txid": "d3" * 32}, {"version": "v1.9-credmap", "ts": 1792570390, "txid": "11" * 32},
       {"version": "v1.9-credmap", "ts": 1792571874, "txid": "78" * 32}, {"version": "v1.10-guardfix", "ts": 1792590000, "txid": "ac" * 32}]
db.put_blob("notices", {"active": []}); db.put_blob("release", {"current": dict(REL[-1]), "history": REL})
reads = []
def missing(t): reads.append(t); raise I.Missing("not found")
S.refresh(fetch_tx=missing, now=1792800000)
f = S.feed(); rows = [r for r in f["records"] if r["kind"] == "release"]
tx = [r["txid"] for r in rows]
check(f"feed: all {len(REL)} release txs kept, no txid twice", len(rows) == len(REL) and len(set(tx)) == len(tx))
lab = {r["txid"]: r for r in rows}
check("feed: a repeated name carries same_id_count and a short-txid label; a unique name keeps its plain id",
      lab["07" * 32]["same_id_count"] == 3 and lab["07" * 32]["label"] == "v1.8.1-hostedrelief · 07070707" and lab["11" * 32]["same_id_count"] == 2
      and lab["ac" * 32]["same_id_count"] == 1 and lab["ac" * 32]["label"] == "v1.10-guardfix" and lab["07" * 32]["txid_short"] == "07070707")
check("feed: backfill summary counts pending records", f["backfill"]["pending"] == sum(1 for r in f["records"] if r["status"] == "pending" and r["txid"]) >= len(REL) and f["backfill"]["per_run"] == S.FETCH_PER_RUN <= 2 and f["backfill"]["run_every_s"] == 600)
db.put_blob("status", db.get_blob("status")[0] or {})
h = V.network_overview("")
h = h[1] if isinstance(h, tuple) else h
check("/network releases: repeated names show a short txid linking the tx; a unique name shows none",
      all(f'href="/tx/{t}"' in h and f">{t[:8]}</a>" in h for t in ("f8" * 32, "07" * 32, "d3" * 32, "11" * 32, "78" * 32)) and f'>{"ac" * 4}</a>' not in h)

# ---------------- backfill: retries over time, light load ----------------
check(f"first run made at most FETCH_PER_RUN reads ({len(reads)})", 1 <= len(reads) <= S.FETCH_PER_RUN)
recs = db.get_blob(S.BLOB)[0]["records"]
check("a 404 waits 1 h", all(recs[t]["next_try"] == 1792800000 + 3600 for t in reads))
T = 1792800000
for k in range(1, 13): S.refresh(fetch_tx=missing, now=T + 600 * k)
check(f"every pending release tx tried within 2 h at <= 2 per run ({len(set(reads))} distinct, {len(REL)} releases, {len(reads)} reads in 13 runs)",
      set(reads) >= {r["txid"] for r in REL} and len(reads) <= 13 * S.FETCH_PER_RUN)
n = len(reads); S.refresh(fetch_tx=missing, now=T + 600 * 13 + 1)
recs = db.get_blob(S.BLOB)[0]["records"]
check("retries keep going after their wait (tries grow, waits double)", max(r.get("tries", 0) for r in recs.values() if r.get("kind") == "release") >= 2)
# a failed read (5xx): record backoff so the next run reads a different tx; the run still stops at the failure
db.put_blob(S.BLOB, {}); busy = []
def busy_fetch(t): busy.append(t); raise I.Busy("HTTP 503", 60)
S.refresh(fetch_tx=busy_fetch, now=T)
check("a 503 ends the run after one read", len(busy) == 1)
first = busy[0]; r0 = db.get_blob(S.BLOB)[0]["records"][first]
check("the failed tx waits 20 min (fails 1), then 40 min", r0["fails"] == 1 and r0["next_try"] == T + 1200)
S.refresh(fetch_tx=busy_fetch, now=T + 600)
check("next run reads a different pending tx, not the one that just failed", len(busy) == 2 and busy[1] != first)
NP = len({t for _k, t, _x in S.wanted() if t})   # every tx POAScan checks (releases, notices, milestone txs): grows with milestones.json
for k in range(2, NP): S.refresh(fetch_tx=busy_fetch, now=T + 600 * k)
check(f"under a steady 503, every pending tx still gets a turn, one read per run ({len(set(busy))} distinct in {len(busy)} runs)",
      set(busy) >= {r["txid"] for r in REL} and len(busy) == NP and len(set(busy)) == NP)
# reads skipped without a request cost no slot and no try
db.put_blob(S.BLOB, {}); seen = []
def skip(t): seen.append(t); raise I.Busy("backing off")
S.refresh(fetch_tx=skip, now=T)
r1 = db.get_blob(S.BLOB)[0]["records"][seen[0]]
check("endpoint backing off: no try or wait recorded (the shared backoff decides)", len(seen) == 1 and not r1.get("fails") and not r1.get("tries") and not r1.get("next_try"))
db.put_blob(S.BLOB, {}); seen.clear(); got = []
def cached(t): seen.append(t); raise I.Missing("not found (cached)")
def ok_then(t): got.append(t); raise I.Missing("not found")
S.refresh(fetch_tx=cached, now=T)
check(f"negative-cached ids cost no read slot (all {len(REL)} looked at in one run, none counted as a try)", len(seen) >= len(REL)
      and not any(r.get("tries") for r in db.get_blob(S.BLOB)[0]["records"].values()))
S.refresh(fetch_tx=ok_then, now=T + 3600)
check("after the 1 h look-again, real reads resume at <= FETCH_PER_RUN", 1 <= len(got) <= S.FETCH_PER_RUN)

print("\n" + ("FAILED: " + str(len(fails)) if fails else "all ok"))
sys.exit(1 if fails else 0)
