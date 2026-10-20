"""Ping IndexNow (Bing, Yandex, Seznam, Naver and others share submissions) with POAScan URLs.

Default: the main pages plus the newest epoch pages, once per deploy.
--all: every URL in the live sitemap (use rarely, e.g. the first submission).
The key is public by design and served at https://poascan.io/<key>.txt.
"""
import json, re, sys, urllib.request
ROOT = __file__.rsplit("/tools/", 1)[0] if "/tools/" in __file__ else "."
INDEXNOW_KEY = re.search(r'INDEXNOW_KEY = "([0-9a-f]+)"', open(ROOT + "/poascan/agentapi.py").read()).group(1)

BASE = "https://poascan.io"
MAIN = ["/", "/epochs", "/txs", "/token", "/unlocks", "/swaps", "/agents/top", "/agents/census", "/about", "/api", "/find", "/llms.txt"]

def sitemap():
    with urllib.request.urlopen(BASE + "/sitemap.xml", timeout=30) as r:
        return re.findall(r"<loc>([^<]+)</loc>", r.read().decode())

def main():
    locs = sitemap()
    if "--all" in sys.argv:
        urls = locs
    else:
        ep = sorted((u for u in locs if "/epoch/" in u), key=lambda u: int(u.rsplit("/", 1)[1]))[-3:]
        urls = [BASE + p for p in MAIN] + ep
    body = {"host": "poascan.io", "key": INDEXNOW_KEY, "keyLocation": f"{BASE}/{INDEXNOW_KEY}.txt", "urlList": urls[:10000]}
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: code = r.status
    except urllib.error.HTTPError as e: code = e.code
    print(f"IndexNow: {len(urls)} URLs, HTTP {code}")
    return 0 if code in (200, 202) else 1

if __name__ == "__main__":
    sys.exit(main())
