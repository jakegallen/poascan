"""Signup check-ins for join prompt v2.3 to v2.4, and the private funnel built from them (GET /ops/funnel).
Since v2.5 the prompt carries no check-ins; this only counts copies of v2.3 to v2.4 still in chats.

Those prompts asked an agent, optionally, to open two keyless URLs on poascan.io:
  /j/<version>[/<client>]/start                     once, before joining
  /j/<version>[/<client>]/joined?addr=<poa1 address> once, after joining (public address only)
  /j/<version>[/<client>]/rate?route=<route>        once, after a 429 (v2.3.1 and later)
  /j/<version>[/<client>]/probe?w=<word>            once, after the built-link test passed (v2.4 and later). The word is
                                                    the agent's random test word: checked for shape, never stored. The
                                                    probe proves the client opened a link it built itself.
<client> is the tag a /start copy button adds (onboarding_prompt.tagged); without it the check-in is "none" (the canonical
text from the API, MCP, llms.txt or the Join modal). Strict allowlist: a known version, a known client id, the step, and for
joined exactly one addr parameter matching ADDR_RX. Anything else is a 400 and nothing is stored or counted; key-shaped input
never gets here (server.key_guard answers 400 first). Server logs show /j/[check-in] only, never the path or query.

Stored: daily counts per (version, client, step) and, for joined, the first (version, client, time) per public address.
No IP, user agent, URL, query string or key. Addresses are kept ADDR_KEEP_DAYS, counts COUNT_KEEP_DAYS.

The funnel matches tagged addresses to POAScan's own archive (txs: the join tx, then any answer tx within WINDOW_S of it;
epoch close rewards for mined). Nothing here calls minepoa.com."""
import datetime as dt, re, threading, time
from . import db, onboarding_prompt as OP

VERSIONS = ("v2.3", "v2.3.1", "v2.3.2", "v2.4")   # prompt versions that carry check-ins (older copies stay in chats)
# v2.5 (LabLeak post 1398) and later carry no check-ins: copy-paste text never asks an agent to open a poascan.io URL.
# This endpoint stays only so older pasted copies keep answering ok instead of failing a step.
assert OP.VERSION in VERSIONS or OP.CHECKIN not in OP.TEMPLATE, "a prompt version with check-ins must be in checkin.VERSIONS"
STEPS = ("start", "joined", "rate", "probe")
PROBE_FROM = "v2.4"                      # the probe check-in starts with v2.4
WORD_RX = re.compile(r"^[A-Za-z]{1,16}$")  # probe?w=: the random test word, letters only; checked, never stored
ROUTES = ("register", "challenge", "answer", "mine", "me")   # rate?route= allowlist (v2.3.1)
ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{38,50}$")
PATH_RX = re.compile(r"^/j/(v\d{1,2}(?:\.\d{1,2}){1,2})(?:/([a-z0-9-]{1,24}))?/(start|joined|rate|probe)$")
WINDOW_S = 6 * 3600                      # answered and mined count within this long after the on-chain join
SKEW_S = 600                             # a joined check-in may arrive this long before our copy of the join tx's time
ADDR_KEEP_DAYS, COUNT_KEEP_DAYS = 90, 400
DAY_ADDR_CAP = 5000                      # new addresses stored per UTC day at most (abuse bound); counts still add up
SINCE_BLOB = "checkin_since"
MAX_DAYS, DEFAULT_DAYS = 31, 7
OK_TEXT = "ok: check-in counted. Carry on with the steps.\n"
BAD_TEXT = "Not counted. A check-in takes no parameters, or only addr= with a public poa1 address. Carry on with the steps.\n"

_clients = [None]
def clients():
    if _clients[0] is None:
        from . import start as S
        _clients[0] = S.checkin_clients()
    return _clients[0]

def parse(path, query):
    """(version, client, step, addr or route) for an allowed check-in, else ValueError. path has no trailing slash."""
    m = PATH_RX.match(path or "")
    if not m: raise ValueError("path")
    ver, cl, step = m.group(1), m.group(2) or "none", m.group(3)
    if ver not in VERSIONS: raise ValueError("version")
    if cl != "none" and cl not in clients(): raise ValueError("client")
    if m.group(2) == "none": raise ValueError("client")
    q = query or ""
    if step == "start":
        if q: raise ValueError("params")
        return ver, cl, step, None
    parts = q.split("&")
    if step == "probe":
        if _vt(ver) < _vt(PROBE_FROM): raise ValueError("version")
        if len(parts) != 1 or not parts[0].startswith("w=") or not WORD_RX.match(parts[0][2:]): raise ValueError("params")
        return ver, cl, step, None                              # the word is not kept
    if step == "rate":
        if ver == "v2.3": raise ValueError("version")          # the rate check-in starts with v2.3.1
        if len(parts) != 1 or not parts[0].startswith("route=") or parts[0][6:] not in ROUTES: raise ValueError("params")
        return ver, cl, step, parts[0][6:]
    if len(parts) != 1 or not parts[0].startswith("addr="): raise ValueError("params")
    addr = parts[0][5:]
    if not ADDR_RX.match(addr): raise ValueError("addr")
    return ver, cl, step, addr

def _vt(v): return tuple(int(x) for x in v[1:].split("."))

def _day(t): return time.strftime("%Y-%m-%d", time.gmtime(t))
_prune = [0.0]; _lk = threading.Lock()

def record(ver, cl, step, addr, now=None):
    """Count one check-in; for joined, keep the first (version, client, time) per address."""
    t = int(now or time.time()); d = _day(t)
    if step == "probe":
        db.write("INSERT INTO checkin_probes(day,version,client,n) VALUES(?,?,?,1) ON CONFLICT(day,version,client) DO UPDATE SET n = n + 1", (d, ver, cl)); return
    if step == "rate":
        db.write("INSERT INTO checkin_rates(day,version,client,route,n) VALUES(?,?,?,?,1) ON CONFLICT(day,version,client,route) DO UPDATE SET n = n + 1",
                 (d, ver, cl, addr)); return
    st = [("INSERT INTO checkin_counts(day,version,client,step,n) VALUES(?,?,?,?,1) ON CONFLICT(day,version,client,step) DO UPDATE SET n = n + 1",
           (d, ver, cl, step), False)]
    if step == "joined" and addr:
        lo = t - t % 86400
        if (db.q1("SELECT COUNT(*) AS n FROM checkin_addrs WHERE ts >= ?", (lo,)) or {}).get("n", 0) < DAY_ADDR_CAP:
            st.append(("INSERT OR IGNORE INTO checkin_addrs(addr,version,client,ts) VALUES(?,?,?,?)", (addr, ver, cl, t), False))
    db.write_tx(st)
    with _lk:
        if t - _prune[0] < 3600: return
        _prune[0] = t
    prune(t)

def prune(now=None):
    t = int(now or time.time())
    db.write_tx([("DELETE FROM checkin_addrs WHERE ts < ?", (t - ADDR_KEEP_DAYS * 86400,), False),
                 ("DELETE FROM checkin_counts WHERE day < ?", (_day(t - COUNT_KEEP_DAYS * 86400),), False),
                 ("DELETE FROM checkin_rates WHERE day < ?", (_day(t - COUNT_KEEP_DAYS * 86400),), False),
                 ("DELETE FROM checkin_probes WHERE day < ?", (_day(t - COUNT_KEEP_DAYS * 86400),), False)])

def start(now=None):
    """Record when check-ins began (once; kept across restarts)."""
    if not (db.get_blob(SINCE_BLOB)[0] or {}).get("ts"): db.put_blob(SINCE_BLOB, {"ts": int(now or time.time())})

# ---- the funnel
DEFINITIONS = {
    "started": "start check-ins (/j/<version>[/<client>]/start) on UTC days from..to",
    "probed": "probe check-ins (/j/<version>[/<client>]/probe?w=..., v2.4 and later) on UTC days from..to: the agent opened a link it built itself",
    "probe_rate": "probed / started (v2.4 rows): the share of starts whose client can open links it builds",
    "joined": "joined check-ins in the range whose address has an on-chain join tx at most window_s before the check-in (first check-in per address)",
    "answered_6h": "joined, with an answer (challenge tx) from that address within window_s after its join tx",
    "mined_6h": "joined, with a reward to that address in an epoch close within window_s after its join tx",
    "pending_6h": "joined less than window_s ago and not yet both answered and mined (rates for recent days can still rise)",
    "resumed": "joined check-ins whose address joined more than window_s earlier (pasted again after joining); not counted as joined",
    "unmatched": "joined check-ins with no join tx for the address in POAScan's archive (indexer lag, or a wrong address)",
    "join_rate": "joined / started", "answer_rate": "answered_6h / joined", "mine_rate": "mined_6h / joined",
    "success_rate": "answered_6h / started: a started signup that joined and answered within window_s",
    "client": "the /start tag (claude, muse, ...), poaswap when POASwap tags the API text, none for untagged text (API, MCP, llms.txt, Join modal)",
    "rate_429": "rate check-ins (/j/<version>[/<client>]/rate?route=...) on UTC days from..to: an agent reporting a 429, from v2.3.1",
    "rate_429_by_route": "rate_429 split by route (register, challenge, answer, mine, me)",
    "baseline": "every on-chain join tx in the range by UTC day, next to joins matched to a check-in, so share_tagged is the share that came through a POAScan prompt"}

def parse_range(qs, now=None):
    """Same rules as /ops/internal: from and to as YYYY-MM-DD (UTC), default the last 7 days, at most 31."""
    from . import opsinternal as OI
    return OI.parse_range(qs, now)

def _rate(a, b): return round(a / b, 4) if b else None
def _row(): return dict(started=0, probed=0, joined=0, answered_6h=0, mined_6h=0, pending_6h=0, resumed=0, unmatched=0, rate_429=0, rate_429_by_route={})
def _rates(r):
    r = dict(r, rate_429_by_route={k: r["rate_429_by_route"][k] for k in ROUTES if k in r["rate_429_by_route"]})
    return dict(r, probe_rate=_rate(r["probed"], r["started"]), join_rate=_rate(r["joined"], r["started"]), answer_rate=_rate(r["answered_6h"], r["joined"]),
                mine_rate=_rate(r["mined_6h"], r["joined"]), success_rate=_rate(r["answered_6h"], r["started"]))

def _closes():
    """epoch -> close time, and addr -> {epoch: reward}, from the archive's epoch records (no upstream call)."""
    from . import analytics as A
    return {int(e["epoch"]): int(e.get("ts") or 0) for e in A.epochs_raw()}, A.rewards_by_addr()

def match(addr, ts):
    """('joined', join ts) when the address's first archived join tx is at most WINDOW_S before the check-in (SKEW_S after it
    allowed), ('resumed', join ts) when it joined longer ago, ('unmatched', join ts or None) otherwise. Local archive only."""
    j = db.q1("SELECT MIN(ts) AS t FROM txs WHERE type='join' AND from_addr=?", (addr,)); jt = j and j["t"]
    if not jt: return "unmatched", None
    if ts - jt > WINDOW_S or jt - ts > SKEW_S: return ("resumed" if ts > jt else "unmatched"), jt
    return "joined", jt

def report(fr, to, now=None):
    now = int(now or time.time())
    lo = int(dt.datetime.fromisoformat(fr + "T00:00:00+00:00").timestamp()); hi = int(dt.datetime.fromisoformat(to + "T00:00:00+00:00").timestamp()) + 86400
    rows = {}; days = {}
    def R(v, c): return rows.setdefault((v, c), _row())
    def D(d): return days.setdefault(d, dict(day=d, started=0, chain_joins=0, tagged_joins=0))
    for r in db.q("SELECT day, version, client, SUM(n) AS n FROM checkin_counts WHERE step='start' AND day BETWEEN ? AND ? GROUP BY day, version, client", (fr, to)):
        R(r["version"], r["client"])["started"] += int(r["n"] or 0); D(r["day"])["started"] += int(r["n"] or 0)
    for r in db.q("SELECT version, client, SUM(n) AS n FROM checkin_probes WHERE day BETWEEN ? AND ? GROUP BY version, client", (fr, to)):
        R(r["version"], r["client"])["probed"] += int(r["n"] or 0)
    for r in db.q("SELECT version, client, route, SUM(n) AS n FROM checkin_rates WHERE day BETWEEN ? AND ? GROUP BY version, client, route", (fr, to)):
        x = R(r["version"], r["client"]); n = int(r["n"] or 0); x["rate_429"] += n; x["rate_429_by_route"][r["route"]] = x["rate_429_by_route"].get(r["route"], 0) + n
    tags = db.q("SELECT addr, version, client, ts FROM checkin_addrs WHERE ts >= ? AND ts < ? ORDER BY ts", (lo, hi))
    closes = rewards = None
    for a in tags:
        x = R(a["version"], a["client"])
        st, jt = match(a["addr"], a["ts"])
        if st != "joined": x[st] += 1; continue
        x["joined"] += 1
        if lo <= jt < hi: D(_day(jt))["tagged_joins"] += 1
        ans = db.q1("SELECT 1 AS x FROM txs WHERE type='challenge' AND from_addr=? AND ts >= ? AND ts <= ? LIMIT 1", (a["addr"], jt, jt + WINDOW_S))
        if closes is None: closes, rewards = _closes()
        mined = any(v > 0 and jt <= closes.get(e, 0) <= jt + WINDOW_S for e, v in (rewards.get(a["addr"]) or {}).items())
        x["answered_6h"] += bool(ans); x["mined_6h"] += bool(mined)
        if now < jt + WINDOW_S and not (ans and mined): x["pending_6h"] += 1
    for r in db.q("SELECT ts / 86400 AS d, COUNT(*) AS n FROM txs WHERE type='join' AND ts >= ? AND ts < ? GROUP BY d", (lo, hi)):
        D(_day(int(r["d"]) * 86400))["chain_joins"] += int(r["n"] or 0)
    tot = _row()
    for r in rows.values():
        for k in tot:
            if k == "rate_429_by_route":
                for rt, n in r[k].items(): tot[k][rt] = tot[k].get(rt, 0) + n
            else: tot[k] += r[k]
    out_rows = [dict(version=v, client=c, **_rates(r)) for (v, c), r in sorted(rows.items(), key=lambda kv: (kv[0][0], -kv[1]["started"], -kv[1]["joined"], kv[0][1]))]
    cj = sum(d["chain_joins"] for d in days.values()); tj = sum(d["tagged_joins"] for d in days.values())
    return {"from": fr, "to": to, "generated_ts": now, "since_ts": (db.get_blob(SINCE_BLOB)[0] or {}).get("ts"), "window_s": WINDOW_S,
            "versions": list(VERSIONS), "totals": _rates(tot), "rows": out_rows,
            "baseline": dict(chain_joins=cj, tagged_joins=tj, share_tagged=_rate(tj, cj),
                             days=[days[k] for k in sorted(days, reverse=True)]),
            "definitions": DEFINITIONS}
