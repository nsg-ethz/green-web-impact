#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from statistics import median, stdev

import pandas as pd
import plotly.graph_objects as go
from scipy.stats import linregress, spearmanr

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------


def load_network_bytes(json_file: Path) -> tuple:
    """Two-pass: skip cold-cache first entry, filter broken captures < 10% of median."""
    if not json_file.exists():
        return [], 0.0

    with open(json_file, "r") as f:
        data = json.load(f)

    positive_entries = []
    for entry in data:
        if "total_bytes" in entry:
            try:
                val = float(entry["total_bytes"])
            except (TypeError, ValueError):
                continue
            if val > 0:
                positive_entries.append(val)

    if len(positive_entries) < 2:
        return positive_entries, 0.0

    med = median(positive_entries)
    threshold = med * 0.1

    valid_values = []
    total_requests = 0

    for i, entry in enumerate(data):
        if i == 0:
            continue

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

    avg_requests = total_requests / len(valid_values) if valid_values else 0.0
    return valid_values, avg_requests


def estimate_network_metrics(valid_values: list, sync_events: int) -> dict:
    """Median-based estimation under MAR assumption."""
    if sync_events <= 0 or not valid_values:
        return {
            "median_page_bytes": 0.0,
            "estimated_total_bytes": 0.0,
            "valid_measurement_count": 0,
            "coverage": 0.0,
            "stdev_page_bytes": 0.0,
            "cv_page_bytes": 0.0,
        }

    med_page_bytes = median(valid_values)
    estimated_total_bytes = med_page_bytes * sync_events
    coverage = min((len(valid_values) / sync_events) * 100.0, 100.0)

    from statistics import stdev

    if len(valid_values) > 1:
        st = stdev(valid_values)
        cv = st / med_page_bytes * 100.0 if med_page_bytes > 0 else 0.0
    else:
        st = 0.0
        cv = 0.0

    return {
        "median_page_bytes": med_page_bytes,
        "estimated_total_bytes": estimated_total_bytes,
        "valid_measurement_count": len(valid_values),
        "coverage": coverage,
        "stdev_page_bytes": st,
        "cv_page_bytes": cv,
    }


def load_external(csv_path: Path, time_offset_sec: float) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    if "measurement_timestamp" not in df.columns:
        raise ValueError("Missing measurement_timestamp column")

    df["measurement_timestamp"] = pd.to_datetime(
        df["measurement_timestamp"],
        utc=True,
        errors="coerce",
    )

    df = df.dropna(subset=["measurement_timestamp"])
    df = df.sort_values("measurement_timestamp")

    t0 = df["measurement_timestamp"].iloc[0]
    df["t_sec"] = (df["measurement_timestamp"] - t0).dt.total_seconds()

    df["t_sec"] += time_offset_sec

    return df


def compute_external_offset(sync_csv: Path, ext_csv: Path) -> float:
    """Compute the time offset to align external trace with Perfetto.

    Uses the first sync event as the common reference:
      external_offset = sync_first_absolute_s - ext_first_absolute_s

    This shifts the external trace so its effective t=0 aligns with the
    first sync event, matching Perfetto's timeline.
    """
    df_sync = pd.read_csv(sync_csv)
    sync_first_s = df_sync["host_ns"].iloc[0] / 1e9

    df_ext = pd.read_csv(ext_csv)
    df_ext["ts_dt"] = pd.to_datetime(
        df_ext["measurement_timestamp"], utc=True, errors="coerce"
    )
    ext_first_s = df_ext["ts_dt"].iloc[0].timestamp()

    return sync_first_s - ext_first_s


def load_perfetto(csv_path: Path) -> pd.DataFrame:
    """Load trace_power_rails.csv (raw counter data).

    `value` is a cumulative energy counter in microjoules (uJ).
    Energy per rail = (last_value - first_value) uJ / 1e6 -> J.
    """
    df = pd.read_csv(csv_path)

    required = {"ts", "rail", "value"}
    if not required.issubset(df.columns):
        raise ValueError(f"Missing columns: {required}")

    df["ts"] = pd.to_numeric(df["ts"])
    df["value"] = pd.to_numeric(df["value"])
    df = df.drop_duplicates(subset=["rail", "ts"], keep="first")
    df = df.sort_values("ts")

    t0 = df["ts"].iloc[0]
    df["t_sec"] = (df["ts"] - t0) / 1e9

    return df


def compute_perfetto_energy(df: pd.DataFrame) -> float:
    """Compute total energy from cumulative counter deltas (uJ -> J).

    Matches extractData.py:compute_energy().
    """
    df = df.sort_values(["rail", "ts"])
    df["next_value"] = df.groupby("rail")["value"].shift(-1)
    energy_uj = (df["next_value"] - df["value"]).sum()
    return energy_uj / 1e6  # uJ -> J


def compute_rail_group_energy(df: pd.DataFrame) -> dict:
    """Compute energy per rail group from cumulative counter deltas (uJ -> J).

    Groups rails into logical categories:
      cpu: cpu.big, cpu.little, cpu.mid
      wifi_bt: wifi.bt
      gpu: gpu
      memory: ddr.a, ddr.b, ddr.c, memory.interface
      display: display
      other: everything else (modem, radio, aoc, system.fabric, tpu)
    """
    df = df.sort_values(["rail", "ts"])
    df["next_value"] = df.groupby("rail")["value"].shift(-1)
    df["delta_uj"] = df["next_value"] - df["value"]
    df = df.dropna(subset=["delta_uj"])

    cpu_rails = {"power.rails.cpu.big", "power.rails.cpu.little", "power.rails.cpu.mid"}
    wifi_bt_rails = {"power.rails.wifi.bt"}
    gpu_rails = {"power.rails.gpu"}
    memory_rails = {
        "power.rails.ddr.a",
        "power.rails.ddr.b",
        "power.rails.ddr.c",
        "power.rails.memory.interface",
    }
    display_rails = {"power.rails.display"}

    groups = {}
    for _, row in df.iterrows():
        rail = row["rail"]
        delta = row["delta_uj"]
        if rail in cpu_rails:
            groups.setdefault("cpu", 0.0)
            groups["cpu"] += delta
        elif rail in wifi_bt_rails:
            groups.setdefault("wifi_bt", 0.0)
            groups["wifi_bt"] += delta
        elif rail in gpu_rails:
            groups.setdefault("gpu", 0.0)
            groups["gpu"] += delta
        elif rail in memory_rails:
            groups.setdefault("memory", 0.0)
            groups["memory"] += delta
        elif rail in display_rails:
            groups.setdefault("display", 0.0)
            groups["display"] += delta
        else:
            groups.setdefault("other", 0.0)
            groups["other"] += delta

    return {k: v / 1e6 for k, v in groups.items()}  # uJ -> J


def compute_per_timestamp_watts(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-timestamp total watts from raw counter data for plotting.

    For each rail, compute power segments (watts = dE/dt), then collapse
    by timestamp (sum watts across rails at each ts).
    This is for the power-vs-time plot only; energy is computed via
    counter-delta (compute_perfetto_energy).
    """
    df = df.sort_values(["rail", "ts"])
    df["next_value"] = df.groupby("rail")["value"].shift(-1)
    df["next_ts"] = df.groupby("rail")["ts"].shift(-1)

    df = df.dropna(subset=["next_value", "next_ts"])
    dt = df["next_ts"] - df["ts"]
    dE = df["next_value"] - df["value"]  # uJ
    df["watts"] = (dE * 1000.0) / dt  # (µJ × 1000) / ns = nJ/ns = W

    collapsed = df.groupby("ts", as_index=False)["watts"].sum()
    collapsed["t_sec"] = (collapsed["ts"] - collapsed["ts"].iloc[0]) / 1e9

    return collapsed


def load_sync_timeline(
    csv_path: Path,
    time_offset_sec: float = 0.0,
) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    if "host_ns" not in df.columns:
        raise ValueError("sync_timeline.csv must contain a 'host_ns' column")

    df = df.sort_values("host_ns")

    sync_t0 = df["host_ns"].iloc[0]

    df["t_sec"] = (df["host_ns"] - sync_t0) / 1e9
    df["t_sec"] += time_offset_sec

    return df


# ------------------------------------------------------------
# Energy computation
# ------------------------------------------------------------


def integrate_energy(df: pd.DataFrame, t_col: str, p_col: str) -> float:
    df = df.sort_values(t_col).dropna()

    if len(df) < 2:
        return 0.0

    t = df[t_col].to_numpy()
    p = df[p_col].to_numpy()

    energy_j = ((p[:-1] + p[1:]) / 2.0) * (t[1:] - t[:-1])

    return float(energy_j.sum())


def compute_per_page_energy_stdev(
    df_p: pd.DataFrame,
    df_e: pd.DataFrame,
    syncs: pd.DataFrame,
) -> tuple:
    """Compute within-run stdev of per-page energy.

    Integrates power between consecutive sync events to get per-page energy,
    then returns stdev of those per-page values for both Perfetto and External.
    Both DataFrames must already be clipped to the overlap window.
    """
    if syncs is None or len(syncs) < 3:
        return None, None

    sync_times = syncs["t_sec"].values

    # --- Perfetto per-page energy ---
    df = df_p.sort_values(["rail", "ts"]).copy()
    df["next_value"] = df.groupby("rail")["value"].shift(-1)
    df["next_ts"] = df.groupby("rail")["ts"].shift(-1)
    df = df.dropna(subset=["next_value", "next_ts"])

    dt = df["next_ts"] - df["ts"]
    dE = df["next_value"] - df["value"]
    df["watts"] = (dE * 1000.0) / dt

    df_w = df.groupby("ts", as_index=False)["watts"].sum()
    df_w["t_sec"] = (df_w["ts"] - df_w["ts"].iloc[0]) / 1e9

    perfetto_pages = []
    for i in range(len(sync_times) - 1):
        t0, t1 = sync_times[i], sync_times[i + 1]
        seg = df_w[(df_w["t_sec"] >= t0) & (df_w["t_sec"] < t1)].sort_values("t_sec")
        if len(seg) < 2:
            continue
        t = seg["t_sec"].values
        p = seg["watts"].values
        perfetto_pages.append(float(((p[:-1] + p[1:]) / 2.0 * (t[1:] - t[:-1])).sum()))

    # --- External per-page energy ---
    ext_pages = []
    e_col = "measurment_value" if "measurment_value" in df_e.columns else "measurement_value"
    for i in range(len(sync_times) - 1):
        t0, t1 = sync_times[i], sync_times[i + 1]
        seg = df_e[(df_e["t_sec"] >= t0) & (df_e["t_sec"] < t1)].sort_values("t_sec")
        if len(seg) < 2:
            continue
        t = seg["t_sec"].values
        p = seg[e_col].values
        ext_pages.append(float(((p[:-1] + p[1:]) / 2.0 * (t[1:] - t[:-1])).sum()))

    pf_stdev = stdev(perfetto_pages) if len(perfetto_pages) > 1 else None
    ex_stdev = stdev(ext_pages) if len(ext_pages) > 1 else None
    return pf_stdev, ex_stdev


def clip_to_window(
    df: pd.DataFrame, t_col: str, start: float, end: float
) -> pd.DataFrame:
    return df[(df[t_col] >= start) & (df[t_col] <= end)].copy()


def compute_offset_crosscorrelation(
    df_p_watts: pd.DataFrame,
    df_e: pd.DataFrame,
    max_lag_sec: float = 60.0,
) -> tuple[float, float]:
    """Compute optimal time offset by cross-correlating power traces.

    Resamples both traces to 1 Hz, normalizes, then cross-correlates
    to find the lag that maximizes correlation.  Returns (offset_sec, peak_r).
    """
    import numpy as np
    from scipy.signal import correlate as sig_correlate

    p_col = "watts"
    e_col = (
        "measurment_value"
        if "measurment_value" in df_e.columns
        else "measurement_value"
    )

    p_start, p_end = df_p_watts["t_sec"].min(), df_p_watts["t_sec"].max()
    e_start, e_end = df_e["t_sec"].min(), df_e["t_sec"].max()

    t_start = max(p_start, e_start)
    t_end = min(p_end, e_end)

    if t_end - t_start < 10:
        return 0.0, 0.0

    dt = 1.0
    t_grid = np.arange(t_start, t_end, dt)

    if len(t_grid) < 10:
        return 0.0, 0.0

    p_watts = np.interp(t_grid, df_p_watts["t_sec"], df_p_watts[p_col])
    e_watts = np.interp(t_grid, df_e["t_sec"], df_e[e_col])

    p_std = np.std(p_watts)
    e_std = np.std(e_watts)

    if p_std < 1e-10 or e_std < 1e-10:
        return 0.0, 0.0

    p_norm = (p_watts - np.mean(p_watts)) / p_std
    e_norm = (e_watts - np.mean(e_watts)) / e_std

    max_lag_samples = int(max_lag_sec / dt)
    correlation = sig_correlate(e_norm, p_norm, mode="full")
    lags = np.arange(-len(p_norm) + 1, len(p_norm))

    mask = np.abs(lags) <= max_lag_samples
    if not np.any(mask):
        return 0.0, 0.0

    best_lag = lags[mask][np.argmax(correlation[mask])]
    peak_corr = correlation[mask][np.argmax(correlation[mask])] / len(p_norm)

    print(f"Cross-correlation: offset={best_lag * dt:.3f}s, peak_r={peak_corr:.3f}")

    if peak_corr < 0.1:
        print("[WARN] Low correlation; cross-correlation offset may be unreliable")
        return 0.0, 0.0

    return float(best_lag * dt), float(peak_corr)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--sync-timeline")
    parser.add_argument("--folder")

    parser.add_argument("--external-offset", type=float, default=0.0)
    parser.add_argument("--sync-offset", type=float, default=0.0)

    parser.add_argument("perfetto_csv", nargs="?", default=None)
    parser.add_argument("external_csv", nargs="?", default=None)

    args = parser.parse_args()

    # --------------------------------------------------------
    # Load inputs
    # --------------------------------------------------------

    if args.folder:
        run = Path(args.folder)
        perfetto_csv = run / "trace_power_rails.csv"
        external_csv = run / "autopower_trace.csv"
        sync_csv = run / "sync_timeline.csv"

    else:
        if not args.perfetto_csv or not args.external_csv:
            raise ValueError("Either --folder or raw CSV args required")

        perfetto_csv = Path(args.perfetto_csv)
        external_csv = Path(args.external_csv)
        sync_csv = None

    df_p = load_perfetto(perfetto_csv)

    # --------------------------------------------------------
    # Compute alignment offset (primary: cross-correlation on peaks)
    # --------------------------------------------------------

    external_offset = args.external_offset

    if args.folder and external_offset == 0.0:
        df_e_raw = load_external(external_csv, 0.0)
        df_e_raw["measurment_value"] = df_e_raw["measurment_value"] / 1000.0
        df_p_watts = compute_per_timestamp_watts(df_p)

        xcorr_offset, peak_corr = compute_offset_crosscorrelation(df_p_watts, df_e_raw)

        sync_offset = 0.0
        if sync_csv.exists():
            try:
                sync_offset = compute_external_offset(sync_csv, external_csv)
                print(f"Sync-based offset: {sync_offset:.3f}s")
            except Exception:
                pass

        sync_is_valid = abs(sync_offset) > 0.1 and abs(sync_offset) < 10.0
        xcorr_is_valid = abs(xcorr_offset) > 0.1 and peak_corr >= 0.3

        if sync_is_valid:
            external_offset = sync_offset
            print(f"Using sync-based offset: {external_offset:.3f}s")
        elif xcorr_is_valid:
            external_offset = xcorr_offset
            print(f"Using cross-correlation offset: {external_offset:.3f}s")
        else:
            external_offset = 0.0
            print("Using offset: 0.0s")

    df_e = load_external(external_csv, external_offset)
    # convert dfe (autopower) to watts
    df_e["measurment_value"] = df_e["measurment_value"] / 1000.0
    df_sync = None

    if args.folder:
        if sync_csv.exists():
            df_sync = load_sync_timeline(sync_csv, args.sync_offset)
    else:
        if args.sync_timeline:
            df_sync = load_sync_timeline(Path(args.sync_timeline), args.sync_offset)

    # --------------------------------------------------------
    # Find overlap window
    # --------------------------------------------------------

    p_start, p_end = df_p["t_sec"].min(), df_p["t_sec"].max()
    e_start, e_end = df_e["t_sec"].min(), df_e["t_sec"].max()

    start = max(p_start, e_start)
    end = min(p_end, e_end)

    if start >= end and external_offset != 0.0:
        print(
            f"[WARN] No overlap with computed offset ({external_offset:.1f}s), "
            f"retrying with offset=0"
        )
        external_offset = 0.0
        df_e = load_external(external_csv, external_offset)
        df_e["measurment_value"] = df_e["measurment_value"] / 1000.0
        p_start, p_end = df_p["t_sec"].min(), df_p["t_sec"].max()
        e_start, e_end = df_e["t_sec"].min(), df_e["t_sec"].max()
        start = max(p_start, e_start)
        end = min(p_end, e_end)

    if start >= end:
        raise ValueError("No overlap between datasets after alignment")

    df_p_clip = clip_to_window(df_p, "t_sec", start, end)
    df_e_clip = clip_to_window(df_e, "t_sec", start, end)

    # --------------------------------------------------------
    # Energy
    # --------------------------------------------------------

    energy_perfetto_j = compute_perfetto_energy(df_p_clip)

    energy_external_j = (
        integrate_energy(df_e_clip, "t_sec", "measurment_value")  # / 4.0
    )

    print("\n==============================")
    print("ENERGY (OVERLAP WINDOW)")
    print("==============================")
    print(f"Window: {start:.2f}s → {end:.2f}s")
    print(f"Perfetto energy : {energy_perfetto_j:.6f} J")
    print(f"External energy : {energy_external_j:.6f} J")

    # --------------------------------------------------------
    # Sync
    # --------------------------------------------------------

    syncs_in_window = None
    avg_perfetto = None
    avg_external = None

    if df_sync is not None:
        syncs_in_window = df_sync[
            (df_sync["t_sec"] >= start) & (df_sync["t_sec"] <= end)
        ]

        print(f"Sync events in overlap: {len(syncs_in_window)}")

        if len(syncs_in_window) > 0:
            avg_perfetto = energy_perfetto_j / len(syncs_in_window)
            avg_external = energy_external_j / len(syncs_in_window)

            print(f"Perfetto avg/microexperiment: {avg_perfetto:.6f} J")
            print(f"External avg/microexperiment: {avg_external:.6f} J")

    print("==============================\n")
    # --------------------------------------------------------
    # Spearman correlation (structure similarity check)
    # --------------------------------------------------------

    # align per-run scalar comparison context (this run only → trivial case not useful)
    # so we compute over sync windows if available, otherwise skip safely

    spearman_corr = None

    if df_sync is not None and len(syncs_in_window) > 1:
        # build per-window energy samples (coarse proxy)
        # use cumulative energy over sync segments

        perfetto_samples = []
        external_samples = []

        for i in range(len(syncs_in_window) - 1):
            t0 = syncs_in_window.iloc[i]["t_sec"]
            t1 = syncs_in_window.iloc[i + 1]["t_sec"]

            p_seg = clip_to_window(df_p, "t_sec", t0, t1)
            e_seg = clip_to_window(df_e, "t_sec", t0, t1)

            if len(p_seg) < 2 or len(e_seg) < 2:
                continue

            perfetto_samples.append(compute_perfetto_energy(p_seg))
            external_samples.append(
                integrate_energy(e_seg, "t_sec", "measurment_value")
            )

        if len(perfetto_samples) > 2:
            spearman_corr, _ = spearmanr(perfetto_samples, external_samples)

            print(f"Spearman correlation (segment energy): {spearman_corr:.4f}")

    # --------------------------------------------------------
    # Linear calibration (Perfetto vs Autopower)
    # --------------------------------------------------------

    calibration_slope = None
    calibration_intercept = None
    r_value = None

    if df_sync is not None and len(syncs_in_window) > 1:
        perfetto_samples = []
        external_samples = []

        for i in range(len(syncs_in_window) - 1):
            t0 = syncs_in_window.iloc[i]["t_sec"]
            t1 = syncs_in_window.iloc[i + 1]["t_sec"]

            p_seg = clip_to_window(df_p, "t_sec", t0, t1)
            e_seg = clip_to_window(df_e, "t_sec", t0, t1)

            if len(p_seg) < 2 or len(e_seg) < 2:
                continue

            perfetto_samples.append(compute_perfetto_energy(p_seg))
            external_samples.append(
                integrate_energy(e_seg, "t_sec", "measurment_value")
            )

        if len(perfetto_samples) > 2:
            res = linregress(perfetto_samples, external_samples)

            calibration_slope = res.slope
            calibration_intercept = res.intercept
            r_value = res.rvalue

            print("\nCALIBRATION (Perfetto → Autopower)")
            print("-----------------------------------")
            print(f"slope      : {calibration_slope:.4f}")
            print(f"intercept  : {calibration_intercept:.4f}")
            print(f"R²         : {r_value**2:.4f}")
    # --------------------------------------------------------
    # Plot
    # --------------------------------------------------------

    fig = go.Figure()

    # Compute per-timestamp watts from counter deltas for the plot
    df_p_watts = compute_per_timestamp_watts(df_p)
    fig.add_trace(
        go.Scatter(x=df_p_watts["t_sec"], y=df_p_watts["watts"], mode="lines", name="Perfetto (W)")
    )
    fig.add_trace(
        go.Scatter(
            x=df_e["t_sec"],
            y=df_e["measurment_value"],
            mode="lines+markers",
            name="Autopower (W)",
        )
    )

    if df_sync is not None:
        for t in df_sync["t_sec"]:
            fig.add_vline(
                x=t,
                line_width=0.75,
                line_dash="dot",
                line_color="rgba(0,0,0,0.08)",
                layer="below",
            )

    fig.add_vrect(
        x0=start, x1=end, fillcolor="green", opacity=0.03, layer="below", line_width=0
    )

    fig.update_layout(
        xaxis_title="Time (s)",
        yaxis_title="Power (W)",
        template="plotly_white",
        hovermode="x unified",
    )

    # --------------------------------------------------------
    # EXPORT (folder mode only)
    # --------------------------------------------------------

    if args.folder:
        out_dir = Path(args.folder)

        variant_name = out_dir.name
        variant_dir = Path(__file__).resolve().parent / "plots" / "compareAutopowerPerfetto" / variant_name
        variant_dir.mkdir(parents=True, exist_ok=True)

        jpg_path = variant_dir / "power_comparison.jpg"
        fig.write_image(str(jpg_path), scale=2)
        print(f"Saved JPG: {jpg_path}")

        html_path = variant_dir / "power_comparison.html"
        fig.write_html(str(html_path))
        print(f"Saved HTML: {html_path}")

        sync_count = len(syncs_in_window) if df_sync is not None else 0

        if df_sync is not None and sync_count > 1:
            intervals_s = syncs_in_window["t_sec"].diff().dropna()
            median_interval_s = float(intervals_s.median())
        else:
            median_interval_s = None

        existing = {}
        existing_path = out_dir / "result.json"
        if existing_path.exists():
            with open(existing_path) as ef:
                existing = json.load(ef)

        result = {
            "window": {"start_s": start, "end_s": end},
            "energy": {
                "perfetto_j": energy_perfetto_j,
                "external_j": energy_external_j,
            },
            "correlation": {"spearman": spearman_corr},
            "calibration": {
                "slope": calibration_slope,
                "intercept": calibration_intercept,
                "r2": (r_value**2) if r_value is not None else None,
            },
            "sync": {"events": sync_count, "median_interval_s": median_interval_s},
        }

        if "website_carbon" in existing:
            result["website_carbon"] = existing["website_carbon"]

        # Rail group energy breakdown
        rail_groups = compute_rail_group_energy(df_p_clip)
        result["energy"]["rail_groups"] = rail_groups

        # Network metrics from network_bytes.json
        net_file = out_dir / "network_bytes.json"
        valid_values, _ = load_network_bytes(net_file)
        net = estimate_network_metrics(valid_values, sync_count)
        result["network"] = net

        if df_sync is not None and sync_count > 0:
            result["energy"]["perfetto_avg_j"] = avg_perfetto
            result["energy"]["external_avg_j"] = avg_external

        # Per-page energy stdev (within-run variability)
        if df_sync is not None and sync_count >= 3:
            pf_sd, ex_sd = compute_per_page_energy_stdev(
                df_p_clip, df_e_clip, syncs_in_window
            )
            result["energy"]["perfetto_stdev_j"] = pf_sd
            result["energy"]["external_stdev_j"] = ex_sd

        with open(out_dir / "result.json", "w") as f:
            json.dump(result, f, indent=2)

        md = f"""# Energy Comparison

Window: {start:.2f}s → {end:.2f}s

Perfetto energy: {energy_perfetto_j:.6f} J
External energy: {energy_external_j:.6f} J

Sync events: {sync_count}
"""

        if df_sync is not None and sync_count > 0:
            md += f"""
Perfetto avg/microexperiment: {avg_perfetto:.6f} J
External avg/microexperiment: {avg_external:.6f} J
"""

        with open(out_dir / "result.md", "w") as f:
            f.write(md)

    # Always display the figure (raw-CSV mode has no file export)
    try:
        fig.show()
    except Exception:
        pass


if __name__ == "__main__":
    main()
