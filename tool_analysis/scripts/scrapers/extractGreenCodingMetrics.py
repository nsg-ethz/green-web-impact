#!/usr/bin/env python3

import csv
import json
from pathlib import Path

import pandas as pd

PAGES_DIR = Path("data/greenmetrics")
GC_CSV = Path("greencoding.csv")

OUTPUT_FILE = "gc_extracted.csv"

# ----------------------------
# LOAD GC CSV (SOURCE OF TRUTH)
# ----------------------------

gc = pd.read_csv(GC_CSV)

# normalize timestamps
gc["ended_at"] = pd.to_datetime(gc.get("ended_at"), errors="coerce")

# drop rows without timestamps (cannot rank them)
gc = gc.dropna(subset=["ended_at"])

# ----------------------------
# DEDUP REPORT IDS (IMPORTANT)
# keep latest run per report_id
# ----------------------------

gc = gc.sort_values("ended_at").groupby("report_id", as_index=False).tail(1)

# mapping: report_id → url + ended_at
gc_map = {r["report_id"]: (r["url"], r["ended_at"]) for _, r in gc.iterrows()}

valid_report_ids = set(gc_map.keys())

# ----------------------------
# READ FILESYSTEM RESULTS
# ----------------------------

rows = []

for stats_file in PAGES_DIR.glob("*/stats.json"):
    try:
        report_id = stats_file.parent.name

        if report_id not in valid_report_ids:
            continue

        url, ended_at = gc_map[report_id]

        with open(stats_file) as f:
            stats = json.load(f)

        visit = stats["data"]["data"]["Visit page and idle for 5 s"]["data"]

        cpu_energy_uJ = visit["cpu_energy_rapl_msr_component"]["data"]["Package_0"][
            "data"
        ][report_id]["mean"]

        cpu_energy_kwh = cpu_energy_uJ / 3_600_000_000_000

        page_weight_bytes = visit["network_total_cgroup_container"]["data"][
            "gmt-playwright-nodejs"
        ]["data"][report_id]["mean"]

        rows.append(
            {
                "url": url,
                "report_id": report_id,
                "page_weight_bytes": float(page_weight_bytes),
                "cpu_energy_kwh": float(cpu_energy_kwh),
                "ended_at": ended_at,
                "source": "gmt",
                "status": "success",
                "failed": False,
            }
        )

    except Exception:
        continue

# ----------------------------
# BUILD DATAFRAME
# ----------------------------

df = pd.DataFrame(rows)

if df.empty:
    print("No valid GC data found.")
    exit(0)

# ----------------------------
# KEEP ONLY LATEST PER URL
# ----------------------------

df = df.sort_values("ended_at").groupby("url", as_index=False).tail(1)

# ----------------------------
# WRITE OUTPUT
# ----------------------------

df.to_csv(OUTPUT_FILE, index=False)

print(f"Done. Wrote {len(df)} latest GC rows to {OUTPUT_FILE}")
