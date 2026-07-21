> **Disclaimer:** This code and README are AI-generated and may contain bugs even though reviewed.

# ABTestSetup — mitmproxy addons

Set up a mitmproxy to replace or modify parts of websites on-the-fly.


## Quick Start

```bash
# Run mitmweb with the desired addons
mitmweb --listen-host :: --listen-port 8080 -s webp_converter.py

# Or alongside the gateway
python3 gateway.py --proxy '[::1]:8080' --tunnel
```

## Configuration (`experiment.yaml`)

All addons read from a single `experiment.yaml` file. See each section below for its config keys.

---

## `gateway.py` — Reverse Proxy Gateway

A lightweight aiohttp reverse proxy that forwards requests to a target site, optionally through mitmproxy.

### Features

- URL rewriting for same-origin resources
- Cloudflare Tunnel support (`--tunnel`)
- Configurable proxy, target, and rewrite hosts
- Content-Type normalization (SCSS → CSS, etc.)

### Usage

```bash
python3 gateway.py --proxy '[::1]:8080' --target https://example.com
python3 gateway.py --proxy '[::1]:8080' --target https://example.com --tunnel
```

---

## `webp_converter.py` — Image-to-WebP Conversion

Automatically converts JPEG/PNG images to WebP format.


### Cache

- Location: `img_cache/` directory (created automatically).
- Format: `{sha256_hash}.webp` (converted) or `{sha256_hash}.jpg/.png` (raw).
- Cache key is `SHA256(url + original_bytes)`.

### Logging (`proxy_log.csv`)

Format: `{timestamp},{state},{url},{filename},{cache_key}`

States: `HIT_WEBP`, `MISS_WEBP`, `HIT_RAW`, `MISS_RAW`

---

## `img_resizer.py` — Image Resizing

Resizes images to fit within a configurable max dimension while maintaining aspect ratio.

---

## `db_js_replacer.py` — JavaScript Function Replacement

On-the-fly replacement of JavaScript function calls or function bodies via mitmproxy.

### Two Modes

| Mode | What it does |
|------|-------------|
| `call` | Replaces a specific function call with `void 0` (no-op). The rest of the code keeps running. |
| `stub` | Replaces the entire function body with `{}`. Nothing inside executes. |


### Call Patterns

`call_patterns` uses regex to match the entire call (function name + arguments + context), not just the function name:

| Pattern | Matches |
|---------|---------|
| `'y\("event"\)'` | `y("event")` |
| `'P\.k\.v4\(\)'` | `P.k.v4()` |
| `'i\.RE\(\)'` | `i.RE()` |
| `'F\(l\)'` | `F(l)` |
| `'this\.exportEntry\([^)]*\)'` | `this.exportEntry(a, b)` |

### Stub Mode

```yaml
mode: "stub"
stub_functions:
  - "track"
```

Replaces the function body with `{}`. Handles multiple JS syntax forms:

- `logEvent: (e, t) => { ... }` (arrow function property)
- `logEvent: function(e, t) { ... }` (regular function property)
- `this.logEvent = (e, t) => { ... }` (arrow function assignment)
- `exportEntry(params) { ... }` (class method)

---

## `css_replacer.py` — CSS Consolidation

Downloads multiple CSS files, merges them into one, caches it server-side, and rewrites HTML to serve a single `<link>` tag.

### Features

- **Server-side caching**: Combined CSS is cached on disk.
- **Two modes**: `replace_all` (all CSS) or `matched` (only target URLs).
- **Browser caching disabled**: `Cache-Control: no-store` on combined file.

### Configuration

```yaml
css_replacement:
  enabled: true
  replace_mode: "replace_all"    # "replace_all" or "matched"
  target_urls:
    - "*example.com/*.css"
```

---

## Safety

All addons follow these principles:

- **Fail-open**: If anything goes wrong, the original response passes through unchanged.
- **Cache-busting**: Response headers prevent the browser from caching modified content (hopefully).
- **Hot-reload config**: Config is reloaded every second, so changes take effect without restarting mitmproxy.
