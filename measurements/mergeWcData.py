#!/usr/bin/env python3
"""Read wc.json from each variant dir and merge into result.json.

For each variant that has a wc.json file:
  - Parses grams, litres, energy (kWh from API), monthly_views
  - Converts energy to joules (kWh * 3_600_000)
  - Adds a "website_carbon" key to result.json
  - Prints a summary line

Variants without wc.json are silently skipped.

Usage:
    python3 mergeWcData.py            # all variants
    python3 mergeWcData.py --dry-run  # print only, don't write
"""

import json
import sys
from pathlib import Path

KWH_TO_J = 3_600_000

PERFETTO_DIR = Path(__file__).resolve().parent

DRY_RUN = "--dry-run" in sys.argv


def main():
    wc_files = sorted(PERFETTO_DIR.glob("runs_*/*/wc.json"))
    if not wc_files:
        print("No wc.json files found.")
        return

    print(f"Found {len(wc_files)} wc.json file(s)\n")
    print(f"{'VARIANT':55s} {'GRAMS':>8s} {'KWH':>12s} {'JOULES':>12s} {'LITRES':>8s}")
    print("-" * 98)

    modified = 0
    for wc_path in wc_files:
        variant_dir = wc_path.parent
        result_path = variant_dir / "result.json"

        if not result_path.exists():
            print(f"  SKIP {variant_dir.name} — no result.json")
            continue

        try:
            with open(wc_path) as f:
                wc = json.load(f)
        except (json.JSONDecodeError, ValueError):
            print(f"  SKIP {variant_dir.name} — wc.json empty or malformed")
            continue

        grams = wc.get("grams", 0)
        litres = wc.get("litres", 0)
        energy_kwh = wc.get("energy", 0)
        energy_j = energy_kwh * KWH_TO_J
        monthly_views = wc.get("monthly_views", 10000)

        with open(result_path) as f:
            result = json.load(f)

        wc_data = {
            "grams": grams,
            "litres": litres,
            "energy_kwh": energy_kwh,
            "energy_j": energy_j,
            "monthly_views": monthly_views,
        }
        result["website_carbon"] = wc_data

        if not DRY_RUN:
            with open(result_path, "w") as f:
                json.dump(result, f, indent=2)
            modified += 1

        print(f"{variant_dir.name:55s} {grams:8.4f} {energy_kwh:12.8f} {energy_j:12.4f} {litres:8.4f}")

    action = "Would modify" if DRY_RUN else "Modified"
    print(f"\n{action} {modified} result.json file(s)")


if __name__ == "__main__":
    main()
