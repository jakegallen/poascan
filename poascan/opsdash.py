"""Private aggregate stats feed for the POAScan tab of POASwap's dashboard (GET /ops/dashboard, Bearer POASCAN_STATS_TOKEN,
else the normal 404). One call answers every section the dashboard draws, built from the other private feeds and the
local archive: visits (poascan/visits.py), the signup funnel (poascan/checkin.py), the hosted route check and upstream
counters (poascan/opsinternal.py, poascan/indexer.py) and the daily network rollup (poascan/network.py).

Read only from POAScan's own database and memory: nothing here calls minepoa.com. Aggregates only: no key, IP, user
agent, query string, tx id or address leaves this module; addresses are only ever counted. Responses are cached per
(from, to) in memory: fresh for CACHE_TTL seconds, then served stale (up to STALE_MAX) while one background rebuild
runs, so a request never waits on a build once a copy exists. A timer (start()) prebuilds the default 7 and 31 day
ranges and every range read in the last hour, every CACHE_TTL seconds (1.26.82: cold builds took 20 to 37 s under CPU
throttling and once ran past POASwap's timeout).

Sections: traffic, onchain, offchain, service, wallets (always null: POAScan does not create wallets), definitions,
not_measurable. UTC days; times are unix seconds; rates are 0..1 with 4 decimals, null when the base is 0."""
import collections, datetime as dt, json, threading, time
from . import db, visits as VS, checkin as CK, opsinternal as OI, network as NW

CACHE_TTL, CACHE_MAX = 300, 8
STALE_MAX = 1800           # a copy older than this is rebuilt inline
WARM_KEEP = 3600           # ranges read within this long are prebuilt by the timer
TOP_N = 10                 # top pages, referrers, API routes listed by name; the rest fold into 'other'
COUNTRY_N = 20
RETENTION_DAYS = (1, 7, 30)
ROUTE_STEPS = CK.ROUTES

_lock = threading.Lock()
_cache = collections.OrderedDict()

def _rate(a, b): return round(a / b, 4) if b else None
def _dn(s): return (dt.date.fromisoformat(s) - dt.date(1970, 1, 1)).days
def _pct(xs, p): return OI._pct(xs, p)

def _top(m, n):
    items = sorted(((k, v) for k, v in m.items() if k != "other"), key=lambda kv: (-kv[1], kv[0]))
    out = dict(items[:n]); rest = sum(v for _, v in items[n:]) + m.get("other", 0)
    if rest: out["other"] = rest
    return out

def _add(dst, src):
    for k, v in (src or {}).items(): dst[k] = dst.get(k, 0) + v

# ---- traffic
def traffic(vs):
    days, pages, refs, dev, cty, api, mcp, pr = [], {}, {}, {}, {}, {}, {}, {}
    tot = dict(human=0, bot=0, agent=0)
    for d in vs["days"]:
        v = {k: sum((g.get(k) or 0) for g in d["views"].values()) for k in VS.KINDS}
        for g, kv in d["views"].items():
            p = pages.setdefault(g, dict(human=0, bot=0, agent=0))
            for k in VS.KINDS: p[k] += kv.get(k) or 0
        for k in VS.KINDS: tot[k] += v[k]
        _add(refs, d["referrers"]); _add(dev, d["devices"]); _add(cty, d["countries"]); _add(api, d["api"]); _add(mcp, d["mcp"]); _add(pr, d["prompts"])
        days.append(dict(day=d["day"], uniques=d["uniques"], views=v, api_calls=sum(d["api"].values()), mcp_calls=sum(d["mcp"].values()),
                         prompt_clicks=sum(d["prompts"].values())))
    tp = sorted(pages.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    top_pages = dict(tp[:TOP_N])
    if tp[TOP_N:]:
        o = dict(human=0, bot=0, agent=0)
        for _, kv in tp[TOP_N:]:
            for k in VS.KINDS: o[k] += kv[k]
        top_pages["other"] = o
    return dict(totals=dict(uniques_sum=sum(d["uniques"] for d in days), views=tot, api_calls=sum(api.values()), mcp_calls=sum(mcp.values()),
                            prompt_clicks=sum(pr.values())),
                days=days, top_pages=top_pages, referrers=_top(refs, TOP_N), devices=_top(dev, 99), countries=_top(cty, COUNTRY_N),
                country_source=vs.get("country_source"), api_routes=_top(api, TOP_N), mcp_tools=_top(mcp, 99), prompt_buttons=_top(pr, 99))

# ---- onchain
def _cohort(lo, hi, now):
    """Matched POAScan check-ins whose on-chain join falls in [lo, hi): [(version, client, join ts, check-in ts)]. The
    addresses stay inside this function; only counts and times leave it."""
    out = []
    for a in db.q("SELECT addr, version, client, ts FROM checkin_addrs WHERE ts >= ? AND ts < ? ORDER BY ts", (lo - CK.SKEW_S, hi + CK.WINDOW_S)):
        st, jt = CK.match(a["addr"], a["ts"])
        if st == "joined" and lo <= jt < hi: out.append((a["addr"], a["version"], a["client"], int(jt), int(a["ts"])))
    return out

# Which network fields are sums over the requested range and which are one point in time (1.26.82: POASwap labelled
# txs_total 'Txs 30d' while the archive starts 2026-10-19, so a 30 day range holds nearly every tx ever archived).
NETWORK_BASIS = {"range": ["chain_joins", "agents_new", "active_agents", "epochs_closed", "epochs_minted", "txs_total", "txs_by_type"],
                 "point_in_time": ["agents_total", "supply"],
                 "note": "range fields count only days in [from, to] that are on or after archive_from; point_in_time fields are the newest daily snapshot in the range"}

def onchain(fu, nw, lo, hi):
    by_v, by_c = {}, {}
    for r in fu["rows"]:
        if r["joined"]:
            by_v[r["version"]] = by_v.get(r["version"], 0) + r["joined"]; by_c[r["client"]] = by_c.get(r["client"], 0) + r["joined"]
    days = nw.get("days") or []
    act = db.q1("SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE ts >= ? AND ts < ? AND from_addr LIKE 'poa1%'", (lo, hi))["n"] or 0
    latest = next((d for d in days if d["agents"]["total"] is not None), None)
    sup = next((d["supply"] for d in days if d.get("supply") is not None), None)
    by_type = {}
    for d in days:
        for t, x in (d["txs"]["by_type"] or {}).items(): by_type[t] = by_type.get(t, 0) + (x.get("n") or 0)
    bl = fu["baseline"]
    return dict(
        via_poascan=dict(joined=fu["totals"]["joined"], joined_by_version=dict(sorted(by_v.items())), joined_by_client=_top(by_c, 99),
                         tagged_joins=bl["tagged_joins"], share_of_chain_joins=bl["share_tagged"]),
        network=dict(chain_joins=bl["chain_joins"], agents_new=sum(d["agents"]["new"] or 0 for d in days), agents_total=latest and latest["agents"]["total"],
                     active_agents=act, supply=sup, epochs_closed=sum(d["epochs"]["closed"] for d in days),
                     epochs_minted=round(sum(float(d["epochs"]["minted"] or 0) for d in days), 6), txs_total=sum(d["txs"]["total"] for d in days),
                     txs_by_type=dict(sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
                     archive_from=(nw.get("snapshot") or {}).get("history_from"), basis=NETWORK_BASIS),
        days=[dict(day=d["day"], chain_joins=d["agents"]["join_txs"], active_agents=d["agents"]["active"], agents_total=d["agents"]["total"],
                   supply=d["supply"], epochs_closed=d["epochs"]["closed"], txs=d["txs"]["total"],
                   tagged_joins=next((b["tagged_joins"] for b in bl["days"] if b["day"] == d["day"]), 0)) for d in days])

# ---- offchain
def _failures(r):
    probe = CK._vt(r["version"]) >= CK._vt(CK.PROBE_FROM)
    before_join = r["probed"] if probe else r["started"]
    return dict(start_no_probe=max(0, r["started"] - r["probed"]) if probe else None,
                no_join_after_start=max(0, before_join - r["joined"]),
                joined_no_answer_6h=max(0, r["joined"] - r["answered_6h"] - r["pending_6h"]),
                unmatched=r["unmatched"], resumed=r["resumed"], rate_429=r["rate_429"], rate_429_by_route=r["rate_429_by_route"])

def _dist(xs):
    return dict(n=len(xs), median_s=_pct(xs, 50), p90_s=_pct(xs, 90))

def setup_signals(vs):
    """1.26.44: intent signals that survive without check-ins (prompt v2.5 and later): copies of the join prompt from /start
    (and the Join dialog until 1.26.86), Join dialog opens (until 1.26.86), /api/v1/prompts/join fetches by client and MCP get_onboarding_steps calls.
    Daily counts from visits.py only (no IP, user agent, name or address). They show someone took the prompt, not a join."""
    days, by_c = [], {}
    tot = dict(prompt_copies=dict(start=0, join=0), join_opens=0, prompt_fetches=0, mcp_onboarding_calls=0)
    for d in vs["days"]:
        s = d.get("setup") or {}; pc = s.get("prompt_copies") or {}; fc = s.get("prompt_fetches_by_client") or {}
        _add(by_c, fc)
        for k in ("start", "join"): tot["prompt_copies"][k] += pc.get(k, 0)
        tot["join_opens"] += s.get("join_opens", 0); tot["prompt_fetches"] += sum(fc.values()); tot["mcp_onboarding_calls"] += s.get("mcp_onboarding_calls", 0)
        days.append(dict(day=d["day"], prompt_copies=dict(start=pc.get("start", 0), join=pc.get("join", 0)), join_opens=s.get("join_opens", 0),
                         prompt_fetches_by_client=dict(fc), mcp_onboarding_calls=s.get("mcp_onboarding_calls", 0)))
    return dict(totals=dict(tot, prompt_fetches_by_client=_top(by_c, 99)), days=days)

def offchain(fu, cohort, now, vs=None):
    rows = [dict(version=r["version"], client=r["client"], started=r["started"], probed=r["probed"], joined=r["joined"],
                 answered_6h=r["answered_6h"], mined_6h=r["mined_6h"], pending_6h=r["pending_6h"], failures=_failures(r)) for r in fu["rows"]]
    t = fu["totals"]; tf = dict(start_no_probe=sum((x["failures"]["start_no_probe"] or 0) for x in rows),
                                no_join_after_start=sum(x["failures"]["no_join_after_start"] for x in rows),
                                joined_no_answer_6h=sum(x["failures"]["joined_no_answer_6h"] for x in rows),
                                unmatched=t["unmatched"], resumed=t["resumed"], rate_429=t["rate_429"], rate_429_by_route=t["rate_429_by_route"])
    lag, lag_v, lag_c, skew = [], {}, {}, 0
    for _, v, c, jt, ct in cohort:
        s = ct - jt
        if s < 0: skew += 1; s = 0
        lag.append(s); lag_v.setdefault(v, []).append(s); lag_c.setdefault(c, []).append(s)
    ret = {}
    for n in RETENTION_DAYS:
        el = [x for x in cohort if x[3] + (n + 1) * 86400 <= now]; k = 0
        for a, _, _, jt, _ in el:
            if db.q1("SELECT 1 AS x FROM txs WHERE from_addr=? AND ts >= ? AND ts < ? LIMIT 1", (a, jt + n * 86400, jt + (n + 1) * 86400)): k += 1
        ret[f"day_{n}"] = dict(eligible=len(el), retained=k, rate=_rate(k, len(el)))
    return dict(setup_signals=setup_signals(vs or {"days": []}),
                funnel=dict(totals=dict(started=t["started"], probed=t["probed"], joined=t["joined"], answered_6h=t["answered_6h"], mined_6h=t["mined_6h"],
                                        pending_6h=t["pending_6h"]), rows=rows),
                failures=tf,
                time_to_checkin=dict(all=_dist(lag), by_version={k: _dist(v) for k, v in sorted(lag_v.items())},
                                     by_client={k: _dist(v) for k, v in sorted(lag_c.items())}, clock_skew_clamped=skew),
                retention=dict(cohort=len(cohort), **ret),
                window_s=fu["window_s"], since_ts=fu["since_ts"])

# ---- service
_BMAX = {"lt100ms": 100, "lt300ms": 300, "lt1s": 1000, "ge1s": None}
def _bucket_pct(b, p):
    tot = sum(b.values())
    if not tot: return None
    acc = 0
    for k in ("lt100ms", "lt300ms", "lt1s", "ge1s"):
        acc += b.get(k, 0)
        if acc >= p / 100 * tot: return k
    return "ge1s"

def service(fu, vs, fr, to, lo, hi):
    sr = [dict(version=r["version"], client=r["client"], success_rate=r["success_rate"], join_rate=r["join_rate"], probe_rate=r["probe_rate"],
               answer_rate=r["answer_rate"], mine_rate=r["mine_rate"]) for r in fu["rows"]]
    days, b_all, nf_all, er_all = [], dict.fromkeys(_BMAX, 0), {}, {}
    try:
        from . import visits as _VS
        rk = _VS.restart_kinds()
    except Exception: rk = {}
    for d in vs["days"]:
        h = d["health"]; b = dict.fromkeys(_BMAX, 0)
        for g in h["response_ms"].values():
            for k, n in g.items(): b[k] = b.get(k, 0) + n
        _add(b_all, b); _add(nf_all, h["not_found"]); _add(er_all, h["errors"])
        resp = sum(b.values()); e5 = sum(h["errors"].values())
        days.append(dict(day=d["day"], responses=resp, errors_5xx=e5, not_found_404=sum(h["not_found"].values()), availability=_rate(resp - e5, resp) if resp else None,
                         restarts=max(0, (d.get("segments") or 0) - 1), latency=dict(buckets=b, p50=_bucket_pct(b, 50), p95=_bucket_pct(b, 95))))
        n, k = days[-1]["restarts"], rk.get(d["day"])
        dep = min(n, int(k.get("deploy") or 0)) if k is not None else None
        days[-1].update(restarts_deploy=dep, restarts_other=(n - dep) if k is not None else None)
    resp = sum(b_all.values()); e5 = sum(er_all.values())
    poascan = dict(responses=resp, errors_5xx=e5, not_found_404=sum(nf_all.values()), availability=_rate(resp - e5, resp),
                   restarts=sum(x["restarts"] for x in days),
                   restarts_deploy=(sum(x["restarts_deploy"] for x in days if x["restarts_deploy"] is not None) if any(x["restarts_deploy"] is not None for x in days) else None),
                   restarts_other=(sum(x["restarts_other"] for x in days if x["restarts_other"] is not None) if any(x["restarts_other"] is not None for x in days) else None),
                   latency=dict(buckets=b_all, p50=_bucket_pct(b_all, 50), p95=_bucket_pct(b_all, 95)),
                   errors_5xx_by_page=_top(er_all, 99), not_found_by_page=_top(nf_all, 99), days=days)
    rc = {}
    for r in db.q("SELECT route, code, ms, ok FROM route_checks WHERE ts >= ? AND ts < ?", (lo, hi)):
        e = rc.setdefault(OI.endpoint_key(r["route"]), dict(count=0, ok=0, _ms=[], status_codes={}))
        e["count"] += 1; e["ok"] += int(r["ok"] or 0); e["status_codes"][r["code"]] = e["status_codes"].get(r["code"], 0) + 1
        if str(r["code"]).isdigit() and r["ms"] is not None: e["_ms"].append(int(r["ms"]))
    routes = {}
    for k, e in sorted(rc.items()):
        ms = e.pop("_ms"); routes[k] = dict(count=e["count"], ok=e["ok"], error_rate=_rate(e["count"] - e["ok"], e["count"]),
                                            p50_ms=_pct(ms, 50), p95_ms=_pct(ms, 95), status_codes=dict(sorted(e["status_codes"].items())))
    probes = {}
    for r in db.q("SELECT endpoint, SUM(n) AS n, SUM(ok) AS ok, SUM(ms * ok) AS msw FROM uptime_daily WHERE day >= ? AND day < ? GROUP BY endpoint", (lo, hi)):
        n, ok = int(r["n"] or 0), int(r["ok"] or 0)
        probes[OI.endpoint_key(r["endpoint"])] = dict(checks=n, ok=ok, uptime=_rate(ok, n), avg_ok_ms=int(r["msw"] / ok) if ok and r["msw"] is not None else None)
    req = {}
    try:
        from . import indexer as I
        I.flush_counts(force=True)
        for r in db.q("SELECT endpoint, code, SUM(n) AS n FROM upstream_counts WHERE minute >= ? AND minute < ? GROUP BY endpoint, code", (lo, hi)):
            e = req.setdefault(OI.endpoint_key(I.template(r["endpoint"])), dict(requests=0, errors=0, rate_429=0))
            n = int(r["n"] or 0); e["requests"] += n
            if r["code"] == "429": e["rate_429"] += n
            if r["code"] not in ("200", "304", "404"): e["errors"] += n
    except Exception: req = {}
    for e in req.values(): e["error_rate"] = _rate(e["errors"], e["requests"])
    rq = sorted(req.items(), key=lambda kv: (-kv[1]["requests"], kv[0]))
    return dict(success_rates=sr, poascan=poascan,
                upstream=dict(route_checks=routes, probes=dict(sorted(probes.items())),
                              requests=dict(rq), requests_total=sum(e["requests"] for e in req.values()),
                              route_checks_since_ts=OI._since("probes")))

DEFINITIONS = {
    "traffic.days.uniques": "Estimated distinct visitors that UTC day from a cookieless daily sketch; days cannot be added into a range total of distinct people.",
    "traffic.totals.uniques_sum": "The sum of daily unique estimates in the range, so a visitor seen on two days counts twice.",
    "traffic.views": "Successful page views split into human browsers, bots and agents (API and MCP calls).",
    "traffic.top_pages": "Views per page group (home, agents, start and so on), never a full path, top 10 with the rest in other.",
    "traffic.referrers": "Human page views per referring domain, with rare domains folded into other.",
    "traffic.devices": "Human page views by device class (mobile, tablet, desktop).",
    "traffic.countries": "Human page views by country from an offline lookup; the IP is dropped right after the lookup.",
    "traffic.api_routes": "API calls per OpenAPI route template, whatever the status.",
    "traffic.mcp_tools": "MCP tool calls per tool name.",
    "traffic.prompt_buttons": "Clicks on the prompt copy and open buttons, by fixed button id.",
    "onchain.via_poascan.joined": "Joined check-ins in the range whose address has an on-chain join tx at most 6 h before the check-in, so an Agent registered through a POAScan prompt.",
    "onchain.via_poascan.joined_by_version": "The same split by prompt version.",
    "onchain.via_poascan.joined_by_client": "The same split by the /start client tag (none for untagged prompt text).",
    "onchain.via_poascan.tagged_joins": "On-chain join txs in the range that a POAScan check-in matched.",
    "onchain.via_poascan.share_of_chain_joins": "tagged_joins divided by every on-chain join tx in the range.",
    "onchain.network.chain_joins": "Every archived join tx in the range, from any source.",
    "onchain.network.agents_new": "Sum of daily changes in the network's reported Agent count.",
    "onchain.network.agents_total": "The network's reported Agent count at the end of the newest day with a snapshot.",
    "onchain.network.active_agents": "Distinct Agents that sent at least one archived tx in the range.",
    "onchain.network.supply": "POA supply in the newest daily status snapshot.",
    "onchain.network.epochs_closed": "Epochs whose close record falls in the range.",
    "onchain.network.epochs_minted": "Rewards paid by those epoch closes, in POA.",
    "onchain.network.txs_total": "Archived txs with a ledger time in the range.",
    "onchain.network.txs_by_type": "The same split by tx type.",
    "offchain.setup_signals": "Intent signals, not joins: someone took the join prompt. Daily counts only, from POAScan's own aggregate counters; no IP, user agent, name or address. Since prompt v2.5 has no check-ins, these and onchain.network.chain_joins are what is left to watch.",
    "offchain.setup_signals.prompt_copies": "Copy and open clicks on the join prompt by card: start (/start step 3 and View prompt) and join (the Join dialog, retired in 1.26.86). Human browsers only. A copy is not a signup.",
    "offchain.setup_signals.join_opens": "Join dialog opens by human browsers. Intent only. The dialog was retired in 1.26.86, so 0 after.",
    "offchain.setup_signals.prompt_fetches_by_client": "GET /api/v1/prompts/join answered 200 or 304, by the ?client= variant asked for (an app id from /api/v1/prompts/clients, none without one, other for anything else). The client is the variant, not the site that fetched it, with one exception: poaswap is POASwap's own server fetch (about every 10 minutes), not a visitor, and gets the plain default text. Responses are cacheable for 10 minutes, so this counts fetches, not people or joins.",
    "offchain.setup_signals.mcp_onboarding_calls": "MCP get_onboarding_steps calls. An agent or app asked for the steps; not a join.",
    "offchain.funnel.started": "Start check-ins from the prompt, by version and client (v2.3 to v2.4 only; v2.5 and later have no check-ins, so this flattens).",
    "offchain.funnel.probed": "Probe check-ins (v2.4 and later): the agent opened a link it built itself.",
    "offchain.funnel.joined": "Joined check-ins matched to an on-chain join tx within 6 h.",
    "offchain.funnel.answered_6h": "Joined Agents with an answer tx within 6 h of the join tx.",
    "offchain.funnel.mined_6h": "Joined Agents paid a reward by an epoch close within 6 h of the join tx.",
    "offchain.funnel.pending_6h": "Joined less than 6 h ago and not yet both answered and mined.",
    "offchain.failures.start_no_probe": "v2.4 and later: started minus probed, an inferred count of clients that could not open a built link (or skipped the probe).",
    "offchain.failures.no_join_after_start": "Probed (v2.4) or started (older) minus joined: signups that did not reach a matched join.",
    "offchain.failures.joined_no_answer_6h": "Joined Agents with no answer within 6 h, leaving out those still pending.",
    "offchain.failures.unmatched": "Joined check-ins with no matching join tx in the archive (indexer lag or a wrong address).",
    "offchain.failures.resumed": "Joined check-ins for an address that joined more than 6 h earlier (the prompt pasted again).",
    "offchain.failures.rate_429": "Agents reporting a 429 from minepoa.com through the rate check-in.",
    "offchain.failures.rate_429_by_route": "The same split by route (register, challenge, answer, mine, me).",
    "offchain.time_to_checkin": "Seconds from the on-chain join tx to the joined check-in, median and p90; it measures reporting lag after joining, not time from start to join.",
    "offchain.time_to_checkin.clock_skew_clamped": "Check-ins that arrived before our copy of the join tx time (allowed up to 10 minutes), counted as 0 seconds.",
    "offchain.retention.cohort": "POAScan-onboarded Agents (matched joined check-ins) whose join tx falls in the range.",
    "offchain.retention.day_N": "Of the cohort Agents whose day N is over, the share that sent any tx in the 24 h window starting N days after the join tx.",
    "service.success_rates": "Per version and client: success_rate is answered_6h over started; the other rates are step over step.",
    "service.poascan.responses": "Responses POAScan served for counted pages and API calls (static files, fragments and check-ins left out).",
    "service.poascan.availability": "Share of those responses that were not a server error (5xx); POAScan's own view, not an outside uptime monitor.",
    "service.poascan.restarts": "Extra process starts on that UTC day (deploys, crashes or machine moves).",
    "service.poascan.restarts_deploy": "Of those restarts, starts on a new image (FLY_IMAGE_REF changed): deploys. Null for days before the split began.",
    "service.poascan.restarts_other": "Restarts on the same image: a crash, a guard exit or a machine move. Null for days before the split began.",
    "service.poascan.latency": "Server time to the response in buckets under 100 ms, under 300 ms, under 1 s and 1 s or more; p50 and p95 name the bucket.",
    "service.poascan.errors_5xx": "Server error responses, total and by page group.",
    "service.poascan.not_found_404": "Not-found responses, total and by page group (search misses left out).",
    "service.upstream.route_checks": "POAScan's own check of each minepoa hosted route: reads, clear reads, error_rate (reads that were not clear), p50 and p95 latency in ms, status codes.",
    "service.upstream.probes": "POAScan's periodic reads of minepoa pages and feeds per endpoint: checks, ok, uptime and the average ok latency in ms.",
    "service.upstream.requests": "Requests POAScan sent to minepoa.com per endpoint template (kept 8 days), with errors (anything but 200, 304 or 404) and 429s.",
    "wallets": "Always null here: POAScan does not create wallets; wallet counts come from POASwap.",
}

NOT_MEASURABLE = {
    "time_from_start_to_join": "the start check-in carries no address or id, so a start cannot be linked to the join that followed it; only reporting lag after the join is measured",
    "distinct_visitors_over_range": "unique visitors are a daily sketch with a salt replaced each UTC midnight, so the same person cannot be recognised across days",
    "failure_error_classes_beyond_429": "agents report only 429s (by route) through check-ins; 401s, refused tool calls and other errors are not reported back, so drop-offs are inferred from step counts",
    "probe_failures_before_v2_4": "the probe check-in starts with v2.4; older versions have no step between start and join",
    "untagged_signups": "agents that join from POAScan text without a check-in (every v2.5 and later signup) cannot be told apart from other joins; offchain.setup_signals shows intent only",
    "poascan_outside_uptime": "POAScan has no outside monitor of itself; availability is the share of non 5xx responses it served, plus restarts per day",
    "retention_beyond_90_days": "check-in addresses are kept 90 days, so cohorts older than that are gone",
    "wallets": "Always null: POAScan does not create wallets, so it has no wallet signups to report. Wallet links seen on chain are in /ops/network days[].wallets (solana_new, ethereum_new, totals)",
    "onchain.network.archive_from": "First UTC day in POAScan's archive (2026-10-19). A range starting earlier counts from here, so a 30 day txs_total is close to all time",
    "onchain.network.basis": "Which network fields are sums over the range (range) and which are the newest snapshot (point_in_time)",
}

def _compute(fr, to, version, now):
    lo, hi = OI._bounds(fr, to)
    vs = VS.report(fr, to); fu = CK.report(fr, to, now=now); nw = json.loads(NW.report(fr, to))
    cohort = _cohort(lo, hi, now)
    out = {"from": fr, "to": to, "generated_ts": now, "version": version, "cache_ttl_s": CACHE_TTL,
           "traffic": traffic(vs), "onchain": onchain(fu, nw, lo, hi), "offchain": offchain(fu, cohort, now, vs),
           "service": service(fu, vs, fr, to, lo, hi), "wallets": None,
           "definitions": DEFINITIONS, "not_measurable": NOT_MEASURABLE}
    del cohort
    return out

_building = set(); _seen = {}   # keys with a rebuild in flight; key -> last read time

def _build(k, version, now=None):
    try: VS.COUNTER.flush()
    except Exception: pass
    v = json.dumps(_compute(k[0], k[1], version, int(now or time.time())), separators=(",", ":"))
    with _lock:
        _cache[k] = (time.time(), v); _cache.move_to_end(k)
        while len(_cache) > CACHE_MAX: _cache.popitem(last=False)
    return v

def _rebuild_bg(k, version):
    def run():
        try: _build(k, version)
        except Exception: pass
        finally:
            db.release()   # 1.26.249: this short-lived thread opened a thread-local conn; release it (same pattern as 1.26.227)
            with _lock: _building.discard(k)
    with _lock:
        if k in _building: return
        _building.add(k)
    threading.Thread(target=run, daemon=True, name="opsdash-build").start()

def report(fr, to, version, now=None):
    """JSON text for [fr, to]: fresh for CACHE_TTL s, then the stale copy at once while one rebuild runs in the background."""
    k = (fr, to); t = time.time()
    with _lock:
        _seen[k] = t; hit = _cache.get(k)
    if hit and t - hit[0] < CACHE_TTL: return hit[1]
    if hit and t - hit[0] < STALE_MAX:
        _rebuild_bg(k, version); return hit[1]
    return _build(k, version, now)

def warm(version, now=None):
    """Prebuild the default ranges and every range read within WARM_KEEP seconds (the timer calls this)."""
    t = now or time.time()
    keys = [OI.parse_range({}, now=t), OI.parse_range({"from": [(dt.datetime.fromtimestamp(t, dt.timezone.utc).date() - dt.timedelta(days=30)).isoformat()]}, now=t)]
    with _lock:
        for k in [k for k, ts in _seen.items() if t - ts > WARM_KEEP]: _seen.pop(k, None)
        keys += [k for k in _seen if k not in keys]
    for k in keys[:CACHE_MAX]:
        try: _build(k, version)
        except Exception: pass
    return keys[:CACHE_MAX]

def start(version, delay=90):
    """Timer: first build after delay seconds (the indexer settles first), then every CACHE_TTL seconds."""
    def loop():
        time.sleep(delay)
        while True:
            t0 = time.time(); warm(version)
            time.sleep(max(30, CACHE_TTL - 30 - (time.time() - t0)))
    threading.Thread(target=loop, daemon=True, name="opsdash-warm").start()

def clear_cache():
    with _lock: _cache.clear()
