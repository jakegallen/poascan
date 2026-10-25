"""minepoa grading list (1.26.136): read schedule, backoff with Retry-After, one read per run and never per page view,
raw copies only before and after a close, seal changes, the compact copy, the Unconfirmed tag with established_source
and minepoa_established, the Health feed row and the /about notes.
Usage: python3 tools/grading_test.py (temp database, no network)."""
import os, sys, tempfile, time, json, gzip
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, grading as GR, indexer as I, analytics as A

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

G1, G2, T1 = "poa1" + "G" * 40, "poa1" + "H" * 40, "poa1" + "T" * 40
AU = "poa1" + "A" * 40
NOW = 1_800_000_000

def doc(epoch=4, last_roll=NOW - 3 * 3600, est=(), q2=False, extra_seal=True):
    ro = [dict(epoch=i, ts=last_roll - (3 - i) * 21600, settled=0, passed=0, expired=0, pending_after=0, eligible=0, established_after=0, paid=0, graders_served=0) for i in range(4)]
    g = [dict(g=T1, ts=NOW - 100, t=True, q=True), dict(g=G1, ts=NOW - 90, t=False, q=True)] + ([dict(g=G2, ts=NOW - 80, t=False, q=q2)] if extra_seal else [])
    rows = [dict(id="a" * 64, author=AU, born=1, since=1, expires=17, kind="short", raw=len(g), qual=sum(x["q"] for x in g), need=max(0, 4 - sum(x["q"] for x in g)), snippet="text " * 40, grades=g),
            dict(id="b" * 64, author=G1, born=2, since=2, expires=18, kind="short", raw=0, qual=0, need=4, snippet="x", grades=[])]
    return dict(as_of=NOW - 30, epoch=epoch, chain="poa-mainnet-1", quorum=4, ttl_epochs=16, trusted=[T1], established=list(est),
                stats=dict(pending=2, at_quorum=0, by_need={"2": 1, "4": 1}), rollups=ro, rows=rows, open=[], leaderboard=[dict(addr=G1, seals=1, qual=1, avg=None, trusted=False, established=False)],
                settled=[dict(id="c" * 64, author=AU, close=1, passed=True, expired=False, jury=[dict(g=G1, aligned=True, t=False, s=2, r="Concrete and correct.")])], gen_ms=1)

def main():
    db.init()
    # schedule
    check("cadence: 10 min far from a close", GR.cadence(NOW, NOW + 3 * 3600) == 600)
    check("cadence: 5 min within 30 min before a close", GR.cadence(NOW, NOW + 1200) == 300)
    check("cadence: 5 min within 30 min after a close", GR.cadence(NOW, NOW - 1200) == 300)
    check("cadence: never skips the window before a close", GR.cadence(NOW, NOW + 1800 + 200) == 205)
    check("backoff doubles from 10 to 30 min", [GR.backoff(n) for n in (1, 2, 3, 4)] == [600, 1200, 1800, 1800])
    check("Retry-After is a floor on the backoff", GR.backoff(1, 60) == 600 and GR.backoff(1, 3600) == 3600)
    ct, ep = GR.next_close(doc())
    check("next close: last rollup plus the median gap", ct == NOW - 3 * 3600 + 21600 and ep == 4)

    calls = []
    def get_ok(d):
        def g(): calls.append(1); return d
        return g
    # first read: far from a close (close in 3 h): stored, no raw copy
    check("first read stores", GR.job(now=NOW, get=get_ok(doc())) is True and len(calls) == 1)
    m = GR.meta()
    check("next read in about 10 min", 600 - 20 <= m["next_at"] - NOW <= 600 + 20)
    check("no raw copy far from a close", GR.raw_index() == [])
    check("a run before next_at makes no call", GR.job(now=NOW + 60, get=get_ok(doc())) is False and len(calls) == 1)
    cur = GR.current()
    check("compact copy drops snippets", all("snippet" not in r for r in cur["rows"]) and cur["fetched_at"] == NOW)
    n = db.q1("SELECT COUNT(*) AS n FROM grading_seals")["n"]
    check("seal store: one row per seal", n == 3)
    # backoff on a busy origin (503 with Retry-After 60)
    def busy(): calls.append(1); raise I.Busy("HTTP 503", 60)
    GR.job(now=NOW + 700, get=busy); m = GR.meta()
    check("a failed read backs off 10 min (Retry-After 60 is lower)", m["fails"] == 1 and m["next_at"] == NOW + 700 + 600)
    GR.job(now=NOW + 1300, get=busy); m = GR.meta()
    check("second failure: 20 min", m["fails"] == 2 and m["next_at"] == NOW + 1300 + 1200)
    check("the last good copy is kept through failures", GR.current() is not None and GR.current()["fetched_at"] == NOW)
    # a bad shape is a failure, not stored
    GR.job(now=NOW + 2600, get=get_ok({"error": "notice"})); m = GR.meta()
    check("an unexpected body is a failure and is not stored", m["fails"] == 3 and GR.current()["fetched_at"] == NOW)
    # inside the window before the close: pre copy; q flip and a seal gone
    pre_t = ct - 900
    GR.job(now=pre_t, get=get_ok(doc(q2=True, extra_seal=True)), force=True)
    ri = GR.raw_index()
    check("pre copy within 30 min of the close", [(r["epoch"], r["kind"]) for r in ri] == [(4, "pre")])
    body = db.q1("SELECT body FROM grading_raw")["body"]
    check("raw copy is the full gzipped list, snippets kept", "snippet" in gzip.decompress(body).decode())
    fl = db.q1("SELECT q, q_changed FROM grading_seals WHERE grader=?", (G2,))
    check("q flip stamped", fl["q"] == 1 and fl["q_changed"] == pre_t)
    check("next read 5 min inside the window", 300 - 20 <= GR.meta()["next_at"] - pre_t <= 300 + 20)
    # after the close: epoch 5, first read is the post copy; G2's seal left the list
    post = doc(epoch=5, last_roll=ct, extra_seal=False)
    GR.job(now=ct + 120, get=get_ok(post), force=True)
    kinds = sorted((r["epoch"], r["kind"]) for r in GR.raw_index())
    check("post copy on the first read after a close", kinds == [(4, "pre"), (5, "post")])
    gone = db.q1("SELECT gone FROM grading_seals WHERE grader=?", (G2,))["gone"]
    check("a seal no longer listed is marked gone, not deleted", gone == ct + 120)
    GR.job(now=ct + 600, get=get_ok(doc(epoch=5, last_roll=ct, extra_seal=True)), force=True)
    check("a seal listed again is no longer gone", db.q1("SELECT gone FROM grading_seals WHERE grader=?", (G2,))["gone"] is None)
    check("a later read in the same epoch adds no raw copy", len(GR.raw_index()) == 2)
    # 304
    GR.job(now=ct + 1200, get=lambda: None, force=True)
    check("304 keeps the copy and clears failures", GR.meta()["fails"] == 0 and GR.current() is not None)

    # established cross-check
    check("conflict when minepoa's list is empty", GR.established_check(G1)[:2] == ("conflict", False))
    check("hover detail names the empty list and quorum", GR.established_check(G1)[2] == "minepoa's grading list shows none; this Agent's seals still count toward quorum.")
    check("no q seals: hosted /me line instead", GR.established_check(AU)[2].endswith("hosted /me is the authority."))
    GR.job(now=ct + 1800, get=get_ok(doc(epoch=5, last_roll=ct, est=[G1])), force=True)
    check("on minepoa's list: minepoa_grading, no tag", GR.established_check(G1) == ("minepoa_grading", True, None) and GR.tag_html(None) == "")
    check("list not empty: detail says not on the list", GR.established_check(AU)[2].startswith("Not on minepoa's grading list"))
    t = GR.tag_html(GR.established_check(AU)[2])
    check("tag is the Unconfirmed flag with hover and tap detail", "Unconfirmed" in t and "<details" in t and "title=" in t)
    from poascan import segments as SG
    if SG.has_cut():
        with SG.use(SG.NUMBERS[0]): check("archived segment: close_records, no tag", GR.established_check(G1) == ("close_records", None, None))
    db.write("DELETE FROM blobs WHERE kind='grading'"); GR._cur.clear()
    check("no copy: close_records and null", GR.established_check(G1) == ("close_records", None, None) and GR.minepoa_established(G1) is None)
    GR.job(now=ct + 2400, get=get_ok(doc(epoch=5, last_roll=ct)), force=True)

    # wiring
    check("indexer allowlist takes the path", bool(I.ALLOWED.match(GR.PATH)))
    check("strain guard knows its shape", "/api/explorer/grading" in __import__("poascan.strain", fromlist=["x"]).REQUIRED)
    check("Health has a Grading list feed", any(f[0] == "Grading list" and GR.PATH in f[1] for f in A.FEEDS))
    check("freshness cadence on record", I.EVERY.get(GR.PATH) == 900)
    check("indexer job registered, no endpoint gate (its own schedule)", any(j[0] == "grading" and j[3] is None for j in I.JOBS))

    # page views and API never call minepoa.com
    def boom(*a, **k): raise AssertionError("upstream call from a page view")
    real = I.fetch; I.fetch = boom
    try:
        from poascan import governance as GV, views as V, standing as SD
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import fixture; fixture.seed(); A._cache.clear()
        for tab in ("overview", "established", "at-risk", "graders", "directory"): GV.page({"tab": [tab]})
        GV.api_overview(); GV.api_established(); GV.api_at_risk(); SD.standing(G1); GV.api_agent(G1)
        check("governance pages and API render from the stored copy only", True)
        ab = V.about() if hasattr(V, "about") else ""
    except AssertionError as e: check(str(e), False); ab = ""
    finally: I.fetch = real
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "views.py"), encoding="utf-8").read()
    check("/about: pending seals carry no verdict", "Pending seals carry no verdict." in src)
    check("/about: q is not documented and inferred", "q is not documented." in src and "inferred" in src)
    check("/about: avg is the mean jury score", "mean jury score" in src)
    ov = GV.api_overview()
    check("overview API has established_check", "established_check" in ov and ov["established_check"]["source"] in ("close_records", "minepoa_grading", "conflict"))
    st = SD.standing(G1)
    check("standing API has established_source and minepoa_established", "established_source" in st and "minepoa_established" in st)

if __name__ == "__main__":
    main()
    print(f"\n{len(fails)} failed" if fails else "\nall passed")
    sys.exit(1 if fails else 0)
