"""Light, cached address balances for MCP get_address and /api/v1/address under load (1.26.319).

MCP tools/call and the address API used to take a heavy serving slot. When the pool was full they
answered 503 "server busy, retry shortly". This module builds balance, spendable_est and locked_est
from the stored agent list and close records already on disk, with as_of, read_at and a stale flag,
and never waits for a heavy slot or a minepoa.com address read.
"""
import threading, time
from . import db, analytics as A, segments as SG

# Thread-local: the request handler could not get a heavy slot, so serve this copy instead of 503.
_flag = threading.local()

# Last good light row per address, so a cold rewards map never blocks this path.
_last = {}
_lock = threading.Lock()
LAST_MAX = 4096
STALE_AFTER_S = 20 * 60   # agent list is read every 15 min; older than 20 min is stale (same window as the address page)

def want_light():
    return bool(getattr(_flag, "on", False))

def enter_light():
    _flag.on = True

def exit_light():
    _flag.on = False

def _iso(ts):
    if ts is None: return None
    try: t = int(ts)
    except (TypeError, ValueError): return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))

def _peek_rewards(addr):
    """addr -> rewards map from the in-memory cache, including a stale copy. None when never computed."""
    k = ("rewards_by_addr", SG.selected())
    with A._lock:
        hit = A._cache.get(k)
    if not hit: return None
    return (hit[1] or {}).get(addr, {})

def _remember(row):
    a = row.get("address")
    if not a: return
    with _lock:
        _last[a] = dict(row)
        if len(_last) > LAST_MAX:
            # drop the oldest insertion (CPython dicts keep insertion order)
            try: _last.pop(next(iter(_last)))
            except Exception: pass

def remember(row):
    """Keep a last-known light row after a full or light read (call with the light fields only)."""
    if isinstance(row, dict) and row.get("address"):
        _remember({k: row.get(k) for k in
                   ("address", "balance", "spendable_est", "locked_est", "as_of", "read_at",
                    "stale", "balance_as_of", "balance_source", "rewards_total")})

def _last_known(addr):
    with _lock:
        r = _last.get(addr)
        return dict(r) if r else None

def payload(addr, reason="cache"):
    """Light row for one poa1 address, or None when the archive has never seen it.

    reason is 'cache' (normal light compute) or 'busy' (heavy slot was not available).
    Never calls minepoa.com. Never waits for a heavy compute slot: uses a warm or stale
    rewards map, else the last-known vest, else leaves spendable_est and locked_est null.
    """
    a = (addr or "").strip()
    acc = db.q1("SELECT addr, balance, balance_s, last_seen, api_ts FROM accounts WHERE addr=?", (a,))
    rb = _peek_rewards(a)
    prior = _last_known(a)
    if acc is None and prior is None and not rb:
        return None
    now = int(time.time())
    bal = None
    as_of = None
    source = None
    if acc:
        if acc["balance_s"] is not None: bal = acc["balance_s"]
        elif acc["balance"] is not None: bal = f'{float(acc["balance"]):.6f}'
        as_of = acc["api_ts"] or acc["last_seen"]
        source = "agents"
    if bal is None and prior and prior.get("balance") is not None:
        bal = prior["balance"]
        as_of = prior.get("balance_as_of") or prior.get("as_of")
        source = "last_known"
    sp = lk = rsum = None
    vest_src = None
    if rb is not None:
        try:
            from . import correction as _CC
            sp, lk = A.vest_split(rb, A.open_gkey())
            lk = _CC.locked_after(a, lk)
            rsum = round(sum(rb.values()), 6)
            sp, lk = round(sp, 6), round(lk, 6)
            vest_src = "close_records"
        except Exception:
            sp = lk = rsum = None
    if sp is None and prior:
        sp, lk, rsum = prior.get("spendable_est"), prior.get("locked_est"), prior.get("rewards_total")
        vest_src = "last_known" if sp is not None else vest_src
    try:
        as_of_i = int(as_of) if as_of is not None and not isinstance(as_of, str) else None
    except (TypeError, ValueError):
        as_of_i = None
    if as_of_i is None and isinstance(as_of, str) and as_of.isdigit():
        as_of_i = int(as_of)
    age = (now - as_of_i) if as_of_i else None
    from . import strain as _ST
    stale = bool(reason == "busy" or _ST.for_endpoint("/api/agents") or (age is not None and age > STALE_AFTER_S)
                 or vest_src == "last_known" or (sp is None and bal is not None))
    as_of_iso = _iso(as_of_i) if as_of_i else (as_of if isinstance(as_of, str) and "T" in as_of else None)
    row = dict(address=a, balance=bal, spendable_est=sp, locked_est=lk,
               as_of=as_of_iso, read_at=_iso(now), stale=stale,
               balance_as_of=as_of_i, balance_source=source, rewards_total=rsum,
               served="light", served_reason=reason, vest_source=vest_src,
               note="Light copy from POAScan's stored agent list and close records. No live address read.")
    _remember(row)
    return row

def wrap_mcp(raw, reason="busy"):
    """JSON-RPC response for a single get_address tools/call, served from payload(). None if the body is not that call."""
    from . import agentapi as AG
    try: msg = json_load(raw)
    except Exception:
        return None
    if not isinstance(msg, dict) or msg.get("method") != "tools/call": return None
    p = msg.get("params") or {}
    if p.get("name") != "get_address": return None
    i = msg.get("id") if "id" in msg else None
    args = p.get("arguments") or {}
    if not isinstance(args, dict):
        return 400, AG._err(i, -32602, "arguments must be an object")
    a = str(args.get("address") or "").strip()
    if not a:
        return 200, _mcp_ok(i, {"error": "address is required"}, True, AG)
    row = payload(a, reason=reason)
    if row is None:
        return 200, _mcp_ok(i, {"error": "address not found in the POAScan archive"}, True, AG)
    data = AG._clean(__import__("json").loads(__import__("json").dumps(row, default=str)))
    if isinstance(data, dict): data.setdefault("meta", AG.meta())
    return 200, _mcp_ok(i, data, False, AG)

def _mcp_ok(i, data, is_err, AG):
    text = data.get("error") if is_err else AG.plainjson(__import__("json").dumps(data))
    body = {"content": [{"type": "text", "text": str(text)}], "structuredContent": data if not is_err else {"error": data.get("error"), "meta": data.get("meta") or AG.meta()}, "isError": is_err}
    if not is_err:
        body["structuredContent"] = data
    return {"jsonrpc": "2.0", "id": i, "result": body}

def json_load(raw):
    import json
    if isinstance(raw, (bytes, bytearray)): raw = raw.decode("utf-8", "replace")
    return json.loads(raw or "null")

def is_get_address_call(raw):
    """True when this MCP body is a single tools/call of get_address."""
    try: msg = json_load(raw)
    except Exception:
        return False
    if not isinstance(msg, dict) or msg.get("method") != "tools/call": return False
    return (msg.get("params") or {}).get("name") == "get_address"
