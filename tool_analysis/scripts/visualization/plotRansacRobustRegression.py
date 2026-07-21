#!/usr/bin/env python3

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sklearn.linear_model import RANSACRegressor

RESIDUAL_THRESHOLD = 0.0029

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)


def main():
    try:
        df = pd.read_csv("gc_extracted.csv")
    except FileNotFoundError:
        print("gc_extracted.csv not found")
        return

    plot_df = (
        df[["url", "page_weight_bytes", "cpu_energy_kwh"]]
        .dropna()
        .query("page_weight_bytes > 0 and cpu_energy_kwh > 0")
        .copy()
    )

    if len(plot_df) < 2:
        print("Not enough data points for regression")
        return

    X = plot_df["page_weight_bytes"].to_numpy().reshape(-1, 1)
    y = plot_df["cpu_energy_kwh"].to_numpy() + 0.04106063 * (X / 1024**3).flatten()
    plot_df["total_energy_kwh"] = y

    ransac = RANSACRegressor(
        residual_threshold=RESIDUAL_THRESHOLD,
        random_state=42,
    )
    ransac.fit(X, y)

    plot_df["predicted"] = ransac.predict(X)
    plot_df["residual"] = plot_df["total_energy_kwh"] - plot_df["predicted"]
    plot_df["is_outlier"] = ~ransac.inlier_mask_
    plot_df["status"] = plot_df["is_outlier"].map({True: "Outlier", False: "Inlier"})

    print("\nRANSAC Regression")
    print("-" * 40)
    print(f"Threshold : {RESIDUAL_THRESHOLD}")
    print(f"Slope     : {ransac.estimator_.coef_[0]:.2e}")
    print(f"Intercept : {ransac.estimator_.intercept_:.2e}")
    print(f"R²        : {ransac.score(X, y):.4f}")

    outliers = plot_df[plot_df["is_outlier"]]
    print(f"\nRows: {len(plot_df)}")
    print(f"Outliers: {len(outliers)}")

    if not outliers.empty:
        print("\nDetected outliers:")
        print(
            outliers[
                ["url", "page_weight_bytes", "cpu_energy_kwh", "residual"]
            ].to_string(index=False)
        )

    fig = px.scatter(
        plot_df,
        x="page_weight_bytes",
        y="total_energy_kwh",
        color="status",
        color_discrete_map={
            "Inlier": "blue",
            "Outlier": "red",
        },
        hover_data=["url", "residual"],
        opacity=0.7,
        labels={
            "page_weight_bytes": "Page Size (bytes)",
            "total_energy_kwh": "CPU + Network Energy (kWh)",
        },
    )

    x_range = np.linspace(X.min(), X.max(), 100).reshape(-1, 1)

    fig.add_trace(
        go.Scatter(
            x=x_range.flatten(),
            y=ransac.predict(x_range),
            mode="lines",
            line=dict(color="green", width=3),
            name="RANSAC",
        )
    )

    fig.update_layout(
        height=700,
        legend_title_text="Classification",
    )

    output_file = plots_dir / "gc_extracted_ransac_robust.html"
    fig.write_html(str(output_file), include_plotlyjs="cdn")
    jpg_file = plots_dir / "gc_extracted_ransac_robust.jpg"
    fig.write_image(str(jpg_file), scale=2)
    print(f"\nSaved {output_file}")
    print(f"Saved {jpg_file}")


if __name__ == "__main__":
    main()
