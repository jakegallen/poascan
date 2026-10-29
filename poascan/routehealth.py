"""1.26.220: per-route health for /api/health, Network > Health and the header status (one rule for all three).

Six routes: mining, grading, assignments, tx lookup, swaps and anchors, each ok, degraded or down, from data POAScan
already holds (routewatch.py probes, the feed rows, the swap write check): no new upstream read.

Core routes are mining and grading. Proof of Agent exists to pay Agents for answers that are graded: an Agent can earn
only while answers can be submitted (mining) and settled (grading). When either is not ok, the network is not doing its
job and health says Partial (HTTP 503). The other four only change how POAScan reads or how an Agent acts: tx lookup and
anchors have indexed copies, assignments and swaps are optional to earning. One of them not ok is listed in degraded on
its own line and never flips the headline."""
import time

CORE = ("mining", "grading")
CORE_BASIS = ("Mining and grading: an Agent earns only while answers can be submitted and settled. "
              "Tx lookup, assignments, swaps and anchors are listed on their own lines and do not change the headline.")
LABELS = {"mining": "Mining", "grading": "Grading", "assignments": "Assignments", "tx_lookup": "Tx lookup", "swaps": "Swaps", "anchors": "Anchors"}
RW_MAP = {"mining": "hosted_mining", "grading": "grading", "assignments": "assignments", "tx_lookup": "tx_lookup"}
FEED_WORD = {"OK": "ok", "Degraded": "degraded", "Down": "down"}

def _row(rid, state, detail, as_of=None, served_by=None):
    return dict(id=rid, label=LABELS[rid], state=state, core=rid in CORE, detail=detail, as_of=as_of, served_by=served_by)

def routes(feed_rows, now=None):
    """[route dict] in LABELS order. feed_rows: analytics.feeds() rows (label, state)."""
    now = now or time.time(); out = []
    fr = {f["label"]: f for f in feed_rows or []}
    try:
        from . import routewatch as RW
        rw = {r["id"]: r for r in RW.state(now)["routes"]}
    except Exception: rw = {}
    try:
        from . import maint as M
        up = bool(M.state()["active"])
    except Exception: up = False
    for rid in ("mining", "grading", "assignments", "tx_lookup"):
        r = rw.get(RW_MAP[rid]) or {}; st = r.get("state") or "unknown"; ao = r.get("as_of")
        if rid == "mining" and up: out.append(_row(rid, "down", "Network maintenance: hosted mining paused", ao)); continue
        if st == "open":
            out.append(_row(rid, "degraded" if r.get("stale") else "ok", r.get("stale_reason") or "Open", ao))
        elif st in ("halted", "down"):
            cov = r.get("covered_by")
            w = "halted" if st == "halted" else "down"
            out.append(_row(rid, "degraded" if cov else "down", f"minepoa.com route {w}" + (f"; reads served from the {cov}" if cov else ""), ao, cov))
        else: out.append(_row(rid, "unknown", "No read yet", ao))   # no probe read at all (a fresh database): never counted either way
    sw = FEED_WORD.get((fr.get("Swaps") or {}).get("state"), "down") if "Swaps" in fr else "degraded"
    ww = FEED_WORD.get((fr.get("Swap writes") or {}).get("state")) if "Swap writes" in fr else None
    if sw == "ok" and ww in (None, "ok"): out.append(_row("swaps", "ok", "Reads and writes OK"))
    elif sw == "ok": out.append(_row("swaps", "degraded", f"Swap reads OK, swap writes {ww}"))
    else: out.append(_row("swaps", sw, f"Swap reads {sw}" + (f", swap writes {ww}" if ww else "")))
    an = fr.get("Anchors")
    out.append(_row("anchors", FEED_WORD.get(an["state"], "down") if an else "degraded", "Anchor list " + (an["state"].lower() if an else "not read yet"),
                    _iso(an.get("last_ok")) if an else None))
    return out

def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts))) if ts else None

def headline(chain, rts, feed_rows):
    """(state, ok, core_not_ok [labels], degraded [labels]). Degraded when the chain is not live; Partial when a core
    route is not ok; OK otherwise. degraded lists every other route and feed that is not ok, each on its own."""
    core_bad = [r["label"] for r in rts if r["core"] and r["state"] in ("degraded", "down")]
    deg = [r["label"] for r in rts if not r["core"] and r["state"] in ("degraded", "down")]
    covered = {"Tx lookup", "Swaps", "Swap writes", "Anchors"}
    deg += [f["label"] for f in feed_rows if f["state"] != "OK" and f["label"] not in covered and f["label"] not in deg]
    state = "Degraded" if chain != "Live" else "Partial" if core_bad else "OK"
    return state, state == "OK", core_bad, deg
