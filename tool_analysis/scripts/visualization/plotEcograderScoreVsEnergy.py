from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

KWH_TO_J = 3_600_000

# Load data
data = pd.read_csv("dataExtracted.csv")

# Clean
data = data.dropna(
    subset=[
        "url",
        "eco_overall_score_no_greenhosting",
        "wc_energy_kwh",
        "gm_estimated_total_energy_kwh",
        "gm_cpu_energy_kwh",
    ]
)

data["wc_energy_j"] = data["wc_energy_kwh"] * KWH_TO_J
data["gm_total_energy_j"] = data["gm_estimated_total_energy_kwh"] * KWH_TO_J
data["gm_cpu_energy_j"] = data["gm_cpu_energy_kwh"] * KWH_TO_J
data["page_weight_mb"] = data["gm_page_weight_bytes"] / (1024 * 1024)
data["sqrt_page_weight_mb"] = np.sqrt(data["page_weight_mb"])

# =====================================================
# 1. Ecograder vs GM Energy
# =====================================================

corr_eco = data["eco_overall_score_no_greenhosting"].corr(
    data["gm_total_energy_j"]
)

fig1 = px.scatter(
    data,
    x="eco_overall_score_no_greenhosting",
    y="gm_total_energy_j",
    color="sqrt_page_weight_mb",
    hover_name="url",
    hover_data={
        "eco_overall_score_no_greenhosting": True,
        "gm_total_energy_j": True,
        "gm_page_weight_bytes": True,
        "url": True,
    },
    color_continuous_scale="Viridis",
)

fig1.update_traces(marker=dict(size=8, opacity=0.7))
fig1.update_layout(
    xaxis_title="Ecograder Score (no green hosting)",
    yaxis_title="GM Estimated Energy (J)",
    coloraxis_colorbar=dict(
        title="√Page Weight",
        tickformat=".1f",
    ),
    template="plotly_white",
)

fig1.write_html(str(plots_dir / "eco_vs_gm_energy.html"), include_plotlyjs="cdn")
fig1.write_image(str(plots_dir / "eco_vs_gm_energy.jpg"), scale=2)

print(f"[Eco vs GM] Pearson r = {corr_eco:.3f}")


# =====================================================
# 2. Ecograder Score vs GM CPU Energy
# =====================================================

corr_eco_cpu = data["eco_overall_score_no_greenhosting"].corr(
    data["gm_cpu_energy_j"]
)

fig2 = px.scatter(
    data,
    x="eco_overall_score_no_greenhosting",
    y="gm_cpu_energy_j",
    color="sqrt_page_weight_mb",
    hover_name="url",
    hover_data={
        "eco_overall_score_no_greenhosting": True,
        "gm_cpu_energy_j": True,
        "gm_page_weight_bytes": True,
        "url": True,
    },
    color_continuous_scale="Viridis",
)

fig2.update_traces(marker=dict(size=8, opacity=0.7))
fig2.update_layout(
    xaxis_title="Ecograder Score (no green hosting)",
    yaxis_title="Green Metrics CPU energy (J)",
    xaxis=dict(rangemode="tozero"),
    yaxis=dict(rangemode="tozero"),
    coloraxis_colorbar=dict(
        title="√Page Weight",
        tickformat=".1f",
    ),
    template="plotly_white",
    annotations=[
        dict(
            x=0.98, y=0.98,
            xref="paper", yref="paper",
            xanchor="right", yanchor="top",
            text=f"Pearson r = {corr_eco_cpu:.3f}",
            showarrow=False,
            font=dict(size=14, color="black"),
            bgcolor="white",
            bordercolor="gray",
            borderwidth=1,
            borderpad=4,
        )
    ],
)

fig2.write_html(str(plots_dir / "eco_vs_gm_cpu_energy.html"), include_plotlyjs="cdn")
fig2.write_image(str(plots_dir / "eco_vs_gm_cpu_energy.jpg"), scale=2)

print(f"[Eco vs GM CPU] Pearson r = {corr_eco_cpu:.3f}")


# =====================================================
# 3. WebsiteCarbon vs GM Energy
# =====================================================

corr_wc = data["wc_energy_j"].corr(data["gm_total_energy_j"])

fig3 = px.scatter(
    data,
    x="wc_energy_j",
    y="gm_total_energy_j",
    color="sqrt_page_weight_mb",
    hover_name="url",
    hover_data={
        "wc_energy_j": True,
        "gm_total_energy_j": True,
        "gm_page_weight_bytes": True,
        "url": True,
    },
    color_continuous_scale="Viridis",
)

fig3.update_traces(marker=dict(size=8, opacity=0.7))
fig3.update_layout(
    xaxis_title="Website Carbon Energy (J)",
    yaxis_title="GM Estimated Energy (J)",
    coloraxis_colorbar=dict(
        title="√Page Weight",
        tickformat=".1f",
    ),
    template="plotly_white",
)

fig3.write_html(str(plots_dir / "wc_vs_gm_energy.html"), include_plotlyjs="cdn")
fig3.write_image(str(plots_dir / "wc_vs_gm_energy.jpg"), scale=2)

print(f"[WC vs GM] Pearson r = {corr_wc:.3f}")
