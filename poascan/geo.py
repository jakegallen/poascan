"""Offline IP to country, for the daily country count only (poascan/visits.py). Reads a DB-IP Lite country file
(MaxMind DB format, CC BY 4.0, https://db-ip.com) fetched at image build by tools/geoip_fetch.py. Stdlib only: the
file is memory-mapped, so it is shared page cache rather than Python heap, and only the tree nodes a lookup touches
are read. Nothing is written or logged; the IP is looked up and dropped by the caller. No file means no country."""
import ipaddress, mmap, os, re, threading

PATH = os.environ.get("POASCAN_GEOIP", os.path.join(os.path.dirname(__file__), "..", "data", "country.mmdb"))
META = b"\xab\xcd\xefMaxMind.com"
ISO_RX = re.compile(r"^[A-Z]{2}$")
_lk = threading.Lock(); _db = [None, False]   # reader, tried

class Reader:
    def __init__(self, path):
        f = open(path, "rb")
        try: self.m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        finally: f.close()
        i = self.m.rfind(META)
        if i < 0: raise ValueError("not a MaxMind DB file")
        self.meta, _ = self._decode(i + len(META), i + len(META))
        self.nodes = self.meta["node_count"]; self.rs = self.meta["record_size"]
        self.nb = self.rs * 2 // 8; self.tree = self.nodes * self.nb; self.data = self.tree + 16
        self.v6 = self.meta["ip_version"] == 6; self.cache = {}
        self.v4start = 0
        if self.v6:
            n = 0
            for _ in range(96):
                if n >= self.nodes: break
                n = self._rec(n, 0)
            self.v4start = n
        self.build = self.meta.get("build_epoch")

    def _rec(self, node, bit):
        m, o = self.m, node * self.nb
        if self.rs == 24: b = m[o + 3 * bit:o + 3 * bit + 3]; return int.from_bytes(b, "big")
        if self.rs == 28:
            if bit == 0: return ((m[o + 3] & 0xF0) << 20) | int.from_bytes(m[o:o + 3], "big")
            return ((m[o + 3] & 0x0F) << 24) | int.from_bytes(m[o + 4:o + 7], "big")
        if self.rs == 32: return int.from_bytes(m[o + 4 * bit:o + 4 * bit + 4], "big")
        raise ValueError("record size")

    def _decode(self, off, base):
        m = self.m; c = m[off]; off += 1; t = c >> 5
        if t == 1:   # pointer
            s = (c >> 3) & 3; v = c & 7
            if s == 0: p = (v << 8) | m[off]; off += 1
            elif s == 1: p = ((v << 16) | int.from_bytes(m[off:off + 2], "big")) + 2048; off += 2
            elif s == 2: p = ((v << 24) | int.from_bytes(m[off:off + 3], "big")) + 526336; off += 3
            else: p = int.from_bytes(m[off:off + 4], "big"); off += 4
            val, _ = self._decode(base + p, base); return val, off
        if t == 0: t = 7 + m[off]; off += 1
        n = c & 31
        if n == 29: n = 29 + m[off]; off += 1
        elif n == 30: n = 285 + int.from_bytes(m[off:off + 2], "big"); off += 2
        elif n == 31: n = 65821 + int.from_bytes(m[off:off + 3], "big"); off += 3
        if t == 2: return m[off:off + n].decode("utf-8", "replace"), off + n
        if t == 3: import struct; return struct.unpack(">d", m[off:off + 8])[0], off + 8
        if t == 4: return bytes(m[off:off + n]), off + n
        if t in (5, 6, 9, 10): return int.from_bytes(m[off:off + n], "big"), off + n
        if t == 8: return int.from_bytes(m[off:off + n], "big", signed=n == 4), off + n
        if t == 7:
            d = {}
            for _ in range(n):
                k, off = self._decode(off, base); v, off = self._decode(off, base); d[k] = v
            return d, off
        if t == 11:
            a = []
            for _ in range(n): v, off = self._decode(off, base); a.append(v)
            return a, off
        if t == 14: return bool(n), off
        if t == 15: import struct; return struct.unpack(">f", m[off:off + 4])[0], off + 4
        raise ValueError("type %d" % t)

    def country(self, ip):
        """ISO 3166-1 alpha-2 code, or None (private, reserved, unknown or unparseable)."""
        try: a = ipaddress.ip_address(ip)
        except ValueError: return None
        if a.version == 6 and a.ipv4_mapped: a = a.ipv4_mapped
        if a.version == 6 and not self.v6: return None
        x = int(a); bits = 32 if a.version == 4 else 128
        node = self.v4start if a.version == 4 else 0
        for i in range(bits):
            if node >= self.nodes: break
            node = self._rec(node, (x >> (bits - 1 - i)) & 1)
        x = None
        if node <= self.nodes: return None   # empty
        off = node - self.nodes - 16
        if off in self.cache: return self.cache[off]
        try:
            rec, _ = self._decode(self.data + off, self.data)
            cc = ((rec.get("country") or {}).get("iso_code") or "").upper()
        except Exception: cc = ""
        cc = cc if ISO_RX.match(cc) else None
        if len(self.cache) < 2048: self.cache[off] = cc
        return cc

def reader():
    if _db[1]: return _db[0]
    with _lk:
        if not _db[1]:
            try: _db[0] = Reader(PATH) if os.path.isfile(PATH) else None
            except Exception: _db[0] = None
            _db[1] = True
    return _db[0]

def country(ip):
    r = reader()
    return r.country(ip) if r and ip else None

def source():
    r = reader()
    if not r: return None
    import time
    return "DB-IP Lite country, built " + time.strftime("%Y-%m-%d", time.gmtime(r.build or 0))
