import gc
import hashlib
import os
import time

import pyvips
import yaml
from mitmproxy import http

CONFIG_PATH = "experiment.yaml"
CACHE_DIR = "img_cache"
LOG_FILE = "proxy_log.csv"

config_cache = {}
last_load = 0

os.makedirs(CACHE_DIR, exist_ok=True)


# -----------------------------
# CONFIG HOT RELOAD
# -----------------------------
def load_config():
    global config_cache, last_load
    now = time.time()

    if now - last_load > 1:
        with open(CONFIG_PATH, "r") as f:
            config_cache = yaml.safe_load(f)
        last_load = now

    return config_cache


# -----------------------------
# BLOCKING
# -----------------------------
def is_blocked(host, cfg):
    return any(b in host for b in cfg.get("block_domains", []))


# -----------------------------
# CACHE KEY
# -----------------------------
def make_key(url: str, data: bytes) -> str:
    h = hashlib.sha256()
    h.update(url.encode("utf-8"))
    h.update(data)
    return h.hexdigest()


def cache_path(key: str, ext: str):
    return os.path.join(CACHE_DIR, f"{key}.{ext}")


# -----------------------------
# IMAGE CONVERSION (STABLE)
# -----------------------------
def convert_to_webp(data: bytes, quality: int) -> bytes:
    img = pyvips.Image.new_from_buffer(data, "", access="sequential")
    out = img.webpsave_buffer(Q=quality)
    del img
    gc.collect()
    return out


# -----------------------------
# LOGGING
# -----------------------------
def log_event(state, url, key, path):
    line = f"{time.time()},{state},{url},{os.path.basename(path)},{key}\n"
    print(line, flush=True)

    with open(LOG_FILE, "a") as f:
        f.write(line)


# -----------------------------
# REQUEST CLEANUP (KEEP THIS!)
# -----------------------------
def request(flow: http.HTTPFlow):
    flow.request.headers.pop("if-none-match", None)
    flow.request.headers.pop("if-modified-since", None)
    flow.request.headers.pop("cache-control", None)


# -----------------------------
# SAFE BUFFER ACCESS (CRITICAL FIX)
# -----------------------------
def get_bytes(flow: http.HTTPFlow) -> bytes:
    # avoids extra retained references in mitmproxy internals
    return bytes(flow.response.get_content())


# -----------------------------
# RESPONSE HOOK
# -----------------------------
def response(flow: http.HTTPFlow):
    cfg = load_config()

    host = flow.request.pretty_host
    if is_blocked(host, cfg):
        return

    ct = flow.response.headers.get("content-type", "").lower()
    if "image/jpeg" not in ct and "image/png" not in ct:
        return

    try:
        url = flow.request.pretty_url
        enabled = cfg.get("enabled", False)

        # ⚠️ IMPORTANT: do NOT hold reference longer than needed
        original = get_bytes(flow)
        key = make_key(url, original)

        # =========================================================
        # WEBP MODE
        # =========================================================
        if enabled:
            path = cache_path(key, "webp")

            if os.path.exists(path):
                with open(path, "rb") as f:
                    webp = f.read()

                flow.response = http.Response.make(
                    flow.response.status_code,
                    webp,
                    {
                        "Content-Type": "image/webp",
                        "Content-Length": str(len(webp)),
                        "Cache-Control": "no-store",
                        "X-Cache": "HIT",
                    },
                )

                log_event("HIT_WEBP", url, key, path)
                return

            webp = convert_to_webp(original, cfg.get("quality", 70))

            with open(path, "wb") as f:
                f.write(webp)

            flow.response = http.Response.make(
                flow.response.status_code,
                webp,
                {
                    "Content-Type": "image/webp",
                    "Content-Length": str(len(webp)),
                    "Cache-Control": "no-store",
                    "X-Cache": "MISS",
                },
            )

            log_event("MISS_WEBP", url, key, path)

            del original
            gc.collect()
            return

        # =========================================================
        # RAW MODE (FIXED MEMORY BEHAVIOR)
        # =========================================================
        else:
            ext = "jpg" if "jpeg" in ct else "png"
            path = cache_path(key, ext)

            if os.path.exists(path):
                with open(path, "rb") as f:
                    data = f.read()

                flow.response = http.Response.make(
                    flow.response.status_code,
                    data,
                    {
                        "Content-Type": ct,
                        "Content-Length": str(len(data)),
                        "Cache-Control": "no-store",
                        "X-Cache": "HIT_RAW",
                    },
                )

                log_event("HIT_RAW", url, key, path)

                del original
                gc.collect()
                return

            # write once
            with open(path, "wb") as f:
                f.write(original)

            flow.response = http.Response.make(
                flow.response.status_code,
                original,
                {
                    "Content-Type": ct,
                    "Content-Length": str(len(original)),
                    "Cache-Control": "no-store",
                    "X-Cache": "MISS_RAW",
                },
            )

            log_event("MISS_RAW", url, key, path)

            del original
            gc.collect()
            return

    except Exception:
        return
