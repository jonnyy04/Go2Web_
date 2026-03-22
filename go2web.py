#!/usr/bin/env python3
import sys
import socket
import ssl
import json
from urllib.parse import urlparse, quote_plus

def make_request(url, method="GET"):
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    
    request = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Connection: close\r\n"
        f"User-Agent: go2web/1.0\r\n\r\n"
    )

    raw_sock = socket.create_connection((host, port), timeout=10)
    sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host) if scheme == "https" else raw_sock
    
    sock.sendall(request.encode("utf-8"))
    response = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk: break
        response += chunk
    sock.close()
    return response