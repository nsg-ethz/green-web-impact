import threading
import time

import yaml
from bs4 import BeautifulSoup
from mitmproxy import http

CONFIG_PATH = "experiment.yaml"

config_cache = {}
last_load = 0
lock = threading.Lock()


# -----------------------------
# CONFIG HOT RELOAD
# -----------------------------
def load_config():
    global config_cache, last_load
    now = time.time()
    with lock:
        if now - last_load > 1:
            try:
                with open(CONFIG_PATH, "r") as f:
                    config_cache = yaml.safe_load(f) or {}
            except Exception:
                config_cache = {}
            last_load = now
    return config_cache


# -----------------------------
# EMBED URL DETECTION
# -----------------------------
def is_video_embed(url: str, block_domains: list) -> bool:
    url_lower = url.lower()
    return any(domain.lower() in url_lower for domain in block_domains)


# -----------------------------
# HTML INTERCEPT
# -----------------------------
def response(flow: http.HTTPFlow):
    cfg = load_config()
    eb_cfg = cfg.get("embed_blocker", {})

    if not eb_cfg.get("enabled", False):
        return

    block_domains = eb_cfg.get("block_domains", ["youtube.com"])

    if not flow.response:
        return

    ct = (flow.response.headers.get("content-type", "")).lower()
    if "text/html" not in ct:
        return

    try:
        body = flow.response.get_text()
        if not body:
            return

        soup = BeautifulSoup(body, "html.parser")

        # Remove iframe embeds
        removed_iframes = 0
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src", "")
            if src and is_video_embed(src, block_domains):
                placeholder = soup.new_tag(
                    "div",
                    attrs={
                        "style": "background:#1a1a1a;color:#888;padding:2rem;text-align:center;font-family:sans-serif;",
                        "data-blocked-embed": src,
                    },
                )
                placeholder.string = f"[Blocked embed: {src}]"
                iframe.replace_with(placeholder)
                removed_iframes += 1

        # Remove video tags pointing to embed URLs
        removed_videos = 0
        for video in soup.find_all("video"):
            src = video.get("src", "")
            sources = video.find_all("source")
            source_urls = [s.get("src", "") for s in sources if s.get("src")]
            if (src and is_video_embed(src, block_domains)) or any(
                is_video_embed(u, block_domains) for u in source_urls
            ):
                video.decompose()
                removed_videos += 1

        # Remove object/embed tags
        removed_objects = 0
        for tag_name in ["object", "embed"]:
            for tag in soup.find_all(tag_name):
                tag_url = tag.get("data", tag.get("src", ""))
                if tag_url and is_video_embed(tag_url, block_domains):
                    tag.decompose()
                    removed_objects += 1

        total = removed_iframes + removed_videos + removed_objects
        if total > 0:
            print(
                f"[embed_blocker] Removed {total} embed(s) from {flow.request.pretty_url}"
            )
            flow.response.text = str(soup)
            flow.response.headers["cache-control"] = "no-store, no-cache, must-revalidate"

    except Exception as e:
        print(f"[embed_blocker] Error processing {flow.request.pretty_url}: {e}")
        return
