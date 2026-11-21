"""AC1 artwork assembly (1.26.413): join parts, check the seal, refuse SVG, no remote fetch, no typographic dashes.
Usage: python3 tools/ac1art_test.py"""
import base64, hashlib, os, sys, tempfile, copy
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "s.db"), POASCAN_INDEXER="0",
                  POA_BASE="http://127.0.0.1:9", POASCAN_MAINTENANCE="0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from poascan import db, ac1art as R, indexer as IX

fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
DASH = ("\u2014", "\u2013")
db.init()

# 1x1 GIF89a
GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
       b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
URI = "data:image/gif;base64," + base64.b64encode(GIF).decode()
# split into 2 parts
mid = len(URI) // 2
p1, p2 = URI[:mid], URI[mid:]
joined_sha = hashlib.sha256((p1 + p2).encode()).hexdigest()
file_sha = hashlib.sha256(GIF).hexdigest()
CID = "abcd1234"
A = "poa17w7ediEhWukn2oYbzR4dtjYBYB8L4L5pt18CkXo2ik7M"

def tid(n):
    return format(n, "064x")

def row(i, memo, fr=A, ts=1795070000, final=1):
    return dict(id=tid(i), type="transfer", from_addr=fr, to_addr=fr, amount="0.000001",
                memo=memo, ts=ts, final=final)

IX.upsert_txs([
    row(1, f"AC1|m|{CID}|01/02|{p1}", ts=1795070001),
    row(2, f"AC1|m|{CID}|02/02|{p2}", ts=1795070002),
    row(3, f"AC1|s|{CID}|sha256:{joined_sha}", ts=1795070003),
], "test")

got = R.assemble(CID)
check("two parts plus seal decode to the GIF",
      got["ok"] is True and got["joined_sha"] == joined_sha and got["file_sha"] == file_sha
      and got["mime"] == "image/gif" and got["raw"] == GIF and got["total"] == 2)

# later duplicate of part 1 must not win
IX.upsert_txs([row(4, f"AC1|m|{CID}|01/02|XXXX", ts=1795070100)], "test")
got2 = R.assemble(CID)
check("later part does not replace the first (ts, id)", got2["ok"] is True and got2["file_sha"] == file_sha)

# seal mismatch
bad = R.assemble(CID, rows=[
    row(1, f"AC1|m|{CID}|01/02|{p1}"),
    row(2, f"AC1|m|{CID}|02/02|{p2}"),
    row(3, f"AC1|s|{CID}|sha256:{'ab'*32}"),
])
check("wrong seal is refused", bad["ok"] is False and bad["reason"] == "seal_mismatch")

svg = "data:image/svg+xml;base64," + base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>").decode()
svg_sha = hashlib.sha256(svg.encode()).hexdigest()
svg_got = R.assemble("deadbeef", rows=[
    row(1, f"AC1|m|deadbeef|01/01|{svg}"),
    row(2, f"AC1|s|deadbeef|sha256:{svg_sha}"),
])
check("SVG data URI is refused", svg_got["ok"] is False and svg_got["reason"] == "unsupported_payload")

# known Digivatar work: committed raster hashes, titled Genesis with credit
w = R.work("e85fe08f")
check("known work is Genesis by Digivatar with a hash-checked local GIF",
      w["ok"] is True and w["name"] == "Genesis" and w.get("credit") == "Digivatar"
      and w["file_sha"] == "415322abc005eb984a8200868fb4fe6ddf0e126dd024b03e21d3eae7d232d217"
      and (w["gif"] in ("/static/apps/digivatar-e85fe08f.gif", "/art/raster/e85fe08f"))
      and (w["still"] in ("/static/apps/digivatar-e85fe08f.png", "/art/raster/e85fe08f/still")))

# still frame from the committed animated GIF
gif_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "apps", "digivatar-e85fe08f.gif")
raw_gif = open(gif_path, "rb").read()
info = R.gif_info(raw_gif)
still = R.gif_still(raw_gif)
sinfo = R.gif_info(still) if still else None
check("Genesis GIF is 28 x 28 with 12 frames at 80 ms",
      info and info["width"] == 28 and info["height"] == 28 and info["frames"] == 12 and info["ms"] == 80)
check("still extractor keeps one 28 x 28 frame",
      still and still.startswith(b"GIF89a") and sinfo and sinfo["frames"] == 1
      and sinfo["width"] == 28 and sinfo["height"] == 28)

# second synthetic artwork (PNG), not in KNOWN, must be auto-listed after a matching seal
import struct, zlib
def _png(w=2, h=2):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\xff\x00" * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
PNG = _png()
URI2 = "data:image/png;base64," + base64.b64encode(PNG).decode()
mid2 = len(URI2) // 2
q1, q2 = URI2[:mid2], URI2[mid2:]
sha2 = hashlib.sha256((q1 + q2).encode()).hexdigest()
file2 = hashlib.sha256(PNG).hexdigest()
CID2 = "b0b0cafe"
IX.upsert_txs([
    row(11, f"AC1|m|{CID2}|01/02|{q1}", ts=1795071001),
    row(12, f"AC1|m|{CID2}|02/02|{q2}", ts=1795071002),
    row(13, f"AC1|s|{CID2}|sha256:{sha2}", ts=1795071003),
], "test")
R.invalidate()
got3 = R.assemble(CID2)
check("second synthetic PNG work decodes against its seal",
      got3["ok"] is True and got3["file_sha"] == file2 and got3["mime"] == "image/png"
      and got3["width"] == 2 and got3["height"] == 2)
listed = {r["id"]: r for r in R.works()}
check("works() auto-lists the second synthetic work without a KNOWN entry",
      CID2 in listed and listed[CID2]["ok"] is True and listed[CID2]["name"] == CID2
      and listed[CID2]["gif"] == "/art/raster/" + CID2
      and listed[CID2].get("credit") in (None, ""))
check("works() also lists the first synthetic GIF work",
      CID in listed and listed[CID]["ok"] is True)
blob = R.raster(CID2)
still_blob = R.raster(CID2, still=True)
check("cached raster and still are served for the new work",
      blob and blob[0] == PNG and blob[1] == "image/png" and still_blob and still_blob[0])

# a sealed but mismatched work is skipped, not shown as a broken card
CID3 = "dead0001"
IX.upsert_txs([
    row(21, f"AC1|m|{CID3}|01/01|{URI2}", ts=1795072001),
    row(22, f"AC1|s|{CID3}|sha256:{'ab'*32}", ts=1795072002),
], "test")
R.invalidate()
bad2 = R.assemble(CID3)
listed2 = {r["id"] for r in R.works()}
check("mismatched seal is not listed", bad2["ok"] is False and CID3 not in listed2)
try:
    R.http("/api/art/works/" + CID3, {})
    api_bad = "no-error"
except LookupError:
    api_bad = "404"
check("API 404s a failed work instead of returning a broken body", api_bad == "404")

api = R.http("/api/art/works", {})
ids = {r["id"] for r in api["works"]}
check("API lists every verified work, including the synthetic PNG",
      CID2 in ids and api["official"] is False and "raw" not in api["works"][0])

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "ac1art.py"), encoding="utf-8").read()
check("no em or en dash in ac1art.py", not any(d in src or d in R.OFFICIAL_NOTE for d in DASH))
check("module does not fetch remote images",
      "urlopen" not in src and "requests." not in src and "http://" not in src.split("source=")[0])

print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
