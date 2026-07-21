#!/usr/bin/env python3
"""Plot energy vs page weight per domain.

Reads result.json from each variant, uses the same network metrics as compareRuns.py.
For variants with low coverage (< 50%) or missing network data, allows manual page
weight overrides via MANUAL_PAGE_WEIGHTS dict below.

Usage:
    python3 plotEnergyVsPageWeight.py
"""

from pathlib import Path
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PERFETTO_DIR = Path(__file__).resolve().parent
PLOTS_DIR = Path(__file__).resolve().parent / "plots" / "pageOptimizations"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

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


def load_all():
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
        net = r.get("network", {})
        sync = r.get("sync", {})

        perfetto_avg = e.get("perfetto_avg_j", float("nan"))
        external_avg = e.get("external_avg_j", float("nan"))
        perfetto_j = e.get("perfetto_j", float("nan"))
        sync_events = sync.get("events", 0)

        median_page_bytes = net.get("median_page_bytes", 0)
        coverage = net.get("coverage", 0)

        # Check manual override from result.json
        manual_pw = net.get("manual_page_weight_bytes")
        if manual_pw is not None:
            median_page_bytes = float(manual_pw)
            coverage = 100.0  # manual override = full confidence

        if pd.isna(perfetto_avg) or perfetto_avg == 0:
            continue
        if sync_events == 0:
            continue

        energy_per_page = perfetto_j / sync_events

        rows.append({
            "variant": variant,
            "domain": domain,
            "label": label,
            "is_baseline": is_baseline,
            "median_page_bytes": median_page_bytes,
            "coverage": coverage,
            "energy_per_page_j": energy_per_page,
            "perfetto_j": perfetto_j,
            "sync_events": sync_events,
        })

    return pd.DataFrame(rows)


palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22"]
color_map = {url: palette[i % len(palette)] for i, url in enumerate(SELECTED_URLS)}
variant_symbols = ["circle", "diamond", "square", "cross", "star"]


if __name__ == "__main__":
    df = load_all()

    valid = df[df["coverage"] >= 50].copy()

    # Per-domain: skip certain variants
    SKIP_VARIANTS = {
        "https://tradingview.com": {"base_small", "merged_css_small"},
    }

    for domain_url in SELECTED_URLS:
        domain_df = valid[valid["domain"] == domain_url]
        if len(domain_df) == 0:
            continue

        # Skip unwanted variants
        skip = SKIP_VARIANTS.get(domain_url, set())
        domain_df = domain_df[~domain_df["label"].isin(skip)]
        if len(domain_df) == 0:
            continue

        short = DOMAIN_SHORT[domain_url]
        color = color_map[domain_url]
        labels = sorted(set(domain_df["label"].tolist()))
        sym_map = {lab: variant_symbols[i % len(variant_symbols)] for i, lab in enumerate(labels)}

        baseline_row = domain_df[domain_df["is_baseline"]]
        base_energy = baseline_row.iloc[0]["energy_per_page_j"] if len(baseline_row) > 0 else 0
        base_weight = baseline_row.iloc[0]["median_page_bytes"] / 1e6 if len(baseline_row) > 0 else 0

        fig = go.Figure()

        for _, row in domain_df.iterrows():
            fig.add_trace(go.Scatter(
                x=[row["median_page_bytes"] / 1e6],
                y=[row["energy_per_page_j"]],
                mode="markers",
                marker=dict(
                    size=14 if row["is_baseline"] else 10,
                    color=color,
                    symbol=sym_map[row["label"]],
                    line=dict(width=2 if row["is_baseline"] else 0, color="black"),
                ),
                name=row["label"],
                showlegend=True,
                hovertemplate=(
                    f"{row['label']}<br>"
                    "Page weight: %{x:.2f} MB<br>"
                    "Energy/page: %{y:.2f} J<br>"
                    f"Coverage: {row['coverage']:.0f}%"
                    "<extra></extra>"
                ),
            ))

        if base_energy > 0:
            opt_rows = domain_df[~domain_df["is_baseline"]].reset_index(drop=True)

            # Per-domain annotation arrow offsets (ax, ay in pixels)
            ANNO_OFFSETS = {
                "https://tradingview.com": [
                    (-45, -45), (45, -45), (45, 45), (-45, 45),
                ],
                "https://dropbox.com": [
                    (-40, -40),
                    (+40, +40),
                ],
                "https://un.org": [
                    (+60, +60),
                    (+50, +50),
                ],
                "https://creativecommons.org": [
                    (+60, 0),
                    (0, -40),
                ],
            }
            offsets = ANNO_OFFSETS.get(domain_url, None)

            for i, row in opt_rows.iterrows():
                energy_pct = row["energy_per_page_j"] / base_energy * 100
                weight_pct = (row["median_page_bytes"] / 1e6) / base_weight * 100

                if offsets:
                    ax, ay = offsets[i % len(offsets)]
                else:
                    ax, ay = 0, -40 - (i * 50)

                fig.add_annotation(
                    x=row["median_page_bytes"] / 1e6,
                    y=row["energy_per_page_j"],
                    text=(
                        f"<b>{row['label']}</b><br>"
                        f"energy: <b>{energy_pct:.1f}%</b><br>"
                        f"weight: {weight_pct:.1f}%"
                    ),
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=1.5,
                    ax=ax,
                    ay=ay,
                    font=dict(size=12),
                    bgcolor="white",
                    bordercolor="gray",
                    borderwidth=1,
                    borderpad=3,
                )

            max_xy = max(
                (domain_df["median_page_bytes"] / 1e6).max() * 1.15,
                domain_df["energy_per_page_j"].max() * 1.15,
            )
            fig.add_trace(go.Scatter(
                x=[0, max_xy], y=[0, max_xy],
                mode="lines",
                line=dict(color="gray", dash="dash", width=1),
                showlegend=False, hoverinfo="skip",
            ))

        fig.update_layout(
            xaxis_title="Page Weight (MB)",
            yaxis_title="Energy per Page Load (J)",
            xaxis=dict(range=[0, (domain_df["median_page_bytes"] / 1e6).max() * 1.15]),
            yaxis=dict(range=[0, domain_df["energy_per_page_j"].max() * 1.15]),
            height=700, width=800,
            legend=dict(title="Variant", bordercolor="gray", borderwidth=1),
        )

        out_html = PLOTS_DIR / f"{short}_energy_vs_weight.html"
        fig.write_html(str(out_html), include_plotlyjs="cdn")
        out_jpg = PLOTS_DIR / f"{short}_energy_vs_weight.jpg"
        fig.write_image(str(out_jpg), scale=2)

        print(f"Wrote {out_html}")
        print(f"Wrote {out_jpg}")

    # --- Summary table ---
    print("=" * 85)
    print("NETWORK DATA SUMMARY (coverage < 50% may need manual override)")
    print("=" * 85)
    print(f"{'VARIANT':55s} {'PAGE_MB':>10s} {'ENERGY/J':>10s} {'COVERAGE':>9s}")
    print("-" * 85)
    for _, row in df.sort_values("domain").iterrows():
        flag = " <-- LOW" if row["coverage"] < 50 else ""
        print(f"{row['variant']:55s} {row['median_page_bytes']/1e6:10.2f} {row['energy_per_page_j']:10.2f} {row['coverage']:8.1f}%{flag}")
