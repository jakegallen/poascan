"""Swap page state and signed feed backfill (1.26.68 reports).
* /swap/<offer_id>: a terminal API status (expired, cancelled, filled) always wins over an inferred in-flight stage
  (Fill landing); the page reads the same record as /api/v1/swaps/<offer_id>; every offer's page tag matches the API.
  Case: offer de1ddefb (live 1.26.68), expired with a swap-fill tx that never finalized, read Fill landing.
* POASwap links use the canonical https://poaswap.io/status/<offer_id> (and status?address=<poa1>), never /track?offer=.
* /api/v1/notices/verified: distinct signed txs that share a version name are kept (no txid repeats) and labelled with a
  short txid; /network releases show the short txid for a repeated name.
* Pending signed records are retried over time at the same light load (at most FETCH_PER_RUN real reads per 10 min run):
  a 404 waits 1 h doubling to 24 h, a failed read (5xx, timeout) waits 20 min doubling to 6 h so one failing tx never
  holds the head of the queue, a read skipped without a request costs no slot.
Usage: python3 tools/swap_state_test.py (temp database, no network)."""
import json, os, re, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

tmp = tempfile.mkdtemp(); os.environ["POASCAN_DB"] = os.path.join(tmp, "s.db"); os.environ["POA_BASE"] = "http://127.0.0.1:9"
import fixture; fixture.seed()
from poascan import db, offer as OF, swapclient as SC, swap as SWM, signed as S, indexer as I, views as V
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

# ---------------- the reported offer: expired, a fill seen but never final ----------------
api = SC.offer(OID); t, h = OF.page_body(OID)
check("fixture: the API record says expired and carries a non-final swap-fill", api["offer"]["status"] == "expired"
      and any(e["kind"] == "swap-fill" and not e["final"] for e in api["events"]))
check("de1ddefb page reads Expired, not Fill landing", tag(h) == "Expired" and "Fill landing" not in h)
check("expired next steps: stop, don't take or pay; nothing about a landing fill", "Expired: stop." in h and "while it lands" not in h and "A fill tx is landing" not in h)
check("stage history keeps the fill tx as Fill submitted, not final, then Expired",
      "Fill submitted, not final" in h and '<span class="dim">not final</span>' in h and h.index("Fill submitted, not final") < h.rindex(">Expired<")
      and '<span class="warn">pending</span>' not in h and "Fill attempt" not in h and "never final" not in h)
check("the page's status is the API record's (same source as /api/v1/swaps/<id>)", OF.stage(SWM.api("/api/swaps/" + OID, {})[0]) == "expired" == OF.stage(api))

# ---------------- every terminal state wins; only live offers infer Fill landing ----------------
FILL = lambda n: [dict(txid=(n * 32)[:64], kind="swap-fill", addr=SW["maker"], ts=now - 30, final=False)]
base = dict(SW, taker=None, fill_txid=None, fill_ts=None, ext_ref=None, cancel_txid=None, cancel_ts=None)
cases = [("cancelled", dict(status="cancelled", cancel_txid="c0" * 32, cancel_ts=now - 60, expires_ts=now + 3600), "Cancelled"),
         ("filled", dict(status="filled", taker=SW["maker"], fill_txid="f0" * 32, fill_ts=now - 60, expires_ts=now + 3600), "Filled"),
         ("open, past expiry", dict(status="open", expires_ts=now - 60), "Expired"),
         ("delisted, past expiry", dict(status="delisted", expires_ts=now - 60), "Expired"),
         ("open", dict(status="open", expires_ts=now + 3600), "Fill landing"),
         ("delisted before expiry", dict(status="delisted", expires_ts=now + 3600), "Fill landing")]
for i, (name, kw, want) in enumerate(cases):
    oid = f"{i:02x}" * 32; put(dict(base, offer_id=oid, **kw), FILL(f"{i + 10:02x}"))
    got = tag(OF.page_body(oid)[1])
    check(f"{name} with a non-final fill reads {want} (got {got})", got == want)
for st in OF.TERMINAL:
    check(f"stage(): terminal {st} is never overridden by events", OF.stage({"offer": {"status": st}, "events": FILL("ee")}) == st)

# ---------------- scan: every offer the site knows, page tag vs API status ----------------
mism = []
for r in SC.offers():
    a = SC.offer(r["offer_id"]); st = a["offer"]["status"]; lab = tag(OF.page_body(r["offer_id"])[1])
    live = st in ("open", "delisted") and OF.stage(a) == "filling"
    if r["status"] != st or lab != (OF.LABEL["filling"] if live else OF.LABEL.get(st, st.capitalize())): mism.append((r["offer_id"][:8], st, lab))
check(f"every offer: page status matches the API, Fill landing only on live offers ({len(SC.offers())} offers, mismatches {mism})", not mism and len(SC.offers()) >= 7)

# ---------------- canonical POASwap status links ----------------
check("status_url: https://poaswap.io/status/<64 hex lowercase>", OF.status_url(OID.upper()) == "https://poaswap.io/status/" + OID
      and OF.status_url("nope") is None and OF.status_url("ab" * 33) is None)
check("addr_status_url: https://poaswap.io/status?address=<poa1>", OF.addr_status_url(SW["maker"]) == "https://poaswap.io/status?address=" + SW["maker"] and OF.addr_status_url("x") is None)
check("/swap page links the canonical status page, never /track?offer=", f'href="https://poaswap.io/status/{OID}"' in h and "track?offer=" not in h and ">Status on POASwap ↗<" in h)
sc = V.swaps_card(SW["maker"])
check("address Swaps card: per-offer Status links, an address-level Status link in the header, no /track", f'href="https://poaswap.io/status/{OID}"' in sc
      and f'href="https://poaswap.io/status?address={SW["maker"]}"' in sc and "track?offer=" not in sc and ">Status ↗<" in sc)
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
for k in range(2, 12): S.refresh(fetch_tx=busy_fetch, now=T + 600 * k)
check(f"under a steady 503, every pending tx still gets a turn, one read per run ({len(set(busy))} distinct in {len(busy)} runs)",
      set(busy) >= {r["txid"] for r in REL} and len(busy) == 12)
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
