from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import pearsonr
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

data = pd.read_csv("dataExtracted.csv")

num_cols = [
    "gm_cpu_energy_kwh",
    "eco_page_weight_bytes",
    "eco_web_requests",
]
for c in num_cols:
    data[c] = pd.to_numeric(data[c], errors="coerce")
data = data.dropna(subset=num_cols).copy()

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

KWH_TO_J = 3_600_000

data["gm_cpu_energy_j"] = data["gm_cpu_energy_kwh"] * KWH_TO_J
data["eco_page_weight_mb"] = data["eco_page_weight_bytes"] / (1024 * 1024)


def add_regline(fig, x, y, row, col):
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
            showlegend=True,
        ),
        row=row,
        col=col,
    )
    return r


fig = make_subplots(
    rows=1,
    cols=2,
    subplot_titles=[
        "GM CPU Energy vs EcoGrader Page Weight",
        "GM CPU Energy vs EcoGrader Web Requests",
    ],
)

fig.add_trace(
    go.Scatter(
        x=data["eco_page_weight_mb"],
        y=data["gm_cpu_energy_j"],
        mode="markers",
        marker=dict(size=6, opacity=0.6),
        text=data["url"],
        hovertemplate=(
            "<b>%{text}</b><br>"
            "Page weight: %{x:.2f} MB<br>"
            "CPU energy: %{y:.4g} J"
            "<extra></extra>"
        ),
        name="Pages",
        showlegend=False,
    ),
    row=1,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=data["eco_web_requests"],
        y=data["gm_cpu_energy_j"],
        mode="markers",
        marker=dict(size=6, opacity=0.6),
        text=data["url"],
        hovertemplate=(
            "<b>%{text}</b><br>"
            "Web requests: %{x:.0f}<br>"
            "CPU energy: %{y:.4g} J"
            "<extra></extra>"
        ),
        name="Pages",
        showlegend=False,
    ),
    row=1,
    col=2,
)

r_pw = add_regline(fig, data["eco_page_weight_mb"], data["gm_cpu_energy_j"], row=1, col=1)
r_wr = add_regline(fig, data["eco_web_requests"], data["gm_cpu_energy_j"], row=1, col=2)

fig.update_xaxes(title_text="Page Weight (MB)", row=1, col=1)
fig.update_xaxes(title_text="Web Requests", row=1, col=2)
fig.update_yaxes(title_text="GM CPU Energy (J)", row=1, col=1)

fig.update_layout(
    height=500,
    width=1100,
    template="plotly_white",
    hovermode="closest",
)

fname = "energy_vs_webrequests_comparison.html"
fig.write_html(str(plots_dir / fname), include_plotlyjs="cdn")
fig.write_image(str(plots_dir / "energy_vs_webrequests_comparison.jpg"), scale=2)
print(f"Saved {fname}")
print(f"  Page weight vs CPU energy:  r = {r_pw:.3f}")
print(f"  Web requests vs CPU energy: r = {r_wr:.3f}")
print(f"  Delta r: {abs(r_wr) - abs(r_pw):+.3f}")

# =====================================================
# MULTIPLE LINEAR REGRESSION
# =====================================================

X = data[["eco_page_weight_mb", "eco_web_requests"]].values
y = data["gm_cpu_energy_j"].values

model_full = LinearRegression().fit(X, y)
y_pred_full = model_full.predict(X)
r2_full = r2_score(y, y_pred_full)

X_pw = data[["eco_page_weight_mb"]].values
model_pw = LinearRegression().fit(X_pw, y)
y_pred_pw = model_pw.predict(X_pw)
r2_pw = r2_score(y, y_pred_pw)

X_wr = data[["eco_web_requests"]].values
model_wr = LinearRegression().fit(X_wr, y)
y_pred_wr = model_wr.predict(X_wr)
r2_wr = r2_score(y, y_pred_wr)

print("\n--- Linear Regression (sklearn) ---")
print(f"  Page weight only:          R² = {r2_pw:.3f}")
print(f"  Web requests only:         R² = {r2_wr:.3f}")
print(f"  Page weight + requests:    R² = {r2_full:.3f}")
print(f"  R² gain from adding requests: {r2_full - r2_pw:+.3f}")
print(f"\n  Multiple model coefficients:")
print(f"    intercept:       {model_full.intercept_:.4g} J")
print(f"    page_weight_mb:  {model_full.coef_[0]:.4g} J/MB")
print(f"    web_requests:    {model_full.coef_[1]:.4g} J/req")
