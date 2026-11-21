"""On-chain AC1 artwork, assembled from archived transfer memos.

A work is a multipart AC1 message (m parts plus an s seal). Bytes are joined in part
order, hashed, and checked against the seal. A data URI is decoded only after that
check. This module never fetches a remote image and never emits SVG.

Known work e85fe08f (Digivatar, Nov 19, 2026): 28 x 28 GIF, 12 frames at 80 ms.
Joined-parts sha256 70003a6a181d33d1c33ffe07d2336cc29ed978ac68ba53351d70ada72267df5f
and file sha256 415322abc005eb984a8200868fb4fe6ddf0e126dd024b03e21d3eae7d232d217 were
verified offline from POAScan's archive. A local raster is served only when those
digests still match.
"""
import base64, hashlib, os, re, threading
from . import db

CID_RE = re.compile(r"^[0-9a-f]{8,32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SEAL_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
# Only raster data URIs. No SVG, no remote http(s).
URI_RE = re.compile(r"^data:image/(gif|png|jpeg|webp);base64,([A-Za-z0-9+/=\s]+)$")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Digests for the known work, used to fail closed if a committed file is edited.
DIGIVATAR = dict(
    id="e85fe08f",
    name="Digivatar",
    blurb="28 x 28, 12.5 fps.",
    addr="poa1ANByoh2aHiEjE6KS5UoXtQLbx1Eh9ejy89VwyNbQFVzT",
    parts=54,
    width=28,
    height=28,
    frames=12,
    ms=80,
    joined_sha="70003a6a181d33d1c33ffe07d2336cc29ed978ac68ba53351d70ada72267df5f",
    file_sha="415322abc005eb984a8200868fb4fe6ddf0e126dd024b03e21d3eae7d232d217",
    mime="image/gif",
    source="https://x.com/Digivatar/status/2123565549494075786",
    post=3161,
    announce_txid="98d89436d7897451db4e433231bb8b0abac815249722a2e064e0c414fb97dba6",
    gif="apps/digivatar-e85fe08f.gif",
    still="apps/digivatar-e85fe08f.png",
)

WORKS = (DIGIVATAR,)
WORK_BY = {w["id"]: w for w in WORKS}

OFFICIAL = False
OFFICIAL_NOTE = ("Unofficial assembly of an AC1 multipart memo from this archive. "
                 "A raster is shown only when the joined bytes match the on-chain seal.")

_lock = threading.Lock()
_cache = {}


def parse_ac1_art(memo):
    """Parse AC1 multipart (m) or seal (s) memos used for artwork. Other ops return None."""
    if not memo or not memo.startswith("AC1|"):
        return None
    bits = memo.split("|")
    if len(bits) < 4:
        return None
    op = bits[1]
    if op == "m" and len(bits) >= 5:
        if not CID_RE.fullmatch(bits[2]):
            return None
        m = re.fullmatch(r"(\d{1,3})/(\d{1,3})", bits[3])
        if not m:
            return None
        part, total = int(m.group(1)), int(m.group(2))
        if part < 1 or total < 1 or part > total:
            return None
        return dict(op="m", cid=bits[2], part=part, total=total, text="|".join(bits[4:]))
    if op == "s" and len(bits) >= 4:
        if not CID_RE.fullmatch(bits[2]):
            return None
        sm = SEAL_RE.fullmatch(bits[3])
        if not sm:
            return None
        return dict(op="s", cid=bits[2], sha=sm.group(1))
    return None


def _file_sha(path):
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()
    except OSError:
        return None


def _static_ok(work):
    gif = os.path.join(ROOT, "static", work["gif"]) if work.get("gif") else None
    still = os.path.join(ROOT, "static", work["still"]) if work.get("still") else None
    if not gif or not os.path.isfile(gif):
        return None
    if _file_sha(gif) != work["file_sha"]:
        return None
    if still and not os.path.isfile(still):
        still = None
    return dict(gif="/static/" + work["gif"] if work.get("gif") else None,
                still=("/static/" + work["still"]) if still else None,
                via="static")


def assemble(cid, rows=None):
    """Join final AC1 m parts for cid in part order, first (ts, id) wins a part, and check the seal.

    Returns a dict with ok, reason, joined_sha, file_sha, mime, raw, and counts; ok is False on any mismatch.
    """
    cid = (cid or "").lower()
    if not CID_RE.fullmatch(cid):
        return dict(ok=False, reason="bad_id", cid=cid)
    if rows is None:
        like_m = "AC1|m|" + cid + "|%"
        like_s = "AC1|s|" + cid + "|%"
        rows = db.q(
            "SELECT id, from_addr, memo, ts, final FROM txs "
            "WHERE type='transfer' AND final=1 AND (memo LIKE ? OR memo LIKE ?) "
            "ORDER BY ts, id",
            (like_m, like_s),
        )
    parts, seals, author = {}, [], None
    for r in rows:
        p = parse_ac1_art(r.get("memo") or "")
        if not p or p.get("cid") != cid:
            continue
        ts, tid = int(r.get("ts") or 0), r.get("id") or ""
        if p["op"] == "m":
            prev = parts.get(p["part"])
            if prev is None or (ts, tid) < (prev[0], prev[1]):
                parts[p["part"]] = (ts, tid, p["text"], p["total"], r.get("from_addr"))
        elif p["op"] == "s":
            seals.append((ts, tid, p["sha"], r.get("from_addr")))
    if not parts:
        return dict(ok=False, reason="no_parts", cid=cid)
    totals = {v[3] for v in parts.values()}
    if len(totals) != 1:
        return dict(ok=False, reason="mixed_total", cid=cid)
    total = next(iter(totals))
    missing = [i for i in range(1, total + 1) if i not in parts]
    if missing:
        return dict(ok=False, reason="incomplete", cid=cid, have=len(parts), total=total, missing=missing)
    if not seals:
        return dict(ok=False, reason="no_seal", cid=cid, have=len(parts), total=total)
    seals.sort(key=lambda x: (x[0], x[1]))
    seal_sha = seals[0][2]
    joined = "".join(parts[i][2] for i in range(1, total + 1))
    joined_sha = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    if joined_sha != seal_sha:
        return dict(ok=False, reason="seal_mismatch", cid=cid, joined_sha=joined_sha, seal_sha=seal_sha,
                    have=total, total=total)
    m = URI_RE.fullmatch(joined)
    if not m:
        return dict(ok=False, reason="unsupported_payload", cid=cid, joined_sha=joined_sha, seal_sha=seal_sha)
    mime = "image/" + m.group(1)
    try:
        raw = base64.b64decode(re.sub(r"\s+", "", m.group(2)), validate=False)
    except ValueError:
        return dict(ok=False, reason="bad_base64", cid=cid, joined_sha=joined_sha)
    raster = (raw[:6] in (b"GIF87a", b"GIF89a") or raw[:8] == b"\x89PNG\r\n\x1a\n"
              or raw[:2] == b"\xff\xd8" or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"))
    if not raster:
        return dict(ok=False, reason="not_raster", cid=cid, joined_sha=joined_sha)
    file_sha = hashlib.sha256(raw).hexdigest()
    author = parts[1][4]
    return dict(ok=True, reason=None, cid=cid, joined_sha=joined_sha, seal_sha=seal_sha,
                file_sha=file_sha, mime=mime, raw=raw, have=total, total=total,
                addr=author, seal_txid=seals[0][1], seal_ts=seals[0][0])


def work(cid="e85fe08f"):
    """Assemble, verify, and describe one known work. Cache-first. Local txs or a hash-checked static raster."""
    cid = (cid or "").lower()
    known = WORK_BY.get(cid)
    if not known:
        return dict(ok=False, official=OFFICIAL, official_note=OFFICIAL_NOTE, reason="unknown_work", id=cid)
    with _lock:
        if cid in _cache:
            return dict(_cache[cid])
        out = dict(id=cid, name=known["name"], blurb=known["blurb"], addr=known["addr"],
                   official=OFFICIAL, official_note=OFFICIAL_NOTE, source=known.get("source"),
                   post=known.get("post"), announce_txid=known.get("announce_txid"),
                   width=known["width"], height=known["height"], frames=known["frames"],
                   ms=known["ms"], parts=known["parts"],
                   expect_joined=known["joined_sha"], expect_file=known["file_sha"],
                   ok=False, gif=None, still=None, via=None, reason=None)
        assembled = None
        try:
            assembled = assemble(cid)
        except Exception:
            assembled = dict(ok=False, reason="assemble_error")
        if assembled and assembled.get("ok"):
            if assembled["joined_sha"] != known["joined_sha"] or assembled["file_sha"] != known["file_sha"]:
                out["reason"] = "digest_mismatch"
                out["joined_sha"] = assembled["joined_sha"]
                out["file_sha"] = assembled["file_sha"]
                _cache[cid] = out
                return dict(out)
            out.update(ok=True, reason=None, via="archive",
                       joined_sha=assembled["joined_sha"], file_sha=assembled["file_sha"],
                       seal_txid=assembled.get("seal_txid"), addr=assembled.get("addr") or known["addr"])
            st = _static_ok(known)
            if st:
                out["gif"], out["still"], out["via"] = st["gif"], st["still"], "archive"
            _cache[cid] = out
            return dict(out)
        # No complete archive memo set: serve the committed raster only if its digest still matches.
        st = _static_ok(known)
        if st:
            out.update(ok=True, reason="static_hash_ok", via="static",
                       gif=st["gif"], still=st["still"],
                       joined_sha=known["joined_sha"], file_sha=known["file_sha"])
            _cache[cid] = out
            return dict(out)
        out["reason"] = (assembled or {}).get("reason") or "unverified"
        _cache[cid] = out
        return dict(out)


def works():
    return [work(w["id"]) for w in WORKS]


def coverage():
    rows = works()
    checked = sum(1 for r in rows if r.get("ok"))
    return dict(official=OFFICIAL, official_note=OFFICIAL_NOTE,
                works=len(rows), checked=checked,
                ordering="part_number",
                ordering_note="AC1 parts join in part order. The first (ts, id) copy of each part is used.")


def http(path, qs):
    """Unofficial art-works read API."""
    if qs:
        for k in qs:
            if k not in ("limit",):
                raise ValueError("unknown parameter")
    if path == "/api/art/works":
        return dict(official=OFFICIAL, official_note=OFFICIAL_NOTE, coverage=coverage(), works=works())
    m = re.match(r"^/api/art/works/([0-9a-f]{8,32})$", path)
    if m:
        row = work(m.group(1))
        if not WORK_BY.get(m.group(1)):
            raise LookupError("unknown work")
        return dict(official=OFFICIAL, official_note=OFFICIAL_NOTE, coverage=coverage(), work=row)
    if path.startswith("/api/art/"):
        raise LookupError("unknown endpoint")
    raise LookupError("unknown endpoint")
