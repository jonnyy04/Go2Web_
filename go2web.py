#!/usr/bin/env python3
import sys
import socket
import ssl
import json
import ipaddress
import os
import hashlib
import time
from urllib.parse import urlparse, urlencode, quote_plus

cache = {}
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


def _cache_path(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{digest}.json")


def cleanup_old_cache():
    """Sterge din cache fisierele mai vechi de 1 ora."""
    if not os.path.exists(CACHE_DIR):
        return

    current_time = time.time()
    for filename in os.listdir(CACHE_DIR):
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(CACHE_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                payload = json.load(f)

            timestamp = payload.get("timestamp", 0)
            age = current_time - timestamp

            # Sterge daca e mai vechi de 1 ora (3600 secunde)
            if age > 3600: #<-------------------------------
                os.remove(filepath)
                print(f"[cleanup] Sters cache: {filename}")
        except (OSError, json.JSONDecodeError):
            pass


def load_from_cache(url: str):
    if url in cache:
        print("[cache] Raspuns din cache.\n")
        return cache[url]

    path = _cache_path(url)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    if payload.get("url") != url:
        return None

    # Verificam daca cache-ul a expirat (mai vechi de 1 ora)
    timestamp = payload.get("timestamp", 0)
    if time.time() - timestamp > 3600:
        # Cache expirat, stergem fisierul
        try:
            os.remove(path)
        except OSError:
            pass
        return None

    result = payload.get("result")
    if not isinstance(result, dict):
        return None

    cache[url] = result
    print("[cache] Raspuns din cache.\n")
    return result


def save_to_cache(url: str, result: dict):
    cache[url] = result

    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(url)
    temp_path = path + ".tmp"

    payload = {
        "url": url,
        "timestamp": time.time(),
        "result": result,
    }

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(temp_path, path)
    except OSError:
        # Daca nu putem scrie pe disk, pastram macar cache-ul in memorie.
        pass

# ─── HTTP REQUEST ──────────────────────────────────────────────────────────────

def make_request(url, method="GET", max_redirects=10):

    for _ in range(max_redirects):
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        # Cache check (memorie + disk)
        cache_key = url
        cached = load_from_cache(cache_key)
        if cached is not None:
            return cached

        # Construim request-ul HTTP
        request = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Accept: text/html,application/json\r\n"
            f"Accept-Language: en-US,en;q=0.9\r\n"
            f"Connection: close\r\n"
            f"User-Agent: go2web/1.0\r\n"
            f"\r\n"
        )

        # Deschidem socket TCP
        raw_sock = socket.create_connection((host, port), timeout=10)

        if scheme == "https":
            context = ssl.create_default_context()
            sock = context.wrap_socket(raw_sock, server_hostname=host)
        else:
            sock = raw_sock

        sock.sendall(request.encode("utf-8"))

        # Citim raspunsul complet
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        sock.close()

        # Separam header-ele de body
        if b"\r\n\r\n" in response:
            header_part, body = response.split(b"\r\n\r\n", 1)
        else:
            header_part, body = response, b""

        headers_text = header_part.decode("utf-8", errors="replace")
        header_lines = headers_text.split("\r\n")
        status_line = header_lines[0]
        status_code = int(status_line.split(" ")[1])

        # Parsam header-ele intr-un dict
        headers = {}
        for line in header_lines[1:]:
            if ": " in line:
                k, v = line.split(": ", 1)
                headers[k.lower()] = v

        # Redirect?
        if status_code in (301, 302, 303, 307, 308):
            new_url = headers.get("location", "")
            if new_url.startswith("/"):
                new_url = f"{scheme}://{host}{new_url}"
            print(f"[redirect] {status_code} -> {new_url}")
            url = new_url
            continue

        # Decodare body
        encoding = "utf-8"
        content_type = headers.get("content-type", "")
        if "charset=" in content_type:
            encoding = content_type.split("charset=")[-1].strip()

        # Chunked transfer encoding
        if headers.get("transfer-encoding", "").lower() == "chunked":
            body = decode_chunked(body)

        body_text = body.decode(encoding, errors="replace")

        result = {
            "status": status_code,
            "headers": headers,
            "content_type": content_type,
            "body": body_text,
            "url": url,
        }

        # Salvam in cache (memorie + disk)
        save_to_cache(cache_key, result)
        return result

    print("Prea multe redirecturi!")
    sys.exit(1)


def build_url_candidates(raw_url: str):
    """Genereaza variante de URL pentru input-uri scurte."""
    value = raw_url.strip()
    if not value:
        return []

    if not value.startswith("http://") and not value.startswith("https://"):
        value = "https://" + value

    parsed = urlparse(value)
    host = parsed.hostname

    if not host:
        return [value]

    # Nu completam automat localhost sau IP-uri.
    try:
        ipaddress.ip_address(host)
        return [value]
    except ValueError:
        pass

    if host == "localhost" or "." in host:
        return [value]

    candidates = [value]
    candidates.append(value.replace(f"//{host}", f"//{host}.com", 1))
    candidates.append(value.replace(f"//{host}", f"//www.{host}.com", 1))

    unique = []
    for item in candidates:
        if item not in unique:
            unique.append(item)
    return unique


def decode_chunked(data: bytes) -> bytes:
    """Decodeaza Transfer-Encoding: chunked."""
    result = b""
    while data:
        crlf = data.find(b"\r\n")
        if crlf == -1:
            break
        size = int(data[:crlf], 16)
        if size == 0:
            break
        result += data[crlf + 2 : crlf + 2 + size]
        data = data[crlf + 2 + size + 2:]
    return result


# ─── HTML → TEXT ──────────────────────────────────────────────────────────────

def html_to_text(html: str) -> str:
    """Converteste HTML in text lizibil fara librarii externe."""
    import re

    # Eliminam <script> si <style>
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Adaugam newline la taguri de bloc
    for tag in ["p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]:
        html = re.sub(rf"</?{tag}[^>]*>", "\n", html, flags=re.IGNORECASE)

    # Eliminam toate tagurile ramase
    html = re.sub(r"<[^>]+>", "", html)

    # Decodare entitati HTML de baza
    entities = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&nbsp;": " ",
        "&apos;": "'", "&mdash;": "—", "&ndash;": "–",
        "&laquo;": "«", "&raquo;": "»",
    }
    for ent, char in entities.items():
        html = html.replace(ent, char)

    # Curatam linii goale multiple
    lines = [line.strip() for line in html.splitlines()]
    lines = [l for l in lines if l]
    return "\n".join(lines)


# ─── SEARCH ───────────────────────────────────────────────────────────────────

def search(term: str):
    """Cauta pe DuckDuckGo si afiseaza top 10 rezultate."""
    import re

    query = quote_plus(term)
    url = f"https://html.duckduckgo.com/html/?q={query}"

    print(f"Caut: {term}\n")
    response = make_request(url)
    body = response["body"]

    # Extragem rezultatele din HTML
    results = []

    # DuckDuckGo HTML: titlul e in <a class="result__a" href="...">
    pattern = re.compile(
        r'<a[^>]+class=["\']result__a["\'][^>]+href=["\'](.*?)["\'][^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    for match in pattern.finditer(body):
        href = match.group(1).strip()
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()

        # DuckDuckGo foloseste uneori redirecturi interne
        if href.startswith("//duckduckgo.com/l/?"):
            uddg = re.search(r"uddg=([^&]+)", href)
            if uddg:
                from urllib.parse import unquote
                href = unquote(uddg.group(1))

        if href.startswith("http") and title:
            results.append((title, href))

        if len(results) >= 10:
            break

    if not results:
        print("Nu s-au gasit rezultate.")
        return []

    print(f"Top {len(results)} rezultate pentru '{term}':\n")
    for i, (title, link) in enumerate(results, 1):
        print(f"{i}. {title}")
        print(f"   {link}\n")

    return results


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def show_help():
    print("""
go2web - HTTP over TCP Sockets
================================
Utilizare:
  go2web -u <URL>          Face un request HTTP la URL si afiseaza raspunsul
  go2web -s <termen>       Cauta termenul si afiseaza top 10 rezultate
  go2web -h                Afiseaza acest ajutor

Exemple:
  go2web -u https://example.com
  go2web -s retele de calculatoare
""")


def cmd_url(url: str):
    candidates = build_url_candidates(url)
    if not candidates:
        print("URL invalid.")
        return

    response = None
    last_error = None

    for attempt_url in candidates:
        print(f"Conectare la: {attempt_url}\n")
        try:
            response = make_request(attempt_url)
            break
        except (socket.gaierror, TimeoutError, OSError, ssl.SSLError) as exc:
            last_error = exc

    if response is None:
        print("Nu am putut rezolva/adresa serverul pentru URL-ul introdus.")
        print("Verifica URL-ul (ex: google.com) si conexiunea la internet.")
        if last_error:
            print(f"Detalii: {last_error}")
        return

    content_type = response["content_type"]

    if "json" in content_type:
        try:
            data = json.loads(response["body"])
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:
            print(response["body"])
    else:
        text = html_to_text(response["body"])
        print(text)


def main():
    # Curatamorb cache-ul vechi la startup
    cleanup_old_cache()

    args = sys.argv[1:]

    if not args or args[0] == "-h":
        show_help()
        return

    if args[0] == "-u":
        if len(args) < 2:
            print("Eroare: specificati un URL dupa -u")
            sys.exit(1)
        cmd_url(args[1])

    elif args[0] == "-s":
        if len(args) < 2:
            print("Eroare: specificati un termen de cautare dupa -s")
            sys.exit(1)
        term = " ".join(args[1:])
        results = search(term)

        # Optiune interactiva: deschide un link din rezultate
        if results:
            print("Vrei sa accesezi un link? Scrie numarul (sau Enter pentru a iesi):")
            try:
                choice = input("> ").strip()
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(results):
                        cmd_url(results[idx][1])
            except (KeyboardInterrupt, EOFError):
                pass
    else:
        print(f"Optiune necunoscuta: {args[0]}")
        show_help()
        sys.exit(1)


if __name__ == "__main__":
    main()