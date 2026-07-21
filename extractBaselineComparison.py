#!/usr/bin/env python3
"""Extract baseline metrics for the 6 perfetto-baseline websites from
Green Coding, Website Carbon, EcoGrader, and Perfetto, then merge for comparison.

Usage:
    python3 extractBaselineComparison.py            # prints table + writes CSV
    python3 extractBaselineComparison.py --csv-only  # writes CSV only
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths (relative to workspace root)
# ---------------------------------------------------------------------------
WS = Path(__file__).resolve().parent
GM_DIR = WS / "tool_analysis" / "data" / "greenmetrics"
GC_CSV = WS / "tool_analysis" / "greencoding.csv"
WC_CSV = WS / "tool_analysis" / "websitecarbon.csv"
ECO_CSV = WS / "tool_analysis" / "ecograder.csv"
ECO_PAGES = WS / "tool_analysis" / "data" / "ecograder"
PERFETTO_DIR = WS / "measurements"
OUT_CSV = WS / "baseline_comparison.csv"

DATA_FACTOR = 0.04106063  # kWh per GB (from Green Coding / webNRJ)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def uj_to_j(uj: float) -> float:
    return uj * 1e-6


def kwh_to_j(kwh: float) -> float:
    return kwh * 3_600_000


def normalize_domain(url: str) -> str:
    s = url.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0]
    s = re.sub(r"^www\.", "", s)
    return s


# ---------------------------------------------------------------------------
# 1. Perfetto baselines — drives the domain list
# ---------------------------------------------------------------------------
def load_perfetto_baselines() -> pd.DataFrame:
    rows = []
    for variant_dir in sorted(PERFETTO_DIR.glob("runs_*/*_baseline")):
        if not variant_dir.is_dir():
            continue
        domain = variant_dir.name.replace("_baseline", "")
        domain_key = normalize_domain(domain)

        result_path = variant_dir / "result.json"
        network_path = variant_dir / "network_bytes.json"

        perfetto_j = external_j = perfetto_avg_j = external_avg_j = float("nan")
        page_weight = requests = float("nan")

        if result_path.exists():
            with open(result_path) as f:
                r = json.load(f)
            e = r.get("energy", {})
            perfetto_j = e.get("perfetto_j", float("nan"))
            external_j = e.get("external_j", float("nan"))
            perfetto_avg_j = e.get("perfetto_avg_j", float("nan"))
            external_avg_j = e.get("external_avg_j", float("nan"))

        if network_path.exists():
            with open(network_path) as f:
                loads = json.load(f)
            if loads:
                positive = [float(e["total_bytes"]) for e in loads
                            if "total_bytes" in e and float(e.get("total_bytes", 0)) > 0]
                if len(positive) >= 2:
                    med = statistics.median(positive)
                    threshold = med * 0.1
                    valid_bytes, valid_reqs = [], []
                    for i, entry in enumerate(loads):
                        if i == 0:
                            continue
                        val = float(entry.get("total_bytes", 0))
                        if val <= threshold:
                            continue
                        valid_bytes.append(val)
                        valid_reqs.append(int(entry.get("request_count", 0)))
                    if valid_bytes:
                        page_weight = statistics.median(valid_bytes)
                        requests = statistics.mean(valid_reqs)

        rows.append({
            "domain": domain_key,
            "url_perfetto": f"https://{domain}",
            "perfetto_total_j": perfetto_j,
            "external_total_j": external_j,
            "perfetto_avg_j_page": perfetto_avg_j,
            "external_avg_j_page": external_avg_j,
            "perfetto_page_weight_bytes": page_weight,
            "perfetto_requests_per_page": requests,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. Green Coding — only stats.json files matching our domains
# ---------------------------------------------------------------------------
def load_green_coding(domains: set[str]) -> pd.DataFrame:
    gc = pd.read_csv(GC_CSV)
    gc["url"] = gc["url"].astype(str).str.strip().str.lower()
    gc = gc.dropna(subset=["url"]).sort_values("ended_at").drop_duplicates("url", keep="last")
    gc["_domain"] = gc["url"].apply(normalize_domain)
    gc_target = gc[gc["_domain"].isin(domains)]
    gc_map = gc_target.set_index("report_id")[["url", "_domain"]].to_dict("index")

    rows = []
    for stats_file in GM_DIR.glob("*/stats.json"):
        report_id = stats_file.parent.name
        if report_id not in gc_map:
            continue
        url = gc_map[report_id]["url"]
        domain = gc_map[report_id]["_domain"]
        try:
            with open(stats_file) as f:
                stats = json.load(f)
            visit = stats["data"]["data"]["Visit page and idle for 5 s"]["data"]
            d = visit["cpu_power_rapl_msr_component"]["data"]["Package_0"]["data"][report_id]
            cpu_power_mw = d["mean"]
            cpu_energy_uj = visit["cpu_energy_rapl_msr_component"]["data"]["Package_0"]["data"][report_id]["mean"]
            ram_power_mw = visit["memory_power_rapl_msr_component"]["data"]["DRAM_0"]["data"][report_id]["mean"]
            ram_energy_uj = visit["memory_energy_rapl_msr_component"]["data"]["DRAM_0"]["data"][report_id]["mean"]
            page_weight = visit["network_total_cgroup_container"]["data"]["gmt-playwright-nodejs"]["data"][report_id]["mean"]

            cpu_energy_j = uj_to_j(cpu_energy_uj)
            ram_energy_j = uj_to_j(ram_energy_uj)
            network_energy_j = kwh_to_j(DATA_FACTOR * (page_weight / 1024**3))

            rows.append({
                "domain": domain,
                "url_gm": url,
                "gm_cpu_power_mw": float(cpu_power_mw),
                "gm_ram_power_mw": float(ram_power_mw),
                "gm_cpu_energy_j": float(cpu_energy_j),
                "gm_ram_energy_j": float(ram_energy_j),
                "gm_page_weight_bytes": float(page_weight),
                "gm_network_energy_j": float(network_energy_j),
                "gm_estimated_total_energy_j": float(cpu_energy_j + ram_energy_j + network_energy_j),
            })
        except Exception:
            continue

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. Website Carbon — only matching domains
# ---------------------------------------------------------------------------
def load_website_carbon(domains: set[str]) -> pd.DataFrame:
    wc = pd.read_csv(WC_CSV)
    wc["url"] = wc["url"].astype(str).str.strip().str.lower()
    wc = wc.dropna(subset=["url"]).sort_values("scrape_date").drop_duplicates("url", keep="last")
    wc["domain"] = wc["url"].apply(normalize_domain)
    wc = wc[wc["domain"].isin(domains)].copy()
    wc["wc_energy_j"] = wc["energy_kwh"].apply(kwh_to_j)
    return wc[["domain", "url", "co2_grams", "wc_energy_j"]].rename(
        columns={"url": "url_wc", "co2_grams": "wc_co2_grams"}
    )


# ---------------------------------------------------------------------------
# 4. EcoGrader — only matching domains
# ---------------------------------------------------------------------------
def load_ecograder(domains: set[str]) -> pd.DataFrame:
    eco = pd.read_csv(ECO_CSV)
    eco["url"] = eco["url"].astype(str).str.strip().str.lower()
    eco = eco.dropna(subset=["url"]).sort_values("scrape_date").drop_duplicates("url", keep="last")
    eco["domain"] = eco["url"].apply(normalize_domain)
    eco = eco[eco["domain"].isin(domains)]

    rows = []
    for _, row in eco.iterrows():
        rid = row["report_id"]
        report_path = ECO_PAGES / rid / "report.json"
        co2 = row.get("co2_emissions", float("nan"))
        page_weight = float("nan")

        if report_path.exists():
            try:
                with open(report_path) as f:
                    data = json.load(f)
                breakdown = data.get("props", {}).get("breakdownGraphData", {})
                page_weight = float(breakdown.get("total", {}).get("byteTotal", float("nan")))
            except Exception:
                pass

        rows.append({
            "domain": row["domain"],
            "url_eco": row["url"],
            "eco_page_weight_bytes": page_weight,
            "eco_co2_emissions": float(co2) if pd.notna(co2) else float("nan"),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-only", action="store_true", help="Skip printed table, only write CSV")
    args = parser.parse_args()

    perf = load_perfetto_baselines()
    domains = set(perf["domain"])

    gm = load_green_coding(domains)
    wc = load_website_carbon(domains)
    eco = load_ecograder(domains)

    print(f"Domains: {sorted(domains)}", file=sys.stderr)
    print(f"Loaded: GM={len(gm)} WC={len(wc)} Eco={len(eco)} Perfetto={len(perf)}", file=sys.stderr)

    df = gm.merge(wc, on="domain", how="outer")
    df = df.merge(eco, on="domain", how="outer")
    df = df.merge(perf, on="domain", how="outer")
    df = df.sort_values("domain").reset_index(drop=True)

    drop_cols = [c for c in ["gm_network_energy_j", "gm_estimated_total_energy_j", "wc_energy_j"] if c in df.columns]
    df = df.drop(columns=drop_cols)

    gm_total = df["gm_cpu_energy_j"] + df["gm_ram_energy_j"]
    df["px_per_gm_ratio"] = df["perfetto_avg_j_page"] / gm_total

    df.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}", file=sys.stderr)

    if not args.csv_only:
        print()

        def f(b, fmt="bytes"):
            if pd.isna(b):
                return "-"
            if fmt == "bytes":
                return f"{b / 1e6:.1f} MB"
            if fmt == "j":
                return f"{b:.1f}"
            if fmt == "mw":
                return f"{b:.0f}"
            if fmt == "co2":
                return f"{b:.3f}"
            if fmt == "int":
                return f"{b:.0f}"
            if fmt == ".2f":
                return f"{b:.2f}"
            return str(b)

        hdr = (
            f"{'Domain':<25s} "
            f"{'GM PgWt':>10s} {'Eco PgWt':>10s} {'Px PgWt':>10s} "
            f"{'GM CPU mW':>9s} {'GM RAM mW':>9s} "
            f"{'GM CPU J':>10s} {'GM RAM J':>10s} "
            f"{'Px J/pg':>9s} {'Ext J/pg':>9s} "
            f"{'Px/GM':>7s} "
            f"{'WC CO2 g':>9s} {'Eco CO2':>9s} "
            f"{'Px Req/pg':>9s}"
        )
        sep = "-" * len(hdr)

        print(sep)
        print(hdr)
        print(sep)

        for _, r in df.iterrows():
            print(
                f"{r['domain']:<25s} "
                f"{f(r.get('gm_page_weight_bytes')):>10s} "
                f"{f(r.get('eco_page_weight_bytes')):>10s} "
                f"{f(r.get('perfetto_page_weight_bytes')):>10s} "
                f"{f(r.get('gm_cpu_power_mw'), 'mw'):>9s} "
                f"{f(r.get('gm_ram_power_mw'), 'mw'):>9s} "
                f"{f(r.get('gm_cpu_energy_j'), 'j'):>10s} "
                f"{f(r.get('gm_ram_energy_j'), 'j'):>10s} "
                f"{f(r.get('perfetto_avg_j_page'), 'j'):>9s} "
                f"{f(r.get('external_avg_j_page'), 'j'):>9s} "
                f"{f(r.get('px_per_gm_ratio'), '.2f'):>7s} "
                f"{f(r.get('wc_co2_grams'), 'co2'):>9s} "
                f"{f(r.get('eco_co2_emissions'), 'co2'):>9s} "
                f"{f(r.get('perfetto_requests_per_page'), 'int'):>9s}"
            )

        print(sep)


if __name__ == "__main__":
    main()
