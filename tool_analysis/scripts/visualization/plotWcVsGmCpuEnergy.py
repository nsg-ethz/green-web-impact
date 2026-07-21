from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy import stats

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

KWH_TO_J = 3_600_000

# --- 1. Load Data (raw sources, not dataExtracted.csv) ---
wc = pd.read_csv("websitecarbon.csv")
gc = pd.read_csv("gc_extracted.csv")

wc = wc[wc["status"] == "success"][["url", "energy_kwh"]].rename(columns={"energy_kwh": "wc_energy_kwh"})
gc = gc[gc["status"] == "success"][["url", "cpu_energy_kwh"]].rename(columns={"cpu_energy_kwh": "gm_cpu_energy_kwh"})

data = pd.merge(wc, gc, on="url", how="inner")
data = data.dropna(subset=["wc_energy_kwh", "gm_cpu_energy_kwh"])
print(f"Valid records (WC ∩ GM): {len(data)}")

# Convert to Joules
data["wc_energy_j"] = data["wc_energy_kwh"] * KWH_TO_J
data["gm_cpu_energy_j"] = data["gm_cpu_energy_kwh"] * KWH_TO_J

# --- 2. Regression ---
slope, intercept, r, p, se = stats.linregress(data["wc_energy_j"], data["gm_cpu_energy_j"])
print(f"Linear fit:  slope={slope:.4f}  intercept={intercept:.1f} J  R={r:.3f}  p={p:.2e}")

x_line = np.linspace(0, data["wc_energy_j"].max(), 100)
y_line = slope * x_line + intercept

# --- 3. Plot ---
SELECTED = [
    "https://creativecommons.org",
    "https://dropbox.com",
    "https://nsg.ee.ethz.ch",
    "https://slack.com",
    "https://tradingview.com",
    "https://un.org",
]

data["selected"] = data["url"].isin(SELECTED)
rest = data[~data["selected"]]
sel = data[data["selected"]]

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=rest["wc_energy_j"],
    y=rest["gm_cpu_energy_j"],
    mode="markers",
    name="All pages",
    text=rest["url"].str.replace("https://", "", regex=False),
    marker=dict(color="#1f77b4", size=8, opacity=0.5),
    hovertemplate="<b>%{text}</b><br>WC: %{x:.1f} J<br>GM CPU: %{y:.1f} J<extra></extra>",
))

fig.add_trace(go.Scatter(
    x=sel["wc_energy_j"],
    y=sel["gm_cpu_energy_j"],
    mode="markers+text",
    name="Selected pages",
    text=sel["url"].str.replace("https://", "", regex=False),
    textposition="top center",
    textfont=dict(size=11, color="#c0392b"),
    marker=dict(color="#c0392b", size=12, opacity=0.9, line=dict(width=1, color="white")),
    hovertemplate="<b>%{text}</b><br>WC: %{x:.1f} J<br>GM CPU: %{y:.1f} J<extra></extra>",
))

fig.add_trace(go.Scatter(
    x=x_line,
    y=y_line,
    mode="lines",
    name=f"Linear regression fit (R={r:.3f})",
    line=dict(color="red", dash="dash", width=2),
    hoverinfo="skip",
))

fig.update_layout(
    xaxis_title="Website Carbon Total Energy (J)",
    yaxis_title="Green Metrics CPU Energy (J)",
    template="plotly_white",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="closest",
    xaxis=dict(rangemode="tozero"),
    yaxis=dict(rangemode="tozero"),
)

out = plots_dir / "wc_vs_gm_cpu_energy_joules.html"
fig.write_html(str(out), include_plotlyjs="cdn")
fig.write_image(str(plots_dir / "wc_vs_gm_cpu_energy_joules.jpg"), scale=2)
print(f"Saved to {out}")
