"""
Stacked power-rail energy plot from Perfetto-extracted CSVs.

For each runs_* folder, produces two HTML files:
  1. rail_energy_stacked.html — stacked bar chart of 16 power rails
  2. energy_comparison.html — grouped bar chart (external total next to Perfetto total)

Energy method:
  - trace_power_rails.csv `value` is a cumulative energy counter in microjoules (uJ)
  - Energy over a window per rail = (last_value - first_value) uJ / 1e6 -> Joules
  - Both Perfetto and external traces are synchronized to absolute epoch time using
    sync_timeline.csv. The overlap window [max(starts), min(ends)] is the only
    interval that contributes to reported energy.
  - Sync events counted inside the window; avg = energy_J / n_sync.
"""

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def load_perfetto_rails(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["ts"] = pd.to_numeric(df["ts"])
    df["value"] = pd.to_numeric(df["value"])
    df["rail"] = df["rail"].str.replace("power.rails.", "", regex=False)
    df = df.sort_values("ts")
    df["t_sec"] = (df["ts"] - df["ts"].iloc[0]) / 1e9
    return df


def load_external_rel(csv_path: Path, time_offset_sec: float = 0.0) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["ts_dt"] = pd.to_datetime(df["measurement_timestamp"], format="ISO8601")
    df = df.sort_values("ts_dt")
    t0 = df["ts_dt"].iloc[0]
    df["t_sec"] = (df["ts_dt"] - t0).dt.total_seconds() + time_offset_sec
    return df


def load_sync_rel(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = df.sort_values("host_ns")
    df["t_sec"] = (df["host_ns"] - df["host_ns"].iloc[0]) / 1e9
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
    df_ext["ts_dt"] = pd.to_datetime(df_ext["measurement_timestamp"], format="ISO8601")
    ext_first_s = df_ext["ts_dt"].iloc[0].timestamp()

    return sync_first_s - ext_first_s


def pretty_rail(rail: str) -> str:
    return "screen" if rail == "display" else rail


def format_variant_label(name: str) -> str:
    """Turn a directory name like 'www.dropbox.com_baseline' into 'dropbox.com (baseline)'."""
    label = name.removesuffix(".html")
    label = label.removeprefix("www.")
    if "_" in label:
        domain, suffix = label.split("_", 1)
        return f"{domain} ({suffix})"
    return label


RAIL_GROUP_MAP = {
    "cpu.big": "cpu",
    "cpu.mid": "cpu",
    "cpu.little": "cpu",
    "wifi.bt": "wifi_bt",
    "ddr.a": "memory",
    "ddr.b": "memory",
    "ddr.c": "memory",
    "memory.interface": "memory",
    "display": "display",
}


def map_rail_to_group(rail: str) -> str:
    return RAIL_GROUP_MAP.get(rail, "other")


def integrate_external_energy(df: pd.DataFrame) -> float:
    """Trapezoidal integration of external power trace (mW -> W, time in s)."""
    if len(df) < 2:
        return 0.0
    t = df["t_sec"].to_numpy()
    p_col = (
        "measurment_value" if "measurment_value" in df.columns else "measurement_value"
    )
    p = df[p_col].to_numpy() / 1000.0
    dt = t[1:] - t[:-1]
    p_avg = (p[:-1] + p[1:]) / 2.0
    return float((p_avg * dt).sum())


def process_variant(variant_dir: Path) -> pd.DataFrame:
    """Return DataFrame with columns variant, rail, avg_energy_j for one variant.

    Also adds 'external_total_j' for the external/autopower total energy.

    Synchronization: Perfetto is the reference timeline (t=0 at first sample).
    The external trace is shifted by an offset computed from the first sync
    event, aligning both to the same physical time axis. The overlap window
    [max(starts), min(ends)] is the only interval that contributes to
    reported energy.
    """
    rails_csv = variant_dir / "trace_power_rails.csv"
    sync_csv = variant_dir / "sync_timeline.csv"
    ext_csv = variant_dir / "autopower_trace.csv"

    if not rails_csv.exists():
        return pd.DataFrame()

    df_p = load_perfetto_rails(rails_csv)
    if len(df_p) < 2:
        return pd.DataFrame()

    p_start, p_end = df_p["t_sec"].min(), df_p["t_sec"].max()

    # --- Compute external offset from sync events and load external trace ---
    start, end = p_start, p_end
    ext_total_j = 0.0
    if ext_csv.exists():
        ext_offset = 0.0
        if sync_csv.exists() and ext_csv.exists():
            ext_offset = compute_external_offset(sync_csv, ext_csv)
        df_e = load_external_rel(ext_csv, time_offset_sec=ext_offset)
        if len(df_e) >= 2:
            e_start, e_end = df_e["t_sec"].min(), df_e["t_sec"].max()
            start = max(p_start, e_start)
            end = min(p_end, e_end)
            df_e_win = df_e[(df_e["t_sec"] >= start) & (df_e["t_sec"] <= end)]
            ext_total_j = integrate_external_energy(df_e_win)

    if start >= end:
        print(f"    [WARN] No overlap window for {variant_dir.name}")
        return pd.DataFrame()

    # --- Sync events inside synchronized overlap ---
    n_sync = 1
    df_sync = None
    if sync_csv.exists():
        df_sync = load_sync_rel(sync_csv)
        in_win = df_sync[(df_sync["t_sec"] >= start) & (df_sync["t_sec"] <= end)]
        n_sync = max(len(in_win), 1)

    # --- Per-rail energy within synchronized window ---
    df_win = df_p[(df_p["t_sec"] >= start) & (df_p["t_sec"] <= end)]
    rows = []
    group_energy = {}
    for rail, group in df_win.groupby("rail"):
        if len(group) < 2:
            continue
        energy_j = (group["value"].iloc[-1] - group["value"].iloc[0]) / 1e6
        rail_name = rail.replace("power.rails.", "")
        group_name = map_rail_to_group(rail_name)
        group_energy[group_name] = group_energy.get(group_name, 0.0) + energy_j / n_sync

    for group_name, total_j in group_energy.items():
        rows.append(
            {
                "variant": format_variant_label(variant_dir.name),
                "rail": group_name,
                "avg_energy_j": total_j,
            }
        )

    # Add external total row
    if ext_total_j > 0:
        rows.append(
            {
                "variant": format_variant_label(variant_dir.name),
                "rail": "EXTERNAL",
                "external_total_j": ext_total_j / n_sync,
            }
        )

    return pd.DataFrame(rows)


RAIL_GROUP_COLORS = {
    "cpu": "#e74c3c",
    "display": "#3498db",
    "wifi_bt": "#2ecc71",
    "memory": "#f39c12",
    "other": "#95a5a6",
}

RAIL_GROUP_PRETTY = {
    "cpu": "CPU",
    "display": "Display",
    "wifi_bt": "WiFi/Bluetooth Chip",
    "memory": "Memory",
    "other": "Other",
}


def plot_stacked(df_plot: pd.DataFrame, runs_dir: Path):
    """Generate stacked bar chart of 6 rail groups."""
    df_perf = df_plot[df_plot["rail"] != "EXTERNAL"]
    if df_perf.empty:
        return

    group_order = ["cpu", "display", "wifi_bt", "memory", "other"]
    present = [g for g in group_order if g in df_perf["rail"].values]

    fig = go.Figure()
    for group in present:
        df_g = df_perf[df_perf["rail"] == group]
        vals = df_g["avg_energy_j"]
        fig.add_trace(go.Bar(
            x=df_g["variant"],
            y=vals,
            name=RAIL_GROUP_PRETTY.get(group, group),
            marker_color=RAIL_GROUP_COLORS.get(group, "#7f7f7f"),
            marker_pattern_shape="",
            text=[f"{v:.2f} J" if v >= 0.05 else "" for v in vals],
            textposition="inside",
            textfont=dict(size=13),
        ))

    fig.update_layout(
        barmode="stack",
        xaxis_title="Variant",
        yaxis_title="Avg energy per load (J)",
        xaxis_tickangle=-30,
        width=800,
        height=600,
    )

    out_html = runs_dir / "rail_energy_stacked.html"
    fig.write_html(str(out_html))

    out_jpg = runs_dir / "rail_energy_stacked.jpg"
    fig.write_image(str(out_jpg), scale=2)
    print(f"  Saved {out_html}")
    print(f"  Saved {out_jpg}")


def plot_comparison(df_plot: pd.DataFrame, runs_dir: Path):
    """Generate grouped bar chart: external total next to Perfetto total."""
    variants = sorted(df_plot["variant"].unique())

    # Compute total Perfetto energy per variant (sum of all rails except EXTERNAL)
    df_perf = df_plot[df_plot["rail"] != "EXTERNAL"]
    perf_totals = df_perf.groupby("variant")["avg_energy_j"].sum().reindex(variants)

    # Get external total per variant
    df_ext = df_plot[df_plot["rail"] == "EXTERNAL"]
    ext_totals = df_ext.set_index("variant")["external_total_j"].reindex(
        variants, fill_value=0
    )

    if ext_totals.sum() == 0:
        print(f"  [WARN] No external data for comparison in {runs_dir.name}")
        return

    # Create grouped bar chart
    fig = go.Figure()

    # External total (left bar, very light red)
    fig.add_trace(
        go.Bar(
            x=variants,
            y=ext_totals.values,
            name="External (Autopower)",
            marker_color="rgba(255, 180, 180, 0.6)",
            width=0.35,
        )
    )

    # Perfetto total (right bar)
    fig.add_trace(
        go.Bar(
            x=variants,
            y=perf_totals.values,
            name="Perfetto (Total)",
            marker_color="#3498db",
            width=0.35,
        )
    )

    fig.update_layout(
        barmode="group",
        xaxis_title="Variant",
        yaxis_title="Avg energy per load (J)",
        xaxis_tickangle=-30,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    # Add value labels on bars
    for i, v in enumerate(variants):
        e_val = ext_totals.iloc[i]
        p_val = perf_totals.iloc[i]
        if e_val > 0:
            fig.add_annotation(
                x=v,
                y=e_val,
                text=f"{e_val:.2f} J",
                showarrow=False,
                font=dict(size=9, color="#c0392b"),
                yanchor="bottom",
                yshift=4,
            )
        if p_val > 0:
            fig.add_annotation(
                x=v,
                y=p_val,
                text=f"{p_val:.2f} J",
                showarrow=False,
                font=dict(size=9, color="#2980b9"),
                yanchor="bottom",
                yshift=4,
            )

    out_html = runs_dir / "energy_comparison.html"
    fig.write_html(str(out_html))

    out_jpg = runs_dir / "energy_comparison.jpg"
    fig.write_image(str(out_jpg), scale=2)
    print(f"  Saved {out_html}")
    print(f"  Saved {out_jpg}")


def main():
    base_dir = Path(".")
    plots_base = Path(__file__).resolve().parent / "plots" / "aggregate_power_rails"
    plots_base.mkdir(parents=True, exist_ok=True)
    runs_dirs = sorted(d for d in base_dir.glob("runs_*") if d.is_dir())

    if not runs_dirs:
        print("No runs_* directories found.")
        return

    for runs_dir in runs_dirs:
        print(f"Processing {runs_dir.name}...")
        variant_dirs = sorted(
            (d for d in runs_dir.iterdir()
             if d.is_dir() and (d / "trace_power_rails.csv").exists()),
            key=lambda d: (0 if "baseline" in d.name.lower() else 1, d.name),
        )
        if not variant_dirs:
            print(f"  No variant subfolders with trace_power_rails.csv")
            continue

        frames = [process_variant(v) for v in variant_dirs]
        frames = [f for f in frames if not f.empty]
        if not frames:
            print(f"  No data for {runs_dir.name}")
            continue

        df_plot = pd.concat(frames, ignore_index=True)

        # Generate stacked plot (Perfetto rails only)
        out_dir = plots_base / runs_dir.name
        out_dir.mkdir(exist_ok=True)
        plot_stacked(df_plot, out_dir)

        # Generate comparison plot (external total next to Perfetto total)
        plot_comparison(df_plot, out_dir)


if __name__ == "__main__":
    main()
