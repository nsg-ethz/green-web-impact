import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy.stats import pearsonr

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

# =========================================================
# 1. ECOGRADER CSV
# =========================================================

eco = pd.read_csv("ecograder.csv")

eco["url"] = eco["url"].astype(str).str.strip().str.lower()
eco["report_id"] = eco["report_id"].astype(str)

eco["co2_eco"] = pd.to_numeric(eco["co2_emissions"], errors="coerce")
eco["scrape_date"] = pd.to_datetime(eco["scrape_date"], errors="coerce", utc=True)

eco = (
    eco[eco["status"] == "success"]
    .sort_values("scrape_date")
    .groupby("url", as_index=False)
    .tail(1)
)

eco = eco.dropna(subset=["co2_eco"])

eco_report_ids = eco["report_id"].unique()

# =========================================================
# 2. ECOGRADER PAGE SIZE (JSON via report_id)
# =========================================================

PAGES_DIR = Path("data/ecograder")

eco_pages = []

for f in PAGES_DIR.glob("*/report.json"):
    report_id = f.parent.name

    if report_id not in eco_report_ids:
        continue

    try:
        with f.open() as file:
            data = json.load(file)

        breakdown = data["props"]["breakdownGraphData"]

        eco_pages.append(
            {
                "report_id": report_id,
                "eco_page_mb": breakdown["total"]["byteTotal"] / (1024 * 1024),
            }
        )

    except Exception:
        continue

eco_pages = pd.DataFrame(eco_pages)

# =========================================================
# 3. WEBSITE CARBON CSV
# =========================================================

wc = pd.read_csv("websitecarbon.csv")

wc["url"] = wc["url"].astype(str).str.strip().str.lower()
wc["report_key"] = wc["report_key"].astype(str)

wc["co2_wc"] = pd.to_numeric(wc["co2_grams"], errors="coerce")
wc["scrape_date"] = pd.to_datetime(wc["scrape_date"], errors="coerce", utc=True)

wc = (
    wc.dropna(subset=["co2_wc"])
    .sort_values("scrape_date")
    .groupby("url", as_index=False)
    .tail(1)
)

wc_keys = wc["report_key"].unique()

# =========================================================
# 4. WEBSITE CARBON PAGE SIZE (JSON via report_key)
# =========================================================

WC_DIR = Path("data/websitecarbon")

wc_pages = []

for f in WC_DIR.glob("*/page.json"):
    report_key = f.parent.name

    if report_key not in wc_keys:
        continue

    try:
        with f.open() as file:
            data = json.load(file)

        grams = data.get("grams")
        if grams is None:
            continue

        wc_pages.append({"report_key": report_key, "wc_page_g": grams})

    except Exception:
        continue

wc_pages = pd.DataFrame(wc_pages)

# =========================================================
# 5. MERGE ECO SIDE
# =========================================================

df_eco = eco.merge(eco_pages, on="report_id", how="left")

# =========================================================
# 6. MERGE WC SIDE
# =========================================================

df_wc = wc.merge(wc_pages, on="report_key", how="left")

# =========================================================
# 7. FINAL MERGE (BY URL)
# =========================================================

df = df_eco.merge(df_wc, on="url", how="inner")

# =========================================================
# 8. STRICT CLEANING (DROP ALL INCOMPLETE ROWS)
# =========================================================

df_plot = df.dropna(subset=["co2_eco", "co2_wc", "eco_page_mb", "wc_page_g"]).copy()

df_plot = df_plot[(df_plot["eco_page_mb"] > 0) & (df_plot["wc_page_g"] > 0)]

print("Final usable rows:", len(df_plot))


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
            name=f"OLS (r={r:.3f}, slope={slope:.3f})",
            hoverinfo="skip",
        )
    )
    return r, slope


# =========================================================
# 9. PLOT — ECO vs WC (bubble = page size)
# =========================================================

# df_plot["page_size"] = df_plot["eco_page_mb"]

fig = px.scatter(
    df_plot,
    x="co2_wc",
    y="co2_eco",
    hover_data=["url", "eco_page_mb", "wc_page_g"],
    opacity=0.7,
    color_continuous_scale="Viridis",
)

r, slope = add_ols(fig, df_plot, "co2_wc", "co2_eco")

fig.update_layout(
    xaxis_title="WebsiteCarbon CO₂ (g per page view)",
    yaxis_title="EcoGrader CO₂ (g per page view)",
)

max_val = max(df_plot["co2_wc"].max(), df_plot["co2_eco"].max())

fig.update_layout(
    xaxis=dict(range=[0, max_val], constrain="domain"),
    yaxis=dict(range=[0, max_val], scaleanchor="x", scaleratio=1, constrain="domain"),
)

fig.write_html(str(plots_dir / "ecograder_vs_wc_co2.html"), include_plotlyjs="cdn")
fig.write_image(str(plots_dir / "ecograder_vs_wc_co2.jpg"), scale=2)
