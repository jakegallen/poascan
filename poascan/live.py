"""Minimal stdlib WebSocket hub for /ws.

One pump thread builds a snapshot from the local SQLite archive (never from upstream) every few seconds and
broadcasts it only when it changed, so N clients cost one DB read + N socket writes. Sockets are detached from
the HTTP handler thread after the handshake, so idle clients hold no thread."""
import base64, hashlib, json, logging, queue, selectors, struct, threading, time

log = logging.getLogger("live")
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_CLIENTS = 2000
PER_IP = 8          # sockets one client (Fly-Client-IP) may hold at once (SC-016); the count lives in memory only
PUMP_EVERY = 3.0
PING_EVERY = 25.0

def frame(payload, opcode=0x1):
    b = payload.encode() if isinstance(payload, str) else payload
    n = len(b)
    if n < 126: hdr = struct.pack("!BB", 0x80 | opcode, n)
    elif n < 65536: hdr = struct.pack("!BBH", 0x80 | opcode, 126, n)
    else: hdr = struct.pack("!BBQ", 0x80 | opcode, 127, n)
    return hdr + b

class Hub:
    def __init__(self, snapshot_fn):
        self.snapshot_fn = snapshot_fn
        self.lock = threading.Lock()
        self.clients = {}            # sock -> bytearray (inbound buffer)
        self.pending = queue.Queue()  # sockets to register with the selector
        self.last_json = None; self.last_frame = None; self.last_at = 0
        self.sel = selectors.DefaultSelector()
        self.sent = 0
        self.ip_of = {}; self.per_ip = {}   # sock -> client key, client key -> open sockets

    # ---- snapshot shared with the polling fallback ----
    def snapshot(self, max_age=PUMP_EVERY):
        if self.last_json is None or time.time() - self.last_at > max_age:
            self._refresh()
        return self.last_json

    def _refresh(self):
        data = self.snapshot_fn()
        js = json.dumps(dict(data, t="snap"), separators=(",", ":"), default=str)
        from . import keysafe as _KS
        js = _KS.redact(js)   # live pushes carry other people's memos: no key-shaped token goes out
        changed = js != self.last_json
        self.last_json = js; self.last_at = time.time()
        if changed: self.last_frame = frame(js)
        return changed

    # ---- handshake ----
    def accept(self, handler):
        h = handler.headers
        key = h.get("Sec-WebSocket-Key")
        if not key or "websocket" not in (h.get("Upgrade") or "").lower():
            handler.send(426, "upgrade required", "text/plain"); return
        if len(self.clients) >= MAX_CLIENTS:
            handler.send(503, "busy", "text/plain"); return
        ip = (h.get("Fly-Client-IP") or "").strip() or None   # without the header (local runs) only MAX_CLIENTS applies
        if ip:
            with self.lock: n = self.per_ip.get(ip, 0)
            if n >= PER_IP:
                handler.send(429, "too many live connections from one client", "text/plain", {"Retry-After": "30"}); return
        acc = base64.b64encode(hashlib.sha1((key.strip() + GUID).encode()).digest()).decode()
        sock = handler.connection
        try:
            sock.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          f"Sec-WebSocket-Accept: {acc}\r\n\r\n").encode())
            sock.settimeout(4)
            self.snapshot()
            if self.last_frame: sock.sendall(self.last_frame)
        except OSError:
            return
        handler.close_connection = True
        handler.server.detached.add(sock)
        with self.lock:
            self.clients[sock] = bytearray()
            if ip: self.ip_of[sock] = ip; self.per_ip[ip] = self.per_ip.get(ip, 0) + 1
        self.pending.put(sock)

    def drop(self, sock):
        with self.lock:
            if self.clients.pop(sock, None) is None: return
            ip = self.ip_of.pop(sock, None)
            if ip:
                n = self.per_ip.get(ip, 1) - 1
                if n > 0: self.per_ip[ip] = n
                else: self.per_ip.pop(ip, None)
        try: self.sel.unregister(sock)
        except Exception: pass
        try: sock.close()
        except Exception: pass

    def broadcast(self, data):
        with self.lock: socks = list(self.clients)
        for s in socks:
            try: s.sendall(data); self.sent += 1
            except OSError: self.drop(s)

    # ---- threads ----
    def _pump(self):
        last_ping = time.time()
        while True:
            time.sleep(PUMP_EVERY)
            try:
                if self.clients and self._refresh(): self.broadcast(self.last_frame)
                if time.time() - last_ping > PING_EVERY:
                    last_ping = time.time()
                    if self.clients: self.broadcast(frame(b"", 0x9))
            except Exception as e:
                log.warning("pump: %s", e)

    def _reader(self):
        while True:
            try:
                while True: self.sel.register(self.pending.get_nowait(), selectors.EVENT_READ)
            except queue.Empty: pass
            except Exception: pass
            if not self.sel.get_map():
                time.sleep(0.25); continue
            for k, _ in self.sel.select(timeout=0.5):
                s = k.fileobj
                try: data = s.recv(4096)
                except BlockingIOError: continue
                except OSError: data = b""
                if not data: self.drop(s); continue
                buf = self.clients.get(s)
                if buf is None: continue
                buf += data
                if len(buf) > 65536: self.drop(s); continue
                self._parse(s, buf)

    def _parse(self, s, buf):
        while len(buf) >= 2:
            b0, b1 = buf[0], buf[1]; op = b0 & 0x0F; masked = b1 & 0x80; n = b1 & 0x7F; i = 2
            if n == 126:
                if len(buf) < 4: return
                n = struct.unpack("!H", bytes(buf[2:4]))[0]; i = 4
            elif n == 127:
                if len(buf) < 10: return
                n = struct.unpack("!Q", bytes(buf[2:10]))[0]; i = 10
            mk = b""
            if masked:
                if len(buf) < i + 4: return
                mk = bytes(buf[i:i + 4]); i += 4
            if len(buf) < i + n: return
            payload = bytes(buf[i:i + n]); del buf[:i + n]
            if masked: payload = bytes(c ^ mk[j % 4] for j, c in enumerate(payload))
            if op == 0x8: self.drop(s); return
            if op == 0x9:
                try: s.sendall(frame(payload, 0xA))
                except OSError: self.drop(s); return
            # text frames from clients are ignored (read-only feed)

    def start(self):
        threading.Thread(target=self._pump, daemon=True, name="ws-pump").start()
        threading.Thread(target=self._reader, daemon=True, name="ws-reader").start()

    def stats(self):
        return dict(clients=len(self.clients), frames_sent=self.sent)
