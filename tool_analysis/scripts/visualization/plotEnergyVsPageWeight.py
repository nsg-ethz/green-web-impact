from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy.stats import pearsonr

data = pd.read_csv("dataExtracted.csv")

num_cols = [
    "gm_cpu_energy_kwh",
    "gm_page_weight_bytes",
    "eco_page_weight_bytes",
]
for c in num_cols:
    data[c] = pd.to_numeric(data[c], errors="coerce")
data = data.dropna(subset=num_cols).copy()

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

KWH_TO_J = 3_600_000

LABELS = {
    "gm_cpu_energy_j": "Green Metrics CPU energy (J)",
    "gm_page_weight_mb": "GM page weight (MB)",
    "eco_page_weight_mb": "EcoGrader page weight (MB)",
}

data["gm_cpu_energy_j"] = data["gm_cpu_energy_kwh"] * KWH_TO_J
data["gm_page_weight_mb"] = data["gm_page_weight_bytes"] / (1024 * 1024)
data["eco_page_weight_mb"] = data["eco_page_weight_bytes"] / (1024 * 1024)


def savefig(fig, name):
    fig.write_html(str(plots_dir / name), include_plotlyjs="cdn")
    jpg_name = name.replace(".html", ".jpg")
    fig.write_image(str(plots_dir / jpg_name), scale=2)


def add_regline(fig, x, y):
    mask = pd.notna(x) & pd.notna(y)
    xx, yy = x[mask].to_numpy(), y[mask].to_numpy()
    r, _ = pearsonr(xx, yy)
    slope, intercept = np.polyfit(xx, yy, 1)
    x_range = np.linspace(xx.min(), xx.max(), 100)
    fig.add_trace(
        go.Scatter(
            x=x_range,
            y=slope * x_range + intercept,
            mode="lines",
            line=dict(color="red", dash="dash"),
            name=f"OLS (r={r:.3f})",
            hoverinfo="skip",
        )
    )
    return r


configs = [
    (
        "gm_cpu_energy_j",
        "gm_page_weight_mb",
        "gm_energy_vs_gm_weight",
    ),
    (
        "gm_cpu_energy_j",
        "eco_page_weight_mb",
        "gm_energy_vs_eco_weight",
    ),
]

for xcol, ycol, name in configs:
    fig = px.scatter(
        data,
        x=xcol,
        y=ycol,
        labels={xcol: LABELS.get(xcol, xcol), ycol: LABELS.get(ycol, ycol)},
        hover_data={"url": True},
    )
    fig.update_traces(marker=dict(size=6, opacity=0.6))
    r = add_regline(fig, data[xcol], data[ycol])
    fname = name + ".html"
    savefig(fig, fname)
    print(f"Saved {fname}  (r = {r:.3f})")

print("\nDone — 2 plots saved to plots/")
