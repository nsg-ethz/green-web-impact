#!/usr/bin/env python3

import argparse
import subprocess
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd


def load_sync(trace_file: Path) -> pd.DataFrame:
    sync_file = trace_file.parent / "sync_timeline.csv"

    if not sync_file.exists():
        print("[WARN] sync_timeline.csv not found → skipping alignment")
        return None

    df = pd.read_csv(sync_file)
    df = df.sort_values("host_ns")

    return df


def attach_event_id(df: pd.DataFrame, sync_df: pd.DataFrame) -> pd.DataFrame:
    if sync_df is None:
        df["event_id"] = -1
        return df

    df = df.copy()

    df["event_id"] = np.interp(
        df["ts"],
        sync_df["host_ns"],
        sync_df["i"],
    ).astype(int)

    return df


# ---------------------------------------------------------------------
# PERFETTO POWER EXTRACTION
# ---------------------------------------------------------------------


def run_sql(trace_file: str) -> pd.DataFrame:
    query = """
    SELECT
      ts,
      counter_track.name AS rail,
      value
    FROM counter
    JOIN counter_track
      ON counter.track_id = counter_track.id
    WHERE counter_track.name LIKE 'power.rails.%'
    ORDER BY ts;
    """

    cmd = [
        "trace_processor_shell",
        trace_file,
        "--query-string",
        query,
    ]

    out = subprocess.check_output(cmd, text=True)

    df = pd.read_csv(StringIO(out))
    df = df.drop_duplicates(subset=["rail", "ts"], keep="first")
    return df


# ---------------------------------------------------------------------
# NETWORK EXTRACTION
# ---------------------------------------------------------------------


def run_network_json(json_file: Path) -> pd.DataFrame:
    import json

    with open(json_file, "r") as f:
        data = json.load(f)

    rows = []

    for entry in data:
        ts = entry.get("load_index", None)
        bytes_val = entry.get("total_bytes", None)

        if ts is None:
            continue

        try:
            bytes_val = float(bytes_val)
        except (TypeError, ValueError):
            continue

        # Skip obvious bad samples (0 or negative bytes)
        if bytes_val <= 0:
            continue

        rows.append({"ts": ts, "bytes": bytes_val})

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------
# ENERGY
# ---------------------------------------------------------------------


def compute_energy(df: pd.DataFrame) -> float:
    df = df.sort_values(["rail", "ts"])

    df["next_value"] = df.groupby("rail")["value"].shift(-1)

    energy_uj = (df["next_value"] - df["value"]).sum()

    return energy_uj


# ---------------------------------------------------------------------
# POWER
# ---------------------------------------------------------------------


def compute_power_segments(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["rail", "ts"])

    df["next_value"] = df.groupby("rail")["value"].shift(-1)
    df["next_ts"] = df.groupby("rail")["ts"].shift(-1)

    df = df.dropna(
        subset=[
            "next_value",
            "next_ts",
        ]
    )

    dt = df["next_ts"] - df["ts"]
    dE = df["next_value"] - df["value"]

    df["watts"] = (dE * 1000.0) / dt  # (µJ × 1000) / ns = nJ/ns = W

    return df


def collapse_power(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby("ts", as_index=False)["watts"].sum()


def compute_average_power(
    df: pd.DataFrame,
    energy_uj: float,
) -> float:

    dt_ns = df["ts"].max() - df["ts"].min()

    if dt_ns <= 0:
        raise ValueError("Invalid timestamps")

    return (energy_uj * 1000.0) / dt_ns


# ---------------------------------------------------------------------
# CHECK
# ---------------------------------------------------------------------


def check_physics(
    power_segments: pd.DataFrame,
    energy_uj: float,
):

    energy_j = energy_uj / 1e6
    dt_ns = power_segments["ts"].max() - power_segments["ts"].min()
    dt_s = dt_ns / 1e9
    avg_power_w = energy_j / dt_s if dt_s > 0 else 0.0

    negative_count = int((power_segments["watts"] < 0).sum())
    total_segments = len(power_segments)

    print("\n==============================")
    print("PHYSICS CHECK")
    print("==============================")
    print(f"Energy           : {energy_j:.4f} J ({energy_uj:.1f} µJ)")
    print(f"Window           : {dt_s:.2f} s")
    print(f"Avg power        : {avg_power_w:.4f} W")
    print(f"Negative segments: {negative_count}/{total_segments}")
    print("==============================\n")


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("trace_file")
    args = parser.parse_args()

    trace_file = Path(args.trace_file)

    if not trace_file.exists():
        raise FileNotFoundError(trace_file)

    energy_csv = trace_file.with_name("trace_power_rails.csv")

    power_csv = trace_file.with_name("trace_power_rails_watt.csv")

    network_csv = trace_file.with_name("trace_network.csv")

    print("[1/4] Extracting power rails...")

    df = run_sql(str(trace_file))

    df.to_csv(
        energy_csv,
        index=False,
    )

    energy_uj = compute_energy(df)

    print(f"Energy: {energy_uj / 1000:.6f} mJ")

    print("[2/4] Computing power...")

    sync_df = load_sync(trace_file)

    power_segments = compute_power_segments(df)

    power_segments = attach_event_id(
        power_segments,
        sync_df,
    )

    power_df = collapse_power(power_segments)

    power_df = attach_event_id(
        power_df,
        sync_df,
    )

    power_df.to_csv(
        power_csv,
        index=False,
    )

    print("[3/4] Loading network bytes per run...")

    json_file = trace_file.with_name("network_bytes.json")

    net = run_network_json(json_file)

    net["bytes"] = pd.to_numeric(net["bytes"], errors="coerce")
    net = net.dropna(subset=["bytes"])

    net = attach_event_id(net, sync_df)

    net.to_csv(network_csv, index=False)

    print(f"Mean network transfer: {net['bytes'].mean():.0f} bytes")

    print("[4/4] Stats...")

    avg = compute_average_power(
        df,
        energy_uj,
    )

    print(f"Average power: {avg:.6f} W")

    check_physics(
        power_segments,
        energy_uj,
    )


if __name__ == "__main__":
    main()
