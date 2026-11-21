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

# known Digivatar work: committed raster hashes
w = R.work("e85fe08f")
check("known work serves the hash-checked local GIF",
      w["ok"] is True and w["name"] == "Digivatar"
      and w["file_sha"] == "415322abc005eb984a8200868fb4fe6ddf0e126dd024b03e21d3eae7d232d217"
      and w["gif"] == "/apps/digivatar-e85fe08f.gif" and w["still"] == "/apps/digivatar-e85fe08f.png")

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poascan", "ac1art.py"), encoding="utf-8").read()
check("no em or en dash in ac1art.py", not any(d in src or d in R.OFFICIAL_NOTE for d in DASH))
check("module does not fetch remote images", "http://" not in src and "https://" not in src.split("source=")[0])

print("\n" + (f"{len(fails)} failed: " + ", ".join(fails) if fails else "all passed"))
sys.exit(1 if fails else 0)
