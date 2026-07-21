from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import pearsonr

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

# ==========================
# Load data
# ==========================

df = pd.read_csv("dataExtracted.csv")


# Convert bytes -> MB for readability
df["images_mb"] = df["eco_images_bytesTotal"] / (1024 * 1024)
df["scripts_mb"] = df["eco_scripts_bytesTotal"] / (1024 * 1024)


# ==========================
# Figure layout
# ==========================

fig = make_subplots(
    rows=2,
    cols=2,
    subplot_titles=[
        "Energy vs Image Size",
        "Energy vs Script Size",
        "Eco Score vs Image Size",
        "Eco Score vs Script Size",
    ],
    horizontal_spacing=0.10,
    vertical_spacing=0.12,
)


plots = [
    ("images_mb", "Images"),
    ("scripts_mb", "Scripts"),
]


# ==========================
# Generate plots
# ==========================

for col, (xcol, label) in enumerate(plots, start=1):
    #
    # -----------------------
    # Row 1: Energy
    # -----------------------
    #

    data = df[
        [
            xcol,
            "gm_estimated_total_energy_kwh",
            "url",
        ]
    ].dropna()

    r, _ = pearsonr(
        data[xcol],
        data["gm_estimated_total_energy_kwh"],
    )

    fig.add_trace(
        go.Scatter(
            x=data[xcol],
            y=data["gm_estimated_total_energy_kwh"],
            mode="markers",
            marker=dict(
                size=6,
                opacity=0.35,
            ),
            text=data["url"],
            hovertemplate=(
                "<b>%{text}</b><br>"
                f"{label}: %{{x:.2f}} MB<br>"
                "Energy: %{y:.6f} kWh"
                "<extra></extra>"
            ),
            showlegend=False,
        ),
        row=1,
        col=col,
    )

    trend = px.scatter(
        data,
        x=xcol,
        y="gm_estimated_total_energy_kwh",
        trendline="ols",
    )

    fig.add_trace(
        trend.data[1],
        row=1,
        col=col,
    )

    fig.layout.annotations[
        col - 1
    ].text = f"{label} → Energy<br>r={r:.3f}, R²={r * r:.3f}"

    #
    # -----------------------
    # Row 2: Eco score
    # -----------------------
    #

    data = df[
        [
            xcol,
            "eco_overall_score_no_greenhosting",
            "url",
        ]
    ].dropna()

    r, _ = pearsonr(
        data[xcol],
        data["eco_overall_score_no_greenhosting"],
    )

    fig.add_trace(
        go.Scatter(
            x=data[xcol],
            y=data["eco_overall_score_no_greenhosting"],
            mode="markers",
            marker=dict(
                size=6,
                opacity=0.35,
            ),
            text=data["url"],
            hovertemplate=(
                "<b>%{text}</b><br>"
                f"{label}: %{{x:.2f}} MB<br>"
                "Eco score: %{y}<br>"
                "<extra></extra>"
            ),
            showlegend=False,
        ),
        row=2,
        col=col,
    )

    trend = px.scatter(
        data,
        x=xcol,
        y="eco_overall_score_no_greenhosting",
        trendline="ols",
    )

    fig.add_trace(
        trend.data[1],
        row=2,
        col=col,
    )

    fig.layout.annotations[
        col + 1
    ].text = f"{label} → Eco Score<br>r={r:.3f}, R²={r * r:.3f}"


# ==========================
# Axes
# ==========================

fig.update_yaxes(
    title="Estimated energy (kWh)",
    row=1,
    col=1,
)

fig.update_yaxes(
    title="Eco score (no green hosting)",
    row=2,
    col=1,
)


for row in [1, 2]:
    for col in [1, 2]:
        fig.update_xaxes(
            title="Size (MB)",
            row=row,
            col=col,
        )


# ==========================
# Layout
# ==========================

fig.update_layout(
    template="plotly_white",
    width=1200,
    height=1000,
)


fig.write_html(str(plots_dir / "energy_vs_asset_size.html"), include_plotlyjs="cdn")
fig.write_image(str(plots_dir / "energy_vs_asset_size.jpg"), scale=2)
