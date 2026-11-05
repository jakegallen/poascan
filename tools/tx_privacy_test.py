"""Privacy: the public tx API and HTML tx page must not republish a grade seal's sealed grade (body.blob).
indexer.public_tx() drops body.blob for grade-sealed txs and keeps every public field. No network. Run: python tools/tx_privacy_test.py"""
import os, sys, json
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.environ.setdefault("POASCAN_DB", "/tmp/poascan_txpriv.db")
from poascan import indexer as I

FAILS = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); (None if ok else FAILS.append(name))

sealed = {"id": "a"*64, "type": "grade-sealed", "from_addr": "poa1x", "final": 1, "ts": 1,
          "body": {"assignment": "b"*64, "blob": "SEALEDGRADESECRET", "cid": "poa-mainnet-1", "from": "poa1x", "nonce": 7, "parents": ["p"*64], "sig": "sig123", "ts": 1, "type": "grade-sealed"}}
r = I.public_tx(sealed)
check("grade-sealed: body.blob removed", "blob" not in r["body"])
check("grade-sealed: sealed value appears nowhere in the output", "SEALEDGRADESECRET" not in json.dumps(r))
check("grade-sealed: public body fields kept", r["body"].get("assignment") == "b"*64 and r["body"].get("sig") == "sig123" and r["body"].get("nonce") == 7 and r["body"].get("parents") == ["p"*64])
check("grade-sealed: public top-level fields kept", r.get("id") == "a"*64 and r.get("from_addr") == "poa1x" and r.get("final") == 1)
check("grade-sealed: flagged grade_seal_redacted", r.get("grade_seal_redacted") is True)
check("public_tx does not mutate its input", sealed["body"].get("blob") == "SEALEDGRADESECRET")

chal = {"id": "c"*64, "type": "challenge", "body": {"answer": "public answer", "sig": "s"}}
check("non-grade-sealed tx is returned unchanged", I.public_tx(chal) == chal)
check("None and non-dict are passed through", I.public_tx(None) is None and I.public_tx("x") == "x")
sealed_noblob = {"id": "d"*64, "type": "grade-sealed", "body": {"assignment": "e"*64, "sig": "s"}}
check("grade-sealed with no blob: unchanged, not falsely flagged", I.public_tx(sealed_noblob) == sealed_noblob)

print("\n%d failure(s)" % len(FAILS) if FAILS else "\nall ok"); sys.exit(1 if FAILS else 0)
