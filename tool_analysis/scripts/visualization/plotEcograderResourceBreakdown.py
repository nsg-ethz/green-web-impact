#!/usr/bin/env python3

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
plots_dir.mkdir(exist_ok=True)

PAGES_DIR = Path("data/ecograder")


def load_reports():
    rows = []

    for report_file in PAGES_DIR.glob("*/report.json"):
        try:
            with report_file.open() as f:
                data = json.load(f)

            props = data["props"]
            response = props["report"]["response"]
            breakdown = props["breakdownGraphData"]

            rows.append(
                {
                    "page_id": report_file.parent.name,
                    "url": response["site_submitted"],
                    "score": response["score"],
                    "total": breakdown["total"]["byteTotal"],
                    "html": breakdown["html"]["byteTotal"],
                    "images": breakdown["images"]["byteTotal"],
                    "scripts": breakdown["scripts"]["byteTotal"],
                    "media": breakdown["media"]["byteTotal"],
                    "other": breakdown["other"]["byteTotal"],
                }
            )

        except Exception as e:
            print(f"Failed to process {report_file}: {e}")

    if not rows:
        raise RuntimeError("No reports found")

    df = pd.DataFrame(rows)

    # Convert to MB
    for col in ["total", "html", "images", "scripts", "media", "other"]:
        df[f"{col}_mb"] = df[col] / (1024 * 1024)

    # Resource percentages
    for col in ["html", "images", "scripts", "media", "other"]:
        df[f"{col}_pct"] = 100 * df[col] / df["total"]

    return df


def print_summary(df):
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(f"Pages analyzed: {len(df)}")
    print(f"Average score: {df['score'].mean():.1f}")
    print(f"Median score: {df['score'].median():.1f}")

    print("\nTop 10 largest pages:")
    print(
        df.sort_values("total_mb", ascending=False)[["url", "score", "total_mb"]]
        .head(10)
        .to_string(index=False)
    )


def print_correlations(df):
    print("\n" + "=" * 80)
    print("CORRELATION WITH SCORE")
    print("=" * 80)

    absolute_cols = [
        "html_mb",
        "images_mb",
        "scripts_mb",
        "media_mb",
        "other_mb",
        "total_mb",
    ]

    corr_abs = df[absolute_cols + ["score"]].corr()["score"].drop("score").sort_values()

    print("\nAbsolute size correlations:")
    print(corr_abs.round(3))

    pct_cols = [
        "html_pct",
        "images_pct",
        "scripts_pct",
        "media_pct",
        "other_pct",
    ]

    corr_pct = df[pct_cols + ["score"]].corr()["score"].drop("score").sort_values()

    print("\nComposition (%) correlations:")
    print(corr_pct.round(3))


def plot_score_vs_weight(df):
    fig = px.scatter(
        df,
        x="total_mb",
        y="score",
        hover_name="url",
        hover_data={
            "html_mb": ":.2f",
            "images_mb": ":.2f",
            "scripts_mb": ":.2f",
            "media_mb": ":.2f",
            "other_mb": ":.2f",
            "total_mb": ":.2f",
        },
    )

    fig.update_layout(
        xaxis_title="Total Page Weight (MB)",
        yaxis_title="Score",
    )

    fig.write_html(str(plots_dir / "ecograder_score_vs_weight.html"), include_plotlyjs="cdn")
    fig.write_image(str(plots_dir / "ecograder_score_vs_weight.jpg"), scale=2)


def plot_resource_composition(df):
    plot_df = df.sort_values("total_mb").reset_index(drop=True)

    fig = go.Figure()

    colors = {
        "html_mb": "#4C78A8",
        "scripts_mb": "#F58518",
        "images_mb": "#54A24B",
        "media_mb": "#E45756",
        "other_mb": "#B279A2",
    }

    for col in ["html_mb", "scripts_mb", "images_mb", "media_mb", "other_mb"]:
        fig.add_trace(
            go.Scatter(
                x=plot_df.index,
                y=plot_df[col],
                stackgroup="one",
                name=col.replace("_mb", "").title(),
                line=dict(width=0.5),
                fillcolor=colors[col],
                customdata=plot_df["url"],
                hovertemplate=(
                    "<b>%{customdata}</b><br>"
                    f"{col.replace('_mb', '').title()}: "
                    "%{y:.2f} MB"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        xaxis_title="Pages",
        yaxis_title="MB",
        hovermode="x unified",
    )

    fig.write_html(str(plots_dir / "page_weight_composition.html"), include_plotlyjs="cdn")
    fig.write_image(str(plots_dir / "page_weight_composition.jpg"), scale=2)


def plot_resource_vs_score(df):
    resources = [
        "html_mb",
        "images_mb",
        "scripts_mb",
        "media_mb",
        "other_mb",
    ]

    fig = make_subplots(
        rows=2,
        cols=3,
        subplot_titles=[
            "HTML",
            "Images",
            "Scripts",
            "Media",
            "Other",
        ],
    )

    for i, resource in enumerate(resources):
        row = i // 3 + 1
        col = i % 3 + 1

        fig.add_trace(
            go.Scatter(
                x=df[resource],
                y=df["score"],
                mode="markers",
                text=df["url"],
                hovertemplate=(
                    "%{text}<br>"
                    + resource
                    + ": %{x:.2f} MB<br>"
                    + "Score: %{y:.1f}"
                    + "<extra></extra>"
                ),
                marker=dict(size=7, opacity=0.7),
            ),
            row=row,
            col=col,
        )

    fig.update_layout(
        height=900,
        showlegend=False,
    )

    fig.write_html(str(plots_dir / "resource_vs_score.html"), include_plotlyjs="cdn")
    fig.write_image(str(plots_dir / "resource_vs_score.jpg"), scale=2)


def plot_resource_percentage_vs_score(df):
    resources = [
        "html_pct",
        "images_pct",
        "scripts_pct",
        "media_pct",
        "other_pct",
    ]

    fig = make_subplots(
        rows=2,
        cols=3,
        subplot_titles=[
            "HTML %",
            "Images %",
            "Scripts %",
            "Media %",
            "Other %",
        ],
    )

    for i, resource in enumerate(resources):
        row = i // 3 + 1
        col = i % 3 + 1

        fig.add_trace(
            go.Scatter(
                x=df[resource],
                y=df["score"],
                mode="markers",
                text=df["url"],
                hovertemplate=(
                    "%{text}<br>"
                    + resource
                    + ": %{x:.1f}%<br>"
                    + "Score: %{y:.1f}"
                    + "<extra></extra>"
                ),
                marker=dict(size=7, opacity=0.7),
            ),
            row=row,
            col=col,
        )

    fig.update_layout(
        height=900,
        showlegend=False,
    )

    fig.write_html(str(plots_dir / "resource_pct_vs_score.html"), include_plotlyjs="cdn")
    fig.write_image(str(plots_dir / "resource_pct_vs_score.jpg"), scale=2)


def plot_image_media_impact(df):
    fig = px.scatter(
        df,
        x="total_mb",
        y="score",
        size="images_mb",
        color="media_mb",
        hover_name="url",
        hover_data={
            "images_mb": ":.2f",
            "media_mb": ":.2f",
            "scripts_mb": ":.2f",
            "html_mb": ":.2f",
        },
    )

    fig.update_layout(
        xaxis_title="Total Weight (MB)",
        yaxis_title="Score",
    )

    fig.write_html(str(plots_dir / "image_media_impact.html"), include_plotlyjs="cdn")
    fig.write_image(str(plots_dir / "image_media_impact.jpg"), scale=2)


def plot_top_offenders(df):
    print("\n" + "=" * 80)
    print("TOP IMAGE-HEAVY PAGES")
    print("=" * 80)

    print(
        df.sort_values("images_mb", ascending=False)[
            ["url", "score", "images_mb", "total_mb"]
        ]
        .head(15)
        .to_string(index=False)
    )

    print("\n" + "=" * 80)
    print("TOP MEDIA-HEAVY PAGES")
    print("=" * 80)

    print(
        df.sort_values("media_mb", ascending=False)[
            ["url", "score", "media_mb", "total_mb"]
        ]
        .head(15)
        .to_string(index=False)
    )

    print("\n" + "=" * 80)
    print("TOP SCRIPT-HEAVY PAGES")
    print("=" * 80)

    print(
        df.sort_values("scripts_mb", ascending=False)[
            ["url", "score", "scripts_mb", "total_mb"]
        ]
        .head(15)
        .to_string(index=False)
    )


def main():
    df = load_reports()

    print_summary(df)
    print_correlations(df)
    plot_top_offenders(df)

    # 1. Main relationship
    plot_score_vs_weight(df)

    # 2. Overall composition across all pages
    plot_resource_composition(df)

    # 3. Absolute resource weight vs score
    plot_resource_vs_score(df)

    # 4. Relative resource composition vs score
    plot_resource_percentage_vs_score(df)

    # 5. Bubble chart emphasizing images/media
    plot_image_media_impact(df)


if __name__ == "__main__":
    main()
