from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

# =====================================================
# Load data
# =====================================================

df = pd.read_csv("dataExtracted.csv")
df = df[~df["url"].isin({"https://slack.com"})]
TARGET = "gm_estimated_total_energy_kwh"

FEATURES = [
    "eco_scripts_bytesTotal",
    "eco_images_bytesTotal",
    "eco_html_bytesTotal",
    "eco_media_bytesTotal",
    "eco_other_bytesTotal",
    "eco_page_weight_bytes",
    "eco_web_requests",
]

data = df[["url"] + FEATURES + [TARGET]].dropna()

# =====================================================
# Feature engineering (composites)
# =====================================================

data["eco_page_plus_images"] = (
    data["eco_page_weight_bytes"] + data["eco_images_bytesTotal"]
)

data["eco_page_plus_scripts"] = (
    data["eco_page_weight_bytes"] + data["eco_scripts_bytesTotal"]
)

data["eco_page_plus_media"] = (
    data["eco_page_weight_bytes"] + data["eco_media_bytesTotal"]
)

data["eco_page_plus_all_assets"] = (
    data["eco_page_weight_bytes"]
    + data["eco_images_bytesTotal"]
    + data["eco_scripts_bytesTotal"]
    + data["eco_media_bytesTotal"]
)

# =====================================================
# Final feature list
# =====================================================

FEATURES = FEATURES + [
    "eco_page_plus_images",
    "eco_page_plus_scripts",
    "eco_page_plus_media",
    "eco_page_plus_all_assets",
]

# =====================================================
# Train/test split
# =====================================================

X_train_all, X_test_all, y_train, y_test, url_train, url_test = train_test_split(
    data[FEATURES], data[TARGET], data["url"], test_size=0.2, random_state=42
)

# =====================================================
# STORAGE FOR RESULTS
# =====================================================

predictions = []
results = []

# =====================================================
# Train single-feature models
# =====================================================

for feature in FEATURES:
    X_train = X_train_all[[feature]]
    X_test = X_test_all[[feature]]

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    model = LinearRegression()
    model.fit(X_train, y_train)

    pred = model.predict(X_test)

    r2 = r2_score(y_test, pred)
    results.append((feature, r2))

    predictions.append((feature, pred))

# =====================================================
# GLOBAL RANGE
# =====================================================

global_min = min(y_test.min(), min(pred.min() for _, pred in predictions))

global_max = max(y_test.max(), max(pred.max() for _, pred in predictions))

# =====================================================
# SUBPLOTS (AUTO-SCALED)
# =====================================================

n = len(FEATURES)
cols = 3
rows = int(np.ceil(n / cols))

fig = make_subplots(rows=rows, cols=cols, subplot_titles=FEATURES)

positions = [(r, c) for r in range(1, rows + 1) for c in range(1, cols + 1)]
positions = positions[:n]

# =====================================================
# PLOT TRACES
# =====================================================

for i, (feature, pred) in enumerate(predictions):
    row, col = positions[i]

    fig.add_trace(
        go.Scatter(
            x=y_test,
            y=pred,
            mode="markers",
            text=url_test,
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Actual: %{x:.6f}<br>"
                "Predicted: %{y:.6f}<extra></extra>"
            ),
            marker=dict(size=6, opacity=0.6),
            name=feature,
        ),
        row=row,
        col=col,
    )

    # 1:1 reference line
    fig.add_trace(
        go.Scatter(
            x=[global_min, global_max],
            y=[global_min, global_max],
            mode="lines",
            line=dict(color="red", dash="dash"),
            showlegend=False,
        ),
        row=row,
        col=col,
    )

# =====================================================
# 1:1 AXIS LOCK
# =====================================================

for i in range(1, len(FEATURES) + 1):
    fig.layout[f"yaxis{i}"].update(
        scaleanchor=f"x{i}", scaleratio=1, constrain="domain"
    )

# =====================================================
# IDENTICAL AXES
# =====================================================

for row, col in positions:
    fig.update_xaxes(range=[global_min, global_max], row=row, col=col)
    fig.update_yaxes(range=[global_min, global_max], row=row, col=col)

# =====================================================
# LAYOUT
# =====================================================

fig.update_layout(
    height=1100,
    width=1100,
    showlegend=False,
)

fig.update_xaxes(title_text="Actual Energy")
fig.update_yaxes(title_text="Predicted Energy")

# =====================================================
# SAVE + OPEN
# =====================================================

output_file = plots_dir / "feature_level_energy_models.html"
fig.write_html(str(output_file), include_plotlyjs="cdn")
jpg_file = plots_dir / "feature_level_energy_models.jpg"
fig.write_image(str(jpg_file), scale=2)

print("\nFEATURE PERFORMANCE (R²)")
for f, r2 in sorted(results, key=lambda x: x[1], reverse=True):
    print(f"{f:30s} R2={r2:.3f}")

print(f"\nSaved: {output_file}")
