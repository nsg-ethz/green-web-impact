import argparse
import re
import subprocess
import threading
from urllib.parse import urljoin, urlparse

import requests
from aiohttp import web
from bs4 import BeautifulSoup

PROXY = None
TARGET = "https://example.com"
REWRITE_HOSTS = set()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Accept": "*/*",
}


# ----------------------------
# Tunnel
# ----------------------------
def start_tunnel(port):
    process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def log_reader():
        try:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                print("[cloudflared]", line.rstrip())
        except Exception as e:
            print("[cloudflared] log reader:", e)

    threading.Thread(target=log_reader, daemon=True).start()

    return process


# ----------------------------
# MIME normalization
# ----------------------------
def normalize_content_type(ct, url):
    if not ct:
        return "application/octet-stream"

    ct = ct.split(";")[0].strip().lower()
    path = urlparse(url).path.lower()

    if ct in ("text/x-scss", "text/scss", "application/x-scss"):
        return "text/css"

    if path.endswith(".css") or path.endswith(".scss"):
        return "text/css"

    if path.endswith(".js"):
        return "application/javascript"

    if "html" in ct:
        return "text/html"

    return ct


# ----------------------------
# HTML detection
# ----------------------------
def looks_like_html(content_type, body):
    ct = (content_type or "").lower()

    if "html" in ct:
        return True

    stripped = body.lstrip()

    return (
        stripped.startswith(b"<!doctype")
        or stripped.startswith(b"<html")
        or b"<head" in stripped[:500]
    )


# ----------------------------
# HTML rewriting (SAFE VERSION)
# ----------------------------
def rewrite_html(html, base_url):
    soup = BeautifulSoup(html, "html.parser")

    base_host = urlparse(base_url).netloc.lower()

    def fix(u):
        if not u:
            return u

        parsed = urlparse(u)

        if parsed.scheme not in ("http", "https"):
            return u

        host = parsed.netloc.split(":")[0].lower()

        # ONLY rewrite same-origin or explicitly allowed hosts
        if host == base_host or host in REWRITE_HOSTS:
            return parsed.path + (("?" + parsed.query) if parsed.query else "")

        # IMPORTANT: keep external CDNs intact
        return u

    for tag, attr in [
        ("a", "href"),
        ("img", "src"),
        ("script", "src"),
        ("link", "href"),
        ("iframe", "src"),
        ("source", "src"),
    ]:
        for t in soup.find_all(tag):
            if t.has_attr(attr):
                t[attr] = fix(t[attr])

    return str(soup)


# ----------------------------
# MAIN HANDLER (FIXED ROUTING LOGIC)
# ----------------------------
async def handler(request):
    path = request.match_info.get("path", "")

    # ✔ CRITICAL FIX:
    # If it's already an absolute URL, respect it
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = urljoin(TARGET.rstrip("/") + "/", path)

    if request.query_string:
        url += "?" + request.query_string

    try:
        proxies = None
        if PROXY:
            proxies = {"http": PROXY, "https": PROXY}

        forward_headers = {
            "User-Agent": request.headers.get("User-Agent", HEADERS["User-Agent"]),
            "Accept": request.headers.get("Accept", "*/*"),
        }

        r = requests.get(
            url,
            verify=False,
            headers=forward_headers,
            proxies=proxies,
            timeout=20,
        )

        raw_ct = r.headers.get("content-type", "")
        content_type = normalize_content_type(raw_ct, url)
        body = r.content

        # ----------------------------
        # HTML
        # ----------------------------
        if looks_like_html(content_type, body):
            html = rewrite_html(
                body.decode("utf-8", errors="ignore"),
                r.url,
            )

            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )

        # ----------------------------
        # EVERYTHING ELSE (CSS / JS / images / fonts)
        # ----------------------------
        return web.Response(
            body=body,
            content_type=content_type,
            headers={"Cache-Control": "no-store"},
        )

    except Exception as e:
        print("gateway error:", e)
        return web.Response(text=str(e), status=500)


# ----------------------------
# APP
# ----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--port", type=int, default=3232)
    parser.add_argument("--proxy", type=str, default="[::1]:8080")
    parser.add_argument("--tunnel", action="store_true")

    parser.add_argument("--target", type=str, default="https://example.com")

    parser.add_argument(
        "--rewrite",
        type=str,
        default="",
        help="comma-separated allowed rewrite hosts",
    )

    args = parser.parse_args()

    PROXY = args.proxy
    TARGET = args.target

    if args.rewrite:
        REWRITE_HOSTS = {
            h.strip().lower() for h in args.rewrite.split(",") if h.strip()
        }

    tunnel = None

    if args.tunnel:
        tunnel = start_tunnel(args.port)

    # Follow redirect to get the effective target
    try:
        r = requests.head(
            TARGET,
            verify=False,
            headers={"User-Agent": HEADERS["User-Agent"]},
            timeout=10,
            allow_redirects=True,
        )
        TARGET = r.url
    except Exception:
        pass

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)

    web.run_app(app, port=args.port)
