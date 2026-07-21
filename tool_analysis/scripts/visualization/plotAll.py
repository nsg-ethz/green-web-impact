from pathlib import Path
import json
import pandas as pd
import plotly.graph_objects as go

plots_dir = Path(__file__).resolve().parent.parent.parent / "plots"
page_opt_dir = plots_dir / "pageOptimizations"
page_opt_dir.mkdir(parents=True, exist_ok=True)

data_dir = Path(__file__).resolve().parent.parent.parent

GM_DIR = data_dir / "data" / "greenmetrics"
GC_CSV = data_dir / "greencoding.csv"
WC_CSV = data_dir / "websitecarbon.csv"
PERFETTO_DIR = data_dir.parent / "measurements"

DATA_FACTOR = 0.04106063
KWH_TO_J = 3_600_000

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

ALL_DOMAINS = [
    "https://creativecommons.org",
    "https://dropbox.com",
    "https://nsg.ee.ethz.ch",
    "https://slack.com",
    "https://tradingview.com",
    "https://un.org",
]

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


def enrich_from_sources(df_all, selected_urls):
    missing = [u for u in selected_urls if u not in df_all["url"].values]
    if not missing:
        return df_all

    gc = pd.read_csv(GC_CSV)
    gc["url_norm"] = gc["url"].str.strip().str.lower()
    gc = gc.dropna(subset=["url_norm"]).sort_values("ended_at").drop_duplicates("url_norm", keep="last")

    wc = pd.read_csv(WC_CSV)
    wc["url_norm"] = wc["url"].str.strip().str.lower()
    wc = wc.dropna(subset=["url_norm"]).sort_values("scrape_date").drop_duplicates("url_norm", keep="last")

    new_rows = []
    for url in missing:
        url_lower = url.lower()
        row = {"url": url}

        gc_match = gc[gc["url_norm"] == url_lower]
        if len(gc_match) > 0:
            report_id = gc_match.iloc[0]["report_id"]
            stats_file = GM_DIR / report_id / "stats.json"
            if stats_file.exists():
                try:
                    with open(stats_file) as f:
                        stats = json.load(f)
                    visit = stats["data"]["data"]["Visit page and idle for 5 s"]["data"]
                    cpu_energy_uj = visit["cpu_energy_rapl_msr_component"]["data"]["Package_0"]["data"][report_id]["mean"]
                    ram_energy_uj = visit["memory_energy_rapl_msr_component"]["data"]["DRAM_0"]["data"][report_id]["mean"]
                    page_weight = visit["network_total_cgroup_container"]["data"]["gmt-playwright-nodejs"]["data"][report_id]["mean"]

                    cpu_energy_j = cpu_energy_uj * 1e-6
                    ram_energy_j = ram_energy_uj * 1e-6
                    network_energy_j = DATA_FACTOR * (page_weight / 1024**3) * KWH_TO_J
                    total_energy_j = cpu_energy_j + ram_energy_j + network_energy_j

                    row["gm_cpu_energy_j"] = cpu_energy_j
                    row["gm_estimated_total_energy_j"] = total_energy_j
                    row["gm_id"] = report_id
                except Exception:
                    pass

        wc_match = wc[wc["url_norm"] == url_lower]
        if len(wc_match) > 0:
            wc_kwh = wc_match.iloc[0].get("energy_kwh", float("nan"))
            row["wc_energy_j"] = wc_kwh * KWH_TO_J if pd.notna(wc_kwh) else float("nan")

        new_rows.append(row)

    if new_rows:
        df_new = pd.DataFrame(new_rows)
        df_all = pd.concat([df_all, df_new], ignore_index=True)

    return df_all


def make_histogram_trace(global_series, label):
    if len(global_series) == 0:
        return []
    mean = global_series.mean()
    std = global_series.std()

    return [
        go.Histogram(x=global_series, nbinsx=60, marker=dict(opacity=0.5), showlegend=False, name="All pages"),
        go.Scatter(x=[mean, mean], y=[0, 0], mode="lines", line=dict(color="blue", width=2), showlegend=False),
    ], mean, std


palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22"]
color_map = {url: palette[i % len(palette)] for i, url in enumerate(SELECTED_URLS)}


if __name__ == "__main__":
    df = pd.read_csv(data_dir / "dataExtracted.csv")

    for col in ["gm_cpu_energy_kwh", "gm_estimated_total_energy_kwh"]:
        if col in df.columns:
            j_col = col.replace("_kwh", "_j")
            df[j_col] = df[col] * KWH_TO_J

    # wc_energy_kwh in dataExtracted.csv is now real kWh
    if "wc_energy_kwh" in df.columns:
        df["wc_energy_j"] = df["wc_energy_kwh"] * KWH_TO_J

    df = enrich_from_sources(df, SELECTED_URLS)
    pf = load_perfetto()

    # ---- Part 1: Histograms per metric (plots/) ----
    HIST_METRICS = {
        "gm_cpu_energy_j": "Green Metrics CPU Energy",
        "wc_energy_j": "Website Carbon Energy",
        "eco_scripts_bytesTotal": "EcoGrader: Scripts",
        "eco_images_bytesTotal": "EcoGrader: Images",
        "eco_media_bytesTotal": "EcoGrader: Media",
        "eco_html_bytesTotal": "EcoGrader: HTML",
        "eco_page_weight_bytes": "EcoGrader: Page Weight",
    }

    for metric_key, metric_title in HIST_METRICS.items():
        global_series = df[metric_key].dropna()
        if len(global_series) == 0:
            continue

        fig = go.Figure()

        fig.add_trace(go.Histogram(
            x=global_series, nbinsx=60, marker=dict(opacity=0.5),
            showlegend=False, name="All pages",
        ))

        mean = global_series.mean()
        std = global_series.std()

        fig.add_vline(x=mean, line_color="blue", line_width=2, annotation_text=f"mean={mean:.4g} J")
        fig.add_vrect(x0=mean - std, x1=mean + std, fillcolor="blue", opacity=0.15, line_width=0)

        for url in SELECTED_URLS:
            url_row = df[df["url"] == url]
            if len(url_row) == 0:
                continue
            val = url_row.iloc[0][metric_key]
            if pd.isna(val):
                continue
            z = (val - mean) / std if std > 0 else 0
            pct = (global_series < val).mean() * 100

            fig.add_trace(go.Scatter(
                x=[val], y=[0],
                mode="markers",
                marker=dict(size=12, color=color_map[url]),
                name=DOMAIN_SHORT[url],
                customdata=[f"z={z:.2f}, pct={pct:.1f}%"],
                hovertemplate=f"{DOMAIN_SHORT[url]}<br>{metric_title}: " + "%{x:.4g} J<extra>%{customdata}</extra>",
            ))

        fig.update_layout(
            xaxis_title="J",
            yaxis_title="Count",
            height=500,
            width=900,
            showlegend=True,
            legend=dict(title="Website", bordercolor="gray", borderwidth=1),
        )

        out_path = plots_dir / f"histogram_{metric_key}.html"
        fig.write_html(str(out_path), include_plotlyjs="cdn")
        jpg_path = plots_dir / f"histogram_{metric_key}.jpg"
        fig.write_image(str(jpg_path), scale=2)
        print(f"Wrote {out_path}")
        print(f"Wrote {jpg_path}")

    # ---- Part 2: Perfetto vs Autopower baselines scatter (plots/) ----
    pf_baselines = pf[pf["is_baseline"]]

    if len(pf_baselines) > 0:
        fig = go.Figure()

        for url in SELECTED_URLS:
            subset = pf_baselines[pf_baselines["domain"] == url]
            if len(subset) == 0:
                continue

            fig.add_trace(go.Scatter(
                x=subset["perfetto_avg_j"],
                y=subset["external_avg_j"],
                mode="markers",
                marker=dict(size=11, color=color_map[url]),
                name=DOMAIN_SHORT[url],
                customdata=subset["variant"],
                hovertemplate="%{customdata}<br>Perfetto: %{x:.2f} J<br>Autopower: %{y:.2f} J<extra></extra>",
            ))

        max_val = max(pf_baselines["perfetto_avg_j"].max(), pf_baselines["external_avg_j"].max()) * 1.15
        fig.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val],
            mode="lines",
            line=dict(color="gray", dash="dash", width=1),
            showlegend=False, hoverinfo="skip",
        ))

        fig.update_layout(
            xaxis_title="Perfetto (J)",
            yaxis_title="Autopower (J)",
            height=600, width=800,
            showlegend=True,
            legend=dict(title="Website", bordercolor="gray", borderwidth=1),
        )

        out_path = plots_dir / "scatter_baselines.html"
        fig.write_html(str(out_path), include_plotlyjs="cdn")
        jpg_path = plots_dir / "scatter_baselines.jpg"
        fig.write_image(str(jpg_path), scale=2)
        print(f"Wrote {out_path}")
        print(f"Wrote {jpg_path}")

    # ---- Part 3: Per-domain optimization scatters (pageOptimizations/) ----
    pf = pf[~((pf["domain"] == "https://dropbox.com") & (pf["label"] == "jsreplace2"))]
    pf = pf[~((pf["domain"] == "https://tradingview.com") & pf["label"].str.contains("small", case=False))]

    for domain_url in ALL_DOMAINS:
        domain_pf = pf[pf["domain"] == domain_url]
        if len(domain_pf) == 0:
            continue

        short = DOMAIN_SHORT[domain_url]
        color = color_map[domain_url]

        labels = sorted(set(domain_pf["label"].tolist()))
        sym_map = {lab: variant_symbols[i % len(variant_symbols)] for i, lab in enumerate(labels)}

        fig = go.Figure()

        for _, row in domain_pf.iterrows():
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
                textposition="top center",
                textfont=dict(size=10),
                showlegend=False,
                hovertemplate=f"{lab}<br>Perfetto: " + "%{x:.2f} J<br>Autopower: %{y:.2f} J<extra></extra>",
            ))

        max_val = max(domain_pf["perfetto_avg_j"].max(), domain_pf["external_avg_j"].max()) * 1.15
        fig.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val],
            mode="lines",
            line=dict(color="gray", dash="dash", width=1),
            showlegend=False, hoverinfo="skip",
        ))

        fig.update_layout(
            xaxis_title="Perfetto (J)",
            yaxis_title="Autopower (J)",
            height=600, width=800,
        )

        out_path = page_opt_dir / f"{short}.html"
        fig.write_html(str(out_path), include_plotlyjs="cdn")
        jpg_path = page_opt_dir / f"{short}.jpg"
        fig.write_image(str(jpg_path), scale=2)
        print(f"Wrote {out_path}")
        print(f"Wrote {jpg_path}")
