from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

data = pd.read_csv("dataExtracted.csv")

data = data.dropna(
    subset=[
        "eco_overall_score_no_greenhosting",
        "eco_page_weight_bytes",
        "gm_page_weight_bytes",
        "eco_id",
        "url",
    ]
)

data["eco_report_url"] = "https://legacy.ecograder.com/report/" + data["eco_id"].astype(
    str
)

x = data["eco_overall_score_no_greenhosting"]

fig = go.Figure()

# =====================================================
# Eco Page Weight
# =====================================================
fig.add_trace(
    go.Scatter(
        x=x,
        y=data["eco_page_weight_bytes"],
        mode="markers",
        name="Eco Page Weight",
        customdata=data[
            [
                "url",
                "eco_report_url",
                "gm_page_weight_bytes",
                "eco_page_weight_bytes",
                "eco_overall_score_no_greenhosting",
            ]
        ],
        hovertemplate=(
            "URL: %{customdata[0]}<br>"
            "Eco Report: %{customdata[1]}<br>"
            "Eco Score: %{customdata[4]}<br>"
            "Eco Page Weight: %{customdata[3]} bytes<br>"
            "GM Page Weight: %{customdata[2]} bytes<br>"
            "<extra></extra>"
        ),
        marker=dict(size=8, opacity=0.7),
    )
)

# =====================================================
# GM Page Weight
# =====================================================
fig.add_trace(
    go.Scatter(
        x=x,
        y=data["gm_page_weight_bytes"],
        mode="markers",
        name="GM Page Weight",
        customdata=data[
            [
                "url",
                "eco_report_url",
                "eco_page_weight_bytes",
                "gm_page_weight_bytes",
                "eco_overall_score_no_greenhosting",
            ]
        ],
        hovertemplate=(
            "URL: %{customdata[0]}<br>"
            "Eco Report: %{customdata[1]}<br>"
            "Eco Score: %{customdata[4]}<br>"
            "GM Page Weight: %{customdata[3]} bytes<br>"
            "Eco Page Weight: %{customdata[2]} bytes<br>"
            "<extra></extra>"
        ),
        marker=dict(size=8, opacity=0.7),
    )
)

fig.update_layout(
    xaxis_title="Ecograder Score (no green hosting)",
    yaxis_title="Page Weight (bytes)",
    template="plotly_white",
    clickmode="event+select",
)

# =====================================================
# Export HTML + inject click handler
# =====================================================
html = pio.to_html(fig, full_html=True, include_plotlyjs="cdn")

custom_js = """
<script>
document.addEventListener('DOMContentLoaded', function () {
    const plots = document.getElementsByClassName('plotly-graph-div');

    for (let i = 0; i < plots.length; i++) {
        plots[i].on('plotly_click', function(data) {
            const point = data.points[0];
            const url = point.customdata[1]; // eco_report_url
            if (url) {
                window.open(url, '_blank');
            }
        });
    }
});
</script>
"""

html = html.replace("</body>", custom_js + "</body>")

with open(str(plots_dir / "eco_vs_gm_page_weight.html"), "w", encoding="utf-8") as f:
    f.write(html)

fig.write_image(str(plots_dir / "eco_vs_gm_page_weight.jpg"), scale=2)
