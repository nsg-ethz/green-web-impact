from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

df = pd.read_csv("dataExtracted.csv")

# --- CLEAN TYPES ---
df["gm_page_weight_bytes"] = pd.to_numeric(df["gm_page_weight_bytes"], errors="coerce")
df["eco_page_weight_bytes"] = pd.to_numeric(
    df["eco_page_weight_bytes"], errors="coerce"
)

df = df.dropna(subset=["gm_page_weight_bytes", "eco_page_weight_bytes"])

# --- CORE DELTAS ---
df["delta_bytes"] = df["gm_page_weight_bytes"] - df["eco_page_weight_bytes"]
df["abs_delta_bytes"] = df["delta_bytes"].abs()

# Percent difference (safe)
df["delta_pct"] = np.where(
    df["eco_page_weight_bytes"] != 0,
    df["delta_bytes"] / df["eco_page_weight_bytes"] * 100,
    np.nan,
)

# --- ROBUST OUTLIER SCORING (Z-score) ---
mean = df["abs_delta_bytes"].mean()
std = df["abs_delta_bytes"].std()

df["z_score"] = (df["abs_delta_bytes"] - mean) / std
df["is_outlier"] = df["z_score"].abs() > 2.5

# --- RANKING ---
df_ranked = df.sort_values("abs_delta_bytes", ascending=False)

# --- OUTPUT FORMAT ---
cols = [
    "url",
    "gm_page_weight_bytes",
    "eco_page_weight_bytes",
    "delta_bytes",
    "delta_pct",
    "z_score",
    "is_outlier",
]

print("\n=== TOP DISCREPANCIES (GM vs ECO, bytes) ===")
print(df_ranked[cols].head(20).to_string(index=False))

print("\n=== OUTLIERS ===")
print(df_ranked[df_ranked["is_outlier"]][cols].to_string(index=False))

# Optional: summary stats
print("\n=== SUMMARY ===")
print(df["abs_delta_bytes"].describe())

fig = px.scatter(
    df,
    x="gm_page_weight_bytes",
    y="eco_page_weight_bytes",
    color="abs_delta_bytes",
    hover_data=["url", "delta_pct", "z_score"],
    labels={
        "gm_page_weight_bytes": "GM Page Weight (bytes)",
        "eco_page_weight_bytes": "EcoGrader Page Weight (bytes)",
        "abs_delta_bytes": "Absolute Discrepancy (bytes)",
    },
)

fig.add_trace(
    go.Scatter(
        x=[df["gm_page_weight_bytes"].min(), df["gm_page_weight_bytes"].max()],
        y=[df["gm_page_weight_bytes"].min(), df["gm_page_weight_bytes"].max()],
        mode="lines",
        line=dict(color="red", dash="dash", width=2),
        name="1:1",
        hoverinfo="skip",
    )
)

fig.write_html(str(plots_dir / "gm_vs_eco_weight_discrepancy.html"), include_plotlyjs="cdn")
fig.write_image(str(plots_dir / "gm_vs_eco_weight_discrepancy.jpg"), scale=2)
