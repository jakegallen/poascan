"""Fetch the DB-IP Lite country file (CC BY 4.0, https://db-ip.com) at image build, for the daily country count.
Tries this month, then last month. Checks the gzip and the MaxMind DB marker. Any failure leaves no file and exits 0,
so a build never fails on it; the server then simply counts no country. Usage: geoip_fetch.py OUT_PATH"""
import datetime as dt, gzip, os, sys, urllib.request

def months():
    t = dt.date.today().replace(day=1); p = (t - dt.timedelta(days=1)).replace(day=1)
    return [t.strftime("%Y-%m"), p.strftime("%Y-%m")]

def main(out):
    for m in months():
        url = f"https://download.db-ip.com/free/dbip-country-lite-{m}.mmdb.gz"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "poascan-build"}), timeout=60) as r: raw = r.read(64 << 20)
            b = gzip.decompress(raw)
            if b"\xab\xcd\xefMaxMind.com" not in b[-200000:] or len(b) < 1 << 20: raise ValueError("not a MaxMind DB file")
            tmp = out + ".tmp"
            with open(tmp, "wb") as f: f.write(b)
            os.replace(tmp, out); print(f"geoip: {m} ({len(b) >> 10} KB)"); return 0
        except Exception as e: print(f"geoip: {m} failed: {type(e).__name__}")
    print("geoip: no country file; country counts are off"); return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/country.mmdb"))
