from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy.stats import pearsonr

# =========================================================
# LOAD DATA
# =========================================================

web = pd.read_csv("webnrj.csv")
eco = pd.read_csv("ecograder.csv")
timing = pd.read_csv("webnrj_timing.csv")

# =========================================================
# NORMALIZE URLS
# =========================================================

web["URL"] = web["URL"].astype(str).str.strip().str.rstrip("/")
eco["url"] = eco["url"].astype(str).str.strip().str.rstrip("/")
timing["URL"] = timing["URL"].astype(str).str.strip().str.rstrip("/")

# =========================================================
# KEEP LATEST RECORDS
# =========================================================


def keep_latest(df, time_col, key_col):
    if time_col not in df.columns:
        return df
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
    df = df.dropna(subset=[time_col])
    return df.sort_values(time_col).drop_duplicates(key_col, keep="last")


web = keep_latest(web, "created_at", "URL")
eco = keep_latest(eco, "scrape_date", "url")
timing = keep_latest(timing, "created_at", "URL")

# =========================================================
# CLEAN WEBNRJ
# =========================================================

web = web[["URL", "Rendering Power [W]", "Network Transfer [MB]"]].copy()

web.rename(
    columns={
        "Rendering Power [W]": "rendering_power_w",
        "Network Transfer [MB]": "network_transfer_mb",
    },
    inplace=True,
)

web["rendering_power_w"] = pd.to_numeric(web["rendering_power_w"], errors="coerce")
web["network_transfer_mb"] = pd.to_numeric(web["network_transfer_mb"], errors="coerce")
web = web.dropna(subset=["rendering_power_w", "network_transfer_mb"])


timing = timing[["URL", "total_visit_ms"]].copy()
timing["total_visit_ms"] = pd.to_numeric(timing["total_visit_ms"], errors="coerce")
timing = timing.dropna(subset=["total_visit_ms"])

# convert ms → seconds
timing["visit_seconds"] = timing["total_visit_ms"] / 1000.0

# =========================================================
# MERGE WEB + TIMING
# =========================================================

web = web.merge(timing[["URL", "visit_seconds"]], on="URL", how="left")

# fallback (median is safer than fake constant)
web["visit_seconds"] = web["visit_seconds"].fillna(web["visit_seconds"].median())


# Wh = W × seconds / 3600
web["energy_wh"] = web["rendering_power_w"] * web["visit_seconds"] / 3600.0

# kWh
web["energy_kwh"] = web["energy_wh"] / 1000.0

# =========================================================
# CLEAN ECOGRADER
# =========================================================

eco = eco[eco["status"] == "success"].copy()
eco = eco[["url", "ecograder_score", "co2_emissions"]]

eco["ecograder_score"] = pd.to_numeric(eco["ecograder_score"], errors="coerce")
eco["co2_emissions"] = pd.to_numeric(eco["co2_emissions"], errors="coerce")
eco = eco.dropna(subset=["ecograder_score", "co2_emissions"])

eco["ecograder_score"] = eco["ecograder_score"].clip(lower=0)

# =========================================================
# MERGE FINAL
# =========================================================

df = web.merge(eco, left_on="URL", right_on="url", how="inner").dropna()

print(f"\nDataset size: {df.shape}\n")

# =========================================================
# PLOTTY PLOTS
# =========================================================

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)


def add_ols(fig, df, x, y):
    mask = df[[x, y]].notna().all(axis=1)
    xx, yy = df.loc[mask, x].to_numpy(), df.loc[mask, y].to_numpy()
    slope, intercept = np.polyfit(xx, yy, 1)
    r, _ = pearsonr(xx, yy)
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


def save_html(fig, filename):
    fig.write_html(str(plots_dir / filename), include_plotlyjs="cdn")
    jpg_name = filename.replace(".html", ".jpg")
    fig.write_image(str(plots_dir / jpg_name), scale=2)


# --- Plot 1: Energy vs EcoGrader Score ---

fig1 = px.scatter(
    df,
    x="energy_kwh",
    y="ecograder_score",
    labels={"energy_kwh": "Energy (kWh)", "ecograder_score": "EcoGrader Score (%)"},
)

add_ols(fig1, df, "energy_kwh", "ecograder_score")

save_html(fig1, "01_energy_vs_ecograder_score.html")

# --- Plot 2: Energy vs CO2 ---

fig2 = px.scatter(
    df,
    x="energy_kwh",
    y="co2_emissions",
    labels={"energy_kwh": "Energy (kWh)", "co2_emissions": "CO₂ Emissions (g CO₂e)"},
)

add_ols(fig2, df, "energy_kwh", "co2_emissions")

save_html(fig2, "02_energy_vs_co2.html")

# --- Plot 3: Log Energy vs CO2 ---

df["energy_log"] = np.log10(df["energy_kwh"] + 1e-12)

fig3 = px.scatter(
    df,
    x="energy_log",
    y="co2_emissions",
    labels={
        "energy_log": "log10(Energy kWh)",
        "co2_emissions": "CO₂ Emissions (g CO₂e)",
    },
)

add_ols(fig3, df, "energy_log", "co2_emissions")

save_html(fig3, "03_energy_log_vs_co2.html")

# --- Correlation Matrix ---

corr = df[["energy_kwh", "ecograder_score", "co2_emissions"]].corr()

fig4 = go.Figure(
    data=go.Heatmap(
        z=corr.values,
        x=corr.columns,
        y=corr.columns,
        colorscale="RdBu_r",
        zmin=-1,
        zmax=1,
        text=corr.round(2).values,
        texttemplate="%{text:.2f}",
        textfont={"size": 12},
        hoverongaps=False,
    )
)

fig4.update_layout(
    xaxis_title="",
    yaxis_title="",
    yaxis_autorange="reversed",
)

save_html(fig4, "04_correlation_matrix.html")

print("Saved 4 plots to plots/")
