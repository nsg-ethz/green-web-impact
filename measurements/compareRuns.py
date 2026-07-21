#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

pd.set_option("display.max_columns", None)
pd.set_option("display.width", None)


def load_network_bytes(json_file: Path) -> tuple:
    """Return (valid_values, avg_request_count).

    Two-pass approach to handle data loss from devtools disconnect:
    1. First pass: collect all entries with total_bytes > 0, compute median.
    2. Second pass: skip first entry (cold cache), then only keep entries
       above 10% of the median to filter out partial/broken captures.
    valid_values is a list of individual byte counts for median-based estimation.
    avg_request_count is the mean of request_count over valid entries.
    """
    if not json_file.exists():
        return [], 0.0

    import json
    from statistics import median

    with open(json_file, "r") as f:
        data = json.load(f)

    # --- First pass: collect positive entries to compute median ---
    positive_entries = []
    for entry in data:
        if "total_bytes" in entry:
            try:
                val = float(entry["total_bytes"])
            except (TypeError, ValueError):
                continue
            if val > 0:
                positive_entries.append(val)
        elif "requests" in entry:
            entry_total = 0.0
            for r in entry["requests"]:
                try:
                    val = float(r.get("bytes", 0))
                except (TypeError, ValueError):
                    continue
                if val > 0:
                    entry_total += val
            if entry_total > 0:
                positive_entries.append(entry_total)

    if len(positive_entries) < 2:
        return positive_entries, 0.0

    # Threshold: entries below 10% of the median are likely broken captures
    med = median(positive_entries)
    threshold = med * 0.1

    # --- Second pass: collect valid values with threshold filter ---
    valid_values = []
    total_requests = 0

    for i, entry in enumerate(data):
        # Skip first entry (cold cache load, not representative of warm repeats)
        if i == 0:
            continue

        # primary source (already aggregated per run)
        if "total_bytes" in entry:
            try:
                val = float(entry["total_bytes"])
            except (TypeError, ValueError):
                continue

            if val <= threshold:
                continue

            valid_values.append(val)
            try:
                total_requests += int(entry.get("request_count", 0))
            except (TypeError, ValueError):
                pass
            continue

        # fallback: sum requests if needed
        if "requests" in entry:
            entry_total = 0.0
            for r in entry["requests"]:
                try:
                    val = float(r.get("bytes", 0))
                except (TypeError, ValueError):
                    continue

                if val > 0:
                    entry_total += val

            if entry_total > threshold:
                valid_values.append(entry_total)
                total_requests += len(entry["requests"])

    avg_requests = total_requests / len(valid_values) if valid_values else 0.0
    return valid_values, avg_requests


def estimate_network_metrics(
    valid_values: list,
    sync_events: int,
) -> dict:
    """Estimate total bytes for the run under a Missing At Random (MAR) assumption.

    Uses median of valid measurements (robust to outliers) to impute missing data.
    Returns a dict with all derived network metrics.
    """
    from statistics import median, stdev

    if sync_events <= 0 or not valid_values:
        return {
            "valid_total_bytes": 0.0,
            "valid_measurement_count": 0,
            "estimated_total_bytes": 0.0,
            "median_page_bytes": 0.0,
            "coverage": 0.0,
            "stdev_page_bytes": 0.0,
            "cv_page_bytes": 0.0,
        }

    med_page_bytes = median(valid_values)
    estimated_total_bytes = med_page_bytes * sync_events
    coverage = min((len(valid_values) / sync_events) * 100.0, 100.0)

    if len(valid_values) > 1:
        st = stdev(valid_values)
        cv = st / med_page_bytes * 100.0 if med_page_bytes > 0 else 0.0
    else:
        st = 0.0
        cv = 0.0

    return {
        "valid_total_bytes": sum(valid_values),
        "valid_measurement_count": len(valid_values),
        "estimated_total_bytes": estimated_total_bytes,
        "median_page_bytes": med_page_bytes,
        "coverage": coverage,
        "stdev_page_bytes": st,
        "cv_page_bytes": cv,
    }


def load_wc_json(wc_file: Path) -> dict | None:
    """Load website carbon data from wc.json if it exists."""
    if not wc_file.exists():
        return None
    with open(wc_file, "r") as f:
        data = json.load(f)
    return {
        "wc_energy_kwh": data.get("energy"),
        "wc_grams_co2": data.get("grams"),
        "wc_litres": data.get("litres"),
    }


def normalize_domain(url: str) -> str:
    s = url.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0]
    s = re.sub(r"^www\.", "", s)
    return s


def load_green_coding_data(gm_dir: Path, gc_csv: Path) -> dict:
    """Load Green Coding CPU+RAM energy per page from stats.json files.

    Returns a dict keyed by normalized domain with values
    {"gm_cpu_j": float, "gm_ram_j": float, "gm_total_j": float}.
    """
    gc = pd.read_csv(gc_csv)
    gc["url"] = gc["url"].astype(str).str.strip().str.lower()
    gc = gc.dropna(subset=["url"]).sort_values("ended_at").drop_duplicates(
        "url", keep="last"
    )
    gc["_domain"] = gc["url"].apply(normalize_domain)
    gc_map = gc.set_index("report_id")["_domain"].to_dict()

    gm_data = {}
    for stats_file in gm_dir.glob("*/stats.json"):
        report_id = stats_file.parent.name
        if report_id not in gc_map:
            continue
        domain = gc_map[report_id]
        try:
            with open(stats_file) as f:
                stats = json.load(f)
            visit = stats["data"]["data"]["Visit page and idle for 5 s"]["data"]
            cpu_energy_uj = (
                visit["cpu_energy_rapl_msr_component"]["data"]["Package_0"]
                ["data"][report_id]["mean"]
            )
            ram_energy_uj = (
                visit["memory_energy_rapl_msr_component"]["data"]["DRAM_0"]
                ["data"][report_id]["mean"]
            )
            cpu_j = float(cpu_energy_uj) * 1e-6
            ram_j = float(ram_energy_uj) * 1e-6
            gm_data[domain] = {
                "gm_cpu_j": cpu_j,
                "gm_ram_j": ram_j,
                "gm_total_j": cpu_j + ram_j,
            }
        except (KeyError, json.JSONDecodeError, TypeError, IndexError) as e:
            print(f"  WARNING: skipping Green Coding {stats_file.parent.name}: {e}")
            continue

    return gm_data


def load_runs(base_path: Path, gm_data: dict | None = None):
    runs = []

    for p in sorted(base_path.iterdir()):
        if not p.is_dir():
            continue

        json_file = p / "result.json"
        if not json_file.exists():
            continue

        with open(json_file, "r") as f:
            data = json.load(f)

        sync_events = data["sync"]["events"]

        perfetto = data["energy"]["perfetto_j"]
        external = data["energy"]["external_j"]

        # keep original comparison metric
        diff_pct = ((external - perfetto) / perfetto) * 100.0

        # network: separate raw measurements from estimated totals
        net_file = p / "network_bytes.json"
        valid_values, avg_requests = load_network_bytes(net_file)

        net = estimate_network_metrics(valid_values, sync_events)

        # manual page weight override from result.json
        manual_pw = data.get("network", {}).get("manual_page_weight_bytes")
        if manual_pw is not None:
            net["median_page_bytes"] = float(manual_pw)
            net["estimated_total_bytes"] = float(manual_pw) * sync_events
            net["coverage"] = 100.0

        # kWh/GB uses estimated bytes so energy and bytes cover the same population
        kwh_per_gb = None
        if net["estimated_total_bytes"] > 0:
            kwh_per_gb = (perfetto / net["estimated_total_bytes"]) * (1e9 / 3.6e6)

        # website carbon: prefer wc.json, fall back to result.json section
        wc = load_wc_json(p / "wc.json")
        if wc is None and "website_carbon" in data:
            wc_data = data["website_carbon"]
            wc = {
                "wc_energy_kwh": wc_data.get("energy_kwh"),
                "wc_grams_co2": wc_data.get("grams"),
                "wc_litres": wc_data.get("litres"),
            }

        # Green Coding: extract domain from dir name, look up GM data
        gm = None
        if gm_data:
            domain = normalize_domain(p.name.split("_")[0])
            gm = gm_data.get(domain)

        runs.append(
            {
                "run": p.name,
                "perfetto_j": perfetto,
                "external_j": external,
                "diff_pct": diff_pct,
                "sync_events": sync_events,
                # network metrics
                "valid_total_bytes": net["valid_total_bytes"],
                "valid_measurement_count": net["valid_measurement_count"],
                "estimated_total_bytes": net["estimated_total_bytes"],
                "median_page_bytes": net["median_page_bytes"],
                "network_coverage": net["coverage"],
                "avg_requests": avg_requests,
                "stdev_page_bytes": net["stdev_page_bytes"],
                "cv_page_bytes": net["cv_page_bytes"],
                # derived
                "perfetto_kwh_per_gb": kwh_per_gb,
                # website carbon
                "wc_energy_kwh": wc["wc_energy_kwh"] if wc else None,
                "wc_grams_co2": wc["wc_grams_co2"] if wc else None,
                "wc_litres": wc["wc_litres"] if wc else None,
                # Green Coding
                "gm_cpu_j": gm["gm_cpu_j"] if gm else None,
                "gm_ram_j": gm["gm_ram_j"] if gm else None,
                "gm_total_j": gm["gm_total_j"] if gm else None,
                # rail groups
                "rail_groups": data.get("energy", {}).get("rail_groups", {}),
                # per-page energy stdev
                "perfetto_stdev_j": data.get("energy", {}).get("perfetto_stdev_j"),
                "external_stdev_j": data.get("energy", {}).get("external_stdev_j"),
            }
        )

    return runs


def print_table(runs):
    if not runs:
        print("No runs found.")
        return

    baseline = next(
        (r for r in runs if "baseline" in r["run"].lower()),
        runs[0],
    )

    def per_page(r, key):
        return r[key] / r["sync_events"] if r["sync_events"] > 0 else 0

    # baseline (per-page) — energy uses all pages, bytes uses estimated totals
    base_energy = per_page(baseline, "perfetto_j")
    base_ext_energy = per_page(baseline, "external_j")
    base_mb_per_page = baseline["median_page_bytes"] / 1e6
    base_wc_kwh = baseline["wc_energy_kwh"]

    has_wc = base_wc_kwh is not None
    base_gm_total = baseline.get("gm_total_j")
    has_gm = base_gm_total is not None

    # Determine which rail groups are present
    rail_keys = ["cpu", "wifi_bt", "gpu", "memory", "display", "other"]
    base_rg = baseline.get("rail_groups", {})
    present_rg = [k for k in rail_keys if base_rg.get(k) is not None]

    print("\n====================== ENERGY COMPARISON ======================\n")
    print(f"Reference: {baseline['run']}\n")

    hdr = (
        f"{'RUN':40} "
        f"{'J/page':>10} {'J/pg sd':>10} "
        f"{'Ext J/page':>12} {'E J/pg sd':>10} "
        f"{'MB/page':>10} {'MB/pg sd':>10} "
        f"{'Page %':>9} "
        f"{'Energy %':>10} "
        f"{'Ext Energy %':>13} "
    )
    if has_wc:
        hdr += (
            f"{'WC J/pg':>12} "
            f"{'WC %':>8} "
            f"{'WC g CO2':>10} "
        )
    if has_gm:
        hdr += f"{'GM J/pg':>10} "
    for k in present_rg:
        hdr += f" {k + ' %':>8}"
    hdr += (
        f"{'kWh/GB':>12} "
        f"{'Req/page':>10} "
        f"{'sync':>6}"
    )

    print(hdr)
    print("-" * len(hdr))

    for r in runs:
        energy_page = per_page(r, "perfetto_j")
        ext_page = per_page(r, "external_j")

        # MB/page from median (robust to outliers, same population as energy)
        bytes_page_mb = r["median_page_bytes"] / 1e6

        # baseline comparison — both use estimated page weight
        page_pct = (
            100.0 * bytes_page_mb / base_mb_per_page
            if base_mb_per_page > 0
            else float("nan")
        )

        energy_pct = (
            100.0 * energy_page / base_energy if base_energy > 0 else float("nan")
        )

        ext_energy_pct = (
            100.0 * ext_page / base_ext_energy if base_ext_energy > 0 else float("nan")
        )

        # per-page stdev (within-run)
        pf_sd = r.get("perfetto_stdev_j")
        ex_sd = r.get("external_stdev_j")
        mb_sd = r["stdev_page_bytes"] / 1e6

        line = (
            f"{r['run'][:40]:40} "
            f"{energy_page:10.3f} {(pf_sd if pf_sd is not None else float('nan')):10.3f} "
            f"{ext_page:12.3f} {(ex_sd if ex_sd is not None else float('nan')):10.3f} "
            f"{bytes_page_mb:10.2f} {mb_sd:10.2f} "
            f"{page_pct:8.1f}% "
            f"{energy_pct:9.1f}% "
            f"{ext_energy_pct:12.1f}% "
        )

        if has_wc:
            wc_kwh = r["wc_energy_kwh"]
            wc_j = wc_kwh * 3.6e6 if wc_kwh is not None else None
            wc_pct = (
                100.0 * wc_kwh / base_wc_kwh
                if wc_kwh is not None and base_wc_kwh > 0
                else float("nan")
            )
            wc_g = r["wc_grams_co2"] if r["wc_grams_co2"] is not None else float("nan")
            line += (
                f"{wc_j if wc_j is not None else float('nan'):12.4f} "
                f"{wc_pct:7.1f}% "
                f"{wc_g:10.4f} "
            )

        if has_gm:
            if r is baseline and base_gm_total is not None:
                line += f"{base_gm_total:10.4f} "
            else:
                line += f"{' ':>10} "

        rg = r.get("rail_groups", {})
        for k in present_rg:
            val = rg.get(k)
            base_val = base_rg.get(k)
            if val is not None and base_val is not None and base_val > 0:
                line += f" {100.0 * val / base_val:7.1f}%"
            else:
                line += f" {'nan':>8}"

        kwh_per_gb = r["perfetto_kwh_per_gb"]
        line += (
            f"{(kwh_per_gb if kwh_per_gb is not None else float('nan')):12.6f} "
            f"{r['avg_requests']:10.0f} "
            f"{r['sync_events']:6}"
        )

        print(line)

    print("\n===============================================================\n")

    # Website Carbon summary
    if has_wc:
        base_wc = baseline["wc_energy_kwh"]
        base_g = baseline["wc_grams_co2"]
        print("WEBSITE CARBON ENERGY vs BASELINE (J per page view)")
        print("-----------------------------------------------------")
        for r in runs:
            wc_kwh = r["wc_energy_kwh"]
            if wc_kwh is None or base_wc is None or base_wc == 0:
                continue
            wc_j = wc_kwh * 3.6e6
            pct_of_baseline = 100.0 * wc_kwh / base_wc
            print(
                f"  {r['run'][:40]:40} "
                f"{wc_j:10.4f} J  "
                f"{pct_of_baseline:6.1f}% of baseline"
            )
        print()

    # Green Coding summary
    if has_gm:
        print("GREEN CODING (CPU+RAM J per page, server RAPL)")
        print("----------------------------------------------")
        print(f"  {baseline['run'][:40]:40} {base_gm_total:10.4f} J")
        print()

    # Network variance
    print("NETWORK VARIANCE (median page bytes)")
    print("------------------------------------")
    print(
        f"  {'Run':45} {'Median MB':>10} {'Stdev MB':>10} {'CV %':>8}"
    )
    print("  " + "-" * 75)
    for r in runs:
        med_mb = r["median_page_bytes"] / 1e6
        sd_mb = r["stdev_page_bytes"] / 1e6
        cv = r["cv_page_bytes"]
        print(f"  {r['run'][:45]:45} {med_mb:10.3f} {sd_mb:10.3f} {cv:8.1f}%")
    print()

    # Diagnostics: measurement coverage per run
    print("NETWORK MEASUREMENT DIAGNOSTICS")
    print("-------------------------------")

    for r in runs:
        print(f"\nRun: {r['run']}")
        print(f"  sync events:          {r['sync_events']}")
        print(f"  valid measurements:   {r['valid_measurement_count']}")
        print(f"  coverage:             {r['network_coverage']:.1f}%")

        if r["network_coverage"] < 90.0:
            print(
                f"  WARNING: Low network measurement coverage ({r['network_coverage']:.1f}%)."
            )
            print("  Network-derived metrics may be unreliable.")

    print()


def print_summary(runs):
    if not runs:
        print("No runs found.")
        return

    diffs = [r["diff_pct"] for r in runs]

    avg = sum(diffs) / len(diffs)
    worst = max(diffs)
    best = min(diffs)

    print("SUMMARY")
    print("-------")
    print(f"Runs: {len(runs)}")
    print(f"Average diff: {avg:.2f}%")
    print(f"Worst (higher external): {worst:.2f}%")
    print(f"Best (lower external): {best:.2f}%")
    print()


# ------------------------------------------------------------
# MATRIX CORE
# ------------------------------------------------------------


def build_matrix(runs, key: str):
    names = [r["run"] for r in runs]

    df = pd.DataFrame(index=names, columns=names, dtype=float)
    lookup = {r["run"]: r for r in runs}

    for a in names:
        for b in names:
            va = lookup[a][key]
            vb = lookup[b][key]

            df.loc[a, b] = ((vb - va) / va) * 100.0

    return df


def plot_matrix(matrix: pd.DataFrame, title: str):
    print(f"\nPAIRWISE MATRIX — {title}")
    print("Each cell = (Column run − Row run) / Row run × 100%")
    print("→ Row is baseline, negative means column is more efficient\n")
    print(matrix.round(2))

    fig = go.Figure(
        data=go.Heatmap(
            z=matrix.values,
            x=matrix.columns,
            y=matrix.index,
            colorscale="RdBu",
            zmid=0,
            colorbar=dict(title="% diff"),
        )
    )

    fig.update_layout(
        xaxis_title="Run B",
        yaxis_title="Run A",
        template="plotly_white",
    )

    plots_dir = Path(__file__).resolve().parent / "plots" / "compareRuns"
    plots_dir.mkdir(parents=True, exist_ok=True)

    safe_name = title.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_")
    html_path = plots_dir / f"{safe_name}.html"
    jpg_path = plots_dir / f"{safe_name}.jpg"
    fig.write_html(str(html_path))
    fig.write_image(str(jpg_path), scale=2)
    print(f"Saved: {html_path}, {jpg_path}")


def print_matrices(runs):
    if len(runs) < 2:
        return

    perf_matrix = build_matrix(runs, "perfetto_j")
    ext_matrix = build_matrix(runs, "external_j")

    plot_matrix(perf_matrix, "Pairwise Perfetto Energy Comparison (J)")
    plot_matrix(ext_matrix, "Pairwise External Energy Comparison (J)")

    # website carbon energy matrix (kWh per page view)
    wc_runs = [r for r in runs if r["wc_energy_kwh"] is not None]
    if len(wc_runs) >= 2:
        wc_matrix = build_matrix(wc_runs, "wc_energy_kwh")
        plot_matrix(wc_matrix, "Pairwise Website Carbon Energy Comparison (J/page)")


def main():
    parser = argparse.ArgumentParser(description="Compare Perfetto runs")
    parser.add_argument(
        "--folder",
        type=str,
        default="runs_tv",
        help="Path to the base directory containing run folders (default: runs_tv)",
    )
    parser.add_argument(
        "--gm-dir",
        type=str,
        default=None,
        help="Path to Green Coding greenmetrics directory (default: ../tool_analysis/data/greenmetrics)",
    )
    parser.add_argument(
        "--gc-csv",
        type=str,
        default=None,
        help="Path to greencoding.csv (default: ../tool_analysis/greencoding.csv)",
    )
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Skip plotly pairwise matrix plots",
    )
    args = parser.parse_args()

    base = Path(args.folder)
    script_dir = Path(__file__).resolve().parent
    gm_dir = Path(args.gm_dir) if args.gm_dir else script_dir.parent / "tool_analysis" / "data" / "greenmetrics"
    gc_csv = Path(args.gc_csv) if args.gc_csv else script_dir.parent / "tool_analysis" / "greencoding.csv"

    gm_data = None
    if gm_dir.exists() and gc_csv.exists():
        gm_data = load_green_coding_data(gm_dir, gc_csv)

    runs = load_runs(base, gm_data)

    runs.sort(key=lambda x: abs(x["diff_pct"]), reverse=True)

    print_table(runs)
    print_summary(runs)

    if not args.no_plot:
        print_matrices(runs)


if __name__ == "__main__":
    main()
