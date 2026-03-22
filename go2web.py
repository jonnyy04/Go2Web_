#!/usr/bin/env python3
import sys
import socket
import ssl
import re
from urllib.parse import urlparse

cache = {}

def decode_chunked(data: bytes) -> bytes:
    result = b""
    while data:
        crlf = data.find(b"\r\n")
        if crlf == -1: break
        size = int(data[:crlf], 16)
        if size == 0: break
        result += data[crlf + 2 : crlf + 2 + size]
        data = data[crlf + 2 + size + 2:]
    return result

def html_to_text(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    for tag in ["p", "div", "br", "li", "h1", "h2", "h3", "tr"]:
        html = re.sub(rf"</?{tag}[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    entities = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&nbsp;": " ", "&quot;": '"'}
    for ent, char in entities.items(): html = html.replace(ent, char)
    return "\n".join([l.strip() for l in html.splitlines() if l.strip()])

def make_request(url, method="GET", max_redirects=10):
    if url in cache: return cache[url]
    for _ in range(max_redirects):
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
        path = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")

        request = f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nUser-Agent: go2web/1.0\r\n\r\n"

        raw_sock = socket.create_connection((host, port), timeout=10)
        sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host) if scheme == "https" else raw_sock
        sock.sendall(request.encode("utf-8"))

        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk: break
            response += chunk
        sock.close()

        header_part, body = response.split(b"\r\n\r\n", 1) if b"\r\n\r\n" in response else (response, b"")
        headers = {line.split(": ", 1)[0].lower(): line.split(": ", 1)[1] for line in header_part.decode().split("\r\n")[1:] if ": " in line}
        status_code = int(header_part.decode().split(" ")[1])

        if status_code in (301, 302, 303, 307, 308):
            url = headers.get("location", "")
            if url.startswith("/"): url = f"{scheme}://{host}{url}"
            continue

        if headers.get("transfer-encoding", "").lower() == "chunked":
            body = decode_chunked(body)

            result = {"body": body.decode(errors="replace")}
            cache[url] = result
            return result
    return None

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(make_request(sys.argv[1])["body"])