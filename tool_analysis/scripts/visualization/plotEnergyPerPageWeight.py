from pathlib import Path

import pandas as pd
import plotly.express as px

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

data = pd.read_csv("dataExtracted.csv")
# data = data[data["url"] == "https://un.org"]
data["gm_estimated_total_energy_mWh"] = data["gm_estimated_total_energy_kwh"] * 1e6
data["gm_energy_per_gigabyte"] = (data["gm_estimated_total_energy_kwh"]) / (
    data["gm_page_weight_bytes"] / 1e9
)


mean_energy = data["gm_energy_per_gigabyte"].mean()
median_energy = data["gm_energy_per_gigabyte"].median()

print("Mean kWh/GB:", mean_energy)
print("Median kWh/GB:", median_energy)

fig = px.scatter(
    data,
    x="url",
    y="gm_energy_per_gigabyte",
    color="url",
    hover_data={
        "gm_estimated_total_energy_kwh": ":.6f",
        "gm_page_weight_bytes": ":,.0f",
        "gm_energy_per_gigabyte": ":.6f",
        "gm_estimated_total_energy_mWh": ":.6f",
    },
)

fig.update_xaxes(visible=False)
# benchmark
fig.add_hline(
    y=0.080,
    line_dash="dash",
    line_color="red",
    annotation_text="SWDM: 0.080 kWh/GB",
)

# mean
fig.add_hline(
    y=mean_energy,
    line_dash="dash",
    line_color="green",
    annotation_text=f"Mean: {mean_energy:.4f}",
)

# median
fig.add_hline(
    y=median_energy,
    line_dash="dot",
    line_color="blue",
    annotation_text=f"Median: {median_energy:.4f}",
)

fig.write_html(str(plots_dir / "energy_per_gb.html"), include_plotlyjs="cdn")
fig.write_image(str(plots_dir / "energy_per_gb.jpg"), scale=2)
