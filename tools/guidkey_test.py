"""GUID-shaped PoA keys (Oct 23: live minepoa keys can be 36 character GUIDs). keysafe redacts a GUID only in a
credential slot (key=, guid=, token=, api_key, X-Api-Key, a JSON key/token/guid field, Bearer) and leaves ordinary
GUIDs alone (app ids, podcast guids, the WebSocket GUID). The server refuses a request whose path segment or query value
is a bare GUID, without echoing it. keyscan flags a GUID in a credential slot and any bare GUID except listed public ones.
GUIDs are made at run time; none is written in this file. Usage: python3 tools/guidkey_test.py"""
import os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error, uuid
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or fails.append(name)
from poascan import keysafe as K
import keyscan as S
g = str(uuid.uuid4()); G = g.upper()

slots = [f"https://minepoa.com/api/hosted/me?key={g}", f"/lableak/.well-known/agentconnect/join?guid={g}", f"x?token={G}",
         f"X-Api-Key: {g}", f'{{"api_key": "{g}"}}', f"{{'key': '{g}'}}", f'"token":"{g}"', f"Authorization: Bearer {g}", f"auth_token={g}"]
check("has_key: a GUID in every credential slot", all(K.has_key(t) for t in slots))
check("redact: the GUID is gone from every slot, the slot name stays", all(g not in K.redact(t).lower() and K.REDACTED in K.redact(t) for t in slots))
check("redact (bytes) and redact_log too", all(g.encode() not in K.redact(t.encode()).lower() for t in slots) and all(g not in K.redact_log(t).lower() for t in slots))
check("URL-encoded slot is caught", K.has_key(f"q=%3Fkey%3D{g}"))
plain = [f'"appId": "{g}"', f"<podcast:guid>{g}</podcast:guid>", f"monkey={g}", f"see {g} here", f"id={g}", "258EAFA5-E914-47DA-95CA-C5AB0DC85B11", f"keys {g}"]
check("ordinary GUIDs are left alone (app id, podcast guid, prose, other params, WebSocket GUID)", not any(K.has_key(t) for t in plain) and all(K.redact(t) == t for t in plain))
check("pk_ keys still redacted", K.redact("pk_" + "a1" * 12) == K.REDACTED)
check("has_guid_value: bare GUID as a path segment or query value", K.has_guid_value(f"/search?q={g}") and K.has_guid_value(f"/address/{G}") and K.has_guid_value(f"/x?a=1&q={g}#t")
      and K.has_guid_value(f"/search?q=%20{g}".replace("%20", "")) and not K.has_guid_value("/swap/" + "ab" * 32) and not K.has_guid_value("/chain?tab=pending"))

# keyscan
def sc(l): return S.scan_text("f", [(1, l)])
check("keyscan: GUID in a credential slot is a PoA GUID key finding", all(any("PoA GUID key" in x for x in sc(t)) for t in slots))
check("keyscan: a bare GUID is a finding", any("bare GUID" in x for x in sc(f"appId {g}")))
check("keyscan: public GUIDs and marked lines pass", not sc('GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"') and not sc(f"appId {g}  # keyscan: public-uuid") and not sc("no ids here"))
check("keyscan: never prints the match", g not in " ".join(sc(f"?key={g}")).lower())

# server: refuse without echo
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def get(u):
    try:
        with urllib.request.urlopen(u, timeout=20) as f: return f.status, f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace")
port = free_port(); base = f"http://127.0.0.1:{port}"; tmp = tempfile.mkdtemp()
env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "g.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
srv = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try:
    for _ in range(100):
        try: get(base + "/api/health"); break
        except Exception: time.sleep(0.2)
    for path in (f"/search?q={g}", f"/address/{g}", f"/?key={g}", f"/api/v1/address/{G}"):
        c, t = get(base + path)
        check(f"{path.replace(g, 'GUID').replace(G, 'GUID')}: 400, not echoed", c == 400 and g not in t.lower())
    c, t = get(base + "/search?q=poa1")
    check("ordinary search still works", c in (200, 302, 404) and c != 400)
finally:
    srv.terminate()
    try: out, _ = srv.communicate(timeout=10)
    except Exception: srv.kill(); out, _ = srv.communicate()
check("server log never holds the GUID", g.encode() not in (out or b"").lower())
print("\n%d failure(s)" % len(fails) if fails else "\nall ok"); sys.exit(1 if fails else 0)
