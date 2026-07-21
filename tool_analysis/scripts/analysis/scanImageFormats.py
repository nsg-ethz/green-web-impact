"""
Fetch each URL from ecograder.csv, scan for image formats,
and save per-page results as images.json in pages/<report_id>/.

Reports stats for:
  1. All ecograder pages
  2. The dataExtracted.csv subset
"""

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

PAGES_DIR = Path("data/ecograder")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"}
IMG_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "avif", "svg", "ico", "bmp", "tiff"}
TIMEOUT = 30
MAX_WORKERS = 8


def scan_images(url):
    """Fetch a URL and extract image format counts from the HTML."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        if "text/html" not in r.headers.get("content-type", ""):
            return None, "not html"

        soup = BeautifulSoup(r.text, "html.parser")
        fmts = Counter()
        total = 0

        for tag in soup.find_all("img"):
            src = tag.get("src", "")
            if not src or src.startswith("data:"):
                continue
            ext = src.rsplit(".", 1)[-1].lower().split("?")[0].split("#")[0]
            if ext in IMG_EXTS:
                fmts[ext] += 1
                total += 1

        for tag in soup.find_all("source"):
            stype = tag.get("type", "")
            if "webp" in stype:
                fmts["webp"] += 1
                total += 1
                continue
            if "avif" in stype:
                fmts["avif"] += 1
                total += 1
                continue
            srcset = tag.get("srcset", "")
            for entry in srcset.split(","):
                part = entry.strip().split()[0]
                if not part or part.startswith("data:"):
                    continue
                ext = part.rsplit(".", 1)[-1].lower().split("?")[0].split("#")[0]
                if ext in IMG_EXTS:
                    fmts[ext] += 1
                    total += 1

        return {"total": total, "formats": dict(fmts), "status": "ok"}, None

    except Exception as e:
        return None, str(e)[:120]


def print_stats(label, collected):
    """Print format breakdown for a list of (url, data) tuples."""
    fmts = Counter()
    total = 0
    pages_with_images = 0

    for url, data in collected:
        t = data.get("total", 0)
        total += t
        if t > 0:
            pages_with_images += 1
        for k, v in data.get("formats", {}).items():
            fmts[k] += v

    print(f"\n{'=' * 50}")
    print(f"{label}  ({len(collected)} pages, {pages_with_images} with images)")
    print(f"{'=' * 50}")
    print(f"Total image references: {total}")

    if total > 0:
        for fmt, count in fmts.most_common():
            print(f"  {fmt:>6s}: {count:>5d}  ({count / total * 100:5.1f}%)")
        modern = fmts.get("webp", 0) + fmts.get("avif", 0)
        pages_webp = sum(1 for _, d in collected if d.get("formats", {}).get("webp", 0) > 0)
        pages_avif = sum(1 for _, d in collected if d.get("formats", {}).get("avif", 0) > 0)
        print(f"\nModern (webp+avif): {modern}/{total} = {modern / total * 100:.1f}%")
        print(f"Pages using webp: {pages_webp}/{len(collected)}")
        print(f"Pages using avif: {pages_avif}/{len(collected)}")
    else:
        print("  No images found.")


def main():
    eco = pd.read_csv("ecograder.csv")
    df = pd.read_csv("dataExtracted.csv")

    subset_urls = set(df["url"].dropna().unique())
    url_to_report = dict(zip(eco["url"], eco["report_id"]))

    all_urls = eco["url"].dropna().unique().tolist()
    print(f"Total ecograder URLs: {len(all_urls)}")

    ok = 0
    fail = 0
    skipped = 0
    all_collected = []

    def process(url):
        report_id = url_to_report.get(url)
        if not report_id:
            return url, None, "no report_id"

        out_path = PAGES_DIR / report_id / "images.json"
        if out_path.exists():
            # Load from disk
            try:
                data = json.loads(out_path.read_text())
                return url, data, "cached"
            except Exception:
                pass

        data, err = scan_images(url)
        if data:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(data, indent=2))
            return url, data, None
        return url, None, err

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(process, u): u for u in all_urls}
        for i, f in enumerate(as_completed(futures)):
            url, data, status = f.result()
            if data:
                ok += 1
                all_collected.append((url, data))
                if status == "cached":
                    skipped += 1
            else:
                fail += 1

            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(all_urls)} (ok={ok} fail={fail} cached={skipped})")

    print(f"\nDone: {ok} ok, {fail} failed, {skipped} loaded from cache")

    # --- Stats for ALL ecograder pages ---
    print_stats("All ecograder pages", all_collected)

    # --- Stats for dataExtracted subset ---
    subset_collected = [(u, d) for u, d in all_collected if u in subset_urls]
    print_stats("dataExtracted subset", subset_collected)


if __name__ == "__main__":
    main()
