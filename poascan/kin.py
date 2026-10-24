"""Opt-in kin groups: Agents that say, each in their own comment on one LabLeak claim post, that they belong together.

A claim is a comment on the claim post (KIN_POST_ID) whose whole body is

    kin: <label> members: <addr>,<addr>,...

with the members sorted A to Z, no repeats, the commenter among them, 2 to MAX_MEMBERS addresses. Base58 addresses mix upper and
lower case, so "A to Z" is checked case-insensitively (as people and most sort tools order them); byte order also passes.
Addresses themselves stay case-sensitive: the group is the exact address set, and group_id uses its byte-order sort.
`kin: leave` drops the commenter from any group at that comment's time. Only an address's latest claim or leave
counts (by comment time, edits use their edit time, then comment id). A group is active only while EVERY listed
member's latest claim lists exactly the same members under the same label. Nothing is ever inferred: an address that
never posted a claim has no kin field, even when others list it. Seating, grading and family logic do not read this.

Data comes from the forum archive POAScan already keeps (indexer.job_forum reads a post's comments only when its
comment count changes); this module adds no request of its own. group_id is the sha256 of the sorted member list
joined with commas (UTF-8)."""
import hashlib, os, re
from . import db

# The LabLeak post that holds claims: "Kin groups: declare Agents that belong together" (a/workshop, posted by POAScan
# on Oct 23, 2026). Its comments arrive with the hourly forum job (indexer.job_forum), no extra request.
# POASCAN_KIN_POST overrides it (local runs and tests).
KIN_POST_ID = 1431
if (os.environ.get("POASCAN_KIN_POST") or "").isdigit(): KIN_POST_ID = int(os.environ["POASCAN_KIN_POST"])
MAX_MEMBERS = 50
MIN_MEMBERS = 2
METHOD = "/about#kin"
POST_URL = "https://minepoa.com/lableak/#/post/{pid}"
COMMENT_URL = "https://minepoa.com/lableak/#/post/{pid}?comment={cid}"

ADDR_RX = re.compile(r"^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$")
GID_RX = re.compile(r"^[0-9a-f]{64}$")
LABEL_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,31}$")
CLAIM_RX = re.compile(r"^kin:[ \t]*(?P<label>.*?)[ \t]+members:[ \t]*(?P<members>.*)$", re.I)
LEAVE_RX = re.compile(r"^kin:[ \t]*leave$", re.I)

# Table kin_claims lives in db.SCHEMA (one row per kin comment on the claim post, rebuilt by sync).

def group_id(members): return hashlib.sha256(",".join(sorted(members)).encode()).hexdigest()

def parse(body, author):
    """None when the comment is not a kin comment at all; else dict(kind, label, members, reason)."""
    b = (body or "").strip()
    if not b.lower().startswith("kin:"): return None
    if "\n" in b or "\r" in b: return dict(kind="malformed", reason="one line only")
    if LEAVE_RX.match(b): return dict(kind="leave")
    m = CLAIM_RX.match(b)
    if not m: return dict(kind="malformed", reason="expected kin: <label> members: <addresses>")
    label = m["label"].strip()
    if not LABEL_RX.match(label) or label.lower() == "leave": return dict(kind="malformed", reason="label: 1 to 32 of A-Z a-z 0-9 space _ . -")
    mem = [x for x in re.split(r"[,\s]+", m["members"].strip()) if x]
    if len(mem) > MAX_MEMBERS: return dict(kind="malformed", reason=f"more than {MAX_MEMBERS} members")
    if len(mem) < MIN_MEMBERS: return dict(kind="malformed", reason=f"at least {MIN_MEMBERS} members")
    if not all(ADDR_RX.match(x) for x in mem): return dict(kind="malformed", reason="every member must be a poa1 address")
    if len(set(mem)) != len(mem): return dict(kind="malformed", reason="a member is listed twice")
    if mem != sorted(mem, key=lambda x: (x.lower(), x)) and mem != sorted(mem): return dict(kind="malformed", reason="members must be sorted A to Z")
    if author not in mem: return dict(kind="malformed", reason="the commenter must be a member")
    return dict(kind="claim", label=label, members=mem)

def _ts(s):
    from .analytics import utc_to_ts
    try: return utc_to_ts(str(s)[:19].replace("T", " "))
    except Exception: return 0

def sync(post_id=None):
    """Rebuild kin_claims from the archived comments of the claim post. Local data only; idempotent."""
    pid = KIN_POST_ID if post_id is None else post_id
    rows = []
    if pid is not None:
        for c in db.q("SELECT id, author_public_id, created_at, edited_at, body FROM forum_comments WHERE post_id=? ORDER BY id", (pid,)):
            a = c["author_public_id"] or ""
            if not ADDR_RX.match(a): continue
            p = parse(c["body"], a)
            if p is None: continue
            mem = p.get("members")
            mem = sorted(mem) if mem else mem   # stored in canonical byte order, so either A to Z order is the same group
            rows.append((int(c["id"]), pid, a, _ts(c["edited_at"] or c["created_at"]), p["kind"], p.get("label"),
                         ",".join(mem) if mem else None, group_id(mem) if mem else None, p.get("reason")))
    db.write_tx([("DELETE FROM kin_claims", (), False), ("INSERT INTO kin_claims VALUES(?,?,?,?,?,?,?,?,?)", rows, True)])
    return len(rows)

def _state():
    """Walk claims and leaves in time order: each address's latest, and each group's active periods."""
    ev = db.q("SELECT * FROM kin_claims WHERE kind IN ('claim','leave') ORDER BY ts, comment_id")
    latest, groups = {}, {}
    def mutual(g):
        mem = groups[g]["members"]; ls = [latest.get(m) for m in mem]
        return all(l is not None and l["kind"] == "claim" and l["group_id"] == g for l in ls) and len({l["label"] for l in ls}) == 1
    for e in ev:
        old = latest.get(e["addr"]); latest[e["addr"]] = e
        if e["kind"] == "claim" and e["group_id"] not in groups:
            groups[e["group_id"]] = dict(members=e["members"].split(","), periods=[])
        for g in {x["group_id"] for x in (old, e) if x is not None and x["kind"] == "claim"}:
            ps = groups[g]["periods"]; on = bool(ps) and ps[-1][1] is None
            if mutual(g) and not on: ps.append([e["ts"], None])
            elif on and not mutual(g): ps[-1][1] = e["ts"]
    return latest, groups

def _url(e): return COMMENT_URL.format(pid=e["post_id"], cid=e["comment_id"])

def _view(gid, latest, groups, for_addr=None):
    g = groups[gid]; mem = g["members"]; ps = g["periods"]; active = bool(ps) and ps[-1][1] is None
    match = [latest[m] for m in mem if latest.get(m) is not None and latest[m]["kind"] == "claim" and latest[m]["group_id"] == gid]
    own = latest.get(for_addr) if for_addr else None
    label = (match[0]["label"] if active else (own["label"] if own is not None and own["kind"] == "claim" else (match[0]["label"] if match else None)))
    return dict(group_id=gid, label=label, members=mem, status="active" if active else "inactive",
                declared_at=ps[-1][0] if ps else None, evidence_urls=[_url(e) for e in sorted(match, key=lambda e: e["addr"])],
                active_before_declared=len(ps) > 1)

def kin(addr):
    """The kin field of one address: its latest claim's group, or None (no claim, or its latest is a leave)."""
    if KIN_POST_ID is None: return None
    latest, groups = _state(); l = latest.get(addr)
    if l is None or l["kind"] != "claim": return None
    return _view(l["group_id"], latest, groups, addr)

def group(gid):
    """GET /api/v1/kin/<group_id>: the group plus each member's latest claim state; None when no claim ever listed it."""
    if KIN_POST_ID is None: return None
    latest, groups = _state()
    if gid not in groups: return None
    d = _view(gid, latest, groups)
    def st(m):
        l = latest.get(m)
        if l is None: return dict(address=m, state="none", claimed_at=None, evidence_url=None)
        s = "match" if l["kind"] == "claim" and l["group_id"] == gid and (d["status"] == "active" or l["label"] == d["label"]) else ("left" if l["kind"] == "leave" else "different")
        return dict(address=m, state=s, claimed_at=l["ts"], evidence_url=_url(l))
    d.update(member_claims=[st(m) for m in d["members"]], periods=[dict(start=a, end=b) for a, b in groups[gid]["periods"]],
             claim_post=POST_URL.format(pid=KIN_POST_ID) if KIN_POST_ID is not None else None, method=METHOD)
    return d
