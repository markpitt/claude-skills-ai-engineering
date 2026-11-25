#!/usr/bin/env python3
"""Minimal allowlisting HTTP CONNECT proxy for NET=proxy sandboxes (install with install-proxy.sh).

Listens on 127.0.0.1:$PROXY_PORT (default 8888). Allowlist file: $PROXY_ALLOWLIST, default allowlist.txt
beside the script. Tunnels CONNECT host:443 only when the host is in the allowlist (one hostname per
line, '#' comments, re-read on every request). Anything else gets 403 and one log line on stderr. Plain HTTP (non-CONNECT) is refused
except for a line of the form `GET http://127.0.0.1:8080/v1/models` (method, scheme, host, port and path, nothing
else): that exact request is forwarded to that address, rebuilt by the proxy, and nothing else on it is. This is how
an agent may read one endpoint of a local service. Logs host and verdict, never payloads.
"""
import ipaddress, os, select, socket, sys, threading, time

ADDR = ("127.0.0.1", int(os.environ.get("PROXY_PORT", "8888")))
HEADER_TIMEOUT = 15                               # seconds to send the CONNECT line, then the timeout is lifted
SLOTS = threading.BoundedSemaphore(int(os.environ.get("PROXY_MAX_CONNECTIONS", "64")))
ALLOW = os.environ.get("PROXY_ALLOWLIST", os.path.join(os.path.dirname(os.path.abspath(__file__)), "allowlist.txt"))
DNS_TTL = float(os.environ.get("PROXY_DNS_TTL", "60"))   # seconds an upstream lookup is reused; 0 resolves every tunnel afresh
_dns, _dns_lock = {}, threading.Lock()

def allowed(host):
    """Exact names, or every host when the file has a `*` line. A line `!name` blocks that host and a line `!*.example.com`
    blocks the domain and everything under it; a block wins over an allow, so an allow-all instance is narrowed by adding a line."""
    host = host.strip().lower()
    if not host:                                  # blank and comment-only lines must never match an empty host
        return False
    try:
        with open(ALLOW) as f:
            names = {n for n in (l.split("#")[0].strip().lower() for l in f) if n}
    except OSError:
        return False
    for n in names:
        if n.startswith("!"):
            b = n[1:].strip()
            if b and (host == b or (b.startswith("*.") and (host == b[2:] or host.endswith(b[1:])))):
                return False
    return "*" in names or host in names

def allowed_http(method, url):
    """True only for a request line listed verbatim as `METHOD http://host:port/path` (no query, no fragment)."""
    want = f"{method.upper()} {url}"
    if method.upper() != "GET" or not url.startswith("http://") or "?" in url or "#" in url:
        return False
    try:
        with open(ALLOW) as f:
            return want in {" ".join(l.split("#")[0].split()) for l in f}
    except OSError:
        return False

def forward_http(c, method, url):
    """Send one rebuilt request, headers fixed by us, and relay the reply. Closes after one exchange."""
    rest = url[len("http://"):]
    hostport, _, path = rest.partition("/")
    host, _, port = hostport.partition(":")
    up = socket.create_connection((host, int(port or 80)), timeout=15)
    try:
        up.sendall(f"{method} /{path} HTTP/1.1\r\nHost: {hostport}\r\nAccept: application/json\r\nConnection: close\r\n\r\n".encode())
        c.settimeout(None)
        up.settimeout(30)
        while True:
            data = up.recv(65536)
            if not data:
                return
            c.sendall(data)
    finally:
        up.close()

def is_public(ip):
    return ipaddress.ip_address(ip).is_global

def resolve(host):
    """getaddrinfo for host:443, reused for DNS_TTL seconds. Claude Code opens a new connection every few seconds, so resolving each tunnel
    afresh sent about 1.25 million lookups a day to AdGuard (25/10/2026). Only allowlisted hosts get here, so the cache stays small."""
    now = time.monotonic()
    with _dns_lock:
        hit = _dns.get(host)
        if hit and now - hit[0] < DNS_TTL:
            return hit[1]
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    with _dns_lock:
        _dns[host] = (now, infos)
    return infos

def connect_upstream(host):
    """Resolve first and refuse a name that points at a loopback, LAN or link-local address: checked on every tunnel, cached answer or not."""
    for *_, sa in resolve(host):
        if is_public(sa[0]):
            try:
                return socket.create_connection((sa[0], 443), timeout=15)
            except OSError:
                with _dns_lock:                   # the host may have moved: look it up again next time
                    _dns.pop(host, None)
                raise
    raise OSError(f"{host} resolves to no public address")

def pipe(a, b):
    socks = [a, b]
    while True:
        r, _, x = select.select(socks, [], socks, 120)
        if x or not r:
            return
        for s in r:
            data = s.recv(65536)
            if not data:
                return
            (b if s is a else a).sendall(data)

def handle(c):
    try:
        c.settimeout(HEADER_TIMEOUT)
        head = b""
        while b"\r\n\r\n" not in head and len(head) < 8192:
            chunk = c.recv(4096)
            if not chunk:
                return
            head += chunk
        head, _, rest = head.partition(b"\r\n\r\n")     # rest: bytes the client sent right after CONNECT
        parts = head.split(b"\r\n", 1)[0].decode("latin1").split()
        if len(parts) >= 2 and parts[0].upper() == "GET" and allowed_http(parts[0], parts[1]):
            print(f"allow {parts[0].upper()} {parts[1]}", file=sys.stderr, flush=True)
            forward_http(c, parts[0].upper(), parts[1]); return
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            c.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n"); print("deny non-CONNECT", file=sys.stderr, flush=True); return
        host, _, port = parts[1].rpartition(":")
        if port != "443" or not allowed(host):
            c.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n"); print(f"deny {parts[1]}", file=sys.stderr, flush=True); return
        up = connect_upstream(host)
        c.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        c.settimeout(None)
        print(f"allow {host}", file=sys.stderr, flush=True)
        if rest:
            up.sendall(rest)
        pipe(c, up); up.close()
    except OSError as e:                          # includes timeouts
        print(f"error {e}", file=sys.stderr, flush=True)
    finally:
        c.close()

def serve(c):
    try:
        handle(c)
    finally:
        SLOTS.release()

def main():
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(ADDR); s.listen(64)
    print(f"listening {ADDR[0]}:{s.getsockname()[1]} allowlist={ALLOW}", file=sys.stderr, flush=True)
    while True:
        c, _ = s.accept()
        if not SLOTS.acquire(blocking=False):      # shared by every agent: one cannot hold every thread
            c.close(); continue
        threading.Thread(target=serve, args=(c,), daemon=True).start()

if __name__ == "__main__":
    main()
