"""Dev only: ?demo=motion on a local server replays the Bench motion (the close, new txs, counters) for previews and recordings.

It is off unless the process has POASCAN_DEV_DEMO=1, and never on Fly (FLY_APP_NAME is set on every Fly machine), so
poascan.io never serves the flag, the script or the seed: /dev/* answers 404 there like any unknown path. The seed is POAScan's
own archive (the local database), so the demo makes no upstream reads either."""
import json, os, time
from . import db
from .ui import REQ

ENABLED = os.environ.get("POASCAN_DEV_DEMO") == "1" and not os.environ.get("FLY_APP_NAME")
JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devdemo.js")

def active():
    """True on a request for ?demo=motion when the dev demo is enabled."""
    return ENABLED and (getattr(REQ, "qs", None) or {}).get("demo") == ["motion"]

def html_attr():
    return ' data-demo="motion"' if active() else ""

def script():
    return '<script src="/dev/demo-motion.js" defer></script>' if active() else ""

def seed():
    """The archive's latest 26 minutes: rows before the last two minutes are history, the last two are replayed as new txs.
    Each row: [lane, ts, atts, final, type, from_addr, name]. Plus the open epoch's numbers and the latest close."""
    from . import analytics as A, bench as BN
    top = (db.q1("SELECT MAX(ts) AS t FROM txs WHERE type IN ('challenge','attest-batch','grade-sealed')") or {}).get("t") or int(time.time())
    rows = db.q("SELECT type, ts, atts, final, from_addr FROM txs WHERE ts>=? AND ts<=? AND type IN ('challenge','attest-batch','grade-sealed') ORDER BY ts LIMIT 3000",
                (top - BN.WIN - 240, top))
    nm = A.forum_names(); o = A.open_epoch(); ep = A.epoch_rows(); last = ep[-1] if ep else {}
    out = [[BN._K[r["type"]], int(r["ts"]), int(r["atts"] or 0), 1 if r["final"] else 0, r["type"], r["from_addr"], nm.get(r["from_addr"])] for r in rows]
    # the archive's newest epoch tag with its answers and sealers, so a stale local copy still reads like a running epoch
    tag = (db.q1("SELECT epoch FROM txs WHERE type='challenge' AND epoch IS NOT NULL ORDER BY ts DESC LIMIT 1") or {}).get("epoch")
    ans = gr = None
    if tag is not None:
        a = db.q1("SELECT COUNT(*) AS n, MIN(ts) AS t FROM txs WHERE type='challenge' AND epoch=?", (tag,))
        ans = a["n"]; gr = db.q1("SELECT COUNT(DISTINCT from_addr) AS n FROM txs WHERE type='grade-sealed' AND ts>=? AND ts<=?", (a["t"] or 0, top))["n"]
    return dict(top=top, cut=top - 120, rows=out, epoch=tag if tag is not None else o.get("epoch"), answers=ans if ans is not None else o.get("answers"),
                graders=gr if gr is not None else o.get("graders"), pool=o.get("pool"),
                period=o.get("period") or 21600, last=dict(epoch=last.get("epoch"), settled=last.get("settled")))

def route(path):
    """(status, body, content type) for /dev/* while enabled, else None (the caller answers 404)."""
    if not ENABLED: return None
    if path == "/dev/demo-motion.js": return 200, open(JS, encoding="utf-8").read(), "text/javascript; charset=utf-8"
    if path == "/dev/demo-seed": return 200, json.dumps(seed(), separators=(",", ":")), "application/json"
    return None
