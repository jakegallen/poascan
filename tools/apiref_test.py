"""Interactive API reference (/api/reference) and the agent-steering robots rules.
Checks: the reference page renders and loads the static same-origin renderer (no external
script, so it stays inside the strict CSP); the /api index links to it; the static renderer
is served as JavaScript; and robots.txt steers AI crawlers to the API and off /address/ /tx/.
Usage: python3 tools/apiref_test.py"""
import os, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FAILS = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name); ok or FAILS.append(name)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def req(url):
    r = urllib.request.urlopen(url, timeout=20)
    return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Content-Type", "")

def main():
    # Pure-unit checks first (no server needed): robots string and the rendered strings via the server below.
    port = free_port(); base = f"http://127.0.0.1:{port}"; tmp = tempfile.mkdtemp()
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", POASCAN_DB=os.path.join(tmp, "t.db"), POASCAN_INDEXER="0", POA_BASE="http://127.0.0.1:9")
    p = subprocess.Popen([sys.executable, "-m", "poascan.server"], cwd=ROOT, env=env)
    try:
        for _ in range(50):
            try: req(base + "/api/health"); break
            except Exception: time.sleep(0.2)

        c, b, _ = req(base + "/api/reference")
        check("/api/reference renders (200) with an h1", c == 200 and "<h1>API reference</h1>" in b)
        check("reference page mounts the apiref container and loads the static same-origin renderer",
              'id="apiref"' in b and 'src="/static/apiref.js"' in b)
        check("reference page loads no external script (stays within the strict CSP)",
              '<script src="http' not in b and "unpkg" not in b and "cdn.jsdelivr" not in b)
        check("reference page degrades without JavaScript (noscript points at /api and openapi.json)",
              "<noscript>" in b and "/openapi.json" in b)

        c, jb, ct = req(base + "/static/apiref.js")
        check("static renderer is served as JavaScript", c == 200 and "javascript" in ct and "openapi.json" in jb)

        c, ap, _ = req(base + "/api")
        check("the /api index links to the interactive reference", c == 200 and "/api/reference" in ap)

        _, rob, _ = req(base + "/robots.txt")
        ai = rob.split("User-agent: GPTBot", 1)[-1]
        check("robots: AI crawlers are pointed at the API and kept off /address/ and /tx/",
              "Allow: /api" in ai and "Disallow: /address/" in ai and "Disallow: /tx/" in ai)
        default = rob.split("User-agent: GPTBot", 1)[0]
        check("robots: the default (all-crawler) group is also kept off /address/ and /tx/ (crawl-storm guard) and allows /mcp + /api",
              "Disallow: /address/" in default and "Disallow: /tx/" in default and "Allow: /mcp" in default and "Allow: /api" in default)
    finally:
        p.terminate()
        try: p.wait(timeout=5)
        except Exception: p.kill()

    print(("all passed" if not FAILS else f"{len(FAILS)} failure(s)"))
    sys.exit(1 if FAILS else 0)

if __name__ == "__main__":
    main()
