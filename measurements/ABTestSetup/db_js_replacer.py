import logging
import re
import threading
import time

import yaml
from mitmproxy import http

CONFIG_PATH = "experiment.yaml"

config_cache = {}
last_load = 0
lock = threading.Lock()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("db_js_replacer")


def load_config():
    global config_cache, last_load
    now = time.time()

    with lock:
        if now - last_load > 1:
            try:
                with open(CONFIG_PATH, "r") as f:
                    config_cache = yaml.safe_load(f)
            except Exception:
                config_cache = {}
            last_load = now

    return config_cache


def url_matches(url: str, patterns: list) -> bool:
    """Check if URL matches any glob-style pattern (supports * wildcards)."""
    for pattern in patterns:
        regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
        if re.search(regex, url):
            return True
    return False


def validate_mode(mode: str) -> str:
    """Validate and return the mode, defaulting to 'call' with a warning."""
    valid_modes = ("call", "stub")
    if mode not in valid_modes:
        log.warning(
            "Invalid mode '%s' for %s. Valid modes: %s. Defaulting to 'call'.",
            mode,
            "js_replacement",
            valid_modes,
        )
        return "call"
    return mode


def request(flow: http.HTTPFlow):
    """Strip caching headers from JS requests so the proxy always gets the latest.

    Without this, the browser may use its cached copy of the JS file instead
    of our modified version, defeating the entire replacement.

    IMPORTANT: This runs unconditionally for target URLs, even when the proxy
    is disabled. If Chrome caches the original JS on the device, re-enabling
    the proxy won't help — Chrome serves the cached copy without ever
    sending the request to the proxy.
    """
    cfg = load_config()
    js_cfg = cfg.get("js_replacement", {})
    target_urls = js_cfg.get("target_urls", [])
    if not target_urls:
        return

    url = flow.request.pretty_url
    if not url_matches(url, target_urls):
        return

    # Strip caching headers so the proxy always fetches and processes the response
    flow.request.headers.pop("if-none-match", None)
    flow.request.headers.pop("if-modified-since", None)
    flow.request.headers.pop("cache-control", None)


def find_matching_brace(text: str, start: int) -> int:
    """Find the index of the closing brace matching the opening brace at `start`.

    Handles nested braces, single/double quotes, and template literals.
    Returns -1 if no matching brace is found.
    """
    depth = 0
    in_single_quote = False
    in_double_quote = False
    in_template_literal = False
    escaped = False

    for i in range(start, len(text)):
        ch = text[i]

        if escaped:
            escaped = False
            continue

        # Handle escape characters
        if ch == "\\":
            escaped = True
            continue

        # Track string/template literal state
        if in_single_quote:
            if ch == "'":
                in_single_quote = False
            continue

        if in_double_quote:
            if ch == '"':
                in_double_quote = False
            continue

        if in_template_literal:
            if ch == "`":
                in_template_literal = False
            continue

        # Enter string literals
        if ch == "'":
            in_single_quote = True
            continue

        if ch == '"':
            in_double_quote = True
            continue

        if ch == "`":
            in_template_literal = True
            continue

        # Count braces (only outside strings)
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i

    return -1


def stub_function_body(js: str, func_name: str, request_url: str = "") -> str:
    """Find and replace the body of a function definition with an empty body.

    Matches function definitions by name with word boundaries, handling multiple
    JS syntax forms.

    Args:
        js: The JavaScript source code.
        func_name: The function name to stub (matched with word boundary).
        request_url: URL for logging purposes.

    Returns:
        The modified JS string.

    Examples matched:
        - logEvent: (e, t) => { ... }
        - logEvent: function(e, t) { ... }
        - this.logEvent = (e, t) => { ... }
        - logEvent: function(e,t) { ... }
    """
    patterns = [
        # Arrow function: logEvent: (params) => {
        rf"(\b{re.escape(func_name)}\s*:\s*\([^)]*\)\s*=>\s*){{",
        # Regular function: logEvent: function(params) {
        rf"(\b{re.escape(func_name)}\s*:\s*function\s*\([^)]*\)\s*){{",
        # Arrow function assignment: this.logEvent = (params) => {
        rf"(this\.{re.escape(func_name)}\s*=\s*\([^)]*\)\s*=>\s*){{",
        # Regular function assignment: this.logEvent = function(params) {
        rf"(this\.{re.escape(func_name)}\s*=\s*function\s*\([^)]*\)\s*){{",
        # Class method: exportEntry(params) { ... }
        rf"(\b{re.escape(func_name)}\s*\([^)]*\)\s*){{",
    ]

    modified = js

    for pattern in patterns:
        for match in re.finditer(pattern, modified):
            open_brace_pos = match.end() - 1  # position of '{'
            close_brace_pos = find_matching_brace(modified, open_brace_pos)

            if close_brace_pos == -1:
                continue  # couldn't find matching brace, skip

            # Replace the body between '{' and '}' with '{}'
            before = modified[:open_brace_pos]
            after = modified[close_brace_pos + 1 :]
            modified = before + "{}" + after
            log.info("Stubbed function '%s' in %s", func_name, request_url)
            break  # only stub the first occurrence per pattern iteration

    return modified


def replace_call(js: str, call_pattern: str, request_url: str = "") -> str:
    """Replace a specific function call with 'void 0'.

    Matches the FULL call pattern (function name + arguments + context),
    not just the function name. This is the key to handling short names
    like 'y', 'F', 'v4' without false positives.

    Args:
        js: The JavaScript source code.
        call_pattern: Regex pattern matching the full call (e.g., 'y\\("event"\\)').
        request_url: URL for logging purposes.

    Returns:
        The modified JS string.

    Examples:
        - 'y\\("event"\\)' matches: y("event")
        - 'P\\.k\\.v4\\(\\)' matches: P.k.v4()
        - 'i\\.RE\\(\\)' matches: i.RE()
    """
    before_len = len(js)
    modified = re.sub(call_pattern, "void 0", js)
    after_len = len(modified)

    if before_len != after_len:
        log.info("Replaced call pattern '%s' in %s", call_pattern, request_url)
    return modified


def response(flow: http.HTTPFlow):
    cfg = load_config()

    if not cfg.get("js_replacement", {}).get("enabled", False):
        return

    # Skip requests without a response (DNS failure, cancelled, etc.)
    if not flow.response:
        return

    js_cfg = cfg.get("js_replacement", {})
    target_urls = js_cfg.get("target_urls", [])
    mode = validate_mode(js_cfg.get("mode", "call"))
    stub_functions = js_cfg.get("stub_functions", [])
    call_patterns = js_cfg.get("call_patterns", [])

    if not target_urls:
        return

    host = flow.request.pretty_host
    url = flow.request.pretty_url

    # Skip blocked domains
    block_domains = cfg.get("block_domains", [])
    if block_domains and any(b in host for b in block_domains):
        return

    # Check if this request matches our target URL pattern
    if not url_matches(url, target_urls):
        return

    # Only handle JS responses
    ct = (flow.response.headers.get("content-type", "")).lower()
    if "application/javascript" not in ct and "text/javascript" not in ct:
        return

    try:
        original_body = flow.response.content
        if not original_body:
            return

        # Decode to string for regex processing
        try:
            body_str = original_body.decode("utf-8")
        except UnicodeDecodeError:
            # Try decompressing gzip/deflate encoded content
            try:
                import gzip

                body_str = gzip.decompress(original_body).decode("utf-8")
            except Exception:
                log.warning("Could not decode JS body for %s, skipping", url)
                return

        modified_body = body_str

        if mode == "call":
            # Remove specific calls by matching the FULL call pattern
            # (function name + arguments + context), not just the name.
            for call_pattern in call_patterns:
                before_len = len(modified_body)
                modified_body = replace_call(modified_body, call_pattern, url)
                after_len = len(modified_body)
                if before_len != after_len:
                    log.info("Replaced call pattern '%s' in %s", call_pattern, url)
        else:
            # Full no-op: replace function bodies with {}
            stubbed = []
            for func_name in stub_functions:
                before = modified_body
                modified_body = stub_function_body(modified_body, func_name, url)
                if before != modified_body:
                    stubbed.append(func_name)

        # Check if anything actually changed
        if modified_body == body_str:
            log.debug("No replacements found in %s, passing through", url)
            return

        # Encode back to bytes
        modified_bytes = modified_body.encode("utf-8")

        # Update the response
        flow.response.content = modified_bytes
        flow.response.headers["content-length"] = str(len(modified_bytes))
        flow.response.headers["x-cache"] = "MISS"
        flow.response.headers["x-js-replacement"] = "db_js_replacer"

        # Cache-busting
        flow.response.headers["cache-control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        flow.response.headers["pragma"] = "no-cache"
        flow.response.headers["expires"] = "0"

        if mode == "call":
            log.info("Call mode: replaced calls in %s", url)
        else:
            log.info("Stub mode: replaced functions in %s", url)

    except Exception as e:
        log.warning("Failed to replace JS for %s: %s", url, e)
        # Fail open — pass through original response
        return
