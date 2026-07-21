from pathlib import Path

import json
import pandas as pd
import plotly.graph_objects as go

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

PERFETTO_DIR = Path(__file__).resolve().parent.parent.parent.parent / "measurements"

SELECTED_URLS = [
    "https://creativecommons.org",
    "https://dropbox.com",
    "https://nsg.ee.ethz.ch",
    "https://slack.com",
    "https://tradingview.com",
    "https://un.org",
]

DOMAIN_SHORT = {
    "https://creativecommons.org": "creativecommons.org",
    "https://dropbox.com": "dropbox.com",
    "https://nsg.ee.ethz.ch": "nsg.ee.ethz.ch",
    "https://slack.com": "slack.com",
    "https://tradingview.com": "tradingview.com",
    "https://un.org": "un.org",
}

COLORS = {
    "https://dropbox.com": "#1f77b4",
    "https://slack.com": "#ff7f0e",
    "https://tradingview.com": "#2ca02c",
}

variant_symbols = ["circle", "diamond", "square", "cross", "star"]


def _variant_to_domain(variant_name: str) -> str:
    for url in SELECTED_URLS:
        short = url.replace("https://", "")
        if short in variant_name:
            return url
    return variant_name


def _variant_label(variant_name: str, domain_url: str) -> str:
    short = domain_url.replace("https://", "")
    label = variant_name.replace(short, "").strip("_")
    label = label.removeprefix("www.").strip("_")
    if not label or label == "baseline":
        label = "baseline"
    return label


def load_perfetto():
    rows = []
    for result_path in sorted(PERFETTO_DIR.glob("runs_*/*/result.json")):
        variant_dir = result_path.parent
        if not variant_dir.parent.name.startswith("runs_"):
            continue

        variant = variant_dir.name
        domain = _variant_to_domain(variant)
        label = _variant_label(variant, domain)
        is_baseline = "baseline" in variant.lower()

        with open(result_path) as f:
            r = json.load(f)
        e = r.get("energy", {})
        perfetto_avg = e.get("perfetto_avg_j", float("nan"))
        external_avg = e.get("external_avg_j", float("nan"))

        if pd.isna(perfetto_avg) or pd.isna(external_avg):
            continue

        rows.append({
            "variant": variant,
            "domain": domain,
            "label": label,
            "is_baseline": is_baseline,
            "perfetto_avg_j": perfetto_avg,
            "external_avg_j": external_avg,
        })

    return pd.DataFrame(rows)


def plot_domain(domain_url, pf_domain):
    color = COLORS[domain_url]
    title = DOMAIN_SHORT[domain_url]

    labels = sorted(set(pf_domain["label"].tolist()))
    sym_map = {lab: variant_symbols[i % len(variant_symbols)] for i, lab in enumerate(labels)}

    fig = go.Figure()

    for _, row in pf_domain.iterrows():
        lab = row["label"]
        is_bl = row["is_baseline"]

        fig.add_trace(go.Scatter(
            x=[row["perfetto_avg_j"]],
            y=[row["external_avg_j"]],
            mode="markers+text",
            marker=dict(
                size=14 if is_bl else 10,
                color=color,
                symbol=sym_map[lab],
                line=dict(width=2 if is_bl else 0, color="black"),
            ),
            text=[lab],
            textposition="top center" if is_bl else "middle left" if "jsreplace2" not in lab else "middle right",
            textfont=dict(size=10),
            showlegend=False,
            hovertemplate=(
                f"{lab}<br>"
                "Perfetto: %{x:.2f} J<br>"
                "Autopower: %{y:.2f} J"
                "<extra></extra>"
            ),
        ))

    max_val = max(pf_domain["perfetto_avg_j"].max(), pf_domain["external_avg_j"].max()) * 1.15
    fig.add_trace(go.Scatter(
        x=[0, max_val], y=[0, max_val],
        mode="lines",
        line=dict(color="gray", dash="dash", width=1),
        showlegend=False,
        hoverinfo="skip",
    ))

    fig.update_layout(
        xaxis_title="Perfetto (J)",
        yaxis_title="Autopower (J)",
        height=600,
        width=800,
    )

    out_path = plots_dir / f"perfetto_autopower_{title}.html"
    fig.write_html(str(out_path), include_plotlyjs="cdn")
    jpg_path = plots_dir / f"perfetto_autopower_{title}.jpg"
    fig.write_image(str(jpg_path), scale=2)
    print(f"Wrote {out_path}")
    print(f"Wrote {jpg_path}")


if __name__ == "__main__":
    pf = load_perfetto()

    # Filter out "small" variants for tradingview
    pf = pf[~((pf["domain"] == "https://tradingview.com") & pf["label"].str.contains("small", case=False))]

    for domain_url in ["https://dropbox.com", "https://slack.com", "https://tradingview.com"]:
        domain_pf = pf[pf["domain"] == domain_url]
        if len(domain_pf) > 0:
            plot_domain(domain_url, domain_pf)
