import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

DATA_FACTOR = 0.04106063  # kWh per GB


# ============================================================
# HELPERS
# ============================================================


def extract_breakdown(breakdown):
    result = {}

    for name, values in breakdown.items():
        if not isinstance(values, dict):
            continue

        key = name.lower().replace(" ", "_").replace("-", "_").replace("/", "_")

        result[f"eco_{key}_bytesTotal"] = values.get("byteTotal", np.nan)
        result[f"eco_{key}_percentage"] = values.get("percentage", np.nan)

    return result


def find_categories(obj):
    if isinstance(obj, dict):
        if "categories" in obj and isinstance(obj["categories"], list):
            return obj["categories"]
        for v in obj.values():
            res = find_categories(v)
            if res:
                return res
    elif isinstance(obj, list):
        for item in obj:
            res = find_categories(item)
            if res:
                return res
    return []


def extract_scores(data):
    render_score = np.nan
    interaction_score = np.nan
    emissions_score = np.nan
    overall_eco_score = np.nan

    category_results = {}

    try:
        overall_eco_score = float(
            data["props"]["report"]["response"].get("score", np.nan)
        )
    except Exception:
        overall_eco_score = np.nan

    try:
        lh_perf = float(
            data["props"]["report"]["response"].get(
                "lighthouse_performance_score", np.nan
            )
        )
        lh_acc = float(
            data["props"]["report"]["response"].get(
                "lighthouse_accessibility_score", np.nan
            )
        )
    except Exception:
        lh_perf = lh_acc = np.nan

    categories = find_categories(data)

    for cat in categories:
        if not isinstance(cat, dict):
            continue

        name = cat.get("category")

        if name:
            key = name.lower().replace(" ", "_").replace("/", "_").replace("-", "_")
            category_results[f"eco_{key}_score"] = cat.get("category_score", np.nan)

        if cat.get("category") != "UX Design":
            continue

        metrics = cat.get("metrics", [])
        if not isinstance(metrics, list):
            continue

        for m in metrics:
            if not isinstance(m, dict):
                continue

            score = m.get("score", {})
            if not isinstance(score, dict):
                continue

            metricscore = score.get("metricscore", np.nan)

            if m.get("name") == "Improve Page Rendering":
                render_score = metricscore
            elif m.get("name") == "Page Interactions":
                interaction_score = metricscore

    try:
        emissions_score = float(
            data["props"]["report"]["response"].get("emissions_score", np.nan)
        )
    except Exception:
        emissions_score = np.nan

    return (
        overall_eco_score,
        render_score,
        interaction_score,
        emissions_score,
        lh_perf,
        lh_acc,
        category_results,
    )


# ============================================================
# LOAD DATASETS
# ============================================================

eco = pd.read_csv("ecograder.csv")
wc = pd.read_csv("websitecarbon.csv")
gc = pd.read_csv("gc_extracted.csv")


def normalize(url):
    if pd.isna(url):
        return url
    url = str(url).lower().strip()
    url = url.replace("https://", "").replace("http://", "")
    url = url.replace("www.", "")
    url = url.split("?")[0]
    return url.rstrip("/")


for df in (eco, wc, gc):
    df["url"] = df["url"].astype(str)
    df["url_key"] = df["url"].apply(normalize)

eco = eco.sort_values("scrape_date").drop_duplicates("report_id", keep="last")
wc = wc.sort_values("scrape_date").drop_duplicates("report_key", keep="last")

eco["report_id"] = eco["report_id"].astype(str)
wc["report_key"] = wc["report_key"].astype(str)
gc["report_id"] = gc["report_id"].astype(str)


# ============================================================
# LOAD ECO REPORTS
# ============================================================

eco_rows = []
eco_map = eco.set_index("report_id")

for f in Path("data/ecograder").glob("*/report.json"):
    rid = f.parent.name

    try:
        data = json.load(open(f))

        (
            overall,
            render_score,
            interaction_score,
            emissions_score,
            lh_perf,
            lh_acc,
            cat,
        ) = extract_scores(data)

        breakdown = data["props"]["breakdownGraphData"]
        response = data["props"]["report"]["response"]

        url = eco_map.loc[rid, "url"] if rid in eco_map.index else np.nan
        emissions_text = response.get("emissions_text", "N/A")

        eco_page_weight_bytes = breakdown.get("total", {}).get("byteTotal", np.nan)

    except Exception:
        url = np.nan
        overall = render_score = interaction_score = emissions_score = np.nan
        lh_perf = lh_acc = np.nan
        cat = {}
        eco_page_weight_bytes = np.nan
        emissions_text = "N/A"

    eco_rows.append(
        {
            "url": url,
            "eco_id": rid,
            "eco_overall_score": overall,
            "eco_lh_perf": lh_perf,
            "eco_lh_acc": lh_acc,
            "eco_render_score": render_score,
            "eco_interaction_score": interaction_score,
            "eco_emissions_score": emissions_score,
            "eco_emissions_text": emissions_text,
            "eco_page_weight_bytes": eco_page_weight_bytes,
            **cat,
        }
    )

eco_df = pd.DataFrame(eco_rows)

eco_df["eco_page_weight_mb"] = eco_df["eco_page_weight_bytes"] / 1_048_576


# ============================================================
# LOAD WC
# ============================================================

wc_rows = []
wc_map = wc.set_index("report_key")

for f in Path("data/websitecarbon").glob("*/page.json"):
    key = f.parent.name

    try:
        data = json.load(open(f))
        url = wc_map.loc[key, "url"] if key in wc_map.index else np.nan
        energy = data.get("energy", np.nan)
        grams = data.get("grams", np.nan)
    except Exception:
        url = np.nan
        energy = np.nan
        grams = np.nan

    wc_rows.append(
        {
            "url": url,
            "wc_id": key,
            "wc_grams": grams,
            "wc_energy_kwh": energy,
        }
    )

wc_df = pd.DataFrame(wc_rows)


# ============================================================
# LOAD GC
# ============================================================

gc_rows = []

for _, r in gc.iterrows():
    gc_rows.append(
        {
            "url": r["url"],
            "gm_id": r["report_id"],
            "gm_cpu_energy_kwh": r["cpu_energy_kwh"],
            "gm_page_weight_bytes": r["page_weight_bytes"],
        }
    )

gc_df = pd.DataFrame(gc_rows)

gc_df["gm_page_weight_mb"] = gc_df["gm_page_weight_bytes"] / 1_048_576


# ============================================================
# MERGE
# ============================================================

for df in (eco_df, wc_df, gc_df):
    df["url_key"] = df["url"].astype(str).apply(normalize)

canonical = eco_df.merge(wc_df, on="url_key", how="outer").merge(
    gc_df, on="url_key", how="outer"
)


# ============================================================
# GLOBAL + LOCAL STATS
# ============================================================

numeric_cols = [
    c for c in canonical.columns if pd.api.types.is_numeric_dtype(canonical[c])
]

global_mean = canonical[numeric_cols].mean()
global_std = canonical[numeric_cols].std()


subset_wc_ids = []

for md_file in Path("outlierAnalysis").glob("*.md"):
    text = md_file.read_text(encoding="utf-8")
    links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text)

    for k, v in links:
        if "Website Carbon" in k:
            subset_wc_ids.append(normalize(Path(v).parent.name))

subset_df = canonical[canonical["wc_id"].isin(subset_wc_ids)]

local_mean = subset_df[numeric_cols].mean()
local_std = subset_df[numeric_cols].std()


# ============================================================
# FORMATTING
# ============================================================


def fmt(val, f):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    try:
        return f.format(val)
    except Exception:
        return "N/A"


def build_table(r):

    def pack(metric):
        val = r.get(metric)
        return (
            val,
            global_mean.get(metric),
            global_std.get(metric),
            local_mean.get(metric),
            local_std.get(metric),
        )

    def line(val, g_mean, g_std, l_mean, l_std, f):
        return (
            fmt(val, f),
            f"μ {fmt(g_mean, f)} ± {fmt(g_std, f)}",
            f"μ {fmt(l_mean, f)} ± {fmt(l_std, f)}",
        )

    eco = line(*pack("eco_overall_score"), "{:.0f}")
    lh = line(*pack("eco_lh_perf"), "{:.0f}")
    la = line(*pack("eco_lh_acc"), "{:.0f}")
    re = line(*pack("eco_render_score"), "{:.0f}")
    em = line(*pack("eco_emissions_score"), "{:.4f}")
    wcg = line(*pack("wc_grams"), "{:.6f}")
    wck = line(*pack("wc_energy_kwh"), "{:.6f}")
    gmc = line(*pack("gm_cpu_energy_kwh"), "{:.6f}")
    eco_pw = line(*pack("eco_page_weight_mb"), "{:.2f}")
    gm_pw = line(*pack("gm_page_weight_mb"), "{:.2f}")

    return f"""
### Metrics
Emissions text from ecograder: {r["eco_emissions_text"]}

| Metric | Value | Global (μ ± σ) | Local (μ ± σ) |
|--------|-------|----------------|----------------|
| Ecograder Score | {eco[0]} | {eco[1]} | {eco[2]} |
| Lighthouse Performance | {lh[0]} | {lh[1]} | {lh[2]} |
| Lighthouse Accessibility | {la[0]} | {la[1]} | {la[2]} |
| Render Score | {re[0]} | {re[1]} | {re[2]} |
| Eco Emissions (g co2e) | {em[0]} | {em[1]} | {em[2]} |
| WC Emissions (g co2e) | {wcg[0]} | {wcg[1]} | {wcg[2]} |
| WC Energy (kWh) | {wck[0]} | {wck[1]} | {wck[2]} |
| GM CPU Energy (kWh) | {gmc[0]} | {gmc[1]} | {gmc[2]} |
| GM Page Weight (MB) | {gm_pw[0]} | {gm_pw[1]} | {gm_pw[2]} |
| Eco Page Weight (MB) | {eco_pw[0]} | {eco_pw[1]} | {eco_pw[2]} |
""".strip()


# ============================================================
# APPLY
# ============================================================


def replace_metrics(text, block):
    pattern = re.compile(r"### Metrics\s*\n.*?(?=\n### |\n# |\Z)", re.DOTALL)
    return pattern.sub(block, text) if pattern.search(text) else text + "\n\n" + block


for md_file in Path("outlierAnalysis").glob("*.md"):
    text = md_file.read_text(encoding="utf-8")

    links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text)

    wc_id = None
    for k, v in links:
        if "Website Carbon" in k:
            wc_id = normalize(Path(v).parent.name)

    if not wc_id:
        continue

    match = canonical[canonical["wc_id"] == wc_id]
    if match.empty:
        continue

    row = match.iloc[0]

    updated = replace_metrics(text, build_table(row))
    md_file.write_text(updated, encoding="utf-8")

    print(f"Updated {md_file.name}")
