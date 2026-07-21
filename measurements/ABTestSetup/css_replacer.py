import hashlib
import os
import re
import threading
import time
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup
from mitmproxy import http

CONFIG_PATH = "experiment.yaml"
CACHE_DIR = "css_cache"

os.makedirs(CACHE_DIR, exist_ok=True)

memory_cache = {}  # key -> css bundle
seen_pages = set()  # keys that already had JS injected
config_cache = {}
last_load = 0
lock = threading.Lock()


# -------------------------
# CONFIG
# -------------------------
def load_config():
    global config_cache, last_load
    now = time.time()
    with lock:
        if now - last_load > 1:
            try:
                with open(CONFIG_PATH, "r") as f:
                    config_cache = yaml.safe_load(f) or {}
            except FileNotFoundError:
                config_cache = {}
            last_load = now
    return config_cache


def cache_path(key):
    return os.path.join(CACHE_DIR, f"{key}.css")


# -------------------------
# FETCH CSS
# -------------------------
def fetch_css(urls):
    parts = []
    for u in urls:
        try:
            r = requests.get(u, timeout=10, verify=False)
            if r.ok:
                parts.append(r.text)
        except Exception:
            pass
    return "\n".join(parts)


def patch_runtime(js: str) -> str:
    """
    Robust webpack CSS disabling patch.
    Works across most webpack 4/5 builds.
    """

    # 1. Force all CSS chunks to resolve to bundle.css
    js = re.sub(
        r"""(\bminiCssF\s*=\s*)function\s*\([^\)]*\)\s*\{[^}]*\}""",
        r'\1function(){return "/bundle.css";}',
        js,
        flags=re.S,
    )

    js = re.sub(
        r"""(\bminiCssF\s*=\s*)\([^\)]*\)\s*=>\s*\{[^}]*\}""",
        r'\1() => "/bundle.css"',
        js,
        flags=re.S,
    )

    # 2. Disable CSS chunk loader entirely (most important hook)
    js = re.sub(
        r"""(\bcss.*?chunk.*?load.*?=\s*)function\s*\([^\)]*\)\s*\{""",
        r"\1function(){ return Promise.resolve(); /* patched */ } /*",
        js,
        flags=re.S,
    )

    js = re.sub(
        r"""(\bcss.*?chunk.*?load.*?=\s*)\([^\)]*\)\s*=>\s*\{""",
        r"\1() => Promise.resolve() /* patched */ /*",
        js,
        flags=re.S,
    )

    # 3. Force stylesheet lookup to ALWAYS succeed
    js = re.sub(
        r"""(document\.getElementsByTagName\("link"\)[\s\S]*?return\s+)[^;]+;""",
        r'\1document.head.querySelector("link[rel=stylesheet]");',
        js,
        flags=re.S,
    )

    # 4. Optional hard override: kill CSS existence check entirely
    js = re.sub(
        r"""(if\s*\([^\)]*stylesheet[^\)]*\)\s*return\s*)[a-zA-Z0-9_$]+""",
        r"\1true",
        js,
        flags=re.S,
    )

    return js


# -------------------------
# BUILD / GET BUNDLE
# -------------------------
def ensure_bundle(key, urls):
    if key in memory_cache:
        return memory_cache[key]

    path = cache_path(key)

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            css = f.read()
        memory_cache[key] = css
        return css

    css = fetch_css(urls)

    with open(path, "w", encoding="utf-8") as f:
        f.write(css)

    memory_cache[key] = css
    return css


# -------------------------
# JS INJECTION (phase 2)
# -------------------------
def inject_js():
    return """
<script>
(function () {
    // disable runtime CSS injection
    const orig = document.createElement;

    document.createElement = function (tag) {
        const el = orig.call(document, tag);

        if (tag === "link") {
            Object.defineProperty(el, "href", {
                set(v) {},
                get() { return ""; }
            });

            el.onload = () => {};
            el.onerror = () => {};
        }

        return el;
    };

    // optionally block future CSS loads completely
    const origAppend = Node.prototype.appendChild;
    Node.prototype.appendChild = function (node) {
        if (node && node.tagName === "LINK" && node.rel === "stylesheet") {
            return node; // drop it
        }
        return origAppend.call(this, node);
    };

})();
</script>
"""


# -------------------------
# RESPONSE HOOK
# -------------------------
def response(flow: http.HTTPFlow):
    cfg = load_config()
    if not cfg.get("css_replacement", {}).get("enabled"):
        return

    ct = flow.response.headers.get("content-type", "").lower()

    #
    # Patch webpack runtime JS
    #
    if "javascript" in ct or flow.request.path.endswith(".js"):
        try:
            flow.response.text = patch_runtime(flow.response.get_text())
        except Exception:
            pass
        return

    #
    # Existing HTML handling
    #
    if "text/html" not in ct:
        return

    try:
        soup = BeautifulSoup(flow.response.content, "html.parser")

        links = soup.find_all("link", rel="stylesheet", href=True)
        if not links:
            return

        base = flow.request.url
        urls = [urljoin(base, l["href"]) for l in links]

        key = hashlib.sha256("".join(urls).encode()).hexdigest()

        css = ensure_bundle(key, urls)

        # remove all original CSS links
        for l in links:
            l.decompose()

        # inject bundle CSS
        if soup.head is None:
            soup.html.insert(0, soup.new_tag("head"))

        soup.head.append(
            soup.new_tag("link", rel="stylesheet", href=f"/bundle.css?key={key}")
        )

        # inject JS ONLY on second visit of same bundle
        if key in seen_pages:
            soup.head.append(BeautifulSoup(inject_js(), "html.parser"))
        else:
            seen_pages.add(key)

        flow.response.text = str(soup)

    except Exception:
        pass


# -------------------------
# SERVE BUNDLE
# -------------------------
def request(flow: http.HTTPFlow):
    if not flow.request.path.startswith("/bundle.css"):
        return

    key = flow.request.query.get("key", "")
    if not key:
        flow.response = http.Response.make(400, b"missing key")
        return

    css = memory_cache.get(key)

    if not css:
        path = cache_path(key)
        if not os.path.exists(path):
            flow.response = http.Response.make(404, b"missing bundle")
            return
        with open(path, "r", encoding="utf-8") as f:
            css = f.read()
        memory_cache[key] = css

    flow.response = http.Response.make(
        200,
        css.encode("utf-8"),
        {"content-type": "text/css", "cache-control": "no-store"},
    )
