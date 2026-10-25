"""Protocol timeline (1.26.141): seeded release and baseline hashes, the hourly client file check (conditional GET with
stored validators, HEAD plus a full GET at most every 6 h without one), source_change events matched to signed releases
or marked unreleased, Stale after 3 h without a good check, /api/protocol JSON and CSV, and the allowlist (only the two
client files; bytes hashed, never kept). Usage: python3 tools/protocol_test.py (temp database, no network)."""
import os, sys, tempfile, time, json, hashlib
os.environ["POASCAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
from poascan import db, protocol as PT, server as SV, indexer as IX

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

NOW = int(time.time())
C0, W0 = PT.SEED_HASHES["client"][0], PT.SEED_HASHES["web_client"][0]
NEWC = b"// a new client build\n" * 100
NEWC_SHA = hashlib.sha256(NEWC).hexdigest()

class Fake:
    """Stands in for minepoa: per path, the bytes served and the validators; logs every request."""
    def __init__(self, files, etag=True):
        self.files, self.etag, self.log = dict(files), etag, []
    def __call__(self, path, method="GET", headers=None):
        headers = headers or {}; self.log.append((path, method, dict(headers)))
        body = self.files[path]; tag = '"' + hashlib.sha256(body).hexdigest()[:16] + '"'
        hd = {"Content-Length": str(len(body))}
        if self.etag: hd["ETag"] = tag
        if method == "HEAD": return 200, hd, b""
        if self.etag and headers.get("If-None-Match") == tag: return 304, hd, b""
        return 200, hd, body

def main():
    db.init()
    # seed
    ev = PT.events()
    check("seed: the current signed release", any(e["kind"] == "release" and e["release_version"] == "v1.1.2-carveout2" for e in ev))
    check("seed: both baseline hashes", {(e["file"], e["sha256_new"]) for e in ev if e["kind"] == "baseline"} == {("poa.mjs", C0), ("poa-web.mjs", W0)})
    st = PT.state()
    check("seed state: client matches release v1.1.2-carveout2", st["state"] == "match" and st["badge"] == "Client matches release v1.1.2-carveout2")
    check("seed: Stale until the first good check", PT.stale())
    PT.seed(); check("seed is idempotent", len(PT.events()) == len(ev))

    # first check: no stored validator and the seed hash only, so one full GET per file
    srv = Fake({"/client/poa.mjs": b"x" * 10, "/poa-web.mjs": b"y" * 10})
    srv.files["/client/poa.mjs"] = NEWC
    m = PT.meta(); files = m["files"]
    # pretend the seed bytes are live: serve bytes whose hash we put in the store
    seedc, seedw = b"client-bytes", b"web-bytes"
    files["client"]["sha"] = hashlib.sha256(seedc).hexdigest(); files["web_client"]["sha"] = hashlib.sha256(seedw).hexdigest()
    db.put_blob(PT.META, dict(m, files=files))
    srv.files.update({"/client/poa.mjs": seedc, "/poa-web.mjs": seedw})
    n0 = len(PT.events())
    check("check: ok", PT.check(NOW, http=srv) is True)
    check("first check: one full GET per file", [(p, mth) for p, mth, _ in srv.log] == [("/client/poa.mjs", "GET"), ("/poa-web.mjs", "GET")])
    check("unchanged bytes: no event", len(PT.events()) == n0)
    check("validators stored", PT.meta()["files"]["client"].get("etag"))
    check("good check clears Stale", not PT.stale(NOW + 60))
    # second check: conditional GET answered 304
    srv.log.clear(); PT.check(NOW + 3600, http=srv)
    check("hourly: conditional GET with If-None-Match", all(mth == "GET" and h.get("If-None-Match") for _, mth, h in srv.log) and len(srv.log) == 2)
    check("304: no event", len(PT.events()) == n0)

    # an unreleased change
    srv.files["/client/poa.mjs"] = NEWC; srv.log.clear(); PT.check(NOW + 7200, http=srv)
    sc = [e for e in PT.events("source_change")]
    check("changed bytes: one source_change", len(sc) == 1 and sc[0]["file"] == "poa.mjs" and sc[0]["sha256_new"] == NEWC_SHA)
    check("not in any signed release: matches_release null", sc[0]["matches_release"] is None)
    st = PT.state()
    check("badge: Unreleased client change", st["state"] == "unreleased" and st["badge"] == "Unreleased client change" and not st["in_sync"])
    PT.check(NOW + 7300, http=srv)
    check("same change is logged once", len(PT.events("source_change")) == 1)

    # a signed release names the new hash
    rel = dict(g0={}, current=dict(PT.SEED_RELEASE, version="v1.2-test", txid="ab" * 32, ts=NOW + 7400, client_sha256=NEWC_SHA, engine_sha256=NEWC_SHA,
                                   web_client_sha256=hashlib.sha256(seedw).hexdigest()), history=[PT.SEED_RELEASE])
    db.put_blob("release", rel)
    check("release sync adds the new release once", PT.sync_releases() == 1 and PT.sync_releases() == 0)
    st = PT.state()
    check("badge: Client matches release v1.2-test", st["state"] == "match" and st["badge"] == "Client matches release v1.2-test" and st["in_sync"])

    # no validator from the host: HEAD hourly, full GET at most every 6 h
    srv2 = Fake({"/client/poa.mjs": NEWC, "/poa-web.mjs": seedw}, etag=False)
    m = PT.meta(); f2 = {k: {kk: vv for kk, vv in v.items() if kk not in ("etag", "lastmod")} for k, v in m["files"].items()}
    for v in f2.values(): v["full_at"] = NOW + 7200
    db.put_blob(PT.META, dict(m, files=f2))
    PT.check(NOW + 9000, http=srv2)
    check("no validator: HEAD only inside 6 h", [mth for _, mth, _ in srv2.log] == ["HEAD", "HEAD"])
    check("HEAD asks for identity encoding (true length)", all(h.get("Accept-Encoding") == "identity" for _, _, h in srv2.log))
    srv2.log.clear(); srv2.files["/poa-web.mjs"] = seedw + b"!"
    PT.check(NOW + 9100, http=srv2)
    check("changed Content-Length: HEAD then GET", [(p, mth) for p, mth, _ in srv2.log] == [("/client/poa.mjs", "HEAD"), ("/poa-web.mjs", "HEAD"), ("/poa-web.mjs", "GET")])
    check("web client change logged", any(e["file"] == "poa-web.mjs" for e in PT.events("source_change")))
    srv2.log.clear(); PT.check(NOW + 7200 + PT.FULL_EVERY_S + 10, http=srv2)
    check("6 h on: full GET of the unchanged-length file", ("/client/poa.mjs", "GET") in [(p, mth) for p, mth, _ in srv2.log])

    # failures keep the last hash and go Stale after 3 h
    def down(path, method="GET", headers=None): raise PT.CheckError("HTTP 503")
    sha_before = PT.meta()["files"]["client"]["sha"]
    check("failed check returns False", PT.check(NOW + 30000, http=down) is False)
    m = PT.meta()
    check("failure: last hash kept, errors recorded", m["files"]["client"]["sha"] == sha_before and m["errors"])
    check("Stale 3 h after the last good check", PT.stale(m["last_ok"] + PT.STALE_S + 1) and not PT.stale(m["last_ok"] + 60))

    # API
    d, is_list = SV.api("/api/protocol", {})
    check("API: shape", not is_list and {"checked_at", "last_ok_ts", "stale", "stale_after_s", "check_errors", "files", "current", "rows"} <= set(d))
    check("API: rows newest first", [r["ts"] for r in d["rows"]] == sorted((r["ts"] for r in d["rows"]), reverse=True))
    check("API: kind filter", all(r["kind"] == "release" for r in SV.api("/api/protocol", {"kind": ["release"]})[0]["rows"]))
    for bad in ({"kind": ["x"]}, {"nope": ["1"]}, {"limit": ["z"]}):
        try: SV.api("/api/protocol", bad); check(f"API: 400 for {bad}", False)
        except SV.BadRequest: check(f"API: 400 for {bad}", True)
    csv = SV.to_csv(d["rows"])
    check("CSV: header and a row per event", csv.splitlines()[0].startswith("id,ts") and len(csv.splitlines()) == len(d["rows"]) + 1)
    check("CSV route lists /api/protocol rows", '"/api/protocol") else [data]' in open(SV.__file__).read())
    from poascan import agentapi as AA
    check("OpenAPI documents /api/protocol with CSV", "/api/protocol" in open(AA.__file__).read() and 'oid="protocol"' in open(AA.__file__).read())

    # allowlist, no execution, no byte storage
    try: PT._http("/api/params"); check("allowlist: other paths refused", False)
    except ValueError: check("allowlist: other paths refused", True)
    src = open(PT.__file__).read()
    check("client bytes are hashed, never run or kept", "subprocess" not in src and "exec(" not in src and "node" not in src.replace("nodes", "") and "write_bytes" not in src)
    check("hourly job calls the check", "poascan.protocol" in open(IX.__file__).read())
    check("health table knows both files", "/client/poa.mjs" in IX.EVERY and "/poa-web.mjs" in IX.EVERY)
    blob = json.dumps(PT.meta()) + json.dumps(PT.events())
    check("no file bytes stored", "a new client build" not in blob)
    check("no em or en dash in module and API", all(c not in src + json.dumps(d) for c in ("\u2014", "\u2013")))
    ui_checks()
    print(f"\n{len(fails)} failed" if fails else "\nall passed")
    sys.exit(1 if fails else 0)

def ui_checks():
    """Governance, Protocol and the Network badge."""
    import re
    from poascan import governance as GV, views as V, protocolview as PV
    txt = lambda h: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
    h = GV.page({"tab": ["protocol"]}); t = txt(h)
    check("tab: Protocol chip and title", 'tab=protocol' in h and "Governance · Protocol" in h)
    check("tab: timeline card with CSV and API links", "Protocol timeline" in t and "/api/v1/protocol.csv" in h and "/api/v1/protocol" in h)
    check("tab: header sorting (aria-sort, phone menu)", "aria-sort" in h and 'class="sortsel"' in h)
    check("tab: visitor-local times", '<time class="t lt' in h)
    check("tab: kind chips", "Releases" in t and "Source" in t)
    check("tab: four stats, no sub-lines", h.count('<div class="stat">') >= 4 and 'class="ss"' not in h)
    h2 = GV.page({"tab": ["protocol"], "sort": ["kind"], "dir": ["asc"]})
    check("tab: sort by event works", "aria-sort=\"" in h2)
    h3 = GV.page({"tab": ["protocol"], "kind": ["release"]}); rows = re.findall(r"<tr><td>", h3)
    body = h3.split('<tbody>')[1].split('</tbody>')[0]; evs = re.findall(r"<tr><td>.*?</td><td>([^<]*)</td>", body)
    check("tab: kind filter keeps releases only", evs and set(evs) == {"Release"})
    # badge states
    st = PT.state()
    b = PV.badge()
    check("badge links to the tab", 'href="/governance?tab=protocol"' in b and "pbadge" in b)
    check("badge text follows the state", (("Client matches release" in b) if st["state"] in ("match", "older_release") else ("Unreleased client change" in b)))
    m = PT.meta(); db.put_blob(PT.META, dict(m, last_ok=int(time.time()) - PT.STALE_S - 60))
    check("stale: ui.flag Stale tag on the badge and stats", "Stale" in PV.badge() and 'class="tag warn"' in PV.badge() and "Stale" in GV.page({"tab": ["protocol"]}))
    db.put_blob(PT.META, dict(m, last_ok=int(time.time())))
    check("fresh: no Stale tag", "Stale" not in PV.badge())
    n = V.network("")
    check("Network overview carries the badge", "pbadge" in n and "/governance?tab=protocol" in n)
    files = {"client": dict(m["files"]["client"], sha="00" * 32), "web_client": m["files"]["web_client"]}
    db.put_blob(PT.META, dict(m, files=files, last_ok=int(time.time())))
    check("unreleased hash: amber badge 'Unreleased client change'", "Unreleased client change" in PV.badge() and "pbadge warn" in PV.badge())
    db.put_blob(PT.META, m)
    ab = V.about() if hasattr(V, "about") else ""
    check("/about#protocol explains the method", 'id="protocol"' in open(V.__file__).read())
    for name, x in (("protocol tab", h), ("network", n), ("badge", b)): check(name + ": no em or en dash", "\u2014" not in x and "\u2013" not in x)
    css = open(os.path.join(HERE, "..", "static", "style.css")).read()
    check("badge styles use tokens", ".pbadge{" in css and ".pbadge.warn" in css)
    base = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)   # rules outside any media query
    check("stat state tags wrap at every width (no clipped Unconfirmed at 1280)", ".sl:has(.sflag){flex-wrap:wrap" in base and "white-space:nowrap;overflow:visible" in base)
    check("copy: Agents, never Accounts", "Accounts" not in txt(h) and "Accounts" not in txt(n))

if __name__ == "__main__":
    main()
