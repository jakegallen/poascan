"""Protocol views: the Governance, Protocol timeline tab and the Network badge. Reads protocol.py's store only; a page
view never calls minepoa.com."""
import json, time
from . import protocol as PT, scoresort as SS
from .ui import E, card, stat, intc, short, lt, rel, flag

KIND_LABEL = {"release": "Release", "baseline": "Baseline", "source_change": "Source change", "params_change": "Params change"}
KIND_ORDER = {k: i for i, k in enumerate(("release", "source_change", "params_change", "baseline"))}
FILTERS = [("", "All"), ("release", "Releases"), ("source_change", "Source"), ("params_change", "Params"), ("baseline", "Baseline")]
COLS = [SS.Col("when", "When", "num"), SS.Col("kind", "Event", "cat"), SS.Col(None, "File", "text", "dk"), SS.Col(None, "sha256", "text", "dk"),
        SS.Col("release", "Release", "text"), SS.Col(None, "Note", "text", "dk")]
SORTS = [(c.key, c.label) for c in COLS if c.key]
_VAL = {"when": lambda r: r["ts"], "kind": lambda r: KIND_ORDER.get(r["kind"], 9), "release": lambda r: SS.text_key(r.get("matches_release") or r.get("release_version"))}

def _ago(s):
    s = max(0, int(s)); return f"{s // 60}m" if s < 3600 else f"{s // 3600}h {s % 3600 // 60}m" if s < 86400 else f"{s // 86400}d"

def stale_flag():
    """Stale tag (ui.flag) when no good check in protocol.STALE_S; the hover says when the last one was."""
    m = PT.meta(); t = m.get("last_ok")
    if not PT.stale(): return ""
    return flag("Stale", f"Client files last checked {_ago(time.time() - t)} ago" if t else "Client files not checked yet")

def badge(link=True):
    """'Client matches release vX' (green) or 'Unreleased client change' (amber); grey before the first check."""
    s = PT.state(); tone = {"match": "ok", "older_release": "ok", "unreleased": "warn"}.get(s["state"], "")
    tip = (f'poa.mjs {short(s["live_client_sha256"] or "", 8, 6)}, poa-web.mjs {short(s["live_web_client_sha256"] or "", 8, 6)}; '
           f'release {s["release_version"] or "none"}')
    inner = f'<i aria-hidden="true"></i>{E(s["badge"])}'
    cls = f'pbadge {tone}'.strip()
    if link: return f'<a class="{cls}" href="/governance?tab=protocol" title="{E(tip)}">{inner}</a>' + stale_flag()
    return f'<span class="{cls}" title="{E(tip)}">{inner}</span>' + stale_flag()

def _file_val(s, f):
    v = s["client_matches_release" if f == "client" else "web_client_matches_release"]
    sha = s["live_client_sha256" if f == "client" else "live_web_client_sha256"]
    if not sha: return '<span class="na">···</span>'
    word = "Matches" if v else "Unreleased"
    return f'<span title="{E(sha)}">{word}</span>'

def stats_row():
    s = PT.state(); m = PT.meta(); f = stale_flag()
    ver = (f'<span class="mono ver" title="{E(s["release_version"])}">{E(s["release_version"])}</span>' if s["release_version"] else '<span class="na">···</span>')
    return ('<div class="stats four">' + "".join([
        stat("Release", ver, tip="The current G0 signed release in /api/release"),
        stat("poa.mjs", _file_val(s, "client"), tip="Live sha256 of minepoa.com/client/poa.mjs against the signed releases", flag_html=f),
        stat("poa-web.mjs", _file_val(s, "web_client"), tip="Live sha256 of minepoa.com/poa-web.mjs against the signed releases", flag_html=f),
        stat("Last check", rel(m.get("last_ok")) if m.get("last_ok") else '<span class="na">···</span>', tip="Both files are checked once an hour", flag_html=f)]) + "</div>")

def _sha_cell(r):
    if r["kind"] == "release":
        return '<span class="dim">···</span>'
    new = f'<span class="mono" title="{E(r["sha256_new"] or "")}">{E((r["sha256_new"] or "")[:10])}</span>'
    if r.get("sha256_old"): return f'<span class="mono dim" title="{E(r["sha256_old"])}">{E(r["sha256_old"][:10])}</span> → {new}'
    return new

def _rel_cell(r):
    if r["kind"] == "release":
        v = E(r["release_version"] or "")
        return f'<a class="mono" href="/tx/{E(r["release_txid"])}">{v}</a>' if r.get("release_txid") else f'<span class="mono">{v}</span>'
    if r["kind"] in ("source_change", "baseline"):
        return f'<span class="mono">{E(r["matches_release"])}</span>' if r.get("matches_release") else '<span class="tag warn">Unreleased</span>'
    return '<span class="dim">···</span>'

def _note(r):
    if r["kind"] == "release": return E((r.get("changelog_ref") or "")[:120])
    if r["kind"] == "params_change":
        ks = r.get("changed_keys") or []; bd = r.get("boundaries") or {}
        txt = E(", ".join(ks[:6]) + (f" and {len(ks) - 6} more" if len(ks) > 6 else ""))
        tip = "; ".join(f'{c["key"]}: {json.dumps(c.get("old"))} to {json.dumps(c.get("new"))}' for c in (r.get("changes") or [])[:12])
        tag = f' <span class="tag est" title="{E(", ".join(bd))}">{len(bd)} boundar{"y" if len(bd) == 1 else "ies"}</span>' if bd else ""
        return f'<span title="{E(tip)}">{txt}</span>{tag}'

    if r["kind"] == "baseline": return "First hash recorded"
    return "Matches a signed release" if r.get("matches_release") else "Not in any signed release"

def select(kind="", by="when", d="desc"):
    rows = PT.events(kind or None, 5000)
    for r in rows: r["changelog_ref"] = (r.get("detail") or {}).get("changelog_ref")
    tie = lambda r: (-r["ts"], -r["id"])
    return SS.sort_rows(rows, _VAL.get(by, _VAL["when"]), SS.kind_of(COLS, by), d, tie=tie)

def tab(qs, href, qsx):
    """Governance, Protocol: stats, the badge and the timeline (header sorting, kind chips, CSV and API links)."""
    q1 = lambda k, dflt="": ((qs or {}).get(k) or [dflt])[0]
    by = SS.page_sort(qs, dict(SORTS), "when"); d = SS.page_dir(qs)
    k = q1("kind"); k = k if k in dict(FILTERS) else ""
    rows = select(k, by, d); allr = PT.events(None, 5000)
    cnt = {"": len(allr), **{x: sum(1 for r in allr if r["kind"] == x) for x, _ in FILTERS if x}}
    keep = lambda **o: dict(dict(sort=by if by != "when" else "", dir="asc" if d == "asc" else "", kind=k), **o)
    link = lambda key, dd: href("protocol", **keep(sort=key if key != "when" else "", dir="asc" if dd == "asc" else "")) + "#timeline"
    chips = "".join(f'<a href="{href("protocol", **keep(kind=x))}#timeline" class="chip {"on" if x == k else ""}">{t} <small>{cnt[x]:,}</small></a>'
                    for x, t in FILTERS if cnt[x] or x == k)
    trs = "".join(f'<tr><td>{lt(r["ts"])}</td><td>{E(KIND_LABEL.get(r["kind"], r["kind"]))}</td><td class="dk">{E(r["file"] or "")}</td>'
                  f'<td class="dk">{_sha_cell(r)}</td><td>{_rel_cell(r)}</td><td class="dk">{_note(r)}</td></tr>' for r in rows[:500])
    tb = (SS.select(COLS, by, d, link) + f'<div class="tw"><table class="hist cal gov proto"><thead><tr>{SS.heads(COLS, by, d, link)}</tr></thead>'
          f'<tbody>{trs or "<tr><td colspan=6 class=na>No events in this view.</td></tr>"}</tbody></table></div>')
    q = qsx(kind=k)
    links = (f'{badge(False)}<a class="more" href="/api/v1/protocol.csv{q}" download>CSV →</a><a class="more" href="/api/v1/protocol{q}">API →</a>')
    foot = '<p class="cov dim small">Hourly check of minepoa.com/client/poa.mjs and /poa-web.mjs; bytes are hashed, never run · <a href="/about#protocol">Method</a></p>'
    return stats_row() + card(f"Protocol timeline · {len(rows):,}", f'<div class="chips">{chips}</div>' + tb + foot, links, cls="histc", id="timeline")
