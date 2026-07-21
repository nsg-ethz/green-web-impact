from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# =========================================================
# LOAD DATA
# =========================================================

df = pd.read_csv("dataExtracted.csv")

cols = [
    "eco_render_score",
    "eco_interaction_score",
    "wc_page_g",
    "gm_cpu_energy_kwh",
    "gm_page_weight_bytes",
    "eco_page_weight_bytes",
    "eco_emissions_score",
    "eco_web_requests",
]

for c in cols:
    df[c] = pd.to_numeric(df[c], errors="coerce")

df = df.dropna(subset=cols).copy()

# create output folder
plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)


def savefig(name):
    fig.write_html(str(plots_dir / name), include_plotlyjs="cdn")
    jpg_name = name.replace(".html", ".jpg")
    fig.write_image(str(plots_dir / jpg_name), scale=2)


# =========================================================
# LABELS
# =========================================================

LABELS = {
    "eco_render_score": "EG: Render score",
    "eco_interaction_score": "EG: Interaction score",
    "wc_page_g": "WC CO2E (g)",
    "gm_cpu_energy_kwh": "GM Measured rendering energy (kWh)",
    "gm_page_weight_bytes": "GM page weight (bytes)",
    "eco_page_weight_bytes": "EG page weight (bytes)",
    "eco_emissions_score": "EG: Emissions score",
    "eco_web_requests": "EG: Web requests",
}

# =========================================================
# 1. CORRELATION MATRIX (LABELED)
# =========================================================

corr_cols = list(LABELS.keys())

corr = df[corr_cols].corr()

corr.index = [LABELS[c] for c in corr.index]
corr.columns = [LABELS[c] for c in corr.columns]

fig = go.Figure(
    data=go.Heatmap(
        z=corr.values,
        x=corr.columns,
        y=corr.columns,
        colorscale="RdBu_r",
        zmin=-1,
        zmax=1,
        text=corr.round(2).values,
        texttemplate="%{text:.2f}",
        textfont={"size": 11},
        hoverongaps=False,
    )
)

fig.update_layout(
    xaxis_title="",
    yaxis_title="",
    yaxis_autorange="reversed",
    width=900,
    height=800,
)

savefig("01_correlation_matrix.html")


# =========================================================
# 2. INTERACTION SCORE vs ENERGY
# =========================================================

fig = px.scatter(
    df,
    x="eco_interaction_score",
    y="gm_cpu_energy_kwh",
    labels={
        "eco_interaction_score": LABELS["eco_interaction_score"],
        "gm_cpu_energy_kwh": LABELS["gm_cpu_energy_kwh"],
    },
)

fig.update_traces(marker=dict(size=6, opacity=0.7))
savefig("02_interaction_vs_energy.html")


# =========================================================
# 3. RENDER SCORE vs GM PAGE WEIGHT
# =========================================================

fig = px.scatter(
    df,
    x="eco_render_score",
    y="gm_page_weight_bytes",
    labels={
        "eco_render_score": LABELS["eco_render_score"],
        "gm_page_weight_bytes": LABELS["gm_page_weight_bytes"],
    },
)

fig.update_traces(marker=dict(size=6, opacity=0.7))
savefig("03_render_vs_gm_bytes.html")


# =========================================================
# 4. RENDER SCORE vs ECO PAGE WEIGHT
# =========================================================

fig = px.scatter(
    df,
    x="eco_render_score",
    y="eco_page_weight_bytes",
    labels={
        "eco_render_score": LABELS["eco_render_score"],
        "eco_page_weight_bytes": LABELS["eco_page_weight_bytes"],
    },
)

fig.update_traces(marker=dict(size=6, opacity=0.7))
savefig("04_render_vs_eco_bytes.html")


# =========================================================
# 5. UX RELATIONSHIP
# =========================================================

fig = px.scatter(
    df,
    x="eco_render_score",
    y="eco_interaction_score",
    labels={
        "eco_render_score": LABELS["eco_render_score"],
        "eco_interaction_score": LABELS["eco_interaction_score"],
    },
)

fig.update_traces(marker=dict(size=6, opacity=0.7))
savefig("05_ux_relationship.html")


# =========================================================
# 6. WC vs GM ENERGY PROXY
# =========================================================

fig = px.scatter(
    df,
    x="wc_page_g",
    y="gm_cpu_energy_kwh",
    labels={
        "wc_page_g": LABELS["wc_page_g"],
        "gm_cpu_energy_kwh": LABELS["gm_cpu_energy_kwh"],
    },
)

fig.update_traces(marker=dict(size=6, opacity=0.7))
savefig("06_wc_vs_gm_energy.html")


# =========================================================
# 7. EMISSIONS SCORE ANALYSIS
# =========================================================

fig = px.scatter(
    df,
    x="eco_emissions_score",
    y="gm_cpu_energy_kwh",
    labels={
        "eco_emissions_score": LABELS["eco_emissions_score"],
        "gm_cpu_energy_kwh": LABELS["gm_cpu_energy_kwh"],
    },
)

fig.update_traces(marker=dict(size=6, opacity=0.7))
savefig("07_emissions_vs_energy.html")


# =========================================================
# 8. LOG SCALE ENERGY VIEW
# =========================================================

df["log_energy"] = np.log1p(df["gm_cpu_energy_kwh"])
df["log_bytes"] = np.log1p(df["gm_page_weight_bytes"])
df["log_eco_bytes"] = np.log1p(df["eco_page_weight_bytes"])

fig = px.scatter(
    df,
    x="eco_interaction_score",
    y="log_energy",
    labels={
        "eco_interaction_score": LABELS["eco_interaction_score"],
        "log_energy": "log(GM Measured rendering energy + 1)",
    },
)

fig.update_traces(marker=dict(size=6, opacity=0.7))
savefig("08_interaction_vs_log_energy.html")


fig = px.scatter(
    df,
    x="eco_interaction_score",
    y="log_bytes",
    labels={
        "eco_interaction_score": LABELS["eco_interaction_score"],
        "log_bytes": "log(GM page weight + 1)",
    },
)

fig.update_traces(marker=dict(size=6, opacity=0.7))
savefig("09_interaction_vs_log_bytes.html")


fig = px.scatter(
    df,
    x="eco_interaction_score",
    y="log_eco_bytes",
    labels={
        "eco_interaction_score": LABELS["eco_interaction_score"],
        "log_eco_bytes": "log(EG page weight + 1)",
    },
)

fig.update_traces(marker=dict(size=6, opacity=0.7))
savefig("10_interaction_vs_log_eco_bytes.html")


# =========================================================
# 9. EFFICIENCY SCORE
# =========================================================

df["efficiency"] = df["eco_interaction_score"] / (df["log_energy"] + df["log_bytes"] + 1e-6)

fig = px.histogram(
    df,
    x="efficiency",
    nbins=20,
    labels={"efficiency": "Efficiency (EG Interaction score / resource cost)"},
)

fig.update_layout(bargap=0.05)
savefig("11_efficiency_distribution.html")


# =========================================================
# 10. TOP WEBSITES
# =========================================================

top = df.sort_values("efficiency", ascending=False).head(10)

print("\nTop 10 most efficient websites:\n")

print(
    top[
        [
            "url",
            "eco_interaction_score",
            "gm_cpu_energy_kwh",
            "gm_page_weight_bytes",
            "eco_page_weight_bytes",
            "eco_emissions_score",
            "efficiency",
        ]
    ]
)
