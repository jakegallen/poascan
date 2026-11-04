"""The visitor's IP (1.26.241). Fly's proxy puts the address that connected to it in Fly-Client-IP. Behind Cloudflare that
address is a Cloudflare edge, and Cloudflare names the visitor in CF-Connecting-IP. That header is believed only when
Fly-Client-IP is inside Cloudflare's published ranges (bundled below, never fetched at run time), so a client that talks
to Fly directly cannot pick its own address by sending the header. Without Fly-Client-IP (local runs) the old fallback
applies. Used in memory only, as before: rate limits, the per IP socket cap, the daily unique estimate and the country count.
Ranges from https://www.cloudflare.com/ips-v4 and /ips-v6 (checked 2026-10-30); check with tools/cloudflare_test.py --print."""
import ipaddress

CF_V4 = ("173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18", "108.162.192.0/18",
         "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
         "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22")
CF_V6 = ("2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32")
_NETS = tuple(ipaddress.ip_network(n) for n in CF_V4 + CF_V6)

def _addr(s):
    try:
        a = ipaddress.ip_address((s or "").strip())
        return a.ipv4_mapped or a if a.version == 6 else a
    except ValueError:
        return None

def is_cloudflare(s):
    a = _addr(s)
    return bool(a) and any(a.version == n.version and a in n for n in _NETS)

def is_internal(s):
    """An address that is not public: loopback, private, link-local, or not an address at all. Used by the Cloudflare-only
    origin guard (server.py) on Fly-Client-IP (1.26.258; the socket peer is always the Fly proxy's private address) to never
    block a Fly internal request. Reuses the same parser as the Cloudflare check, so IPv4-mapped IPv6 peers resolve correctly."""
    a = _addr(s)
    if a is None: return True
    return a.is_loopback or a.is_private or a.is_link_local

def of(headers, peer=None):
    """The client key for a request: CF-Connecting-IP when Fly-Client-IP is a Cloudflare edge and the header is a valid
    address, else Fly-Client-IP, else the first X-Forwarded-For hop or the socket peer (local runs only; Fly always sets it)."""
    fci = (headers.get("Fly-Client-IP") or "").strip()
    if fci:
        if is_cloudflare(fci):
            cf = (headers.get("CF-Connecting-IP") or "").strip()
            if _addr(cf): return str(_addr(cf))
        return fci
    return (headers.get("X-Forwarded-For") or "").split(",")[0].strip() or peer

def proxied(headers):
    """Only the Fly header, Cloudflare aware: None without Fly-Client-IP (callers that skip local runs)."""
    return of(headers) if (headers.get("Fly-Client-IP") or "").strip() else None

def limiter_key(s):
    """The rate-limit bucket key for a client address (1.26.252): the /64 network for IPv6 and the full address for IPv4.
    One IPv6 allocation holds 2^64 addresses, so without the /64 a single /64 could rotate addresses to slip the per-IP
    limit; IPv4 keeps its exact address, as before. Not an address (local runs: a peer or a header value) is returned
    unchanged, so nothing that is not an IP is grouped by accident."""
    a = _addr(s)
    if a is None: return s
    if a.version == 6:
        return str(ipaddress.ip_network(f"{a}/64", strict=False).network_address) + "/64"
    return str(a)
