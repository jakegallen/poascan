"""Join difficulty is set by each challenge (1.26.226, prompt v2.9.1; minepoa v0.67 made it adjustable, bits 20 to 21).
Fails on any fixed bit count or time estimate in the join copy (prompt variants, /start steps, join shape, combined
prompt, llms.txt, /about, MCP and OpenAPI text), and checks kind and required_bits handling: kind is read and anything
but pow stops the join; a 403 with required_bits gets a fresh challenge and a new proof. Also the Protocol timeline:
release notes for v0.67 and v0.68, and the early release read when an indexed G0 release tx is missing from the stored
/api/release copy. No network. Usage: python3 tools/joinpow_kind_test.py"""
import json, os, re, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.update(POASCAN_DB=os.path.join(tempfile.mkdtemp(), "j.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)

import fixture; fixture.seed()
from poascan import db, onboarding_prompt as OP, start as S, combined as CB, agentapi as AG, views as V, protocol as PT, protocolview as PV, signed as SGN
FIXED = re.compile(r"\b\d+\s*(?:leading\s+)?(?:zero\s+)?bits?\b|\bbits?\W{0,4}\d+\b|about a minute|2\^\d+|\b1048576\b|1,048,576", re.I)
def fixed(t): return [m.group(0) for m in FIXED.finditer(t) if "currently 21" not in t[max(0, m.start() - 60):m.end() + 20]]

# ---------------- no fixed difficulty anywhere in the join copy ----------------
variants = {v: S.prompt("NAME", v) for v in ("full", "connector")}
ab = V.about(); ab = ab[1] if isinstance(ab, tuple) else ab
llms = AG.llms_txt(); llms = llms[1] if isinstance(llms, tuple) else llms
tools = json.dumps(AG.tools_list(), ensure_ascii=False)
surf = dict(variants, template=OP.TEMPLATE, pow=OP.POW, r403=OP.R403, note=OP.RELEASE_NOTE, steps=json.dumps(S.STEPS), shape=json.dumps(S.join_shape()),
            combined=CB.TEXT or "", llms=llms, mcp=tools)
for k, t in surf.items():
    check(f"{k}: no fixed bit count or time estimate {fixed(t)[:3]}", not fixed(t))
check("about: no fixed bit count in the join method", not [x for x in fixed(ab) if "bit" in x.lower()])
check("a 20 bit line is caught (the check works)", fixed("mine to 20 bits") and fixed("bits=20") and fixed("Expect about a minute.") and not fixed("set by the challenge (currently 21 bits)"))

# ---------------- kind ----------------
for v, t in variants.items():
    check(f"{v}: reads kind and stops unless it is pow", "returns kind, challenge, bits and expires_ts" in t and "If kind is not pow, stop and tell me" in t)
    check(f"{v}: bits read from each challenge", "Read bits from each challenge" in t)
js = S.join_shape()
check("join shape: kind returned, kind_rule stops on anything but pow", "kind" in js["pow"]["returns"] and "pow" in js["pow"]["kind_rule"] and "stop" in js["pow"]["kind_rule"])
check("join shape: bits_source says per challenge, no number", "each challenge" in js["pow"]["bits_source"] and not re.search(r"\d+\s*bits", js["pow"]["bits_source"]))

# ---------------- required_bits ----------------
for v, t in variants.items():
    check(f"{v}: a 403 with required_bits gets a fresh challenge and a new proof, once", OP.R403 in t and "get a fresh challenge" in OP.R403 and "at least required_bits" in OP.R403 and "Never loop." in OP.R403)
check("join shape: rejected 403 rule fetches a fresh challenge", js["rejected"]["status"] == 403 and "required_bits" in js["rejected"]["fields"] and "fresh challenge" in js["rejected"]["rule"])
check("combined prompt carries the new join core", not CB.TEXT or (OP.R403 in CB.TEXT and "If kind is not pow" in CB.TEXT))
check("prompt version v2.9.2, history entry with today's hash", OP.VERSION == "v2.9.2" and __import__("poascan.prompthist", fromlist=["x"]).VERSIONS[-1]["template_sha256"] == S.template_sha256())

# ---------------- Protocol timeline ----------------
REL = lambda v, ts, tx: dict(version=v, ts=ts, txid=tx, engine_sha256="e" * 64, client_sha256="c" * 64, web_client_sha256="w" * 64, changelog_ref="ref " + v)
now = int(time.time())
r67, r68 = REL("v0.67-joindiff", now - 7200, "67" * 32), REL("v0.68-surge", now - 1800, "68" * 32)
db.put_blob("release", dict(current=r67, history=[r67])); PT._ensure(); PT.sync_releases()
db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, ts, final) VALUES(?,?,?,?,?)", (r68["txid"], "release", SGN.TRUSTED_G0, r68["ts"], 1))
db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, ts, final) VALUES(?,?,?,?,?)", ("ff" * 32, "release", "poa1notG0", r68["ts"], 1))
check("unknown G0 release tx found (a non G0 release tx is ignored)", PT.unknown_release_txs() == [r68["txid"]])
reads = []
def fake(): reads.append(1); return dict(current=r68, history=[r67, r68])
check("nudge: one early read adds v0.68 to the timeline", PT.release_nudge(now, fake) is True and len(reads) == 1 and any(e["release_version"] == "v0.68-surge" for e in PT.events("release")))
check("nudge: nothing unknown, no read", PT.release_nudge(now + 5, fake) is False and len(reads) == 1)
db.write("INSERT OR REPLACE INTO txs(id, type, from_addr, ts, final) VALUES(?,?,?,?,?)", ("69" * 32, "release", SGN.TRUSTED_G0, now, 1))
db.write("INSERT INTO fetch_log(endpoint,last_ok,fails,next_at) VALUES('/api/release',?,0,0) ON CONFLICT(endpoint) DO UPDATE SET last_ok=excluded.last_ok", (now,))
check("nudge: at most one read per NUDGE_GAP_S", PT.release_nudge(now + 60, fake) is False and len(reads) == 1 and PT.release_nudge(now + PT.NUDGE_GAP_S + 1, fake) is True)
ev = {e["release_version"]: e for e in PT.events("release")}
check("release notes: v0.67 adjustable difficulty with kind and required_bits; v0.68 joins briefly halted", "kind" in ev["v0.67-joindiff"]["note"] and "required_bits" in ev["v0.67-joindiff"]["note"]
      and "21" in ev["v0.67-joindiff"]["note"] and "halted" in ev["v0.68-surge"]["note"])
api = PT.api("release")
check("API rows carry note", all("note" in r for r in api["rows"]) and "early" in api["note"])
h = PV.tab({}, lambda tab, **k: "/governance?tab=" + tab, lambda **k: "")
h = h[1] if isinstance(h, tuple) else h
check("timeline shows the short notes; full note and changelog_ref on hover", PT.SHORT["v0.68-surge"] in h and PT.SHORT["v0.67-joindiff"] in h
      and f'title="{PT.NOTES["v0.67-joindiff"]} · ref v0.67-joindiff"' in h and all(len(x) <= 46 for x in PT.SHORT.values()))
import inspect; from poascan import indexer as I
check("hourly retry syncs the timeline after a release read", "sync_releases" in inspect.getsource(I.job_hourly_retry))
check("release_nudge job every 5 min", {j[0]: j[2] for j in I.JOBS}.get("release_nudge") == 300)
txt = "".join(surf.values()) + ab + h + json.dumps(PT.NOTES)
check("no em or en dashes", not any(c in txt for c in "\u2013\u2014"))

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
