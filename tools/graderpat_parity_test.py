"""Old-vs-new parity for the streamed graderpat refactor (memory-peak fix). Embeds the PRE-refactor _patterns/timing
(full db.q fetchall + by_ans + per-row score lists) as a reference, seeds a rich randomized dataset across two segments,
closes spanning every range, varied jury sizes, settled and not-yet-scored seats, system graders, seals and answer txs,
then asserts the new streamed implementation produces identical patterns() aggregates, identical per-grader rows (keyed by
address, since rows are re-sorted downstream), identical timing, and byte-identical Graders-tab HTML / API / CSV across both
segments, all ranges and many min_n. Usage: python3 tools/graderpat_parity_test.py (temp database, no network)."""
import os, sys, tempfile, time, random, collections, statistics, json
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from poascan import db, analytics as A, segments as SG, gradehist as GH, graderpat as GP, grading as GR, server as SV

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)

NOW = int(time.time()); CUR = SG.CURRENT
GPOOL = ["poa1" + c * 40 for c in "ABCDEFGHIJKLMNO"]; SYSG = [GPOOL[13], GPOOL[14]]

# ----- reference implementation (verbatim pre-refactor logic), driven through the same module helpers -----
def ref_timing(rng="all"):
    GH._ensure(); GR._ensure(); seg = SG.selected(); cl = GP._closes_in(rng)
    seats = db.q("SELECT answer, grader, close FROM grade_history WHERE seg=?", (seg,))
    if cl is not None: seats = [r for r in seats if r["close"] in cl]
    if not seats: return dict(seals=0, median_hours=None, bands=[])
    sealt = {(r["answer"], r["grader"]): r["t"] for r in db.q("SELECT answer, grader, MIN(ts) AS t FROM grading_seals GROUP BY answer, grader")}
    want = list({r["answer"] for r in seats if (r["answer"], r["grader"]) in sealt})
    ats = {}
    for i in range(0, len(want), 500):
        ch = want[i:i + 500]
        for r in db.q(f"SELECT id, ts FROM txs WHERE id IN ({','.join('?' * len(ch))})", tuple(ch)): ats[r["id"]] = r["ts"]
    hrs = []
    for r in seats:
        t = sealt.get((r["answer"], r["grader"])); a = ats.get(r["answer"])
        if t and a and t >= a: hrs.append((t - a) / 3600)
    if len(hrs) < GP.TIMING_MIN: return dict(seals=len(hrs), median_hours=None, bands=[])
    out = []
    for i, (lo, lab) in enumerate(GP.TIMING_BANDS):
        hi = GP.TIMING_BANDS[i + 1][0] if i + 1 < len(GP.TIMING_BANDS) else float("inf")
        out.append(dict(band=lab, seals=sum(1 for h in hrs if lo <= h < hi)))
    return dict(seals=len(hrs), median_hours=round(statistics.median(hrs), 2), bands=out)

def ref_patterns(rng="all", min_n=GP.MIN_N):
    GH._ensure(); seg = SG.selected(); sc_on = GP.has_scores(seg)
    cl = GP._closes_in(rng)
    rs = db.q("SELECT answer, grader, close, aligned, score FROM grade_history WHERE seg=?", (seg,))
    if cl is not None: rs = [r for r in rs if r["close"] in cl]
    by_ans = collections.defaultdict(list)
    for r in rs: by_ans[r["answer"]].append(r)
    g = collections.defaultdict(lambda: dict(seats=0, aligned=0, peers=[], scores=[], dist=[], closes=set()))
    for ans, js in by_ans.items():
        for r in js:
            x = g[r["grader"]]; x["seats"] += 1; x["aligned"] += r["aligned"]; x["closes"].add(r["close"])
            oth = [o for o in js if o["grader"] != r["grader"]]
            if oth: x["peers"].append(sum(o["aligned"] for o in oth) / len(oth))
            if sc_on and r["score"] is not None:
                x["scores"].append(r["score"])
                os_ = [o["score"] for o in oth if o["score"] is not None]
                if os_: x["dist"].append(abs(r["score"] - statistics.fmean(os_)))
    sysg = GP.system_set(); nm = A.forum_names(); out = []
    for a, x in g.items():
        s = x["scores"]; hist = [s.count(k) for k in range(4)]
        top = max(range(4), key=lambda k: (hist[k], -k)) if s else None
        n_elig = len(s) if sc_on else x["seats"]
        row = dict(address=a, name=nm.get(a) or None, system=a in sysg, seats=x["seats"], aligned=x["aligned"],
                   agreement=round(x["aligned"] / x["seats"], 4) if x["seats"] else None,
                   peers=round(statistics.fmean(x["peers"]), 4) if x["peers"] else None, peer_seats=len(x["peers"]),
                   closes=len(x["closes"]), last_close=max(x["closes"]) if x["closes"] else None)
        if sc_on:
            row.update(scored=len(s), spread=round(statistics.stdev(s), 3) if len(s) > 1 else None,
                       top_score=top, top_share=round(hist[top] / len(s), 4) if s else None,
                       distance=round(statistics.fmean(x["dist"]), 3) if x["dist"] else None, mix={str(k): hist[k] for k in range(4)})
        row["below_min"] = n_elig < min_n
        out.append(row)
    pool = [r for r in out if not r["system"] and not r["below_min"]]
    keys = GP.PCT_KEYS if sc_on else ("agreement", "peers")
    vals = {k: sorted(r[k] for r in pool if r.get(k) is not None) for k in keys}
    for r in out:
        r["percentiles"] = None if (r["system"] or r["below_min"]) else {k: GP._pctile(vals[k], r.get(k)) for k in keys}
    med = lambda k: round(statistics.median(vals[k]), 4) if vals.get(k) else None
    mix = [sum(r["mix"][str(k)] for r in pool) for k in range(4)] if sc_on else None
    return dict(segment=seg, archived=SG.archived(), range=rng, min_n=min_n, scores=sc_on, graders=len(out), pool=len(pool),
                seats=sum(r["seats"] for r in out), hidden=sum(1 for r in out if r["below_min"]),
                median=dict({k: med(k) for k in keys}), score_mix=mix,
                bands=dict(agreement=GP._bands([r["agreement"] for r in pool if r["agreement"] is not None], GP.AG_BANDS),
                           spread=GP._bands([r["spread"] for r in pool if r.get("spread") is not None], GP.SD_BANDS) if sc_on else None),
                timing=ref_timing(rng), rows=out)

# ----- rich randomized dataset -----
def seed():
    random.seed(42); db.init(); GH._ensure(); GR._ensure()
    db.put_blob("params", {"auto_epoch_seconds": 21600, "trusted_graders": SYSG, "pending_merge_from_epoch": 0})
    # closes 1..8 across the ranges: 1-2 very old (all), 3-4 ~20d (30d), 5-6 ~5d (7d), 7-8 ~12h (24h)
    close_ts = {1: NOW - 60 * 86400, 2: NOW - 45 * 86400, 3: NOW - 20 * 86400, 4: NOW - 15 * 86400,
                5: NOW - 5 * 86400, 6: NOW - 4 * 86400, 7: NOW - 40000, 8: NOW - 20000}
    db.put_blob("epochs", [{"epoch": c, "ts": close_ts[c], "basis": {"settled": [], "pending": {}}} for c in range(1, 9)])
    db.put_blob("epochs:s1", [{"epoch": 9, "ts": NOW - 90 * 86400, "basis": {"settled": [], "pending": {}}}])
    rows = []; txs = []; seals = []
    # Segment CUR: 260 answers, jury 1..6, aligned/score random, some seats not yet scored (score None)
    for i in range(260):
        c = random.randint(1, 8)
        jury = random.sample(GPOOL, random.randint(1, 6))
        atx = f"a{i}"; t0 = close_ts[c] - random.randint(3600, 200000)
        txs.append((atx, "challenge", GPOOL[0], c, t0, 5, 5, 1))
        for j, gr in enumerate(jury):
            aligned = random.randint(0, 1)
            score = random.choice([0, 1, 2, 3, None]) if random.random() < 0.9 else None
            rows.append((CUR, atx, gr, c, aligned, 1, score))
            if random.random() < 0.7:   # most seats get a seal some hours after the answer tx
                seals.append((atx, gr, t0 + random.randint(1, 300000), 0, 1, NOW))
    # Segment 1: no scores at all (score None) -> exercises the Agreement/Peers-only path
    for i in range(80):
        jury = random.sample(GPOOL[:8], random.randint(1, 5))
        for gr in jury: rows.append((1, f"s{i}", gr, 9, random.randint(0, 1), 1, None))
    db.write("INSERT OR IGNORE INTO grade_history(seg, answer, grader, close, aligned, passed, score) VALUES(?,?,?,?,?,?,?)", rows, many=True)
    db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, epoch, ts, atts, k, final) VALUES(?,?,?,?,?,?,?,?)", txs, many=True)
    db.write("INSERT INTO grading_seals(answer, grader, ts, t, q, first_seen) VALUES(?,?,?,?,?,?)", seals, many=True)
    A._cache.clear()

seed()

def rows_by_addr(p): return {r["address"]: r for r in p["rows"]}
def same(a, b): return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)

RANGES = ["all", "24h", "7d", "30d"]; MINS = [0, 1, 5, 20, 37, 500, 1000]
orig = GP._patterns
for segid in (CUR, 1):
    with SG.use(segid):
        for rng in RANGES:
            for mn in MINS:
                A._cache.clear(); GP._odd.clear()
                new = orig(rng, mn)             # new streamed implementation (module default)
                ref = ref_patterns(rng, mn)     # pre-refactor reference
                agg_keys = ("segment", "archived", "range", "min_n", "scores", "graders", "pool", "seats", "hidden", "median", "score_mix", "bands", "timing")
                agg_ok = all(same(new[k], ref[k]) for k in agg_keys)
                rows_ok = same(rows_by_addr(new), rows_by_addr(ref))
                check(f"seg {segid} range {rng} min_n {mn}: aggregates + per-grader rows identical", agg_ok and rows_ok)

# byte-identical Graders-tab HTML, API JSON and CSV (monkeypatch _patterns to ref, render, restore, render, compare)
href = lambda **kw: "/governance?tab=graders" + ("&amp;" + "&amp;".join(f"{k}={v}" for k, v in kw.items() if v) if any(kw.values()) else "")
QS = [{}, {"prange": ["7d"]}, {"psort": ["spread"], "pdir": ["asc"]}, {"pn": ["all"]}, {"prange": ["30d"], "psort": ["agreement"]}]
for segid in (CUR, 1):
    with SG.use(segid):
        for qs in QS:
            GP._patterns = ref_patterns; A._cache.clear(); GP._odd.clear(); ref_html = GP.section(qs, href)
            GP._patterns = orig; A._cache.clear(); GP._odd.clear(); new_html = GP.section(qs, href)
            check(f"seg {segid} qs {qs}: Graders-tab HTML byte-identical", ref_html == new_html)
for args in ({}, {"min_n": ["0"], "sort": ["agreement"], "range": ["7d"]}, {"range": ["30d"], "min_n": ["5"]}):
    GP._patterns = ref_patterns; A._cache.clear(); GP._odd.clear(); rd = SV.governance_api("/api/governance/grader-patterns", args); rcsv = SV.to_csv(GP.csv_rows(rd["rows"]))
    GP._patterns = orig; A._cache.clear(); GP._odd.clear(); nd = SV.governance_api("/api/governance/grader-patterns", args); ncsv = SV.to_csv(GP.csv_rows(nd["rows"]))
    check(f"API JSON byte-identical {args}", json.dumps(rd, sort_keys=True, default=str) == json.dumps(nd, sort_keys=True, default=str))
    check(f"CSV byte-identical {args}", rcsv == ncsv)
GP._patterns = orig; A._cache.clear()
print("all passed" if not fails else f"{len(fails)} failed"); sys.exit(1 if fails else 0)
