"""On-chain AC1 artwork, assembled from archived transfer memos.

Any multipart AC1 message (m parts plus an s seal) is a candidate work. Bytes are
joined in part order, hashed, and checked against the seal. A data URI is decoded
only after that check. Verified rasters are written to a local cache and listed on
the Art tab automatically. This module never fetches a remote image and never emits
SVG. Incomplete or failed seals are skipped.
"""
import base64, hashlib, os, re, threading
from . import db

CID_RE = re.compile(r"^[0-9a-f]{8,32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SEAL_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
# Only raster data URIs. No SVG, no remote http(s).
URI_RE = re.compile(r"^data:image/(gif|png|jpeg|webp);base64,([A-Za-z0-9+/=\s]+)$")
EXT = {"image/gif": ".gif", "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_PARTS = 256
MAX_JOINED = 512 * 1024
MAX_RAW = 256 * 1024

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Optional credits and hash-checked fallback rasters for known works. Listing and
# decode do not require an entry; a matching on-chain seal is enough.
# source= URLs are artist citations, not fetched.
KNOWN = {
    "e85fe08f": dict(
        name="Genesis",
        credit="Digivatar",
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
    ),
}

OFFICIAL = False
OFFICIAL_NOTE = ("Unofficial assembly of an AC1 multipart memo from this archive. "
                 "A raster is shown only when the joined bytes match the on-chain seal.")

_lock = threading.Lock()
_cache = {}
_listed = [None]


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
        if part < 1 or total < 1 or part > total or total > MAX_PARTS:
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


def _cache_dir():
    env = os.environ.get("POASCAN_ART_CACHE")
    if env:
        root = env
    else:
        root = os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), "art-cache")
    os.makedirs(root, exist_ok=True)
    return root


def _static_ok(known):
    gif = os.path.join(ROOT, "static", known["gif"]) if known.get("gif") else None
    still = os.path.join(ROOT, "static", known["still"]) if known.get("still") else None
    if not gif or not os.path.isfile(gif):
        return None
    if known.get("file_sha") and _file_sha(gif) != known["file_sha"]:
        return None
    if still and not os.path.isfile(still):
        still = None
    return dict(gif="/static/" + known["gif"] if known.get("gif") else None,
                still=("/static/" + known["still"]) if still else None,
                via="static")


def _gif_skip_blocks(data, i):
    end = len(data)
    while i < end:
        n = data[i]
        i += 1
        if n == 0:
            return i
        i += n
    return None


def gif_info(data):
    """Logical size, frame count, and first-frame delay in ms for a GIF, or None."""
    if not data or len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    w = int.from_bytes(data[6:8], "little")
    h = int.from_bytes(data[8:10], "little")
    i = 13
    if data[10] & 0x80:
        i += 3 * (2 ** ((data[10] & 7) + 1))
    frames = 0
    delay_cs = None
    end = len(data)
    pending = None
    while i < end:
        b = data[i]
        if b == 0x3B:
            break
        if b == 0x21:
            if i + 2 >= end:
                break
            label = data[i + 1]
            if label == 0xF9 and i + 8 <= end and data[i + 2] == 4:
                pending = int.from_bytes(data[i + 4:i + 6], "little")
                i = i + 8
                continue
            i = _gif_skip_blocks(data, i + 2)
            if i is None:
                break
            continue
        if b == 0x2C:
            frames += 1
            if delay_cs is None:
                delay_cs = pending
            if i + 10 > end:
                break
            local = data[i + 9]
            i += 10
            if local & 0x80:
                i += 3 * (2 ** ((local & 7) + 1))
            i += 1
            i = _gif_skip_blocks(data, i)
            if i is None:
                break
            pending = None
            continue
        break
    ms = None
    if delay_cs is not None:
        ms = 100 if delay_cs <= 0 else delay_cs * 10
    return dict(width=w, height=h, frames=max(1, frames), ms=ms)


def gif_still(data):
    """Build a one-frame GIF from the first image of an animated GIF. None if it cannot be parsed."""
    if not data or len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    i = 13
    if data[10] & 0x80:
        i += 3 * (2 ** ((data[10] & 7) + 1))
    out = bytearray(data[:i])
    gce = b""
    end = len(data)
    while i < end:
        b = data[i]
        if b == 0x3B:
            break
        if b == 0x21:
            if i + 2 >= end:
                break
            label = data[i + 1]
            start = i
            if label == 0xF9 and i + 8 <= end and data[i + 2] == 4:
                gce = data[start:i + 8]
                i = i + 8
                continue
            i = _gif_skip_blocks(data, i + 2)
            if i is None:
                return None
            continue
        if b == 0x2C:
            start = i
            if i + 10 > end:
                return None
            local = data[i + 9]
            i += 10
            if local & 0x80:
                i += 3 * (2 ** ((local & 7) + 1))
            i += 1
            i = _gif_skip_blocks(data, i)
            if i is None:
                return None
            out += gce + data[start:i] + b"\x3b"
            return bytes(out)
        return None
    return None


def _png_size(data):
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


def _jpeg_size(data):
    if data[:2] != b"\xff\xd8":
        return None
    i, end = 2, len(data)
    while i + 8 < end:
        if data[i] != 0xFF:
            return None
        while i < end and data[i] == 0xFF:
            i += 1
        if i >= end:
            return None
        marker = data[i]
        i += 1
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if i + 2 > end:
            return None
        seglen = int.from_bytes(data[i:i + 2], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF) and seglen >= 7:
            return int.from_bytes(data[i + 5:i + 7], "big"), int.from_bytes(data[i + 3:i + 5], "big")
        i += seglen
    return None


def _webp_size(data):
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    kind = data[12:16]
    if kind == b"VP8X" and len(data) >= 30:
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return w, h
    if kind == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
    if kind == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def raster_info(raw, mime):
    """Width, height, frame count and delay for a verified raster."""
    out = dict(width=None, height=None, frames=1, ms=None)
    if mime == "image/gif":
        info = gif_info(raw)
        if info:
            out.update(info)
        return out
    size = None
    if mime == "image/png":
        size = _png_size(raw)
    elif mime == "image/jpeg":
        size = _jpeg_size(raw)
    elif mime == "image/webp":
        size = _webp_size(raw)
    if size:
        out["width"], out["height"] = size
    return out


def _blurb(info):
    w, h = info.get("width"), info.get("height")
    if not w or not h:
        return ""
    frames = int(info.get("frames") or 1)
    ms = info.get("ms")
    if frames > 1 and ms:
        fps = 1000.0 / ms
        fps_s = f"{fps:.1f}".rstrip("0").rstrip(".")
        return f"{w} x {h}, {fps_s} fps."
    return f"{w} x {h}."


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
    if total > MAX_PARTS:
        return dict(ok=False, reason="too_many_parts", cid=cid, total=total)
    missing = [i for i in range(1, total + 1) if i not in parts]
    if missing:
        return dict(ok=False, reason="incomplete", cid=cid, have=len(parts), total=total, missing=missing)
    if not seals:
        return dict(ok=False, reason="no_seal", cid=cid, have=len(parts), total=total)
    seals.sort(key=lambda x: (x[0], x[1]))
    seal_sha = seals[0][2]
    joined = "".join(parts[i][2] for i in range(1, total + 1))
    if len(joined) > MAX_JOINED:
        return dict(ok=False, reason="too_large", cid=cid)
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
    if len(raw) > MAX_RAW:
        return dict(ok=False, reason="too_large", cid=cid, joined_sha=joined_sha)
    raster = (raw[:6] in (b"GIF87a", b"GIF89a") or raw[:8] == b"\x89PNG\r\n\x1a\n"
              or raw[:2] == b"\xff\xd8" or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"))
    if not raster:
        return dict(ok=False, reason="not_raster", cid=cid, joined_sha=joined_sha)
    file_sha = hashlib.sha256(raw).hexdigest()
    author = parts[1][4]
    info = raster_info(raw, mime)
    return dict(ok=True, reason=None, cid=cid, joined_sha=joined_sha, seal_sha=seal_sha,
                file_sha=file_sha, mime=mime, raw=raw, have=total, total=total,
                addr=author, seal_txid=seals[0][1], seal_ts=seals[0][0],
                width=info.get("width"), height=info.get("height"),
                frames=info.get("frames") or 1, ms=info.get("ms"))


def _write_atomic(path, blob):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _store_raster(cid, raw, mime, file_sha):
    """Write the verified raster and a still frame into the local cache. Returns URL paths."""
    ext = EXT.get(mime)
    if not ext:
        return None
    root = _cache_dir()
    path = os.path.join(root, cid + ext)
    if not (os.path.isfile(path) and _file_sha(path) == file_sha):
        _write_atomic(path, raw)
    still_bytes, still_ext = raw, ext
    if mime == "image/gif":
        info = gif_info(raw) or {}
        if int(info.get("frames") or 1) > 1:
            still = gif_still(raw)
            if still:
                still_bytes, still_ext = still, ".gif"
    still_path = os.path.join(root, cid + "-still" + still_ext)
    still_sha_path = still_path  # rewrite if missing
    if not os.path.isfile(still_path):
        _write_atomic(still_path, still_bytes)
    return dict(gif="/art/raster/" + cid,
                still="/art/raster/" + cid + "/still",
                mime=mime,
                via="cache")


def raster(cid, still=False):
    """Return (bytes, mime) for a verified cached raster, or None."""
    cid = (cid or "").lower()
    if not CID_RE.fullmatch(cid):
        return None
    row = work(cid)
    if not row.get("ok"):
        return None
    # Prefer the cache written from a matching seal; fall back to a hash-checked static file.
    root = _cache_dir()
    if still:
        for ext, mime in ((".gif", "image/gif"), (".png", "image/png"), (".jpg", "image/jpeg"), (".webp", "image/webp")):
            path = os.path.join(root, cid + "-still" + ext)
            if os.path.isfile(path):
                return open(path, "rb").read(), mime
        still_rel = (row.get("still") or "")
        if still_rel.startswith("/static/"):
            path = os.path.join(ROOT, still_rel.lstrip("/"))
            if os.path.isfile(path):
                mime = {".gif": "image/gif", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(
                    os.path.splitext(path)[1], "application/octet-stream")
                return open(path, "rb").read(), mime
        still = False
    if not still:
        for ext, mime in ((".gif", "image/gif"), (".png", "image/png"), (".jpg", "image/jpeg"), (".webp", "image/webp")):
            path = os.path.join(root, cid + ext)
            if os.path.isfile(path) and (not row.get("file_sha") or _file_sha(path) == row.get("file_sha")):
                return open(path, "rb").read(), mime
        gif_rel = (row.get("gif") or "")
        if gif_rel.startswith("/static/"):
            path = os.path.join(ROOT, gif_rel.lstrip("/"))
            if os.path.isfile(path):
                mime = {".gif": "image/gif", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(
                    os.path.splitext(path)[1], "application/octet-stream")
                if not row.get("file_sha") or _file_sha(path) == row.get("file_sha"):
                    return open(path, "rb").read(), mime
    return None


def _public(row):
    """Strip raw bytes from a work dict before it leaves this module."""
    out = dict(row)
    out.pop("raw", None)
    return out


def _describe(cid, assembled=None, via=None, gif=None, still=None, reason=None, ok=False):
    known = KNOWN.get(cid) or {}
    info = {}
    if assembled and assembled.get("ok"):
        info = dict(width=assembled.get("width"), height=assembled.get("height"),
                    frames=assembled.get("frames") or 1, ms=assembled.get("ms"))
    elif known:
        info = dict(width=known.get("width"), height=known.get("height"),
                    frames=known.get("frames") or 1, ms=known.get("ms"))
    name = known.get("name") or cid
    blurb = known.get("blurb") or _blurb(info)
    return dict(
        id=cid, name=name, credit=known.get("credit"), blurb=blurb,
        addr=(assembled or {}).get("addr") or known.get("addr"),
        official=OFFICIAL, official_note=OFFICIAL_NOTE,
        source=known.get("source"), post=known.get("post"),
        announce_txid=known.get("announce_txid"),
        width=info.get("width"), height=info.get("height"),
        frames=info.get("frames") or 1, ms=info.get("ms"),
        parts=(assembled or {}).get("total") or known.get("parts"),
        expect_joined=known.get("joined_sha"), expect_file=known.get("file_sha"),
        ok=ok, gif=gif, still=still, via=via, reason=reason,
        joined_sha=(assembled or {}).get("joined_sha") or known.get("joined_sha"),
        file_sha=(assembled or {}).get("file_sha") or known.get("file_sha"),
        mime=(assembled or {}).get("mime") or known.get("mime"),
        seal_txid=(assembled or {}).get("seal_txid"),
        seal_ts=(assembled or {}).get("seal_ts"),
    )


def work(cid):
    """Assemble, verify, and describe one work by AC1 id. Cache-first. Local txs or a hash-checked static raster."""
    cid = (cid or "").lower()
    if not CID_RE.fullmatch(cid):
        return dict(ok=False, official=OFFICIAL, official_note=OFFICIAL_NOTE, reason="bad_id", id=cid)
    known = KNOWN.get(cid)
    with _lock:
        if cid in _cache:
            return _public(_cache[cid])
        assembled = None
        try:
            assembled = assemble(cid)
        except Exception:
            assembled = dict(ok=False, reason="assemble_error")
        if assembled and assembled.get("ok"):
            if known and known.get("joined_sha") and (
                assembled["joined_sha"] != known["joined_sha"] or assembled["file_sha"] != known["file_sha"]
            ):
                out = _describe(cid, assembled, reason="digest_mismatch", ok=False)
                out["joined_sha"] = assembled["joined_sha"]
                out["file_sha"] = assembled["file_sha"]
                _cache[cid] = out
                return _public(out)
            stored = None
            try:
                stored = _store_raster(cid, assembled["raw"], assembled["mime"], assembled["file_sha"])
            except OSError:
                stored = None
            gif = still = None
            via = "archive"
            if stored:
                gif, still, via = stored["gif"], stored["still"], "archive"
            elif known:
                st = _static_ok(known)
                if st:
                    gif, still, via = st["gif"], st["still"], "archive"
            out = _describe(cid, assembled, via=via, gif=gif, still=still, ok=True)
            _cache[cid] = out
            return _public(out)
        # No complete archive memo set: serve a committed raster only if its digest still matches.
        if known:
            st = _static_ok(known)
            if st:
                out = _describe(cid, via="static", gif=st["gif"], still=st["still"],
                                reason="static_hash_ok", ok=True)
                _cache[cid] = out
                return _public(out)
        out = _describe(cid, assembled, reason=(assembled or {}).get("reason") or "unverified", ok=False)
        _cache[cid] = out
        return _public(out)


def discover_cids():
    """AC1 message ids that have a final on-chain seal in this archive, in first-seal order."""
    rows = db.q(
        "SELECT id, memo, ts FROM txs "
        "WHERE type='transfer' AND final=1 AND memo LIKE 'AC1|s|%' "
        "ORDER BY ts, id"
    )
    cids, seen = [], set()
    for r in rows:
        p = parse_ac1_art(r.get("memo") or "")
        if not p or p.get("op") != "s":
            continue
        cid = p["cid"]
        if cid in seen:
            continue
        seen.add(cid)
        cids.append(cid)
    # Keep a known fallback work visible even if this archive has not yet stored its memos.
    for cid in KNOWN:
        if cid not in seen:
            cids.append(cid)
    return cids


def works():
    """Verified works only. Failed or incomplete seals are omitted.
    The listing is a snapshot: rebuilt after ingest invalidates it, never by a visitor request
    calling backfill (that used to reassemble every work on each Art page view)."""
    with _lock:
        if _listed[0] is not None:
            return list(_listed[0])
    rows = []
    for cid in discover_cids():
        row = work(cid)
        if row.get("ok") and (row.get("gif") or row.get("still")):
            rows.append(row)
    rows.sort(key=lambda r: (int(r.get("seal_ts") or 0) or 10**12, r.get("id") or ""))
    with _lock:
        _listed[0] = list(rows)
    return list(rows)


def invalidate(cids=None):
    """Drop cached assemblies so the next read reassembles from txs."""
    with _lock:
        if cids is None:
            _cache.clear()
        else:
            for c in cids:
                _cache.pop((c or "").lower(), None)
        _listed[0] = None


def ingest(rows, source=""):
    """Notice AC1 artwork memos in a local upsert batch and drop stale assemblies. No upstream reads."""
    cids = set()
    for r in rows or []:
        if (r.get("type") or "") != "transfer":
            continue
        p = parse_ac1_art(r.get("memo") or "")
        if p and p.get("cid"):
            cids.add(p["cid"])
    if cids:
        invalidate(cids)
    return len(cids)


def backfill():
    """Reassemble every sealed AC1 work from transfer memos already in txs. Local only."""
    invalidate()
    n = 0
    for cid in discover_cids():
        row = work(cid)
        if row.get("ok"):
            n += 1
    return n


def coverage():
    rows = works()
    return dict(official=OFFICIAL, official_note=OFFICIAL_NOTE,
                works=len(rows), checked=len(rows),
                ordering="part_number",
                ordering_note="AC1 parts join in part order. The first (ts, id) copy of each part is used.")


def http(path, qs):
    """Unofficial art-works read API. Lists every verified work, not a fixed catalog."""
    if qs:
        for k in qs:
            if k not in ("limit",):
                raise ValueError("unknown parameter")
    if path == "/api/art/works":
        return dict(official=OFFICIAL, official_note=OFFICIAL_NOTE, coverage=coverage(), works=works())
    m = re.match(r"^/api/art/works/([0-9a-f]{8,32})$", path)
    if m:
        row = work(m.group(1))
        if not row.get("ok"):
            raise LookupError("unknown work")
        return dict(official=OFFICIAL, official_note=OFFICIAL_NOTE, coverage=coverage(), work=row)
    if path.startswith("/api/art/"):
        raise LookupError("unknown endpoint")
    raise LookupError("unknown endpoint")
